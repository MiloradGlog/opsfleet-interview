"""Agent assembly: LangChain V1 ``create_agent`` + ordered middleware stack.

Middleware order is outermost-first (first wraps all):
  1. ModelCallLimit  — per-request model-call budget (cost backstop, FR-1.7.4)
  2. ModelRetry      — transient backoff on the agent's own model calls
  3. ToolRetry       — transient backoff on tools (e.g. query_data / BigQuery blip)
  4. HumanInTheLoop  — gate the destructive delete_reports tool

The bounded SQL repair loop is NOT here — it lives inside the analysis subgraph
(see :mod:`subgraph`). Middleware enforces cross-cutting policy; the subgraph owns
the deterministic workflow.
"""
from __future__ import annotations

import logging
import sqlite3

from .config import Settings
from .prompts import SYSTEM_PROMPT
from .runtime import AgentRuntime
from .tools import build_tools

log = logging.getLogger("retail_agent.agent")


def build_agent(settings: Settings, thread_id: str):
    """Construct the agent and its runtime. Returns ``(agent, runtime)``."""
    from langchain.agents import create_agent
    from langchain.agents.middleware import (
        HumanInTheLoopMiddleware,
        ModelCallLimitMiddleware,
        ModelRetryMiddleware,
        ToolRetryMiddleware,
    )
    from langgraph.checkpoint.sqlite import SqliteSaver

    runtime = AgentRuntime(settings, thread_id)
    tools = build_tools(runtime)

    conn = sqlite3.connect(str(settings.checkpoint_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    middleware = [
        ModelCallLimitMiddleware(run_limit=settings.model_run_limit),
        ModelRetryMiddleware(max_retries=2),
        ToolRetryMiddleware(max_retries=2, on_failure="return_message"),
        HumanInTheLoopMiddleware(
            interrupt_on={"delete_reports": {"allowed_decisions": ["approve", "reject"]}},
            description_prefix="Report deletion pending your confirmation",
        ),
    ]

    agent = create_agent(
        model=runtime.llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        checkpointer=checkpointer,
    )
    log.info("Agent built (user=%s, thread=%s)", settings.user_id, thread_id)
    return agent, runtime
