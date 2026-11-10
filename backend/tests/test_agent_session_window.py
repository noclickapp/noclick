"""The replay window a bounded session hands the model must be coherent: a
tool output without its call, or reasoning without its message, fails the
whole turn at the provider."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from coder.openai_agent.session import PostgresSession, coherent_tail


def _user(i): return {"role": "user", "content": f"u{i}"}
def _assistant(i): return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": f"a{i}"}]}
def _call(i): return {"type": "function_call", "call_id": f"call_{i}", "name": "list_workflows", "arguments": "{}"}
def _output(i): return {"type": "function_call_output", "call_id": f"call_{i}", "output": "{}"}
def _reasoning(i): return {"type": "reasoning", "content": [{"type": "reasoning_text", "text": f"r{i}"}]}


def test_window_opens_on_a_user_message_never_on_an_orphan_output():
    history = [_user(1), _reasoning(1), _call(1), _output(1), _assistant(1),
               _user(2), _call(2), _output(2), _assistant(2), _user(3), _assistant(3)]
    # A naive tail of 8 would open on call_1's output with its call gone.
    assert [i for i in history[-8:]][0] == _output(1)
    window = coherent_tail(history, 8)
    assert window[0] == _user(2) and window[-1] == _assistant(3)
    # Wide enough: untouched. Exact fit: untouched.
    assert coherent_tail(history, 50) == history and coherent_tail(history, len(history)) == history


def test_a_turn_longer_than_the_window_opens_on_a_standalone_item():
    history = [_user(1)] + [x for i in range(10) for x in (_reasoning(i), _call(i), _output(i))] + [_assistant(1)]
    window = coherent_tail(history, 5)
    # tail = [reasoning_9? ...]: whatever the cut, the first item is a call or a message, never an output or reasoning
    assert window[0]["type"] in ("function_call", "message")
    assert all(item in history for item in window) and window[-1] == _assistant(1)


@pytest.mark.asyncio
async def test_get_items_applies_the_coherent_window(monkeypatch):
    history = [_user(1), _call(1), _output(1), _assistant(1), _user(2), _assistant(2)]
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"metadata": {"sdk_history": history}})
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    session = PostgresSession("coordinator:u1", user_id="u1", history_limit=4)
    assert await session.get_items() == [_user(2), _assistant(2)]
    assert await session.get_items(limit=None) == [_user(2), _assistant(2)]  # the session's own bound applies
    session_all = PostgresSession("coordinator:u1", user_id="u1")
    assert await session_all.get_items() == history


@pytest.mark.asyncio
async def test_a_read_only_session_remembers_but_is_not_remembered(monkeypatch):
    """A live phone turn reads the caller's conversation and writes nothing:
    the call's transcript at hang-up is the one message it leaves behind."""
    history = [_user(1), _assistant(1)]
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"metadata": {"sdk_history": history}})
    pool.execute = AsyncMock()
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    session = PostgresSession("ck:wf:agent:+1555:+1567", user_id="u1", read_only=True)
    assert await session.get_items() == history
    await session.add_items([_user(2), _assistant(2)])
    assert await session.pop_item() is None
    await session.clear_session()
    pool.execute.assert_not_awaited()


def test_a_call_its_stopped_turn_never_answered_is_closed_for_the_next_turn():
    """A turn stopped mid-call kept the call and no result: the next turn reads it closed, so its model neither runs it
    again nor answers it (a stopped ``sleep 150 && echo too-late`` ran again and became the next reply)."""
    from coder.openai_agent.session import STOPPED_CALL, close_unanswered

    items = [
        {"role": "user", "content": "Run the slow command."},
        {"type": "function_call", "call_id": "c1", "name": "execute_bash", "arguments": "{}"},
        {"type": "function_call", "call_id": "c2", "name": "read", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c2", "output": "ok"},
        {"role": "user", "content": "Reply with exactly after."},
    ]
    closed = close_unanswered(items)
    assert [i.get("call_id") or i.get("role") for i in closed] == ["user", "c1", "c1", "c2", "c2", "user"]
    assert closed[2] == {"type": "function_call_output", "call_id": "c1", "output": STOPPED_CALL}
    answered = items[:1] + [items[2], items[3]]
    assert close_unanswered(answered) == answered, "nothing to close: the history as it is"
