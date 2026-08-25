"""Tests for the drain-interrupt vs user-cancel split (2026-06-19 fix).

A container drain cancels every active builder scope with reason="shutdown"
(api.py lifespan → cancel_all_builder_scopes). Before this fix the turn loop
collapsed "shutdown" into the same terminal as a user Stop ("user"): both became
TurnResult(next_action="cancelled") → _finalize_run_cancelled, which commits a
cancelled:true assistant turn AND clears the resume checkpoint — mislabeling a
drain as a user cancel and making it UNRECOVERABLE.

The fix threads the CancelScope reason → TurnResult.cancel_reason → the handler's
cancelled dispatch, which now routes "shutdown" to _finalize_run_interrupted: it
emits active_gen:terminal outcome='interrupted' (the SAME signal the event relay
sends → InterruptedRunBanner auto-resume), KEEPS the checkpoint, and does NOT
commit cancelled:true. "user" keeps _finalize_run_cancelled exactly. Operation-limit failures are reported directly as incomplete and never enter
cancellation dispatch.

These tests drive the REAL builder turn loop + the REAL handler dispatch
(_drive_builder_and_terminate) + the REAL resume_checkpoint store (fakeredis), stubbing only
the LLM stream and the DB-writing collaborators, so they assert the actual
end-to-end behavior the production drain path takes.
"""
from __future__ import annotations

from types import SimpleNamespace

import fakeredis.aioredis
import pytest

from coder.workflow import resume_checkpoint as rc
from coder.workflow.agentic.builder import AgenticBuilder
from coder.workflow.agentic.config import AgenticBuilderConfig
from coder.workflow.agentic.state import TurnResult
from utils.cancellation import CancelScope
import wss.handlers.workflow_builder_handler as wbh
from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler


PLAN = [
    {"tag": "add_node", "attrs": {"name": "n1", "type": "automation-slack"}, "body": None},
    {"tag": "add_node", "attrs": {"name": "n2", "type": "automation-slack"}, "body": None},
]


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(rc, "_client", lambda: client)
    return client


def _aret(value):
    async def _f(*a, **kw):
        return value
    return _f


def _make_request(cid: str) -> SimpleNamespace:
    """A WorkflowBuilderEditRequest stand-in carrying every field the finalizers
    read (conversation_id, request_id, edit_prompt, current_graph, target/selected
    node ids, user_context)."""
    return SimpleNamespace(
        conversation_id=cid,
        request_id="req-1",
        edit_prompt="build it",
        current_graph={},
        target_node_ids=None,
        selected_node_id=None,
        user_context=None,
    )


async def _drive_with_cancel_reason(monkeypatch, fake_redis, *, reason, user_id):
    """Run _drive_builder_and_terminate end to end where the single turn is cancelled
    with the given CancelScope reason.

    Models a FIRST-run drain faithfully: no checkpoint exists at run start (so the
    resume gate does NOT fire), the brain turn writes the plan checkpoint (as the
    real brain does via save_plan) and then is cancelled — leaving the checkpoint
    behind for the keep-vs-clear assertion.

    Returns (handler, builder, cid, emitted_terminals, committed_turns) where
    emitted_terminals is the list of active_gen:terminal events emitted and
    committed_turns is the list of new_messages handed to _save_conversation.
    """
    cid = "conv-drain"

    builder = AgenticBuilder(
        config=AgenticBuilderConfig(max_turns=3),
        generation_id="gen-drain",
        conversation_id=cid,
        user_id=user_id,
    )
    builder.user_id = user_id

    # Stub the turn so it writes a plan checkpoint mid-turn (as the real brain
    # does), then reports cancelled with the given reason — exactly the
    # TurnResult builder.run_one_turn produces for that scope reason.
    async def fake_run_one_turn():
        await rc.save_plan(cid, turn=1, prompt="build it", ops=PLAN)
        await rc.mark_node_completed(cid, "n1")
        builder._last_turn_result = TurnResult(
            next_action="cancelled", cancel_reason=reason,
        )
        return
        yield  # async generator

    monkeypatch.setattr(builder, "run_one_turn", fake_run_one_turn)

    handler = object.__new__(WorkflowBuilderHandler)
    handler.sio = SimpleNamespace()
    handler._gen_to_request_id = {}
    monkeypatch.setattr(handler, "_emit_builder_event", _aret(""))
    # Avoid DB writes from the usage helper (the cancel path hits it).
    async def _noop_store_builder_usage_event(*a, **kw):
        return None
    monkeypatch.setattr(handler, "_store_builder_usage_event", _noop_store_builder_usage_event)

    # Capture the session-end success arg: cancel writes False ("failed"),
    # interrupt writes None ("ended, neither completed nor failed") so the row
    # is_active=FALSE but not mistaken for a clean cancel.
    session_end_success = []

    async def fake_log_session_end(success=True):
        session_end_success.append(success)

    monkeypatch.setattr(builder, "log_session_end", fake_log_session_end)

    # Capture the committed conversation turns (cancel path commits cancelled:true).
    committed_turns = []

    async def fake_save_conversation(conv_id, uid, new_messages, **kw):
        committed_turns.append(new_messages)
        return new_messages

    monkeypatch.setattr(handler, "_save_conversation", fake_save_conversation)

    # Capture every emitted event (active_gen:terminal + ResponseEvents) by sniffing
    # the module-level send_event the handler uses.
    emitted = []

    async def fake_send_event(sio, sid, event, **kw):
        emitted.append(event)

    monkeypatch.setattr(wbh, "send_event", fake_send_event)

    await handler._drive_builder_and_terminate(
        "sid", builder,
        request=_make_request(cid),
        user_id=user_id,
        session={},
        start_time=0.0,
        model_used="m",
        current_graph_summary={},
        conversation_history_len=0,
        generation_id="gen-drain",
        log_context="test",
    )

    terminals = [e for e in emitted if getattr(e, "event_name", None) == "active_gen:terminal"]
    return handler, builder, cid, terminals, committed_turns, session_end_success


# ── shutdown → recoverable interrupt ────────────────────────────────────────

async def test_shutdown_cancel_keeps_checkpoint_and_emits_interrupted(monkeypatch, fake_redis):
    """A drain (reason='shutdown') KEEPS the checkpoint, emits outcome='interrupted',
    and does NOT commit a cancelled:true turn."""
    handler, builder, cid, terminals, committed_turns, session_end = await _drive_with_cancel_reason(
        monkeypatch, fake_redis, reason="shutdown", user_id="u-1",
    )

    # Checkpoint PRESERVED — the auto-resume has a plan to replay.
    assert await rc.load_checkpoint(cid) is not None, (
        "a shutdown interrupt must KEEP the checkpoint for InterruptedRunBanner resume"
    )

    # outcome='interrupted' emitted (the same signal the event relay sends).
    assert len(terminals) == 1
    assert terminals[0].outcome == "interrupted"
    assert terminals[0].gen_id == "gen-drain"
    # The FE ignores committed_messages for interrupted — we send it empty.
    assert terminals[0].committed_messages == []

    # NO cancelled:true assistant turn committed.
    assert committed_turns == [], "interrupt must NOT commit a turn at all"
    # DB row: is_active=FALSE with success=None (not False) so it isn't mistaken
    # for a zombie nor a clean user cancel.
    assert session_end == [None], "interrupt must end the session with success=None"


async def test_shutdown_cancel_no_cancelled_response_frames(monkeypatch, fake_redis):
    """The interrupt path must NOT emit the legacy cancelled:true ResponseEvents
    that _finalize_run_cancelled sends (they would render the 'Response interrupted
    by user' cancelled bubble + commit cancelled:true)."""
    cid = "conv-frames"

    builder = AgenticBuilder(
        config=AgenticBuilderConfig(max_turns=3),
        generation_id="gen-frames", conversation_id=cid, user_id="u-1",
    )
    builder.user_id = "u-1"

    async def fake_run_one_turn():
        await rc.save_plan(cid, turn=1, prompt="build it", ops=PLAN)
        builder._last_turn_result = TurnResult(next_action="cancelled", cancel_reason="shutdown")
        return
        yield
    monkeypatch.setattr(builder, "run_one_turn", fake_run_one_turn)

    handler = object.__new__(WorkflowBuilderHandler)
    handler.sio = SimpleNamespace()
    handler._gen_to_request_id = {}
    monkeypatch.setattr(handler, "_emit_builder_event", _aret(""))
    async def _noop_store_builder_usage_event(*a, **kw):
        return None
    monkeypatch.setattr(handler, "_store_builder_usage_event", _noop_store_builder_usage_event)
    monkeypatch.setattr(builder, "log_session_end", _aret(None))

    emitted = []
    async def fake_send_event(sio, sid, event, **kw):
        emitted.append(event)
    monkeypatch.setattr(wbh, "send_event", fake_send_event)

    await handler._drive_builder_and_terminate(
        "sid", builder, request=_make_request(cid), user_id="u-1",
        session={}, start_time=0.0, model_used="m", current_graph_summary={},
        conversation_history_len=0, generation_id="gen-frames", log_context="t",
    )

    # No event carries cancelled:true (the FE's cancelled rendering trigger).
    for e in emitted:
        data = getattr(e, "data", None)
        if isinstance(data, dict):
            assert data.get("cancelled") is not True, (
                f"interrupt must not emit a cancelled:true frame: {data}"
            )


# ── user → terminal cancel (UNCHANGED) ──────────────────────────────────────

async def test_user_cancel_clears_checkpoint_and_commits_cancelled(monkeypatch, fake_redis):
    """A user Stop (reason='user') CLEARS the checkpoint, commits a cancelled:true
    turn, and emits outcome='cancelled' — the existing behavior, unchanged."""
    handler, builder, cid, terminals, committed_turns, session_end = await _drive_with_cancel_reason(
        monkeypatch, fake_redis, reason="user", user_id="u-1",
    )

    # Checkpoint CLEARED so it is not auto-resumed.
    assert await rc.load_checkpoint(cid) is None, (
        "a user cancel must CLEAR the checkpoint"
    )

    # outcome='cancelled' (NOT interrupted).
    assert len(terminals) == 1
    assert terminals[0].outcome == "cancelled"

    # A cancelled:true assistant turn WAS committed.
    assert len(committed_turns) == 1
    msgs = committed_turns[0]
    assistant = next(m for m in msgs if m.get("role") == "assistant")
    assert assistant.get("cancelled") is True, "user cancel must commit cancelled:true"
    # DB row: user cancel ends the session with success=False (unchanged).
    assert session_end == [False], "user cancel must end the session with success=False"


# ── op_limit is an internal kill — never reaches a cancelled terminal ─────────



async def test_shutdown_reason_threaded_through_real_run_one_turn(monkeypatch):
    """Pin the reason thread end-to-end through the REAL run_one_turn: a 'shutdown'
    scope cancel must surface as next_action='cancelled' with cancel_reason='shutdown'
    (the thread the interrupt finalize routes on). The shutdown-dispatch tests stub
    run_one_turn, so without this the live builder.py threading is only exercised by
    the direct operation-limit path, which never enters cancellation dispatch."""
    config = AgenticBuilderConfig(
        max_turns=3, max_ops_per_turn_soft=20, max_ops_per_turn_kill=25,
    )
    builder = AgenticBuilder(config=config, generation_id="drain-thread")

    from utils.cancellation import CancelledByUser

    builder.cancel_scope = CancelScope()
    builder.cancel_scope.cancel(reason="shutdown")

    async def boom_inner():
        raise CancelledByUser()
        yield
    monkeypatch.setattr(builder, "_run_one_turn_inner", boom_inner)

    async for _ in builder.run_one_turn():
        pass

    result = builder.last_turn_result()
    # A shutdown cancellation is terminal and
    # carries its reason so the dispatch routes it to the recoverable interrupt path.
    assert result.next_action == "cancelled"
    assert result.cancel_reason == "shutdown"


async def test_non_shutdown_cancel_reason_does_not_route_to_interrupt(monkeypatch, fake_redis):
    """Defense in depth: even if a 'cancelled' result somehow carried cancel_reason
    other than 'shutdown' (e.g. 'user'/None), it must route to _finalize_run_cancelled,
    NOT the interrupt path. Only 'shutdown' is the recoverable interrupt."""
    handler, builder, cid, terminals, committed_turns, session_end = await _drive_with_cancel_reason(
        monkeypatch, fake_redis, reason="superseded", user_id="u-1",
    )
    # A non-'shutdown' reason takes the cancelled path: checkpoint cleared, cancelled
    # terminal, cancelled:true committed.
    assert await rc.load_checkpoint(cid) is None
    assert terminals[0].outcome == "cancelled"
    assert len(committed_turns) == 1
