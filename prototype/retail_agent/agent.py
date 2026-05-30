"""Agent assembly: LangChain V1 ``create_agent`` + ordered middleware stack.

Middleware order is outermost-first (first wraps all):
  1. ModelCallLimit  — per-request model-call budget (cost backstop, FR-1.7.4)
  2. PII (email)     — redact emails in tool results and final output (R2)
  3. PII (phone)     — redact phone numbers via regex (R2)
  4. ModelRetry      — transient backoff on the agent's own model calls
  5. ToolRetry       — transient backoff on tools (e.g. query_data / BigQuery blip)
  6. HumanInTheLoop  — gate the destructive delete_reports tool

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

# Phone numbers aren't a built-in PII type; this regex matches common formats
# (optional country code, separators) while staying clear of plain integers and
# decimal money amounts that appear in analytics output.
PHONE_REGEX = r"\b(?:\+?\d{1,3}[ .\-]?)?\(?\d{3}\)?[ .\-]\d{3}[ .\-]\d{4}\b"


def build_agent(settings: Settings, thread_id: str):
    """Construct the agent and its runtime. Returns ``(agent, runtime)``."""
    from langchain.agents import create_agent
    from langchain.agents.middleware import (
        HumanInTheLoopMiddleware,
        ModelCallLimitMiddleware,
        ModelRetryMiddleware,
        PIIMiddleware,
        ToolRetryMiddleware,
    )
    from langgraph.checkpoint.sqlite import SqliteSaver

    runtime = AgentRuntime(settings, thread_id)
    tools = build_tools(runtime)

    conn = sqlite3.connect(str(settings.checkpoint_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    middleware = [
        ModelCallLimitMiddleware(run_limit=settings.model_run_limit),
        # PII guard (R2): redact emails/phones in tool results AND final output,
        # so raw customer contact data never reaches the model or the user even
        # if a generated query selects it.
        PIIMiddleware(
            "email", strategy="redact",
            apply_to_input=True, apply_to_tool_results=True, apply_to_output=True,
        ),
        PIIMiddleware(
            "phone", strategy="redact", detector=PHONE_REGEX,
            apply_to_input=True, apply_to_tool_results=True, apply_to_output=True,
        ),
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
