# Staged rollout

Each stage requires the previous stage's evaluation gates and an explicit agent
version promotion.

`SUPPORTSENSE_ROLLOUT_STAGE` is the deployment-wide safety ceiling. An active
tenant agent version may select a more restrictive stage, but it cannot enable
more automation than that ceiling. Activating a version deactivates the prior
tenant version and creates an audit event. In offline, shadow, and Agent Assist
modes, drafts are stored as internal assistant messages; customer history
excludes them. Customer API callers receive only a neutral acknowledgement in
non-customer-visible stages.

## 1. Offline testing

- Synthetic and anonymized historical conversations only.
- Run unit, integration, migration, retrieval, safety, and production evals.
- No external write tools.
- Exit: all safety/citation gates pass and failure runbooks are exercised.

## 2. Shadow mode

- Observe live traffic without showing AI output or executing tools.
- Compare intent, suggested answers, escalation, and tool choice to agents.
- Measure drift, false containment, latency, and cost.
- Exit: human-reviewed accuracy meets targets for two consecutive weeks.

## 3. Agent Assist

- Show cited drafts and read-only tool results to agents.
- Agents approve all replies and actions.
- Capture accepted, edited, and rejected suggestions.
- Exit: quality improves without increasing handling risk or severe errors.

## 4. Limited automation

- Automate only approved intents and read tools.
- Sensitive/write tools remain confirmation- and approval-controlled.
- Start with a small tenant/traffic allowlist and automatic rollback thresholds.
- Expand by intent, not by globally increasing traffic.

## 5. Full automation

- Requires supervisor sign-off, incident readiness, and sustained evaluation.
- Monitor safe resolution, repeat contact, customer satisfaction, and escalation
  precision—not containment alone.
- Continue requiring independent approval for refunds, cancellations, billing
  changes, and account deletion; “full” means all approved intent classes are
  eligible, not that irreversible actions bypass controls.
