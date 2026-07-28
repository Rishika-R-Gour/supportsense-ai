from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportsense.guardrails import redact_pii

log = logging.getLogger("supportsense.audit")


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    occurred_at: str
    event_type: str
    tenant_id: str
    actor_id: str
    request_id: str
    resource_id: str | None = None
    outcome: str = "success"
    attributes: dict[str, Any] = field(default_factory=dict)


class AuditLog:
    """Development audit sink; the interface can be backed by Postgres/S3."""

    def __init__(self, max_events: int = 10_000) -> None:
        self._events: list[AuditEvent] = []
        self._max_events = max_events
        self._lock = Lock()

    def record(
        self,
        *,
        event_type: str,
        tenant_id: str,
        actor_id: str,
        request_id: str,
        resource_id: str | None = None,
        outcome: str = "success",
        attributes: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=str(uuid4()),
            occurred_at=datetime.now(UTC).isoformat(),
            event_type=event_type,
            tenant_id=tenant_id,
            actor_id=actor_id,
            request_id=request_id,
            resource_id=resource_id,
            outcome=outcome,
            attributes=attributes or {},
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]
        log.info(json.dumps(asdict(event), separators=(",", ":"), default=str))
        return event

    def list_for_tenant(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        with self._lock:
            matches = [event for event in self._events if event.tenant_id == tenant_id]
        return matches[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def private_text_metadata(value: str) -> dict[str, Any]:
    """Describe sensitive text without placing the text itself in audit logs."""
    normalized = value.strip()
    return {
        "text_length": len(normalized),
        "text_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def redact_payload(value: Any, key: str | None = None) -> Any:
    sensitive_keys = {
        "email",
        "payment_method_token",
        "card",
        "card_number",
        "ssn",
        "secret",
        "password",
        "token",
    }
    if key and key.lower() in sensitive_keys:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            item_key: redact_payload(item, item_key)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact_pii(value)
    return value


audit_log = AuditLog()


def persist_audit_event(session: Session, event: AuditEvent) -> None:
    from supportsense.db_models import AuditRecord

    previous = session.scalar(
        select(AuditRecord)
        .where(AuditRecord.tenant_id == event.tenant_id)
        .order_by(AuditRecord.occurred_at.desc(), AuditRecord.id.desc())
        .limit(1)
    )
    previous_hash = previous.event_hash if previous else None
    canonical = json.dumps(
        {
            **asdict(event),
            "previous_hash": previous_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    session.add(
        AuditRecord(
            id=event.event_id,
            tenant_id=event.tenant_id,
            actor_id=event.actor_id,
            event_type=event.event_type,
            resource_type=event.event_type.split(".", 1)[0],
            resource_id=event.resource_id,
            request_id=event.request_id,
            outcome=event.outcome,
            attributes=event.attributes,
            previous_hash=previous_hash,
            event_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            occurred_at=datetime.fromisoformat(event.occurred_at),
        )
    )
    session.commit()


def record_audit(session: Session, **kwargs: Any) -> AuditEvent:
    event = audit_log.record(**kwargs)
    persist_audit_event(session, event)
    return event


def persisted_audit_events(
    session: Session, tenant_id: str, limit: int
) -> list[dict[str, Any]]:
    from supportsense.db_models import AuditRecord

    records = session.scalars(
        select(AuditRecord)
        .where(AuditRecord.tenant_id == tenant_id)
        .order_by(AuditRecord.occurred_at.desc())
        .limit(limit)
    ).all()
    records.reverse()
    return [
        {
            "event_id": record.id,
            "occurred_at": record.occurred_at.isoformat(),
            "event_type": record.event_type,
            "actor_id": record.actor_id,
            "request_id": record.request_id,
            "resource_id": record.resource_id,
            "outcome": record.outcome,
            "attributes": record.attributes,
            "previous_hash": record.previous_hash,
            "event_hash": record.event_hash,
        }
        for record in records
    ]
