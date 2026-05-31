"""Postgres operational store: saved reports + audit log.

Holds the High-Stakes-Oversight invariants in one place (HLD §9.1):
* ownership scoping is enforced in SQL (``AND user_id = %s``), never by the LLM;
* deletion is a **soft-delete** (``deleted_at``) on a captured id set, so it is
  drift-safe across the human-confirmation pause;
* the audit entry is keyed by an HMAC ``op_id`` with ``ON CONFLICT DO NOTHING`` so
  a double-resume cannot duplicate it (idempotency).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Iterable


class Storage:
    """Thin synchronous wrapper over the shared Postgres pool."""

    def __init__(self, pool, hmac_secret: str = "dev-secret-change-me") -> None:
        self.pool = pool
        self.hmac_secret = hmac_secret.encode()

    # --- saved reports -------------------------------------------------------
    def save_report(self, user_id: str, title: str, body: str) -> int:
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO saved_reports (user_id, title, body) VALUES (%s, %s, %s) "
                "RETURNING id",
                (user_id, title, body),
            ).fetchone()
            conn.commit()
        return int(row[0])

    def list_reports(self, user_id: str) -> list[dict]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at FROM saved_reports "
                "WHERE user_id = %s AND deleted_at IS NULL ORDER BY id",
                (user_id,),
            ).fetchall()
        return [{"id": int(r[0]), "title": r[1], "created_at": r[2]} for r in rows]

    def preview_deletable(self, user_id: str, criteria: str) -> dict:
        """Return the live, user-owned reports matching ``criteria`` (case-insensitive
        substring over title + body). Read-only — this is the previewed id set."""
        like = f"%{(criteria or '').strip().lower()}%"
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, title FROM saved_reports "
                "WHERE user_id = %s AND deleted_at IS NULL "
                "AND (LOWER(title) LIKE %s OR LOWER(body) LIKE %s) ORDER BY id",
                (user_id, like, like),
            ).fetchall()
        ids = [int(r[0]) for r in rows]
        return {"count": len(ids), "ids": ids, "titles": [r[1] for r in rows]}

    def soft_delete(self, user_id: str, ids: Iterable[int]) -> dict:
        """Idempotently soft-delete the captured ids, scoped to the owner.

        Ownership is enforced here in SQL (``AND user_id = %s``) — never trusted
        from an LLM argument. Returns counts: requested / actually deleted now /
        already-gone (drift during the confirmation pause)."""
        ids = [int(i) for i in ids]
        if not ids:
            return {"requested": 0, "deleted": 0, "already_gone": 0}
        with self.pool.connection() as conn:
            live_before = conn.execute(
                "SELECT COUNT(*) FROM saved_reports "
                "WHERE id = ANY(%s) AND user_id = %s AND deleted_at IS NULL",
                (ids, user_id),
            ).fetchone()[0]
            cur = conn.execute(
                "UPDATE saved_reports SET deleted_at = now() "
                "WHERE id = ANY(%s) AND user_id = %s AND deleted_at IS NULL",
                (ids, user_id),
            )
            deleted = cur.rowcount
            conn.commit()
        return {
            "requested": len(ids),
            "deleted": deleted,
            "already_gone": len(ids) - int(live_before),
        }

    # --- audit log -----------------------------------------------------------
    def op_id(self, user_id: str, thread_id: str, ids: Iterable[int]) -> str:
        msg = f"{user_id}:{thread_id}:{sorted(int(i) for i in ids)}".encode()
        return hmac.new(self.hmac_secret, msg, hashlib.sha256).hexdigest()

    def write_audit(
        self,
        op_id: str,
        actor: str,
        action: str,
        target_ids: Iterable[int],
        counts: dict,
    ) -> bool:
        """Append an audit row. Returns True if inserted, False if it already
        existed (idempotent — safe against double-resume)."""
        with self.pool.connection() as conn:
            cur = conn.execute(
                "INSERT INTO audit_log (op_id, actor, action, target_ids, counts) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (op_id) DO NOTHING",
                (
                    op_id,
                    actor,
                    action,
                    json.dumps(sorted(int(i) for i in target_ids)),
                    json.dumps(counts),
                ),
            )
            inserted = cur.rowcount > 0
            conn.commit()
        return inserted
