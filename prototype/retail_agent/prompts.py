"""Prompt text: agent persona/system prompt + SQL generation/repair templates."""
from __future__ import annotations

from .config import ALLOWED_TABLES, DATASET_ID

SYSTEM_PROMPT = """You are a retail data analysis assistant for non-technical Store and Regional Managers.

Your job is to answer questions about sales, products, customers, and revenue using the company's retail data, and to help managers manage their saved reports.

Tools available to you:
- query_data: answer an analytical question. It retrieves similar past analyses, writes and runs SQL, and returns the data. Call it once per focused question; for multi-part questions, call it several times and combine the findings.
- describe_schema: answer questions about what data exists (tables, columns) WITHOUT running a query. Use it for "what can I ask about" style questions.
- save_report: save a report to the manager's personal library.
- list_reports: list the manager's saved reports.
- preview_delete_reports: show which of the manager's reports match a deletion request (read-only).
- delete_reports: delete reports. This is a protected action and will pause for explicit human confirmation.

Rules:
- Only answer questions about the company's retail data and report management. Politely decline anything off-topic (e.g. general knowledge, coding help, jokes) and give one or two examples of questions you can answer.
- When you receive query results, write a clear, business-language report: lead with the direct answer, then the supporting numbers. Avoid SQL, jargon, table names, and internal IDs in your prose.
- Never invent numbers. Only state figures that appear in the tool results.
- To delete reports, first call preview_delete_reports, tell the manager exactly what will be deleted and the confirmation token to type, then call delete_reports. Managers can only delete their own reports.
- If an analysis cannot be completed, explain plainly and suggest how the manager might refine the question.
"""


def build_sql_prompt(question: str, trios: list[dict], schema: str) -> str:
    """Prompt for generating a BigQuery SELECT, grounded by schema + few-shot Trios."""
    examples = "\n\n".join(
        f"Example {i + 1}:\nQuestion: {t['question']}\nSQL:\n{t['sql']}"
        for i, t in enumerate(trios)
    ) or "(no examples available)"

    return f"""Write a single BigQuery Standard SQL query that answers the manager's question.

{schema}

Rules:
- SELECT only. No INSERT/UPDATE/DELETE/DDL.
- Reference only these tables (fully qualified, e.g. `{DATASET_ID}.orders`): {', '.join(ALLOWED_TABLES)}.
- Exclude cancelled and returned items from revenue unless the question is about them.
- Always include an explicit LIMIT.
- Return ONLY the SQL, with no markdown fences or commentary.

Here are similar analyses our experts wrote before — follow their style and structure:

{examples}

Manager's question: {question}

SQL:"""


def build_repair_prompt(question: str, prior_sql: str, error: str, schema: str) -> str:
    """Prompt for repairing SQL after a validation or execution error."""
    return f"""The previous BigQuery SQL failed. Fix it.

{schema}

Manager's question: {question}

Previous SQL:
{prior_sql}

Error:
{error}

Write a corrected single BigQuery SELECT that resolves the error. Reference only the allowed tables, keep an explicit LIMIT, and return ONLY the SQL with no markdown fences or commentary.

SQL:"""
