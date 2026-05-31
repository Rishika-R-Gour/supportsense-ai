from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app.config import settings
from app.theme_discovery import ThemeResult


def generate_executive_summary(df: pd.DataFrame, themes: list[ThemeResult], kpis: dict[str, Any]) -> list[dict[str, Any]]:
    """Return cited executive bullets, using a configured model and a deterministic fallback otherwise."""
    if settings.ai_provider in {"auto", "gemini"} and settings.gemini_api_key:
        try:
            return _generate_with_gemini(df, themes, kpis)
        except Exception:
            if settings.ai_provider == "gemini":
                return _fallback_summary(df, themes, kpis)

    if settings.ai_provider in {"auto", "anthropic"} and settings.anthropic_api_key:
        try:
            return _generate_with_anthropic(df, themes, kpis)
        except Exception:
            return _fallback_summary(df, themes, kpis)

    return _fallback_summary(df, themes, kpis)


def active_ai_provider() -> str:
    if settings.ai_provider == "gemini" and settings.gemini_api_key:
        return f"Gemini ({settings.gemini_model})"
    if settings.ai_provider == "anthropic" and settings.anthropic_api_key:
        return f"Claude ({settings.anthropic_model})"
    if settings.ai_provider == "auto":
        if settings.gemini_api_key:
            return f"Gemini ({settings.gemini_model})"
        if settings.anthropic_api_key:
            return f"Claude ({settings.anthropic_model})"
    return "Local deterministic fallback"


def _summary_prompt(df: pd.DataFrame, themes: list[ThemeResult], kpis: dict[str, Any]) -> dict[str, Any]:
    examples = df.head(40)[["ticket_id", "customer_segment", "priority", "subject", "description"]].to_dict("records")
    theme_payload = [theme.__dict__ for theme in themes[:8]]
    return {
        "kpis": kpis,
        "themes": theme_payload,
        "representative_tickets": examples,
        "instruction": (
            "Write exactly five executive support insights as JSON. Each item must include "
            "headline, detail, business_impact, confidence, and ticket_ids. Use only the data provided. "
            "Return only valid JSON as a list of objects, with no markdown."
        ),
    }


def _parse_json_response(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    parsed = json.loads(cleaned)
    return parsed if isinstance(parsed, list) else parsed["insights"]


def _generate_with_gemini(df: pd.DataFrame, themes: list[ThemeResult], kpis: dict[str, Any]) -> list[dict[str, Any]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = _summary_prompt(df, themes, kpis)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=json.dumps(prompt),
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    return _parse_json_response(response.text or "[]")


def _generate_with_anthropic(df: pd.DataFrame, themes: list[ThemeResult], kpis: dict[str, Any]) -> list[dict[str, Any]]:
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    prompt = _summary_prompt(df, themes, kpis)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1200,
        temperature=0.1,
        messages=[{"role": "user", "content": json.dumps(prompt)}],
    )
    text = response.content[0].text
    return _parse_json_response(text)


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
