"""Agent assembly: create_agent + middleware compile into the expected graph
(offline — uses a dummy key; no network call is made at build time)."""
import pathlib
import tempfile

from retail_agent.agent import build_agent
from retail_agent.config import Settings


def _settings(tmp):
    return Settings(
        google_api_key="dummy-key", gcp_project=None, gemini_model="gemini-3.5-flash",
        embed_model="gemini-embedding-001", user_id="manager_a", hmac_secret="x",
        max_sql_attempts=3, max_result_rows=1000, preview_rows=50, model_run_limit=8,
        data_dir=tmp,
    )


def test_build_agent_compiles_expected_graph(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key")
    tmp = pathlib.Path(tempfile.mkdtemp())
    agent, rt = build_agent(_settings(tmp), "t-build")
    try:
        nodes = set(agent.get_graph().nodes.keys())
        assert "model" in nodes and "tools" in nodes
        assert any("HumanInTheLoopMiddleware" in n for n in nodes)
        assert any("ModelCallLimitMiddleware" in n for n in nodes)
    finally:
        rt.close()
