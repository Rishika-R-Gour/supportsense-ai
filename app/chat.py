from __future__ import annotations

import re

import pandas as pd


def answer_question(question: str, df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {
            "answer": "I do not have any tickets in the current view to answer from.",
            "ticket_ids": [],
            "method": "empty_dataset",
        }

    lower = question.lower()
    scoped = _apply_question_filters(lower, df)

    if any(token in lower for token in ["how many", "count", "number of"]):
        return _count_answer(question, scoped)
    if "enterprise" in lower and any(token in lower for token in ["angry", "upset", "frustrated", "low csat"]):
        angry = scoped[(scoped["customer_segment"] == "Enterprise") & (scoped["csat_score"] <= 2)]
        return _example_answer("enterprise customers with low CSAT", angry)
    if any(token in lower for token in ["top", "most", "biggest", "theme", "issue"]):
        return _top_theme_answer(scoped)

    return _search_answer(question, scoped)


def _apply_question_filters(lower: str, df: pd.DataFrame) -> pd.DataFrame:
    scoped = df.copy()
    for segment in ["Enterprise", "Mid-Market", "SMB", "Startup"]:
        if segment.lower() in lower:
            scoped = scoped[scoped["customer_segment"] == segment]
    for priority in ["Critical", "High", "Medium", "Low"]:
        if priority.lower() in lower:
            scoped = scoped[scoped["priority"] == priority]
    for category, aliases in TOPIC_ALIASES.items():
        if category in lower:
            pattern = "|".join(re.escape(alias) for alias in aliases)
            mask = scoped["ticket_text"].str.lower().str.contains(pattern, na=False, regex=True)
            scoped = scoped[mask]
    return scoped


def _count_answer(question: str, df: pd.DataFrame) -> dict[str, object]:
    ticket_ids = df.head(8)["ticket_id"].astype(str).tolist()
    return {
        "answer": f"I found {len(df)} tickets matching that question in the current filtered dataset.",
        "ticket_ids": ticket_ids,
        "method": "deterministic_count",
    }


def _example_answer(label: str, df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {
            "answer": f"I did not find tickets for {label} in the current filtered dataset.",
            "ticket_ids": [],
            "method": "filtered_search",
        }
    examples = df.sort_values(["priority", "csat_score"], ascending=[True, True]).head(5)
    lines = [
        f"{row.ticket_id}: {row.subject} ({row.customer_name}, CSAT {row.csat_score})"
        for row in examples.itertuples()
    ]
    return {
        "answer": "Here are the strongest examples:\n" + "\n".join(lines),
        "ticket_ids": examples["ticket_id"].astype(str).tolist(),
        "method": "filtered_search",
    }


def _top_theme_answer(df: pd.DataFrame) -> dict[str, object]:
    if "theme" not in df.columns:
        return _search_answer("top theme", df)
    counts = df["theme"].value_counts().head(5)
    lines = [f"{theme}: {count} tickets" for theme, count in counts.items()]
    examples = df[df["theme"].isin(counts.index)].head(8)
    return {
        "answer": "Top themes in the current view:\n" + "\n".join(lines),
        "ticket_ids": examples["ticket_id"].astype(str).tolist(),
        "method": "theme_count",
    }


def _search_answer(question: str, df: pd.DataFrame) -> dict[str, object]:
    terms = [term for term in re.findall(r"[a-zA-Z]{4,}", question.lower()) if term not in STOPWORDS]
    expanded_terms = set(terms)
    lower_question = question.lower()
    for category, aliases in TOPIC_ALIASES.items():
        if category in lower_question:
            expanded_terms.update(aliases)

    if not terms:
        return {
            "answer": "Ask a more specific question about customers, priorities, themes, or ticket content.",
            "ticket_ids": [],
            "method": "needs_specific_query",
        }

    scored = df.copy()
    scored["score"] = scored["ticket_text"].str.lower().apply(lambda text: sum(term in text for term in expanded_terms))
    matches = scored[scored["score"] > 0].sort_values(["score", "created_at"], ascending=[False, False]).head(5)

    if matches.empty:
        return {
            "answer": "I could not find matching tickets in the current filtered dataset.",
            "ticket_ids": [],
            "method": "keyword_search",
        }

    lines = [
        f"{row.ticket_id}: {row.subject} ({row.customer_segment}, {row.priority})"
        for row in matches.itertuples()
    ]
    return {
        "answer": "I found these relevant tickets:\n" + "\n".join(lines),
        "ticket_ids": matches["ticket_id"].astype(str).tolist(),
        "method": "keyword_search",
    }


STOPWORDS = {
    "what",
    "which",
    "show",
    "about",
    "from",
    "with",
    "this",
    "that",
    "customer",
    "customers",
    "ticket",
    "tickets",
}


TOPIC_ALIASES = {
    "billing": ["billing", "invoice", "payment", "charge", "renewal", "contract"],
    "pricing": ["pricing", "price", "invoice", "charge", "renewal", "contract"],
    "export": ["export", "csv", "spreadsheet", "download", "report"],
    "integration": ["integration", "salesforce", "hubspot", "slack", "api", "webhook", "sync"],
    "sso": ["sso", "login", "role", "permission", "access", "mfa"],
    "login": ["login", "sso", "mfa", "access"],
    "performance": ["performance", "slow", "latency", "timeout", "loading", "freeze"],
}
