from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Theme(BaseModel):
    name: str
    count: int
    share: float
    avg_csat: float
    critical_high_count: int
    trend: str
    summary: str
    ticket_ids: list[str]


class AnalysisResponse(BaseModel):
    analysis_id: str
    filename: str
    created_at: datetime
    row_count: int
    content_sha256: str
    kpis: dict[str, Any]
    themes: list[Theme]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)


class ChatResponse(BaseModel):
    answer: str
    ticket_ids: list[str]
    method: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ConversationCreate(BaseModel):
    analysis_id: str | None = None
    channel: str = Field(default="web", pattern=r"^[a-z][a-z0-9_-]{1,31}$")


class ConversationResponse(BaseModel):
    conversation_id: str
    status: str
    channel: str
    summary: str | None = None
    memory: dict[str, Any] = Field(default_factory=dict)
    intent: str | None = None
    outcome: str | None = None
    escalated: bool
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8_000)


class MessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    role: str
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=128)
    approval_id: str | None = None


class ToolCallResponse(BaseModel):
    tool_log_id: str
    tool_name: str
    status: str
    risk_level: str
    result: dict[str, Any] | None = None
    approval_id: str | None = None
    error_code: str | None = None


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str | None = Field(default=None, max_length=1_000)


class ApprovalResponse(BaseModel):
    approval_id: str
    status: str
    tool_name: str
    conversation_id: str
    decided_by: str | None = None
    requested_arguments: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None
    reason: str | None = None
    created_at: datetime | None = None


class AgentChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=8_000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class AgentChatResponse(BaseModel):
    conversation_id: str
    answer: str
    intent: str
    citations: list[str] = Field(default_factory=list)
    escalated: bool = False
    escalation_reason: str | None = None
    tool_call: ToolCallResponse | None = None
    mode: str = "limited_automation"
    requires_agent_review: bool = False
    customer_visible: bool = True
    confidence: float | None = None
    tool_suggestion: str | None = None


class EscalationRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1_000)


class EscalationPackage(BaseModel):
    ticket_id: str
    conversation_id: str
    reason: str
    intent: str | None = None
    summary: str
    customer_context: dict[str, Any]
    retrieved_docs: list[dict[str, Any]]
    conversation_history: list[dict[str, Any]]
    tool_history: list[dict[str, Any]]
    recommended_action: str


class DashboardResponse(BaseModel):
    total_conversations: int
    contained_conversations: int
    containment_rate: float
    escalated_conversations: int
    escalation_rate: float
    failed_tool_calls: int
    top_intents: list[dict[str, Any]]
    tool_failures: list[dict[str, Any]]
    knowledge_gaps: list[dict[str, Any]]
    conversation_outcomes: list[dict[str, Any]]
    top_customer_issues: list[dict[str, Any]]
    average_response_time_ms: float
    customer_sentiment: list[dict[str, Any]]
    automation_opportunities: list[dict[str, Any]]


class AuthMeResponse(BaseModel):
    subject: str
    tenant_id: str
    role: str


class TicketResponse(BaseModel):
    ticket_id: str
    customer_id: str | None = None
    requester_subject: str | None = None
    assigned_to: str | None = None
    subject: str
    description: str
    status: str
    priority: str
    category: str | None = None
    attributes: dict[str, Any]


class TicketCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=3, max_length=4_000)
    priority: str = Field(default="Medium", pattern=r"^(Low|Medium|High|Critical)$")
    category: str | None = Field(default=None, max_length=100)
    customer_id: str | None = Field(default=None, max_length=255)


class TicketAssignment(BaseModel):
    assigned_to: str = Field(min_length=1, max_length=255)


class AgentVersionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=64)
    prompt_version: str = Field(min_length=1, max_length=64)
    model_settings: dict[str, Any] = Field(
        default_factory=dict,
        alias="model_config",
    )
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    rollout_stage: str = Field(
        default="offline",
        pattern=r"^(offline|shadow|agent_assist|limited_automation|full_automation)$",
    )
    active: bool = False


class AgentVersionResponse(AgentVersionCreate):
    agent_version_id: str
    created_at: datetime


class EvaluationResponse(BaseModel):
    evaluation_id: str
    suite: str
    status: str
    passed: bool
    metrics: dict[str, Any]
    gates: dict[str, bool]


class MemoryUpsert(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)
    conversation_id: str | None = None


class MemoryFactResponse(BaseModel):
    key: str
    value: str
    confidence: float
    updated_at: datetime


class KnowledgeChunkInput(BaseModel):
    content: str = Field(min_length=1, max_length=12_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    uri: str = Field(min_length=1, max_length=2_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunks: list[KnowledgeChunkInput] = Field(min_length=1, max_length=100)


class KnowledgeSourceResponse(BaseModel):
    source_id: str
    title: str
    uri: str
    status: str
    content_sha256: str
    metadata: dict[str, Any]
