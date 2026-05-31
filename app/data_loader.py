from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import pandas as pd


REQUIRED_COLUMNS = {
    "ticket_id",
    "created_at",
    "customer_name",
    "customer_segment",
    "plan_type",
    "priority",
    "status",
    "subject",
    "description",
    "csat_score",
}


OPTIONAL_COLUMNS_DEFAULTS = {
    "arr_band": "Unknown",
    "channel": "Unknown",
    "product_area": "Unknown",
    "sentiment": "Neutral",
    "first_response_hours": 0.0,
    "resolution_hours": 0.0,
    "bot_solvable_label": "needs_review",
}


def load_ticket_csv(source: str | Path | BinaryIO) -> pd.DataFrame:
    df = pd.read_csv(source)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"CSV is missing required columns: {missing_list}")

    for column, default in OPTIONAL_COLUMNS_DEFAULTS.items():
        if column not in df.columns:
            df[column] = default

    df = df.copy()
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df = df.dropna(subset=["created_at"])
    df["csat_score"] = pd.to_numeric(df["csat_score"], errors="coerce")
    df["first_response_hours"] = pd.to_numeric(df["first_response_hours"], errors="coerce").fillna(0)
    df["resolution_hours"] = pd.to_numeric(df["resolution_hours"], errors="coerce").fillna(0)
    df["ticket_text"] = (
        df["subject"].fillna("").astype(str)
        + "\n"
        + df["description"].fillna("").astype(str)
    )
    return df.sort_values("created_at", ascending=False).reset_index(drop=True)


def filter_tickets(
    df: pd.DataFrame,
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    segments: list[str] | None = None,
    priorities: list[str] | None = None,
    plans: list[str] | None = None,
) -> pd.DataFrame:
    filtered = df.copy()

    if date_range:
        start, end = date_range
        filtered = filtered[(filtered["created_at"] >= start) & (filtered["created_at"] <= end)]
    if segments:
        filtered = filtered[filtered["customer_segment"].isin(segments)]
    if priorities:
        filtered = filtered[filtered["priority"].isin(priorities)]
    if plans:
        filtered = filtered[filtered["plan_type"].isin(plans)]

    return filtered.reset_index(drop=True)


def sample_dataset_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "sample_tickets.csv"
