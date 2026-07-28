# SupportSense production requirements

## Product

SupportSense is a multi-tenant AI support platform for mid-size SaaS companies.
It combines:

1. **AI Agent** for bounded customer self-service.
2. **Agent Assist** for evidence, recommended actions, and approvals.
3. **Conversation Intelligence** for executive summaries, pain themes,
   automation opportunities, product recommendations, and knowledge gaps.

The CSV analyzer remains the fastest onboarding path: a team can upload a
historical ticket export before connecting live support systems.

## Personas

| Persona | Goal | Default role |
| --- | --- | --- |
| Customer | Resolve a supported issue safely | Customer |
| Support agent | Investigate and execute ordinary workflows | Agent |
| Supervisor | Review escalations and sensitive actions | Supervisor |
| Administrator | Configure tenants, identity, tools, and rollout | Admin |
| Support/Product leader | Understand customer pain and outcomes | Supervisor |

## Supported use cases

- Ticket and conversation analytics.
- Payment, refund-status, invoice, subscription, billing, and API-auth questions.
- Customer, invoice, subscription, payment, refund, and transaction lookup.
- Ticket creation/escalation, email update, and invoice resend.
- Approval-controlled refunds, cancellations, billing updates, and deletion.
- Human handoff with summary, transcript, evidence, and tool history.

## Unsupported behavior

- Executing unknown tools or arbitrary code.
- Actions across tenant boundaries.
- Handling raw card numbers, credentials, or government identifiers.
- Sensitive actions without explicit supervisor approval.
- Answers without evidence when evidence is required.
- Legal, medical, investment, or unrelated general-assistant requests.

## Success metrics

| Metric | Initial release gate |
| --- | --- |
| Unauthorized sensitive actions | 0 |
| Citation integrity | 100% |
| Safety evaluation pass rate | 100% |
| Intent accuracy | >=95% |
| Tool selection accuracy | >=95% |
| P95 orchestration latency excluding providers | <=500 ms |
| API availability | 99.9% target |
| Containment | Measured with quality; never optimized alone |
| Escalation package completeness | 100% |

## Trust principles

- Code computes counts and permissions; models explain and summarize.
- Every tool call is typed, authorized, idempotent, timed, and audited.
- Retrieved content is untrusted data, never instructions.
- Sensitive values are rejected or redacted before model/tool boundaries.
- Low-confidence evidence produces abstention or human escalation.
