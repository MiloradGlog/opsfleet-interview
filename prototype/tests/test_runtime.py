"""Runtime container: model-text extraction + schema wiring (offline)."""
import pathlib
import tempfile
import types

from retail_agent.config import Settings
from retail_agent.runtime import AgentRuntime


def _runtime():
    tmp = pathlib.Path(tempfile.mkdtemp())
    s = Settings(
        google_api_key=None, gcp_project=None, gemini_model="m", embed_model="e",
        user_id="manager_a", hmac_secret="x", max_sql_attempts=3, max_result_rows=1000,
        preview_rows=50, model_run_limit=8, data_dir=tmp,
    )
    return AgentRuntime(s, "t1")


def test_complete_extracts_plain_string():
    rt = _runtime()
    rt._llm = types.SimpleNamespace(invoke=lambda p: types.SimpleNamespace(content="SELECT 1"))
    assert rt._complete("prompt") == "SELECT 1"
    rt.close()


def test_complete_joins_content_blocks():
    rt = _runtime()
    rt._llm = types.SimpleNamespace(
        invoke=lambda p: types.SimpleNamespace(content=[{"text": "SELECT "}, {"text": "1"}])
    )
    assert rt._complete("prompt") == "SELECT 1"
    rt.close()


def test_schema_is_loaded_for_grounding():
    rt = _runtime()
    assert "orders" in rt.schema and "sale_price" in rt.schema
    rt.close()
