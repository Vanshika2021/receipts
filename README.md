# 🧾 Receipts

> AI agent that tracks whether powerful people keep their promises.

Built at the Agentic Engineering Hack — May 23, 2026

## What it does

1. **Finds** public promises made by CEOs, founders, and public figures (via Nimble)
2. **Extracts** concrete commitments with deadlines (via Gemini)
3. **Stores** every promise in a database (via ClickHouse)
4. **Checks** whether deadlines were met using live web evidence (via Nimble + Gemini)
5. **Publishes** a public verdict page for each promise (via Senso)
6. **Traces** the entire pipeline (via Datadog LLM Observability)

## Who it's for

Journalists who need to track whether the people they cover follow through on their public commitments.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy env template and fill in your API keys
cp .env.template .env

# Run
python agent.py
```

## Sponsor tools used

- 🔍 **Nimble** — live web search for statements and evidence
- 🏠 **ClickHouse** — fast database for storing all promises and verdicts
- 📢 **Senso** — publishing grounded, citeable verdict pages
- 🧠 **Gemini (Google DeepMind)** — promise extraction and verdict reasoning
- 🐶 **Datadog** — LLM observability and tracing

## Run with Datadog tracing

```bash
DD_LLMOBS_ENABLED=1 \
DD_LLMOBS_ML_APP=receipts \
DD_API_KEY=your_key \
DD_SITE=us5.datadoghq.com \
ddtrace-run python agent.py
```
