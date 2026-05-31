"""Idempotent first-boot seed: embed ``trios.json`` into ``golden_assets`` (pgvector).

Run as ``python -m retail_agent.seed``. Uses REAL Gemini embeddings via the runtime
embedder. Safe to re-run (ON CONFLICT upsert).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import get_settings
from .db import get_pool
from .golden_bucket import load_trios, seed_golden_assets
from .runtime import AgentRuntime

log = logging.getLogger("retail_agent.seed")

TRIOS_PATH = Path(__file__).resolve().parent.parent / "trios.json"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if not settings.google_api_key:
        print(
            "GOOGLE_API_KEY is not set — cannot compute Trio embeddings. "
            "Set it in .env and retry.",
            file=sys.stderr,
        )
        return 1

    pool = get_pool(settings.database_url, settings.embed_dim)
    trios = load_trios(TRIOS_PATH)

    # Skip if already seeded with the same count (cheap idempotency check before
    # spending embedding calls). Upsert still runs if counts differ.
    with pool.connection() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM golden_assets").fetchone()[0]
    if existing == len(trios):
        print(f"golden_assets already seeded ({existing} Trios); skipping re-embed.")
        return 0

    runtime = AgentRuntime(settings, thread_id="seed")
    n = seed_golden_assets(pool, trios, runtime.embed_fn)
    print(f"Seeded {n} Trios into golden_assets (embedded with {settings.embed_model}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
