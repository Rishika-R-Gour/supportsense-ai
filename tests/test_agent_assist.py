from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from supportsense.api import app
from supportsense.tooling import sandbox_backend

AUTH = {"Authorization": "Bearer dev-admin-key"}


def test_agent_assist_can_read_but_only_suggests_write_actions() -> None:
    with TestClient(app) as client:
        read = client.post(
            "/api/v1/agent-assist",
            json={
                "message": "Check invoice inv_demo for customer cus_demo",
                "idempotency_key": f"assist-read-{uuid4()}",
            },
            headers=AUTH,
        )
        assert read.status_code == 200, read.text
        assert read.json()["tool_call"]["status"] == "succeeded"
        assert read.json()["requires_agent_review"]
        assert not read.json()["customer_visible"]

        before = sandbox_backend.executions.get("resend_invoice", 0)
        write = client.post(
            "/api/v1/agent-assist",
            json={
                "message": "Resend invoice inv_demo for customer cus_demo",
                "idempotency_key": f"assist-write-{uuid4()}",
            },
            headers=AUTH,
        )
        assert write.status_code == 200, write.text
        assert write.json()["tool_call"] is None
        assert "Suggested action" in write.json()["answer"]
        assert sandbox_backend.executions.get("resend_invoice", 0) == before
