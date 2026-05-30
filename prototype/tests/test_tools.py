"""Tool-level tests: report management + the delete tool's token/scoping/audit
logic, exercised without the LLM (build_tools needs no model)."""
import pytest

from retail_agent.config import Settings
from retail_agent.runtime import AgentRuntime
from retail_agent.tools import build_tools


@pytest.fixture
def runtime(tmp_path):
    settings = Settings(
        google_api_key=None, gcp_project=None, gemini_model="m", embed_model="e",
        user_id="manager_a", hmac_secret="test-secret", max_sql_attempts=3,
        max_result_rows=1000, preview_rows=50, model_run_limit=8, data_dir=tmp_path,
    )
    rt = AgentRuntime(settings, thread_id="thread-1")
    yield rt
    rt.close()


def _by_name(tools):
    return {t.name: t for t in tools}


def test_tool_surface_is_manager_facing_only(runtime):
    names = set(_by_name(build_tools(runtime)))
    assert names == {
        "query_data", "describe_schema", "save_report",
        "list_reports", "preview_delete_reports", "delete_reports",
    }


def test_save_and_list(runtime):
    tools = _by_name(build_tools(runtime))
    out = tools["save_report"].invoke({"title": "Q2 review", "body": "numbers"})
    assert "Saved report #1" in out
    listing = tools["list_reports"].invoke({})
    assert "Q2 review" in listing


def test_describe_schema_runs_without_sql(runtime):
    tools = _by_name(build_tools(runtime))
    out = tools["describe_schema"].invoke({"topic": "products"})
    assert "products" in out.lower()
    assert "category" in out.lower()


def test_full_delete_flow_with_correct_token(runtime):
    tools = _by_name(build_tools(runtime))
    tools["save_report"].invoke({"title": "Acme analysis", "body": "client acme spend"})
    tools["save_report"].invoke({"title": "Other", "body": "unrelated"})

    preview = tools["preview_delete_reports"].invoke({"criteria": "acme"})
    assert "CONFIRM-DELETE-1" in preview
    assert "#1" in preview

    deleted = tools["delete_reports"].invoke({"report_ids": [1], "confirmation_token": "CONFIRM-DELETE-1"})
    assert "Deleted 1 report" in deleted
    # gone from listing, the unrelated one remains
    listing = tools["list_reports"].invoke({})
    assert "Acme analysis" not in listing and "Other" in listing


def test_delete_rejects_wrong_token(runtime):
    tools = _by_name(build_tools(runtime))
    tools["save_report"].invoke({"title": "Acme", "body": "acme"})
    out = tools["delete_reports"].invoke({"report_ids": [1], "confirmation_token": "CONFIRM-DELETE-9"})
    assert "did not match" in out
    assert "Acme" in tools["list_reports"].invoke({})  # still there


def test_query_data_runs_subgraph_and_formats(runtime):
    import types
    runtime._subgraph = types.SimpleNamespace(invoke=lambda state: {
        "status": "ok", "rows": [{"a": 1}], "columns": ["a"], "row_count": 1,
        "trio_ids": ["t1"], "sql": "SELECT a FROM t", "truncated": False,
    })
    tools = _by_name(build_tools(runtime))
    out = tools["query_data"].invoke({"question": "anything"})
    assert "SELECT a FROM t" in out and "t1" in out


def test_preview_no_match_message(runtime):
    tools = _by_name(build_tools(runtime))
    out = tools["preview_delete_reports"].invoke({"criteria": "nonexistent"})
    assert "Nothing to delete" in out


def test_delete_writes_audit_row(runtime):
    tools = _by_name(build_tools(runtime))
    tools["save_report"].invoke({"title": "Acme", "body": "acme"})
    tools["delete_reports"].invoke({"report_ids": [1], "confirmation_token": "CONFIRM-DELETE-1"})
    n = runtime.storage.conn.execute("SELECT COUNT(*) n FROM audit_log").fetchone()["n"]
    assert n == 1
