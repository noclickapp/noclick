"""Credit denial stays typed across the SDK while chat finishes exactly once."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from billing.exceptions import InsufficientBalanceError, insufficient_credits_message
from billing.usage_tracker import usage_tracker
from coder.openai_agent.agent import Agent
from coder.openai_agent.billing import BillingHooks
from nodes.agent.handlers.llm import execute_llm_model
from wss.handlers.agent_handler import AgentHandler
from wss.sender import AgentStateEvent, ChatMessageEvent
from wss.sender.schema import ContentItem


USER_ID = "00000000-0000-0000-0000-000000000001"
DENIAL = insufficient_credits_message(0, 0.2)


def _hooks(env=None):
    return BillingHooks(
        model="gpt-4o", model_instance=MagicMock(), user_id=USER_ID,
        sio=None, sid=None, env=env,
    )


async def test_denied_call_does_not_count_input_tokens(monkeypatch):
    denial = InsufficientBalanceError(DENIAL)
    gate = AsyncMock(side_effect=denial)
    count = MagicMock(return_value=123)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", gate)
    monkeypatch.setattr("coder.openai_agent.billing._count_input_tokens", count)
    hooks = _hooks()

    with pytest.raises(InsufficientBalanceError) as exc:
        await hooks.on_llm_start(None, None, "system", [{"content": "large history"}])

    assert exc.value is denial
    gate.assert_awaited_once()
    count.assert_not_called()
    assert hooks._pending_input_tokens == 0


@pytest.mark.parametrize("byok", [False, True])
async def test_admitted_call_keeps_token_accounting(monkeypatch, byok):
    order = []

    async def admit(*_args, **_kwargs):
        order.append("gate")

    def count(**_kwargs):
        order.append("count")
        return 123

    gate = AsyncMock(side_effect=admit)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", gate)
    monkeypatch.setattr("coder.openai_agent.billing._count_input_tokens", count)
    hooks = _hooks({"OPENAI_API_KEY": "test-byok"} if byok else None)

    await hooks.on_llm_start(None, None, "system", [{"content": "hello"}])

    assert order == (["count"] if byok else ["gate", "count"])
    assert gate.await_count == (0 if byok else 1)
    assert hooks._pending_input_tokens == 123


class _DeniedStream:
    def __init__(self, denial):
        self.denial = denial

    async def stream_events(self):
        raise self.denial
        yield  # pragma: no cover - SDK streams are async iterators


def _agent(emit):
    agent = Agent.__new__(Agent)
    agent._initialized = True
    agent._sdk_agent = MagicMock()
    agent._session = None
    agent._history = []
    agent._billing_hooks = None
    agent._env = None
    agent._active_result = None
    agent._emit_message = emit
    agent.cleanup = AsyncMock()
    return agent


@pytest.mark.parametrize("through_handler", [False, True])
async def test_denial_propagates_once_and_handler_cleans_up(monkeypatch, through_handler):
    denial = InsufficientBalanceError(DENIAL)
    emitted = []

    async def emit(event):
        emitted.append(event)

    agent = _agent(emit)
    run = MagicMock(return_value=_DeniedStream(denial))
    monkeypatch.setattr("coder.openai_agent.agent.Runner.run_streamed", run)
    node = SimpleNamespace(
        node_id="agent_1", sid=None, sio=None, organization_id=None,
        workflow_id="wf_1", execution_id="exec_1", conversation_id=None,
        emit=AsyncMock(),
    )
    config = SimpleNamespace(
        model="gpt-4o", temperature=0.7, system_prompt="",
        conversation_key=None, message="hello",
    )
    monkeypatch.setattr("nodes.agent.handlers.llm.Agent.create", AsyncMock(return_value=agent))

    with pytest.raises(InsufficientBalanceError) as exc:
        if through_handler:
            await execute_llm_model(node, config, None, USER_ID, None, emit_callback=emit)
        else:
            await agent({"content_items": [{"type": "text", "text": "hello"}]})

    assert exc.value is denial
    run.assert_called_once()
    assert len(emitted) == 2
    assert isinstance(emitted[0], ChatMessageEvent)
    assert emitted[0].finished is True
    assert emitted[0].message == DENIAL
    assert isinstance(emitted[1], AgentStateEvent)
    assert emitted[1].state == "error"
    assert emitted[1].reason == DENIAL
    assert agent._active_result is None
    assert agent._history == []
    assert agent.cleanup.await_count == (1 if through_handler else 0)
    node.emit.assert_not_awaited()


async def test_interactive_chat_does_not_emit_a_second_finished_message(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr("wss.handlers.agent_handler.send_event", send)
    handler = AgentHandler(MagicMock())
    emit = await handler._create_emit_callback(
        "sid_1", "gpt-4o", conversation_id="chat_1", user_id=None, workflow_id=None,
    )
    agent = _agent(emit)
    run = MagicMock(return_value=_DeniedStream(InsufficientBalanceError(DENIAL)))
    monkeypatch.setattr("coder.openai_agent.agent.Runner.run_streamed", run)

    await handler._process_message_with_content(
        agent, "sid_1", [ContentItem(type="text", text="hello")], "gpt-4o", "chat_1",
    )

    run.assert_called_once()
    events = [call.args[2] for call in send.await_args_list]
    assert len(events) == 2
    assert isinstance(events[0], ChatMessageEvent)
    assert events[0].message == DENIAL and events[0].finished is True
    assert isinstance(events[1], AgentStateEvent)
    assert events[1].state == "error" and events[1].reason == DENIAL


async def test_interactive_chat_still_reports_unexpected_failures(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr("wss.handlers.agent_handler.send_event", send)
    handler = AgentHandler(MagicMock())

    await handler._process_message_with_content(
        AsyncMock(side_effect=ValueError("unexpected")), "sid_1", [], "gpt-4o", "chat_1",
    )

    send.assert_awaited_once()
    event = send.await_args.args[2]
    assert event.finished is True and "unexpected" in event.message
