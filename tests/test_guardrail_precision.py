from __future__ import annotations

from supportsense.guardrails import contains_sensitive_data, validate_input, validate_output


def test_sensitive_detector_uses_card_checksum() -> None:
    assert contains_sensitive_data("card 4242 4242 4242 4242")
    assert not contains_sensitive_data("reference 1234-5678-9012-3456")


def test_api_credentials_are_treated_as_sensitive() -> None:
    synthetic_credential = "_".join(["sk", "live", "abcdefghijklmnop"])

    assert validate_input(
        f"Use API key {synthetic_credential} for billing"
    ).reason == "sensitive_data"


def test_internal_tool_citation_is_not_treated_as_sensitive_output() -> None:
    citation = "tool:12345678-9012-3456-7890-123456789012"
    decision = validate_output(
        f"Action paused [{citation}].",
        [citation],
        {citation},
    )

    assert decision.allowed
