# Retail Data Analysis Chat Assistant — Prototype

A CLI chat agent that lets non-technical retail managers ask natural-language
questions about sales, products, customers, and revenue. It retrieves
analyst-curated examples ("Golden Trios"), generates and runs **read-only** SQL
against the public `bigquery-public-data.thelook_ecommerce` dataset, and writes a
business-language report. It also manages a personal saved-reports library with a
human-confirmed delete flow.

This is a deliberate, runnable **subset** of the production High-Level Design in
[`../design/04_System_Design.md`](../design/04_System_Design.md). Design rationale
and the decisions behind this prototype are in
[`../docs/superpowers/specs/2026-05-30-retail-data-agent-prototype-design.md`](../docs/superpowers/specs/2026-05-30-retail-data-agent-prototype-design.md).

## Which requirements this prototype demonstrates

The brief asks the prototype to support **2 of 5** optional requirements. This one
implements two **structurally** (enforced by architecture, not LLM discretion),
plus the core hybrid-intelligence theme:

| Requirement | How it's solved | Where |
|---|---|---|
| **R5 — Resilience & Self-Correction** | A sealed analysis **subgraph**: retrieve → generate → validate → execute → **bounded repair loop**, empty-result re-generation, and a graceful jargon-free failure. Transient errors are classified and retried by middleware; semantic SQL errors are repaired. | `subgraph.py`, `sql_guard.py`, `bigquery_client.py` |
| **R3 — High-Stakes Oversight** | Deleting saved reports pauses via **HumanInTheLoopMiddleware** (`interrupt` + `CONFIRM-DELETE-N` token). Ownership is scoped in SQL, deletes are idempotent soft-deletes, and every deletion is audit-logged. | `tools.py`, `storage.py`, `agent.py` |
| **R1 — Hybrid Intelligence** (core) | Golden Trios (Question→SQL→Report) embedded once and retrieved by cosine similarity as few-shot examples for SQL generation. | `golden_bucket.py`, `data/golden_trios.json` |

It also answers **schema-discovery** questions ("what data can I ask about?") with
no SQL via `describe_schema`.

## Architecture

```
CLI REPL ──► create_agent (LangChain V1) ──► middleware ──► tools ──► analysis subgraph
                                                  │                         │     │
   ModelCallLimit · ModelRetry · ToolRetry · HITL │                  Golden Bucket │
                                                  │                         BigQuery
   tools ──► SQLite (saved_reports, audit_log)    └─► Gemini (gemini-3.5-flash)
   agent ──► SqliteSaver (durable interrupts)
```

* **Cross-cutting policy = middleware** (budget cap, transient retry, the human gate) — structurally unskippable.
* **Bounded deterministic workflow = the analysis subgraph** (the SQL repair loop) — the agent can't ad-lib it.
* **Discrete actions = tools**; the only destructive one (`delete_reports`) is HITL-gated. No admin/persona/GDPR tools exist in the agent's surface.

## Setup

Requires **Python 3.11+** and two **separate** Google credentials.

```bash
cd prototype
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in the two values below
```

### Credential 1 — Google AI Studio (Gemini chat + embeddings)
Get a free key at <https://aistudio.google.com/apikey> and set `GOOGLE_API_KEY` in `.env`.
Mind the [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

### Credential 2 — BigQuery compute (a different mechanism)
The dataset is public, but the *query* runs in **your** GCP project (free 1 TB/month tier).

```bash
gcloud auth application-default login      # Application Default Credentials
```

Set `GOOGLE_CLOUD_PROJECT` in `.env` to a project you can run BigQuery jobs in.
(Alternatively, point `GOOGLE_APPLICATION_CREDENTIALS` at a service-account JSON.)

> These two are independent: the API key is **not** used for BigQuery, and ADC is
> **not** used for Gemini. You need both for full functionality. Report-management
> commands (save/list/delete) work without either.

## Run

```bash
python -m retail_agent.cli --user manager_a
```

Example session:

```
you> what are the top 5 products by revenue?
agent> The top products by revenue are ... (table) ...
you> save that as "Top products"
agent> Saved report #1: "Top products".
you> list my reports
agent> Your saved reports:
       #1 — "Top products" (saved 2026-05-30)
you> delete my reports about products
agent> 1 of your reports match "products": #1 "Top products".
       To proceed, type: CONFIRM-DELETE-1

⚠️  Confirmation required before deleting reports:
   • delete reports [1]
Type the confirmation token to approve (or 'reject' to cancel): CONFIRM-DELETE-1
agent> Deleted 1 report.
```

One-shot, non-interactive:

```bash
python -m retail_agent.cli --user manager_a --question "monthly revenue last 12 months"
```

`--user` sets the identity used for report ownership — run as `manager_a` and
`manager_b` to see that one manager cannot delete another's reports.

## Tests

Offline (Gemini and BigQuery are mocked — no credentials, no network, no cost):

```bash
pytest
```

Covers the SQL guard (rejects DML/DDL and unknown tables, enforces `LIMIT`), the
subgraph repair loop (repair → success, exhaustion → graceful fail, empty handling,
transient-vs-semantic split), delete scoping + idempotency, tool behavior, and the
real HITL interrupt/resume contract through `create_agent`.

## Configuration

All via `.env` (see `.env.example`): `GEMINI_MODEL` (default `gemini-3.5-flash`),
`EMBED_MODEL` (default `gemini-embedding-001`), `MAX_SQL_ATTEMPTS`,
`MAX_RESULT_ROWS`, `PREVIEW_ROWS`, `MODEL_RUN_LIMIT`, `AGENT_USER_ID`, `HMAC_SECRET`.

## Designed in the HLD, deferred in this prototype

To keep the prototype simple and focused on the two chosen requirements, the
following are designed in the HLD but intentionally **not** built here:
**PII masking** (R2 — a `PIIMiddleware("email", strategy="redact", apply_to_output=True)`
one-liner would slot into the middleware stack), persona governance (R8), user
preferences, the feedback/analyst-curation learning loop (R4), pre-deployment evals
(R6), observability dashboards (R7), authentication/SSO, the GDPR cascade, and all
cloud infrastructure (Cloud Run, Cloud SQL+pgvector, Vertex AI, LangSmith) — replaced
here by SQLite + in-process vectors + Google AI Studio.
```