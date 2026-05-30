"""Configuration resolution."""
from retail_agent.config import ALLOWED_TABLES, DATASET_ID, Settings, get_settings

_ENV_KEYS = [
    "GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT", "GEMINI_MODEL", "EMBED_MODEL",
    "AGENT_USER_ID", "MAX_SQL_ATTEMPTS", "MAX_RESULT_ROWS", "PREVIEW_ROWS",
    "MODEL_RUN_LIMIT", "HMAC_SECRET",
]


def _clear(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_dataset_constants():
    assert DATASET_ID == "bigquery-public-data.thelook_ecommerce"
    assert set(ALLOWED_TABLES) == {"orders", "order_items", "products", "users"}


def test_defaults(monkeypatch):
    _clear(monkeypatch)
    s = get_settings()
    assert s.gemini_model == "gemini-3.5-flash"
    assert s.embed_model == "gemini-embedding-001"
    assert s.user_id == "manager_a"
    assert (s.max_sql_attempts, s.max_result_rows, s.preview_rows) == (3, 1000, 50)
    assert s.google_api_key is None and s.gcp_project is None


def test_cli_user_overrides_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_USER_ID", "from_env")
    assert get_settings().user_id == "from_env"
    assert get_settings(user_id="from_cli").user_id == "from_cli"


def test_env_int_parsing_and_invalid_fallback(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("MAX_SQL_ATTEMPTS", "5")
    monkeypatch.setenv("MAX_RESULT_ROWS", "not-an-int")
    s = get_settings()
    assert s.max_sql_attempts == 5      # parsed
    assert s.max_result_rows == 1000    # invalid -> default


def test_derived_paths(tmp_path):
    s = Settings(
        google_api_key=None, gcp_project=None, gemini_model="m", embed_model="e",
        user_id="u", hmac_secret="x", max_sql_attempts=3, max_result_rows=1000,
        preview_rows=50, model_run_limit=8, data_dir=tmp_path,
    )
    assert s.sqlite_path == tmp_path / "retail_agent.sqlite"
    assert s.checkpoint_path == tmp_path / "checkpoints.sqlite"
    assert s.embeddings_cache_path == tmp_path / "embeddings_cache.json"
    assert s.trios_path == tmp_path / "golden_trios.json"
