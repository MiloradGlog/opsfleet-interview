"""Formatting of the analysis-subgraph result into text the agent narrates."""
from retail_agent.tools import _format_analysis


def _ok(**over):
    base = {
        "status": "ok",
        "rows": [{"category": "Jeans", "rev": 100}, {"category": "Tees", "rev": 80}],
        "columns": ["category", "rev"],
        "row_count": 2,
        "trio_ids": ["trio-a", "trio-b"],
        "sql": "SELECT category, rev FROM t LIMIT 5",
        "truncated": False,
    }
    base.update(over)
    return base


def test_ok_includes_table_sql_and_trace():
    out = _format_analysis(_ok())
    assert "| category | rev |" in out
    assert "Jeans" in out and "Tees" in out
    assert "SELECT category, rev FROM t" in out
    assert "trio-a, trio-b" in out
    assert "Summarize these results" in out


def test_truncation_note_present_only_when_truncated():
    assert "Showing the first" not in _format_analysis(_ok())
    out = _format_analysis(_ok(truncated=True, row_count=500))
    assert "Showing the first 2 of 500 rows" in out


def test_empty_status_returns_message():
    out = _format_analysis({"status": "empty", "message": "No matching data was found."})
    assert out == "No matching data was found."


def test_failed_status_returns_message():
    out = _format_analysis({"status": "failed", "message": "I couldn't produce a valid query."})
    assert out == "I couldn't produce a valid query."


def test_ok_with_no_rows_label():
    out = _format_analysis(_ok(rows=[], columns=["category", "rev"], row_count=0))
    assert "(no rows)" in out
