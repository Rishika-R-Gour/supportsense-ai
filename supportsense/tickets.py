from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from supportsense.db_models import Ticket
from supportsense.errors import ServiceError
from supportsense.models import TicketAssignment, TicketCreate, TicketResponse
from supportsense.security import Principal, Role, require_role


class TicketService:
    def create(
        self,
        session: Session,
        principal: Principal,
        payload: TicketCreate,
    ) -> Ticket:
        ticket = Ticket(
            tenant_id=principal.tenant_id,
            external_ticket_id=f"TCK-{uuid4().hex[:10].upper()}",
            customer_id=payload.customer_id,
            requester_subject=principal.subject,
            subject=payload.subject,
            description=payload.description,
            status="Open",
            priority=payload.priority,
            category=payload.category,
            attributes={},
        )
        session.add(ticket)
        session.commit()
        return ticket

    def list(
        self,
        session: Session,
        principal: Principal,
        *,
        limit: int,
    ) -> list[Ticket]:
        statement = self._visible_query(principal).order_by(
            Ticket.updated_at.desc()
        ).limit(limit)
        return list(session.scalars(statement).all())

    def get(
        self,
        session: Session,
        principal: Principal,
        ticket_id: str,
    ) -> Ticket:
        ticket = session.scalar(
            self._visible_query(principal).where(
                Ticket.external_ticket_id == ticket_id
            )
        )
        if ticket is None:
            # Deliberately hide whether an inaccessible ticket exists.
            raise ServiceError("ticket_not_found", "Ticket not found.", 404)
        return ticket

    def assign(
        self,
        session: Session,
        principal: Principal,
        ticket_id: str,
        payload: TicketAssignment,
    ) -> Ticket:
        require_role(principal, Role.SUPERVISOR)
        ticket = session.scalar(
            select(Ticket).where(
                Ticket.tenant_id == principal.tenant_id,
                Ticket.external_ticket_id == ticket_id,
            )
        )
        if ticket is None:
            raise ServiceError("ticket_not_found", "Ticket not found.", 404)
        ticket.assigned_to = payload.assigned_to
        session.commit()
        return ticket

    @staticmethod
    def response(ticket: Ticket) -> TicketResponse:
        return TicketResponse(
            ticket_id=ticket.external_ticket_id,
            customer_id=ticket.customer_id,
            requester_subject=ticket.requester_subject,
            assigned_to=ticket.assigned_to,
            subject=ticket.subject,
            description=ticket.description,
            status=ticket.status,
            priority=ticket.priority,
            category=ticket.category,
            attributes=ticket.attributes or {},
        )

    @staticmethod
    def _visible_query(principal: Principal) -> Select[tuple[Ticket]]:
        statement = select(Ticket).where(Ticket.tenant_id == principal.tenant_id)
        if principal.role == Role.CUSTOMER:
            return statement.where(Ticket.requester_subject == principal.subject)
        if principal.role == Role.AGENT:
            return statement.where(Ticket.assigned_to == principal.subject)
        return statement


ticket_service = TicketService()
