"""Subgraph resilience (R5): semantic repair, empty retry, exhaustion, transient re-raise."""
import pandas as pd
import pytest

from retail_agent.subgraph import AnalysisDeps, build_analysis_subgraph, initial_state


def _retrieve(_q, _k):
    return [{"id": "t1", "question": "q", "sql": "SELECT 1 FROM orders LIMIT 1"}]


def _deps(complete, run_query, max_attempts=2):
    return AnalysisDeps(
        retrieve=_retrieve,
        complete=complete,
        run_query=run_query,
        schema="schema",
        max_attempts=max_attempts,
    )


def test_happy_path_returns_rows():
    sql = "SELECT category, revenue FROM order_items LIMIT 10"
    df = pd.DataFrame([{"category": "Jeans", "revenue": 100}, {"category": "Swim", "revenue": 80}])
    g = build_analysis_subgraph(_deps(lambda p: sql, lambda s: df))
    out = g.invoke(initial_state("revenue by category"))
    assert out["status"] == "ok"
    assert out["rows"] == [{"category": "Jeans", "revenue": 100}, {"category": "Swim", "revenue": 80}]
    assert out["row_count"] == 2


def test_semantic_repair_recovers_on_second_generation():
    # First gen: invalid (unknown table). Second gen: valid.
    gens = iter(["SELECT * FROM nope LIMIT 5", "SELECT * FROM orders LIMIT 5"])
    calls = {"n": 0}

    def run(sql):
        calls["n"] += 1
        return pd.DataFrame([{"x": 1}])

    g = build_analysis_subgraph(_deps(lambda p: next(gens), run, max_attempts=2))
    out = g.invoke(initial_state("q"))
    assert out["status"] == "ok"
    assert calls["n"] == 1  # only the valid query reached execution


def test_exhaustion_goes_to_graceful_fail():
    # Every generation is invalid; with max_attempts=2 we get initial + 1 repair, then fail.
    g = build_analysis_subgraph(
        _deps(lambda p: "SELECT * FROM nope LIMIT 5", lambda s: pd.DataFrame(), max_attempts=2)
    )
    out = g.invoke(initial_state("q"))
    assert out["status"] == "failed"
    assert "couldn't" in out["message"].lower()


def test_empty_result_triggers_one_shot_empty_repair_then_data():
    gens = iter(["SELECT * FROM orders LIMIT 5", "SELECT * FROM orders LIMIT 50"])
    runs = iter([pd.DataFrame(), pd.DataFrame([{"x": 1}])])  # empty, then data
    g = build_analysis_subgraph(_deps(lambda p: next(gens), lambda s: next(runs)))
    out = g.invoke(initial_state("q"))
    assert out["status"] == "ok"
    assert out["rows"] == [{"x": 1}]


def test_empty_twice_goes_to_graceful_empty():
    g = build_analysis_subgraph(
        _deps(lambda p: "SELECT * FROM orders LIMIT 5", lambda s: pd.DataFrame())
    )
    out = g.invoke(initial_state("q"))
    assert out["status"] == "empty"
    assert "no matching data" in out["message"].lower()


def test_transient_error_is_re_raised_not_repaired():
    from google.api_core import exceptions as gexc

    def run(sql):
        raise gexc.ServiceUnavailable("503 backend error")

    g = build_analysis_subgraph(
        _deps(lambda p: "SELECT * FROM orders LIMIT 5", run, max_attempts=2)
    )
    # Re-raised to ToolRetryMiddleware rather than swallowed into repair.
    with pytest.raises(gexc.ServiceUnavailable):
        g.invoke(initial_state("q"))


def test_semantic_bigquery_error_routes_to_repair():
    from google.api_core import exceptions as gexc

    gens = iter(["SELECT bad FROM orders LIMIT 5", "SELECT * FROM orders LIMIT 5"])
    runs = iter([gexc.BadRequest("400 unknown column"), pd.DataFrame([{"x": 1}])])

    def run(sql):
        r = next(runs)
        if isinstance(r, Exception):
            raise r
        return r

    g = build_analysis_subgraph(_deps(lambda p: next(gens), run, max_attempts=2))
    out = g.invoke(initial_state("q"))
    assert out["status"] == "ok"
