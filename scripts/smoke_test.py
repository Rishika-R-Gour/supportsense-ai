from __future__ import annotations

import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


def request(
    base_url: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
) -> tuple[dict, dict[str, str]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    method = "POST" if payload is not None else "GET"
    with urlopen(
        Request(
            f"{base_url.rstrip('/')}{path}",
            data=data,
            headers=headers,
            method=method,
        ),
        timeout=5,
    ) as response:
        return (
            json.loads(response.read().decode("utf-8")),
            {key.lower(): value for key, value in response.headers.items()},
        )


def request_text(base_url: str, path: str) -> str:
    with urlopen(f"{base_url.rstrip('/')}{path}", timeout=5) as response:
        return response.read().decode("utf-8")


def wait_until_ready(base_url: str, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            payload, _ = request(base_url, "/health/ready")
            if payload.get("status") == "ready":
                return
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(1)
    raise RuntimeError("SupportSense did not become ready before the deadline")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--exercise-vector", action="store_true")
    args = parser.parse_args()

    wait_until_ready(args.base_url)
    live, live_headers = request(args.base_url, "/health/live")
    assert live["status"] == "ok"
    assert live_headers["x-request-id"]
    assert live_headers["cache-control"] == "no-store"

    identity, _ = request(args.base_url, "/api/v1/auth/me", token=args.token)
    assert identity["tenant_id"]
    assert identity["role"] in {"customer", "agent", "supervisor", "admin"}

    openapi, _ = request(args.base_url, "/openapi.json")
    assert "/api/v1/chat" in openapi["paths"]
    assert "/api/v1/agent-assist" in openapi["paths"]

    chat, _ = request(
        args.base_url,
        "/api/v1/chat",
        token=args.token,
        payload={
            "message": "Can you find my latest invoice?",
            "idempotency_key": f"smoke-{uuid4()}",
        },
    )
    assert chat["intent"] == "invoice_request"
    assert chat["answer"]
    assert chat["conversation_id"]
    if args.exercise_vector:
        source, _ = request(
            args.base_url,
            "/api/v1/knowledge-sources",
            token=args.token,
            payload={
                "title": "Smoke-test API authentication guide",
                "uri": "https://docs.example.test/smoke-api-auth",
                "chunks": [
                    {
                        "content": (
                            "Rotate exposed API authentication keys immediately "
                            "and revoke the old credential."
                        ),
                        "metadata": {"topic": "api_auth"},
                    }
                ],
            },
        )
        assert source["status"] == "active"
        grounded, _ = request(
            args.base_url,
            "/api/v1/chat",
            token=args.token,
            payload={
                "message": "How should an exposed API authentication key be rotated?",
                "idempotency_key": f"smoke-vector-{uuid4()}",
            },
        )
        assert grounded["citations"]
        metrics = request_text(args.base_url, "/metrics")
        assert (
            'supportsense_vector_store_operations_total{operation="index",outcome="success"}'
            in metrics
        )
        assert (
            'supportsense_vector_store_operations_total{operation="search",outcome="success"}'
            in metrics
        )
    print("SupportSense smoke test passed")


if __name__ == "__main__":
    main()
