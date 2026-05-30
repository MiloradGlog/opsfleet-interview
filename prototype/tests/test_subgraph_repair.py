"""Analysis subgraph resilience: repair loop, empty handling, graceful fail,
and transient-vs-semantic error separation. All offline (LLM + BigQuery faked)."""
import pandas as pd
import pytest

from retail_agent.subgraph import AnalysisDeps, build_analysis_subgraph, initial_state

DS = "bigquery-public-data.thelook_ecommerce"
VALID_SQL = f"SELECT category FROM `{DS}.products` LIMIT 5"
INVALID_SQL = f"DELETE FROM `{DS}.products`"  # rejected by the guard


def _sequenced(responses):
    """A complete() fake returning queued responses, then repeating the last."""
    box = {"i": 0}

    def complete(_prompt: str) -> str:
        i = min(box["i"], len(responses) - 1)
        box["i"] += 1
        return responses[i]

    return complete


def _retrieve(_q, _k):
    return [{"id": "trio-demo", "question": "demo", "sql": VALID_SQL, "report": "r"}]


def _deps(complete, run_query, max_attempts=3):
    return AnalysisDeps(
        retrieve=_retrieve, complete=complete, run_query=run_query,
        schema="(schema)", max_attempts=max_attempts, max_result_rows=1000, preview_rows=50,
    )


def test_happy_path_returns_rows():
    df = pd.DataFrame([{"category": "Jeans", "rev": 100}, {"category": "Tees", "rev": 80}])
    graph = build_analysis_subgraph(_deps(_sequenced([VALID_SQL]), lambda sql: df))
    out = graph.invoke(initial_state("revenue by category"))
    assert out["status"] == "ok"
    assert out["row_count"] == 2
    assert out["trio_ids"] == ["trio-demo"]
    assert len(out["rows"]) == 2


def test_repairs_invalid_sql_then_succeeds():
    df = pd.DataFrame([{"x": 1}])
    graph = build_analysis_subgraph(_deps(_sequenced([INVALID_SQL, VALID_SQL]), lambda sql: df))
    out = graph.invoke(initial_state("q"))
    assert out["status"] == "ok"
    assert out["attempts"] == 2
    assert any("validation" in e for e in out["errors"])


def test_semantic_execution_error_triggers_repair():
    calls = {"n": 0}

    def run_query(sql):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Unrecognized name: foo")  # non-transient -> semantic
        return pd.DataFrame([{"ok": 1}])

    graph = build_analysis_subgraph(_deps(_sequenced([VALID_SQL, VALID_SQL]), run_query))
    out = graph.invoke(initial_state("q"))
    assert out["status"] == "ok"
    assert any("execution" in e for e in out["errors"])


def test_exhaustion_yields_graceful_failure():
    graph = build_analysis_subgraph(_deps(_sequenced([INVALID_SQL]), lambda sql: pd.DataFrame()))
    out = graph.invoke(initial_state("q"))
    assert out["status"] == "failed"
    assert "couldn't" in out["message"].lower() or "could not" in out["message"].lower()
    assert out["attempts"] == 3  # bounded


def test_empty_result_retries_once_then_graceful():
    empty = pd.DataFrame(columns=["a"])
    graph = build_analysis_subgraph(_deps(_sequenced([VALID_SQL, VALID_SQL]), lambda sql: empty))
    out = graph.invoke(initial_state("q"))
    assert out["status"] == "empty"
    assert out["empty_retried"] is True
    assert "no matching data" in out["message"].lower()


def test_transient_error_is_reraised_not_repaired():
    def run_query(sql):
        raise TimeoutError("connection reset")  # transient

    graph = build_analysis_subgraph(_deps(_sequenced([VALID_SQL]), run_query))
    with pytest.raises(Exception):
        graph.invoke(initial_state("q"))


def test_two_repairs_then_success_within_budget():
    df = pd.DataFrame([{"x": 1}])
    graph = build_analysis_subgraph(
        _deps(_sequenced([INVALID_SQL, INVALID_SQL, VALID_SQL]), lambda sql: df, max_attempts=3)
    )
    out = graph.invoke(initial_state("q"))
    assert out["status"] == "ok"
    assert out["attempts"] == 3
    assert len([e for e in out["errors"] if "validation" in e]) == 2


def test_clean_sql_strips_markdown_fences():
    from retail_agent.subgraph import _clean_sql
    assert _clean_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert _clean_sql("```\nSELECT 2\n```") == "SELECT 2"
    assert _clean_sql("sql\nSELECT 3") == "SELECT 3"
    assert _clean_sql("  SELECT 4  ") == "SELECT 4"


def test_preview_rows_truncation_reports_full_count():
    df = pd.DataFrame([{"n": i} for i in range(5)])
    deps = AnalysisDeps(
        retrieve=_retrieve, complete=_sequenced([VALID_SQL]), run_query=lambda sql: df,
        schema="(s)", max_attempts=3, max_result_rows=1000, preview_rows=2,
    )
    out = build_analysis_subgraph(deps).invoke(initial_state("q"))
    assert out["status"] == "ok"
    assert out["row_count"] == 5          # full count preserved
    assert len(out["rows"]) == 2          # preview capped
    assert out["truncated"] is True


def test_empty_then_repair_finds_rows():
    calls = {"n": 0}

    def run_query(sql):
        calls["n"] += 1
        return pd.DataFrame() if calls["n"] == 1 else pd.DataFrame([{"x": 1}])

    graph = build_analysis_subgraph(_deps(_sequenced([VALID_SQL, VALID_SQL]), run_query))
    out = graph.invoke(initial_state("q"))
    assert out["status"] == "ok"
    assert out["empty_retried"] is True
