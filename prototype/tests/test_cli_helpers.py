"""CLI helpers: AI-text extraction, interrupt resolution, invoke fallback."""
import types

import builtins

from retail_agent import cli


def _msg(mtype, content):
    return types.SimpleNamespace(type=mtype, content=content)


def test_last_ai_text_picks_last_ai_message():
    msgs = [_msg("human", "hi"), _msg("ai", "first"), _msg("tool", "x"), _msg("ai", "final")]
    assert cli._last_ai_text(msgs) == "final"


def test_last_ai_text_handles_content_blocks():
    msgs = [_msg("ai", [{"text": "hello "}, {"text": "world"}])]
    assert cli._last_ai_text(msgs) == "hello world"


def test_last_ai_text_empty_when_no_ai():
    assert cli._last_ai_text([_msg("human", "hi")]) == ""


class _Interrupt:
    def __init__(self, value):
        self.value = value


def _delete_interrupt(token, ids=(1,)):
    return _Interrupt({
        "action_requests": [{
            "name": "delete_reports",
            "args": {"report_ids": list(ids), "confirmation_token": token},
        }],
        "review_configs": [{"action_name": "delete_reports", "allowed_decisions": ["approve", "reject"]}],
    })


def test_resolve_interrupt_approves_on_matching_token(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "CONFIRM-DELETE-2")
    decision = cli._resolve_interrupt(_delete_interrupt("CONFIRM-DELETE-2", ids=(1, 2)))
    assert decision == {"type": "approve"}


def test_resolve_interrupt_rejects_on_wrong_token(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "CONFIRM-DELETE-1")
    decision = cli._resolve_interrupt(_delete_interrupt("CONFIRM-DELETE-2", ids=(1, 2)))
    assert decision == {"type": "reject"}


def test_resolve_interrupt_rejects_on_garbage(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "nope")
    decision = cli._resolve_interrupt(_delete_interrupt("CONFIRM-DELETE-1"))
    assert decision == {"type": "reject"}


class _AgentV2:
    def invoke(self, payload, config=None, version=None):
        return {"version": version}


class _AgentNoV2:
    def invoke(self, payload, config=None):
        return {"called": True}


def test_invoke_uses_v2_when_supported():
    assert cli._invoke(_AgentV2(), {}, {}) == {"version": "v2"}


def test_invoke_falls_back_without_version_kwarg():
    assert cli._invoke(_AgentNoV2(), {}, {}) == {"called": True}
