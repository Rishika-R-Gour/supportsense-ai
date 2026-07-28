from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportsense.conversations import conversation_service
from supportsense.db_models import KnowledgeChunk, KnowledgeSource
from supportsense.errors import ServiceError
from supportsense.guardrails import validate_input
from supportsense.models import KnowledgeSourceCreate, KnowledgeSourceResponse
from supportsense.retrieval import KnowledgeDocument
from supportsense.security import Principal
from supportsense.vector_store import vector_store


def create_knowledge_source(
    session: Session,
    principal: Principal,
    payload: KnowledgeSourceCreate,
) -> KnowledgeSource:
    conversation_service.ensure_identity(session, principal)
    combined = "\n".join(chunk.content for chunk in payload.chunks)
    decisions = [validate_input(chunk.content) for chunk in payload.chunks]
    if any(decision.reason == "sensitive_data" for decision in decisions):
        raise ServiceError(
            "sensitive_knowledge_content",
            "Knowledge sources must not contain credentials or payment data.",
        )
    quarantined = any(
        decision.reason == "prompt_injection" for decision in decisions
    )
    source = KnowledgeSource(
        tenant_id=principal.tenant_id,
        title=payload.title,
        uri=payload.uri,
        content_sha256=hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        status="quarantined" if quarantined else "active",
        metadata_json=payload.metadata,
    )
    session.add(source)
    session.flush()
    created_chunks: list[KnowledgeChunk] = []
    if not quarantined:
        for index, chunk in enumerate(payload.chunks):
            record = KnowledgeChunk(
                tenant_id=principal.tenant_id,
                source_id=source.id,
                chunk_index=index,
                content=chunk.content,
                content_sha256=hashlib.sha256(
                    chunk.content.encode("utf-8")
                ).hexdigest(),
                metadata_json=chunk.metadata,
            )
            session.add(record)
            created_chunks.append(record)
        session.flush()
    session.commit()
    if created_chunks:
        vector_store.index_documents(
            principal.tenant_id,
            "knowledge",
            [
                KnowledgeDocument(
                    document_id=f"KB-{chunk.id}",
                    title=source.title,
                    content=chunk.content,
                    metadata={
                        **(source.metadata_json or {}),
                        **(chunk.metadata_json or {}),
                        "source_uri": source.uri,
                        "source_id": source.id,
                    },
                )
                for chunk in created_chunks
            ],
        )
    return source


def list_knowledge_sources(
    session: Session, principal: Principal
) -> list[KnowledgeSourceResponse]:
    sources = session.scalars(
        select(KnowledgeSource)
        .where(KnowledgeSource.tenant_id == principal.tenant_id)
        .order_by(KnowledgeSource.created_at.desc())
    ).all()
    return [
        KnowledgeSourceResponse(
            source_id=source.id,
            title=source.title,
            uri=source.uri,
            status=source.status,
            content_sha256=source.content_sha256,
            metadata=source.metadata_json or {},
        )
        for source in sources
    ]


def knowledge_documents_for_tenant(
    session: Session, tenant_id: str
) -> list[KnowledgeDocument]:
    rows = session.execute(
        select(KnowledgeChunk, KnowledgeSource)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeChunk.source_id)
        .where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.status == "active",
        )
    ).all()
    return [
        KnowledgeDocument(
            document_id=f"KB-{chunk.id}",
            title=source.title,
            content=chunk.content,
            metadata={
                **(source.metadata_json or {}),
                **(chunk.metadata_json or {}),
                "source_uri": source.uri,
                "source_id": source.id,
            },
        )
        for chunk, source in rows
    ]
