"""AgentNode.execute() must always give the chat surface a terminal signal.

The interface chat send dispatches the agent via ``workflow:execute`` and shows
a streaming indicator until it receives a terminal ``chat:message`` (finished)
or ``agent:state`` (error) for the conversation. Early failures — a missing
sandbox-mount credential, the CLI credit/credential gate, tool-delivery injection
— raise before any harness emits, so without the execute() failure wrapper the
chat dot pulses forever. These tests pin that wrapper: any exception emits a
terminal, conversation-scoped ``agent:state`` error (idempotently), and a
cancelled run is not reported as a chat error.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from nodes.agent_node import AgentNode
from wss.sender import AgentStateEvent


def _make_agent(captured):
    async def fake_send_event(sio, sid, event):
        captured.append(event)

    agent = AgentNode(
        node_id="agent_1",
        node_type="agent",
        node_data={},
        config=None,
        sio=MagicMock(),
        sid="sid_1",
        workflow_id="wf_1",
    )
    # conversation_key is normally captured inside _execute_impl; set it here
    # since these tests stub the impl out.
    agent._conversation_key = "__interface_chat__"
    return agent, fake_send_event


@pytest.mark.asyncio
async def test_early_failure_emits_terminal_error_scoped_to_conversation(monkeypatch):
    captured = []
    agent, fake_send_event = _make_agent(captured)
    monkeypatch.setattr("nodes.agent_node.send_event", fake_send_event)

    async def boom(_inputs):
        raise ValueError("Sandbox mount 'owner/repo' requires a credential")

    monkeypatch.setattr(agent, "_execute_impl", boom)

    with pytest.raises(ValueError, match="requires a credential"):
        await agent.execute({})

    errors = [e for e in captured if isinstance(e, AgentStateEvent) and e.state == "error"]
    assert len(errors) == 1
    # Must be the ck-form the frontend AgentChatBlock subscribes to, or the
    # indicator never clears.
    assert errors[0].conversation_id == "ck:wf_1:agent_1:__interface_chat__"
    assert "requires a credential" in errors[0].reason


@pytest.mark.asyncio
async def test_no_double_emit_when_harness_already_reported_error(monkeypatch):
    captured = []
    agent, fake_send_event = _make_agent(captured)
    monkeypatch.setattr("nodes.agent_node.send_event", fake_send_event)

    async def boom(_inputs):
        # Mirror emit_callback marking a terminal error the harness already sent.
        agent._terminal_state_emitted = True
        raise ValueError("failure after the harness already emitted its error")

    monkeypatch.setattr(agent, "_execute_impl", boom)

    with pytest.raises(ValueError):
        await agent.execute({})

    assert [e for e in captured if isinstance(e, AgentStateEvent)] == []


@pytest.mark.asyncio
async def test_cancelled_run_is_not_reported_as_chat_error(monkeypatch):
    captured = []
    agent, fake_send_event = _make_agent(captured)
    monkeypatch.setattr("nodes.agent_node.send_event", fake_send_event)

    async def boom(_inputs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(agent, "_execute_impl", boom)

    with pytest.raises(asyncio.CancelledError):
        await agent.execute({})

    assert captured == []


@pytest.mark.asyncio
async def test_success_does_not_emit_error(monkeypatch):
    captured = []
    agent, fake_send_event = _make_agent(captured)
    monkeypatch.setattr("nodes.agent_node.send_event", fake_send_event)

    async def ok(_inputs):
        return {"type": "agent", "status": "completed"}

    monkeypatch.setattr(agent, "_execute_impl", ok)

    result = await agent.execute({})
    assert result["status"] == "completed"
    assert captured == []
