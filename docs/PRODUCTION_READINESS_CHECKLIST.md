# Production readiness checklist

Status as of 2026-07-28. “Implemented” means the repository contains the
feature and its local automated checks pass. It does not mean the service has
already been deployed to an AWS account.

## Roadmap coverage

| Phase | Evidence | Status |
| --- | --- | --- |
| Planning and design | PRD, personas, supported scope, metrics, architecture, sequence, schema, API contract | Implemented |
| Production backend | Versioned FastAPI, OpenAPI, liveness/readiness, structured errors | Implemented |
| PostgreSQL and memory | SQLAlchemy models, Alembic chain, messages, summaries, session and long-term memory | Implemented |
| AI Agent | Explicit LangGraph intent, plan, retrieve, policy, tool, validation, response, and escalation nodes | Implemented |
| Tool calling | Six read, four write, and four approval-controlled tools with typed arguments | Implemented |
| RAG | Keyword + tenant-isolated Chroma vector retrieval, filters, rewriting, reranking, citations, confidence, conflict handling | Implemented |
| Guardrails and handoff | Injection, scope, PII, evidence, permission, output, fraud, anger, failures, complete handoff | Implemented |
| Authentication and RBAC | API keys for local/service access; JWT verification; customer, agent, supervisor, admin isolation | Implemented |
| Audit | Hash-chained durable prompt metadata, references, tools, redacted arguments/results, confidence, approvals, latency, errors | Implemented |
| Evaluation | 140 reproducible cases spanning intent, retrieval, response, tools, safety, escalation, latency, and cost | Implemented |
| Resilience | Deadlines, bounded retry, circuit breakers, model fallback, idempotency, structured errors | Implemented |
| Observability | Prometheus metrics, provisioned Grafana dashboard, optional privacy-safe Langfuse and Sentry, CloudWatch | Implemented |
| Agent Assist | Suggested reply, evidence, customer context, ticket history, tool suggestion, confidence, approvals | Implemented |
| Conversation Intelligence | Intents, issues, containment, escalation, latency, gaps, failures, sentiment, opportunities | Implemented |
| Role-aware frontend | Customer, agent/supervisor, and admin workspaces | Implemented |
| Cloud and containers | ECS Fargate, ALB/TLS, Multi-AZ RDS, Redis, S3, Secrets Manager, CloudWatch dashboard/alarms, Dockerfiles, Compose, Chroma | Configured |
| CI/CD and rollout | Lint, tests, integrations, security/eval/container gates; tenant agent-version promotion under a deployment safety ceiling; server-enforced shadow privacy; five-stage runbook | Configured |
| Documentation | README, architecture, API contract, evaluation, deployment, rollout, generated demo video and runbook | Implemented |

## Local evidence

- `ruff check .`
- `pytest -q`
- `python scripts/run_production_evals.py`
- `python scripts/verify_roadmap.py`
- `alembic upgrade head && alembic check` against a clean database
- `terraform fmt -check -recursive`, `terraform init -backend=false`, and
  `terraform validate`
- `pip-audit --vulnerability-service osv -r requirements-production.lock`
- API and role-aware Streamlit startup smoke test
- Live Chroma client/server test covering readiness, knowledge retrieval, and
  vector indexing/querying for 800 tickets
- Chroma uses the HTTP-only client, explicit application embeddings, and a
  digest-pinned private Rust server; the vulnerable Python server is not run
- Reproducible 1080p demo video built from real sandbox API responses

The generated evaluation artifact is
`outputs/production-eval-results.json`; the executable roadmap evidence is
`outputs/roadmap-verification.json`. The latest clean locked-environment run
passed 75 tests, all 140 production evaluation cases, and all 20 roadmap
capability checks. Local tests use sandbox support tools and a provider-free
deterministic model path; they do not claim a live payment, CRM,
identity-provider, or model integration.

## Required before staging

- [ ] Push a review branch and let every GitHub Actions job pass.
- [ ] Build and scan both Docker images in CI (Docker is unavailable on the
  current workstation).
- [ ] Provision a staging AWS environment and populate Secrets Manager.
- [ ] Connect a staging OIDC issuer and least-privileged support-tool gateway.
- [ ] Run PostgreSQL/Redis migrations and authenticated post-deploy smoke tests.
- [ ] Configure alerts and verify Prometheus/Grafana, Langfuse, Sentry, and
  CloudWatch data.
- [ ] Exercise tool timeout, circuit-breaker, model-fallback, and ECS rollback
  drills.
- [ ] Verify backups with an RDS restore test and document RTO/RPO.
- [ ] Complete dependency, container, secret, SAST, and tenant-isolation review.

## Required before customer automation

- [ ] Run shadow mode on anonymized or approved traffic.
- [ ] Label real intent, retrieval, safety, and escalation outcomes.
- [ ] Require agent review during Agent Assist and measure edits/rejections.
- [ ] Establish incident ownership and sensitive-action approval SLAs.
- [ ] Start limited automation with allowlisted tenants and read-only intents.
- [ ] Expand only after quality, safety, repeat-contact, and rollback gates pass.

No production deployment, commit, or GitHub push is performed automatically by
this repository.
