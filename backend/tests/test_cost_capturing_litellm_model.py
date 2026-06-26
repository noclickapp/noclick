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
