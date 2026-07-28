from __future__ import annotations

from fastapi.testclient import TestClient

from supportsense.api import app

AUTH = {"Authorization": "Bearer dev-admin-key"}


def test_allowlisted_memory_is_available_to_new_conversations() -> None:
    with TestClient(app) as client:
        stored = client.put(
            "/api/v1/memory",
            json={"key": "preferred_language", "value": "Spanish"},
            headers=AUTH,
        )
        assert stored.status_code == 200, stored.text

        conversation = client.post(
            "/api/v1/conversations",
            json={"channel": "web"},
            headers=AUTH,
        )
        assert (
            conversation.json()["memory"]["long_term"]["preferred_language"]
            == "Spanish"
        )


def test_memory_rejects_secrets_and_unapproved_keys() -> None:
    with TestClient(app) as client:
        secret = client.put(
            "/api/v1/memory",
            json={
                "key": "communication_style",
                "value": "Card 4242 4242 4242 4242",
            },
            headers=AUTH,
        )
        assert secret.status_code == 400
        assert secret.json()["code"] == "unsafe_memory_value"

        unknown = client.put(
            "/api/v1/memory",
            json={"key": "credit_card", "value": "never store this"},
            headers=AUTH,
        )
        assert unknown.status_code == 400
        assert unknown.json()["code"] == "memory_key_not_allowed"
