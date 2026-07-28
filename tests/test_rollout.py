from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from supportsense import db_models  # noqa: F401
from supportsense.agent import SupportAgent
from supportsense.conversations import conversation_service
from supportsense.database import Base
from supportsense.errors import ServiceError
from supportsense.rollout import STAGE_ORDER, RolloutPolicy, RolloutStage
from supportsense.security import Principal, Role


def test_offline_and_shadow_modes_block_execution() -> None:
    for stage in [RolloutStage.OFFLINE, RolloutStage.SHADOW]:
        with pytest.raises(ServiceError) as error:
            RolloutPolicy(stage).enforce_tool("read")
        assert error.value.code == "rollout_blocked"


def test_agent_assist_allows_only_read_tools() -> None:
    policy = RolloutPolicy(RolloutStage.AGENT_ASSIST)
    policy.enforce_tool("read")
    with pytest.raises(ServiceError):
        policy.enforce_tool("write")


def test_limited_automation_keeps_sensitive_tools_in_policy_layer() -> None:
    policy = RolloutPolicy(RolloutStage.LIMITED_AUTOMATION)
    policy.enforce_tool("read")
    policy.enforce_tool("write")
    policy.enforce_tool("sensitive")


def test_full_automation_is_customer_visible_but_keeps_policy_enforcement() -> None:
    policy = RolloutPolicy(RolloutStage.FULL_AUTOMATION)

    assert policy.customer_visible
    for risk in ["read", "write", "sensitive"]:
        policy.enforce_tool(risk)


def test_tenant_rollout_cannot_exceed_global_safety_ceiling() -> None:
    global_stage = RolloutPolicy.current().stage

    assert RolloutPolicy.effective(RolloutStage.FULL_AUTOMATION).stage == global_stage
    assert RolloutPolicy.effective(RolloutStage.OFFLINE).stage == RolloutStage.OFFLINE
    assert STAGE_ORDER.index(
        RolloutPolicy.effective(RolloutStage.AGENT_ASSIST).stage
    ) <= STAGE_ORDER.index(global_stage)


def test_shadow_mode_hides_internal_assistant_message_from_customer_history() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    customer = Principal("cus_demo", "rollout-tenant", Role.CUSTOMER)
    agent = Principal("agent-one", "rollout-tenant", Role.AGENT)

    with Session(engine, expire_on_commit=False) as session:
        conversation = conversation_service.create(
            session,
            customer,
            analysis_id=None,
            channel="web",
        )
        result = SupportAgent(
            session,
            customer,
            RolloutPolicy(RolloutStage.SHADOW),
        ).run(
            conversation_id=conversation.id,
            question="Check invoice inv_demo for customer cus_demo",
            idempotency_key="shadow-customer-invoice",
        )

        customer_detail = conversation_service.detail(
            session,
            customer,
            conversation.id,
        )
        agent_detail = conversation_service.detail(
            session,
            agent,
            conversation.id,
        )

    assert result.get("tool_result") is None
    assert [message.role for message in customer_detail.messages] == ["user"]
    assert [message.role for message in agent_detail.messages] == [
        "user",
        "assistant_internal",
    ]
