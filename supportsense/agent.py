from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from supportsense.analysis_persistence import ticket_documents_for_analysis
from supportsense.conversations import conversation_service
from supportsense.db_models import ToolLog
from supportsense.errors import ServiceError
from supportsense.guardrails import validate_input, validate_output
from supportsense.knowledge import knowledge_documents_for_tenant
from supportsense.retrieval import HybridRetriever, grounded_ticket_answer
from supportsense.rollout import RolloutPolicy
from supportsense.security import Principal, require_role
from supportsense.tooling import TOOL_SPECS, ToolResult, tool_executor
from supportsense.tracing import agent_observation
from supportsense.vector_store import vector_store


class AgentState(TypedDict, total=False):
    question: str
    safe_question: str
    conversation_id: str
    idempotency_key: str
    guardrail_reason: str | None
    intent: str
    tool_name: str | None
    tool_arguments: dict[str, Any]
    tool_result: ToolResult | None
    answer: str
    citations: list[str]
    escalated: bool
    escalation_reason: str | None
    analysis_id: str | None
    draft_answer: str
    validation_error: str | None
    policy_error: str | None
    tool_route: Literal["execute_tool", "retrieve", "respond"]
    retrieval_confidence: float
    conversation_context: str
    user_message_id: str
    assistant_message_id: str


class SupportAgent:
    """Bounded LangGraph agent with deterministic policy and tool routing."""

    def __init__(
        self,
        session: Session,
        principal: Principal,
        rollout_policy: RolloutPolicy | None = None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.rollout_policy = rollout_policy or RolloutPolicy.current()
        graph = StateGraph(AgentState)
        graph.add_node("guardrail", self._guardrail)
        graph.add_node("classify", self._classify)
        graph.add_node("plan", self._plan)
        graph.add_node("policy_validator", self._policy_validator)
        graph.add_node("tool_router", self._tool_router)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("execute_tool", self._execute_tool)
        graph.add_node("validate_result", self._validate_result)
        graph.add_node("respond", self._respond)
        graph.add_node("escalate", self._escalate)
        graph.set_entry_point("guardrail")
        graph.add_conditional_edges(
            "guardrail",
            lambda state: "classify" if not state.get("guardrail_reason") else "escalate",
            {"classify": "classify", "escalate": "escalate"},
        )
        graph.add_edge("classify", "plan")
        graph.add_edge("plan", "policy_validator")
        graph.add_conditional_edges(
            "policy_validator",
            lambda state: (
                "escalate" if state.get("validation_error") else "tool_router"
            ),
            {"escalate": "escalate", "tool_router": "tool_router"},
        )
        graph.add_conditional_edges(
            "tool_router",
            lambda state: state["tool_route"],
            {
                "execute_tool": "execute_tool",
                "retrieve": "retrieve",
                "respond": "respond",
            },
        )
        graph.add_edge("execute_tool", "validate_result")
        graph.add_edge("retrieve", "validate_result")
        graph.add_conditional_edges(
            "validate_result",
            lambda state: "escalate" if state.get("validation_error") else "respond",
            {"escalate": "escalate", "respond": "respond"},
        )
        graph.add_edge("respond", END)
        graph.add_edge("escalate", END)
        self.graph = graph.compile()

    def run(
        self,
        *,
        conversation_id: str,
        question: str,
        idempotency_key: str,
    ) -> AgentState:
        started = time.perf_counter()
        conversation = conversation_service.get(
            self.session, self.principal, conversation_id
        )
        previous_context = conversation.summary or ""
        long_term = (conversation.memory or {}).get("long_term", {})
        if long_term:
            previous_context += "\nCustomer preferences: " + ", ".join(
                f"{key}={value}" for key, value in sorted(long_term.items())
            )
        user_message = conversation_service.add_message(
            self.session,
            self.principal,
            conversation_id,
            role="user",
            content=question,
        )
        with agent_observation(
            {
                "tenant_id": self.principal.tenant_id,
                "conversation_id": conversation_id,
                "role": self.principal.role.value,
                "rollout_stage": self.rollout_policy.stage.value,
            }
        ):
            result = self.graph.invoke(
                {
                    "question": question,
                    "conversation_id": conversation_id,
                    "idempotency_key": idempotency_key,
                    "citations": [],
                    "escalated": False,
                    "analysis_id": conversation.analysis_id,
                    "conversation_context": previous_context[-4_000:],
                }
            )
        output_decision = validate_output(
            result["answer"],
            result.get("citations", []),
            set(result.get("citations", [])),
        )
        if not output_decision.allowed:
            result = {
                **result,
                "answer": "The response was blocked by output safety validation.",
                "citations": [],
                "escalated": True,
                "escalation_reason": output_decision.reason,
            }
        else:
            result["answer"] = output_decision.redacted_text or result["answer"]
        tool_result = result.get("tool_result")
        tool_calls = (
            [
                {
                    "tool_log_id": tool_result.tool_log_id,
                    "tool_name": tool_result.tool_name,
                    "status": tool_result.status,
                    "risk_level": tool_result.risk_level,
                }
            ]
            if tool_result
            else []
        )
        assistant_message = conversation_service.add_message(
            self.session,
            self.principal,
            conversation_id,
            role=(
                "assistant"
                if self.rollout_policy.customer_visible
                else "assistant_internal"
            ),
            content=result["answer"],
            citations=[{"reference": item} for item in result.get("citations", [])],
            tool_calls=tool_calls,
            model="deterministic-policy-agent",
            prompt_version="supportsense-agent-v2",
            latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=0,
        )
        result["user_message_id"] = user_message.id
        result["assistant_message_id"] = assistant_message.id
        conversation.intent = result.get("intent")
        conversation.escalated = bool(result.get("escalated"))
        conversation.outcome = (
            "escalated"
            if conversation.escalated
            else (tool_result.status if tool_result else "answered")
        )
        self.session.commit()
        return result

    @staticmethod
    def _guardrail(state: AgentState) -> AgentState:
        decision = validate_input(state["question"])
        if (
            decision.reason == "unsupported_scope"
            and state.get("conversation_context")
            and re.search(
                r"\b(it|that|those|again|also|earlier|previous)\b|what about",
                state["question"],
                flags=re.IGNORECASE,
            )
        ):
            return {
                "guardrail_reason": None,
                "safe_question": " ".join(state["question"].split()),
            }
        return {
            "guardrail_reason": decision.reason,
            "safe_question": decision.redacted_text or "",
        }

    @staticmethod
    def _classify(state: AgentState) -> AgentState:
        text = (
            state["safe_question"] + "\n" + state.get("conversation_context", "")
        ).lower()
        if "refund status" in text:
            intent = "refund_status"
        elif "refund" in text:
            intent = "refund_request"
        elif "delete" in text and "account" in text:
            intent = "delete_account"
        elif "update" in text and "billing" in text:
            intent = "update_billing"
        elif "update" in text and "email" in text:
            intent = "update_email"
        elif "escalate" in text and "ticket" in text:
            intent = "escalate_ticket"
        elif "ticket" in text and ("create" in text or "open" in text):
            intent = "create_ticket"
        elif ("recent" in text or "last" in text) and (
            "transaction" in text or "charge" in text
        ):
            intent = "recent_transactions"
        elif (
            "customer" in text
            and any(word in text for word in ["profile", "record", "details"])
            and not any(
                word in text
                for word in [
                    "invoice",
                    "payment",
                    "charge",
                    "refund",
                    "subscription",
                    "transaction",
                ]
            )
        ):
            intent = "customer_lookup"
        elif "resend" in text and "invoice" in text:
            intent = "resend_invoice"
        elif "invoice" in text or re.search(r"\b(?:in|inv)_[a-z0-9]+\b", text):
            intent = "invoice_request"
        elif "cancel" in text and "subscription" in text:
            intent = "cancel_subscription"
        elif "subscription" in text:
            intent = "subscription_issue"
        elif "payment" in text or "charge" in text:
            intent = "payment_issue"
        elif "api" in text and ("auth" in text or "key" in text):
            intent = "api_authentication"
        elif any(word in text for word in ["theme", "csat", "priority", "top issue"]):
            intent = "conversation_intelligence"
        else:
            intent = "billing_question"
        return {"intent": intent}

    @staticmethod
    def _plan(state: AgentState) -> AgentState:
        text = state["safe_question"] + "\n" + state.get("conversation_context", "")
        original_text = state["question"]
        intent = state["intent"]
        customer_id = _identifier(text, r"\bcus_[A-Za-z0-9]+\b")
        mappings = {
            "refund_status": ("refund_status", r"\b(?:re|refund)_[A-Za-z0-9]+\b"),
            "invoice_request": ("get_invoice", r"\b(?:in|inv)_[A-Za-z0-9]+\b"),
            "resend_invoice": ("resend_invoice", r"\b(?:in|inv)_[A-Za-z0-9]+\b"),
            "subscription_issue": ("get_subscription", r"\bsub_[A-Za-z0-9]+\b"),
            "payment_issue": ("get_payment", r"\bpay_[A-Za-z0-9]+\b"),
        }
        if intent in mappings:
            tool_name, pattern = mappings[intent]
            entity_id = _identifier(text, pattern)
            if customer_id and entity_id:
                return {
                    "tool_name": tool_name,
                    "tool_arguments": {
                        "customer_id": customer_id,
                        "entity_id": entity_id,
                    },
                }
            return {"tool_name": None}

        if intent == "refund_request":
            payment_id = _identifier(text, r"\bpay_[A-Za-z0-9]+\b")
            amount = re.search(r"\$(\d+(?:\.\d{1,2})?)", text)
            if customer_id and payment_id and amount:
                return {
                    "tool_name": "refund_customer",
                    "tool_arguments": {
                        "customer_id": customer_id,
                        "payment_id": payment_id,
                        "amount_cents": round(float(amount.group(1)) * 100),
                        "reason": "Customer requested refund",
                    },
                }
        if intent == "cancel_subscription":
            subscription_id = _identifier(text, r"\bsub_[A-Za-z0-9]+\b")
            if customer_id and subscription_id:
                return {
                    "tool_name": "cancel_subscription",
                    "tool_arguments": {
                        "customer_id": customer_id,
                        "subscription_id": subscription_id,
                        "reason": "Customer requested cancellation",
                    },
                }
        if intent == "customer_lookup" and customer_id:
            return {
                "tool_name": "get_customer",
                "tool_arguments": {"customer_id": customer_id},
            }
        if intent == "recent_transactions" and customer_id:
            limit_match = re.search(r"\b(?:last|recent)\s+(\d{1,2})\b", text)
            return {
                "tool_name": "recent_transactions",
                "tool_arguments": {
                    "customer_id": customer_id,
                    "limit": int(limit_match.group(1)) if limit_match else 10,
                },
            }
        if intent == "create_ticket" and customer_id:
            return {
                "tool_name": "create_ticket",
                "tool_arguments": {
                    "customer_id": customer_id,
                    "subject": "Customer support request",
                    "description": state["safe_question"],
                    "priority": "High" if "high priority" in text.lower() else "Medium",
                },
            }
        if intent == "escalate_ticket":
            ticket_id = _identifier(text, r"\b(?:TCK|ESC)-[A-Za-z0-9-]+\b")
            if ticket_id:
                return {
                    "tool_name": "escalate_ticket",
                    "tool_arguments": {
                        "ticket_id": ticket_id,
                        "reason": "Agent requested escalation",
                    },
                }
        if intent == "update_email" and customer_id:
            email = re.search(
                r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                original_text,
                flags=re.IGNORECASE,
            )
            if email:
                return {
                    "tool_name": "update_email",
                    "tool_arguments": {
                        "customer_id": customer_id,
                        "email": email.group(0),
                    },
                }
        if intent == "update_billing" and customer_id:
            token = _identifier(original_text, r"\bpm_[A-Za-z0-9_]+\b")
            if token:
                return {
                    "tool_name": "update_billing",
                    "tool_arguments": {
                        "customer_id": customer_id,
                        "payment_method_token": token,
                    },
                }
        if (
            intent == "delete_account"
            and customer_id
            and re.search(r"\bconfirm\s+DELETE\b", original_text)
        ):
            return {
                "tool_name": "delete_account",
                "tool_arguments": {
                    "customer_id": customer_id,
                    "confirmation": "DELETE",
                },
            }
        return {"tool_name": None}

    def _execute_tool(self, state: AgentState) -> AgentState:
        result = tool_executor.execute(
            self.session,
            self.principal,
            conversation_id=state["conversation_id"],
            tool_name=state["tool_name"] or "",
            arguments=state["tool_arguments"],
            idempotency_key=state["idempotency_key"],
            rollout_policy=self.rollout_policy,
        )
        return {"tool_result": result}

    def _policy_validator(self, state: AgentState) -> AgentState:
        tool_name = state.get("tool_name")
        if not tool_name:
            return {"policy_error": None}
        spec = TOOL_SPECS.get(tool_name)
        if spec is None:
            return {"validation_error": "unknown_tool"}
        # Permission checks fail closed with a structured 403. Rollout blocks
        # become non-executing suggestions in shadow and Agent Assist modes.
        require_role(self.principal, spec.minimum_role)
        try:
            self.rollout_policy.enforce_tool(spec.risk.value)
        except ServiceError as exc:
            return {"policy_error": exc.code}
        return {"policy_error": None}

    @staticmethod
    def _tool_router(state: AgentState) -> AgentState:
        if state.get("tool_name") and not state.get("policy_error"):
            route: Literal["execute_tool", "retrieve", "respond"] = "execute_tool"
        elif (
            state.get("intent") == "conversation_intelligence"
            and state.get("analysis_id")
        ) or state.get("intent") == "api_authentication":
            route = "retrieve"
        else:
            route = "respond"
        return {"tool_route": route}

    def _retrieve(self, state: AgentState) -> AgentState:
        if state["intent"] == "api_authentication":
            documents = knowledge_documents_for_tenant(
                self.session, self.principal.tenant_id
            )
        else:
            documents = ticket_documents_for_analysis(
                self.session,
                self.principal.tenant_id,
                state["analysis_id"],
            )
        namespace = (
            "knowledge"
            if state["intent"] == "api_authentication"
            else f"analysis:{state['analysis_id']}"
        )
        filters = _question_filters(state["safe_question"])
        lower_question = state["safe_question"].lower()
        if "top" in lower_question and any(
            word in lower_question for word in ["theme", "issue"]
        ):
            matching = [
                document
                for document in documents
                if all(
                    document.metadata.get(key) == value
                    for key, value in filters.items()
                )
            ]
            counts = Counter(
                str(document.metadata.get("theme") or "Other")
                for document in matching
            )
            citations = [document.document_id for document in matching[:5]]
            if counts and citations:
                lines = [
                    f"{theme}: {count} tickets"
                    for theme, count in counts.most_common(5)
                ]
                return {
                    "draft_answer": (
                        "Top ticket themes in the selected evidence:\n"
                        + "\n".join(lines)
                        + "\nEvidence: "
                        + ", ".join(f"[{item}]" for item in citations)
                    ),
                    "citations": citations,
                    "retrieval_confidence": 1.0,
                }
        retrieval = HybridRetriever(
            documents,
            semantic_search=(
                lambda query, candidates, limit: vector_store.search(
                    self.principal.tenant_id,
                    namespace,
                    query,
                    candidates,
                    limit,
                )
                if vector_store.enabled
                else {}
            ),
        ).retrieve(
            state["safe_question"],
            metadata_filters=filters,
        )
        grounded = grounded_ticket_answer(retrieval)
        return {
            "draft_answer": grounded["answer"],
            "citations": grounded["citations"],
            "retrieval_confidence": grounded["confidence"],
            "validation_error": (
                "retrieval_conflict"
                if retrieval.conflicts
                else "insufficient_evidence"
                if grounded["abstained"]
                else None
            ),
        }

    def _validate_result(self, state: AgentState) -> AgentState:
        result = state.get("tool_result")
        if result and result.status not in {
            "succeeded",
            "approval_required",
            "failed",
        }:
            return {"validation_error": "invalid_tool_result"}
        if result and result.status == "failed":
            failure_count = self.session.scalar(
                select(func.count(ToolLog.id)).where(
                    ToolLog.tenant_id == self.principal.tenant_id,
                    ToolLog.conversation_id == state["conversation_id"],
                    ToolLog.status == "failed",
                )
            )
            if (failure_count or 0) >= 2:
                return {"validation_error": "multiple_tool_failures"}
        citations = state.get("citations", [])
        draft = state.get("draft_answer", "")
        if citations and any(f"[{citation}]" not in draft for citation in citations):
            return {"validation_error": "invalid_citations"}
        return {"validation_error": state.get("validation_error")}

    @staticmethod
    def _respond(state: AgentState) -> AgentState:
        if state.get("draft_answer"):
            return {
                "answer": state["draft_answer"],
                "citations": state.get("citations", []),
            }
        result = state.get("tool_result")
        if result:
            citation = f"tool:{result.tool_log_id}"
            if result.status == "succeeded":
                return {
                    "answer": (
                        f"{_tool_result_summary(result.tool_name, result.result)} "
                        f"[{citation}]"
                    ),
                    "citations": [citation],
                }
            if result.status == "approval_required":
                return {
                    "answer": (
                        "This sensitive action is paused for supervisor approval. "
                        f"No change has been made [{citation}]."
                    ),
                    "citations": [citation],
                }
            return {
                "answer": f"The support tool failed safely [{citation}].",
                "citations": [citation],
            }
        intent = state["intent"]
        if state.get("tool_name"):
            return {
                "answer": (
                    f"Suggested action: {state['tool_name']}. An authorized agent "
                    "must review and execute this action."
                ),
                "citations": [],
            }
        if intent == "conversation_intelligence":
            return {
                "answer": (
                    "This question belongs to Conversation Intelligence. Select an "
                    "analysis dataset so I can answer with cited ticket evidence."
                ),
                "citations": [],
            }
        if intent == "api_authentication":
            return {
                "answer": (
                    "I need a connected knowledge source to answer API authentication "
                    "questions with verified documentation."
                ),
                "citations": [],
            }
        return {
            "answer": (
                "Please provide the customer and object identifiers needed for this "
                "request (for example cus_demo and inv_123)."
            ),
            "citations": [],
        }

    @staticmethod
    def _escalate(state: AgentState) -> AgentState:
        reason = (
            state.get("guardrail_reason")
            or state.get("validation_error")
            or "policy_blocked"
        )
        if reason == "prompt_injection":
            answer = "I cannot follow instructions that attempt to bypass support policies."
        elif reason == "sensitive_data":
            answer = "Please remove payment credentials or other sensitive data and try again."
        elif reason in {"insufficient_evidence", "retrieval_conflict"}:
            answer = "I could not verify a safe answer from the available evidence."
        elif reason == "suspected_fraud":
            answer = "I’m escalating this suspected fraud report for immediate human review."
        elif reason == "angry_customer":
            answer = "I’m connecting this conversation to a human support agent."
        elif reason == "multiple_tool_failures":
            answer = "Multiple support actions failed, so I’m escalating for manual resolution."
        else:
            answer = "This request is outside the supported customer-support scope."
        return {
            "answer": answer,
            "escalated": True,
            "escalation_reason": reason,
            "intent": state.get("intent") or "blocked",
            "citations": [],
        }


def _identifier(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(0) if match else None


def _question_filters(text: str) -> dict[str, str]:
    lower = text.lower()
    filters: dict[str, str] = {}
    for priority in ["Critical", "High", "Medium", "Low"]:
        if priority.lower() in lower:
            filters["priority"] = priority
    for segment in ["Enterprise", "Mid-Market", "SMB", "Startup"]:
        if segment.lower() in lower:
            filters["customer_segment"] = segment
    return filters


def _tool_result_summary(tool_name: str, result: dict[str, Any] | None) -> str:
    """Turn an allowlisted tool result into a useful, injection-safe sentence."""
    payload = result or {}

    def identifier(key: str) -> str | None:
        return _safe_result_value(payload.get(key))

    status = _safe_result_value(payload.get("status"))
    customer_id = identifier("customer_id")

    if tool_name == "get_customer" and customer_id:
        plan = _safe_result_value(payload.get("plan"))
        return (
            f"Customer {customer_id} is on the {plan} plan."
            if plan
            else f"Customer {customer_id} was found."
        )
    if tool_name == "get_invoice" and identifier("id"):
        return _entity_status("Invoice", identifier("id"), status)
    if tool_name == "get_subscription" and identifier("id"):
        return _entity_status("Subscription", identifier("id"), status)
    if tool_name == "get_payment" and identifier("id"):
        return _entity_status("Payment", identifier("id"), status)
    if tool_name == "refund_status" and identifier("id"):
        return _entity_status("Refund", identifier("id"), status)
    if tool_name == "recent_transactions":
        transactions = payload.get("transactions")
        if isinstance(transactions, list):
            count = len(transactions)
            suffix = "s" if count != 1 else ""
            return f"Found {count} recent transaction{suffix}."
    if tool_name in {"create_ticket", "escalate_ticket"} and identifier("ticket_id"):
        return _entity_status("Ticket", identifier("ticket_id"), status)
    if tool_name == "update_email" and customer_id and payload.get("updated") is True:
        return f"Customer {customer_id}'s email address was updated."
    if tool_name == "resend_invoice" and identifier("invoice_id"):
        invoice_id = identifier("invoice_id")
        delivery = _safe_result_value(payload.get("delivery_status"))
        return (
            f"Invoice {invoice_id} delivery is {delivery}."
            if delivery
            else f"Invoice {invoice_id} was queued for delivery."
        )
    if tool_name == "refund_customer" and identifier("refund_id"):
        return _entity_status("Refund", identifier("refund_id"), status)
    if tool_name == "cancel_subscription" and identifier("subscription_id"):
        return _entity_status(
            "Subscription",
            identifier("subscription_id"),
            status,
        )
    if (
        tool_name == "update_billing"
        and customer_id
        and payload.get("billing_updated") is True
    ):
        return f"Customer {customer_id}'s billing method was updated."
    if tool_name == "delete_account" and customer_id:
        deletion_status = _safe_result_value(payload.get("deletion_status"))
        return (
            f"Customer {customer_id}'s account deletion is {deletion_status}."
            if deletion_status
            else f"Customer {customer_id}'s account deletion was accepted."
        )
    action = tool_name.replace("_", " ")
    return f"The authorized {action} action completed successfully."


def _entity_status(label: str, identifier: str | None, status: str | None) -> str:
    return (
        f"{label} {identifier} status: {status}."
        if status
        else f"{label} {identifier} was found."
    )


def _safe_result_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:@+-]{1,128}", normalized):
        return None
    return normalized
