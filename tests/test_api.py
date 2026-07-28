from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from supportsense.api import app
from supportsense.audit import audit_log
from supportsense.config import settings
from supportsense.store import analysis_store
from supportsense.tooling import sandbox_backend

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "data" / "sample_tickets.csv").read_bytes()
AUTH = {"Authorization": "Bearer dev-admin-key"}


def setup_function() -> None:
    analysis_store.clear()
    audit_log.clear()


def test_health_does_not_require_authentication() -> None:
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.headers["x-request-id"]


def test_authenticated_identity_contract() -> None:
    response = TestClient(app).get("/api/v1/auth/me", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "subject": "df76ff796f70d2c9",
        "tenant_id": "demo-tenant",
        "role": "admin",
    }


def test_upload_analyze_chat_and_audit_flow() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/v1/analyses",
            content=SAMPLE,
            headers={**AUTH, "Content-Type": "text/csv", "X-Filename": "tickets.csv"},
        )

        assert created.status_code == 201, created.text
        analysis = created.json()
        assert analysis["row_count"] > 0
        analysis_store.clear()
        persisted = client.get(
            f"/api/v1/analyses/{analysis['analysis_id']}",
            headers=AUTH,
        )
        assert persisted.status_code == 200
        assert persisted.json()["content_sha256"] == analysis["content_sha256"]
        assert analysis["themes"][0]["ticket_ids"]
        ticket_id = analysis["themes"][0]["ticket_ids"][0]
        ticket = client.get(f"/api/v1/tickets/{ticket_id}", headers=AUTH)
        assert ticket.status_code == 200
        assert ticket.json()["ticket_id"] == ticket_id

        chat = client.post(
            f"/v1/analyses/{analysis['analysis_id']}/chat",
            json={"question": "How many high priority tickets are there?"},
            headers=AUTH,
        )
        assert chat.status_code == 200
        assert chat.json()["method"] == "deterministic_count"

        audit = client.get("/v1/audit-events", headers=AUTH)
        assert audit.status_code == 200
        events = audit.json()
        assert [event["event_type"] for event in events[-3:]] == [
            "analysis.created",
            "analysis.viewed",
            "chat.answered",
        ]
        assert "question" not in events[-1]["attributes"]
        assert events[-1]["attributes"]["text_sha256"]
        assert events[-1]["event_hash"]
        assert events[-1]["previous_hash"] == events[-2]["event_hash"]


def test_supervisor_can_run_and_persist_release_evaluation() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/evals/run", headers=AUTH)

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "passed"
        assert payload["passed"]
        assert payload["metrics"]["safety_pass_rate"] == 1


def test_conversation_intelligence_uses_persisted_ticket_citations() -> None:
    with TestClient(app) as client:
        analysis = client.post(
            "/v1/analyses",
            content=SAMPLE,
            headers={**AUTH, "Content-Type": "text/csv", "X-Filename": "tickets.csv"},
        ).json()
        conversation = client.post(
            "/api/v1/conversations",
            json={"analysis_id": analysis["analysis_id"], "channel": "web"},
            headers=AUTH,
        )
        assert conversation.status_code == 201, conversation.text

        answer = client.post(
            "/api/v1/chat",
            json={
                "conversation_id": conversation.json()["conversation_id"],
                "message": "What are the top high priority ticket themes?",
                "idempotency_key": f"ci-answer-{uuid4()}",
            },
            headers=AUTH,
        )
        assert answer.status_code == 200, answer.text
        payload = answer.json()
        assert payload["intent"] == "conversation_intelligence"
        assert payload["citations"]
        assert all(citation.startswith("TCK-") for citation in payload["citations"])


def test_agent_audit_links_stored_prompt_and_response_messages() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "Check invoice inv_demo for customer cus_demo",
                "idempotency_key": f"audit-message-links-{uuid4()}",
            },
            headers=AUTH,
        )
        assert response.status_code == 200, response.text
        conversation_id = response.json()["conversation_id"]

        detail = client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=AUTH,
        ).json()
        events = client.get(
            "/api/v1/admin/audit-events?limit=500",
            headers=AUTH,
        ).json()
        event = next(
            item
            for item in reversed(events)
            if item["event_type"] == "agent.response.created"
            and item["resource_id"] == conversation_id
        )

        assert event["attributes"]["prompt_message_id"] == detail["messages"][0][
            "message_id"
        ]
        assert event["attributes"]["response_message_id"] == detail["messages"][1][
            "message_id"
        ]
        assert event["outcome"] == "succeeded"


def test_api_requires_authentication() -> None:
    response = TestClient(app).post(
        "/v1/analyses",
        content=SAMPLE,
        headers={"Content-Type": "text/csv", "X-Filename": "tickets.csv"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_multi_turn_conversation_persists_bounded_memory() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"channel": "web"},
            headers=AUTH,
        )
        assert created.status_code == 201, created.text
        conversation_id = created.json()["conversation_id"]

        for content in [
            "Our enterprise customers are reporting failed exports.",
            "Focus on the high priority cases.",
        ]:
            message = client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": content},
                headers=AUTH,
            )
            assert message.status_code == 201, message.text

        detail = client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=AUTH,
        )
        assert detail.status_code == 200
        payload = detail.json()
        assert len(payload["messages"]) == 2
        assert payload["memory"]["turn_count"] >= 2
        assert "high priority" in payload["summary"].lower()


def test_tools_are_idempotent_and_sensitive_actions_require_approval() -> None:
    with TestClient(app) as client:
        conversation = client.post(
            "/api/v1/conversations", json={"channel": "web"}, headers=AUTH
        ).json()
        conversation_id = conversation["conversation_id"]

        before = sandbox_backend.executions.get("get_customer", 0)
        request = {
            "arguments": {"customer_id": "cus_demo"},
            "idempotency_key": f"read-customer-{uuid4()}",
        }
        first = client.post(
            f"/api/v1/conversations/{conversation_id}/tools/get_customer",
            json=request,
            headers=AUTH,
        )
        second = client.post(
            f"/api/v1/conversations/{conversation_id}/tools/get_customer",
            json=request,
            headers=AUTH,
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["status"] == "succeeded"
        assert first.json()["tool_log_id"] == second.json()["tool_log_id"]
        assert sandbox_backend.executions["get_customer"] == before + 1

        refund_request = {
            "arguments": {
                "customer_id": "cus_demo",
                "payment_id": "pay_demo",
                "amount_cents": 2500,
                "reason": "Duplicate charge",
            },
            "idempotency_key": f"refund-demo-{uuid4()}",
        }
        pending = client.post(
            f"/api/v1/conversations/{conversation_id}/tools/refund_customer",
            json=refund_request,
            headers=AUTH,
        )
        assert pending.status_code == 200
        assert pending.json()["status"] == "approval_required"
        assert sandbox_backend.executions.get("refund_customer", 0) == 0
        replayed_pending = client.post(
            f"/api/v1/conversations/{conversation_id}/tools/refund_customer",
            json=refund_request,
            headers=AUTH,
        )
        assert replayed_pending.status_code == 200
        assert replayed_pending.json()["approval_id"] == pending.json()["approval_id"]

        approvals = client.get(
            "/api/v1/approvals?status=pending",
            headers=AUTH,
        )
        assert approvals.status_code == 200
        assert any(
            item["approval_id"] == pending.json()["approval_id"]
            for item in approvals.json()
        )

        approval_id = pending.json()["approval_id"]
        decision = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"approved": True, "reason": "Verified duplicate"},
            headers=AUTH,
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "approved"

        executed = client.post(
            f"/api/v1/conversations/{conversation_id}/tools/refund_customer",
            json={**refund_request, "approval_id": approval_id},
            headers=AUTH,
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["status"] == "succeeded"
        assert executed.json()["result"]["amount_cents"] == 2500
        assert sandbox_backend.executions["refund_customer"] == 1


def test_sensitive_tool_and_approval_audit_fields_are_redacted() -> None:
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/v1/conversations", json={"channel": "web"}, headers=AUTH
        ).json()["conversation_id"]
        tool_request = {
            "arguments": {
                "customer_id": "cus_demo",
                "payment_method_token": "pm_secret_12345678",
            },
            "idempotency_key": f"billing-audit-{uuid4()}",
        }
        pending = client.post(
            f"/api/v1/conversations/{conversation_id}/tools/update_billing",
            json=tool_request,
            headers=AUTH,
        )
        assert pending.status_code == 200, pending.text
        assert pending.json()["status"] == "approval_required"

        decision = client.post(
            f"/api/v1/approvals/{pending.json()['approval_id']}/decision",
            json={
                "approved": False,
                "reason": "Customer owner@example.com did not confirm.",
            },
            headers=AUTH,
        )
        assert decision.status_code == 200, decision.text
        denied_execution = client.post(
            f"/api/v1/conversations/{conversation_id}/tools/update_billing",
            json={**tool_request, "approval_id": pending.json()["approval_id"]},
            headers=AUTH,
        )
        assert denied_execution.status_code == 409
        assert denied_execution.json()["code"] == "approval_denied"

        events = client.get(
            "/api/v1/admin/audit-events?limit=500", headers=AUTH
        ).json()
        tool_event = next(
            event
            for event in events
            if event["resource_id"] == pending.json()["tool_log_id"]
        )
        assert (
            tool_event["attributes"]["arguments"]["payment_method_token"]
            == "[REDACTED]"
        )
        approval_event = next(
            event
            for event in events
            if event["event_type"] == "approval.decided"
            and event["resource_id"] == pending.json()["approval_id"]
        )
        assert (
            approval_event["attributes"]["requested_arguments"][
                "payment_method_token"
            ]
            == "[REDACTED]"
        )
        assert "[EMAIL_REDACTED]" in approval_event["attributes"]["reason"]


def test_authenticated_service_errors_are_durably_audited() -> None:
    with TestClient(app) as client:
        missing = client.get(
            f"/api/v1/tickets/TCK-MISSING-{uuid4().hex}",
            headers=AUTH,
        )
        assert missing.status_code == 404

        events = client.get(
            "/api/v1/admin/audit-events?limit=500", headers=AUTH
        ).json()
        event = next(
            item
            for item in events
            if item["request_id"] == missing.headers["x-request-id"]
        )
        assert event["event_type"] == "request.error"
        assert event["outcome"] == "error"
        assert event["attributes"]["status_code"] == 404
        assert event["attributes"]["code"] == "ticket_not_found"


def test_human_escalation_contains_summary_and_tool_history() -> None:
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/v1/conversations", json={"channel": "web"}, headers=AUTH
        ).json()["conversation_id"]
        client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "Customer cannot find their latest billing details."},
            headers=AUTH,
        )
        client.post(
            f"/api/v1/conversations/{conversation_id}/tools/get_customer",
            json={
                "arguments": {"customer_id": "cus_demo"},
                "idempotency_key": f"handoff-tool-{uuid4()}",
            },
            headers=AUTH,
        )

        response = client.post(
            f"/api/v1/conversations/{conversation_id}/escalate",
            json={"reason": "Customer requested a human agent"},
            headers=AUTH,
        )
        assert response.status_code == 200, response.text
        package = response.json()
        assert package["ticket_id"].startswith("ESC-")
        assert package["conversation_history"][0]["role"] == "user"
        assert package["tool_history"][0]["tool_name"] == "get_customer"
        assert package["summary"]
        assert package["customer_context"]["customer_ids"] == ["cus_demo"]
        assert "memory" in package["customer_context"]
        assert isinstance(package["retrieved_docs"], list)
        assert package["recommended_action"]

        dashboard = client.get("/api/v1/admin/dashboard", headers=AUTH)
        assert dashboard.status_code == 200
        metrics = dashboard.json()
        assert metrics["total_conversations"] >= 1
        assert metrics["escalated_conversations"] >= 1
        assert metrics["top_intents"]
        assert "top_customer_issues" in metrics
        assert "average_response_time_ms" in metrics
        assert "customer_sentiment" in metrics
        assert "automation_opportunities" in metrics


def test_admin_can_register_and_list_tenant_scoped_agent_version() -> None:
    version = f"v-{uuid4().hex[:8]}"
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/agent-versions",
            json={
                "name": "support-agent",
                "version": version,
                "prompt_version": "supportsense-agent-v2",
                "model_config": {"primary": "deterministic-policy-agent"},
                "tool_policy": {"sensitive": "approval_required"},
                "rollout_stage": "shadow",
                "active": True,
            },
            headers=AUTH,
        )
        assert created.status_code == 201, created.text
        assert created.json()["model_config"]["primary"] == "deterministic-policy-agent"
        assert created.json()["active"]

        shadow_chat = client.post(
            "/api/v1/chat",
            json={
                "message": "Check invoice inv_demo for customer cus_demo",
                "idempotency_key": f"version-shadow-{uuid4()}",
            },
            headers=AUTH,
        )
        assert shadow_chat.status_code == 200, shadow_chat.text
        assert shadow_chat.json()["mode"] == "shadow"
        assert shadow_chat.json()["tool_call"] is None
        assert shadow_chat.json()["tool_suggestion"] == "get_invoice"
        assert not shadow_chat.json()["customer_visible"]
        assert shadow_chat.json()["requires_agent_review"]

        versions = client.get(
            "/api/v1/admin/agent-versions",
            headers=AUTH,
        )
        assert versions.status_code == 200
        assert any(item["version"] == version for item in versions.json())

        events = client.get(
            "/api/v1/admin/audit-events?limit=500",
            headers=AUTH,
        ).json()
        event = next(
            item
            for item in events
            if item["event_type"] == "agent_version.created"
            and item["resource_id"] == created.json()["agent_version_id"]
        )
        assert event["outcome"] == "activated"
        assert event["attributes"]["rollout_stage"] == "shadow"


def test_shadow_mode_never_returns_internal_draft_to_customer() -> None:
    version = f"v-{uuid4().hex[:8]}"
    previous_keys = settings.api_keys
    object.__setattr__(
        settings,
        "api_keys",
        "dev-admin-key:demo-tenant:admin,"
        "shadow-customer-token:demo-tenant:customer",
    )
    try:
        with TestClient(app) as client:
            configured = client.post(
                "/api/v1/admin/agent-versions",
                json={
                    "name": "customer-shadow-agent",
                    "version": version,
                    "prompt_version": "supportsense-agent-v2",
                    "model_config": {},
                    "tool_policy": {},
                    "rollout_stage": "shadow",
                    "active": True,
                },
                headers=AUTH,
            )
            assert configured.status_code == 201, configured.text

            customer_auth = {
                "Authorization": "Bearer shadow-customer-token",
            }
            response = client.post(
                "/api/v1/chat",
                json={
                    "message": "Check invoice inv_demo for customer cus_demo",
                    "idempotency_key": f"customer-shadow-{uuid4()}",
                },
                headers=customer_auth,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["answer"] == (
                "Your request was received and will be reviewed by support."
            )
            assert payload["mode"] == "shadow"
            assert not payload["customer_visible"]
            assert payload["requires_agent_review"]
            assert payload["citations"] == []
            assert payload["tool_call"] is None
            assert payload["tool_suggestion"] is None
            assert payload["confidence"] is None

            detail = client.get(
                f"/api/v1/conversations/{payload['conversation_id']}",
                headers=customer_auth,
            )
            assert detail.status_code == 200, detail.text
            assert [message["role"] for message in detail.json()["messages"]] == [
                "user"
            ]
    finally:
        object.__setattr__(settings, "api_keys", previous_keys)
