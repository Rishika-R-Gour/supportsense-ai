from __future__ import annotations

import json
import time
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from supportsense import db_models  # noqa: F401
from supportsense.agent import SupportAgent
from supportsense.conversations import conversation_service
from supportsense.database import Base
from supportsense.db_models import ToolLog
from supportsense.retrieval import (
    HybridRetriever,
    KnowledgeDocument,
    grounded_ticket_answer,
)
from supportsense.security import Principal, Role

DEFAULT_CASES = (
    Path(__file__).resolve().parents[1] / "evals" / "production_agent_cases.json"
)


def load_evaluation_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation suite must contain at least one case")
    return cases


def run_agent_evaluation(
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected = cases or load_evaluation_cases()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    principal = Principal("eval-admin", "eval-tenant", Role.ADMIN)
    results: list[dict[str, Any]] = []

    with Session(engine, expire_on_commit=False) as session:
        for case in selected:
            conversation = conversation_service.create(
                session, principal, analysis_id=None, channel="evaluation"
            )
            started = time.perf_counter()
            result = SupportAgent(session, principal).run(
                conversation_id=conversation.id,
                question=case["question"],
                idempotency_key=f"eval-{case['case_id']}-{uuid4()}",
            )
            latency_ms = (time.perf_counter() - started) * 1000
            tool = result.get("tool_result")
            tool_log = session.get(ToolLog, tool.tool_log_id) if tool else None
            citations = result.get("citations", [])
            expected_arguments = case.get("expected_arguments")
            answer = result.get("answer", "")
            checks = {
                "intent": result.get("intent") == case["expected_intent"],
                "tool": (tool.tool_name if tool else None) == case.get("expected_tool"),
                "tool_status": (
                    not case.get("expected_tool_status")
                    or (tool and tool.status == case["expected_tool_status"])
                ),
                "escalation": bool(result.get("escalated"))
                == bool(case["expected_escalated"]),
                "escalation_reason": (
                    not case.get("expected_escalation_reason")
                    or result.get("escalation_reason")
                    == case["expected_escalation_reason"]
                ),
                "citations": (
                    bool(citations) if case["expect_citations"] else not citations
                ),
                "citation_integrity": (
                    not citations
                    or (
                        tool is not None
                        and citations == [f"tool:{tool.tool_log_id}"]
                    )
                ),
                "parameters": (
                    True
                    if expected_arguments is None
                    else bool(
                        tool_log
                        and all(
                            tool_log.arguments.get(key) == value
                            for key, value in expected_arguments.items()
                        )
                    )
                ),
                "response_correctness": (
                    not case.get("expected_answer_contains")
                    or case["expected_answer_contains"].lower() in answer.lower()
                ),
                "response_safety": not any(
                    forbidden.lower() in answer.lower()
                    for forbidden in case.get("forbidden_answer_contains", [])
                ),
            }
            results.append(
                {
                    "case_id": case["case_id"],
                    "category": case.get("category", "uncategorized"),
                    "latency_ms": round(latency_ms, 3),
                    "cost_usd": 0.0,
                    "checks": checks,
                    "passed": all(checks.values()),
                    "actual": {
                        "intent": result.get("intent"),
                        "tool": tool.tool_name if tool else None,
                        "tool_status": tool.status if tool else None,
                        "escalated": bool(result.get("escalated")),
                        "escalation_reason": result.get("escalation_reason"),
                        "citations": citations,
                        "arguments": tool_log.arguments if tool_log else None,
                        "answer": answer,
                    },
                }
            )

    latencies = [result["latency_ms"] for result in results]
    parameter_results = [
        result["checks"]["parameters"]
        for result, case in zip(results, selected, strict=True)
        if case.get("expected_arguments") is not None
    ]
    expected_escalations = [
        result["actual"]["escalated"]
        for result, case in zip(results, selected, strict=True)
        if case["expected_escalated"]
    ]
    predicted_escalations = [
        case["expected_escalated"]
        for result, case in zip(results, selected, strict=True)
        if result["actual"]["escalated"]
    ]
    safety_results = [
        result["passed"]
        for result, case in zip(results, selected, strict=True)
        if case.get("category") in {"safety", "escalation"}
    ]
    retrieval = run_retrieval_evaluation()
    metrics = {
        "cases": len(results),
        "pass_rate": mean(result["passed"] for result in results),
        "intent_accuracy": mean(result["checks"]["intent"] for result in results),
        "tool_selection_accuracy": mean(result["checks"]["tool"] for result in results),
        "tool_parameter_accuracy": mean(parameter_results) if parameter_results else 1,
        "citation_integrity_rate": mean(
            result["checks"]["citation_integrity"] for result in results
        ),
        "response_correctness_rate": mean(
            result["checks"]["response_correctness"] for result in results
        ),
        "response_safety_rate": mean(
            result["checks"]["response_safety"] for result in results
        ),
        "safety_pass_rate": mean(safety_results) if safety_results else 1,
        "escalation_recall": mean(expected_escalations) if expected_escalations else 1,
        "escalation_precision": mean(predicted_escalations) if predicted_escalations else 1,
        "mean_latency_ms": round(mean(latencies), 3),
        "p95_latency_ms": round(float(np.percentile(latencies, 95)), 3),
        "mean_cost_usd": mean(result["cost_usd"] for result in results),
        "retrieval_accuracy": retrieval["accuracy"],
        "retrieval_precision_at_1": retrieval["precision_at_1"],
        "retrieval_recall_at_3": retrieval["recall_at_3"],
        "retrieval_citation_rate": retrieval["citation_rate"],
        "retrieval_conflict_abstention_rate": retrieval[
            "conflict_abstention_rate"
        ],
    }
    gates = {
        "case_count": 100 <= metrics["cases"] <= 150,
        "pass_rate": metrics["pass_rate"] >= 1,
        "intent_accuracy": metrics["intent_accuracy"] >= 0.95,
        "tool_selection_accuracy": metrics["tool_selection_accuracy"] >= 0.95,
        "tool_parameter_accuracy": metrics["tool_parameter_accuracy"] >= 0.95,
        "citation_integrity_rate": metrics["citation_integrity_rate"] >= 1,
        "response_correctness_rate": metrics["response_correctness_rate"] >= 0.95,
        "response_safety_rate": metrics["response_safety_rate"] == 1,
        "safety_pass_rate": metrics["safety_pass_rate"] >= 1,
        "escalation_recall": metrics["escalation_recall"] >= 0.95,
        "escalation_precision": metrics["escalation_precision"] >= 0.95,
        "p95_latency_ms": metrics["p95_latency_ms"] <= 500,
        "mean_cost_usd": metrics["mean_cost_usd"] <= 0.01,
        "retrieval_accuracy": metrics["retrieval_accuracy"] >= 0.95,
        "retrieval_precision_at_1": metrics["retrieval_precision_at_1"] >= 0.95,
        "retrieval_recall_at_3": metrics["retrieval_recall_at_3"] >= 0.95,
        "retrieval_citation_rate": metrics["retrieval_citation_rate"] == 1,
        "retrieval_conflict_abstention_rate": (
            metrics["retrieval_conflict_abstention_rate"] == 1
        ),
    }
    return {
        "suite": "production-agent-v2",
        "passed": all(gates.values()),
        "metrics": metrics,
        "gates": gates,
        "results": results,
        "retrieval_results": retrieval["results"],
    }


def run_retrieval_evaluation() -> dict[str, Any]:
    documents = [
        KnowledgeDocument(
            "EVAL-KB-1",
            "Export troubleshooting",
            "CSV report exports can time out when dashboards contain large filters.",
            {"customer_segment": "Enterprise", "topic": "exports"},
        ),
        KnowledgeDocument(
            "EVAL-KB-2",
            "Invoice guide",
            "Billing administrators can download annual invoices.",
            {"customer_segment": "SMB", "topic": "invoices"},
        ),
        KnowledgeDocument(
            "EVAL-KB-3",
            "API key rotation",
            "Rotate an API key from Developer Settings and revoke the previous key.",
            {"customer_segment": "Enterprise", "topic": "api_authentication"},
        ),
        KnowledgeDocument(
            "EVAL-KB-4",
            "Subscription cancellation",
            "Administrators can schedule a subscription cancellation at period end.",
            {"customer_segment": "SMB", "topic": "subscriptions"},
        ),
        KnowledgeDocument(
            "EVAL-KB-5",
            "Payment decline troubleshooting",
            "A declined card payment can be retried after the payment method is updated.",
            {"customer_segment": "Startup", "topic": "payments"},
        ),
        KnowledgeDocument(
            "EVAL-KB-6",
            "Salesforce integration",
            "Reconnect Salesforce OAuth when customer records stop synchronizing.",
            {"customer_segment": "Enterprise", "topic": "integrations"},
        ),
    ]
    cases = [
        ("slow CSV export", {"customer_segment": "Enterprise"}, "EVAL-KB-1"),
        ("annual billing invoice", {}, "EVAL-KB-2"),
        ("rotate api authentication key", {}, "EVAL-KB-3"),
        ("cancel subscription at period end", {}, "EVAL-KB-4"),
        ("retry declined card payment", {}, "EVAL-KB-5"),
        ("salesforce records stopped syncing", {}, "EVAL-KB-6"),
    ]
    results = []
    for query, filters, expected in cases:
        response = HybridRetriever(documents).retrieve(
            query, metadata_filters=filters
        )
        grounded = grounded_ticket_answer(response)
        results.append(
            {
                "query": query,
                "expected": expected,
                "actual": response.hits[0].document_id if response.hits else None,
                "top_three": [hit.document_id for hit in response.hits[:3]],
                "citation_valid": (
                    expected in grounded["citations"]
                    and f"[{expected}]" in grounded["answer"]
                ),
            }
        )

    conflicting = HybridRetriever(
        [
            KnowledgeDocument(
                "CONFLICT-1",
                "Refund policy",
                "Refunds are allowed for thirty days.",
                {"topic": "refund_window", "policy_value": "30"},
            ),
            KnowledgeDocument(
                "CONFLICT-2",
                "Refund window",
                "Refunds are allowed for fourteen days.",
                {"topic": "refund_window", "policy_value": "14"},
            ),
        ]
    ).retrieve("refund policy window")
    conflict_abstained = grounded_ticket_answer(conflicting)["abstained"]
    return {
        "accuracy": mean(item["actual"] == item["expected"] for item in results),
        "precision_at_1": mean(item["actual"] == item["expected"] for item in results),
        "recall_at_3": mean(
            item["expected"] in item["top_three"] for item in results
        ),
        "citation_rate": mean(item["citation_valid"] for item in results),
        "conflict_abstention_rate": 1.0 if conflict_abstained else 0.0,
        "results": [
            *results,
            {
                "query": "conflicting refund policy",
                "expected": "abstain",
                "actual": "abstain" if conflict_abstained else "answered",
                "citation_valid": conflict_abstained,
            },
        ],
    }
