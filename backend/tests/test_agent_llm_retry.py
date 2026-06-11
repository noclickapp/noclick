"""
Turn-level retry for transient LLM/provider failures in the SDK agent wrapper
(coder/openai_agent/agent.py).

Contract under test:
- a retryable provider error (litellm transient classes) on a turn that
  produced NOTHING observable — no streamed text, no run items — is retried
  up to _LLM_RUN_ATTEMPTS with backoff;
- a turn that already streamed text or executed a tool is NEVER retried
  (a retry would duplicate user-visible output or re-fire side effects);
- deterministic errors (bad request, auth, plain exceptions) are not retried;
- exhausted retries surface the original error exactly like before
  (ChatMessageEvent "Error: ..." + AgentStateEvent state='error').
"""

from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest

from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from coder.openai_agent.agent import (
    _LLM_RUN_ATTEMPTS,
    _RETRY_MAX_DELAY_S,
    Agent,
    _is_retryable_llm_error,
    _retry_delay,
)
from wss.sender import AgentStateEvent, ChatMessageEvent


def _transient_error():
    return litellm.ServiceUnavailableError(
        message="openrouter raised a streaming error - finish_reason: error",
        llm_provider="openrouter",
        model="minimax/minimax-m3",
    )


# ---------------------------------------------------------------------------
# Classification + backoff
# ---------------------------------------------------------------------------

class TestClassification:
    def test_transient_provider_errors_are_retryable(self):
        assert _is_retryable_llm_error(_transient_error())
        assert _is_retryable_llm_error(
            litellm.RateLimitError(message="slow down", llm_provider="openai", model="gpt-4o")
        )
        assert _is_retryable_llm_error(
            litellm.APIConnectionError(message="conn reset", llm_provider="openai", model="gpt-4o")
        )

    def test_deterministic_errors_are_not(self):
        assert not _is_retryable_llm_error(
            litellm.AuthenticationError(message="bad key", llm_provider="openai", model="gpt-4o")
        )
        assert not _is_retryable_llm_error(
            litellm.BadRequestError(message="bad arg", llm_provider="openai", model="gpt-4o")
        )
        assert not _is_retryable_llm_error(ValueError("template error"))

    def test_backoff_bounded_with_jitter(self):
        for attempt in range(6):
            for _ in range(20):
                d = _retry_delay(attempt)
                assert 0.0 <= d <= _RETRY_MAX_DELAY_S


# ---------------------------------------------------------------------------
# Turn-level retry behavior
# ---------------------------------------------------------------------------

class FakeResult:
    """Stand-in for the SDK's RunResultStreaming."""

    def __init__(self, events=(), exc=None, final_output=None):
        self._events = list(events)
        self._exc = exc
        self.final_output = final_output

    async def stream_events(self):
        for ev in self._events:
            yield ev
        if self._exc is not None:
            raise self._exc

    def to_input_list(self):
        return [{"role": "assistant", "content": self.final_output or ""}]

    def cancel(self):
        pass


def _make_agent(events):
    """Hand-built Agent (bypasses create()) with an event collector."""
    agent = Agent.__new__(Agent)
    agent._initialized = True
    agent._sdk_agent = MagicMock()
    agent._session = None
    agent._history = []
    agent._billing_hooks = None
    agent._env = None
    agent._active_result = None
    agent._emit_run_item_event = AsyncMock()

    async def emit(event):
        events.append(event)

    agent._emit_message = emit
    return agent


def _text_delta_event(text):
    ev = MagicMock(spec=RawResponsesStreamEvent)
    ev.data = MagicMock()
    ev.data.type = "response.output_text.delta"
    ev.data.delta = text
    return ev


MESSAGE = {"content_items": [{"type": "text", "text": "summarize this"}]}


@pytest.mark.asyncio
class TestTurnRetry:
    async def test_transient_error_with_no_output_retries_then_succeeds(self):
        events = []
        agent = _make_agent(events)
        attempts = [
            FakeResult(exc=_transient_error()),
            FakeResult(final_output="the summary"),
        ]
        with patch("coder.openai_agent.agent.Runner.run_streamed", side_effect=attempts) as run, \
             patch("coder.openai_agent.agent._retry_delay", return_value=0.0):
            await agent(MESSAGE)

        assert run.call_count == 2
        # A retry status was surfaced, then the run completed normally.
        assert any(
            isinstance(e, ChatMessageEvent) and e.status == "Retrying" for e in events
        )
        final = [e for e in events if isinstance(e, ChatMessageEvent) and e.finished]
        assert final and final[-1].message == "the summary"
        assert not any(isinstance(e, AgentStateEvent) for e in events)

    async def test_exhausted_retries_surface_error(self):
        events = []
        agent = _make_agent(events)
        with patch(
            "coder.openai_agent.agent.Runner.run_streamed",
            side_effect=[FakeResult(exc=_transient_error())] * _LLM_RUN_ATTEMPTS,
        ) as run, patch("coder.openai_agent.agent._retry_delay", return_value=0.0):
            await agent(MESSAGE)

        assert run.call_count == _LLM_RUN_ATTEMPTS
        errors = [e for e in events if isinstance(e, AgentStateEvent)]
        assert errors and errors[-1].state == "error"
        final = [e for e in events if isinstance(e, ChatMessageEvent) and e.finished]
        assert final and final[-1].message.startswith("Error:")

    async def test_partial_streamed_text_blocks_retry(self):
        """Text already reached the user — retrying would duplicate it."""
        events = []
        agent = _make_agent(events)
        failing = FakeResult(events=[_text_delta_event("Markets are")], exc=_transient_error())
        with patch("coder.openai_agent.agent.Runner.run_streamed", side_effect=[failing]) as run, \
             patch("coder.openai_agent.agent._retry_delay", return_value=0.0):
            await agent(MESSAGE)

        assert run.call_count == 1
        assert any(isinstance(e, AgentStateEvent) and e.state == "error" for e in events)

    async def test_tool_call_blocks_retry(self):
        """A run item means a tool may have fired — retrying re-runs side effects."""
        events = []
        agent = _make_agent(events)
        item_event = MagicMock(spec=RunItemStreamEvent)
        failing = FakeResult(events=[item_event], exc=_transient_error())
        with patch("coder.openai_agent.agent.Runner.run_streamed", side_effect=[failing]) as run, \
             patch("coder.openai_agent.agent._retry_delay", return_value=0.0):
            await agent(MESSAGE)

        assert run.call_count == 1
        agent._emit_run_item_event.assert_awaited_once_with(item_event)
        assert any(isinstance(e, AgentStateEvent) and e.state == "error" for e in events)

    async def test_non_retryable_error_fails_immediately(self):
        events = []
        agent = _make_agent(events)
        failing = FakeResult(exc=ValueError("template exploded"))
        with patch("coder.openai_agent.agent.Runner.run_streamed", side_effect=[failing]) as run:
            await agent(MESSAGE)

        assert run.call_count == 1
        assert any(isinstance(e, AgentStateEvent) and e.state == "error" for e in events)

    async def test_success_first_try_no_retry_machinery(self):
        events = []
        agent = _make_agent(events)
        ok = FakeResult(events=[_text_delta_event("All good.")], final_output="All good.")
        with patch("coder.openai_agent.agent.Runner.run_streamed", side_effect=[ok]) as run:
            await agent(MESSAGE)

        assert run.call_count == 1
        assert not any(
            isinstance(e, ChatMessageEvent) and e.status == "Retrying" for e in events
        )
        # Streamed chunks populated the accumulator; completion carries no
        # duplicate text.
        final = [e for e in events if isinstance(e, ChatMessageEvent) and e.finished]
        assert final and final[-1].message is None
