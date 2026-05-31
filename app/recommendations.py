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


def build_product_recommendations(themes: list[ThemeResult], df: pd.DataFrame, audience: str = "CEO") -> list[dict[str, object]]:
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
            "recommended_action": _recommended_action(theme.name, audience),
            "owner": _recommended_owner(theme.name, audience),
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


def _recommended_action(theme: str, audience: str) -> str:
    if audience == "Product":
        actions = {
            "Reporting exports": "Scope export reliability work and add regression coverage for filtered report downloads.",
            "Performance and reliability": "Profile slow dashboard paths and prioritize the highest-volume latency regressions.",
            "Billing and pricing": "Clarify plan, renewal, and invoice states in-product before billing escalation.",
            "Integrations": "Add sync-health diagnostics and clearer recovery steps for failed integrations.",
            "Permissions and security": "Simplify role mapping and SSO error messages for admins.",
            "Onboarding and documentation": "Close setup gaps with guided onboarding and better in-product docs.",
            "Workflow automation": "Expose rule audit trails and make trigger conditions easier to inspect.",
            "Feature requests": "Group repeated asks into discovery themes and size the highest-value roadmap gaps.",
        }
        return actions.get(theme, "Investigate root cause and size the product opportunity.")

    if audience == "Support":
        actions = {
            "Reporting exports": "Create an export-incident macro and escalation path for blocked reporting workflows.",
            "Performance and reliability": "Tag latency tickets consistently and route severe cases to incident review.",
            "Billing and pricing": "Build a billing explanation macro and self-serve invoice checklist.",
            "Integrations": "Create integration troubleshooting runbooks with sync status checks.",
            "Permissions and security": "Publish admin-access playbooks for SSO, MFA, and role-mapping issues.",
            "Onboarding and documentation": "Turn repeated setup confusion into onboarding macros and help-center updates.",
            "Workflow automation": "Create workflow debugging scripts for rule triggers and approval paths.",
            "Feature requests": "Route repeated requests into product feedback with customer segment and ARR context.",
        }
        return actions.get(theme, "Create a triage workflow and collect evidence for the owning team.")

    actions = {
        "Reporting exports": "Assign an owner to reduce reporting blockers for high-value accounts this quarter.",
        "Performance and reliability": "Treat reliability as a retention risk and review progress weekly.",
        "Billing and pricing": "Reduce billing friction before renewal conversations are affected.",
        "Integrations": "Protect daily customer workflows by improving integration reliability.",
        "Permissions and security": "Remove access friction that slows enterprise rollout.",
        "Onboarding and documentation": "Reduce early-life support dependency and improve time-to-value.",
        "Workflow automation": "Improve automation trust so customers expand usage instead of reverting to manual work.",
        "Feature requests": "Decide which repeated requests are strategic enough for product investment.",
    }
    return actions.get(theme, "Assign an owner and decide whether this is a retention, efficiency, or roadmap priority.")


def _recommended_owner(theme: str, audience: str) -> str:
    if audience == "Support":
        return "Support Ops"
    if audience == "Product":
        return "Product"
    owners = {
        "Billing and pricing": "Revenue Ops",
        "Feature requests": "Product",
        "Onboarding and documentation": "Customer Success",
    }
    return owners.get(theme, "Product + Support")
