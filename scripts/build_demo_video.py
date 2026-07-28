from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "outputs" / "supportsense-production-demo.mp4"
WIDTH = 1920
HEIGHT = 1080
BACKGROUND = "#07111f"
PANEL = "#111f31"
PANEL_ALT = "#172940"
TEXT = "#f4f7fb"
MUTED = "#9fb1c7"
TEAL = "#2dd4bf"
BLUE = "#70a5ff"
AMBER = "#f8c56b"
RED = "#ff7b7b"


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/SFCompact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


TITLE = _font(64)
SUBTITLE = _font(30)
LABEL = _font(23)
VALUE = _font(48)
BODY = _font(27)
SMALL = _font(22)


def _request(client, method: str, path: str, token: str, **kwargs) -> dict[str, Any]:
    response = client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})},
        **kwargs,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
    return response.json()


def collect_live_demo() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="supportsense-demo-") as work:
        os.environ["DATABASE_URL"] = f"sqlite:///{work}/demo.db"
        os.environ["SUPPORTSENSE_ENV"] = "development"
        os.environ["SUPPORTSENSE_ROLLOUT_STAGE"] = "limited_automation"
        os.environ["SUPPORTSENSE_TOOL_BACKEND"] = "sandbox"
        os.environ["SUPPORTSENSE_API_KEYS"] = ",".join(
            [
                "demo-admin:video-tenant:admin",
                "demo-agent:video-tenant:agent",
                "demo-supervisor:video-tenant:supervisor",
            ]
        )

        from fastapi.testclient import TestClient

        from supportsense.api import app
        from supportsense.audit import audit_log
        from supportsense.store import analysis_store

        analysis_store.clear()
        audit_log.clear()
        sample = (ROOT / "data" / "sample_tickets.csv").read_bytes()
        with TestClient(app) as client:
            analysis = _request(
                client,
                "POST",
                "/api/v1/analyses",
                "demo-admin",
                content=sample,
                headers={
                    "Content-Type": "text/csv",
                    "X-Filename": "sample_tickets.csv",
                },
            )
            conversation = _request(
                client,
                "POST",
                "/api/v1/conversations",
                "demo-admin",
                json={"analysis_id": analysis["analysis_id"], "channel": "web"},
            )
            first_turn = _request(
                client,
                "POST",
                "/api/v1/chat",
                "demo-admin",
                json={
                    "conversation_id": conversation["conversation_id"],
                    "message": "What are the top high priority ticket themes?",
                    "idempotency_key": f"video-chat-{uuid4()}",
                },
            )
            second_turn = _request(
                client,
                "POST",
                "/api/v1/chat",
                "demo-admin",
                json={
                    "conversation_id": conversation["conversation_id"],
                    "message": "What about billing?",
                    "idempotency_key": f"video-chat-{uuid4()}",
                },
            )
            assist = _request(
                client,
                "POST",
                "/api/v1/agent-assist",
                "demo-agent",
                json={
                    "conversation_id": conversation["conversation_id"],
                    "message": "Check invoice inv_demo for customer cus_demo",
                    "idempotency_key": f"video-assist-{uuid4()}",
                },
            )

            action_conversation = _request(
                client,
                "POST",
                "/api/v1/conversations",
                "demo-admin",
                json={"channel": "web"},
            )
            refund_payload = {
                "arguments": {
                    "customer_id": "cus_demo",
                    "payment_id": "pay_demo",
                    "amount_cents": 2500,
                    "reason": "Verified duplicate charge",
                },
                "idempotency_key": f"video-refund-{uuid4()}",
            }
            refund_pending = _request(
                client,
                "POST",
                (
                    "/api/v1/conversations/"
                    f"{action_conversation['conversation_id']}/tools/refund_customer"
                ),
                "demo-admin",
                json=refund_payload,
            )
            approval = _request(
                client,
                "POST",
                f"/api/v1/approvals/{refund_pending['approval_id']}/decision",
                "demo-supervisor",
                json={"approved": True, "reason": "Duplicate charge verified"},
            )
            refund_executed = _request(
                client,
                "POST",
                (
                    "/api/v1/conversations/"
                    f"{action_conversation['conversation_id']}/tools/refund_customer"
                ),
                "demo-admin",
                json={**refund_payload, "approval_id": refund_pending["approval_id"]},
            )
            handoff = _request(
                client,
                "POST",
                f"/api/v1/conversations/{conversation['conversation_id']}/escalate",
                "demo-admin",
                json={"reason": "Customer requested a human specialist"},
            )
            dashboard = _request(
                client,
                "GET",
                "/api/v1/admin/dashboard",
                "demo-supervisor",
            )
            audits = _request(
                client,
                "GET",
                "/api/v1/admin/audit-events?limit=500",
                "demo-supervisor",
            )

    evaluation = json.loads(
        (ROOT / "outputs" / "production-eval-results.json").read_text()
    )
    return {
        "analysis": analysis,
        "first_turn": first_turn,
        "second_turn": second_turn,
        "assist": assist,
        "refund_pending": refund_pending,
        "approval": approval,
        "refund_executed": refund_executed,
        "handoff": handoff,
        "dashboard": dashboard,
        "audit_count": len(audits),
        "evaluation": evaluation,
    }


def _wrapped(text: str, width: int) -> list[str]:
    return textwrap.wrap(" ".join(str(text).split()), width=width) or [""]


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    font: ImageFont.FreeTypeFont,
    fill: str = TEXT,
    *,
    width: int | None = None,
    spacing: int = 10,
    max_lines: int | None = None,
) -> int:
    lines = _wrapped(value, width) if width else [value]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .") + "…"
    draw.multiline_text(xy, "\n".join(lines), font=font, fill=fill, spacing=spacing)
    return xy[1] + len(lines) * (font.size + spacing)


def _base(title: str, subtitle: str, step: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((90, 70, 220, 112), radius=21, fill="#16384a")
    draw.text((115, 79), "SUPPORTSENSE", font=LABEL, fill=TEAL)
    draw.text((1675, 79), step, font=LABEL, fill=MUTED)
    draw.text((90, 160), title, font=TITLE, fill=TEXT)
    draw.text((94, 242), subtitle, font=SUBTITLE, fill=MUTED)
    return image, draw


def _card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    body: str,
    *,
    accent: str = TEAL,
) -> None:
    draw.rounded_rectangle(box, radius=26, fill=PANEL, outline="#29445f", width=2)
    x1, y1, x2, _ = box
    draw.rounded_rectangle((x1, y1, x1 + 12, y1 + 92), radius=6, fill=accent)
    draw.text((x1 + 34, y1 + 28), label.upper(), font=LABEL, fill=accent)
    draw.text((x1 + 34, y1 + 82), value, font=VALUE, fill=TEXT)
    _text(
        draw,
        (x1 + 34, y1 + 160),
        body,
        BODY,
        MUTED,
        width=max(24, (x2 - x1) // 16),
        spacing=12,
        max_lines=9,
    )


def build_frames(data: dict[str, Any], directory: Path) -> list[Path]:
    dashboard = data["dashboard"]
    evaluation = data["evaluation"]
    metrics = evaluation["metrics"]
    frames: list[Image.Image] = []

    image, draw = _base(
        "Production AI support, end to end",
        "A verified walkthrough generated from real SupportSense API responses",
        "01 / 08",
    )
    draw.rounded_rectangle((90, 350, 1830, 895), radius=38, fill=PANEL_ALT)
    draw.text((145, 420), "AI Agent", font=VALUE, fill=TEAL)
    draw.text((735, 420), "Agent Assist", font=VALUE, fill=BLUE)
    draw.text((1285, 420), "Conversation Intelligence", font=VALUE, fill=AMBER)
    _text(
        draw,
        (145, 510),
        "Multi-turn memory, grounded retrieval, typed tools, guardrails, and human escalation.",
        BODY,
        MUTED,
        width=31,
    )
    _text(
        draw,
        (735, 510),
        "Cited draft replies, customer context, ticket history, tool suggestions, and approvals.",
        BODY,
        MUTED,
        width=31,
    )
    _text(
        draw,
        (1285, 510),
        "Intent, containment, escalation, latency, knowledge gaps, sentiment, and automation.",
        BODY,
        MUTED,
        width=31,
    )
    draw.text(
        (145, 790),
        f"Loaded {data['analysis']['row_count']} synthetic support tickets",
        font=SUBTITLE,
        fill=TEXT,
    )
    frames.append(image)

    image, draw = _base(
        "Conversation Intelligence",
        "Tenant-scoped operational metrics computed from persisted conversations and tickets",
        "02 / 08",
    )
    _card(
        draw,
        (90, 340, 630, 900),
        "Containment",
        f"{dashboard['containment_rate']:.0%}",
        f"{dashboard['contained_conversations']} of "
        f"{dashboard['total_conversations']} conversations safely contained.",
    )
    _card(
        draw,
        (690, 340, 1230, 900),
        "Escalation",
        f"{dashboard['escalation_rate']:.0%}",
        f"{dashboard['escalated_conversations']} conversation handed to a human with context.",
        accent=AMBER,
    )
    top_intent = (dashboard["top_intents"] or [{"name": "unknown", "count": 0}])[0]
    _card(
        draw,
        (1290, 340, 1830, 900),
        "Top intent",
        top_intent["name"].replace("_", " ").title(),
        f"{top_intent['count']} observed. Tool failures: "
        f"{dashboard['failed_tool_calls']}. Audit events: {data['audit_count']}.",
        accent=BLUE,
    )
    frames.append(image)

    first = data["first_turn"]
    second = data["second_turn"]
    image, draw = _base(
        "AI Agent: multi-turn and grounded",
        "The second answer reuses conversation context; cited ticket IDs remain inspectable",
        "03 / 08",
    )
    _card(
        draw,
        (90, 340, 930, 900),
        "Turn 1",
        first["intent"].replace("_", " ").title(),
        first["answer"][:430]
        + f" Citations: {', '.join(first['citations'][:4]) or 'none'}.",
        accent=TEAL,
    )
    _card(
        draw,
        (990, 340, 1830, 900),
        "Turn 2",
        second["intent"].replace("_", " ").title(),
        second["answer"][:430]
        + f" Confidence: {(second.get('confidence') or 0):.0%}.",
        accent=BLUE,
    )
    frames.append(image)

    assist = data["assist"]
    tool_status = (assist.get("tool_call") or {}).get("status", "suggested")
    image, draw = _base(
        "Agent Assist: evidence before action",
        "Read-only assistance is shown to an agent and never sent automatically",
        "04 / 08",
    )
    _card(
        draw,
        (90, 340, 630, 900),
        "Suggested reply",
        assist["intent"].replace("_", " ").title(),
        assist["answer"][:390],
        accent=BLUE,
    )
    _card(
        draw,
        (690, 340, 1230, 900),
        "Tool suggestion",
        assist.get("tool_suggestion") or "None",
        f"Tool status: {tool_status}. Agent review required: "
        f"{assist['requires_agent_review']}. Customer visible: "
        f"{assist['customer_visible']}.",
        accent=TEAL,
    )
    _card(
        draw,
        (1290, 340, 1830, 900),
        "AI confidence",
        f"{(assist.get('confidence') or 0):.0%}",
        f"Evidence references: {', '.join(assist['citations'][:4]) or 'typed tool result'}.",
        accent=AMBER,
    )
    frames.append(image)

    pending = data["refund_pending"]
    executed = data["refund_executed"]
    image, draw = _base(
        "Sensitive action: approval required",
        "Typed parameters, RBAC, stable idempotency, supervisor decision, durable audit",
        "05 / 08",
    )
    _card(
        draw,
        (90, 340, 630, 900),
        "Initial state",
        pending["status"].replace("_", " ").title(),
        "The refund did not execute. The request was persisted for supervisor review.",
        accent=AMBER,
    )
    _card(
        draw,
        (690, 340, 1230, 900),
        "Supervisor",
        data["approval"]["status"].title(),
        "Decision recorded with actor, reason, requested arguments, and hash-chained audit history.",
        accent=BLUE,
    )
    _card(
        draw,
        (1290, 340, 1830, 900),
        "Final state",
        executed["status"].title(),
        f"Refund {executed['result']['refund_id']} submitted for "
        f"${executed['result']['amount_cents'] / 100:.2f}.",
        accent=TEAL,
    )
    frames.append(image)

    handoff = data["handoff"]
    image, draw = _base(
        "Human escalation with complete context",
        "A human receives the history required to continue without making the customer repeat it",
        "06 / 08",
    )
    _card(
        draw,
        (90, 340, 630, 900),
        "Handoff ticket",
        handoff["ticket_id"],
        handoff["summary"][:350],
        accent=AMBER,
    )
    _card(
        draw,
        (690, 340, 1230, 900),
        "Evidence package",
        f"{len(handoff['retrieved_docs'])} docs",
        f"{len(handoff['conversation_history'])} transcript messages and "
        f"{len(handoff['tool_history'])} tool records included.",
        accent=BLUE,
    )
    _card(
        draw,
        (1290, 340, 1830, 900),
        "Next action",
        "Human review",
        handoff["recommended_action"],
        accent=TEAL,
    )
    frames.append(image)

    image, draw = _base(
        "Production release evidence",
        "Reproducible gates prevent unsafe versions from reaching staging or production",
        "07 / 08",
    )
    _card(
        draw,
        (90, 340, 630, 900),
        "Automated tests",
        "All passed",
        "Unit, API, tenant isolation, RAG, resilience, tools, memory, rollout, and storage.",
        accent=TEAL,
    )
    _card(
        draw,
        (690, 340, 1230, 900),
        "Evaluation suite",
        f"{metrics['cases']} / {metrics['cases']}",
        "Intent, retrieval, citations, response, tools, safety, escalation, latency, and cost.",
        accent=BLUE,
    )
    _card(
        draw,
        (1290, 340, 1830, 900),
        "Local P95",
        f"{metrics['p95_latency_ms']:.1f} ms",
        "Provider-free orchestration. Terraform, migrations, OpenAPI, and dependency audit also pass.",
        accent=AMBER,
    )
    frames.append(image)

    image, draw = _base(
        "Ready for staged validation",
        "Offline testing → shadow mode → Agent Assist → limited automation",
        "08 / 08",
    )
    draw.rounded_rectangle((90, 350, 1830, 820), radius=34, fill=PANEL_ALT)
    stages = [
        ("1", "Offline", "140-case gates"),
        ("2", "Shadow", "Observe only"),
        ("3", "Agent Assist", "Human reviews"),
        ("4", "Limited", "Allowlisted automation"),
    ]
    for index, (number, title, note) in enumerate(stages):
        x = 145 + index * 420
        draw.ellipse((x, 430, x + 92, 522), fill=TEAL if index == 0 else "#23415a")
        draw.text((x + 32, 446), number, font=SUBTITLE, fill=BACKGROUND if index == 0 else TEXT)
        draw.text((x, 570), title, font=SUBTITLE, fill=TEXT)
        draw.text((x, 630), note, font=BODY, fill=MUTED)
        if index < 3:
            draw.line((x + 115, 476, x + 385, 476), fill="#375a74", width=5)
    draw.text(
        (90, 915),
        "SupportSense  ·  AI Agent + Agent Assist + Conversation Intelligence",
        font=SUBTITLE,
        fill=TEXT,
    )
    frames.append(image)

    paths: list[Path] = []
    for index, frame in enumerate(frames, 1):
        path = directory / f"frame-{index:02d}.png"
        frame.save(path, optimize=True)
        paths.append(path)
    return paths


def encode_video(frames: list[Path]) -> None:
    if not frames:
        raise RuntimeError("No demo frames were generated")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "1/5",
            "-i",
            str(frames[0].parent / "frame-%02d.png"),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(OUTPUT),
        ],
        check=True,
    )


def main() -> int:
    data = collect_live_demo()
    with tempfile.TemporaryDirectory(prefix="supportsense-video-") as directory:
        frames = build_frames(data, Path(directory))
        encode_video(frames)
    print(f"Created {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
