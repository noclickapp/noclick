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
    assert terminal_kwargs["outcome"] == "failed"
    assert emitted and emitted[0].data["success"] is False
    assert emitted[0].data["incomplete"] is True
    assert emitted[0].data["nodes"][0]["id"] == "partial"
