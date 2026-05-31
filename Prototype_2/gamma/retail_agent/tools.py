"""The six manager-facing tools. Built as closures over an ``AgentRuntime`` so they
share the wired collaborators and the session's user/thread identity.

Only manager-facing tools live here. The single destructive tool, ``delete_reports``,
is gated by HumanInTheLoopMiddleware in :mod:`agent`. There are deliberately no
admin/persona/GDPR tools — an operation the agent has no tool for is unreachable
(HLD §4.1 containment boundary).
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

from .schema_catalog import describe_schema as _describe_schema
from .subgraph import initial_state

log = logging.getLogger("retail_agent.tools")


def _format_analysis(result: dict) -> str:
    """Render the subgraph result into text the agent narrates into a report."""
    status = result.get("status")
    if status != "ok":
        return result.get("message", "I couldn't complete that analysis.")

    rows = result.get("rows", [])
    columns = result.get("columns", [])
    row_count = result.get("row_count", len(rows))
    trio_ids = result.get("trio_ids", [])
    sql = result.get("sql", "")

    if rows:
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join("---" for _ in columns) + " |"
        body = "\n".join(
            "| " + " | ".join(str(r.get(c, "")) for c in columns) + " |" for r in rows
        )
        table = "\n".join([header, sep, body])
    else:
        table = "(no rows)"

    note = ""
    if result.get("truncated"):
        note = f"\n(Showing the first {len(rows)} of {row_count} rows.)"

    return (
        f"Query returned {row_count} row(s). Retrieved examples: "
        f"{', '.join(trio_ids) or 'none'}.\nSQL used:\n{sql}\n\nResults:\n{table}{note}\n\n"
        "Summarize these results for the manager in clear business language."
    )


def build_tools(runtime) -> list:
    """Return the tool list bound to this runtime."""

    @tool
    def query_data(question: str) -> str:
        """Answer one analytical question about the retail data (sales, products,
        customers, revenue). Runs retrieval -> SQL generation -> execution and
        returns the data to summarize. Call once per focused question."""
        log.info("query_data: %s", question)
        result = runtime.subgraph.invoke(initial_state(question))
        return _format_analysis(result)

    @tool
    def describe_schema(topic: str = "") -> str:
        """Describe what data is available (tables and columns) in business language,
        WITHOUT running a query. Use for 'what can I ask about' style questions.
        Optionally pass a topic/table name to focus the description."""
        return _describe_schema(topic)

    @tool
    def save_report(title: str, body: str) -> str:
        """Save a report to the manager's personal library. ``body`` is the full
        report text to store; ``title`` is a short label."""
        report_id = runtime.storage.save_report(runtime.user_id, title, body)
        return f'Saved report #{report_id}: "{title}".'

    @tool
    def list_reports() -> str:
        """List the manager's saved reports (id, title, date)."""
        rows = runtime.storage.list_reports(runtime.user_id)
        if not rows:
            return "You have no saved reports."
        lines = [
            f"#{r['id']} — \"{r['title']}\" (saved {str(r['created_at'])[:10]})" for r in rows
        ]
        return "Your saved reports:\n" + "\n".join(lines)

    @tool
    def preview_delete_reports(criteria: str) -> str:
        """Preview which of the manager's OWN reports match a deletion request
        (read-only; deletes nothing). ``criteria`` is matched against report title
        and body. Always call this before delete_reports."""
        prev = runtime.storage.preview_deletable(runtime.user_id, criteria)
        if prev["count"] == 0:
            return f'None of your saved reports match "{criteria}". Nothing to delete.'
        listing = "\n".join(
            f'#{rid} — "{title}"' for rid, title in zip(prev["ids"], prev["titles"])
        )
        token = f"CONFIRM-DELETE-{prev['count']}"
        return (
            f'{prev["count"]} of your reports match "{criteria}":\n{listing}\n\n'
            f"To proceed, call delete_reports with these ids {prev['ids']} and the "
            f'confirmation token "{token}". The manager must type "{token}" to approve.'
        )

    @tool
    def delete_reports(report_ids: list[int], confirmation_token: str) -> str:
        """Delete the manager's saved reports by id. PROTECTED: execution pauses for
        explicit human approval. ``confirmation_token`` must be "CONFIRM-DELETE-N"
        where N is the number of ids. Only the manager's own reports are affected."""
        expected = f"CONFIRM-DELETE-{len(report_ids)}"
        if (confirmation_token or "").strip() != expected:
            return (
                f'Confirmation token did not match (expected "{expected}"). '
                "Nothing was deleted."
            )
        op_id = runtime.storage.op_id(runtime.user_id, runtime.thread_id, report_ids)
        counts = runtime.storage.soft_delete(runtime.user_id, report_ids)
        runtime.storage.write_audit(op_id, runtime.user_id, "delete_reports", report_ids, counts)
        msg = f"Deleted {counts['deleted']} report(s)."
        if counts["already_gone"]:
            msg += f" ({counts['already_gone']} had already been deleted.)"
        return msg

    return [
        query_data,
        describe_schema,
        save_report,
        list_reports,
        preview_delete_reports,
        delete_reports,
    ]
