# SupportSense Production Roadmap Traceability

This document maps the requested production roadmap to implementation and
release evidence. Run `python scripts/verify_roadmap.py` to regenerate
`outputs/roadmap-verification.json`. The verifier is a structural release gate;
tests, evaluation thresholds, security scans, and staging validation remain
independent gates.

| Roadmap area | Implementation evidence | Verification evidence |
|---|---|---|
| Product scope and architecture | `docs/PRODUCT_REQUIREMENTS.md`, `SYSTEM_DESIGN.md`, `docs/PRODUCTION_ARCHITECTURE.md` | Roadmap verifier documentation check |
| FastAPI and PostgreSQL foundation | `supportsense/api.py`, `supportsense/db_models.py`, `migrations/` | API, schema, migration, and API tests |
| Multi-turn memory | `supportsense/conversations.py`, `supportsense/memory.py` | `tests/test_memory.py`, `tests/test_agent.py` |
| Agent orchestration | `supportsense/agent.py` | Explicit LangGraph node verification and agent tests |
| Tool workflows and approvals | `supportsense/tooling.py`, approval API endpoints | Typed input/output contracts, tool, RBAC, idempotency, and backend tests |
| Production RAG | `supportsense/retrieval.py`, `supportsense/vector_store.py` | Retrieval, citation, conflict, and Chroma tests |
| Guardrails | `supportsense/guardrails.py`, agent policy validator | Guardrail precision, injection, PII, RBAC, and output tests |
| Human escalation | `supportsense/escalation.py` | Escalation model and production evaluation checks |
| Authentication and RBAC | `supportsense/security.py` | API and tenant-isolation tests |
| Auditability | `supportsense/audit.py`, `audit_logs`, `messages`, `tool_logs` | Hash-chain, request, tool, error, approval, and response records |
| Evaluation suite | `evals/production_agent_cases.json`, `scripts/run_production_evals.py` | `outputs/production-eval-results.json` and CI thresholds |
| Failure handling | `supportsense/resilience.py`, `supportsense/errors.py`, `app/llm.py` | Resilience and model-fallback tests |
| Observability | `supportsense/observability.py`, `supportsense/tracing.py`, `observability/` | Prometheus metrics and Grafana dashboard checks |
| Agent Assist | `/api/v1/agent-assist`, `app/support_console.py` | Agent Assist tests and response-contract checks |
| Conversation Intelligence | `supportsense/dashboard.py`, admin dashboard API and UI | Dashboard-field and analytics tests |
| Docker and AWS | Dockerfiles, `compose.yaml`, `infra/terraform/` | Image build/scan CI jobs and Terraform validation |
| CI/CD and security | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` | Lint, tests, evals, migrations, audits, secret and image scans |
| Staged rollout | `supportsense/rollout.py`, active tenant agent versions, internal-message visibility controls, `docs/STAGED_ROLLOUT.md` | Safety-ceiling, shadow-privacy, promotion, offline, Agent Assist, limited, and full-stage tests |
| Demo and operations | `docs/DEMO_RUNBOOK.md`, `docs/PRODUCTION_READINESS_CHECKLIST.md` | Reproducible demo video and release-evidence artifact |

## Demonstrated product pillars

- **AI Agent:** bounded multi-turn orchestration, retrieval, citations, tools,
  policy enforcement, approval, validation, and escalation.
- **Agent Assist:** internal draft answer, confidence, citations, tool
  suggestions, and mandatory review controls.
- **Conversation Intelligence:** intents, containment, escalations, failures,
  knowledge gaps, outcomes, sentiment, customer issues, and automation
  opportunities.

## External gates before real customer traffic

Repository completion does not prove a live production environment. GitHub CI
must pass on the target commit, images must be built and scanned, Terraform must
be applied to an AWS staging account, and smoke/load/failure tests must pass
there. The identity provider, Chroma service, model provider, payment system,
and support platform also require real secrets and provider-specific acceptance
tests. Security, privacy, support operations, and business owners must approve
each rollout transition.
