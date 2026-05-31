from __future__ import annotations

import pandas as pd


PRIORITY_ORDER = ["Critical", "High", "Medium", "Low"]
SEGMENT_ORDER = ["Enterprise", "Mid-Market", "SMB", "Startup"]


def compute_kpis(df: pd.DataFrame) -> dict[str, float | int | str]:
    if df.empty:
        return {
            "total_tickets": 0,
            "critical_high_pct": 0.0,
            "avg_csat": 0.0,
            "median_resolution_hours": 0.0,
            "enterprise_pct": 0.0,
            "open_pct": 0.0,
        }

    critical_high = df["priority"].isin(["Critical", "High"]).mean() * 100
    enterprise_pct = (df["customer_segment"] == "Enterprise").mean() * 100
    open_pct = df["status"].isin(["Open", "In Progress", "Escalated"]).mean() * 100
    return {
        "total_tickets": int(len(df)),
        "critical_high_pct": round(float(critical_high), 1),
        "avg_csat": round(float(df["csat_score"].dropna().mean()), 2),
        "median_resolution_hours": round(float(df["resolution_hours"].median()), 1),
        "enterprise_pct": round(float(enterprise_pct), 1),
        "open_pct": round(float(open_pct), 1),
    }


def count_by(df: pd.DataFrame, column: str) -> pd.DataFrame:
    if df.empty or column not in df:
        return pd.DataFrame(columns=[column, "count"])
    return (
        df.groupby(column, dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )


def tickets_over_time(df: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["created_at", "tickets"])
    return (
        df.set_index("created_at")
        .resample(freq)
        .size()
        .reset_index(name="tickets")
    )


def segment_priority_matrix(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    matrix = pd.crosstab(df["customer_segment"], df["priority"])
    return matrix.reindex(index=SEGMENT_ORDER, columns=PRIORITY_ORDER, fill_value=0).dropna(how="all")


def top_customer_examples(df: pd.DataFrame, n: int = 8) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    priority_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    examples = df.assign(priority_rank=df["priority"].map(priority_rank).fillna(4))
    return (
        examples.sort_values(["priority_rank", "created_at"], ascending=[True, False])
        .head(n)
        [
            [
                "ticket_id",
                "created_at",
                "customer_name",
                "customer_segment",
                "priority",
                "subject",
                "csat_score",
            ]
        ]
    )
