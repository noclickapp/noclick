"""
Tests for user-pause cancellation in the agentic builder + extension.

Verifies the OpenRouter pattern (set cancel flag → close response → break)
is honored at every layer:
- Brain stream loop (agentic.brain.LiteLLMBrain)
- registered node-drafter stream loop

And the higher-level invariant the user asked for: when cancelled mid-turn,
the in-flight assistant message is discarded so the next user prompt picks
up from the previous turn's context.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from coder.workflow.agentic.builder import AgenticBuilder
from coder.workflow.agentic.config import AgenticBuilderConfig
from utils import cancellation as _cancellation
from utils.cancellation import (
    CancelScope,
    CancelledByUser,
    bind_scope,
    reset_scope,
)


# ---------------------------------------------------------------------------
# Mock streaming response that tracks aclose() and pause-after-N-chunks
# ---------------------------------------------------------------------------

class TrackedStream:
    """Async iterable that mimics a litellm streaming response.

    Yields `chunks_before_pause` chunks, then calls `on_pause()` (which the test
    uses to flip a CancelScope), then keeps yielding until aclose() is called
    or the loop breaks. Records whether aclose() was awaited.
    """

    def __init__(self, content: str, chunks_before_pause: int, on_pause):
        self._content = content
        self._chunks_before_pause = chunks_before_pause
        self._on_pause = on_pause
        self.aclose_called = False
        self._closed = False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for i, ch in enumerate(self._content):
            if self._closed:
                return
            if i == self._chunks_before_pause:
                self._on_pause()
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock()
            chunk.choices[0].delta.content = ch
            chunk.choices[0].delta.reasoning_content = None
            chunk.choices[0].delta.reasoning = None
            chunk.choices[0].delta.tool_calls = None
            yield chunk
            await asyncio.sleep(0)  # Yield to event loop so cancel checks can run

    async def aclose(self):
        self.aclose_called = True
        self._closed = True


def _make_acompletion_returning(stream: TrackedStream):
    """Return an async function suitable for patching litellm.acompletion."""
    async def _acompletion(*args, **kwargs):
        return stream
    return _acompletion


async def _empty_async_gen(*args, **kwargs):
    """Stub async generator that yields nothing."""
    return
    yield  # pragma: no cover — makes this a generator


# ---------------------------------------------------------------------------
# Brain stream tests
# ---------------------------------------------------------------------------

class TestBrainStreamCancellation:
    @pytest.mark.asyncio
    async def test_brain_stream_aborts_on_cancel(self):
        """LiteLLMBrain breaks out of its async-for loop and aclose's the stream."""
        from coder.workflow.agentic.brain import LiteLLMBrain

        scope = CancelScope()
        token = bind_scope(scope)
        try:
            stream = TrackedStream(
                content="abcdefghij" * 5,
                chunks_before_pause=3,
                on_pause=scope.cancel,
            )
            brain = LiteLLMBrain(model="test-model", max_attempts=1)

            collected = []
            with patch("litellm.acompletion", side_effect=_make_acompletion_returning(stream)):
                with pytest.raises(CancelledByUser):
                    async for item in brain.step(
                        messages=[{"role": "user", "content": "hi"}],
                        turn=1,
                        generation_id="t1",
                    ):
                        if isinstance(item, str):
                            collected.append(item)

            # We must have emitted *some* tokens (the ones before the pause)
            # but stopped early — full content is 50 chars, we cancel at 3.
            assert 1 <= len(collected) <= 10, f"unexpected collected count: {len(collected)}"
            assert stream.aclose_called, "Brain stream did not call aclose() on cancel"
        finally:
            reset_scope(token)


# ---------------------------------------------------------------------------
# node drafter stream test
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# node drafter stream test
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Builder turn-rollback test
# ---------------------------------------------------------------------------

class TestBuilderTurnRollback:
    @pytest.mark.asyncio
    async def test_cancel_mid_turn_discards_assistant_message(self):
        """The in-flight turn's partial output must NOT land in builder.messages."""
        config = AgenticBuilderConfig(max_turns=3)
        scope = CancelScope()
        builder = AgenticBuilder(
            config=config, generation_id="cancel-test", cancel_scope=scope,
        )

        # Long response, cancellation flips after a few chunks.
        long_response = "I'll start with " + ("more text " * 200) + "<done/>"
        stream = TrackedStream(
            content=long_response,
            chunks_before_pause=10,
            on_pause=scope.cancel,
        )

        from coder.workflow.schema import BuilderInput
        await builder.generate(BuilderInput(prompt="Build something"))

        pretturn_message_count = len(builder.messages)
        pretturn_messages_snapshot = list(builder.messages)

        with patch("litellm.acompletion", side_effect=_make_acompletion_returning(stream)):
            events = []
            async for ev in builder.run_one_turn():
                events.append(ev)

        result = builder.last_turn_result()
        assert result.next_action == "cancelled"
        # Message list rolled back: no partial assistant message appended.
        assert len(builder.messages) == pretturn_message_count
        assert builder.messages == pretturn_messages_snapshot
        # And the underlying HTTP stream was torn down.
        assert stream.aclose_called

    @pytest.mark.asyncio
    async def test_cancel_before_first_chunk_is_honored(self):
        """If the scope is already flipped when run_one_turn starts, no chunks are emitted."""
        config = AgenticBuilderConfig(max_turns=3)
        scope = CancelScope()
        scope.cancel()  # Pre-cancel before any LLM activity.
        builder = AgenticBuilder(
            config=config, generation_id="early-cancel", cancel_scope=scope,
        )

        # The stream factory should never be reached; if it is, this would
        # produce thousands of chunks. We assert the brain never even calls
        # litellm.acompletion by counting invocations.
        invocation_count = 0
        stream = TrackedStream(content="x" * 200, chunks_before_pause=10**9, on_pause=lambda: None)
        async def _counting_acompletion(*a, **kw):
            nonlocal invocation_count
            invocation_count += 1
            return stream

        from coder.workflow.schema import BuilderInput
        await builder.generate(BuilderInput(prompt="Build something"))
        pretturn_messages = list(builder.messages)

        with patch("litellm.acompletion", side_effect=_counting_acompletion):
            async for _ in builder.run_one_turn():
                pass

        assert builder.last_turn_result().next_action == "cancelled"
        assert invocation_count == 0, "Pre-cancelled scope should short-circuit before LLM call"
        assert builder.messages == pretturn_messages


    @pytest.mark.asyncio
    async def test_cancel_then_resume_uses_clean_context(self):
        """After a cancelled turn, the next prompt sees only the original messages."""
        config = AgenticBuilderConfig(max_turns=3)
        scope = CancelScope()
        builder = AgenticBuilder(
            config=config, generation_id="cancel-resume-test", cancel_scope=scope,
        )

        cancel_stream = TrackedStream(
            content="Long partial response " * 100,
            chunks_before_pause=5,
            on_pause=scope.cancel,
        )

        from coder.workflow.schema import BuilderInput
        await builder.generate(BuilderInput(prompt="Initial prompt"))
        original_messages = list(builder.messages)

        # First turn — cancelled.
        with patch("litellm.acompletion", side_effect=_make_acompletion_returning(cancel_stream)):
            async for _ in builder.run_one_turn():
                pass
        assert builder.last_turn_result().next_action == "cancelled"
        assert builder.messages == original_messages

        # Reset scope so the next turn doesn't immediately get cancelled.
        builder.cancel_scope = CancelScope()

        # Second turn — completes normally.
        good_response = "<done/>"
        good_stream = TrackedStream(content=good_response, chunks_before_pause=10**9, on_pause=lambda: None)
        with patch("litellm.acompletion", side_effect=_make_acompletion_returning(good_stream)):
            async for _ in builder.run_one_turn():
                pass

        # Messages now contains the good turn's assistant content but NOT any
        # of the cancelled turn's partial text.
        assert any(m.get("role") == "assistant" for m in builder.messages)
        assistant_texts = [m["content"] for m in builder.messages if m.get("role") == "assistant"]
        assert all("Long partial response" not in t for t in assistant_texts)


# ---------------------------------------------------------------------------
# Drain cancellation (container shutdown / scale-down) — the 2026-06-17 gap
# ---------------------------------------------------------------------------

class TestDrainCancellation:
    """A managed worker drain must flip every in-flight builder scope so the
    cooperative teardown (already covered above) runs and each run finalizes,
    instead of being hard-killed mid-stream and left as a zombie. The missing
    primitive is a broadcast cancel keyed off the active-scope registry."""

    def test_cancel_all_builder_scopes_cancels_registered_runs(self):
        c = _cancellation
        s1, s2 = CancelScope(), CancelScope()
        c.register_builder_scope("conv-drain-1", s1)
        c.register_builder_scope("conv-drain-2", s2)
        try:
            n = c.cancel_all_builder_scopes(reason="shutdown")
            assert n == 2
            assert s1.cancelled and s2.cancelled, "drain must cancel every active run"
            # A distinct reason lets the turn loop tell drain from a user pause.
            assert s1.reason == "shutdown"
        finally:
            c.unregister_builder_scope("conv-drain-1", s1)
            c.unregister_builder_scope("conv-drain-2", s2)

    def test_cancel_all_builder_scopes_empty_is_noop(self):
        """No active runs → returns 0, never raises (lifespan calls this blind)."""
        assert _cancellation.cancel_all_builder_scopes() == 0
