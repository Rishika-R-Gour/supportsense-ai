from __future__ import annotations

from supportsense.evaluation import run_agent_evaluation


def test_production_agent_release_gates() -> None:
    result = run_agent_evaluation()

    assert result["passed"], result
    assert 100 <= result["metrics"]["cases"] <= 150
    assert result["metrics"]["intent_accuracy"] == 1
    assert result["metrics"]["tool_selection_accuracy"] == 1
    assert result["metrics"]["tool_parameter_accuracy"] == 1
    assert result["metrics"]["citation_integrity_rate"] == 1
    assert result["metrics"]["response_correctness_rate"] == 1
    assert result["metrics"]["response_safety_rate"] == 1
    assert result["metrics"]["safety_pass_rate"] == 1
    assert result["metrics"]["escalation_recall"] == 1
    assert result["metrics"]["escalation_precision"] == 1
    assert result["metrics"]["retrieval_accuracy"] == 1
    assert result["metrics"]["retrieval_precision_at_1"] == 1
    assert result["metrics"]["retrieval_recall_at_3"] == 1
    assert result["metrics"]["retrieval_citation_rate"] == 1
    assert result["metrics"]["retrieval_conflict_abstention_rate"] == 1
