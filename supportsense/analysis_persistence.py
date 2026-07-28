from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat import answer_question
from supportsense.conversations import conversation_service
from supportsense.db_models import Analysis, Dataset, Ticket, now
from supportsense.errors import ServiceError
from supportsense.models import AnalysisResponse, ChatResponse
from supportsense.retrieval import KnowledgeDocument
from supportsense.security import Principal
from supportsense.store import AnalysisRecord


def persist_analysis(
    session: Session,
    principal: Principal,
    record: AnalysisRecord,
    *,
    object_uri: str | None = None,
) -> Analysis:
    conversation_service.ensure_identity(session, principal)
    dataset = Dataset(
        tenant_id=principal.tenant_id,
        filename=record.filename,
        object_uri=object_uri,
        content_sha256=record.content_sha256,
        row_count=len(record.dataframe),
        status="ready",
    )
    session.add(dataset)
    session.flush()

    analysis = Analysis(
        id=record.analysis_id,
        tenant_id=principal.tenant_id,
        dataset_id=dataset.id,
        status="completed",
        kpis=_json_value(record.kpis),
        themes=[_json_value(theme.__dict__) for theme in record.themes],
        model_provider="deterministic",
        prompt_version="supportsense-v1",
        completed_at=now(),
    )
    session.add(analysis)
    for row in record.dataframe.to_dict("records"):
        session.add(
            Ticket(
                tenant_id=principal.tenant_id,
                dataset_id=dataset.id,
                external_ticket_id=str(row["ticket_id"]),
                customer_id=str(row.get("customer_name") or "") or None,
                subject=str(row.get("subject") or ""),
                description=str(row.get("description") or ""),
                status=str(row.get("status") or "Unknown"),
                priority=str(row.get("priority") or "Unknown"),
                category=str(row.get("theme") or row.get("product_area") or "") or None,
                attributes={
                    key: _json_value(row.get(key))
                    for key in [
                        "customer_segment",
                        "plan_type",
                        "product_area",
                        "csat_score",
                        "sentiment",
                        "bot_solvable_label",
                        "created_at",
                    ]
                },
            )
        )
    session.commit()
    return analysis


def persisted_analysis_response(
    session: Session,
    tenant_id: str,
    analysis_id: str,
) -> AnalysisResponse:
    row = session.execute(
        select(Analysis, Dataset)
        .join(Dataset, Dataset.id == Analysis.dataset_id)
        .where(
            Analysis.id == analysis_id,
            Analysis.tenant_id == tenant_id,
            Dataset.tenant_id == tenant_id,
        )
    ).one_or_none()
    if row is None:
        raise ServiceError("analysis_not_found", "Analysis not found.", 404)
    analysis, dataset = row
    return AnalysisResponse.model_validate(
        {
            "analysis_id": analysis.id,
            "filename": dataset.filename,
            "created_at": analysis.created_at,
            "row_count": dataset.row_count,
            "content_sha256": dataset.content_sha256,
            "kpis": analysis.kpis,
            "themes": analysis.themes,
        }
    )


def persisted_analysis_chat(
    session: Session,
    tenant_id: str,
    analysis_id: str,
    question: str,
) -> ChatResponse:
    analysis = session.scalar(
        select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.tenant_id == tenant_id,
        )
    )
    if analysis is None:
        raise ServiceError("analysis_not_found", "Analysis not found.", 404)
    tickets = session.scalars(
        select(Ticket).where(
            Ticket.tenant_id == tenant_id,
            Ticket.dataset_id == analysis.dataset_id,
        )
    ).all()
    dataframe = pd.DataFrame(
        [
            {
                "ticket_id": ticket.external_ticket_id,
                "customer_name": ticket.customer_id or "",
                "customer_segment": (ticket.attributes or {}).get(
                    "customer_segment", ""
                ),
                "priority": ticket.priority,
                "status": ticket.status,
                "subject": ticket.subject,
                "description": ticket.description,
                "ticket_text": f"{ticket.subject} {ticket.description}",
                "theme": ticket.category,
                "csat_score": (ticket.attributes or {}).get("csat_score"),
                "created_at": (ticket.attributes or {}).get("created_at"),
            }
            for ticket in tickets
        ]
    )
    return ChatResponse.model_validate(answer_question(question, dataframe))


def ticket_documents_for_analysis(
    session: Session, tenant_id: str, analysis_id: str
) -> list[KnowledgeDocument]:
    analysis = session.scalar(
        select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.tenant_id == tenant_id,
        )
    )
    if analysis is None:
        raise ServiceError("analysis_not_found", "Analysis not found.", 404)
    tickets = session.scalars(
        select(Ticket).where(
            Ticket.dataset_id == analysis.dataset_id,
            Ticket.tenant_id == tenant_id,
        )
    ).all()
    return [
        KnowledgeDocument(
            document_id=ticket.external_ticket_id,
            title=ticket.subject,
            content=ticket.description,
            metadata={
                **(ticket.attributes or {}),
                "priority": ticket.priority,
                "status": ticket.status,
                "theme": ticket.category,
            },
        )
        for ticket in tickets
    ]


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value
