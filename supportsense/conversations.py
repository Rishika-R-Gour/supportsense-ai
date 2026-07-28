from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportsense.config import settings
from supportsense.db_models import Conversation, Message, Tenant, User, now
from supportsense.errors import ServiceError
from supportsense.models import (
    ConversationDetail,
    ConversationResponse,
    MessageResponse,
)
from supportsense.security import Principal, Role, require_role


class ConversationService:
    def ensure_identity(self, session: Session, principal: Principal) -> User:
        tenant = session.get(Tenant, principal.tenant_id)
        if tenant is None:
            tenant = Tenant(id=principal.tenant_id, name=principal.tenant_id)
            session.add(tenant)
            session.flush()

        user = session.scalar(
            select(User).where(
                User.tenant_id == principal.tenant_id,
                User.external_subject == principal.subject,
            )
        )
        if user is None:
            user = User(
                tenant_id=principal.tenant_id,
                external_subject=principal.subject,
                role=principal.role.value,
            )
            session.add(user)
        else:
            user.role = principal.role.value
            user.active = True
        session.flush()
        return user

    def create(
        self,
        session: Session,
        principal: Principal,
        *,
        analysis_id: str | None,
        channel: str,
    ) -> Conversation:
        if analysis_id is not None:
            require_role(principal, Role.AGENT)
        user = self.ensure_identity(session, principal)
        from supportsense.db_models import MemoryFact

        facts = session.scalars(
            select(MemoryFact).where(
                MemoryFact.tenant_id == principal.tenant_id,
                MemoryFact.user_id == user.id,
            )
        ).all()
        conversation = Conversation(
            tenant_id=principal.tenant_id,
            user_id=user.id,
            analysis_id=analysis_id,
            channel=channel,
            memory={
                "turn_count": 0,
                "recent_topics": [],
                "long_term": {fact.key: fact.value for fact in facts},
            },
        )
        session.add(conversation)
        session.commit()
        return conversation

    def get(
        self, session: Session, principal: Principal, conversation_id: str
    ) -> Conversation:
        conversation = session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == principal.tenant_id,
            )
        )
        if conversation is None:
            raise ServiceError("conversation_not_found", "Conversation not found.", 404)
        if principal.role == Role.CUSTOMER:
            owner = session.get(User, conversation.user_id) if conversation.user_id else None
            if owner is None or owner.external_subject != principal.subject:
                raise ServiceError(
                    "conversation_not_found",
                    "Conversation not found.",
                    404,
                )
        return conversation

    def list(
        self,
        session: Session,
        principal: Principal,
        *,
        limit: int,
    ) -> list[Conversation]:
        statement = select(Conversation).where(
            Conversation.tenant_id == principal.tenant_id
        )
        if principal.role == Role.CUSTOMER:
            user = self.ensure_identity(session, principal)
            statement = statement.where(Conversation.user_id == user.id)
        return list(
            session.scalars(
                statement.order_by(Conversation.updated_at.desc()).limit(limit)
            ).all()
        )

    def add_message(
        self,
        session: Session,
        principal: Principal,
        conversation_id: str,
        *,
        role: str,
        content: str,
        citations: list[dict] | None = None,
        tool_calls: list[dict] | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        latency_ms: float | None = None,
        cost_usd: float = 0,
    ) -> Message:
        conversation = self.get(session, principal, conversation_id)
        if conversation.status != "open":
            raise ServiceError(
                "conversation_closed",
                "Messages cannot be added to a closed conversation.",
                409,
            )
        normalized = content.strip()
        message = Message(
            tenant_id=principal.tenant_id,
            conversation_id=conversation.id,
            role=role,
            content=normalized,
            content_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            citations=citations or [],
            tool_calls=tool_calls or [],
            model=model,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
        session.add(message)
        session.flush()
        self._refresh_memory(session, conversation)
        conversation.updated_at = now()
        session.commit()
        return message

    def detail(
        self, session: Session, principal: Principal, conversation_id: str
    ) -> ConversationDetail:
        conversation = self.get(session, principal, conversation_id)
        statement = select(Message).where(
            Message.conversation_id == conversation.id,
            Message.tenant_id == principal.tenant_id,
        )
        if principal.role == Role.CUSTOMER:
            statement = statement.where(Message.role != "assistant_internal")
        messages = session.scalars(statement.order_by(Message.created_at.asc())).all()
        payload = self.response(conversation).model_dump()
        payload["messages"] = [self.message_response(message) for message in messages]
        return ConversationDetail.model_validate(payload)

    def _refresh_memory(self, session: Session, conversation: Conversation) -> None:
        recent = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(settings.conversation_window)
        ).all()
        recent.reverse()
        snippets = [
            f"{message.role}: {' '.join(message.content.split())[:240]}"
            for message in recent
            if message.role in {"user", "assistant"}
        ]
        user_topics = [
            " ".join(message.content.split())[:100]
            for message in recent
            if message.role == "user"
        ]
        previous_count = int((conversation.memory or {}).get("turn_count", 0))
        conversation.summary = "\n".join(snippets) or None
        conversation.memory = {
            "turn_count": max(previous_count + 1, len(recent)),
            "recent_topics": user_topics[-5:],
            "window_size": len(recent),
            "long_term": (conversation.memory or {}).get("long_term", {}),
        }

    @staticmethod
    def response(conversation: Conversation) -> ConversationResponse:
        return ConversationResponse(
            conversation_id=conversation.id,
            status=conversation.status,
            channel=conversation.channel,
            summary=conversation.summary,
            memory=conversation.memory or {},
            intent=conversation.intent,
            outcome=conversation.outcome,
            escalated=conversation.escalated,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    @staticmethod
    def message_response(message: Message) -> MessageResponse:
        return MessageResponse(
            message_id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            citations=message.citations or [],
            tool_calls=message.tool_calls or [],
            created_at=message.created_at,
        )


conversation_service = ConversationService()
