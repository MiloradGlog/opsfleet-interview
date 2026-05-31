"""End-to-end HITL gate through create_agent + the real ordered middleware stack.

Uses a scripted (offline) chat model that drives the agent to call delete_reports,
then asserts the interrupt/resume contract: approve deletes + audits; reject does
neither. Validates the real middleware wiring (ToolRetry + ModelCallLimit + HITL
ordering from build_middleware), not a stand-in graph.
"""
import json

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from retail_agent.agent import build_middleware
from retail_agent.config import get_settings
from retail_agent.prompts import build_system_prompt
from retail_agent.runtime import AgentRuntime
from retail_agent.tools import build_tools

from .fakes import FakePool


class ScriptedDeleteModel(BaseChatModel):
    """Calls delete_reports with the given ids on turn 1; a plain message after a tool ran."""

    ids: list = [1]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(getattr(m, "type", None) == "tool" for m in messages):
            msg = AIMessage(content="Okay, that's handled.")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[{
                    "name": "delete_reports",
                    "args": {
                        "report_ids": self.ids,
                        "confirmation_token": f"CONFIRM-DELETE-{len(self.ids)}",
                    },
                    "id": "call_1",
                }],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _count_audit(pool) -> int:
    with pool.connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])


@pytest.fixture
def env():
    settings = get_settings(user_id="manager_a")
    pool = FakePool()
    rt = AgentRuntime(settings, "t1", pool=pool)
    rt.storage.save_report("manager_a", "Acme", "client acme")
    model = ScriptedDeleteModel()
    agent = create_agent(
        model=model,
        tools=build_tools(rt),
        system_prompt=build_system_prompt(),
        middleware=build_middleware(settings),
        checkpointer=InMemorySaver(),
    )
    return agent, rt, pool


def _config():
    return {"configurable": {"thread_id": "t1"}}


def test_delete_pauses_for_confirmation(env):
    agent, rt, pool = env
    agent.invoke({"messages": [{"role": "user", "content": "delete acme"}]}, config=_config())
    snap = agent.get_state(_config())
    assert snap.interrupts, "delete_reports must trigger a human interrupt"
    # report still present while paused; no audit yet
    assert len(rt.storage.list_reports("manager_a")) == 1
    assert _count_audit(pool) == 0


def test_approve_executes_delete_and_audits(env):
    agent, rt, pool = env
    agent.invoke({"messages": [{"role": "user", "content": "delete acme"}]}, config=_config())
    agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=_config())
    assert rt.storage.list_reports("manager_a") == []
    assert _count_audit(pool) == 1


def test_reject_keeps_report_and_writes_no_audit(env):
    agent, rt, pool = env
    agent.invoke({"messages": [{"role": "user", "content": "delete acme"}]}, config=_config())
    agent.invoke(Command(resume={"decisions": [{"type": "reject"}]}), config=_config())
    assert len(rt.storage.list_reports("manager_a")) == 1
    assert _count_audit(pool) == 0


def test_middleware_order_budget_outermost():
    """ModelCallLimit must be registered first (outermost) so it short-circuits
    before token spend; HITL last."""
    settings = get_settings()
    names = [type(m).__name__ for m in build_middleware(settings)]
    assert names[0] == "ModelCallLimitMiddleware"
    assert names[-1] == "HumanInTheLoopMiddleware"
    assert "ToolRetryMiddleware" in names
