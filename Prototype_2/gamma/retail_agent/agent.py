"""Agent assembly: LangChain V1 ``create_agent`` + ordered middleware stack.

Middleware order is outermost-first (first wraps all):
  1. ModelCallLimit  — per-request model-call budget (registered FIRST so it
     short-circuits before any token spend).
  2. ToolRetry       — exponential backoff for transient BQ/Gemini errors (R5).
  3. HumanInTheLoop  — gate the destructive delete_reports tool; approve/reject only,
     NO edit (HLD §9.1). Needs the checkpointer for durable interrupts.

This prototype showcases exactly the two required capabilities — High-Stakes
Oversight (R3) and Resilience (R5). It does not redact PII; instead the SQL
generation prompt simply does not select customer contact columns.

The bounded SQL repair loop is NOT here — it lives inside the analysis subgraph
(see :mod:`subgraph`). Middleware enforces cross-cutting policy; the subgraph owns
the deterministic workflow.
"""
from __future__ import annotations

import logging

from .config import Settings
from .prompts import build_system_prompt
from .runtime import AgentRuntime
from .tools import build_tools

log = logging.getLogger("retail_agent.agent")


def build_checkpointer(database_url: str):
    """Open a durable Postgres checkpointer (HITL interrupts survive a restart).

    We hold an explicit long-lived autocommit connection (the checkpointer requires
    autocommit) rather than relying on ``from_conn_string``'s short-lived context
    manager, so the connection stays open for the process lifetime.
    """
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    conn = psycopg.connect(database_url, autocommit=True)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver, conn


def build_middleware(settings: Settings):
    """Construct the ordered middleware list (outermost first)."""
    from langchain.agents.middleware import (
        HumanInTheLoopMiddleware,
        ModelCallLimitMiddleware,
        ToolRetryMiddleware,
    )

    return [
        ModelCallLimitMiddleware(run_limit=settings.model_run_limit, exit_behavior="end"),
        ToolRetryMiddleware(max_retries=2, on_failure="continue"),
        HumanInTheLoopMiddleware(
            interrupt_on={
                "delete_reports": {"allowed_decisions": ["approve", "reject"]}
            },
            description_prefix="Report deletion pending your confirmation",
        ),
    ]


def build_agent(settings: Settings, thread_id: str, checkpointer=None):
    """Construct the agent and its runtime. Returns ``(agent, runtime)``.

    If ``checkpointer`` is None a durable Postgres checkpointer is opened.
    """
    from langchain.agents import create_agent

    runtime = AgentRuntime(settings, thread_id)
    tools = build_tools(runtime)

    if checkpointer is None:
        checkpointer, _ = build_checkpointer(settings.database_url)

    agent = create_agent(
        model=runtime.llm,
        tools=tools,
        system_prompt=build_system_prompt(),
        middleware=build_middleware(settings),
        checkpointer=checkpointer,
    )
    log.info("Agent built (user=%s, thread=%s)", settings.user_id, thread_id)
    return agent, runtime
