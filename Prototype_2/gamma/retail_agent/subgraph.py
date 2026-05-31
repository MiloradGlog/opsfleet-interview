"""The analysis subgraph — sealed SQL lifecycle (brief R5: Resilience + R1: Hybrid).

A compiled LangGraph ``StateGraph`` that owns the deterministic path:

    retrieve_trios -> generate_sql -> validate_sql -> execute_bq -> END
                          ^                  |  invalid & attempts<N -> repair_sql ┐
                          └── repair_sql ────┤  empty & not retried   -> repair_empty
                                             └  error & exhausted     -> graceful_fail

* ``retrieve_trios`` is structurally FIRST — the agent cannot skip retrieval (R1).
* ``generate_sql`` and ``repair_sql`` share one prompt site ("generate again, with
  the error in context"), so there is a single generation behavior.
* ``execute_bq`` classifies failures: a *semantic* SQL error routes to repair; a
  *transient* error is re-raised to the agent's ToolRetryMiddleware.
* The loop is bounded by ``max_attempts`` (total generations including the first)
  and terminates into ``graceful_fail``.

Collaborators (retrieve, complete, run_query) are injected so the subgraph is
unit-testable offline with fakes.
"""
from __future__ import annotations

import operator
import re
from dataclasses import dataclass
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from . import sql_guard
from .bigquery_client import is_transient_error
from .prompts import build_empty_repair_prompt, build_repair_prompt, build_sql_prompt

# Injected collaborators ------------------------------------------------------
RetrieveFn = Callable[[str, int], list[dict]]
CompleteFn = Callable[[str], str]      # prompt -> raw model text
RunQueryFn = Callable[[str], Any]      # sql -> pandas.DataFrame (duck-typed)


@dataclass
class AnalysisDeps:
    retrieve: RetrieveFn
    complete: CompleteFn
    run_query: RunQueryFn
    schema: str
    max_attempts: int = 2          # total SQL generations INCLUDING the first
    max_result_rows: int = 1000
    preview_rows: int = 50
    top_k: int = 3


class AnalysisState(TypedDict, total=False):
    question: str
    trios: list[dict]
    trio_ids: list[str]
    sql: str
    attempts: int
    errors: Annotated[list[str], operator.add]
    last_error: str
    valid: bool
    exec_result: str           # "success" | "empty" | "error"
    rows: list[dict]
    columns: list[str]
    row_count: int
    truncated: bool
    empty_retried: bool
    status: str                # "ok" | "empty" | "failed"
    message: str


_FENCE = re.compile(r"^```(?:sql)?|```$", re.IGNORECASE | re.MULTILINE)


def _clean_sql(raw: str) -> str:
    """Strip markdown fences / stray 'sql' prefixes the model may add."""
    text = _FENCE.sub("", raw or "").strip()
    if text.lower().startswith("sql\n"):
        text = text[4:]
    return text.strip()


def build_analysis_subgraph(deps: AnalysisDeps):
    """Compile and return the analysis StateGraph for the given collaborators."""

    def retrieve_trios(state: AnalysisState) -> dict:
        trios = deps.retrieve(state["question"], deps.top_k)
        return {"trios": trios, "trio_ids": [t.get("id", "?") for t in trios]}

    def generate_sql(state: AnalysisState) -> dict:
        prompt = build_sql_prompt(state["question"], state.get("trios", []), deps.schema)
        return {"sql": _clean_sql(deps.complete(prompt)), "attempts": 1}

    def repair_sql(state: AnalysisState) -> dict:
        prompt = build_repair_prompt(
            state["question"], state.get("sql", ""), state.get("last_error", ""), deps.schema
        )
        return {
            "sql": _clean_sql(deps.complete(prompt)),
            "attempts": state.get("attempts", 1) + 1,
        }

    def repair_empty(state: AnalysisState) -> dict:
        prompt = build_empty_repair_prompt(
            state["question"], state.get("sql", ""), deps.schema
        )
        return {
            "sql": _clean_sql(deps.complete(prompt)),
            "attempts": state.get("attempts", 1) + 1,
            "empty_retried": True,
        }

    def validate_sql(state: AnalysisState) -> dict:
        try:
            safe = sql_guard.validate(state.get("sql", ""), max_rows=deps.max_result_rows)
            return {"sql": safe, "valid": True}
        except sql_guard.SQLGuardError as exc:
            return {"valid": False, "errors": [f"validation: {exc}"], "last_error": str(exc)}

    def execute_bq(state: AnalysisState) -> dict:
        try:
            df = deps.run_query(state["sql"])
        except Exception as exc:  # noqa: BLE001 - classify, then route or re-raise
            if is_transient_error(exc):
                raise  # transient -> ToolRetryMiddleware retries the whole tool
            return {
                "valid": False,
                "exec_result": "error",
                "errors": [f"execution: {exc}"],
                "last_error": str(exc),
            }
        row_count = int(len(df))
        if row_count == 0:
            return {"exec_result": "empty", "row_count": 0}
        preview = df.head(deps.preview_rows)
        return {
            "status": "ok",
            "exec_result": "success",
            "rows": preview.to_dict("records"),
            "columns": [str(c) for c in df.columns],
            "row_count": row_count,
            "truncated": row_count > deps.preview_rows,
        }

    def graceful_fail(state: AnalysisState) -> dict:
        if state.get("exec_result") == "empty":
            return {
                "status": "empty",
                "message": "No matching data was found for that question. Try broadening "
                "the time range or relaxing the filters.",
            }
        return {
            "status": "failed",
            "message": "I couldn't produce a valid query for that question after a few "
            "attempts. Try rephrasing it or making it more specific (name the metric, "
            "time period, or category you're interested in).",
        }

    # --- routing -------------------------------------------------------------
    def route_after_validate(state: AnalysisState) -> str:
        if state.get("valid"):
            return "execute"
        return "repair" if state.get("attempts", 0) < deps.max_attempts else "fail"

    def route_after_execute(state: AnalysisState) -> str:
        result = state.get("exec_result")
        if result == "success":
            return "done"
        if result == "empty":
            return "empty_retry" if not state.get("empty_retried") else "fail"
        # semantic execution error
        return "repair" if state.get("attempts", 0) < deps.max_attempts else "fail"

    # --- wiring --------------------------------------------------------------
    g = StateGraph(AnalysisState)
    g.add_node("retrieve_trios", retrieve_trios)
    g.add_node("generate_sql", generate_sql)
    g.add_node("validate_sql", validate_sql)
    g.add_node("execute_bq", execute_bq)
    g.add_node("repair_sql", repair_sql)
    g.add_node("repair_empty", repair_empty)
    g.add_node("graceful_fail", graceful_fail)

    g.add_edge(START, "retrieve_trios")
    g.add_edge("retrieve_trios", "generate_sql")
    g.add_edge("generate_sql", "validate_sql")
    g.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {"execute": "execute_bq", "repair": "repair_sql", "fail": "graceful_fail"},
    )
    g.add_conditional_edges(
        "execute_bq",
        route_after_execute,
        {
            "done": END,
            "repair": "repair_sql",
            "empty_retry": "repair_empty",
            "fail": "graceful_fail",
        },
    )
    g.add_edge("repair_sql", "validate_sql")
    g.add_edge("repair_empty", "validate_sql")
    g.add_edge("graceful_fail", END)
    return g.compile()


def initial_state(question: str) -> AnalysisState:
    return {
        "question": question,
        "trios": [],
        "sql": "",
        "attempts": 0,
        "errors": [],
        "empty_retried": False,
        "row_count": 0,
    }
