# How SupportSense Works

SupportSense turns a CSV of customer support tickets into leadership-ready insights.

## What the AI does

It helps summarize repeated customer pain, name support themes, explain why issues matter, and draft product recommendations.
It can also reframe the same evidence for a CEO, Product leader, or Support leader.

## What the AI does not do

It does not invent ticket counts, customer segments, priorities, or dates. Those come from normal code so numbers stay reliable.

## Why the output is trustworthy

- Every executive claim includes example ticket IDs.
- Users can open the source tickets behind executive claims and recommendations.
- Counts and charts are computed directly from the uploaded CSV.
- The chat interface uses dataset filters and search before generating an answer.
- If the current data cannot answer a question, the app says so.

## Where this can fail

- Poor CSV quality can hide patterns.
- Short ticket descriptions may make theme detection less precise.
- Sentiment and urgency may need human review for high-stakes accounts.
- Historical trends are only meaningful if the upload covers enough time.

## What production would add

- Human-labeled evaluation set for themes and recommendations.
- Role-based access controls for customer data.
- Drift checks to catch new issue categories.
- Cost and latency tracking per upload.
- Direct integrations with Zendesk, Intercom, Salesforce, or Jira.
