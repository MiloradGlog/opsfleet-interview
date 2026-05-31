"""Central configuration: environment loading + tunable constants.

Everything the rest of the package needs to know about the environment is
resolved here once, into an immutable ``Settings`` object. The spec's tunables
(``MAX_SQL_ATTEMPTS``, etc.) and the Postgres connection string live here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# --- Fixed facts about the mandated dataset (brief Dataset Specification) ---
DATASET_ID = "bigquery-public-data.thelook_ecommerce"
ALLOWED_TABLES = ("orders", "order_items", "products", "users")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration. Immutable for the life of the process."""

    google_api_key: str | None
    gcp_project: str | None
    google_app_creds: str | None
    gemini_model: str
    embed_model: str
    embed_dim: int
    database_url: str
    user_id: str
    hmac_secret: str
    max_sql_attempts: int          # total SQL generations incl. the first
    max_result_rows: int
    preview_rows: int              # rows handed to the LLM for narration (token control)
    model_run_limit: int           # ModelCallLimitMiddleware run_limit
    top_k: int


def get_settings(user_id: str | None = None) -> Settings:
    """Build a ``Settings`` from the environment.

    ``user_id`` (from the CLI ``--user`` flag) overrides ``AGENT_USER_ID``.
    """
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        google_app_creds=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        embed_model=os.getenv("EMBED_MODEL", "gemini-embedding-001"),
        embed_dim=_env_int("EMBED_DIM", 768),
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://retail:retail@localhost:5435/retail"
        ),
        user_id=user_id or os.getenv("AGENT_USER_ID", "manager_a"),
        hmac_secret=os.getenv("HMAC_SECRET", "dev-secret-change-me"),
        max_sql_attempts=_env_int("MAX_SQL_ATTEMPTS", 2),
        max_result_rows=_env_int("MAX_RESULT_ROWS", 1000),
        preview_rows=_env_int("PREVIEW_ROWS", 50),
        model_run_limit=_env_int("MODEL_RUN_LIMIT", 12),
        top_k=_env_int("RETRIEVAL_TOP_K", 3),
    )
