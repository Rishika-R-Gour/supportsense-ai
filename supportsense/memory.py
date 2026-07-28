from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportsense.conversations import conversation_service
from supportsense.db_models import MemoryFact
from supportsense.errors import ServiceError
from supportsense.guardrails import redact_pii, validate_input
from supportsense.models import MemoryFactResponse
from supportsense.security import Principal

ALLOWED_MEMORY_KEYS = {
    "preferred_language",
    "communication_style",
    "product_area",
    "timezone",
    "accessibility_preference",
}


class LongTermMemoryService:
    def remember(
        self,
        session: Session,
        principal: Principal,
        *,
        key: str,
        value: str,
        conversation_id: str | None,
    ) -> MemoryFact:
        if key not in ALLOWED_MEMORY_KEYS:
            raise ServiceError(
                "memory_key_not_allowed",
                "This information is not permitted in long-term memory.",
            )
        decision = validate_input(value)
        if decision.reason in {"prompt_injection", "sensitive_data"}:
            raise ServiceError(
                "unsafe_memory_value",
                "Sensitive data and instructions cannot be stored in memory.",
            )
        if conversation_id:
            conversation_service.get(session, principal, conversation_id)
        user = conversation_service.ensure_identity(session, principal)
        fact = session.scalar(
            select(MemoryFact).where(
                MemoryFact.tenant_id == principal.tenant_id,
                MemoryFact.user_id == user.id,
                MemoryFact.key == key,
            )
        )
        if fact is None:
            fact = MemoryFact(
                tenant_id=principal.tenant_id,
                user_id=user.id,
                conversation_id=conversation_id,
                key=key,
                value=redact_pii(value.strip()),
            )
            session.add(fact)
        else:
            fact.value = redact_pii(value.strip())
            fact.conversation_id = conversation_id
        session.commit()
        return fact

    def list(
        self, session: Session, principal: Principal
    ) -> list[MemoryFactResponse]:
        user = conversation_service.ensure_identity(session, principal)
        facts = session.scalars(
            select(MemoryFact)
            .where(
                MemoryFact.tenant_id == principal.tenant_id,
                MemoryFact.user_id == user.id,
            )
            .order_by(MemoryFact.key)
        ).all()
        return [
            MemoryFactResponse(
                key=fact.key,
                value=fact.value,
                confidence=fact.confidence,
                updated_at=fact.updated_at,
            )
            for fact in facts
        ]

    def as_dict(self, session: Session, principal: Principal) -> dict[str, str]:
        return {fact.key: fact.value for fact in self.list(session, principal)}


long_term_memory = LongTermMemoryService()
