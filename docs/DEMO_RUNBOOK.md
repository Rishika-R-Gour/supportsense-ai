# SupportSense demo runbook

Use this as the live-demo flow and as a script for a 5–7 minute recording.

A short, reproducible walkthrough is already generated at
`outputs/supportsense-production-demo.mp4`. Rebuild it from real sandbox API
responses with:

```bash
python scripts/build_demo_video.py
```

The generator uses a temporary database and synthetic support data. It executes
analysis, multi-turn chat, Agent Assist, a supervisor-approved refund, human
handoff, dashboard, and audit endpoints before rendering the video. `ffmpeg`
must be available on the host.

## Setup

```bash
docker compose up --build
```

Open the support console at `http://localhost:8501`. Use role-specific tokens
from a local `SUPPORTSENSE_API_KEYS` configuration; never record real customer
data or credentials.

## Story

1. **Conversation Intelligence (60 seconds)**
   Sign in as a supervisor. Show top intents, customer issues, containment,
   escalation, latency, knowledge gaps, tool failures, sentiment, and
   automation opportunities.

2. **AI Agent (90 seconds)**
   Sign in as a customer. Start a multi-turn payment or invoice conversation,
   ask a follow-up that depends on the prior turn, and show cited evidence and
   retained conversation history.

3. **Guardrail and escalation (60 seconds)**
   Submit a suspected-fraud or explicit human-request example. Show the safe
   response, then open the handoff package containing summary, transcript,
   customer context, retrieved evidence, tool history, reason, and suggested
   next action.

4. **Agent Assist (90 seconds)**
   Sign in as an agent. Select the conversation and generate a suggested reply.
   Show evidence, history, assigned tickets, tool recommendation, and
   confidence. Emphasize that the draft is not sent automatically.

5. **Sensitive approval (60 seconds)**
   Request a refund or cancellation. Show `approval_required`, then sign in as
   a supervisor and approve or deny it. Point out typed parameters,
   idempotency, RBAC, and the redacted audit event.

6. **Production evidence (60 seconds)**
   Run the 140-case release evaluation from the admin workspace. Briefly show
   audit history, Grafana, the staged-rollout document, and AWS/CI configuration.

## Recording checklist

- [ ] Use only synthetic data and non-secret local tokens.
- [ ] Hide browser bookmarks, notifications, terminal secrets, and AWS account IDs.
- [ ] Record at 1080p with readable browser zoom.
- [ ] Keep failures visible only when they demonstrate resilience intentionally.
- [ ] Add captions and remove pauses.
- [ ] End with the three outcomes: AI Agent, Agent Assist, Conversation Intelligence.
