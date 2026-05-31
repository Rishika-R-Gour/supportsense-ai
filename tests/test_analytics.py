from __future__ import annotations

import pandas as pd

from app.analytics import compute_kpis
from app.theme_discovery import add_theme_column, discover_themes


def test_compute_kpis_counts_priority_share() -> None:
    df = pd.DataFrame(
        {
            "priority": ["High", "Low", "Critical", "Medium"],
            "customer_segment": ["Enterprise", "SMB", "Enterprise", "Startup"],
            "status": ["Open", "Closed", "Escalated", "Closed"],
            "csat_score": [2, 5, 1, 4],
            "resolution_hours": [10, 20, 30, 40],
        }
    )

    kpis = compute_kpis(df)

    assert kpis["total_tickets"] == 4
    assert kpis["critical_high_pct"] == 50.0
    assert kpis["avg_csat"] == 3.0


def test_theme_discovery_assigns_reporting_theme() -> None:
    df = pd.DataFrame(
        {
            "ticket_id": ["TCK-1"],
            "created_at": pd.to_datetime(["2026-01-01"]),
            "priority": ["High"],
            "customer_segment": ["Enterprise"],
            "product_area": ["Analytics"],
            "csat_score": [2],
            "ticket_text": ["Dashboard export to CSV keeps timing out"],
        }
    )

    themed = add_theme_column(df)
    themes = discover_themes(themed)

    assert themed.loc[0, "theme"] == "Reporting exports"
    assert themes[0].name == "Reporting exports"
