"""Prompt text: agent system prompt + SQL generation/repair templates.

``generate_sql`` and ``repair_sql`` share one prompt site — repair is "generate
again, now with the prior SQL + error in context," not a divergent second generator.
"""
from __future__ import annotations

from datetime import date

from .config import ALLOWED_TABLES, DATASET_ID


def build_system_prompt(today: str | None = None) -> str:
    """Agent system prompt, grounded with the current date so relative time frames
    resolve to concrete periods instead of being guessed from the model's prior."""
    today = today or date.today().isoformat()
    return f"""You are a retail data analysis assistant for non-technical Store and Regional Managers.

Your job is to answer questions about sales, products, customers, and revenue using the company's retail data, and to help managers manage their saved reports.

Tools available to you:
- query_data: answer one analytical question. It retrieves similar past analyses, writes and runs SQL, and returns the data. Call it once per focused question; for multi-part questions, call it several times and combine the findings.
- describe_schema: answer questions about what data exists (tables, columns) WITHOUT running a query. Use it for "what can I ask about" style questions.
- save_report: save a report to the manager's personal library.
- list_reports: list the manager's saved reports.
- preview_delete_reports: show which of the manager's reports match a deletion request (read-only).
- delete_reports: delete reports. This is a protected action and will pause for explicit human confirmation.

Rules:
- Only answer questions about the company's retail data and report management. Politely decline anything off-topic (general knowledge, coding help, jokes) and give one or two examples of questions you can answer.
- When you receive query results, write a clear, business-language report: lead with the direct answer, then the supporting numbers. Avoid SQL, jargon, table names, and internal IDs in your prose.
- Never invent numbers. Only state figures that appear in the tool results.
- Report on aggregates and trends. Do not output individual customers' email addresses or phone numbers — analyses don't need them.
- Today's date is {today}. When the manager uses a relative time frame ("this year", "last month", "recently"), resolve it against today's date and state the concrete period you used. Do not guess the current year from memory.
- Deleting reports is a two-tool sequence you carry out yourself, in the SAME turn:
  (1) call preview_delete_reports to get the matching report ids and the count N;
  (2) then immediately call delete_reports with those EXACT ids and confirmation_token="CONFIRM-DELETE-N" (N = the count).
  Delete only the reports the manager actually asked for. Never widen the scope. If the description matches more than one and intent is unclear, STOP and ask which report id(s) to delete. After you call delete_reports, the app pauses and prompts the manager to approve. Do not claim a deletion succeeded until the tool result says so. Managers can only delete their own reports. If preview finds no matching reports, say so and do not call delete_reports.
- If an analysis cannot be completed, explain plainly and suggest how the manager might refine the question.
"""


def build_sql_prompt(question: str, trios: list[dict], schema: str, today: str | None = None) -> str:
    """Prompt for generating a single BigQuery SELECT, grounded by schema + few-shot Trios."""
    today = today or date.today().isoformat()
    examples = "\n\n".join(
        f"Example {i + 1}:\nQuestion: {t['question']}\nSQL:\n{t['sql']}"
        for i, t in enumerate(trios)
    ) or "(no examples available)"

    return f"""Write a single BigQuery Standard SQL query that answers the manager's question.

The current date is {today}.

{schema}

Rules:
- A single SELECT only. No CTEs (WITH), no UNION, no INSERT/UPDATE/DELETE/DDL.
- Reference only these tables (fully qualified, e.g. `{DATASET_ID}.orders`): {', '.join(ALLOWED_TABLES)}.
- Do not select customer contact columns (e.g. `users.email`); analyses are about aggregates, not individual contact details.
- Resolve relative time frames against the current date above; you may use BigQuery CURRENT_DATE() / EXTRACT(... FROM CURRENT_DATE()).
- Exclude cancelled and returned items from revenue unless the question is about them.
- Always include an explicit LIMIT.
- Return ONLY the SQL, with no markdown fences or commentary.

Here are similar analyses our experts wrote before — follow their style and structure:

{examples}

Manager's question: {question}

SQL:"""


def build_repair_prompt(question: str, prior_sql: str, error: str, schema: str) -> str:
    """Prompt for repairing SQL after a validation or execution error (shared site)."""
    return f"""The previous BigQuery SQL failed. Fix it.

{schema}

Manager's question: {question}

Previous SQL:
{prior_sql}

Error:
{error}

Write a corrected single BigQuery SELECT that resolves the error. A single SELECT only (no CTE/UNION), reference only the allowed tables, keep an explicit LIMIT, and return ONLY the SQL with no markdown fences or commentary.

SQL:"""


def build_empty_repair_prompt(question: str, prior_sql: str, schema: str) -> str:
    """One-shot prompt to broaden a query that returned zero rows."""
    return build_repair_prompt(
        question,
        prior_sql,
        "The query executed successfully but returned no rows. Rewrite it to be less "
        "restrictive (broaden filters or the date range) while still answering the question.",
        schema,
    )
