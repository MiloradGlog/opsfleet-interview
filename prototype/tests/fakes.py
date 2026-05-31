"""Provider-boundary fakes for the offline suite — zero network, zero credentials.

* :class:`FakePool` — a SQLite-backed stand-in for the psycopg ConnectionPool used
  by :mod:`retail_agent.storage`. It implements the small subset of the psycopg
  surface Storage touches (``connection()`` context manager, ``execute`` returning a
  cursor with ``fetchone``/``fetchall``/``rowcount``/``commit``) and rewrites the
  few Postgres-isms Storage emits (``%s`` -> ``?``, ``ANY(%s)`` -> ``IN (...)``,
  ``now()`` -> CURRENT_TIMESTAMP, ``RETURNING id``, ``ON CONFLICT DO NOTHING``).
  This lets the High-Stakes-Oversight invariants (scoping, idempotency, drift) be
  tested exactly, with no live database.

* :class:`FakeChat` — a scripted chat model returning queued SQL/text, mimicking the
  langchain_google_genai content-block shape.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager


# --- Storage fake -----------------------------------------------------------
class _FakeCursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._c = cursor

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    @property
    def rowcount(self):
        return self._c.rowcount


class _FakeConn:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, sql: str, params=()):
        sql, params = _translate(sql, params)
        return _FakeCursor(self._conn.execute(sql, params))

    def commit(self):
        self._conn.commit()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    op_id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_ids TEXT NOT NULL,
    counts TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _translate(sql: str, params):
    """Rewrite the Postgres SQL Storage emits into SQLite-compatible SQL."""
    params = list(params)
    # ANY(%s) with a python list param -> IN (?,?,...) expanding that one param.
    if "= ANY(%s)" in sql:
        # find positional index of the ANY param among %s placeholders
        before = sql.split("= ANY(%s)")[0]
        idx = before.count("%s")
        lst = params[idx]
        placeholders = ",".join("?" for _ in lst)
        sql = sql.replace("= ANY(%s)", f"IN ({placeholders})", 1)
        params = params[:idx] + list(lst) + params[idx + 1:]
    sql = sql.replace("now()", "CURRENT_TIMESTAMP")
    if "ON CONFLICT (op_id) DO NOTHING" in sql:
        sql = sql.replace("ON CONFLICT (op_id) DO NOTHING", "")
        sql = sql.replace("INSERT INTO audit_log", "INSERT OR IGNORE INTO audit_log", 1)
    sql = sql.replace("RETURNING id", "")
    sql = sql.replace("%s", "?")
    return sql, tuple(params)


class FakePool:
    """SQLite-backed stand-in for psycopg ConnectionPool."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._patch_returning()

    def _patch_returning(self):
        # SQLite's INSERT ... RETURNING is supported in modern sqlite3; if not,
        # storage.save_report falls back to lastrowid. We handle save_report
        # specially in the connection wrapper below.
        pass

    @contextmanager
    def connection(self):
        yield _ReturningConn(self._conn)

    def close(self):
        self._conn.close()


class _ReturningConn(_FakeConn):
    """Adds RETURNING-id emulation for the save_report INSERT."""

    def execute(self, sql: str, params=()):
        if sql.strip().startswith("INSERT INTO saved_reports") and "RETURNING id" in sql:
            tsql, tparams = _translate(sql, params)
            cur = self._conn.execute(tsql, tparams)
            rid = cur.lastrowid
            return _ScalarCursor(rid)
        return super().execute(sql, params)


class _ScalarCursor:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return (self._value,)

    @property
    def rowcount(self):
        return 1


# --- Chat model fake --------------------------------------------------------
class _Resp:
    def __init__(self, text, as_blocks=False):
        self.content = [{"type": "text", "text": text}] if as_blocks else text


class FakeChat:
    """Returns queued responses in order; mimics content-block shape by default."""

    def __init__(self, scripted: list[str], as_blocks=True):
        self._scripted = list(scripted)
        self._as_blocks = as_blocks
        self.calls: list[str] = []

    def invoke(self, prompt, *args, **kwargs):
        self.calls.append(prompt if isinstance(prompt, str) else str(prompt))
        text = self._scripted.pop(0) if self._scripted else ""
        return _Resp(text, as_blocks=self._as_blocks)
