# Production evaluation report

Suite: `production-agent-v2`
Corpus: 140 reproducibly generated cases
Command: `python scripts/run_production_evals.py`

## Coverage

- Intent classification and paraphrases
- Tool selection, status, and parameter accuracy
- Citation presence and reference integrity
- Response correctness and sensitive-output safety
- Prompt injection, secret/PII input, and unsupported scope
- Fraud, angry-customer, low-evidence, and policy escalation
- Retrieval precision@1, recall@3, query rewriting, metadata filters, conflicts,
  abstention, and citations
- Mean/P95 local orchestration latency
- Per-case cost accounting

## Current local release result

| Gate | Result |
| --- | --- |
| Cases | 140 |
| Overall pass rate | 100% |
| Intent accuracy | 100% |
| Tool selection accuracy | 100% |
| Tool parameter accuracy | 100% |
| Citation integrity | 100% |
| Response correctness | 100% |
| Response safety | 100% |
| Escalation precision / recall | 100% / 100% |
| Retrieval precision@1 / recall@3 | 100% / 100% |
| Conflict abstention | 100% |
| Cost for deterministic evaluation path | $0 |

Latency varies by machine and is gated at P95 ≤ 500 ms for the local,
provider-free orchestration path. The detailed machine-readable artifact is
`outputs/production-eval-results.json`. CI regenerates it and fails on any gate.

This synthetic release suite is necessary but not sufficient for broad
automation. Shadow and Agent Assist stages require labeled real traffic and
human review before expanding the rollout.
