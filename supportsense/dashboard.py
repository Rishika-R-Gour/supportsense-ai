from __future__ import annotations

from collections import Counter
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportsense.db_models import Conversation, Message, Ticket, ToolLog
from supportsense.models import DashboardResponse


def supervisor_dashboard(session: Session, tenant_id: str) -> DashboardResponse:
    conversations = session.scalars(
        select(Conversation).where(Conversation.tenant_id == tenant_id)
    ).all()
    tools = session.scalars(
        select(ToolLog).where(ToolLog.tenant_id == tenant_id)
    ).all()
    tickets = session.scalars(
        select(Ticket).where(Ticket.tenant_id == tenant_id)
    ).all()
    assistant_messages = session.scalars(
        select(Message).where(
            Message.tenant_id == tenant_id,
            Message.role == "assistant",
        )
    ).all()
    total = len(conversations)
    escalated = sum(conversation.escalated for conversation in conversations)
    contained = sum(
        not conversation.escalated
        and conversation.outcome in {"answered", "succeeded", "approval_required"}
        for conversation in conversations
    )
    intents = Counter(
        conversation.intent or "unknown" for conversation in conversations
    )
    failed_tools = Counter(
        tool.tool_name for tool in tools if tool.status == "failed"
    )
    gaps = Counter(
        conversation.intent or "unknown"
        for conversation in conversations
        if conversation.outcome == "answered"
        and conversation.intent in {"api_authentication", "conversation_intelligence"}
    )
    outcomes = Counter(
        conversation.outcome or "in_progress" for conversation in conversations
    )
    issues = Counter(ticket.category or "Uncategorized" for ticket in tickets)
    sentiment = Counter(
        str((ticket.attributes or {}).get("sentiment") or "Unknown")
        for ticket in tickets
    )
    automation = Counter(
        ticket.category or "Uncategorized"
        for ticket in tickets
        if (ticket.attributes or {}).get("bot_solvable_label") == "bot_solvable"
    )
    response_latencies = [
        message.latency_ms
        for message in assistant_messages
        if message.latency_ms is not None
    ]
    return DashboardResponse(
        total_conversations=total,
        contained_conversations=contained,
        containment_rate=round(contained / total, 4) if total else 0,
        escalated_conversations=escalated,
        escalation_rate=round(escalated / total, 4) if total else 0,
        failed_tool_calls=sum(failed_tools.values()),
        top_intents=_counter_rows(intents),
        tool_failures=_counter_rows(failed_tools),
        knowledge_gaps=_counter_rows(gaps),
        conversation_outcomes=_counter_rows(outcomes),
        top_customer_issues=_counter_rows(issues),
        average_response_time_ms=(
            round(mean(response_latencies), 3) if response_latencies else 0
        ),
        customer_sentiment=_counter_rows(sentiment),
        automation_opportunities=_counter_rows(automation),
    )


def _counter_rows(counter: Counter[str]) -> list[dict[str, int | str]]:
    return [
        {"name": name, "count": count}
        for name, count in counter.most_common(10)
    ]
