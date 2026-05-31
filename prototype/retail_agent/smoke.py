"""Live no-BQ smoke check: ``python -m retail_agent.smoke``.

Exercises everything that does NOT need a BigQuery SELECT (which is gated by a
pending IAM grant): real Gemini embeddings, pgvector retrieval, storage, and the
full HITL delete interrupt/resume through create_agent + the Postgres checkpointer.
"""
from __future__ import annotations

from langgraph.types import Command

from .agent import build_agent
from .config import get_settings
from .schema_catalog import describe_schema


def main() -> int:
    s = get_settings(user_id="smoke_user")
    agent, rt = build_agent(s, "smoke-thread")
    cfg = {"configurable": {"thread_id": "smoke-thread"}}

    print("== pgvector retrieval (REAL Gemini embeddings) ==")
    for h in rt.golden.retrieve("which products earn the most money?", k=3):
        print(f"  - {h['id']}: {h['question']}")

    print("\n== describe_schema (no SQL) ==")
    print("  " + describe_schema("products").splitlines()[2])

    print("\n== save_report / list_reports ==")
    rid = rt.storage.save_report("smoke_user", "Acme Q2", "report on client Acme")
    print(f"  saved #{rid}; live: {len(rt.storage.list_reports('smoke_user'))}")

    print("\n== HITL delete interrupt -> resume approve ==")
    agent.invoke(
        {"messages": [{"role": "user", "content": "delete my report about Acme"}]}, config=cfg
    )
    snap = agent.get_state(cfg)
    intr = snap.interrupts or (snap.tasks[0].interrupts if snap.tasks else None)
    print(f"  interrupt raised: {bool(intr)} (live during pause: "
          f"{len(rt.storage.list_reports('smoke_user'))})")
    agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=cfg)
    print(f"  after approve: live={len(rt.storage.list_reports('smoke_user'))}")
    with rt.pool.connection() as c:
        print(f"  audit rows: {c.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]}")

    print("\nSMOKE-OK (live BigQuery SELECT intentionally not run — pending IAM grant)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
