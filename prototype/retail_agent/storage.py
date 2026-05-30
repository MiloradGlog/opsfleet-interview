"""SQLite operational store: saved reports + audit log.

Holds the High-Stakes-Oversight invariants in one place:
* ownership scoping is enforced in SQL (``AND user_id = ?``), never by the LLM;
* deletion is a **soft-delete** (``deleted_at``) on a captured id set, so it is
  drift-safe across the human-confirmation pause;
* the audit entry is keyed by an HMAC ``op_id`` with ``INSERT OR IGNORE`` so a
  double-resume cannot duplicate it (idempotency).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    op_id      TEXT PRIMARY KEY,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    target_ids TEXT NOT NULL,
    counts     TEXT NOT NULL,
    ts         TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """Thin synchronous wrapper over a SQLite connection."""

    def __init__(self, path: str | Path, hmac_secret: str = "dev-secret-change-me") -> None:
        self.path = str(path)
        self.hmac_secret = hmac_secret.encode()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- saved reports -------------------------------------------------------
    def save_report(self, user_id: str, title: str, body: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO saved_reports (user_id, title, body, created_at) VALUES (?, ?, ?, ?)",
            (user_id, title, body, _now()),
        )
        self.conn.commit()
        rowid = cur.lastrowid
        if rowid is None:  # pragma: no cover - sqlite always sets this on INSERT
            raise RuntimeError("INSERT did not return a row id")
        return int(rowid)

    def list_reports(self, user_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, title, created_at FROM saved_reports "
            "WHERE user_id = ? AND deleted_at IS NULL ORDER BY id",
            (user_id,),
        ).fetchall()

    def preview_deletable(self, user_id: str, criteria: str) -> dict:
        """Return the live, user-owned reports matching ``criteria`` (case-insensitive
        substring over title + body). Read-only — this is the previewed id set."""
        like = f"%{(criteria or '').strip().lower()}%"
        rows = self.conn.execute(
            "SELECT id, title FROM saved_reports "
            "WHERE user_id = ? AND deleted_at IS NULL "
            "AND (LOWER(title) LIKE ? OR LOWER(body) LIKE ?) ORDER BY id",
            (user_id, like, like),
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        return {"count": len(ids), "ids": ids, "titles": [r["title"] for r in rows]}

    def soft_delete(self, user_id: str, ids: Iterable[int]) -> dict:
        """Idempotently soft-delete the captured ids, scoped to the owner.

        Returns counts: how many were requested, actually deleted now, and how
        many had already been deleted (drift during the confirmation pause).
        """
        ids = [int(i) for i in ids]
        if not ids:
            return {"requested": 0, "deleted": 0, "already_gone": 0}
        placeholders = ",".join("?" for _ in ids)
        # How many of the requested ids the user owns and are still live, pre-delete.
        live_before = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM saved_reports "
            f"WHERE id IN ({placeholders}) AND user_id = ? AND deleted_at IS NULL",
            (*ids, user_id),
        ).fetchone()["n"]
        cur = self.conn.execute(
            f"UPDATE saved_reports SET deleted_at = ? "
            f"WHERE id IN ({placeholders}) AND user_id = ? AND deleted_at IS NULL",
            (_now(), *ids, user_id),
        )
        self.conn.commit()
        deleted = cur.rowcount
        return {
            "requested": len(ids),
            "deleted": deleted,
            "already_gone": len(ids) - live_before,
        }

    # --- audit log -----------------------------------------------------------
    def op_id(self, user_id: str, thread_id: str, ids: Iterable[int]) -> str:
        msg = f"{user_id}:{thread_id}:{sorted(int(i) for i in ids)}".encode()
        return hmac.new(self.hmac_secret, msg, hashlib.sha256).hexdigest()

    def write_audit(self, op_id: str, actor: str, action: str, target_ids: Iterable[int], counts: dict) -> bool:
        """Append an audit row. Returns True if inserted, False if it already
        existed (idempotent — safe against double-resume)."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO audit_log (op_id, actor, action, target_ids, counts, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (op_id, actor, action, json.dumps(sorted(int(i) for i in target_ids)), json.dumps(counts), _now()),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self.conn.close()
