"""PII masking (R2) via PIIMiddleware: redaction at output and tool-result
boundaries, phone regex behavior, and false-positive safety on analytics numbers."""
import re

from langchain.agents import create_agent
from langchain.agents.middleware import PIIMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from retail_agent.agent import PHONE_REGEX


def _result(message):
    return ChatResult(generations=[ChatGeneration(message=message)])


class EmitTextModel(BaseChatModel):
    def __init__(self, text):
        super().__init__()
        self._text = text

    @property
    def _llm_type(self):
        return "emit-text"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return _result(AIMessage(content=self._text))


@tool
def lookup_customer() -> str:
    """Return a customer's contact details."""
    return "Top customer: Jane Roe, email jane.roe@corp.com, phone 415-555-2671"


class CallToolThenFinish(BaseChatModel):
    @property
    def _llm_type(self):
        return "call-then-finish"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(getattr(m, "type", None) == "tool" for m in messages):
            return _result(AIMessage(content="Here are the results you asked for."))
        return _result(AIMessage(content="", tool_calls=[{"name": "lookup_customer", "args": {}, "id": "c1"}]))


def _cfg(tid):
    return {"configurable": {"thread_id": tid}}


def test_email_redacted_in_model_output():
    agent = create_agent(
        model=EmitTextModel("You can reach them at john.doe@example.com."),
        tools=[],
        middleware=[PIIMiddleware("email", strategy="redact", apply_to_output=True)],
        checkpointer=InMemorySaver(),
    )
    agent.invoke({"messages": [{"role": "user", "content": "contact?"}]}, config=_cfg("e1"))
    out = str(agent.get_state(_cfg("e1")).values["messages"][-1].content)
    assert "john.doe@example.com" not in out
    assert "REDACTED" in out.upper()


def test_phone_redacted_in_model_output():
    agent = create_agent(
        model=EmitTextModel("Call the store at 415-555-2671 today."),
        tools=[],
        middleware=[PIIMiddleware("phone", strategy="redact", detector=PHONE_REGEX, apply_to_output=True)],
        checkpointer=InMemorySaver(),
    )
    agent.invoke({"messages": [{"role": "user", "content": "phone?"}]}, config=_cfg("p1"))
    out = str(agent.get_state(_cfg("p1")).values["messages"][-1].content)
    assert "415-555-2671" not in out
    assert "REDACTED" in out.upper()


def test_email_redacted_in_tool_result_before_reaching_user():
    agent = create_agent(
        model=CallToolThenFinish(),
        tools=[lookup_customer],
        middleware=[PIIMiddleware("email", strategy="redact", apply_to_tool_results=True)],
        checkpointer=InMemorySaver(),
    )
    agent.invoke({"messages": [{"role": "user", "content": "top customer"}]}, config=_cfg("t1"))
    msgs = agent.get_state(_cfg("t1")).values["messages"]
    tool_text = " ".join(str(m.content) for m in msgs if getattr(m, "type", None) == "tool")
    assert tool_text  # the tool ran
    assert "jane.roe@corp.com" not in tool_text
    assert "REDACTED" in tool_text.upper()


def test_phone_regex_does_not_match_analytics_numbers():
    # Guard against redacting money, counts, or ids that look numeric.
    for s in ["$12,225.00", "33853 customers", "Revenue 945749.42", "2477 units sold", "order #1834291"]:
        assert re.search(PHONE_REGEX, s) is None, f"false positive on {s!r}"


def test_phone_regex_matches_real_phone_formats():
    for s in ["415-555-2671", "(415) 555-2671", "+1 415-555-2671", "415.555.2671"]:
        assert re.search(PHONE_REGEX, s) is not None, f"missed {s!r}"
