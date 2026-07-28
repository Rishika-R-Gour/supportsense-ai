from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from supportsense.config import settings
from supportsense.db_models import Approval, ToolLog
from supportsense.errors import ServiceError
from supportsense.observability import (
    CIRCUIT_BREAKER_REJECTIONS,
    CIRCUIT_BREAKER_STATE,
    TOOL_EXECUTIONS,
    TOOL_RETRIES,
)
from supportsense.resilience import CircuitBreaker, CircuitOpenError, CircuitState
from supportsense.rollout import RolloutPolicy
from supportsense.security import Principal, Role, require_role


class RiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    SENSITIVE = "sensitive"


class ToolFailure(RuntimeError):
    code = "tool_failure"
    retryable = False


class TransientToolFailure(ToolFailure):
    code = "tool_temporarily_unavailable"
    retryable = True


class CircuitOpenToolFailure(ToolFailure):
    code = "tool_circuit_open"
    retryable = False


class InvalidToolResponseFailure(ToolFailure):
    code = "invalid_tool_response"
    retryable = False


class CustomerArgs(BaseModel):
    customer_id: str = Field(min_length=1, max_length=255)


class EntityArgs(CustomerArgs):
    entity_id: str = Field(min_length=1, max_length=255)


class RecentTransactionsArgs(CustomerArgs):
    limit: int = Field(default=10, ge=1, le=50)


class TicketArgs(CustomerArgs):
    subject: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=3, max_length=4_000)
    priority: str = Field(default="Medium", pattern=r"^(Low|Medium|High|Critical)$")


class EscalateTicketArgs(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=3, max_length=1_000)


class UpdateEmailArgs(CustomerArgs):
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )


class RefundArgs(CustomerArgs):
    payment_id: str = Field(min_length=1, max_length=255)
    amount_cents: int = Field(gt=0, le=1_000_000)
    reason: str = Field(min_length=3, max_length=500)


class CancelSubscriptionArgs(CustomerArgs):
    subscription_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=3, max_length=500)


class UpdateBillingArgs(CustomerArgs):
    payment_method_token: str = Field(min_length=8, max_length=500)


class DeleteAccountArgs(CustomerArgs):
    confirmation: str = Field(pattern=r"^DELETE$")


class StrictToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomerResult(StrictToolResult):
    customer_id: str
    name: str
    email: str
    plan: str


class EntityResult(StrictToolResult):
    id: str
    customer_id: str
    status: str
    sandbox: bool | None = None


class TransactionResult(StrictToolResult):
    payment_id: str
    amount_cents: int = Field(ge=0)
    status: str


class RecentTransactionsResult(StrictToolResult):
    transactions: list[TransactionResult]


class TicketResult(StrictToolResult):
    ticket_id: str
    status: str


class UpdateEmailResult(StrictToolResult):
    customer_id: str
    updated: bool


class ResendInvoiceResult(StrictToolResult):
    invoice_id: str
    delivery_status: str


class RefundResult(StrictToolResult):
    refund_id: str
    payment_id: str
    amount_cents: int = Field(gt=0)
    status: str


class CancelSubscriptionResult(StrictToolResult):
    subscription_id: str
    status: str


class UpdateBillingResult(StrictToolResult):
    customer_id: str
    billing_updated: bool


class DeleteAccountResult(StrictToolResult):
    customer_id: str
    deletion_status: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: RiskLevel
    arguments_model: type[BaseModel]
    minimum_role: Role
    redact_fields: frozenset[str] = frozenset()


TOOL_SPECS = {
    spec.name: spec
    for spec in [
        ToolSpec("get_customer", "Get a customer profile.", RiskLevel.READ, CustomerArgs, Role.VIEWER),
        ToolSpec("get_invoice", "Get one invoice.", RiskLevel.READ, EntityArgs, Role.VIEWER),
        ToolSpec("get_subscription", "Get one subscription.", RiskLevel.READ, EntityArgs, Role.VIEWER),
        ToolSpec("get_payment", "Get one payment.", RiskLevel.READ, EntityArgs, Role.VIEWER),
        ToolSpec("refund_status", "Check refund status.", RiskLevel.READ, EntityArgs, Role.VIEWER),
        ToolSpec(
            "recent_transactions",
            "List recent transactions.",
            RiskLevel.READ,
            RecentTransactionsArgs,
            Role.VIEWER,
        ),
        ToolSpec("create_ticket", "Create a support ticket.", RiskLevel.WRITE, TicketArgs, Role.ANALYST),
        ToolSpec(
            "escalate_ticket",
            "Escalate an existing ticket.",
            RiskLevel.WRITE,
            EscalateTicketArgs,
            Role.ANALYST,
        ),
        ToolSpec(
            "update_email",
            "Update a customer email.",
            RiskLevel.WRITE,
            UpdateEmailArgs,
            Role.ANALYST,
            frozenset({"email"}),
        ),
        ToolSpec("resend_invoice", "Resend an invoice.", RiskLevel.WRITE, EntityArgs, Role.ANALYST),
        ToolSpec(
            "refund_customer",
            "Issue a customer refund.",
            RiskLevel.SENSITIVE,
            RefundArgs,
            Role.ANALYST,
        ),
        ToolSpec(
            "cancel_subscription",
            "Cancel a subscription.",
            RiskLevel.SENSITIVE,
            CancelSubscriptionArgs,
            Role.ANALYST,
        ),
        ToolSpec(
            "update_billing",
            "Replace billing credentials.",
            RiskLevel.SENSITIVE,
            UpdateBillingArgs,
            Role.ANALYST,
            frozenset({"payment_method_token"}),
        ),
        ToolSpec(
            "delete_account",
            "Permanently delete an account.",
            RiskLevel.SENSITIVE,
            DeleteAccountArgs,
            Role.ADMIN,
        ),
    ]
}

TOOL_RESULT_MODELS: dict[str, type[BaseModel]] = {
    "get_customer": CustomerResult,
    "get_invoice": EntityResult,
    "get_subscription": EntityResult,
    "get_payment": EntityResult,
    "refund_status": EntityResult,
    "recent_transactions": RecentTransactionsResult,
    "create_ticket": TicketResult,
    "escalate_ticket": TicketResult,
    "update_email": UpdateEmailResult,
    "resend_invoice": ResendInvoiceResult,
    "refund_customer": RefundResult,
    "cancel_subscription": CancelSubscriptionResult,
    "update_billing": UpdateBillingResult,
    "delete_account": DeleteAccountResult,
}


class SupportBackend:
    """Adapter boundary for Stripe, billing, CRM, and ticket providers."""

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        raise NotImplementedError


class SandboxSupportBackend(SupportBackend):
    """Deterministic sandbox used in local demos and automated evaluations."""

    def __init__(self) -> None:
        self.customers = {
            "cus_demo": {
                "customer_id": "cus_demo",
                "name": "Northstar Labs",
                "email": "billing@northstar.example",
                "plan": "Enterprise",
            }
        }
        self.executions: dict[str, int] = {}

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        self.executions[tool_name] = self.executions.get(tool_name, 0) + 1
        customer_id = arguments.get("customer_id")
        if customer_id and customer_id not in self.customers:
            raise ToolFailure("Customer not found")
        if tool_name == "get_customer":
            return dict(self.customers[customer_id])
        if tool_name == "recent_transactions":
            return {
                "transactions": [
                    {"payment_id": "pay_demo", "amount_cents": 9900, "status": "succeeded"}
                ][: arguments["limit"]]
            }
        if tool_name in {"get_invoice", "get_subscription", "get_payment", "refund_status"}:
            status = {
                "get_invoice": "open",
                "get_subscription": "active",
                "get_payment": "succeeded",
                "refund_status": "submitted",
            }[tool_name]
            return {
                "id": arguments["entity_id"],
                "customer_id": customer_id,
                "status": status,
                "sandbox": True,
            }
        if tool_name == "create_ticket":
            return {"ticket_id": f"TCK-{uuid4().hex[:8].upper()}", "status": "open"}
        if tool_name == "escalate_ticket":
            return {"ticket_id": arguments["ticket_id"], "status": "escalated"}
        if tool_name == "update_email":
            self.customers[customer_id]["email"] = arguments["email"]
            return {"customer_id": customer_id, "updated": True}
        if tool_name == "resend_invoice":
            return {"invoice_id": arguments["entity_id"], "delivery_status": "queued"}
        if tool_name == "refund_customer":
            return {
                "refund_id": f"re_{uuid4().hex[:12]}",
                "payment_id": arguments["payment_id"],
                "amount_cents": arguments["amount_cents"],
                "status": "submitted",
            }
        if tool_name == "cancel_subscription":
            return {"subscription_id": arguments["subscription_id"], "status": "cancelled"}
        if tool_name == "update_billing":
            return {"customer_id": customer_id, "billing_updated": True}
        if tool_name == "delete_account":
            return {"customer_id": customer_id, "deletion_status": "scheduled"}
        raise ToolFailure("Tool is not implemented")


class DisabledSupportBackend(SupportBackend):
    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        failure = ToolFailure("Production tool gateway is not configured")
        failure.code = "tool_gateway_not_configured"
        raise failure


class HttpSupportBackend(SupportBackend):
    """Authenticated adapter for an internal Stripe/CRM/ticket tool gateway."""

    def __init__(self, base_url: str, token: str, timeout_seconds: float = 4) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/v1/tools/{tool_name}",
            data=json.dumps({"arguments": arguments}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
                "X-Tenant-ID": tenant_id,
                "User-Agent": "SupportSense/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                raise TransientToolFailure(f"Tool gateway HTTP {exc.code}") from exc
            failure = ToolFailure(f"Tool gateway HTTP {exc.code}")
            failure.code = "tool_gateway_rejected"
            raise failure from exc
        except (URLError, TimeoutError) as exc:
            raise TransientToolFailure("Tool gateway unavailable") from exc
        except json.JSONDecodeError as exc:
            failure = ToolFailure("Tool gateway returned invalid JSON")
            failure.code = "invalid_tool_response"
            raise failure from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
            failure = ToolFailure("Tool gateway response has an invalid schema")
            failure.code = "invalid_tool_response"
            raise failure
        return payload["result"]


@dataclass(frozen=True)
class ToolResult:
    tool_log_id: str
    tool_name: str
    status: str
    risk_level: str
    result: dict[str, Any] | None = None
    approval_id: str | None = None
    error_code: str | None = None


class ToolExecutor:
    def __init__(
        self,
        backend: SupportBackend,
        *,
        timeout_seconds: float = 5,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        circuit_breaker: CircuitBreaker | None = None,
        dependency_name: str = "support_tool_gateway",
    ) -> None:
        self.backend = backend
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.dependency_name = dependency_name
        self._publish_circuit_state()

    def execute(
        self,
        session: Session,
        principal: Principal,
        *,
        conversation_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        approval_id: str | None = None,
        rollout_policy: RolloutPolicy | None = None,
    ) -> ToolResult:
        spec = TOOL_SPECS.get(tool_name)
        if spec is None:
            raise ServiceError("unknown_tool", "The requested tool is not allowed.", 400)
        require_role(principal, spec.minimum_role)
        (rollout_policy or RolloutPolicy.current()).enforce_tool(spec.risk.value)
        if not idempotency_key or len(idempotency_key) > 128:
            raise ServiceError(
                "invalid_idempotency_key",
                "A stable idempotency key of at most 128 characters is required.",
            )
        try:
            validated = spec.arguments_model.model_validate(arguments).model_dump(mode="json")
        except ValidationError as exc:
            raise ServiceError("invalid_tool_arguments", str(exc)) from exc
        if (
            principal.role == Role.CUSTOMER
            and validated.get("customer_id") != principal.subject
        ):
            raise ServiceError(
                "permission_denied",
                "Customers may only access their own support records.",
                403,
            )

        existing = session.scalar(
            select(ToolLog).where(
                ToolLog.tenant_id == principal.tenant_id,
                ToolLog.idempotency_key == idempotency_key,
            )
        )
        if existing and (
            existing.conversation_id != conversation_id
            or existing.tool_name != tool_name
            or existing.arguments != self._redact(validated, spec)
        ):
            raise ServiceError(
                "idempotency_conflict",
                "The idempotency key was already used for a different operation.",
                409,
            )
        if existing and existing.status != "approval_required":
            return self._result(existing)
        if existing and existing.status == "approval_required" and not approval_id:
            return self._result(existing)

        approval = None
        if spec.risk == RiskLevel.SENSITIVE:
            if approval_id:
                approval = session.scalar(
                    select(Approval).where(
                        Approval.id == approval_id,
                        Approval.tenant_id == principal.tenant_id,
                        Approval.conversation_id == conversation_id,
                        Approval.tool_name == tool_name,
                    )
                )
                if approval is None:
                    raise ServiceError(
                        "approval_not_found",
                        "Approval not found.",
                        404,
                    )
                if approval.status == "denied":
                    raise ServiceError(
                        "approval_denied",
                        "The sensitive action was denied.",
                        409,
                    )
            if approval is None or approval.status != "approved":
                if approval is None:
                    approval = Approval(
                        tenant_id=principal.tenant_id,
                        conversation_id=conversation_id,
                        tool_name=tool_name,
                        requested_arguments=self._redact(validated, spec),
                        requested_by=principal.subject,
                    )
                    session.add(approval)
                    session.flush()
                log = existing or ToolLog(
                    tenant_id=principal.tenant_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                    risk_level=spec.risk.value,
                    arguments=self._redact(validated, spec),
                    status="approval_required",
                    idempotency_key=idempotency_key,
                )
                log.approval_id = approval.id
                session.add(log)
                session.commit()
                return self._observed_result(log)

        log = existing or ToolLog(
            tenant_id=principal.tenant_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            risk_level=spec.risk.value,
            arguments=self._redact(validated, spec),
            status="running",
            idempotency_key=idempotency_key,
        )
        log.status = "running"
        if approval:
            log.approval_id = approval.id
        session.add(log)
        session.flush()

        started = time.perf_counter()
        try:
            result = self._execute_with_resilience(
                tool_name,
                validated,
                idempotency_key,
                principal.tenant_id,
            )
            log.result = validate_tool_result(tool_name, result)
            log.status = "succeeded"
        except ToolFailure as exc:
            log.status = "failed"
            log.error_code = exc.code
        finally:
            log.latency_ms = (time.perf_counter() - started) * 1000
            session.commit()
        return self._observed_result(log)

    def decide_approval(
        self,
        session: Session,
        principal: Principal,
        approval_id: str,
        *,
        approved: bool,
        reason: str | None,
    ) -> Approval:
        require_role(principal, Role.SUPERVISOR)
        approval = session.scalar(
            select(Approval).where(
                Approval.id == approval_id,
                Approval.tenant_id == principal.tenant_id,
            )
        )
        if approval is None:
            raise ServiceError("approval_not_found", "Approval not found.", 404)
        if approval.status != "pending":
            raise ServiceError("approval_already_decided", "Approval is already decided.", 409)
        approval.status = "approved" if approved else "denied"
        approval.decided_by = principal.subject
        approval.reason = reason
        approval.decided_at = datetime.now(UTC)
        session.commit()
        return approval

    def _execute_with_resilience(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        last_error: ToolFailure | None = None
        for attempt in range(self.max_attempts):
            try:
                try:
                    self.circuit_breaker.before_call()
                except CircuitOpenError as exc:
                    CIRCUIT_BREAKER_REJECTIONS.labels(self.dependency_name).inc()
                    self._publish_circuit_state()
                    raise CircuitOpenToolFailure(str(exc)) from exc

                pool = ThreadPoolExecutor(max_workers=1)
                try:
                    future = pool.submit(
                        self.backend.execute,
                        tool_name,
                        arguments,
                        idempotency_key,
                        tenant_id,
                    )
                    try:
                        result = future.result(timeout=self.timeout_seconds)
                    except FutureTimeout as exc:
                        future.cancel()
                        raise TransientToolFailure("Tool timed out") from exc
                    self.circuit_breaker.record_success()
                    self._publish_circuit_state()
                    return result
                finally:
                    # Do not wait for an uncooperative adapter after the deadline.
                    pool.shutdown(wait=False, cancel_futures=True)
            except ToolFailure as exc:
                last_error = exc
                if exc.retryable:
                    self.circuit_breaker.record_failure()
                    self._publish_circuit_state()
                if not exc.retryable or attempt + 1 >= self.max_attempts:
                    raise
                TOOL_RETRIES.labels(tool_name, exc.code).inc()
                self.sleep(0.05 * (2**attempt))
        raise last_error or ToolFailure("Tool failed")

    def _publish_circuit_state(self) -> None:
        values = {
            CircuitState.CLOSED.value: 0,
            CircuitState.HALF_OPEN.value: 0.5,
            CircuitState.OPEN.value: 1,
        }
        state = str(self.circuit_breaker.snapshot()["state"])
        CIRCUIT_BREAKER_STATE.labels(self.dependency_name).set(values[state])

    @staticmethod
    def _redact(arguments: dict[str, Any], spec: ToolSpec) -> dict[str, Any]:
        return {
            key: "[REDACTED]" if key in spec.redact_fields else value
            for key, value in arguments.items()
        }

    @staticmethod
    def _result(log: ToolLog) -> ToolResult:
        return ToolResult(
            tool_log_id=log.id,
            tool_name=log.tool_name,
            status=log.status,
            risk_level=log.risk_level,
            result=log.result,
            approval_id=log.approval_id,
            error_code=log.error_code,
        )

    @classmethod
    def _observed_result(cls, log: ToolLog) -> ToolResult:
        result = cls._result(log)
        TOOL_EXECUTIONS.labels(
            result.tool_name,
            result.risk_level,
            result.status,
        ).inc()
        return result


def validate_tool_result(
    tool_name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    model = TOOL_RESULT_MODELS.get(tool_name)
    if model is None:
        raise InvalidToolResponseFailure("No output contract exists for the tool")
    try:
        return model.model_validate(result).model_dump(
            mode="json",
            exclude_none=True,
        )
    except ValidationError as exc:
        raise InvalidToolResponseFailure(
            "Tool gateway returned an invalid result"
        ) from exc


def build_backend() -> SupportBackend:
    if settings.tool_backend == "sandbox":
        return SandboxSupportBackend()
    if settings.tool_backend == "http":
        return HttpSupportBackend(
            settings.tool_api_url or "",
            settings.tool_api_token or "",
        )
    return DisabledSupportBackend()


sandbox_backend = build_backend()
tool_executor = ToolExecutor(sandbox_backend)
