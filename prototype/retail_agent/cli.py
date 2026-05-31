"""Command-line chat interface — a polished interactive REPL + one-shot mode.

Drives the agent with the LangChain V1 interrupt/resume contract: ``invoke`` then,
while a pending interrupt exists, resume with ``Command(resume={"decisions": [...]})``.
The destructive delete flow pauses; the CLI renders the preview from the interrupt
payload, reads the ``CONFIRM-DELETE-N`` token, and maps it to approve/reject.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

from .config import get_settings
from .runtime import extract_text

BANNER = r"""
  ____      _        _ _      _                    _
 |  _ \ ___| |_ __ _(_) |    / \   __ _  ___ _ __ | |_
 | |_) / _ \ __/ _` | | |   / _ \ / _` |/ _ \ '_ \| __|
 |  _ <  __/ || (_| | | |  / ___ \ (_| |  __/ | | | |_
 |_| \_\___|\__\__,_|_|_| /_/   \_\__, |\___|_| |_|\__|
                                  |___/
Retail Data Assistant — ask about sales, products, customers, revenue.

  • "What are the top 5 products by revenue?"
  • "Show monthly revenue for the last 12 months"
  • "What data can I ask about?"
Manage reports: "save that as 'Q2 review'", "list my reports",
  "delete my reports about products".
Commands: /help  /exit
"""


def _credential_banner(settings) -> str:
    def mark(ok: bool) -> str:
        return "configured" if ok else "MISSING"

    gemini_ok = bool(settings.google_api_key)
    bq_ok = bool(settings.google_app_creds and os.path.exists(settings.google_app_creds))
    return (
        "Credentials:\n"
        f"  Gemini API key (GOOGLE_API_KEY)         : {mark(gemini_ok)}\n"
        f"  BigQuery SA key (GOOGLE_APPLICATION_CREDENTIALS): {mark(bq_ok)} "
        f"({settings.google_app_creds or 'unset'})\n"
        f"  Postgres (DATABASE_URL)                 : {settings.database_url}\n"
        f"  Model: {settings.gemini_model} | Embeddings: {settings.embed_model} "
        f"| MAX_SQL_ATTEMPTS={settings.max_sql_attempts}\n"
    )


def _last_ai_text(messages: list) -> str:
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        mtype = getattr(msg, "type", None)
        if mtype == "ai" and content:
            text = extract_text(msg)
            if text.strip():
                return text
    return ""


def _pending_interrupt(agent, config):
    """Return the first pending interrupt for this thread, or None."""
    snap = agent.get_state(config)
    intr = getattr(snap, "interrupts", None)
    if intr:
        return intr[0]
    for task in getattr(snap, "tasks", []) or []:
        task_intr = getattr(task, "interrupts", None)
        if task_intr:
            return task_intr[0]
    return None


def _resolve_interrupt(interrupt) -> dict:
    """Render the deletion preview and ask the human to type the confirmation token.

    The CONFIRM-DELETE-N token is a UX tripwire; the interrupt/resume is the actual
    security boundary (HLD §9.1).
    """
    value = getattr(interrupt, "value", interrupt)
    actions = []
    if isinstance(value, dict):
        actions = value.get("action_requests") or value.get("action_request") or []
        if isinstance(actions, dict):
            actions = [actions]
    elif isinstance(value, list):
        actions = value
    ids: list = []
    expected_token = None
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        args = action.get("arguments", action.get("args", {})) or {}
        ids = args.get("report_ids", ids)
        expected_token = args.get("confirmation_token", expected_token)

    print("\n!  Confirmation required before deleting reports.")
    if expected_token:
        print(f"   This will permanently delete {len(ids)} report(s): {ids}")
        print(f"   To approve, type exactly:  {expected_token}")
        print("   To cancel, type 'reject' (or anything else).")
        answer = input("confirm> ").strip()
        if answer == expected_token:
            return {"type": "approve"}
    else:
        print(f"   {value}")
        answer = input("Approve? (yes / reject): ").strip()
        if answer.lower() in {"y", "yes", "approve"}:
            return {"type": "approve"}
    print("Cancelled — no reports were deleted.")
    return {"type": "reject"}


def run_turn(agent, config, user_text: str) -> str:
    from langgraph.types import Command

    agent.invoke({"messages": [{"role": "user", "content": user_text}]}, config=config)
    while True:
        interrupt = _pending_interrupt(agent, config)
        if interrupt is None:
            break
        decision = _resolve_interrupt(interrupt)
        agent.invoke(Command(resume={"decisions": [decision]}), config=config)

    snap = agent.get_state(config)
    return _last_ai_text(snap.values.get("messages", [])) or "(no response)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retail Data Analysis chat assistant (Prototype_2 / gamma)."
    )
    parser.add_argument("--user", default=None, help="User id for ownership scoping.")
    parser.add_argument(
        "--question", default=None, help="Ask one question and exit (non-interactive)."
    )
    args = parser.parse_args(argv)

    settings = get_settings(user_id=args.user)

    if not settings.google_api_key:
        print(
            "FATAL: GOOGLE_API_KEY is not set. Analytical questions and retrieval need a "
            "Google AI Studio key. Set it in .env.",
            file=sys.stderr,
        )
        return 2

    from .agent import build_agent

    thread_id = f"cli-{settings.user_id}-{uuid.uuid4().hex[:8]}"
    agent, runtime = build_agent(settings, thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    if args.question:
        print(run_turn(agent, config, args.question))
        return 0

    print(BANNER)
    print(_credential_banner(settings))
    print(f"(signed in as: {settings.user_id})\n")
    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text in {"/exit", "/quit"}:
            break
        if user_text == "/help":
            print(BANNER)
            continue
        try:
            print(f"\nagent> {run_turn(agent, config, user_text)}\n")
        except Exception as exc:  # noqa: BLE001 - never crash the REPL
            print(
                f"\nagent> Sorry, a temporary issue occurred handling that ({exc}).\n",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
