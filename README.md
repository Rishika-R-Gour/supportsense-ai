# SupportSense

SupportSense is an AI customer support analyzer for mid-size SaaS companies. It turns a CSV of support tickets into executive summaries, top customer pain themes, bot-solvable opportunities, product recommendations, and trusted follow-up answers.

## Business Problem

Support leaders have thousands of tickets, but leadership wants answers in minutes:

- What are customers frustrated about?
- Which issues are growing?
- Which cases can a bot solve?
- What should product fix next?

SupportSense compresses an analyst workflow into a fast, demo-friendly AI workflow.

## Demo Flow

1. Upload a support ticket CSV or use the bundled sample dataset.
2. Review executive KPIs and five cited insights.
3. Inspect top issue themes, trends, and example tickets.
4. See bot-solvable vs human-required ticket categories.
5. Switch between CEO, Product, and Support lenses to reframe the same evidence for different stakeholders.
6. Ask follow-up questions like "show me angry enterprise customers" or "how many billing tickets are high priority".

## Architecture

```text
CSV Upload -> Streamlit UI -> Analytics Layer
                         -> Theme Discovery
                         -> Executive Summary
                         -> Product Recommendations
                         -> Ticket Chat
```

The current version keeps infrastructure simple on purpose. Counts, filters, charts, and ticket retrieval are deterministic. AI is used for summarization and business framing when a model API key is available, with local fallbacks for portfolio demos.

## AI Design Choices

- Embeddings first, LLM second: discover ticket groups from the data, then use AI to explain them.
- Deterministic counts: the app computes numbers directly instead of asking a model to guess.
- Citations by default: claims include ticket IDs so a skeptical stakeholder can inspect the source.
- Evidence drill-down: executive insights, recommendations, themes, and chat answers can open the source ticket rows.
- Audience lens: the same dataset can be packaged for CEO, Product, or Support conversations.
- Human-in-the-loop framing: automation is recommended for repetitive cases, not for bugs, renewals, or roadmap decisions.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_sample_data.py
streamlit run app/streamlit_app.py
```

Optional:

```bash
cp .env.example .env
```

Then add a model API key for AI-powered executive summaries. For free testing, Gemini is the easiest path:

```bash
AI_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key_here
GEMINI_MODEL=gemini-2.5-flash
THEME_EMBEDDING_PROVIDER=local
```

You can also use `AI_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`, or leave keys blank to use the local deterministic fallback. For semantic theme clustering with Gemini, set `THEME_EMBEDDING_PROVIDER=gemini`. Use synthetic or approved data when sending tickets to an external model provider.

Run tests:

```bash
pytest tests
```

## CSV Format

Required columns:

- `ticket_id`
- `created_at`
- `customer_name`
- `customer_segment`
- `plan_type`
- `priority`
- `status`
- `subject`
- `description`
- `csat_score`

The bundled `data/sample_tickets.csv` shows the full recommended schema.

## Evaluation Plan

Production evaluation would include:

- 50 human-labeled tickets for theme accuracy.
- Golden questions for deterministic count correctness.
- Citation checks to ensure every claim maps to real tickets.
- Weekly drift checks for new issue categories.
- Cost tracking per upload and per chat answer.

## Interview Positioning

This project is not "a chatbot for support." It is a leadership workflow:

> Upload messy support data, identify customer pain, quantify automation potential, and prioritize product fixes with evidence.

That is the AI Solutions Engineer story: business problem, technical architecture, trust layer, ROI, and a demo people can understand quickly.
