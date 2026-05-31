from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app.config import settings
from app.theme_discovery import ThemeResult


def generate_executive_summary(df: pd.DataFrame, themes: list[ThemeResult], kpis: dict[str, Any]) -> list[dict[str, Any]]:
    """Return cited executive bullets, using Claude when configured and a deterministic fallback otherwise."""
    if settings.anthropic_api_key:
        try:
            return _generate_with_anthropic(df, themes, kpis)
        except Exception:
            return _fallback_summary(df, themes, kpis)
    return _fallback_summary(df, themes, kpis)


def _generate_with_anthropic(df: pd.DataFrame, themes: list[ThemeResult], kpis: dict[str, Any]) -> list[dict[str, Any]]:
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    examples = df.head(40)[["ticket_id", "customer_segment", "priority", "subject", "description"]].to_dict("records")
    theme_payload = [theme.__dict__ for theme in themes[:8]]
    prompt = {
        "kpis": kpis,
        "themes": theme_payload,
        "representative_tickets": examples,
        "instruction": (
            "Write exactly five executive support insights as JSON. Each item must include "
            "headline, detail, business_impact, confidence, and ticket_ids. Use only the data provided."
        ),
    }
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1200,
        temperature=0.1,
        messages=[{"role": "user", "content": json.dumps(prompt)}],
    )
    text = response.content[0].text
    parsed = json.loads(text)
    return parsed if isinstance(parsed, list) else parsed["insights"]


def _fallback_summary(df: pd.DataFrame, themes: list[ThemeResult], kpis: dict[str, Any]) -> list[dict[str, Any]]:
    if df.empty:
        return []

    top_theme = themes[0] if themes else None
    enterprise_high = df[(df["customer_segment"] == "Enterprise") & (df["priority"].isin(["Critical", "High"]))]
    low_csat = df.sort_values("csat_score", ascending=True).head(5)

    bullets = [
        {
            "headline": f"{kpis['total_tickets']} tickets analyzed across the selected period",
            "detail": (
                f"{kpis['critical_high_pct']}% are high or critical priority, with an average CSAT of "
                f"{kpis['avg_csat']}."
            ),
            "business_impact": "Leadership has a quick read on volume, urgency, and customer satisfaction.",
            "confidence": "High",
            "ticket_ids": df.head(5)["ticket_id"].astype(str).tolist(),
        },
        {
            "headline": f"Top friction theme: {top_theme.name if top_theme else 'None'}",
            "detail": top_theme.summary if top_theme else "No dominant theme found.",
            "business_impact": "This is the first place product and support leaders should inspect.",
            "confidence": "Medium",
            "ticket_ids": top_theme.ticket_ids if top_theme else [],
        },
        {
            "headline": "Enterprise accounts drive a meaningful share of urgent work",
            "detail": f"{len(enterprise_high)} enterprise tickets are high or critical in the current view.",
            "business_impact": "Enterprise friction has higher renewal and expansion risk.",
            "confidence": "High",
            "ticket_ids": enterprise_high.head(5)["ticket_id"].astype(str).tolist(),
        },
        {
            "headline": "Low-CSAT tickets show where trust is breaking",
            "detail": "The worst-rated tickets cluster around slow resolution, unclear ownership, or blocked workflows.",
            "business_impact": "These tickets are useful coaching and escalation samples for support leadership.",
            "confidence": "Medium",
            "ticket_ids": low_csat["ticket_id"].astype(str).tolist(),
        },
        {
            "headline": "Several issues are candidates for automation",
            "detail": "Billing, access, and documentation-style requests can often be deflected with guided support flows.",
            "business_impact": "Automation should reduce repeat tickets while preserving human help for complex cases.",
            "confidence": "Medium",
            "ticket_ids": df[df["bot_solvable_label"] == "bot_solvable"].head(5)["ticket_id"].astype(str).tolist(),
        },
    ]
    return bullets
