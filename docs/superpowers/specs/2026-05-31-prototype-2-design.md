# Prototype_2 — Design Spec

**Type**: prototype_design
**State**: proposed
**Date**: 2026-05-31
**Supersedes**: the earlier prototype (`prototype/`) — clean-room rebuild, not an edit.

---

## 1. Purpose & North Star

A dockerized, CLI data-analysis chat agent for non-technical retail managers. The manager
asks in plain English; the agent retrieves similar analyst examples, generates and runs
read-only SQL against BigQuery `thelook_ecommerce`, and writes a short business-language
report. It also keeps a personal saved-reports library whose deletion is human-gated.

**North star: simple, elegant, easy to run, dockerized.** Every decision below bends toward
a build a reviewer can read in one sitting and run with `docker compose up`. It is an *honest
slice* of the production High-Level Design (`design/04_System_Design.md`), not a second HLD.

The brief (`design/00_Brief.md`) is the source of truth and outranks this document.

## 2. Scope — Requirements Covered

The brief requires the prototype to implement **at least 2 of 5** optional requirements, on
top of the baseline SQL→report flow.

| Req | Status in Prototype_2 | How |
|---|---|---|
| **R3 High-Stakes Oversight** | **Showcased #1** | Saved-reports library + `preview/delete` with a durable HITL confirmation gate, in-SQL ownership scoping, idempotent soft-delete + audit log |
| **R5 Resilience** | **Showcased #2** | Sealed analysis subgraph with a bounded SQL repair loop, empty-result retry, transient-vs-semantic split, graceful failure |
| **R1 Hybrid Intelligence** | **Baseline (structural)** | Real `pgvector` top-k retrieval of analyst "Trios" as the structurally-first subgraph node — the agent cannot answer without consulting them |
| **R2 PII Masking** | **Near-free safety add** | `PIIMiddleware` output guardrail + a Layer-1 `redact_pii` node at the subgraph source boundary (so raw PII never lands in the Postgres checkpoint) |

**Explicitly out of scope** (left to the HLD): persona governance, user formatting prefs, the
analyst curation/feedback loop, the pre-deploy eval gate, observability stack (LangSmith /
Cloud Monitoring), SSO, the GDPR cascade, Cloud Run / Vertex AI, provider failover.

### 2.1 Decisions log (why this shape)

- **Topology follows the HLD** (§4–§5, §9): `create_agent` + ordered middleware + a sealed
  analysis subgraph behind one tool. The prototype's job is to demonstrate that production
  thesis faithfully, so a plain in-tool loop would understate the design.
- **Postgres + pgvector, not SQLite/in-process.** Raises fidelity to HLD §7 (single store) and
  is fully contained by `docker compose`, so it stays easy to run. Real pgvector retrieval is
  the honest form of R1 — not static inline few-shot (rejected) and not cut (rejected).
- **PII pulled in** despite not being one of the two showcased requirements: the dataset is
  full of emails/phones, the brief's language is its strongest ("strictly forbidden… even if
  the SQL query retrieves it"), and it costs ~one middleware. Framed as judgment, not padding.
- **No frontend / FastAPI.** The brief says twice that UIs gain no points and to ship a CLI.
  Presentation effort goes into a polished CLI instead.
- **Live-only, no offline fixture mode** (user decision). Mitigated by fail-fast startup checks
  and a tiny SQL attempt cap so the repair loop can't exhaust the Gemini free tier.

## 3. Deployment & Run Story

`docker compose up` brings up two services:

| Service | Image / build | Holds / does |
|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | Single store: `golden_assets` (Trios + embeddings), `saved_reports`, `audit_log`, LangGraph Postgres checkpointer |
| `agent` | local `Dockerfile` (Python 3.11+) | The CLI agent. Connects to Postgres, Gemini (AI Studio key), BigQuery (service-account key) |

**Credentials — configure `.env` once, no `gcloud` CLI required:**

1. **Gemini (LLM + embeddings):** AI Studio API key, pure env — `GOOGLE_API_KEY=...` in `.env`.
2. **BigQuery:** a **service-account JSON key** referenced by path, not pasted into env (native
   `GOOGLE_APPLICATION_CREDENTIALS`, zero custom auth code, no multi-line/base64 pain).
   - File lives at a fixed gitignored path: `secrets/gcp.json`.
   - `.gitignore`: `secrets/*` + `!secrets/.gitkeep` (folder tracked, contents not).
   - `secrets/README.md` placeholder tells the reviewer to drop their key as `gcp.json`.
   - `.dockerignore` excludes `secrets/`; compose mounts it read-only:
     `./secrets:/app/secrets:ro`, with `GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/gcp.json`.
   - *Irreducible:* a GCP project with the BigQuery API enabled (free tier, 1 TB/mo) — queries
     bill to the caller's project; there is no API-key-only path for BigQuery. gcloud ADC is
     supported as an optional alternative (the client auto-detects), but the documented path is
     the service-account key.

**On first boot**, an idempotent seed step embeds `trios.json` and upserts the rows into
`golden_assets`. **At startup**, the agent fails fast and loud if the Gemini key or BigQuery
credentials are missing, naming exactly what to fix.

Reviewer's entire setup: paste Gemini key into `.env` → drop `secrets/gcp.json` → `docker compose up`.

## 4. Agent Topology (HLD §4)

One LangChain V1 `create_agent`. Cross-cutting policy is **ordered middleware** (only the
slices our requirements need); the model decides *which tool*, middleware enforces policy
*regardless*, the subgraph owns the one deterministic workflow.

Middleware, outermost→inner:

1. `ModelCallLimit` — per-request budget cap (registered first so it short-circuits before any token spend).
2. `PIIMiddleware` — redact emails (built-in) + phones (regex) on output / tool results.
3. `ToolRetryMiddleware` — exponential backoff for *transient* BQ/Gemini errors.
4. `HumanInTheLoopMiddleware` — gates `delete_reports`, `allowed_decisions=["approve","reject"]` (**no edit**).

**Tool surface (manager-facing only):** `query_data` (→ subgraph), `describe_schema` (no SQL),
`save_report`, `list_reports`, `preview_delete_reports`, `delete_reports`. Privileged / admin /
GDPR operations are **absent from the tool list** — a prompt-injected agent has no tool to reach them.

## 5. Analysis Subgraph (HLD §5) — Resilience + Hybrid Intelligence

A single compiled `StateGraph` behind `query_data`. Retrieval is the first node, so R1 is
structural. Generation and repair share one prompt site ("generate again, with the error in
context"). PII is redacted at the source boundary before rows touch state/checkpoint.

```
START → retrieve_trios → generate_sql → validate_sql → execute_bq → redact_pii → return
                              ▲   │ invalid              │ error & attempts<N → repair_sql ┐
                              └───┴─ repair_sql ──────────┤ empty & not retried → repair_empty ┘
                                                          └ error & exhausted → graceful_fail
```

- **`retrieve_trios`** — embed question (RETRIEVAL_QUERY), pgvector top-k over `golden_assets`.
- **`generate_sql` / `repair_sql`** — few-shot from retrieved Trios + static schema grounding; repair adds the prior SQL + error.
- **`validate_sql`** — `sql_guard`: SELECT-only, allowed-tables (sqlglot AST walk, not regex), enforced `LIMIT`.
- **`execute_bq`** — read-only BigQuery via the provided runner.
- **`redact_pii`** — Layer-1 mask of emails/phones in rows at source.
- **Bounded:** `MAX_SQL_ATTEMPTS` = total SQL generations *including* the first (env-tunable,
  default `2` → initial + one repair) + per-request `ModelCallLimit` both terminate into `graceful_fail`.
- **Repair vs retry split:** *semantic* errors (`BadRequest`/`NotFound`) → regenerate SQL here;
  *transient* errors (5xx/429/timeout) → re-raise to `ToolRetryMiddleware` (same call + backoff).
  Unknown → treated as semantic (don't hammer a possibly-failing endpoint). This split is the resilience tell.

**State:** `{question, trios, sql, attempts, max_attempts, errors[], rows, empty_retried}`.

## 6. High-Stakes Oversight (HLD §9.1)

Two tools, durable gate:

- **`preview_delete_reports`** (ungated, read-only) — runs the scoped `SELECT`, returns
  `{count, ids, titles}`, captures the count-bound id set, surfaces a `CONFIRM-DELETE-N` token.
- **`delete_reports`** (HITL-gated) — the `HumanInTheLoopMiddleware` interrupt pauses the graph;
  state is checkpointed in Postgres so the pause survives a restart; only an approve resume executes.

Safety invariants, all in `storage.py`, not in LLM args:
- **Ownership scoped in SQL** — `WHERE user_id = ?`; the manager can only ever touch their own reports.
- **Idempotency** — `op_id = HMAC(user, thread, sorted(ids))` + `ON CONFLICT DO NOTHING` on `audit_log`; double-resume is safe.
- **Drift-safe soft-delete** — set `deleted_at` on the *captured* ids; report `already_gone` rather than crash if some vanished during the pause.
- The `CONFIRM-DELETE-N` token is a UX tripwire (N must match the id count), **not** the security boundary — the interrupt/resume is. Documented as such.

## 7. Data Layer (HLD §7)

Single Postgres + pgvector instance:

| Table / store | Purpose |
|---|---|
| `golden_assets` | Trios (question, sql, report, `embedding vector`, status); pgvector index for top-k |
| `saved_reports` | `(id, user_id, title, body, created_at, deleted_at)` — soft-delete |
| `audit_log` | append-only `(op_id, actor, target_ids, counts, ts)` |
| LangGraph checkpointer | thread state / durable HITL interrupts (`langgraph-checkpoint-postgres`) |

BigQuery is used **only** as the read-only source dataset (`orders`, `order_items`, `products`, `users`).

## 8. Module Layout (~12 focused files)

| File | One job |
|---|---|
| `cli.py` | Polished REPL: `--user` (ownership), `--question` one-shot; streamed output, rendered tables, HITL prompt, startup banner |
| `agent.py` | `create_agent` wiring: tools + ordered middleware |
| `subgraph.py` | Sealed analysis `StateGraph` (retrieve→generate→validate→execute→redact + repair/empty/fail) |
| `sql_guard.py` | Pure validation (SELECT-only, allowed tables, enforced LIMIT) — own module, densest tests, reused verbatim by prod |
| `golden_bucket.py` | pgvector retrieval + first-boot seed of `trios.json` |
| `tools.py` | The six manager-facing tools |
| `storage.py` | `saved_reports` + `audit_log`; ownership scoping; idempotent soft-delete |
| `db.py` | Postgres connection pool + schema bootstrap (shared by storage + golden_bucket) |
| `bigquery_client.py` | Thin read-only BQ runner + `is_transient_error` classifier |
| `config.py` | Env settings (`.env`) |
| `prompts.py` | System prompt + SQL generate/repair prompts |
| `schema_catalog.py` | Static schema description for `describe_schema` (answers structure questions without SQL) |

Plus: `trios.json`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.env.example`,
`secrets/README.md`, `README.md`, `tests/`.

## 9. Error Handling & Fallback (HLD §10)

| Situation | Handling |
|---|---|
| Invalid / rejected SQL | `repair_sql` regenerate with error in context, bounded by `MAX_SQL_ATTEMPTS` |
| Empty result set | one-shot `repair_empty`, then graceful "no matching data" |
| Transient BQ/Gemini error | `ToolRetryMiddleware` exponential backoff (kept separate from SQL repair) |
| Per-request budget reached | `ModelCallLimit` stops the loop |
| Postgres / BigQuery unreachable, missing creds | fail-fast at startup with a named fix; mid-session → plain "temporary issue", REPL stays up |
| Off-topic / injection attempt | system prompt declines + redirects; no destructive tool exists to reach |

## 10. Testing

Offline suite, **provider-boundary mocks** (chat model, BQ runner, embedder injected as
callables) so it runs with zero credentials and zero cost in CI / Docker. Leads with the *hard*
tests, not a vanity count:

- Real HITL interrupt through `create_agent` + `HumanInTheLoopMiddleware` (interrupt → resume approve/reject).
- `sql_guard` rejections (writes, unknown tables, CTEs, unions) and enforced LIMIT.
- Subgraph repair loop (semantic repair, empty retry, exhaustion → graceful_fail, transient re-raise).
- Delete scoping (cross-user isolation) + audit idempotency (double-resume).
- PII redaction at both the subgraph source node and the output middleware.

A short live smoke run (Gemini + BigQuery) is documented separately, not committed as a test.

## 11. Anti-Over-Engineering Guardrails

- Keep audit/idempotency, but label it in one line as the production seam.
- `MAX_SQL_ATTEMPTS` default `2` (one repair) so resilience can't 429 itself on the free tier.
- Pin the exact Gemini model string; fail fast at startup if unavailable.
- README leads with: what it does → the two requirements → one command → the two credentials.
  Keep one architecture diagram that matches the file list; link to the HLD for the rest.

## 12. Requirements Traceability

| Requirement | Satisfied by |
|---|---|
| R1 Hybrid intelligence | §5 `retrieve_trios` (pgvector top-k, structurally first) |
| R2 PII masking | §4 `PIIMiddleware` + §5 `redact_pii` node |
| R3 High-stakes oversight | §6 HITL delete + ownership scoping + idempotent audit |
| R5 Resilience | §5 bounded repair loop + §9 retry/budget/graceful split |
| Baseline NL→SQL→report | §4 agent + §5 subgraph |
| Schema discovery | §8 `describe_schema` (no SQL) |
| Runnable on another machine | §3 `docker compose up`, `.env` + one mounted key |

---

*End of Prototype_2 design spec.*
