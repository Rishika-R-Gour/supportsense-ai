from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from app.config import settings


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

    themed = df.copy() if "theme" in df.columns else add_theme_column(df)

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
    texts = themed["ticket_text"].fillna("").astype(str).tolist()
    if len(texts) < 6:
        themed["theme"] = themed["ticket_text"].fillna("").map(assign_theme)
        themed["theme_method"] = "keyword"
        return themed

    embeddings, method = _build_embeddings(texts)
    cluster_count = _choose_cluster_count(texts)
    if cluster_count < 2:
        themed["theme"] = themed["ticket_text"].fillna("").map(assign_theme)
        themed["theme_method"] = "keyword"
        return themed

    labels = _kmeans_labels(embeddings, cluster_count)
    themed["theme_cluster"] = labels
    themed["theme_method"] = method

    theme_names = {
        cluster_id: _label_cluster(themed[themed["theme_cluster"] == cluster_id])
        for cluster_id in sorted(set(labels))
    }
    themed["theme"] = themed["theme_cluster"].map(theme_names)
    return themed


def theme_discovery_method() -> str:
    provider = settings.theme_embedding_provider
    if provider == "gemini" and settings.gemini_api_key:
        return f"Gemini embeddings ({settings.gemini_embedding_model})"
    if provider == "auto" and settings.gemini_api_key:
        return f"Gemini embeddings ({settings.gemini_embedding_model})"
    return "Local TF-IDF embeddings"


def _build_embeddings(texts: list[str]) -> tuple[np.ndarray, str]:
    provider = settings.theme_embedding_provider
    if provider in {"auto", "gemini"} and settings.gemini_api_key:
        try:
            return _embed_with_gemini(texts), "gemini_embeddings"
        except Exception:
            if provider == "gemini":
                return _embed_with_tfidf(texts), "tfidf_fallback_after_gemini_error"

    return _embed_with_tfidf(texts), "tfidf_embeddings"


def _embed_with_gemini(texts: list[str]) -> np.ndarray:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    vectors: list[list[float]] = []
    for batch_start in range(0, len(texts), 100):
        batch = texts[batch_start : batch_start + 100]
        response = client.models.embed_content(
            model=settings.gemini_embedding_model,
            contents=batch,
            config=types.EmbedContentConfig(task_type="CLUSTERING"),
        )
        vectors.extend([embedding.values for embedding in response.embeddings])
    return np.array(vectors, dtype=float)


def _embed_with_tfidf(texts: list[str]) -> np.ndarray:
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=300)
    matrix = vectorizer.fit_transform(texts)
    return matrix.toarray()


def _choose_cluster_count(texts: list[str]) -> int:
    unique_text_count = len(set(texts))
    if unique_text_count < 2:
        return 1
    by_volume = max(4, min(8, len(texts) // 80))
    return min(by_volume, unique_text_count)


def _kmeans_labels(embeddings: np.ndarray, cluster_count: int, iterations: int = 18) -> np.ndarray:
    if len(embeddings) <= cluster_count:
        return np.arange(len(embeddings))

    vectors = _normalize_rows(embeddings)
    initial_indices = np.linspace(0, len(vectors) - 1, cluster_count, dtype=int)
    centroids = vectors[initial_indices].copy()

    labels = np.zeros(len(vectors), dtype=int)
    for _ in range(iterations):
        distances = np.linalg.norm(vectors[:, None, :] - centroids[None, :, :], axis=2)
        next_labels = distances.argmin(axis=1)
        if np.array_equal(labels, next_labels):
            break
        labels = next_labels
        for cluster_id in range(cluster_count):
            members = vectors[labels == cluster_id]
            if len(members):
                centroids[cluster_id] = members.mean(axis=0)
    return labels


def _normalize_rows(values: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return values / norms


def _label_cluster(group: pd.DataFrame) -> str:
    combined = " ".join(group["ticket_text"].fillna("").astype(str).tolist())
    taxonomy_label = assign_theme(combined)
    if taxonomy_label != "Other customer friction":
        return taxonomy_label

    top_area = _top_value(group["product_area"])
    if top_area != "unknown":
        return f"{top_area} friction"
    return "Other customer friction"


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
