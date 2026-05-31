from __future__ import annotations

import pandas as pd

from app.theme_discovery import ThemeResult


BOT_SOLVABLE_THEMES = {
    "Billing and pricing",
    "Onboarding and documentation",
    "Permissions and security",
}


def classify_automation_opportunity(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["category", "tickets", "share", "reasoning"])

    mapping = {
        "bot_solvable": "Bot-solvable",
        "human_required": "Human-required",
        "product_bug": "Product bug",
        "feature_request": "Feature request",
        "needs_review": "Needs review",
    }
    labeled = df.copy()
    labeled["automation_category"] = labeled["bot_solvable_label"].map(mapping).fillna("Needs review")
    counts = (
        labeled.groupby("automation_category")
        .size()
        .reset_index(name="tickets")
        .sort_values("tickets", ascending=False)
    )
    counts["share"] = (counts["tickets"] / len(labeled) * 100).round(1)
    counts["reasoning"] = counts["automation_category"].map(_automation_reason)
    return counts.rename(columns={"automation_category": "category"})


def build_product_recommendations(themes: list[ThemeResult], df: pd.DataFrame) -> list[dict[str, object]]:
    recommendations: list[dict[str, object]] = []
    total = max(len(df), 1)

    for theme in themes[:6]:
        severity_score = theme.critical_high_count * 2 + theme.count
        enterprise_count = _theme_enterprise_count(theme.name, df)
        impact = "High" if severity_score / total > 0.12 or enterprise_count >= 10 else "Medium"
        recommendation = {
            "title": _recommendation_title(theme.name),
            "impact": impact,
            "theme": theme.name,
            "evidence": f"{theme.count} tickets ({theme.share}% of filtered volume), {theme.critical_high_count} high or critical.",
            "why_it_matters": _why_it_matters(theme.name),
            "ticket_ids": theme.ticket_ids,
        }
        recommendations.append(recommendation)

    return recommendations


def _automation_reason(category: str) -> str:
    reasons = {
        "Bot-solvable": "Clear policy or how-to response can resolve most cases without account-specific investigation.",
        "Human-required": "Needs customer context, negotiation, or judgment from support or success.",
        "Product bug": "Requires engineering diagnosis or product fix before support can fully resolve.",
        "Feature request": "Should be routed to product discovery rather than automated away.",
        "Needs review": "Insufficient signal for safe automation.",
    }
    return reasons.get(category, "Needs review before automation.")


def _theme_enterprise_count(theme: str, df: pd.DataFrame) -> int:
    if df.empty or "theme" not in df:
        return 0
    return int(((df["theme"] == theme) & (df["customer_segment"] == "Enterprise")).sum())


def _recommendation_title(theme: str) -> str:
    titles = {
        "Reporting exports": "Stabilize exports and reporting workflows",
        "Performance and reliability": "Prioritize performance and reliability incidents",
        "Billing and pricing": "Create clearer billing self-service flows",
        "Integrations": "Improve integration health monitoring and error recovery",
        "Permissions and security": "Simplify admin access and SSO troubleshooting",
        "Onboarding and documentation": "Close onboarding and documentation gaps",
        "Workflow automation": "Improve workflow rule clarity and diagnostics",
        "Feature requests": "Review top-requested roadmap gaps",
    }
    return titles.get(theme, f"Investigate {theme.lower()}")


def _why_it_matters(theme: str) -> str:
    reasons = {
        "Reporting exports": "Reporting failures block finance, operations, and executive review cycles.",
        "Performance and reliability": "Reliability issues create repeat contacts and reduce confidence in core workflows.",
        "Billing and pricing": "Billing friction creates renewal risk and avoidable support volume.",
        "Integrations": "Integration failures break cross-tool workflows that customers rely on daily.",
        "Permissions and security": "Access issues block admins and can slow enterprise rollout.",
        "Onboarding and documentation": "Confusing setup creates early churn risk and support dependency.",
        "Workflow automation": "Automation confusion reduces product stickiness and increases manual work.",
        "Feature requests": "Repeated requests are demand signals for product discovery.",
    }
    return reasons.get(theme, "The theme shows repeated customer friction that leadership should inspect.")
