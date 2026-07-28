from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from app.config import settings
from app.theme_discovery import ThemeResult
from supportsense.observability import MODEL_COST_USD, MODEL_REQUESTS, MODEL_TOKENS
from supportsense.resilience import CircuitBreaker, CircuitOpenError

LOGGER = logging.getLogger("supportsense.models")
_PROVIDER_CIRCUITS = {
    "gemini": CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=30),
    "anthropic": CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=30),
}


def generate_executive_summary(
    df: pd.DataFrame,
    themes: list[ThemeResult],
    kpis: dict[str, Any],
    audience: str = "CEO",
) -> list[dict[str, Any]]:
    """Return cited executive bullets with provider failover and a local fallback."""
    for provider in _provider_order():
        model = (
            settings.gemini_model
            if provider == "gemini"
            else settings.anthropic_model
        )
        circuit = _PROVIDER_CIRCUITS[provider]
        try:
            circuit.before_call()
        except CircuitOpenError:
            MODEL_REQUESTS.labels(provider, model, "circuit_open").inc()
            LOGGER.warning("Skipping %s because its circuit is open", provider)
            continue
        try:
            if provider == "gemini":
                result = _generate_with_gemini(df, themes, kpis, audience)
            else:
                result = _generate_with_anthropic(df, themes, kpis, audience)
        except Exception:
            circuit.record_failure()
            MODEL_REQUESTS.labels(provider, model, "error").inc()
            LOGGER.exception("%s summary generation failed; trying fallback", provider)
            continue
        circuit.record_success()
        MODEL_REQUESTS.labels(provider, model, "success").inc()
        return result

    MODEL_REQUESTS.labels("local", "deterministic", "fallback").inc()
    return _fallback_summary(df, themes, kpis, audience)


def active_ai_provider() -> str:
    providers = _provider_order()
    if providers:
        labels = {
            "gemini": f"Gemini ({settings.gemini_model})",
            "anthropic": f"Claude ({settings.anthropic_model})",
        }
        return " → ".join([*(labels[item] for item in providers), "Local fallback"])
    return "Local deterministic fallback"


def _provider_order() -> list[str]:
    available = {
        "gemini": bool(settings.gemini_api_key),
        "anthropic": bool(settings.anthropic_api_key),
    }
    preferred = {
        "auto": ["gemini", "anthropic"],
        "gemini": ["gemini", "anthropic"],
        "anthropic": ["anthropic", "gemini"],
    }.get(settings.ai_provider, [])
    return [provider for provider in preferred if available[provider]]


def _summary_prompt(df: pd.DataFrame, themes: list[ThemeResult], kpis: dict[str, Any], audience: str) -> dict[str, Any]:
    examples = df.head(40)[["ticket_id", "customer_segment", "priority", "subject", "description"]].to_dict("records")
    theme_payload = [theme.__dict__ for theme in themes[:8]]
    return {
        "audience": audience,
        "kpis": kpis,
        "themes": theme_payload,
        "representative_tickets": examples,
        "instruction": (
            "Write exactly five executive support insights as JSON. Each item must include "
            "headline, detail, business_impact, confidence, and ticket_ids. Use only the data provided. "
            f"Tailor the language for this audience: {audience}. {_audience_instruction(audience)} "
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


def _generate_with_gemini(
    df: pd.DataFrame,
    themes: list[ThemeResult],
    kpis: dict[str, Any],
    audience: str,
) -> list[dict[str, Any]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = _summary_prompt(df, themes, kpis, audience)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=json.dumps(prompt),
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    usage = getattr(response, "usage_metadata", None)
    _record_usage(
        "gemini",
        settings.gemini_model,
        int(getattr(usage, "prompt_token_count", 0) or 0),
        int(getattr(usage, "candidates_token_count", 0) or 0),
        settings.gemini_input_cost_per_million,
        settings.gemini_output_cost_per_million,
    )
    return _parse_json_response(response.text or "[]")


def _generate_with_anthropic(
    df: pd.DataFrame,
    themes: list[ThemeResult],
    kpis: dict[str, Any],
    audience: str,
) -> list[dict[str, Any]]:
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    prompt = _summary_prompt(df, themes, kpis, audience)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1200,
        temperature=0.1,
        messages=[{"role": "user", "content": json.dumps(prompt)}],
    )
    usage = getattr(response, "usage", None)
    _record_usage(
        "anthropic",
        settings.anthropic_model,
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
        settings.anthropic_input_cost_per_million,
        settings.anthropic_output_cost_per_million,
    )
    text = response.content[0].text
    return _parse_json_response(text)


def _record_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> None:
    MODEL_TOKENS.labels(provider, model, "input").inc(input_tokens)
    MODEL_TOKENS.labels(provider, model, "output").inc(output_tokens)
    estimated_cost = (
        input_tokens * input_cost_per_million
        + output_tokens * output_cost_per_million
    ) / 1_000_000
    MODEL_COST_USD.labels(provider, model).inc(estimated_cost)


def _fallback_summary(
    df: pd.DataFrame,
    themes: list[ThemeResult],
    kpis: dict[str, Any],
    audience: str,
) -> list[dict[str, Any]]:
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
            "business_impact": _audience_impact(
                audience,
                "Leadership has a quick read on volume, urgency, and customer satisfaction.",
            ),
            "confidence": "High",
            "ticket_ids": df.head(5)["ticket_id"].astype(str).tolist(),
        },
        {
            "headline": f"Top friction theme: {top_theme.name if top_theme else 'None'}",
            "detail": top_theme.summary if top_theme else "No dominant theme found.",
            "business_impact": _audience_impact(
                audience,
                "This is the first place product and support leaders should inspect.",
            ),
            "confidence": "Medium",
            "ticket_ids": top_theme.ticket_ids if top_theme else [],
        },
        {
            "headline": "Enterprise accounts drive a meaningful share of urgent work",
            "detail": f"{len(enterprise_high)} enterprise tickets are high or critical in the current view.",
            "business_impact": _audience_impact(
                audience,
                "Enterprise friction has higher renewal and expansion risk.",
            ),
            "confidence": "High",
            "ticket_ids": enterprise_high.head(5)["ticket_id"].astype(str).tolist(),
        },
        {
            "headline": "Low-CSAT tickets show where trust is breaking",
            "detail": "The worst-rated tickets cluster around slow resolution, unclear ownership, or blocked workflows.",
            "business_impact": _audience_impact(
                audience,
                "These tickets are useful coaching and escalation samples for support leadership.",
            ),
            "confidence": "Medium",
            "ticket_ids": low_csat["ticket_id"].astype(str).tolist(),
        },
        {
            "headline": "Several issues are candidates for automation",
            "detail": "Billing, access, and documentation-style requests can often be deflected with guided support flows.",
            "business_impact": _audience_impact(
                audience,
                "Automation should reduce repeat tickets while preserving human help for complex cases.",
            ),
            "confidence": "Medium",
            "ticket_ids": df[df["bot_solvable_label"] == "bot_solvable"].head(5)["ticket_id"].astype(str).tolist(),
        },
    ]
    return bullets


def _audience_instruction(audience: str) -> str:
    instructions = {
        "CEO": "Focus on customer risk, revenue exposure, operating leverage, and board-level decisions.",
        "Product": "Focus on product areas, root causes, roadmap tradeoffs, severity, and fix prioritization.",
        "Support": "Focus on queue health, escalation paths, deflection opportunities, macros, and coaching moments.",
    }
    return instructions.get(audience, instructions["CEO"])


def _audience_impact(audience: str, default: str) -> str:
    if audience == "Product":
        return f"Product lens: {default} Translate this into roadmap priority and root-cause investigation."
    if audience == "Support":
        return f"Support lens: {default} Translate this into triage, enablement, and automation actions."
    return f"CEO lens: {default} Translate this into customer risk and operating focus."
