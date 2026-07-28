from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from supportsense.guardrails import validate_citations

QUERY_EXPANSIONS = {
    "auth": ["authentication", "login", "api key"],
    "bill": ["billing", "invoice", "charge"],
    "refund": ["refund", "reimbursement", "money back"],
    "slow": ["latency", "timeout", "performance"],
    "export": ["download", "csv", "report"],
}


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any]
    keyword_rank: int | None
    semantic_rank: int | None
    fused_score: float
    rerank_score: float


@dataclass(frozen=True)
class RetrievalResponse:
    query: str
    rewritten_query: str
    hits: list[RetrievalHit]
    confidence: float
    confidence_label: str
    citations_valid: bool
    conflicts: list[str] = field(default_factory=list)


class HybridRetriever:
    """Local reference implementation of hybrid retrieval and reranking.

    The interface is intentionally backend-neutral so OpenSearch/pgvector can
    replace the local scorer without changing orchestration or evaluations.
    """

    def __init__(
        self,
        documents: Iterable[KnowledgeDocument],
        semantic_search: (
            Callable[
                [str, Sequence[KnowledgeDocument], int],
                dict[str, float],
            ]
            | None
        ) = None,
    ) -> None:
        self.documents = list(documents)
        self.semantic_search = semantic_search
        corpus = [f"{doc.title}\n{doc.content}" for doc in self.documents]
        self.vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            max_features=20_000,
            sublinear_tf=True,
        )
        self.matrix = (
            self.vectorizer.fit_transform(corpus)
            if corpus
            else None
        )

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        metadata_filters: dict[str, Any] | None = None,
    ) -> RetrievalResponse:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        rewritten = rewrite_query(query)
        candidate_indexes = [
            index
            for index, document in enumerate(self.documents)
            if _metadata_matches(document.metadata, metadata_filters or {})
        ]
        if not candidate_indexes or self.matrix is None:
            return RetrievalResponse(query, rewritten, [], 0, "insufficient", False, [])

        query_terms = _terms(rewritten)
        keyword_scores = {
            index: _keyword_score(query_terms, self.documents[index])
            for index in candidate_indexes
        }
        keyword_order = sorted(
            candidate_indexes, key=lambda index: keyword_scores[index], reverse=True
        )

        external_scores = (
            self.semantic_search(
                rewritten,
                [self.documents[index] for index in candidate_indexes],
                max(top_k * 4, 20),
            )
            if self.semantic_search
            else {}
        )
        if external_scores:
            semantic_scores = {
                index: external_scores.get(
                    self.documents[index].document_id,
                    0,
                )
                for index in candidate_indexes
            }
        else:
            query_vector = self.vectorizer.transform([rewritten])
            semantic_values = (
                self.matrix[candidate_indexes] @ query_vector.T
            ).toarray().ravel()
            semantic_scores = dict(
                zip(candidate_indexes, semantic_values, strict=True)
            )
        semantic_order = sorted(
            candidate_indexes, key=lambda index: semantic_scores[index], reverse=True
        )

        keyword_rank = {index: rank for rank, index in enumerate(keyword_order, 1)}
        semantic_rank = {index: rank for rank, index in enumerate(semantic_order, 1)}
        hits: list[RetrievalHit] = []
        for index in candidate_indexes:
            fused = 1 / (60 + keyword_rank[index]) + 1 / (60 + semantic_rank[index])
            coverage = _term_coverage(query_terms, self.documents[index])
            rerank = fused + 0.04 * coverage + 0.02 * semantic_scores[index]
            document = self.documents[index]
            hits.append(
                RetrievalHit(
                    document_id=document.document_id,
                    title=document.title,
                    content=document.content,
                    metadata=document.metadata,
                    keyword_rank=keyword_rank[index],
                    semantic_rank=semantic_rank[index],
                    fused_score=round(fused, 6),
                    rerank_score=round(rerank, 6),
                )
            )
        hits.sort(key=lambda hit: hit.rerank_score, reverse=True)
        hits = [hit for hit in hits if hit.rerank_score > 0.025][:top_k]
        confidence = _confidence(hits, query_terms)
        conflicts = _conflicting_topics(hits)
        if conflicts:
            confidence = 0
        citations = [hit.document_id for hit in hits]
        return RetrievalResponse(
            query=query,
            rewritten_query=rewritten,
            hits=hits,
            confidence=confidence,
            confidence_label=(
                "insufficient"
                if conflicts
                else "high"
                if confidence >= 0.75
                else "medium"
                if confidence >= 0.45
                else "insufficient"
            ),
            citations_valid=validate_citations(citations, set(citations)),
            conflicts=conflicts,
        )


def rewrite_query(query: str) -> str:
    normalized = " ".join(query.lower().split())
    additions: list[str] = []
    for trigger, expansions in QUERY_EXPANSIONS.items():
        if trigger in normalized:
            additions.extend(expansions)
    return " ".join(dict.fromkeys([normalized, *additions]))


def ticket_documents(dataframe) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []
    for row in dataframe.to_dict("records"):
        documents.append(
            KnowledgeDocument(
                document_id=str(row["ticket_id"]),
                title=str(row.get("subject") or row["ticket_id"]),
                content=str(row.get("ticket_text") or row.get("description") or ""),
                metadata={
                    key: _json_value(row.get(key))
                    for key in [
                        "customer_segment",
                        "priority",
                        "status",
                        "product_area",
                        "theme",
                    ]
                    if key in row
                },
            )
        )
    return documents


def grounded_ticket_answer(response: RetrievalResponse) -> dict[str, Any]:
    if response.confidence_label == "insufficient" or not response.hits:
        return {
            "answer": "I could not find enough matching ticket evidence.",
            "citations": [],
            "confidence": response.confidence,
            "abstained": True,
        }
    lines = [
        f"{hit.title} [{hit.document_id}]"
        for hit in response.hits[:3]
    ]
    citations = [hit.document_id for hit in response.hits[:3]]
    if not validate_citations(citations, {hit.document_id for hit in response.hits}):
        return {
            "answer": "Citation validation failed.",
            "citations": [],
            "confidence": 0,
            "abstained": True,
        }
    return {
        "answer": "Most relevant ticket evidence:\n" + "\n".join(lines),
        "citations": citations,
        "confidence": response.confidence,
        "abstained": False,
    }


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9_]{3,}", text.lower())
        if term not in {"the", "and", "for", "with", "this", "that"}
    }


def _keyword_score(terms: set[str], document: KnowledgeDocument) -> float:
    text = f"{document.title} {document.content}".lower()
    return sum((2 if term in document.title.lower() else 1) * text.count(term) for term in terms)


def _term_coverage(terms: set[str], document: KnowledgeDocument) -> float:
    if not terms:
        return 0
    text = f"{document.title} {document.content}".lower()
    return sum(term in text for term in terms) / len(terms)


def _metadata_matches(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    return all(
        metadata.get(key) in value if isinstance(value, (list, set, tuple))
        else metadata.get(key) == value
        for key, value in filters.items()
    )


def _confidence(hits: list[RetrievalHit], query_terms: set[str]) -> float:
    if not hits:
        return 0
    top = hits[0]
    coverage_component = min(1, max(0, (top.rerank_score - top.fused_score) / 0.06))
    margin = (
        top.rerank_score - hits[1].rerank_score
        if len(hits) > 1
        else top.rerank_score
    )
    score = 0.25 + 0.55 * coverage_component + min(0.2, max(0, margin * 5))
    if not query_terms:
        score = 0
    return round(min(1, score), 3)


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _conflicting_topics(hits: list[RetrievalHit]) -> list[str]:
    policies: dict[str, set[str]] = {}
    for hit in hits:
        topic = hit.metadata.get("topic")
        value = hit.metadata.get("policy_value")
        if topic and value is not None:
            policies.setdefault(str(topic), set()).add(str(value))
    return sorted(topic for topic, values in policies.items() if len(values) > 1)
