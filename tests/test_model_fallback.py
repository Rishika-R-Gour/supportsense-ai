from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from app import llm


def _settings(provider: str = "gemini") -> SimpleNamespace:
    return SimpleNamespace(
        ai_provider=provider,
        gemini_api_key="gemini-key",
        gemini_model="gemini-test",
        anthropic_api_key="anthropic-key",
        anthropic_model="anthropic-test",
        gemini_input_cost_per_million=0,
        gemini_output_cost_per_million=0,
        anthropic_input_cost_per_million=0,
        anthropic_output_cost_per_million=0,
    )


def _circuits() -> dict[str, llm.CircuitBreaker]:
    return {
        "gemini": llm.CircuitBreaker(failure_threshold=3),
        "anthropic": llm.CircuitBreaker(failure_threshold=3),
    }


def test_model_failure_falls_through_to_secondary_provider(monkeypatch) -> None:
    expected = [{"headline": "secondary"}]
    monkeypatch.setattr(llm, "settings", _settings())
    monkeypatch.setattr(llm, "_PROVIDER_CIRCUITS", _circuits())
    monkeypatch.setattr(
        llm,
        "_generate_with_gemini",
        lambda *args: (_ for _ in ()).throw(RuntimeError("provider down")),
    )
    monkeypatch.setattr(
        llm,
        "_generate_with_anthropic",
        lambda *args: expected,
    )

    result = llm.generate_executive_summary(
        pd.DataFrame([{"ticket_id": "T-1"}]),
        [],
        {},
    )

    assert result == expected
    assert llm.active_ai_provider().startswith("Gemini")


def test_model_chain_uses_local_fallback_after_all_providers_fail(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llm, "settings", _settings("anthropic"))
    monkeypatch.setattr(llm, "_PROVIDER_CIRCUITS", _circuits())
    monkeypatch.setattr(
        llm,
        "_generate_with_gemini",
        lambda *args: (_ for _ in ()).throw(RuntimeError("gemini down")),
    )
    monkeypatch.setattr(
        llm,
        "_generate_with_anthropic",
        lambda *args: (_ for _ in ()).throw(RuntimeError("anthropic down")),
    )
    monkeypatch.setattr(
        llm,
        "_fallback_summary",
        lambda *args: [{"headline": "local"}],
    )

    result = llm.generate_executive_summary(
        pd.DataFrame([{"ticket_id": "T-1"}]),
        [],
        {},
    )

    assert result == [{"headline": "local"}]
