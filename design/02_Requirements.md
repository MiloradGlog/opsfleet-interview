# Requirements

**Type**: requirements
**State**: completed
**Created**: 2026-05-26 13:46:07.841963
**Updated**: 2026-05-27 10:06:17.454784

---

# Requirements Document: AI Data Analysis Chat Assistant

This document outlines the functional and non-functional requirements for the AI-powered Data Analysis Chat Assistant, derived from the project's vision statement and its guiding principles.

## 1.0 Functional Requirements

### 1.1 Natural Language Query Interface
- **FR-1.1.1:** The system shall provide a chat-based interface for users to submit data analysis queries in natural language.
- **FR-1.1.2:** The interface shall accept complex, multi-part questions (e.g., "Why is the X branch underperforming? And how does it compare to our branch in Y?").
- **FR-1.1.3:** The system shall maintain conversation history to understand follow-up questions and context.

### 1.2 Intelligence and Accuracy
- **FR-1.2.1 (implements brief R1):** The system shall analyze incoming user queries to determine the optimal retrieval strategy.
- **FR-1.2.2 (implements brief R1):** The system must be able to retrieve relevant historical analyses (Question → SQL Query → Analyst Report trios) from the "Golden Knowledge" base based on semantic similarity to the user's query.
- **FR-1.2.3 (implements brief R1):** The system shall generate new SQL queries to run against the read-only database for every analytical request, using retrieved Golden Knowledge Trios as few-shot examples to guide generation.
- **FR-1.2.4 (implements brief R1):** The system shall synthesize a human-readable report grounded in the executed query results, informed by the analytical style of retrieved Golden Knowledge Trios.
- **FR-1.2.5 (implements brief — *Expected Agent Capabilities*):** The system shall answer questions about the general structure of the database (e.g., "What tables are available?", "What columns does the orders table have?", "What data do you have about products?") without requiring execution of an analytical SQL query against the source data. Schema responses shall be phrased in business-friendly language rather than raw DDL.

### 1.3 Security and Privacy by Design
- **FR-1.3.1a (implements brief R2):** The system shall redact PII from query results before they are passed to any LLM for processing.
- **FR-1.3.1b (implements brief R2):** The system shall apply a final PII-detection guardrail to the generated output before it is displayed to the user, as defense-in-depth.
- **FR-1.3.2 (implements brief R2):** The system shall reject and refuse to process any queries identified as malicious, including attempts at SQL injection or prompt injection.
- **FR-1.3.3 (implements brief R2):** The system shall be restricted to answering only data analysis questions related to the company's retail data and must politely decline off-topic requests.

### 1.4 User Empowerment and Control
- **FR-1.4.1 (implements brief R3):** Users shall be able to save generated reports to a personal library for future reference.
- **FR-1.4.2 (implements brief R3):** Users shall be able to view and retrieve their saved reports.
- **FR-1.4.3 (implements brief R3):** The system shall support a secure process for deleting saved reports (e.g., "Delete all reports mentioning Client X").
- **FR-1.4.4 (implements brief R3):** For destructive actions like deletion, the system must implement a multi-step confirmation flow, requiring explicit user verification before execution.
- **FR-1.4.5 (implements brief R3):** Users shall only be able to delete reports they own (created themselves). The system shall enforce this scoping in the preview step.
- **FR-1.4.6 (implements brief R3 — *GDPR compliance*):** The system shall provide a `delete_user_data(user_id)` administrative operation that cascades deletion across every store keyed on `user_id`. Specifically:
  - `saved_reports` — soft-delete via `deleted_at` timestamp.
  - LangGraph long-term memory store — hard-delete the user's namespace.
  - LangGraph thread checkpoints — hard-delete all threads owned by the user.
  - Per-user cost attribution and observability traces — anonymize (preserve aggregate dashboards and eval failure-mode samples) rather than hard-delete.
  - The audit log shall **not** be deleted, per GDPR Article 17(3)(b) (legal-obligation carve-out); the audit log is the record of the deletion itself.
  - The operation shall be HITL-gated with a typed confirmation token, restricted by IAM to an explicit administrator group, and shall write an immutable audit-log entry capturing actor, target user, timestamp, and per-store affected-row counts.
  - A daily reconciliation job shall verify that no `user_id` from a known deletion appears in any store other than `audit_log`, alerting on discrepancies.

### 1.5 Continuous Improvement
- **FR-1.5.1 (implements brief R4):** The system shall provide a documented workflow for expert data analysts to review user interactions and contribute new, validated "Golden Knowledge" trios (Question → SQL Query → Analyst Report) to the knowledge base.
- **FR-1.5.2 (implements brief R4):** The system shall incorporate newly added Golden Knowledge trios into its retrieval strategy to improve accuracy for future queries.
- **FR-1.5.3 (implements brief R4):** The system shall allow end users to provide feedback (positive / negative) on responses.
- **FR-1.5.4 (implements brief R4):** Positively-rated interactions shall be added to a candidate queue for analyst review and possible promotion to Trios.
- **FR-1.5.5 (implements brief R4):** Negatively-rated interactions shall be logged as quality signals for failure analysis.
- **FR-1.5.6 (implements brief R4 — quality preservation under schema change):** The system shall run a scheduled (nightly) drift-detection job that dry-runs the SQL of every active Trio against the current database schema. Trios whose SQL fails dry-run shall be automatically marked `quarantined` and excluded from retrieval until an analyst re-validates them via the curation UI. A schema-level change that quarantines more than a configurable fraction of trios in a single run shall raise a high-severity operational alert.
- **FR-1.5.7 (implements brief R4 — controlled learning):** No user-flagged interaction shall be promoted into the Golden Knowledge base without explicit analyst review. Positive feedback (FR-1.5.4) routes the interaction into the candidate queue; promotion requires an analyst's approve/edit action in the curation UI. This invariant exists to prevent low-quality or attacker-influenced interactions from poisoning the few-shot example pool used by the SQL generator.

### 1.6 Adaptability and Personalization
- **FR-1.6.1 (implements brief R8):** The system shall learn and store individual user preferences for report formatting (e.g., tables, bullet points, charts).
- **FR-1.6.2 (implements brief R8):** The system shall apply the user's preferred format to all subsequent reports generated for that user.
- **FR-1.6.3 (implements brief R8):** Users shall have a mechanism to change their saved preferences.
- **FR-1.6.4 (implements brief R8):** The system shall provide a simple administrative interface for authorized non-developers to update the agent's persona (e.g., communication tone, greeting, sign-off).
- **FR-1.6.5 (implements brief R8):** Changes to the agent's persona must take effect within a short propagation window without redeployment.
- **FR-1.6.6 (implements brief R8 — protection against single-account compromise):** Activation of a new persona version shall require a **policy-configurable** approval gate. The governing policy is the `PERSONA_REQUIRE_DISTINCT_PROPOSER` flag (recommended default: enabled): when enabled, activation requires at least one approver who is not the proposer of the change (four-eyes principle for privileged configuration, minimum two distinct humans); when disabled, the proposer may activate alone (an explicit opt-in appropriate only for very small organizations). The policy floor may be raised in future without breaking this gate. The system shall additionally validate every proposed persona payload against an explicit schema and reject proposals containing unknown keys or fields exceeding length bounds at submission time — preventing an attacker from smuggling injection payloads inside arbitrary keys. The audit trail (FR-1.4.6, audit log) shall capture proposer, approver(s), activation time, and a diff hash of every persona change.

### 1.7 System Resilience and Reliability
- **FR-1.7.1 (implements brief R5):** The system shall automatically detect when a generated SQL query fails due to syntax errors.
- **FR-1.7.2 (implements brief R5):** Upon detecting a syntax error, the system shall attempt to self-correct the query and re-execute it up to a predefined number of times.
- **FR-1.7.3 (implements brief R5):** When a query returns empty results, the system shall attempt one bounded re-generation with the empty-result context, then return a graceful response indicating no matching data was found and suggesting refinements.
- **FR-1.7.4 (implements brief R5):** The system shall enforce a per-request token budget that, if exceeded, aborts further self-correction attempts and returns a graceful failure message.
- **FR-1.7.5 (implements brief R5 — *resilient to API/3rd party services failures/downtime*):** The system shall remain operational in the face of transient failures or downtime of external dependencies (LLM provider, BigQuery, vector store, observability sinks). Specifically:
  - Transient network/API failures shall be retried with exponential backoff, distinct from the semantic SQL self-correction loop.
  - Observability sinks shall be non-blocking and fail-silent: a tracing or logging outage shall not block, slow, or crash a user request.
  - Where configured, the LLM call layer shall fail over to an alternative provider (e.g., via the Opsfleet `lc-openrouter-ollama-client`) if the primary provider is unavailable.
  - When degradation is unavoidable, the user shall receive a clear, plain-language temporary-unavailability message rather than a technical error.
- **FR-1.7.6 (implements brief R5 — *without inflating costs*, scoped per-user):** Beyond per-request token budgets (FR-1.7.4), the system shall enforce cost and rate limits at the per-user granularity:
  - Per-user request-rate limiting at the API gateway (sliding-window QPS, keyed on the user's authenticated identity).
  - Per-user daily dollar cap computed from a per-user cost-attribution table populated by the agent itself (LLM tokens, embedding tokens, and BigQuery bytes-billed, attributed to the user that initiated each request). Over-cap users shall receive a friendly "daily budget exceeded" response without invoking the LLM.
  - A high-cost-per-hour alert (e.g., $5/hour per user) shall fire to on-call, catching active abuse loops before the daily cap triggers.
  - A reconciliation job shall detect drift between the agent's in-process cost attribution and the cloud provider's official billing export, alerting on discrepancies above a configurable threshold.

### 1.8 Operational Excellence and Observability
- **FR-1.8.1 (implements brief R7):** The system shall provide a backend dashboard for administrators and developers.
- **FR-1.8.2 (implements brief R7):** The dashboard shall display key performance metrics, including query success/failure rates, response times, user engagement, cost per request, retry rate, PII redaction events, and a destructive-action audit trail.
- **FR-1.8.3 (implements brief R7):** The dashboard shall provide access to detailed, anonymized interaction logs for debugging and deep-dive analysis.
- **FR-1.8.4 (implements brief R7):** The dashboard shall expose per-request execution traces showing the full sequence of LLM calls, retrieved Trios, generated SQL, validation outcomes, and masking events for any individual request.

### 1.9 Quality Assurance
- **FR-1.9.1 (implements brief R6):** The system shall maintain a held-out evaluation set of analyst-approved Trios used as ground truth for regression testing.
- **FR-1.9.2 (implements brief R6):** The system shall evaluate generated SQL for correctness (executable, returns expected schema, semantic equivalence to ground-truth SQL).
- **FR-1.9.3 (implements brief R6):** The system shall evaluate generated reports for faithfulness to the retrieved data using an LLM-as-judge scoring mechanism.
- **FR-1.9.4 (implements brief R6):** Release candidates that score below configurable quality thresholds shall be blocked from deployment.
- **FR-1.9.5 (implements brief R6):** The evaluation suite shall be runnable on demand and on every release candidate.

---

## 2.0 Non-Functional Requirements

- **NFR-2.1 Performance:**
  - **NFR-2.1.1:** Average response time for simple queries (retrieved from Golden Knowledge) should be under 5 seconds.
  - **NFR-2.1.2:** Average response time for complex queries (requiring new SQL generation and execution) should be under 30 seconds.
- **NFR-2.2 Security:**
  - **NFR-2.2.1:** All data in transit and at rest shall be encrypted.
  - **NFR-2.2.2:** The connection to the primary database must be strictly read-only.
  - **NFR-2.2.3:** User authentication and authorization shall be required to access the service and manage personal reports.
- **NFR-2.3 Usability:**
  - **NFR-2.3.1:** The user interface shall be intuitive for non-technical users.
  - **NFR-2.3.2:** System responses shall be clear, concise, and free of technical jargon.
  - **NFR-2.3.3:** The confirmation flow for destructive actions must be unambiguous and easy to follow.
- **NFR-2.4 Reliability & Resilience:**
  - **NFR-2.4.1:** The system shall have an uptime of 99.5%.
  - **NFR-2.4.2:** The system must handle failures of external services (e.g., LLM API) gracefully, informing the user of a temporary issue without crashing.
- **NFR-2.5 Maintainability & Agility:**
  - **NFR-2.5.1:** The system architecture shall be modular to allow for independent updates of components (e.g., query engine, UI, persona config).
  - **NFR-2.5.2:** The process for adding new expert analyses to the "Golden Knowledge" base should be simple and well-documented.
- **NFR-2.6 Observability:**
  - **NFR-2.6.1:** The system shall log all queries, generated SQL, system errors, and performance metrics.
  - **NFR-2.6.2:** The system shall provide real-time monitoring and alerting for critical failures (e.g., database connection loss, high API error rate).

---

## 3.0 Illustrative User Stories

These vignettes humanize the FRs above with concrete end-user scenarios from the Store/Regional Manager persona. They are not the canonical behavior spec — the formal actor↔system flows live in `03_Use_Case_Diagrams.md`. Stories whose acceptance criteria duplicated a use case have been folded into the corresponding UC.

- **US-1: Querying Sales Performance**
  - **As a** Regional Manager,
  - **I want to** ask "What were the top 5 selling products in the North region last quarter?"
  - **So that** I can inform inventory planning for the upcoming quarter.
  - **Acceptance Criteria:**
    - The system correctly identifies the entities: 'top 5 products', 'North region', and 'last quarter'.
    - The system generates a valid SQL query to retrieve the data.
    - The final output is a list of the 5 products with the highest sales volume/revenue in that region and time frame.
    - The response is formatted according to my saved preferences (e.g., a table).

- **US-2: Comparative Analysis**
  - **As a** Store Manager,
  - **I want to** ask "How does my store's performance in electronics compare to the store in city Y?"
  - **So that** I can identify areas for improvement.
  - **Acceptance Criteria:**
    - The system understands the context of "my store".
    - The system retrieves and compares key performance metrics (e.g., sales revenue, units sold) for the 'electronics' category for both stores.
    - The response provides a clear, summarized comparison.

- **US-4: PII Redaction in Action**
  - **As a** Manager, 
  - **I want to** ask "Who are my top customers?" and have their contact details automatically hidden, 
  - **so that** I don't accidentally see PII I'm not entitled to.
  - **Acceptance Criteria:**
    - The system retrieves customer-related data including phone and email columns.
    - All phone/email values are replaced with redaction placeholders (e.g., [REDACTED:email]) before the response is rendered.
    - The redaction is noted in the response so the user understands fields were masked.

- **US-5: Graceful Failure Handling**
  - **As a** Manager, 
  - **when** my query is ambiguous or fails, 
  - **I want** a clear explanation rather than a stack trace, 
  - **so that** I can refine and try again.
  - **Acceptance Criteria:**
    - When the system cannot produce a valid SQL query after bounded retries, the user sees a clear, plain-language explanation.
    - The response avoids technical jargon (no SQL errors, stack traces, or internal IDs).
    - The response suggests how the user might refine their question.

---

## 4.0 Constraints and Assumptions

### 4.1 Constraints
- **C-1:** The system's access to the primary SQL database is strictly **read-only**.
- **C-2:** The initial development will target the schema of the `bigquery-public-data.thelook_ecommerce` dataset, specifically the orders, order_items, products, and users tables.
- **C-3:** The system is for internal use by company employees only.
- **C-4:** The "Golden Knowledge" base is the secondary source of truth for complex, previously analyzed questions.
- **C-5:** The solution should preferably be built using the LangGraph or LangChain V1 framework.

### 4.2 Assumptions
- **A-1:** The data in the SQL database is accurate and up-to-date.
- **A-2:** An initial set of high-quality "Golden Knowledge" trios will be provided by expert data analysts before launch.
- **A-3:** Target users (Store and Regional Managers) are proficient enough to use a chat interface but have limited to no SQL knowledge.
- **A-4:** A user authentication system is in place or can be integrated to identify individual users.

---

## 5.0 Dependencies

### 5.1 Internal Dependencies
- **ID-1:** Continuous, reliable read-only access to the company's retail SQL database.
- **ID-2:** Access to and maintenance of the "Golden Knowledge" data repository.
- **ID-3:** Availability of an identity and access management (IAM) service for user authentication.

### 5.2 External Dependencies
- **ED-1:** A third-party Large Language Model (LLM) API (e.g., OpenAI, Google, Anthropic; Google Gemini is preferred) for natural language understanding and SQL generation.
- **ED-2:** Cloud hosting provider (e.g., GCP, AWS, Azure; GCP is the primary target, as it hosts the BigQuery data source) for application services, databases, and monitoring tools.
