"""The "Golden Bucket" — hybrid intelligence (brief R1) over **pgvector**.

Analyst-curated Trios (Question -> SQL -> Report) are embedded once into the
``golden_assets`` table and retrieved by cosine similarity (pgvector ``<=>``) to
steer SQL generation with few-shot examples. The embedder is injected so the unit
tests can run offline with a deterministic fake.

* :func:`seed_golden_assets` — idempotent first-boot embed + upsert of trios.json.
* :class:`GoldenBucket.retrieve` — top-k over the live pgvector index.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("retail_agent.golden_bucket")

# An embedder turns a list of texts into a list of float vectors.
EmbedFn = Callable[[list[str]], list[list[float]]]


def load_trios(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text())


def _vec_literal(vec: list[float]) -> str:
    """Render a python float list as a pgvector literal string."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def seed_golden_assets(pool, trios: list[dict], embed_fn: EmbedFn) -> int:
    """Embed Trio questions and upsert into ``golden_assets`` (idempotent).

    Re-embeds and updates on conflict so editing a Trio's text refreshes it.
    Returns the number of rows written.
    """
    if not trios:
        return 0
    questions = [t["question"] for t in trios]
    vectors = embed_fn(questions)
    with pool.connection() as conn:
        for t, vec in zip(trios, vectors):
            conn.execute(
                """
                INSERT INTO golden_assets (id, question, sql, report, tags, status, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    question = EXCLUDED.question,
                    sql       = EXCLUDED.sql,
                    report    = EXCLUDED.report,
                    tags      = EXCLUDED.tags,
                    status    = EXCLUDED.status,
                    embedding = EXCLUDED.embedding
                """,
                (
                    t["id"],
                    t["question"],
                    t["sql"],
                    t.get("report", ""),
                    ",".join(t.get("tags", [])) if t.get("tags") else None,
                    t.get("status", "active"),
                    _vec_literal(vec),
                ),
            )
        conn.commit()
    log.info("Seeded %d golden_assets", len(trios))
    return len(trios)


class GoldenBucket:
    """pgvector-backed top-k retrieval over ``golden_assets``."""

    def __init__(self, pool, embed_fn: EmbedFn) -> None:
        self._pool = pool
        self._embed_fn = embed_fn

    def retrieve(self, question: str, k: int = 3) -> list[dict]:
        """Return the top-``k`` most similar active Trios to ``question``."""
        q_vec = self._embed_fn([question])[0]
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, question, sql, report
                FROM golden_assets
                WHERE status = 'active'
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (_vec_literal(q_vec), k),
            ).fetchall()
        return [
            {"id": r[0], "question": r[1], "sql": r[2], "report": r[3]}
            for r in rows
        ]
