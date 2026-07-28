from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportsense.conversations import conversation_service
from supportsense.db_models import (
    KnowledgeChunk,
    KnowledgeSource,
    Message,
    Ticket,
    ToolLog,
    User,
)
from supportsense.models import EscalationPackage
from supportsense.security import Principal


class EscalationService:
    def escalate(
        self,
        session: Session,
        principal: Principal,
        conversation_id: str,
        *,
        reason: str,
    ) -> EscalationPackage:
        conversation = conversation_service.get(
            session, principal, conversation_id
        )
        messages = session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.tenant_id == principal.tenant_id,
            )
            .order_by(Message.created_at.asc())
        ).all()
        tool_logs = session.scalars(
            select(ToolLog)
            .where(
                ToolLog.conversation_id == conversation.id,
                ToolLog.tenant_id == principal.tenant_id,
            )
            .order_by(ToolLog.created_at.asc())
        ).all()

        memory = dict(conversation.memory or {})
        ticket_id = memory.get("escalation_ticket_id")
        ticket = (
            session.scalar(
                select(Ticket).where(
                    Ticket.external_ticket_id == ticket_id,
                    Ticket.tenant_id == principal.tenant_id,
                )
            )
            if ticket_id
            else None
        )
        if ticket is None:
            ticket = Ticket(
                tenant_id=principal.tenant_id,
                external_ticket_id=f"ESC-{conversation.id[:8].upper()}",
                requester_subject=principal.subject,
                subject=f"AI escalation: {conversation.intent or 'support request'}",
                description=conversation.summary or "Conversation requires human review.",
                status="Escalated",
                priority="High",
                category="ai_escalation",
                attributes={"reason": reason, "conversation_id": conversation.id},
            )
            session.add(ticket)
            session.flush()
            memory["escalation_ticket_id"] = ticket.external_ticket_id

        conversation.escalated = True
        conversation.status = "escalated"
        conversation.outcome = "human_handoff"
        conversation.memory = memory
        session.commit()

        customer_ids = sorted(
            {
                str(log.arguments["customer_id"])
                for log in tool_logs
                if (log.arguments or {}).get("customer_id")
            }
        )
        owner = session.get(User, conversation.user_id) if conversation.user_id else None
        references = list(
            dict.fromkeys(
                str(citation["reference"])
                for message in messages
                for citation in (message.citations or [])
                if isinstance(citation, dict) and citation.get("reference")
            )
        )

        return EscalationPackage(
            ticket_id=ticket.external_ticket_id,
            conversation_id=conversation.id,
            reason=reason,
            intent=conversation.intent,
            summary=conversation.summary or "No summary available.",
            customer_context={
                "requester_subject": owner.external_subject if owner else None,
                "customer_ids": customer_ids,
                "memory": conversation.memory or {},
            },
            retrieved_docs=_retrieved_documents(
                session,
                principal.tenant_id,
                references,
            ),
            conversation_history=[
                {
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at.isoformat(),
                }
                for message in messages
            ],
            tool_history=[
                {
                    "tool_name": log.tool_name,
                    "risk_level": log.risk_level,
                    "status": log.status,
                    "arguments": log.arguments,
                    "result": log.result,
                    "error_code": log.error_code,
                    "created_at": log.created_at.isoformat(),
                }
                for log in tool_logs
            ],
            recommended_action=_recommendation(reason, tool_logs),
        )


def _recommendation(reason: str, tool_logs: list[ToolLog]) -> str:
    if reason in {"prompt_injection", "sensitive_data"}:
        return "Review for security or privacy risk before responding."
    if reason == "suspected_fraud":
        return "Route to the fraud workflow, lock risky actions, and verify the customer."
    if reason == "angry_customer":
        return "Acknowledge the frustration and have a senior agent respond promptly."
    failed = [log for log in tool_logs if log.status == "failed"]
    if failed:
        return f"Review failed tool {failed[-1].tool_name} and complete the workflow manually."
    pending = [log for log in tool_logs if log.status == "approval_required"]
    if pending:
        return f"Review and approve or deny {pending[-1].tool_name}."
    return "Review the conversation context and respond to the customer."


escalation_service = EscalationService()


def _retrieved_documents(
    session: Session,
    tenant_id: str,
    references: list[str],
) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    for reference in references:
        if reference.startswith("tool:"):
            continue
        if reference.startswith("KB-"):
            chunk = session.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.id == reference.removeprefix("KB-"),
                    KnowledgeChunk.tenant_id == tenant_id,
                )
            )
            source = session.get(KnowledgeSource, chunk.source_id) if chunk else None
            if chunk and source:
                documents.append(
                    {
                        "reference": reference,
                        "type": "knowledge",
                        "title": source.title,
                        "excerpt": chunk.content[:1_000],
                        "uri": source.uri,
                    }
                )
            continue
        ticket = session.scalar(
            select(Ticket).where(
                Ticket.external_ticket_id == reference,
                Ticket.tenant_id == tenant_id,
            )
        )
        if ticket:
            documents.append(
                {
                    "reference": reference,
                    "type": "ticket",
                    "title": ticket.subject,
                    "excerpt": ticket.description[:1_000],
                    "uri": "",
                }
            )
    return documents
