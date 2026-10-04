"""``TURN_EVENTS``: a watcher hears each tool call as it's about to run, a
held one naming its approval, through the one guard every tool path passes;
publishing never fails a turn, and nothing is heard without a watcher."""

import pytest

from nodes.agent.tool_execution import tool_call_refusal
from utils import capabilities
from utils.turn_events import publish, turn_ref_of


@pytest.fixture
def heard(monkeypatch):
    events = []
    monkeypatch.setattr(capabilities, "_providers", {capabilities.TURN_EVENTS: lambda c, e: events.append((c, e))})
    return events


async def _refusal(**overrides):
    return await tool_call_refusal(**{"user_id": "u", "workflow_id": "wf", "node_id": "n", "conversation_id": "ck:wf:n:k",
                                      "tool_name": "gmail__send", "tool_info": {"tool_type": "node_op"},
                                      "arguments": {"to": "ada@example.com"}, **overrides})


async def test_a_call_is_heard_as_it_is_about_to_run(heard):
    assert await _refusal() is None
    assert heard == [("ck:wf:n:k", {"type": "tool_call", "tool": "gmail__send", "arguments": {"to": "ada@example.com"}})]


async def test_a_held_call_names_its_approval(monkeypatch, heard):
    held = {"success": False, "error": "needs approval", "approval_required": {"approval_id": "ap1", "approver": "owner"}}

    async def guard(**kwargs):
        return held

    capabilities._providers[capabilities.TOOL_CALL_GUARD] = guard
    assert await _refusal() == held
    [(_, event)] = heard
    assert event["held"] == {"approval_id": "ap1", "approver": "owner"}


def test_publishing_never_fails_the_turn(monkeypatch):
    def broken(conversation_id, event):
        raise RuntimeError("down")

    monkeypatch.setattr(capabilities, "_providers", {capabilities.TURN_EVENTS: broken})
    publish("ck:wf:n:k", {"type": "text", "text": "hi"})
    monkeypatch.setattr(capabilities, "_providers", {})
    publish("ck:wf:n:k", {"type": "text", "text": "hi"})  # nobody watching


def test_a_turn_ref_is_read_from_the_node_config():
    assert turn_ref_of({"_turnRef": "op-1"}) == "op-1"
    assert turn_ref_of({}) is None and turn_ref_of(None) is None
