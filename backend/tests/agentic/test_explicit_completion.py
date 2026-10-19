"""Handler invariants for the builder's explicit completion protocol."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from coder.workflow.agentic.builder import AgenticBuilder
from coder.workflow.agentic.config import AgenticBuilderConfig
from coder.workflow.agentic.state import TurnResult
import wss.handlers.workflow_builder_handler as wbh
from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id=None,
        request_id="req-explicit-done",
        edit_prompt="build it",
        current_graph={"nodes": [], "edges": []},
        target_node_ids=None,
        selected_node_id=None,
        user_context=None,
        n8n_workflow=None,
    )


@pytest.mark.asyncio
async def test_max_turns_is_incomplete_not_done(monkeypatch):
    builder = AgenticBuilder(
        config=AgenticBuilderConfig(max_turns=1),
        generation_id="gen-max-turns",
        conversation_id="conv-max-turns",
    )
    builder._user_prompt = "build it"

    async def one_nonterminal_turn():
        builder._turn_count += 1
        builder._last_turn_result = TurnResult(next_action="continue")
        return
        yield

    monkeypatch.setattr(builder, "run_one_turn", one_nonterminal_turn)
    monkeypatch.setattr(wbh.resume_checkpoint, "load_checkpoint", AsyncMock(return_value=None))

    handler = object.__new__(WorkflowBuilderHandler)
    handler._emit_builder_event = AsyncMock(return_value="")
    result, _ = await handler._run_builder_turns(
        "sid",
        builder,
        segments=[],
        pending_text="",
        user_context=None,
        edit_steps=[],
    )

    assert result == TurnResult(
        next_action="incomplete",
        incomplete_reason="max_turns_without_explicit_done",
    )


@pytest.mark.asyncio
async def test_driver_routes_incomplete_without_calling_complete(monkeypatch):
    builder = AgenticBuilder(
        generation_id="gen-route-incomplete",
        conversation_id=None,
    )
    handler = object.__new__(WorkflowBuilderHandler)
    handler.sio = SimpleNamespace()
    handler._run_builder_turns = AsyncMock(return_value=(
        TurnResult(
            next_action="incomplete",
            incomplete_reason="missing_explicit_terminal",
        ),
        "",
    ))
    handler._finalize_run_incomplete = AsyncMock()
    handler._finalize_run_complete = AsyncMock()
    handler._finalize_run_failed = AsyncMock()
    monkeypatch.setattr(
        wbh.resume_checkpoint,
        "claim_attempt",
        AsyncMock(return_value=None),
    )

    await handler._drive_builder_and_terminate(
        "sid",
        builder,
        request=_request(),
        user_id=None,
        session={},
        start_time=0.0,
        model_used="test-model",
        current_graph_summary={},
        conversation_history_len=0,
        generation_id=builder.generation_id,
        log_context="explicit-completion-test",
    )

    handler._finalize_run_incomplete.assert_awaited_once()
    assert (
        handler._finalize_run_incomplete.await_args.kwargs["reason"]
        == "missing_explicit_terminal"
    )
    handler._finalize_run_complete.assert_not_awaited()
    handler._finalize_run_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_incomplete_finalizer_preserves_graph_and_reports_failure(monkeypatch):
    builder = AgenticBuilder(
        generation_id="gen-incomplete",
        conversation_id=None,
    )
    builder.graph_state.add_node(
        "partial", "automation-exa", label="Partial research"
    )

    handler = object.__new__(WorkflowBuilderHandler)
    handler.sio = SimpleNamespace()
    handler._persist_builder_graph = AsyncMock()
    handler._emit_active_gen_terminal = AsyncMock()
    handler._clear_checkpoint_if_current = AsyncMock()
    handler._maybe_notify_agent_result = AsyncMock()
    handler._store_build_request = lambda *args, **kwargs: None
    handler._store_builder_usage_event = AsyncMock()
    builder.log_session_end = AsyncMock()

    emitted = []

    async def capture_event(sio, sid, event, **kwargs):
        emitted.append(event)

    monkeypatch.setattr(wbh, "send_event", capture_event)

    await handler._finalize_run_incomplete(
        "sid",
        builder,
        request=_request(),
        reason="missing_explicit_terminal",
        segments=[{"type": "text", "text": "I will build it."}],
        pending_text="",
        conversation_history_len=0,
        edit_steps=[],
        user_id=None,
        start_time=0.0,
        model_used="test-model",
        current_graph_summary={},
    )

    handler._persist_builder_graph.assert_awaited_once()
    builder.log_session_end.assert_awaited_once_with(
        success=False,
        terminal_reason="missing_explicit_terminal",
    )
    handler._emit_active_gen_terminal.assert_awaited_once()
    terminal_kwargs = handler._emit_active_gen_terminal.await_args.kwargs
    # Unfinished is its own outcome: no error happened, and the reply says so.
    assert terminal_kwargs["outcome"] == "incomplete"
    assert emitted and emitted[0].data["success"] is False
    assert emitted[0].data["incomplete"] is True
    assert emitted[0].data["nodes"][0]["id"] == "partial"


def _saving_handler(existing=()):
    """A handler whose conversation store is a list: what it read, and what it was asked to save."""
    handler = object.__new__(WorkflowBuilderHandler)
    handler.sio = SimpleNamespace()
    saved = []

    class Repo:
        def __init__(self, pool):
            pass

        async def upsert_events(self, **kwargs):
            saved.append(kwargs["events"])

    handler.get_pool = AsyncMock(return_value=None)
    handler._read_conversation_events = AsyncMock(return_value=list(existing))
    return handler, saved, Repo


@pytest.mark.asyncio
async def test_an_imported_workflows_request_is_kept_as_an_import(monkeypatch):
    """The import goes in its own field; its request alone is a sentence, never one to send again as it is."""
    handler, saved, Repo = _saving_handler()
    monkeypatch.setattr(wbh, "ConversationRepo", Repo)
    monkeypatch.setattr(wbh, "send_event", AsyncMock())
    handler._persist_builder_graph = AsyncMock()
    handler._emit_active_gen_terminal = AsyncMock()
    handler._clear_checkpoint_if_current = AsyncMock()
    handler._maybe_notify_agent_result = AsyncMock()
    handler._store_build_request = lambda *args, **kwargs: None
    handler._store_builder_usage_event = AsyncMock()
    handler._new_turn_llm_messages = lambda *args, **kwargs: []
    builder = AgenticBuilder(generation_id="gen-import", conversation_id="conv-import")
    builder.log_session_end = AsyncMock()
    request = SimpleNamespace(**{**vars(_request()), "conversation_id": "conv-import",
                                 "edit_prompt": "Import this n8n workflow into NoClick.",
                                 "n8n_workflow": {"nodes": [{"name": "Cron"}, {"name": "Slack"}]}})

    await handler._finalize_run_incomplete(
        "sid", builder, request=request, reason="missing_explicit_terminal", segments=[], pending_text="",
        conversation_history_len=0, edit_steps=[], user_id="u1", start_time=0.0, model_used="m",
        current_graph_summary={},
    )

    assert saved[-1][0] == {"role": "user", "message": "Import this n8n workflow into NoClick.", "n8n_import": {"node_count": 2}}


@pytest.mark.asyncio
async def test_a_run_that_was_started_announces_an_import_as_one(monkeypatch):
    sent = []
    monkeypatch.setattr(wbh, "send_event", AsyncMock(side_effect=lambda sio, sid, event, **kw: sent.append(event)))
    handler = object.__new__(WorkflowBuilderHandler)
    handler.sio = SimpleNamespace()
    handler._gen_to_request_id = {}
    await handler._emit_active_gen_started("sid", gen_id="g", workflow_id="wf", conversation_id="c",
                                           prompt="Import this n8n workflow into NoClick.", user_id="u1",
                                           n8n_import_node_count=2)
    assert sent[0].n8n_import_node_count == 2


@pytest.mark.asyncio
async def test_a_resumed_run_that_stops_unfinished_is_kept_unfinished(monkeypatch):
    """Answering or skipping a question continues its turn in place; how that run ended is how the turn ends."""
    paused = [
        {"role": "user", "message": "Add Gmail"},
        {"role": "assistant", "message": "", "edit_segments": [], "pending_ask": {"ask_id": "a1", "inputs": [{}]}},
    ]
    handler, saved, Repo = _saving_handler(paused)
    monkeypatch.setattr(wbh, "ConversationRepo", Repo)
    merged = await handler._save_conversation("c", "u1", [
        {"role": "user", "message": "Add Gmail"},
        {"role": "assistant", "message": "", "edit_segments": [], "incomplete": True, "incomplete_reason": "missing_explicit_terminal"},
    ], replace_pending=True)
    assert merged[-1]["incomplete"] is True and merged[-1]["incomplete_reason"] == "missing_explicit_terminal"
    assert "pending_ask" not in merged[-1]


@pytest.mark.asyncio
async def test_answering_a_later_turns_question_continues_that_turn(monkeypatch):
    """A run resumed after a question goes on with the request it paused on, never the chat's first one."""
    chat = [
        {"role": "user", "message": "Add Gmail"},
        {"role": "assistant", "message": "", "edit_segments": [{"type": "text", "text": "Added it."}]},
        {"role": "user", "message": "Post the brief to Slack"},
        {"role": "assistant", "message": "", "edit_segments": [], "pending_ask": {"ask_id": "a2", "inputs": [{}]}},
    ]
    handler, saved, Repo = _saving_handler(chat)
    monkeypatch.setattr(wbh, "ConversationRepo", Repo)
    request = WorkflowBuilderHandler._paused_request(chat)
    merged = await handler._save_conversation("c", "u1", [
        {"role": "user", "message": request},
        {"role": "assistant", "message": "", "edit_segments": [{"type": "text", "text": "Posted."}]},
    ], replace_pending=True)
    assert [m.get("message") for m in merged if m["role"] == "user"] == ["Add Gmail", "Post the brief to Slack"]
    assert merged[-1]["edit_segments"] == [{"type": "text", "text": "Posted."}] and "pending_ask" not in merged[-1]
