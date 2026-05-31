"""Smaller units: schema catalog (no SQL), BQ error classifier, config defaults,
tool result formatting, Gemini content-block extraction."""
import pandas as pd

from retail_agent.bigquery_client import is_transient_error
from retail_agent.config import get_settings
from retail_agent.runtime import extract_text
from retail_agent.schema_catalog import describe_schema, schema_for_prompt
from retail_agent.tools import _format_analysis


def test_describe_schema_runs_without_sql_and_flags_pii():
    out = describe_schema("users")
    assert "email" in out
    assert "sensitive personal data" in out
    # no query is executed; pure string from the static catalog
    assert "SELECT" not in out.upper()


def test_schema_for_prompt_lists_all_tables():
    s = schema_for_prompt()
    for t in ("orders", "order_items", "products", "users"):
        assert t in s


def test_config_defaults_match_spec():
    s = get_settings()
    assert s.max_sql_attempts == 2  # spec §11: one repair
    assert s.gemini_model == "gemini-3.5-flash"
    assert s.embed_model == "gemini-embedding-001"


def test_transient_classifier():
    from google.api_core import exceptions as gexc

    assert is_transient_error(gexc.ServiceUnavailable("503")) is True
    assert is_transient_error(gexc.TooManyRequests("429")) is True
    assert is_transient_error(gexc.BadRequest("400")) is False   # semantic -> repair
    assert is_transient_error(gexc.NotFound("404")) is False
    assert is_transient_error(ValueError("?")) is False          # unknown -> semantic


def test_extract_text_handles_blocks_and_str():
    class R:
        content = [{"type": "text", "text": "hello"}]

    assert extract_text(R()) == "hello"

    class S:
        content = "world"

    assert extract_text(S()) == "world"


def test_format_analysis_renders_table_and_failure():
    ok = _format_analysis({
        "status": "ok", "rows": [{"a": 1}], "columns": ["a"], "row_count": 1, "trio_ids": ["t1"],
        "sql": "SELECT a FROM orders LIMIT 1",
    })
    assert "| a |" in ok
    failed = _format_analysis({"status": "failed", "message": "nope"})
    assert failed == "nope"


def test_pandas_dataframe_dict_records_shape():
    # guards the rows/columns contract used by execute_bq
    df = pd.DataFrame([{"x": 1, "y": 2}])
    assert df.to_dict("records") == [{"x": 1, "y": 2}]
