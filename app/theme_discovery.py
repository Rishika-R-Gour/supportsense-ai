from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


THEME_TAXONOMY: dict[str, list[str]] = {
    "Reporting exports": [
        "export",
        "csv",
        "spreadsheet",
        "report",
        "dashboard",
        "download",
        "pdf",
    ],
    "Performance and reliability": [
        "slow",
        "latency",
        "timeout",
        "crash",
        "down",
        "error",
        "loading",
        "freeze",
    ],
    "Billing and pricing": [
        "invoice",
        "billing",
        "charge",
        "payment",
        "price",
        "pricing",
        "renewal",
    ],
    "Integrations": [
        "salesforce",
        "slack",
        "hubspot",
        "api",
        "webhook",
        "zapier",
        "integration",
    ],
    "Permissions and security": [
        "permission",
        "sso",
        "login",
        "role",
        "access",
        "admin",
        "security",
        "mfa",
    ],
    "Onboarding and documentation": [
        "setup",
        "onboarding",
        "documentation",
        "docs",
        "tutorial",
        "confusing",
        "guide",
    ],
    "Workflow automation": [
        "automation",
        "workflow",
        "rule",
        "trigger",
        "template",
        "approval",
    ],
    "Feature requests": [
        "feature",
        "request",
        "wish",
        "missing",
        "roadmap",
        "support",
        "add",
    ],
}


@dataclass(frozen=True)
class ThemeResult:
    name: str
    count: int
    share: float
    avg_csat: float
    critical_high_count: int
    trend: str
    summary: str
    ticket_ids: list[str]


def assign_theme(text: str) -> str:
    lower_text = text.lower()
    scores = {
        theme: sum(1 for keyword in keywords if keyword in lower_text)
        for theme, keywords in THEME_TAXONOMY.items()
    }
    best_theme, best_score = max(scores.items(), key=lambda item: item[1])
    return best_theme if best_score > 0 else "Other customer friction"


def discover_themes(df: pd.DataFrame) -> list[ThemeResult]:
    if df.empty:
        return []

    themed = df.copy()
    themed["theme"] = themed["ticket_text"].fillna("").map(assign_theme)

    results: list[ThemeResult] = []
    for theme, group in themed.groupby("theme"):
        current, previous = _split_current_previous(group)
        trend = _trend_label(len(current), len(previous))
        example_ids = (
            group.sort_values(["priority", "created_at"], ascending=[True, False])["ticket_id"]
            .head(5)
            .astype(str)
            .tolist()
        )
        results.append(
            ThemeResult(
                name=theme,
                count=int(len(group)),
                share=round(float(len(group) / len(themed) * 100), 1),
                avg_csat=round(float(group["csat_score"].dropna().mean()), 2),
                critical_high_count=int(group["priority"].isin(["Critical", "High"]).sum()),
                trend=trend,
                summary=_theme_summary(theme, group),
                ticket_ids=example_ids,
            )
        )

    return sorted(results, key=lambda item: (item.critical_high_count, item.count), reverse=True)


def add_theme_column(df: pd.DataFrame) -> pd.DataFrame:
    themed = df.copy()
    themed["theme"] = themed["ticket_text"].fillna("").map(assign_theme)
    return themed


def _split_current_previous(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df
    midpoint = df["created_at"].min() + (df["created_at"].max() - df["created_at"].min()) / 2
    previous = df[df["created_at"] < midpoint]
    current = df[df["created_at"] >= midpoint]
    return current, previous


def _trend_label(current_count: int, previous_count: int) -> str:
    if previous_count == 0 and current_count > 0:
        return "New"
    if previous_count == 0:
        return "Flat"
    change = (current_count - previous_count) / previous_count
    if change >= 0.25:
        return "Trending up"
    if change <= -0.25:
        return "Trending down"
    return "Stable"


def _theme_summary(theme: str, group: pd.DataFrame) -> str:
    top_segment = _top_value(group["customer_segment"])
    top_area = _top_value(group["product_area"])
    critical_high = int(group["priority"].isin(["Critical", "High"]).sum())
    return (
        f"{theme} is concentrated in {top_segment} accounts and appears most often in "
        f"{top_area}. {critical_high} tickets are high or critical priority."
    )


def _top_value(values: Iterable[str]) -> str:
    series = pd.Series(values).dropna()
    if series.empty:
        return "unknown"
    return str(series.value_counts().idxmax())
