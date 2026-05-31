"""Postgres connection pool + schema bootstrap.

Single store (HLD §7): ``golden_assets`` (Trios + pgvector embeddings),
``saved_reports``, ``audit_log``, plus the LangGraph checkpointer tables (created
by the checkpointer itself). Shared by :mod:`storage` and :mod:`golden_bucket`.

The pool is created lazily so importing the package (and the offline test suite)
needs no live Postgres.
"""
from __future__ import annotations

import logging

log = logging.getLogger("retail_agent.db")

_POOL = None


def get_pool(database_url: str, embed_dim: int = 768):
    """Return a process-wide psycopg ConnectionPool, creating + bootstrapping once."""
    global _POOL
    if _POOL is None:
        from psycopg_pool import ConnectionPool

        log.info("Opening Postgres pool")
        _POOL = ConnectionPool(conninfo=database_url, min_size=1, max_size=5, open=True)
        bootstrap_schema(_POOL, embed_dim)
    return _POOL


def bootstrap_schema(pool, embed_dim: int = 768) -> None:
    """Create the pgvector extension and operational tables if absent (idempotent)."""
    ddl = f"""
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS golden_assets (
        id          TEXT PRIMARY KEY,
        question    TEXT NOT NULL,
        sql         TEXT NOT NULL,
        report      TEXT NOT NULL,
        tags        TEXT,
        status      TEXT NOT NULL DEFAULT 'active',
        embedding   vector({embed_dim})
    );

    CREATE TABLE IF NOT EXISTS saved_reports (
        id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id    TEXT NOT NULL,
        title      TEXT NOT NULL,
        body       TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        deleted_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        op_id      TEXT PRIMARY KEY,
        actor      TEXT NOT NULL,
        action     TEXT NOT NULL,
        target_ids TEXT NOT NULL,
        counts     TEXT NOT NULL,
        ts         TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    with pool.connection() as conn:
        conn.execute(ddl)
        # pgvector index for cosine top-k. ivfflat needs data to train; for a tiny
        # seed corpus a plain index is fine and exact scan is cheap, so we skip it.
        conn.commit()
    log.info("Postgres schema ready (embed_dim=%s)", embed_dim)


def close_pool() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.close()
        _POOL = None
