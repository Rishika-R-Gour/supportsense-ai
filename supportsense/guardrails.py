from __future__ import annotations

import re
from dataclasses import dataclass

INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
        r"(reveal|show|print)\s+(the\s+)?(system|developer)\s+prompt",
        r"you\s+are\s+now\s+(in|a)\s+",
        r"<\s*(system|assistant|developer)\s*>",
        r"execute\s+(this\s+)?(hidden|unauthorized)\s+tool",
        r"bypass\s+(the\s+)?(policy|guardrail|approval)",
        r"\bDAN\b.*\b(jailbreak|mode|rules)\b",
        r"pretend\s+(there\s+are|you\s+have)\s+no\s+(rules|restrictions)",
    ]
]

SECRET_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{12,}\b"),
]
CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")

FRAUD_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(?:fraud|fraudulent)\b",
        r"\b(?:unauthorized|unrecognized)\s+(?:charge|payment|transaction)\b",
        r"\b(?:card|account)\s+(?:was\s+)?(?:stolen|compromised)\b",
        r"\bidentity\s+theft\b",
    ]
]

ANGER_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(?:furious|enraged|livid)\b",
        r"\b(?:extremely|really)\s+angry\b",
        r"\b(?:completely\s+)?unacceptable\b",
        r"\b(?:speak|talk)\s+to\s+(?:a\s+)?(?:human|manager|supervisor)\b",
    ]
]

ALLOWED_SCOPE = {
    "support",
    "ticket",
    "customer",
    "payment",
    "refund",
    "invoice",
    "subscription",
    "billing",
    "charge",
    "charges",
    "transaction",
    "transactions",
    "account",
    "email",
    "api",
    "authentication",
    "login",
    "issue",
    "error",
    "export",
    "integration",
    "theme",
    "csat",
    "priority",
    "profile",
    "record",
    "details",
}


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str | None = None
    redacted_text: str | None = None


def validate_input(text: str) -> GuardrailDecision:
    normalized = " ".join(text.split())
    if not normalized:
        return GuardrailDecision(False, "empty_input")
    if any(pattern.search(normalized) for pattern in INJECTION_PATTERNS):
        return GuardrailDecision(False, "prompt_injection")
    if contains_sensitive_data(normalized):
        return GuardrailDecision(False, "sensitive_data")
    if any(pattern.search(normalized) for pattern in FRAUD_PATTERNS):
        return GuardrailDecision(False, "suspected_fraud")
    if any(pattern.search(normalized) for pattern in ANGER_PATTERNS):
        return GuardrailDecision(False, "angry_customer")

    tokens = set(re.findall(r"[a-z]{3,}", normalized.lower()))
    if len(tokens) >= 4 and not tokens.intersection(ALLOWED_SCOPE):
        return GuardrailDecision(False, "unsupported_scope")
    return GuardrailDecision(True, redacted_text=redact_pii(normalized))


def redact_pii(text: str) -> str:
    value = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[EMAIL_REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    value = CARD_CANDIDATE.sub(
        lambda match: (
            "[PAYMENT_CARD_REDACTED]"
            if _passes_luhn(re.sub(r"\D", "", match.group(0)))
            else match.group(0)
        ),
        value,
    )
    value = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[GOVERNMENT_ID_REDACTED]", value)
    value = re.sub(
        r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{12,}\b",
        "[CREDENTIAL_REDACTED]",
        value,
    )
    value = re.sub(
        r"(?<![A-Za-z0-9_-])\+?\d[\d ()-]{8,}\d(?![A-Za-z0-9_-])",
        "[PHONE_REDACTED]",
        value,
    )
    return value


def contains_sensitive_data(text: str) -> bool:
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        return True
    return any(
        _passes_luhn(re.sub(r"\D", "", candidate.group(0)))
        for candidate in CARD_CANDIDATE.finditer(text)
    )


def _passes_luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        value = int(character)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        checksum += value
    return checksum % 10 == 0


def validate_citations(citations: list[str], allowed: set[str]) -> bool:
    return bool(citations) and set(citations).issubset(allowed)


def validate_tool_allowed(tool_name: str, allowed_tools: set[str]) -> bool:
    return tool_name in allowed_tools


def validate_output(
    text: str,
    citations: list[str],
    allowed_citations: set[str],
) -> GuardrailDecision:
    text_without_internal_citations = re.sub(r"\[tool:[^\]]+\]", "", text)
    if contains_sensitive_data(text_without_internal_citations):
        return GuardrailDecision(False, "sensitive_output")
    if citations and (
        not validate_citations(citations, allowed_citations)
        or any(f"[{citation}]" not in text for citation in citations)
    ):
        return GuardrailDecision(False, "invalid_citations")
    return GuardrailDecision(True, redacted_text=redact_pii(text))
