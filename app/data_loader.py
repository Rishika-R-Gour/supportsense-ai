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


COLUMN_ALIASES = {
    "Ticket ID": "ticket_id",
    "ticket_id": "ticket_id",
    "Ticket No.": "ticket_id",
    "Customer Name": "customer_name",
    "customer_name": "customer_name",
    "Customer": "customer_name",
    "First Response Time": "first_response_at",
    "Created At": "created_at",
    "created_at": "created_at",
    "Date of Purchase": "date_of_purchase",
    "Ticket Priority": "priority",
    "priority": "priority",
    "Ticket Status": "status",
    "status": "status",
    "Ticket Subject": "subject",
    "subject": "subject",
    "Title": "subject",
    "Ticket Description": "description",
    "description": "description",
    "Content": "description",
    "body": "description",
    "Customer Satisfaction Rating": "csat_score",
    "csat_score": "csat_score",
    "Ticket Channel": "channel",
    "channel": "channel",
    "Ticket Type": "ticket_type",
    "Product Purchased": "product_area",
    "Time to Resolution": "resolution_at",
}


def load_ticket_csv(source: str | Path | BinaryIO) -> pd.DataFrame:
    df = pd.read_csv(source)
    df = normalize_ticket_schema(df)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"CSV is missing required columns: {missing_list}")

    for column, default in OPTIONAL_COLUMNS_DEFAULTS.items():
        if column not in df.columns:
            df[column] = default

    df = df.copy()
    df["created_at"] = _parse_datetime(df["created_at"])
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


def normalize_ticket_schema(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.rename(columns={column: COLUMN_ALIASES.get(column, column) for column in df.columns}).copy()

    if "created_at" not in normalized.columns:
        if "first_response_at" in normalized.columns:
            normalized["created_at"] = normalized["first_response_at"]
            if "date_of_purchase" in normalized.columns:
                normalized["created_at"] = normalized["created_at"].fillna(normalized["date_of_purchase"])
        elif "date_of_purchase" in normalized.columns:
            normalized["created_at"] = normalized["date_of_purchase"]

    if "customer_name" not in normalized.columns:
        normalized["customer_name"] = "Unknown customer"

    if "customer_segment" not in normalized.columns:
        normalized["customer_segment"] = _derive_customer_segment(normalized)

    if "plan_type" not in normalized.columns:
        if "ticket_type" in normalized.columns:
            normalized["plan_type"] = normalized["ticket_type"]
        elif "product_area" in normalized.columns:
            normalized["plan_type"] = normalized["product_area"]
        else:
            normalized["plan_type"] = "General"

    if "product_area" not in normalized.columns and "ticket_type" in normalized.columns:
        normalized["product_area"] = normalized["ticket_type"]

    if {"description", "product_area"}.issubset(normalized.columns):
        normalized["description"] = normalized.apply(
            lambda row: _clean_description(str(row["description"]), str(row["product_area"])),
            axis=1,
        )

    if "bot_solvable_label" not in normalized.columns:
        normalized["bot_solvable_label"] = _derive_bot_solvable_label(normalized)

    if "sentiment" not in normalized.columns and "csat_score" in normalized.columns:
        normalized["sentiment"] = normalized["csat_score"].map(_sentiment_from_csat)

    if "resolution_hours" not in normalized.columns and {"created_at", "resolution_at"}.issubset(normalized.columns):
        start = _parse_datetime(normalized["created_at"])
        end = _parse_datetime(normalized["resolution_at"])
        normalized["resolution_hours"] = ((end - start).dt.total_seconds() / 3600).clip(lower=0)

    if "first_response_hours" not in normalized.columns:
        normalized["first_response_hours"] = 0.0

    if "priority" in normalized.columns:
        normalized["priority"] = normalized["priority"].astype(str).str.title()

    if "status" in normalized.columns:
        normalized["status"] = normalized["status"].replace(
            {
                "Pending Customer Response": "In Progress",
                "pending customer response": "In Progress",
            }
        )

    if "ticket_id" in normalized.columns:
        normalized["ticket_id"] = normalized["ticket_id"].astype(str).map(lambda value: f"TCK-{value}" if value.isdigit() else value)

    return normalized


def _derive_customer_segment(df: pd.DataFrame) -> pd.Series:
    if "ticket_type" in df.columns:
        mapping = {
            "Billing inquiry": "Revenue-sensitive",
            "Refund request": "At-risk",
            "Cancellation request": "At-risk",
            "Technical issue": "Technical user",
            "Product inquiry": "Prospect or evaluator",
        }
        return df["ticket_type"].map(mapping).fillna("General customer")

    if "Customer Age" in df.columns:
        ages = pd.to_numeric(df["Customer Age"], errors="coerce")
        return pd.cut(
            ages,
            bins=[0, 29, 44, 60, 200],
            labels=["18-29", "30-44", "45-60", "60+"],
        ).astype(str).replace("nan", "Unknown")

    return pd.Series(["General customer"] * len(df), index=df.index)


def _parse_datetime(values: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(values, errors="coerce", format="mixed")
    except TypeError:
        return pd.to_datetime(values, errors="coerce")


def _clean_description(description: str, product_area: str) -> str:
    return (
        description.replace("{product_purchased}", product_area)
        .replace("{product_purchased", product_area)
        .replace("product_purchased", product_area)
    )


def _derive_bot_solvable_label(df: pd.DataFrame) -> pd.Series:
    if "ticket_type" not in df.columns:
        return pd.Series(["needs_review"] * len(df), index=df.index)

    mapping = {
        "Billing inquiry": "bot_solvable",
        "Product inquiry": "bot_solvable",
        "Technical issue": "human_required",
        "Refund request": "human_required",
        "Cancellation request": "human_required",
    }
    return df["ticket_type"].map(mapping).fillna("needs_review")


def _sentiment_from_csat(score: object) -> str:
    numeric_score = pd.to_numeric(score, errors="coerce")
    if pd.isna(numeric_score):
        return "Unknown"
    if numeric_score <= 1:
        return "Very Negative"
    if numeric_score == 2:
        return "Negative"
    if numeric_score == 3:
        return "Neutral"
    return "Positive"


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
