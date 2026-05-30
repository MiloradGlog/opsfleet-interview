"""End-to-end HITL gate through create_agent + HumanInTheLoopMiddleware.

Uses a scripted (offline) chat model that drives the agent to call delete_reports,
then asserts the interrupt/resume contract: approve deletes + audits; reject does
neither. Validates the real middleware wiring, not a stand-in graph.
"""
import pathlib
import tempfile

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from retail_agent.config import Settings
from retail_agent.runtime import AgentRuntime
from retail_agent.tools import build_tools


class ScriptedChatModel(BaseChatModel):
    """Calls delete_reports on the first turn; a plain message once a tool ran."""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        has_tool_result = any(getattr(m, "type", None) == "tool" for m in messages)
        if has_tool_result:
            msg = AIMessage(content="Okay, that's handled.")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[{
                    "name": "delete_reports",
                    "args": {"report_ids": [1], "confirmation_token": "CONFIRM-DELETE-1"},
                    "id": "call_1",
                }],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


@pytest.fixture
def env():
    tmp = pathlib.Path(tempfile.mkdtemp())
    settings = Settings(
        google_api_key=None, gcp_project=None, gemini_model="m", embed_model="e",
        user_id="manager_a", hmac_secret="x", max_sql_attempts=3, max_result_rows=1000,
        preview_rows=50, model_run_limit=8, data_dir=tmp,
    )
    rt = AgentRuntime(settings, "t1")
    rt.storage.save_report("manager_a", "Acme", "client acme")
    agent = create_agent(
        model=ScriptedChatModel(),
        tools=build_tools(rt),
        middleware=[HumanInTheLoopMiddleware(
            interrupt_on={"delete_reports": {"allowed_decisions": ["approve", "reject"]}}
        )],
        checkpointer=InMemorySaver(),
    )
    yield agent, rt
    rt.close()


def _config():
    return {"configurable": {"thread_id": "t1"}}


def test_delete_pauses_for_confirmation(env):
    agent, rt = env
    agent.invoke({"messages": [{"role": "user", "content": "delete acme"}]}, config=_config())
    snap = agent.get_state(_config())
    assert snap.interrupts, "delete_reports must trigger a human interrupt"
    action = snap.interrupts[0].value["action_requests"][0]
    assert action["name"] == "delete_reports"
    # report still present while paused
    assert len(rt.storage.list_reports("manager_a")) == 1


def test_approve_executes_delete_and_audits(env):
    agent, rt = env
    agent.invoke({"messages": [{"role": "user", "content": "delete acme"}]}, config=_config())
    agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=_config())
    assert rt.storage.list_reports("manager_a") == []
    n = rt.storage.conn.execute("SELECT COUNT(*) n FROM audit_log").fetchone()["n"]
    assert n == 1


def test_reject_keeps_report_and_writes_no_audit(env):
    agent, rt = env
    agent.invoke({"messages": [{"role": "user", "content": "delete acme"}]}, config=_config())
    agent.invoke(Command(resume={"decisions": [{"type": "reject"}]}), config=_config())
    assert len(rt.storage.list_reports("manager_a")) == 1
    n = rt.storage.conn.execute("SELECT COUNT(*) n FROM audit_log").fetchone()["n"]
    assert n == 0
