# SupportSense AWS deployment

This stack provisions an HTTPS Application Load Balancer, private ECS Fargate
tasks for both API and frontend, encrypted RDS PostgreSQL, encrypted Redis, a
private versioned S3 upload bucket, two ECR repositories, Secrets Manager,
CloudWatch logs, a service dashboard and alarms, autoscaling, backups, and
deployment rollback. Production RDS is Multi-AZ with encrypted `gp3` storage,
PostgreSQL log exports, deletion protection, and snapshot tag copying.

Before applying:

1. Create an ACM certificate and provide `certificate_arn`.
2. Run `terraform apply` once to create ECR and the application secret.
3. Store a JSON secret containing `DATABASE_URL`, `JWT_PUBLIC_KEY`,
   `JWT_ISSUER`, `JWT_AUDIENCE`, and the private `CHROMA_URL`, plus the
   support-tool and observability values documented in `docs/DEPLOYMENT.md`.
4. Build and push both images with the same immutable Git SHA.
5. Use the deploy workflow, which runs Alembic as a one-off ECS task before
   updating the service and then runs an authenticated smoke test.
6. Set optional `alarm_topic_arn` to an operations SNS topic so API 5xx,
   p95-latency, and sustained ECS CPU alarms notify the on-call route.

Never place credentials in Terraform variables or state. Production database
deletion protection and fourteen-day backups are enabled by default.
