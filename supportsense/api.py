from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from supportsense import __version__
from supportsense.agent import SupportAgent
from supportsense.analysis_persistence import (
    persist_analysis,
    persisted_analysis_chat,
    persisted_analysis_response,
)
from supportsense.audit import (
    persisted_audit_events,
    private_text_metadata,
    record_audit,
    redact_payload,
)
from supportsense.config import settings
from supportsense.conversations import conversation_service
from supportsense.dashboard import supervisor_dashboard
from supportsense.database import SessionFactory, create_development_schema, get_session
from supportsense.db_models import AgentVersion, Approval, Evaluation, ToolLog, now
from supportsense.errors import ServiceError
from supportsense.escalation import escalation_service
from supportsense.evaluation import run_agent_evaluation
from supportsense.knowledge import create_knowledge_source, list_knowledge_sources
from supportsense.memory import long_term_memory
from supportsense.models import (
    AgentChatRequest,
    AgentChatResponse,
    AgentVersionCreate,
    AgentVersionResponse,
    AnalysisResponse,
    ApprovalDecision,
    ApprovalResponse,
    AuthMeResponse,
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
    DashboardResponse,
    EscalationPackage,
    EscalationRequest,
    EvaluationResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    MemoryFactResponse,
    MemoryUpsert,
    MessageCreate,
    MessageResponse,
    TicketAssignment,
    TicketCreate,
    TicketResponse,
    ToolCallRequest,
    ToolCallResponse,
)
from supportsense.object_storage import object_storage
from supportsense.observability import (
    AGENT_OUTCOMES,
    ANALYSIS_ROWS,
    ESCALATIONS,
    HTTP_LATENCY,
    HTTP_REQUESTS,
    INFLIGHT_REQUESTS,
)
from supportsense.rate_limit import rate_limiter, request_identity
from supportsense.retrieval import ticket_documents
from supportsense.rollout import RolloutPolicy, RolloutStage
from supportsense.security import Principal, Role, authenticate, require_role
from supportsense.service import analysis_service
from supportsense.tickets import ticket_service
from supportsense.tooling import tool_executor
from supportsense.tracing import configure_error_monitoring
from supportsense.vector_store import vector_store

logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_error_monitoring()
    if settings.environment != "production":
        create_development_schema()
    yield


app = FastAPI(
    title="SupportSense API",
    version=__version__,
    description="Tenant-isolated support-ticket analytics and grounded follow-up answers.",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    remaining: int | None = None
    if request.url.path not in {
        "/health/live",
        "/health/ready",
        "/metrics",
        "/docs",
        "/openapi.json",
    }:
        try:
            allowed, remaining = rate_limiter.check(
                request_identity(
                    request.headers.get("Authorization"),
                    request.client.host if request.client else None,
                )
            )
        except Exception:
            if settings.environment == "production":
                return JSONResponse(
                    status_code=503,
                    content={
                        "code": "rate_limiter_unavailable",
                        "message": "The request safety service is unavailable.",
                        "request_id": request_id,
                    },
                    headers={"X-Request-ID": request_id},
                )
            allowed, remaining = True, settings.rate_limit_per_minute
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limit_exceeded",
                    "message": "Too many requests. Try again later.",
                    "request_id": request_id,
                },
                headers={
                    "X-Request-ID": request_id,
                    "Retry-After": "60",
                    "X-RateLimit-Remaining": "0",
                },
            )
    started = time.perf_counter()
    INFLIGHT_REQUESTS.inc()
    try:
        response = await call_next(request)
    finally:
        INFLIGHT_REQUESTS.dec()
    route = getattr(request.scope.get("route"), "path", "unmatched")
    elapsed = time.perf_counter() - started
    HTTP_REQUESTS.labels(route, request.method, str(response.status_code)).inc()
    HTTP_LATENCY.labels(route, request.method).observe(elapsed)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{elapsed * 1000:.1f}"
    response.headers["Cache-Control"] = "no-store"
    if remaining is not None:
        response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    _audit_request_error(request, exc.code, exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("supportsense").exception("Unhandled request error")
    _audit_request_error(request, "internal_error", 500)
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/health/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise ServiceError("database_unavailable", "Database is unavailable.", 503) from exc
    if not rate_limiter.ready():
        raise ServiceError(
            "rate_limiter_unavailable",
            "Redis rate limiter is unavailable.",
            503,
        )
    if vector_store.enabled and not vector_store.ready():
        raise ServiceError(
            "vector_store_unavailable",
            "Vector retrieval is unavailable.",
            503,
        )
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/analyses", response_model=AnalysisResponse, status_code=201)
@app.post(
    "/v1/analyses",
    response_model=AnalysisResponse,
    status_code=201,
    deprecated=True,
    include_in_schema=False,
)
def create_analysis(
    request: Request,
    content: bytes = Body(media_type="text/csv"),
    filename: str = Header(default="tickets.csv", alias="X-Filename"),
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> AnalysisResponse:
    require_role(principal, Role.ANALYST)
    record = analysis_service.analyze_csv(
        tenant_id=principal.tenant_id, filename=filename, content=content
    )
    object_uri = object_storage.store_csv(
        tenant_id=principal.tenant_id,
        analysis_id=record.analysis_id,
        filename=record.filename,
        content=content,
        content_sha256=record.content_sha256,
    )
    persist_analysis(
        session,
        principal,
        record,
        object_uri=object_uri,
    )
    vector_store.index_documents(
        principal.tenant_id,
        f"analysis:{record.analysis_id}",
        ticket_documents(record.dataframe),
    )
    ANALYSIS_ROWS.observe(len(record.dataframe))
    record_audit(
        session,
        event_type="analysis.created",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=record.analysis_id,
        attributes={
            "filename": record.filename,
            "row_count": len(record.dataframe),
            "content_sha256": record.content_sha256,
        },
    )
    return analysis_service.response(record)


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResponse)
@app.get(
    "/v1/analyses/{analysis_id}",
    response_model=AnalysisResponse,
    deprecated=True,
    include_in_schema=False,
)
def get_analysis(
    request: Request,
    analysis_id: str,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> AnalysisResponse:
    require_role(principal, Role.AGENT)
    response = persisted_analysis_response(
        session,
        principal.tenant_id,
        analysis_id,
    )
    record_audit(
        session,
        event_type="analysis.viewed",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=analysis_id,
    )
    return response


@app.post("/api/v1/analyses/{analysis_id}/chat", response_model=ChatResponse)
@app.post(
    "/v1/analyses/{analysis_id}/chat",
    response_model=ChatResponse,
    deprecated=True,
    include_in_schema=False,
)
def chat(
    request: Request,
    analysis_id: str,
    payload: ChatRequest,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> ChatResponse:
    require_role(principal, Role.AGENT)
    response = persisted_analysis_chat(
        session,
        principal.tenant_id,
        analysis_id,
        payload.question,
    )
    record_audit(
        session,
        event_type="chat.answered",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=analysis_id,
        attributes={
            **private_text_metadata(payload.question),
            "method": response.method,
            "citation_count": len(response.ticket_ids),
        },
    )
    return response


@app.get("/api/v1/admin/audit-events", tags=["admin"])
@app.get("/v1/audit-events", deprecated=True, include_in_schema=False)
def list_audit_events(
    principal: Principal = Depends(authenticate),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    require_role(principal, Role.SUPERVISOR)
    return persisted_audit_events(session, principal.tenant_id, limit)


@app.post(
    "/api/v1/conversations",
    response_model=ConversationResponse,
    status_code=201,
    tags=["conversations"],
)
def create_conversation(
    request: Request,
    payload: ConversationCreate,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> ConversationResponse:
    conversation = conversation_service.create(
        session,
        principal,
        analysis_id=payload.analysis_id,
        channel=payload.channel,
    )
    record_audit(
        session,
        event_type="conversation.created",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=conversation.id,
        attributes={"channel": conversation.channel},
    )
    return conversation_service.response(conversation)


@app.get(
    "/api/v1/conversations",
    response_model=list[ConversationResponse],
    tags=["conversations"],
)
def list_conversations(
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ConversationResponse]:
    return [
        conversation_service.response(conversation)
        for conversation in conversation_service.list(
            session, principal, limit=limit
        )
    ]


@app.get(
    "/api/v1/conversations/{conversation_id}",
    response_model=ConversationDetail,
    tags=["conversations"],
)
def get_conversation(
    conversation_id: str,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> ConversationDetail:
    return conversation_service.detail(session, principal, conversation_id)


@app.post(
    "/api/v1/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    tags=["conversations"],
)
def add_conversation_message(
    request: Request,
    conversation_id: str,
    payload: MessageCreate,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> MessageResponse:
    message = conversation_service.add_message(
        session,
        principal,
        conversation_id,
        role="user",
        content=payload.content,
    )
    record_audit(
        session,
        event_type="conversation.message.created",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=conversation_id,
        attributes=private_text_metadata(payload.content),
    )
    return conversation_service.message_response(message)


@app.post(
    "/api/v1/conversations/{conversation_id}/tools/{tool_name}",
    response_model=ToolCallResponse,
    tags=["tools"],
)
def execute_tool(
    request: Request,
    conversation_id: str,
    tool_name: str,
    payload: ToolCallRequest,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> ToolCallResponse:
    conversation_service.get(session, principal, conversation_id)
    result = tool_executor.execute(
        session,
        principal,
        conversation_id=conversation_id,
        tool_name=tool_name,
        arguments=payload.arguments,
        idempotency_key=payload.idempotency_key,
        approval_id=payload.approval_id,
    )
    tool_log = session.get(ToolLog, result.tool_log_id)
    record_audit(
        session,
        event_type="tool.executed",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=result.tool_log_id,
        outcome=result.status,
        attributes={
            "tool_name": tool_name,
            "risk_level": result.risk_level,
            "approval_id": result.approval_id,
            "error_code": result.error_code,
            "arguments": redact_payload(tool_log.arguments if tool_log else {}),
            "result": redact_payload(tool_log.result if tool_log else None),
            "latency_ms": tool_log.latency_ms if tool_log else None,
        },
    )
    return ToolCallResponse(**result.__dict__)


@app.post(
    "/api/v1/approvals/{approval_id}/decision",
    response_model=ApprovalResponse,
    tags=["approvals"],
)
def decide_approval(
    request: Request,
    approval_id: str,
    payload: ApprovalDecision,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> ApprovalResponse:
    approval = tool_executor.decide_approval(
        session,
        principal,
        approval_id,
        approved=payload.approved,
        reason=payload.reason,
    )
    record_audit(
        session,
        event_type="approval.decided",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=approval.id,
        outcome=approval.status,
        attributes={
            "tool_name": approval.tool_name,
            "requested_arguments": redact_payload(approval.requested_arguments),
            "decision": approval.status,
            "reason": redact_payload(approval.reason),
        },
    )
    return ApprovalResponse(
        approval_id=approval.id,
        status=approval.status,
        tool_name=approval.tool_name,
        conversation_id=approval.conversation_id,
        decided_by=approval.decided_by,
        requested_arguments=approval.requested_arguments,
        requested_by=approval.requested_by,
        reason=approval.reason,
        created_at=approval.created_at,
    )


@app.get(
    "/api/v1/approvals",
    response_model=list[ApprovalResponse],
    tags=["approvals"],
)
def list_approvals(
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
    status: str = Query(default="pending", pattern=r"^(pending|approved|denied|all)$"),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ApprovalResponse]:
    require_role(principal, Role.AGENT)
    statement = select(Approval).where(Approval.tenant_id == principal.tenant_id)
    if status != "all":
        statement = statement.where(Approval.status == status)
    approvals = session.scalars(
        statement.order_by(Approval.created_at.desc()).limit(limit)
    ).all()
    return [
        ApprovalResponse(
            approval_id=approval.id,
            status=approval.status,
            tool_name=approval.tool_name,
            conversation_id=approval.conversation_id,
            decided_by=approval.decided_by,
            requested_arguments=approval.requested_arguments,
            requested_by=approval.requested_by,
            reason=approval.reason,
            created_at=approval.created_at,
        )
        for approval in approvals
    ]


@app.post(
    "/api/v1/chat",
    response_model=AgentChatResponse,
    tags=["agent"],
)
def agent_chat(
    request: Request,
    payload: AgentChatRequest,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> AgentChatResponse:
    if payload.conversation_id:
        conversation = conversation_service.get(
            session, principal, payload.conversation_id
        )
    else:
        conversation = conversation_service.create(
            session, principal, analysis_id=None, channel="web"
        )
    rollout, agent_version = _tenant_rollout(session, principal.tenant_id)
    result = SupportAgent(session, principal, rollout).run(
        conversation_id=conversation.id,
        question=payload.message,
        idempotency_key=payload.idempotency_key,
    )
    if result.get("escalated"):
        escalation_service.escalate(
            session,
            principal,
            conversation.id,
            reason=result.get("escalation_reason") or "agent_escalation",
        )
        ESCALATIONS.labels(result.get("escalation_reason") or "agent_escalation").inc()
    AGENT_OUTCOMES.labels(
        result.get("intent", "unknown"),
        _agent_outcome(result),
    ).inc()
    tool_result = result.get("tool_result")
    record_audit(
        session,
        event_type="agent.response.created",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=conversation.id,
        outcome=_agent_outcome(result),
        attributes={
            **private_text_metadata(payload.message),
            "prompt_message_id": result.get("user_message_id"),
            "response_message_id": result.get("assistant_message_id"),
            "agent_version_id": agent_version.id if agent_version else None,
            "agent_version": agent_version.version if agent_version else None,
            "prompt_version": (
                agent_version.prompt_version
                if agent_version
                else "supportsense-agent-v2"
            ),
            "rollout_stage": rollout.stage.value,
            "intent": result.get("intent"),
            "citation_count": len(result.get("citations", [])),
            "retrieved_references": result.get("citations", []),
            "retrieval_confidence": result.get("retrieval_confidence"),
            "tool_name": tool_result.tool_name if tool_result else None,
            "tool_status": tool_result.status if tool_result else None,
            "escalation_reason": result.get("escalation_reason"),
        },
    )
    expose_internal = principal.role != Role.CUSTOMER or rollout.customer_visible
    return AgentChatResponse(
        conversation_id=conversation.id,
        answer=(
            result["answer"]
            if expose_internal
            else "Your request was received and will be reviewed by support."
        ),
        intent=result.get("intent", "unknown"),
        citations=result.get("citations", []) if expose_internal else [],
        escalated=bool(result.get("escalated")),
        escalation_reason=result.get("escalation_reason"),
        tool_call=(
            ToolCallResponse(**tool_result.__dict__)
            if tool_result and expose_internal
            else None
        ),
        mode=rollout.stage.value,
        requires_agent_review=(
            not rollout.customer_visible
            or bool(tool_result and tool_result.status == "approval_required")
        ),
        customer_visible=rollout.customer_visible,
        confidence=_agent_confidence(result) if expose_internal else None,
        tool_suggestion=result.get("tool_name") if expose_internal else None,
    )


@app.post(
    "/api/v1/agent-assist",
    response_model=AgentChatResponse,
    tags=["agent-assist"],
)
def agent_assist(
    request: Request,
    payload: AgentChatRequest,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> AgentChatResponse:
    require_role(principal, Role.AGENT)
    if payload.conversation_id:
        conversation = conversation_service.get(
            session, principal, payload.conversation_id
        )
    else:
        conversation = conversation_service.create(
            session, principal, analysis_id=None, channel="agent_assist"
        )
    policy = RolloutPolicy(RolloutStage.AGENT_ASSIST)
    result = SupportAgent(session, principal, policy).run(
        conversation_id=conversation.id,
        question=payload.message,
        idempotency_key=payload.idempotency_key,
    )
    tool_result = result.get("tool_result")
    record_audit(
        session,
        event_type="agent_assist.suggestion.created",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=conversation.id,
        outcome="suggested",
        attributes={
            **private_text_metadata(payload.message),
            "prompt_message_id": result.get("user_message_id"),
            "response_message_id": result.get("assistant_message_id"),
            "intent": result.get("intent"),
            "tool_name": result.get("tool_name"),
            "tool_executed": bool(tool_result),
        },
    )
    return AgentChatResponse(
        conversation_id=conversation.id,
        answer=result["answer"],
        intent=result.get("intent", "unknown"),
        citations=result.get("citations", []),
        escalated=bool(result.get("escalated")),
        escalation_reason=result.get("escalation_reason"),
        tool_call=ToolCallResponse(**tool_result.__dict__) if tool_result else None,
        mode="agent_assist",
        requires_agent_review=True,
        customer_visible=False,
        confidence=_agent_confidence(result),
        tool_suggestion=result.get("tool_name"),
    )


@app.post(
    "/api/v1/conversations/{conversation_id}/escalate",
    response_model=EscalationPackage,
    tags=["escalations"],
)
def escalate_conversation(
    request: Request,
    conversation_id: str,
    payload: EscalationRequest,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> EscalationPackage:
    package = escalation_service.escalate(
        session, principal, conversation_id, reason=payload.reason
    )
    ESCALATIONS.labels(payload.reason[:80]).inc()
    record_audit(
        session,
        event_type="conversation.escalated",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=conversation_id,
        outcome="human_handoff",
        attributes={
            "ticket_id": package.ticket_id,
            "reason": payload.reason,
            "tool_count": len(package.tool_history),
        },
    )
    return package


@app.get(
    "/api/v1/admin/dashboard",
    response_model=DashboardResponse,
    tags=["admin"],
)
def admin_dashboard(
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> DashboardResponse:
    require_role(principal, Role.SUPERVISOR)
    return supervisor_dashboard(session, principal.tenant_id)


@app.get(
    "/api/v1/admin/agent-versions",
    response_model=list[AgentVersionResponse],
    tags=["admin"],
)
def list_agent_versions(
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> list[AgentVersionResponse]:
    require_role(principal, Role.SUPERVISOR)
    versions = session.scalars(
        select(AgentVersion)
        .where(AgentVersion.tenant_id == principal.tenant_id)
        .order_by(AgentVersion.created_at.desc())
    ).all()
    return [_agent_version_response(version) for version in versions]


@app.post(
    "/api/v1/admin/agent-versions",
    response_model=AgentVersionResponse,
    status_code=201,
    tags=["admin"],
)
def create_agent_version(
    request: Request,
    payload: AgentVersionCreate,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> AgentVersionResponse:
    require_role(principal, Role.ADMIN)
    conversation_service.ensure_identity(session, principal)
    existing = session.scalar(
        select(AgentVersion).where(
            AgentVersion.tenant_id == principal.tenant_id,
            AgentVersion.name == payload.name,
            AgentVersion.version == payload.version,
        )
    )
    if existing:
        raise ServiceError(
            "agent_version_exists",
            "This agent version already exists.",
            409,
        )
    if payload.active:
        for version in session.scalars(
            select(AgentVersion).where(
                AgentVersion.tenant_id == principal.tenant_id,
            )
        ).all():
            version.active = False
    version = AgentVersion(
        tenant_id=principal.tenant_id,
        name=payload.name,
        version=payload.version,
        prompt_version=payload.prompt_version,
        model_config=payload.model_settings,
        tool_policy=payload.tool_policy,
        rollout_stage=payload.rollout_stage,
        active=payload.active,
    )
    session.add(version)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ServiceError(
            "agent_version_exists",
            "This agent version already exists for the tenant.",
            409,
        ) from exc
    record_audit(
        session,
        event_type="agent_version.created",
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        request_id=request.state.request_id,
        resource_id=version.id,
        outcome="activated" if version.active else "registered",
        attributes={
            "name": version.name,
            "version": version.version,
            "prompt_version": version.prompt_version,
            "rollout_stage": version.rollout_stage,
            "active": version.active,
        },
    )
    return _agent_version_response(version)


@app.get("/api/v1/auth/me", response_model=AuthMeResponse, tags=["auth"])
def auth_me(principal: Principal = Depends(authenticate)) -> AuthMeResponse:
    return AuthMeResponse(
        subject=principal.subject,
        tenant_id=principal.tenant_id,
        role=principal.role.value,
    )


@app.get(
    "/api/v1/tickets",
    response_model=list[TicketResponse],
    tags=["tickets"],
)
def list_tickets(
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[TicketResponse]:
    return [
        ticket_service.response(ticket)
        for ticket in ticket_service.list(session, principal, limit=limit)
    ]


@app.post(
    "/api/v1/tickets",
    response_model=TicketResponse,
    status_code=201,
    tags=["tickets"],
)
def create_ticket(
    payload: TicketCreate,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> TicketResponse:
    return ticket_service.response(ticket_service.create(session, principal, payload))


@app.patch(
    "/api/v1/tickets/{ticket_id}/assignment",
    response_model=TicketResponse,
    tags=["tickets"],
)
def assign_ticket(
    ticket_id: str,
    payload: TicketAssignment,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> TicketResponse:
    return ticket_service.response(
        ticket_service.assign(session, principal, ticket_id, payload)
    )


@app.get(
    "/api/v1/tickets/{ticket_id}",
    response_model=TicketResponse,
    tags=["tickets"],
)
def get_ticket(
    ticket_id: str,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> TicketResponse:
    return ticket_service.response(
        ticket_service.get(session, principal, ticket_id)
    )


@app.post(
    "/api/v1/evals/run",
    response_model=EvaluationResponse,
    tags=["evaluations"],
)
def run_evaluations(
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> EvaluationResponse:
    require_role(principal, Role.SUPERVISOR)
    conversation_service.ensure_identity(session, principal)
    active_version = _active_agent_version(session, principal.tenant_id)
    result = run_agent_evaluation()
    evaluation = Evaluation(
        tenant_id=principal.tenant_id,
        agent_version_id=active_version.id if active_version else None,
        suite=result["suite"],
        status="passed" if result["passed"] else "failed",
        metrics={**result["metrics"], "gates": result["gates"]},
        cases=result["results"],
        completed_at=now(),
    )
    session.add(evaluation)
    session.commit()
    return EvaluationResponse(
        evaluation_id=evaluation.id,
        suite=evaluation.suite,
        status=evaluation.status,
        passed=result["passed"],
        metrics=result["metrics"],
        gates=result["gates"],
    )


@app.put(
    "/api/v1/memory",
    response_model=MemoryFactResponse,
    tags=["memory"],
)
def remember_customer_preference(
    payload: MemoryUpsert,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> MemoryFactResponse:
    fact = long_term_memory.remember(
        session,
        principal,
        key=payload.key,
        value=payload.value,
        conversation_id=payload.conversation_id,
    )
    return MemoryFactResponse(
        key=fact.key,
        value=fact.value,
        confidence=fact.confidence,
        updated_at=fact.updated_at,
    )


@app.get(
    "/api/v1/memory",
    response_model=list[MemoryFactResponse],
    tags=["memory"],
)
def list_customer_memory(
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> list[MemoryFactResponse]:
    return long_term_memory.list(session, principal)


@app.post(
    "/api/v1/knowledge-sources",
    response_model=KnowledgeSourceResponse,
    status_code=201,
    tags=["knowledge"],
)
def add_knowledge_source(
    payload: KnowledgeSourceCreate,
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> KnowledgeSourceResponse:
    require_role(principal, Role.AGENT)
    source = create_knowledge_source(session, principal, payload)
    return KnowledgeSourceResponse(
        source_id=source.id,
        title=source.title,
        uri=source.uri,
        status=source.status,
        content_sha256=source.content_sha256,
        metadata=source.metadata_json or {},
    )


@app.get(
    "/api/v1/knowledge-sources",
    response_model=list[KnowledgeSourceResponse],
    tags=["knowledge"],
)
def get_knowledge_sources(
    principal: Principal = Depends(authenticate),
    session: Session = Depends(get_session),
) -> list[KnowledgeSourceResponse]:
    require_role(principal, Role.AGENT)
    return list_knowledge_sources(session, principal)


def _agent_confidence(result: dict) -> float | None:
    if result.get("retrieval_confidence") is not None:
        return float(result["retrieval_confidence"])
    tool = result.get("tool_result")
    if tool and tool.status in {"succeeded", "approval_required"}:
        return 1.0
    if result.get("escalated"):
        return 0.0
    return 0.5


def _agent_outcome(result: dict) -> str:
    if result.get("escalated"):
        return "escalated"
    tool = result.get("tool_result")
    return tool.status if tool else "answered"


def _active_agent_version(
    session: Session,
    tenant_id: str,
) -> AgentVersion | None:
    return session.scalar(
        select(AgentVersion)
        .where(
            AgentVersion.tenant_id == tenant_id,
            AgentVersion.active.is_(True),
        )
        .order_by(AgentVersion.created_at.desc(), AgentVersion.id.desc())
        .limit(1)
    )


def _tenant_rollout(
    session: Session,
    tenant_id: str,
) -> tuple[RolloutPolicy, AgentVersion | None]:
    version = _active_agent_version(session, tenant_id)
    if version is None:
        return RolloutPolicy.current(), None
    try:
        return RolloutPolicy.effective(version.rollout_stage), version
    except ValueError as exc:
        raise ServiceError(
            "invalid_agent_configuration",
            "The active agent version has an invalid rollout stage.",
            503,
        ) from exc


def _agent_version_response(version: AgentVersion) -> AgentVersionResponse:
    return AgentVersionResponse(
        agent_version_id=version.id,
        name=version.name,
        version=version.version,
        prompt_version=version.prompt_version,
        model_settings=version.model_config or {},
        tool_policy=version.tool_policy or {},
        rollout_stage=version.rollout_stage,
        active=version.active,
        created_at=version.created_at,
    )


def _audit_request_error(request: Request, code: str, status_code: int) -> None:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return
    try:
        with SessionFactory() as session:
            record_audit(
                session,
                event_type="request.error",
                tenant_id=principal.tenant_id,
                actor_id=principal.subject,
                request_id=getattr(request.state, "request_id", "unknown"),
                outcome="error",
                attributes={
                    "code": code,
                    "status_code": status_code,
                    "path": request.url.path,
                    "method": request.method,
                },
            )
    except Exception:
        logging.getLogger("supportsense.audit").exception(
            "Could not persist request error audit event"
        )
