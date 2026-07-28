# Deployment guide

## Local production stack

```bash
cp .env.example .env
docker compose up --build
```

Services:

- Support console: `http://localhost:8501`
- FastAPI and Swagger: `http://localhost:8000/docs`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- PostgreSQL, Redis, and ChromaDB are private dependencies in the compose
  network (Chroma also exposes local port 8001 for inspection).

The HTTP-only `chromadb-client` is pinned to `1.5.9`. The server is Chroma's
pure-Rust `rust-frontend-service-oss` image from the same release commit,
locked to its OCI digest and wrapped by `Dockerfile.chroma` to apply current
Debian security updates. SupportSense does not install or run
the vulnerable Python server from the full `chromadb` distribution. The client
always supplies embeddings and explicitly disables collection embedding
functions. This avoids both server-side model loading and execution of
poisoned embedding configuration. CI scans the Rust image independently.

The API readiness endpoint performs the real Chroma heartbeat whenever
`CHROMA_URL` is configured. Keep Chroma on a private network; for a remote
vector service, use a private TLS endpoint and configure its
network/authentication controls outside the public ALB.

Production Python dependencies are fully pinned with distribution hashes in
`requirements-production.lock`. Regenerate that file from
`requirements-production.txt` after an intentional dependency update, then run
the tests, evaluations, audit, and container scan before merging it. The
frontend uses its own minimal `requirements-frontend.lock` to reduce image size
and attack surface. CI installs `requirements-dev.lock`, so lint, test, and
evaluation jobs use the same reviewed versions on every run.

Run migrations explicitly after schema changes:

```bash
docker compose run --rm api alembic upgrade head
```

## Credits-limited AWS staging

For a personal AWS Free Plan account, do not apply the production Terraform
stack: its NAT gateway, load balancer, ECS services, managed Redis, and
Multi-AZ RDS are continuously billed. Use
[`infra/terraform-free`](../infra/terraform-free/README.md) instead.
The GitHub workflow for that full stack is labelled
`Deploy Production Architecture (Paid)` and requires explicit confirmation.

The credits-limited profile uses one auto-stopping EC2 instance, encrypted
storage, an AWS Budget, SSM administration, and an IP-restricted HTTP endpoint.
It runs only in shadow mode with support tools disabled. Use synthetic data and
destroy it when the demonstration is complete.

## AWS prerequisites

1. Configure AWS OIDC for GitHub Actions; do not use long-lived AWS keys.
2. Create an ACM certificate and protected GitHub `staging` and `production`
   environments.
3. Apply `infra/terraform` with an immutable initial image tag.
4. Populate the created Secrets Manager JSON object with `DATABASE_URL`,
   `JWT_PUBLIC_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE`, `CHROMA_URL`,
   `TOOL_API_URL`, and `TOOL_API_TOKEN`. `CHROMA_URL` must resolve to a
   privately reachable, TLS-protected Rust Chroma deployment. Include
   `SENTRY_DSN`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` (empty
   strings are acceptable when those integrations are disabled).
5. Configure GitHub environment variables `AWS_REGION`, `ECS_CLUSTER`,
   `ECS_SERVICE`, and `SERVICE_BASE_URL`.
6. Configure secrets `AWS_DEPLOY_ROLE_ARN` and a short-lived,
   least-privileged `SMOKE_TEST_TOKEN`.

Set Terraform `alarm_topic_arn` to an operations SNS topic before production
so API 5xx, p95 latency, and sustained ECS CPU alarms notify the on-call route.

The ECS task runs API and frontend containers in private subnets. The ALB
terminates TLS, routes `/api`, health, docs, and metrics paths to FastAPI, and
routes browser traffic to the support console. RDS, Redis, and S3 are encrypted.

## Release procedure

1. Merge only after CI lint, tests, integrations, security scans, container
   scans, migration drift, and evaluation gates pass.
2. Dispatch `Deploy` for `staging`.
3. The workflow pushes immutable images, renders both task containers, runs
   Alembic in a one-off ECS task, deploys with the ECS rollback circuit breaker,
   and runs an authenticated smoke test.
4. Exercise shadow/Agent Assist runbooks and inspect Grafana, Langfuse, Sentry,
   CloudWatch, tool failures, escalation precision, and audit logs.
5. Dispatch `Deploy` for `production`; GitHub environment approval is the
   promotion gate.

If health checks or service stability fail, ECS rolls back. If the post-deploy
smoke test fails, stop promotion and redeploy the previous immutable SHA.

## Optional observability

Set `SENTRY_DSN` for error reporting and `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` for privacy-safe agent spans.
SupportSense does not send raw prompts to Langfuse metadata by default.
