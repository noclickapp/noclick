"""Unit tests for ``CostCapturingLitellmModel``.

The model overrides ``_fetch_response`` to capture provider-reported cost
from the raw LiteLLM result BEFORE the SDK transforms it (which strips
``_hidden_params`` and rebuilds usage without ``cost``). Tests stub the
parent's ``_fetch_response`` so we don't need a live OpenRouter call.

Covers:
  - non-streaming path: cost read off the assembled response's usage.cost.
  - streaming path: cost captured from a usage-bearing chunk while the
    consumer iterates; non-usage chunks pass through unchanged.
  - per-call slot reset: turn N never reads turn N-1's stale cost.
  - missing cost: ``last_call_cost_reported`` stays ``False``.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, AsyncIterator, List
from unittest.mock import AsyncMock, patch

import pytest

from coder.openai_agent.litellm_model import CostCapturingLitellmModel


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _chunk(text: str | None = None, *, cost: float | None = None) -> SimpleNamespace:
    """Build a stand-in for litellm.types.utils.ModelResponseStream."""
    usage = SimpleNamespace(cost=cost) if cost is not None else None
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))] if text else [],
        usage=usage,
    )


class _FakeStream:
    """Minimal CustomStreamWrapper stand-in: async-iterates a fixed chunk list."""

    def __init__(self, chunks: List[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> AsyncIterator[Any]:
        async def gen():
            for c in self._chunks:
                yield c
        return gen()


# --------------------------------------------------------------------------- #
# Non-streaming path
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_fetch_response_non_streaming_captures_cost():
    model = CostCapturingLitellmModel(model="openrouter/openai/gpt-4o-mini")
    fake_response = SimpleNamespace(
        usage=SimpleNamespace(cost=0.0042, prompt_tokens=10, completion_tokens=5),
        _hidden_params={"response_cost": None},
    )
    with patch.object(
        CostCapturingLitellmModel.__bases__[0],
        "_fetch_response",
        new=AsyncMock(return_value=fake_response),
    ):
        result = await model._fetch_response(stream=False)
    assert result is fake_response
    assert model.last_call_cost == 0.0042
    assert model.last_call_cost_reported is True


@pytest.mark.anyio
async def test_fetch_response_non_streaming_no_cost_marks_unreported():
    model = CostCapturingLitellmModel(model="openrouter/openai/gpt-4o-mini")
    fake_response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),  # no cost field
        _hidden_params={},
    )
    with patch.object(
        CostCapturingLitellmModel.__bases__[0],
        "_fetch_response",
        new=AsyncMock(return_value=fake_response),
    ):
        await model._fetch_response(stream=False)
    assert model.last_call_cost is None
    assert model.last_call_cost_reported is False


# --------------------------------------------------------------------------- #
# Streaming path
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_stream_interceptor_captures_cost_from_final_chunk():
    """The most common shape: usage-with-cost arrives on the final chunk."""
    model = CostCapturingLitellmModel(model="openrouter/~openai/gpt-mini-latest")
    chunks = [
        _chunk("Hello"),
        _chunk(" world"),
        _chunk(cost=0.000123),  # OpenRouter's final usage chunk
    ]
    fake_stream = _FakeStream(chunks)
    fake_response = SimpleNamespace()
    with patch.object(
        CostCapturingLitellmModel.__bases__[0],
        "_fetch_response",
        new=AsyncMock(return_value=(fake_response, fake_stream)),
    ):
        response, wrapped_stream = await model._fetch_response(stream=True)

    # Cost slot is reset to None at the start of the call — set only as the
    # interceptor sees the usage chunk while the consumer iterates.
    assert model.last_call_cost is None

    collected = []
    async for chunk in wrapped_stream:
        collected.append(chunk)

    # All chunks passed through unchanged.
    assert collected == chunks
    assert model.last_call_cost == 0.000123
    assert model.last_call_cost_reported is True


@pytest.mark.anyio
async def test_stream_interceptor_captures_latest_when_split_across_chunks():
    """Some providers emit usage twice (e.g. mid-stream + final). Take the
    latest reported value, not the first."""
    model = CostCapturingLitellmModel(model="openrouter/openai/gpt-oss-120b")
    chunks = [
        _chunk("partial"),
        _chunk(cost=0.0001),  # early usage chunk
        _chunk(" output"),
        _chunk(cost=0.0005),  # final, authoritative
    ]
    fake_stream = _FakeStream(chunks)
    with patch.object(
        CostCapturingLitellmModel.__bases__[0],
        "_fetch_response",
        new=AsyncMock(return_value=(SimpleNamespace(), fake_stream)),
    ):
        _, wrapped_stream = await model._fetch_response(stream=True)
    async for _ in wrapped_stream:
        pass
    assert model.last_call_cost == 0.0005
    assert model.last_call_cost_reported is True


@pytest.mark.anyio
async def test_stream_with_no_usage_marks_unreported():
    """Provider that drops the usage chunk entirely → reported stays False so
    BillingHooks can fall back to the pricing table."""
    model = CostCapturingLitellmModel(model="openrouter/community/whatever")
    chunks = [_chunk("only text"), _chunk(" no usage")]
    fake_stream = _FakeStream(chunks)
    with patch.object(
        CostCapturingLitellmModel.__bases__[0],
        "_fetch_response",
        new=AsyncMock(return_value=(SimpleNamespace(), fake_stream)),
    ):
        _, wrapped_stream = await model._fetch_response(stream=True)
    async for _ in wrapped_stream:
        pass
    assert model.last_call_cost is None
    assert model.last_call_cost_reported is False


@pytest.mark.anyio
async def test_per_call_slot_reset_between_turns():
    """Turn N must NOT see turn N-1's cost. ``_fetch_response`` resets the
    slot at the top of every call."""
    model = CostCapturingLitellmModel(model="openrouter/openai/gpt-4o-mini")

    # Turn 1: cost reported.
    with patch.object(
        CostCapturingLitellmModel.__bases__[0],
        "_fetch_response",
        new=AsyncMock(return_value=SimpleNamespace(usage=SimpleNamespace(cost=0.01), _hidden_params={})),
    ):
        await model._fetch_response(stream=False)
    assert model.last_call_cost == 0.01
    assert model.last_call_cost_reported is True

    # Turn 2: provider drops cost — slot MUST clear, not stick at 0.01.
    with patch.object(
        CostCapturingLitellmModel.__bases__[0],
        "_fetch_response",
        new=AsyncMock(return_value=SimpleNamespace(usage=SimpleNamespace(input_tokens=1), _hidden_params={})),
    ):
        await model._fetch_response(stream=False)
    assert model.last_call_cost is None
    assert model.last_call_cost_reported is False


# --------------------------------------------------------------------------- #
# A model stuck streaming whitespace
# --------------------------------------------------------------------------- #
def _real_chunk(*, text=None, arguments=None, name=None, call_id=None, usage=None):
    """An OpenAI chat-completion chunk, as the SDK's stream handler reads it."""
    from openai.types.chat import ChatCompletionChunk
    from openai.types.chat.chat_completion_chunk import (
        Choice, ChoiceDelta, ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction,
    )

    calls = None if arguments is None else [ChoiceDeltaToolCall(
        index=0, id=call_id, type="function" if call_id else None,
        function=ChoiceDeltaToolCallFunction(name=name, arguments=arguments))]
    return ChatCompletionChunk(
        id="gen-stuck", object="chat.completion.chunk", created=0, model="test-model", usage=usage,
        choices=[] if usage else [Choice(index=0, delta=ChoiceDelta(content=text, tool_calls=calls))])


class _Stream:
    """A provider stream: ``head`` chunks, then whitespace in a tool call's arguments for ``blank`` chunks (a model
    stuck until its output cap), then a usage chunk; it records how much was read and whether it was closed."""

    def __init__(self, head, blank=0):
        from openai.types.completion_usage import CompletionUsage

        self._chunks = iter([*head, *(_real_chunk(arguments="\n  ") for _ in range(blank)),
                             _real_chunk(usage=CompletionUsage(prompt_tokens=10, completion_tokens=65536,
                                                               total_tokens=65546))])
        self.read = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        chunk = next(self._chunks, None)
        if chunk is None:
            raise StopAsyncIteration
        self.read += 1
        return chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.anyio
async def test_a_model_streaming_whitespace_has_its_call_ended_and_calls_again():
    """A shop's assistant wrote its question's arguments, then streamed newlines and spaces for minutes until the
    model's output cap; the cut-off arguments answered it as invalid JSON and it asked again, properly. The call now
    ends at ``STUCK_WHITESPACE_CHARS`` of whitespace in a row (the provider's stream closed, read no further), and
    the run goes on the same way: the tool answers the cut arguments as invalid, the model calls again."""
    import json

    from agents import Agent as SDKAgent
    from agents import FunctionTool, Runner

    from coder.openai_agent import litellm_model

    head = '{"question": "Dana asks who owns the bakery. What should we tell her?"'
    stuck = _Stream([_real_chunk(arguments=head, name="human__ask", call_id="call_1")], blank=30_000)
    answer = _Stream([_real_chunk(text="I asked the owner.")])
    streams = iter([stuck, answer])
    got = []

    async def ask(ctx, arguments):
        got.append(arguments)
        try:
            json.loads(arguments)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON arguments for tool 'human__ask': {exc}"})
        return json.dumps({"success": True})

    agent = SDKAgent(name="shop", instructions="Ask the owner.", model=CostCapturingLitellmModel(model="test/model"),
                     tools=[FunctionTool(name="human__ask", description="Ask the owner.", on_invoke_tool=ask,
                                         params_json_schema={"type": "object",
                                                             "properties": {"question": {"type": "string"}}},
                                         strict_json_schema=False)])
    with patch("litellm.acompletion", new=AsyncMock(side_effect=lambda **kwargs: next(streams))) as model:
        result = Runner.run_streamed(agent, "Dana wrote: Qui est le propriétaire ?")
        async for _ in result.stream_events():
            pass

    assert result.final_output == "I asked the owner."
    assert model.await_count == 2
    # The stuck call was ended once its whitespace reached the limit: the stream was closed, barely read.
    assert stuck.closed and stuck.read <= 1 + litellm_model.STUCK_WHITESPACE_CHARS // 3 + 1
    [cut] = got
    assert cut.startswith(head) and not cut[len(head):].strip()
    # The chunk that reached the limit isn't passed on.
    assert litellm_model.STUCK_WHITESPACE_CHARS - 3 <= len(cut) - len(head) < litellm_model.STUCK_WHITESPACE_CHARS
    # A stream that ends on its own is read to its end and never cut.
    assert answer.read == 2 and not answer.closed


@pytest.mark.anyio
async def test_whitespace_in_real_output_never_ends_a_call():
    """Indentation, blank lines and a reply's paragraphs reset the count at each word: only a run of whitespace with
    nothing in it ends a call."""
    from coder.openai_agent import litellm_model

    pretty = "\n".join(" " * 40 + f'"line{i}": "value",' for i in range(200))
    chunks = [_chunk(pretty), _chunk("\n\n" + " " * (litellm_model.STUCK_WHITESPACE_CHARS - 10) + "more"),
              _chunk(cost=0.001)]
    model = CostCapturingLitellmModel(model="openrouter/openai/gpt-4o-mini")
    with patch.object(CostCapturingLitellmModel.__bases__[0], "_fetch_response",
                      new=AsyncMock(return_value=(SimpleNamespace(), _FakeStream(chunks)))):
        _, wrapped = await model._fetch_response(stream=True)
    assert [c async for c in wrapped] == chunks
    assert model.last_call_cost == 0.001


# --------------------------------------------------------------------------- #
# A provider that stalls
# --------------------------------------------------------------------------- #
class _Silent:
    """A provider stream that sends ``chunks``, then nothing ever again (OpenRouter holding the connection open while
    its provider never answers); it records whether it was closed."""

    def __init__(self, chunks=()):
        self._chunks = list(chunks)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.mark.anyio
async def test_a_call_whose_first_chunk_never_comes_is_asked_again(monkeypatch):
    """A coordinator's third model call of a texted turn never answered: nothing timed it out, so the turn sat silent
    for 15 minutes until its time limit cancelled it (2026-10-27). A call that sends nothing within ``FIRST_CHUNK_S``
    is now closed and requested again before the SDK has read anything, so the run goes on as if it had answered."""
    from agents import Agent as SDKAgent
    from agents import Runner

    from coder.openai_agent import litellm_model

    monkeypatch.setattr(litellm_model, "FIRST_CHUNK_S", 0.05)
    stalled = _Silent()
    answer = _Stream([_real_chunk(text="I'm changing the label in the file you sent.")])
    streams = iter([stalled, answer])
    agent = SDKAgent(name="coordinator", instructions="Help.", model=CostCapturingLitellmModel(model="test/model"))
    with patch("litellm.acompletion", new=AsyncMock(side_effect=lambda **kwargs: next(streams))) as model:
        result = Runner.run_streamed(agent, "change Score to Points in my game")
        async for _ in result.stream_events():
            pass

    assert result.final_output == "I'm changing the label in the file you sent."
    assert model.await_count == 2
    assert stalled.closed
    assert answer.read == 2 and not answer.closed


@pytest.mark.anyio
async def test_a_call_that_stalls_every_time_fails_as_a_timeout_the_run_retries(monkeypatch):
    """Past ``STALL_ATTEMPTS`` requests the call fails, as a timeout: the run's own retry treats it as transient."""
    import litellm

    from coder.openai_agent import litellm_model
    from coder.openai_agent.agent import _is_retryable_llm_error

    monkeypatch.setattr(litellm_model, "FIRST_CHUNK_S", 0.01)
    stalls = [_Silent() for _ in range(litellm_model.STALL_ATTEMPTS)]
    parent = AsyncMock(side_effect=[(SimpleNamespace(), s) for s in stalls])
    model = CostCapturingLitellmModel(model="openrouter/openai/gpt-4o-mini")
    with patch.object(CostCapturingLitellmModel.__bases__[0], "_fetch_response", new=parent):
        with pytest.raises(litellm.Timeout) as raised:
            await model._fetch_response(stream=True)
    assert parent.await_count == litellm_model.STALL_ATTEMPTS
    assert all(s.closed for s in stalls)
    assert _is_retryable_llm_error(raised.value)


@pytest.mark.anyio
async def test_a_stream_that_goes_silent_partway_ends_there(monkeypatch):
    """A stream that stops sending partway is ended after ``CHUNK_GAP_S``, as a stuck one is: what came is kept."""
    from coder.openai_agent import litellm_model

    monkeypatch.setattr(litellm_model, "CHUNK_GAP_S", 0.05)
    chunks = [_chunk("I'm changing "), _chunk("the label")]
    silent = _Silent(chunks)
    model = CostCapturingLitellmModel(model="openrouter/openai/gpt-4o-mini")
    with patch.object(CostCapturingLitellmModel.__bases__[0], "_fetch_response",
                      new=AsyncMock(return_value=(SimpleNamespace(), silent))):
        _, wrapped = await model._fetch_response(stream=True)
        got = [c async for c in wrapped]
    assert got == chunks
    assert silent.closed
