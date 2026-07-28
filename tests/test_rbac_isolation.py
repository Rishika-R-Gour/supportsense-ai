from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from supportsense import db_models  # noqa: F401
from supportsense.conversations import conversation_service
from supportsense.database import Base
from supportsense.errors import ServiceError
from supportsense.models import TicketAssignment, TicketCreate
from supportsense.security import Principal, Role
from supportsense.tickets import ticket_service
from supportsense.tooling import ToolExecutor, sandbox_backend


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def test_customers_only_see_their_own_conversations() -> None:
    customer_one = Principal("customer-one", "tenant-rbac", Role.CUSTOMER)
    customer_two = Principal("customer-two", "tenant-rbac", Role.CUSTOMER)
    agent = Principal("agent-one", "tenant-rbac", Role.AGENT)

    with _session() as session:
        first = conversation_service.create(
            session, customer_one, analysis_id=None, channel="web"
        )
        second = conversation_service.create(
            session, customer_two, analysis_id=None, channel="web"
        )

        assert [item.id for item in conversation_service.list(
            session, customer_one, limit=20
        )] == [first.id]
        with pytest.raises(ServiceError, match="Conversation not found"):
            conversation_service.get(session, customer_one, second.id)
        assert conversation_service.get(session, agent, second.id).id == second.id


def test_ticket_visibility_follows_owner_assignment_and_supervisor_rules() -> None:
    customer_one = Principal("customer-one", "tenant-rbac", Role.CUSTOMER)
    customer_two = Principal("customer-two", "tenant-rbac", Role.CUSTOMER)
    agent = Principal("agent-one", "tenant-rbac", Role.AGENT)
    supervisor = Principal("supervisor-one", "tenant-rbac", Role.SUPERVISOR)

    with _session() as session:
        ticket = ticket_service.create(
            session,
            customer_one,
            TicketCreate(
                subject="Invoice is missing",
                description="The annual invoice is not visible.",
            ),
        )

        assert ticket_service.get(
            session, customer_one, ticket.external_ticket_id
        ).id == ticket.id
        with pytest.raises(ServiceError, match="Ticket not found"):
            ticket_service.get(session, customer_two, ticket.external_ticket_id)
        with pytest.raises(ServiceError, match="Ticket not found"):
            ticket_service.get(session, agent, ticket.external_ticket_id)

        ticket_service.assign(
            session,
            supervisor,
            ticket.external_ticket_id,
            TicketAssignment(assigned_to=agent.subject),
        )
        assert ticket_service.get(
            session, agent, ticket.external_ticket_id
        ).assigned_to == agent.subject
        assert ticket_service.get(
            session, supervisor, ticket.external_ticket_id
        ).id == ticket.id


def test_customer_tool_access_is_bound_to_authenticated_subject() -> None:
    customer = Principal("cus_demo", "tenant-rbac", Role.CUSTOMER)
    with _session() as session:
        conversation = conversation_service.create(
            session, customer, analysis_id=None, channel="web"
        )
        executor = ToolExecutor(sandbox_backend)

        own = executor.execute(
            session,
            customer,
            conversation_id=conversation.id,
            tool_name="get_customer",
            arguments={"customer_id": "cus_demo"},
            idempotency_key="customer-own-record",
        )
        assert own.status == "succeeded"

        with pytest.raises(ServiceError, match="only access their own"):
            executor.execute(
                session,
                customer,
                conversation_id=conversation.id,
                tool_name="get_customer",
                arguments={"customer_id": "cus_someone_else"},
                idempotency_key="customer-cross-record",
            )


def test_customer_cannot_attach_private_analysis_to_conversation() -> None:
    customer = Principal("customer-one", "tenant-rbac", Role.CUSTOMER)
    with _session() as session, pytest.raises(
        ServiceError,
        match="requires the agent role",
    ):
        conversation_service.create(
            session,
            customer,
            analysis_id="private-analysis",
            channel="web",
        )
