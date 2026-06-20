"""Regression: OpenRouter ``:free`` models must never be billed.

Root cause (prod, 2026-06-18): the agent billing hook captured the provider's
streamed cost into a container-global ``{response_id: cost}`` dict and popped
it back in ``on_llm_end``. The SDK reports ``__fake_id__`` as the response id
for every streamed call, so the keyed lookup always missed and fell back to a
LIFO "pop the most-recent entry" guess. A ``:free`` model reports $0 (storing
nothing), then inherited a leftover *paid* cost from an unrelated call —
billing a free run for another call's spend.

The fix replaces the global dict + LIFO with a per-call cost sink bound to the
call's async context (no cross-attribution), records a provider-reported $0 as
$0 (instead of discarding it as "no data"), and adds an explicit ``:free``
guard so a free model bills $0 no matter what any cost source reports.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import asyncio
import pytest

from coder.openai_agent import billing
from coder.openai_agent.billing import BillingHooks


@pytest.fixture
def anyio_backend():
    return "asyncio"


_TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
_FREE_MODEL = "openrouter/nvidia/nemotron-3-nano-30b-a3b:free"


def _response(input_tokens=25, output_tokens=126):
    """SDK-shaped ModelResponse stub with a populated usage block."""
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        output=[],
        response_id="__fake_id__",  # the SDK's streaming placeholder
        request_id=None,
    )


def _bind_sink(cost, reported):
    """Bind a ready cost sink to the current context, as if the litellm
    success callback already fired for this call. Returns the reset token."""
    sink = billing._CostSink()
    sink.cost = cost
    sink.reported = reported
    sink.ready.set()
    return billing._active_cost_sink.set(sink)


async def _track_event(hooks, response):
    with patch(
        "billing.usage_tracker.usage_tracker.track_usage_event", new=MagicMock()
    ) as mock_track:
        await hooks.on_llm_end(context=MagicMock(), agent=MagicMock(), response=response)
    mock_track.assert_called_once()
    return mock_track.call_args[0][0]


# --------------------------------------------------------------------------- #
# The core regression
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_free_model_bills_zero_even_with_stale_provider_cost():
    """A ``:free`` model must bill $0 even when a non-zero cost is sitting in
    the active sink — exactly the cross-attribution the old LIFO produced."""
    hooks = BillingHooks(model=_FREE_MODEL, user_id=_TEST_USER_ID, sio=None, sid=None)
    # A paid cost is bound (as the old global dict would have leaked); the
    # ``:free`` guard must ignore it entirely.
    token = _bind_sink(cost=0.02, reported=True)
    try:
        event = await _track_event(hooks, _response())
    finally:
        billing._active_cost_sink.reset(token)

    assert event.total_cost == Decimal("0")
    assert event.metadata["cost_source"] == "free_model"
    # Real token counts are still recorded so the row exists on the dashboard.
    assert event.metadata["prompt_tokens"] == 25
    assert event.metadata["completion_tokens"] == 126
    assert event.usage_subtype == _FREE_MODEL


# --------------------------------------------------------------------------- #
# Supporting behavior the fix relies on
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_provider_reported_zero_recorded_as_zero():
    """A non-free model whose provider reports $0 bills $0 via the provider
    path — a reported zero is data, not "missing cost"."""
    hooks = BillingHooks(model="openrouter/openai/gpt-4o-mini", user_id=_TEST_USER_ID, sio=None, sid=None)
    token = _bind_sink(cost=0.0, reported=True)
    try:
        event = await _track_event(hooks, _response())
    finally:
        billing._active_cost_sink.reset(token)

    assert event.total_cost == Decimal("0")
    assert event.metadata["cost_source"] == "provider"


@pytest.mark.anyio
async def test_provider_cost_applied_with_markup():
    """A non-free model with a positive provider cost is billed that cost ×
    the platform markup, sourced from the per-call sink."""
    hooks = BillingHooks(model="openrouter/openai/gpt-4o-mini", user_id=_TEST_USER_ID, sio=None, sid=None)
    token = _bind_sink(cost=0.01, reported=True)
    try:
        event = await _track_event(hooks, _response())
    finally:
        billing._active_cost_sink.reset(token)

    from billing.markup import PLATFORM_MIN_MARKUP
    assert event.total_cost == Decimal("0.01") * PLATFORM_MIN_MARKUP
    assert event.metadata["cost_source"] == "provider"


@pytest.mark.anyio
async def test_concurrent_calls_capture_their_own_cost():
    """Two concurrent calls each capture their OWN cost — the contextvar
    isolation that replaces the cross-attributing global LIFO."""

    async def call(cost_value):
        billing._active_cost_sink.set(billing._CostSink())
        await asyncio.sleep(0)  # interleave with the other call
        # Simulate the litellm success callback firing for THIS call.
        billing._record_provider_cost({"response_cost": cost_value}, None)
        await asyncio.sleep(0)
        sink = billing._active_cost_sink.get()
        return (sink.cost, sink.reported)

    results = await asyncio.gather(call(0.01), call(0.99), call(0.0))
    assert results == [(0.01, True), (0.99, True), (0.0, True)]


def test_record_provider_cost_noop_without_sink():
    """A litellm call outside an SDK-agent run (no sink bound) must not record
    anything — unrelated litellm traffic can't pollute billing."""
    billing._active_cost_sink.set(None)
    # Must not raise.
    billing._record_provider_cost({"response_cost": 0.5}, None)
    assert billing._active_cost_sink.get() is None


# --------------------------------------------------------------------------- #
# Pure-function units
# --------------------------------------------------------------------------- #
def test_is_free_model():
    assert billing._is_free_model("openrouter/nvidia/nemotron-3-nano-30b-a3b:free")
    assert billing._is_free_model("openrouter/qwen/qwen3-coder:free")
    assert billing._is_free_model("MODEL:FREE")  # case-insensitive
    assert not billing._is_free_model("openrouter/openai/gpt-4o-mini")
    assert not billing._is_free_model("gpt-4o")
    assert not billing._is_free_model(None)
    assert not billing._is_free_model("")


def test_extract_distinguishes_reported_zero_from_missing():
    # Reported via kwargs — including an explicit 0.
    assert billing._extract_cost_from_litellm_response(None, {"response_cost": 0}) == (0.0, True)
    assert billing._extract_cost_from_litellm_response(None, {"response_cost": 0.5}) == (0.5, True)
    # No cost field anywhere → not reported.
    assert billing._extract_cost_from_litellm_response(None, {}) == (None, False)
    # OpenRouter streamed usage.cost — zero and positive both count as reported.
    zero = SimpleNamespace(usage=SimpleNamespace(cost=0.0), _hidden_params={})
    assert billing._extract_cost_from_litellm_response(zero, {}) == (0.0, True)
    paid = SimpleNamespace(usage=SimpleNamespace(cost=0.02), _hidden_params={})
    assert billing._extract_cost_from_litellm_response(paid, {}) == (0.02, True)
