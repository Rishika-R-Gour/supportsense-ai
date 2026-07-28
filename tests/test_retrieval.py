from __future__ import annotations

from supportsense.retrieval import (
    HybridRetriever,
    KnowledgeDocument,
    grounded_ticket_answer,
)

DOCUMENTS = [
    KnowledgeDocument(
        "TCK-1",
        "CSV export timeout",
        "Enterprise dashboard report export times out after thirty seconds.",
        {"priority": "High", "customer_segment": "Enterprise"},
    ),
    KnowledgeDocument(
        "TCK-2",
        "Invoice question",
        "Customer needs a copy of the annual billing invoice.",
        {"priority": "Low", "customer_segment": "SMB"},
    ),
    KnowledgeDocument(
        "TCK-3",
        "Login unavailable",
        "SSO authentication fails for administrators.",
        {"priority": "Critical", "customer_segment": "Enterprise"},
    ),
]


def test_hybrid_retrieval_reranks_and_filters_metadata() -> None:
    response = HybridRetriever(DOCUMENTS).retrieve(
        "slow report export",
        metadata_filters={"customer_segment": "Enterprise"},
    )

    assert response.hits[0].document_id == "TCK-1"
    assert response.hits[0].keyword_rank is not None
    assert response.hits[0].semantic_rank is not None
    assert response.citations_valid
    assert response.confidence_label in {"medium", "high"}


def test_grounded_answer_uses_only_retrieved_citations() -> None:
    retrieval = HybridRetriever(DOCUMENTS).retrieve("invoice billing")
    answer = grounded_ticket_answer(retrieval)

    assert not answer["abstained"]
    assert answer["citations"][0] == "TCK-2"
    assert "[TCK-2]" in answer["answer"]


def test_irrelevant_metadata_filter_abstains() -> None:
    retrieval = HybridRetriever(DOCUMENTS).retrieve(
        "invoice",
        metadata_filters={"customer_segment": "Nonexistent"},
    )

    assert retrieval.confidence_label == "insufficient"
    assert grounded_ticket_answer(retrieval)["abstained"]


def test_conflicting_policy_documents_force_abstention() -> None:
    documents = [
        KnowledgeDocument(
            "KB-1",
            "Refund window",
            "Refunds are available for thirty days.",
            {"topic": "refund_window", "policy_value": "30_days"},
        ),
        KnowledgeDocument(
            "KB-2",
            "Refund policy",
            "Refunds are available for fourteen days.",
            {"topic": "refund_window", "policy_value": "14_days"},
        ),
    ]

    retrieval = HybridRetriever(documents).retrieve("refund policy window")

    assert retrieval.conflicts == ["refund_window"]
    assert retrieval.confidence_label == "insufficient"
    assert grounded_ticket_answer(retrieval)["abstained"]


def test_external_vector_scores_are_used_for_semantic_ranking() -> None:
    documents = [
        KnowledgeDocument("KB-A", "First article", "generic support content"),
        KnowledgeDocument("KB-B", "Second article", "other generic content"),
    ]

    retrieval = HybridRetriever(
        documents,
        semantic_search=lambda _query, _documents, _limit: {
            "KB-A": 0.1,
            "KB-B": 0.9,
        },
    ).retrieve("unmatched terminology")

    assert retrieval.hits[0].document_id == "KB-B"
    assert retrieval.hits[0].semantic_rank == 1
