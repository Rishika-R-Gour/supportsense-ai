from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path


random.seed(42)

CUSTOMERS = [
    ("Northstar Analytics", "Enterprise", "Enterprise", "$500K+"),
    ("Acme Finance", "Enterprise", "Enterprise", "$500K+"),
    ("BrightCart", "Mid-Market", "Growth", "$100K-$250K"),
    ("LumaHR", "Mid-Market", "Pro", "$50K-$100K"),
    ("Evergreen Health", "Enterprise", "Enterprise", "$250K-$500K"),
    ("Cobalt Labs", "Startup", "Starter", "<$25K"),
    ("Nimbus Retail", "SMB", "Pro", "$25K-$50K"),
    ("Atlas Security", "Enterprise", "Enterprise", "$500K+"),
    ("OrbitOps", "Mid-Market", "Growth", "$100K-$250K"),
    ("Finchly", "SMB", "Starter", "<$25K"),
    ("Summit Legal", "Mid-Market", "Pro", "$50K-$100K"),
    ("HarborCloud", "Enterprise", "Enterprise", "$250K-$500K"),
]

ISSUES = [
    {
        "area": "Analytics",
        "subject": "Dashboard export failing for finance team",
        "description": "Users cannot export dashboard data to CSV for month-end reporting. The download either times out or returns an empty spreadsheet.",
        "theme": "reporting",
        "priority": ["Critical", "High", "High", "Medium"],
        "label": "product_bug",
    },
    {
        "area": "Core Platform",
        "subject": "Reports are loading slowly during business hours",
        "description": "The dashboard takes more than 30 seconds to load and sometimes freezes after filters are applied.",
        "theme": "performance",
        "priority": ["Critical", "High", "Medium"],
        "label": "product_bug",
    },
    {
        "area": "Billing",
        "subject": "Invoice total does not match contract renewal",
        "description": "The invoice shows an unexpected charge after renewal. Customer asks for a clear explanation before finance approves payment.",
        "theme": "billing",
        "priority": ["High", "Medium", "Medium", "Low"],
        "label": "bot_solvable",
    },
    {
        "area": "Integrations",
        "subject": "Salesforce integration stopped syncing records",
        "description": "The Salesforce integration has not synced account updates since yesterday. Admins see an API authentication error.",
        "theme": "integrations",
        "priority": ["Critical", "High", "Medium"],
        "label": "human_required",
    },
    {
        "area": "Security",
        "subject": "SSO login fails for new admin role",
        "description": "A newly added admin cannot log in through SSO. The role mapping and permissions are unclear in the setup guide.",
        "theme": "security",
        "priority": ["High", "Medium", "Low"],
        "label": "bot_solvable",
    },
    {
        "area": "Onboarding",
        "subject": "Setup documentation is confusing for first workspace",
        "description": "Customer says the onboarding guide skips required setup steps and does not explain the workspace approval flow.",
        "theme": "docs",
        "priority": ["Medium", "Low", "Low"],
        "label": "bot_solvable",
    },
    {
        "area": "Automation",
        "subject": "Workflow rule triggered the wrong approval path",
        "description": "A workflow automation sent an enterprise approval to the wrong team. The trigger conditions are hard to audit.",
        "theme": "workflow",
        "priority": ["High", "Medium", "Medium"],
        "label": "human_required",
    },
    {
        "area": "Product",
        "subject": "Request for custom approval templates",
        "description": "Customer asks for reusable workflow templates by department and says this is blocking broader rollout.",
        "theme": "feature",
        "priority": ["Medium", "Low"],
        "label": "feature_request",
    },
]

STATUSES = ["Open", "In Progress", "Closed", "Escalated"]
CHANNELS = ["Email", "Chat", "Portal", "Slack Connect"]
SENTIMENTS = ["Positive", "Neutral", "Negative", "Very Negative"]


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "data" / "sample_tickets.csv"
    rows = []
    start = date(2026, 1, 1)

    for index in range(1, 801):
        customer_name, segment, plan, arr_band = random.choice(CUSTOMERS)
        issue = weighted_issue(index)
        created_at = start + timedelta(days=random.randint(0, 145))
        priority = random.choice(issue["priority"])
        status = random.choices(STATUSES, weights=[18, 20, 55, 7], k=1)[0]
        csat = csat_for(priority, issue["label"])
        first_response = round(random.uniform(0.2, 9.0), 1)
        resolution = round(first_response + random.uniform(2.0, 84.0), 1)
        sentiment = sentiment_for(csat)
        ticket_id = f"TCK-{1000 + index}"

        rows.append(
            {
                "ticket_id": ticket_id,
                "created_at": created_at.isoformat(),
                "customer_name": customer_name,
                "customer_segment": segment,
                "plan_type": plan,
                "arr_band": arr_band,
                "priority": priority,
                "status": status,
                "channel": random.choice(CHANNELS),
                "subject": issue["subject"],
                "description": personalize_description(issue["description"], customer_name, segment),
                "product_area": issue["area"],
                "sentiment": sentiment,
                "csat_score": csat,
                "first_response_hours": first_response,
                "resolution_hours": resolution,
                "bot_solvable_label": issue["label"],
            }
        )

    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output}")


def weighted_issue(index: int) -> dict[str, object]:
    weights = [18, 16, 12, 13, 11, 10, 10, 10]
    if index > 560:
        weights[0] += 10
        weights[1] += 6
    return random.choices(ISSUES, weights=weights, k=1)[0]


def csat_for(priority: str, label: str) -> int:
    base = {
        "Critical": [1, 1, 2, 2, 3],
        "High": [1, 2, 2, 3, 4],
        "Medium": [2, 3, 3, 4, 5],
        "Low": [3, 4, 4, 5, 5],
    }[priority]
    if label == "product_bug":
        base = base[:4]
    return random.choice(base)


def sentiment_for(csat: int) -> str:
    if csat <= 1:
        return "Very Negative"
    if csat == 2:
        return "Negative"
    if csat == 3:
        return "Neutral"
    return "Positive"


def personalize_description(description: str, customer_name: str, segment: str) -> str:
    context = {
        "Enterprise": "The account team says this is visible to executive stakeholders.",
        "Mid-Market": "The customer says the issue is slowing a planned rollout.",
        "SMB": "The admin needs a fast answer because they do not have dedicated ops support.",
        "Startup": "The founder is asking whether there is a workaround.",
    }[segment]
    return f"{description} {context} Account: {customer_name}."


if __name__ == "__main__":
    main()
