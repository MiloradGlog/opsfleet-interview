"""Command-line chat interface.

Drives the agent with the documented LangChain V1 interrupt/resume contract:
``stream``/``invoke`` with ``version="v2"`` and ``Command(resume={"decisions": [...]})``.
The destructive delete flow pauses; the CLI renders the preview from the interrupt
payload, reads the ``CONFIRM-DELETE-N`` token, and maps it to approve/reject.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

from .config import get_settings
from .logging_setup import setup_logging

BANNER = """\
Retail Data Assistant (prototype)
Ask about sales, products, customers, and revenue — e.g.
  • "What are the top 5 products by revenue?"
  • "Show monthly revenue for the last 12 months"
  • "What data can I ask about?"
Manage reports: "save that as 'Q2 review'", "list my reports",
  "delete my reports about products".
Commands: /help  /exit
"""


def _last_ai_text(messages: list) -> str:
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        mtype = getattr(msg, "type", None)
        if mtype == "ai" and content:
            if isinstance(content, list):
                content = "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                )
            if str(content).strip():
                return str(content)
    return ""


def _invoke(agent, payload, config):
    """Invoke with version='v2' when supported, falling back gracefully."""
    try:
        return agent.invoke(payload, config=config, version="v2")
    except TypeError:
        return agent.invoke(payload, config=config)


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
    """Render the deletion preview and ask the human for the confirmation token."""
    value = getattr(interrupt, "value", interrupt)
    actions = []
    if isinstance(value, dict):
        actions = value.get("action_requests") or value.get("action_request") or []
        if isinstance(actions, dict):
            actions = [actions]
    expected_token = None
    print("\n⚠️  Confirmation required before deleting reports:")
    for action in actions or []:
        args = action.get("arguments", action.get("args", {})) if isinstance(action, dict) else {}
        ids = args.get("report_ids", [])
        expected_token = args.get("confirmation_token")
        print(f"   • delete reports {ids}")
    if not actions:
        print(f"   {value}")

    prompt = "Type the confirmation token to approve (or 'reject' to cancel): "
    answer = input(prompt).strip()
    if expected_token and answer == expected_token:
        return {"type": "approve"}
    if answer.lower() in {"y", "yes", "approve"} and expected_token is None:
        return {"type": "approve"}
    print("Cancelled — no reports were deleted.")
    return {"type": "reject"}


def run_turn(agent, config, user_text: str) -> str:
    from langgraph.types import Command

    _invoke(agent, {"messages": [{"role": "user", "content": user_text}]}, config)
    while True:
        interrupt = _pending_interrupt(agent, config)
        if interrupt is None:
            break
        decision = _resolve_interrupt(interrupt)
        _invoke(agent, Command(resume={"decisions": [decision]}), config)

    snap = agent.get_state(config)
    return _last_ai_text(snap.values.get("messages", [])) or "(no response)"


def _preflight(settings) -> None:
    if not settings.google_api_key:
        print(
            "⚠️  GOOGLE_API_KEY is not set. Analytical questions and retrieval need a "
            "Google AI Studio key (https://aistudio.google.com/apikey).",
            file=sys.stderr,
        )
    if not settings.gcp_project and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print(
            "⚠️  No GOOGLE_CLOUD_PROJECT / ADC detected. BigQuery queries need a billable "
            "GCP project and `gcloud auth application-default login`.",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retail Data Analysis chat assistant (prototype).")
    parser.add_argument("--user", default=None, help="User id for ownership scoping (default: AGENT_USER_ID).")
    parser.add_argument("--question", default=None, help="Ask one question and exit (non-interactive).")
    args = parser.parse_args(argv)

    settings = get_settings(user_id=args.user)
    setup_logging(settings.data_dir)
    _preflight(settings)

    # Imported here so --help works without the heavy deps installed.
    from .agent import build_agent

    thread_id = f"cli-{settings.user_id}-{uuid.uuid4().hex[:8]}"
    agent, runtime = build_agent(settings, thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        if args.question:
            print(run_turn(agent, config, args.question))
            return 0

        print(BANNER)
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
                print(f"\nagent> Sorry, something went wrong handling that ({exc}).\n", file=sys.stderr)
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
