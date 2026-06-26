"""Regression: OpenRouter ``:free`` models must never be billed, and the
provider-reported cost on paid models is read in-band from the model
instance (not from a callback/sink that races against the SDK).

History:
  - 2026-06-18: agent billing captured provider cost into a container-global
    ``{response_id: cost}`` dict popped by a ``__fake_id__`` LIFO heuristic.
    The SDK uses ``__fake_id__`` as the response id for every streamed call,
    so the keyed lookup always missed and fell back to "pop the most-recent
    entry" — billing a call for a *different* call's cost. Most visible on
    ``:free`` models, which report $0 (storing nothing) and inherited a
    leftover paid cost from an unrelated call.
  - 2026-06-18: replaced with a per-call cost sink bound to the call's async
    context (no cross-attribution), plus an explicit ``:free`` guard.
  - Prior billing regression — ``openrouter/~openai/gpt-mini-latest``
    and ``deepseek-v4-pro`` calls booking as $0 with cost_source
    ``lookup_failed``. Root cause: the sink-via-callback channel raced
    against the SDK's response transformation; under load with large-context
    prompts the LiteLLM async success callback's queued task didn't run
    within ``_capture_provider_cost``'s 5s wait, frequently.
  - This file: covers the in-band capture path that replaced it.
    ``CostCapturingLitellmModel`` reads ``usage.cost`` off the LiteLLM
    response BEFORE the SDK transformation strips it, exposes it via
    ``last_call_cost``, and ``BillingHooks._record_usage`` reads that
    synchronously — no callback, no contextvar, no timeout.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from coder.openai_agent import billing
from coder.openai_agent.billing import BillingHooks
from coder.openai_agent.litellm_model import (
    CostCapturingLitellmModel,
    extract_cost_from_response,
)


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


def _model_with_cost(name: str, cost: float | None, reported: bool) -> CostCapturingLitellmModel:
    """Build a CostCapturingLitellmModel with the per-call slot pre-populated,
    as if ``_fetch_response`` had just completed."""
    m = CostCapturingLitellmModel(model=name)
    m._call_cost = cost
    m._call_cost_reported = reported
    return m


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
    the model's slot — exactly the cross-attribution the old LIFO produced."""
    model_instance = _model_with_cost(_FREE_MODEL, cost=0.02, reported=True)
    hooks = BillingHooks(
        model=_FREE_MODEL,
        model_instance=model_instance,
        user_id=_TEST_USER_ID,
        sio=None,
        sid=None,
    )
    event = await _track_event(hooks, _response())

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
    model = "openrouter/openai/gpt-4o-mini"
    model_instance = _model_with_cost(model, cost=0.0, reported=True)
    hooks = BillingHooks(
        model=model, model_instance=model_instance,
        user_id=_TEST_USER_ID, sio=None, sid=None,
    )
    event = await _track_event(hooks, _response())

    assert event.total_cost == Decimal("0")
    assert event.metadata["cost_source"] == "provider"


@pytest.mark.anyio
async def test_provider_cost_applied_with_markup():
    """A non-free model with a positive provider cost is billed that cost ×
    the platform markup, sourced from the model's last_call_cost slot."""
    model = "openrouter/openai/gpt-4o-mini"
    model_instance = _model_with_cost(model, cost=0.01, reported=True)
    hooks = BillingHooks(
        model=model, model_instance=model_instance,
        user_id=_TEST_USER_ID, sio=None, sid=None,
    )
    event = await _track_event(hooks, _response())

    from billing.markup import PLATFORM_MIN_MARKUP
    assert event.total_cost == Decimal("0.01") * PLATFORM_MIN_MARKUP
    assert event.metadata["cost_source"] == "provider"


@pytest.mark.anyio
async def test_provider_unreported_falls_to_pricing_table():
    """When the provider didn't surface cost (``reported=False``), fall to
    ``litellm.completion_cost``. This is the safety net for non-OpenRouter
    providers — it should NOT be hit in normal OpenRouter operation."""
    model = "openrouter/openai/gpt-4o-mini"
    model_instance = _model_with_cost(model, cost=None, reported=False)
    hooks = BillingHooks(
        model=model, model_instance=model_instance,
        user_id=_TEST_USER_ID, sio=None, sid=None,
    )
    event = await _track_event(hooks, _response())

    # gpt-4o-mini IS in litellm's pricing table; cost_source should be the
    # table path, not the previous lookup_failed leak.
    assert event.metadata["cost_source"] in ("litellm_pricing_table", "zero")


def test_billing_hooks_rejects_missing_model_instance():
    """A missing model_instance must fail loud — no fallback path. The
    previous design's "missing cost = lookup_failed = $0" is what this
    refactor exists to remove."""
    with pytest.raises(ValueError, match="CostCapturingLitellmModel"):
        BillingHooks(
            model="openrouter/openai/gpt-4o-mini",
            model_instance=None,  # type: ignore[arg-type]
            user_id=_TEST_USER_ID,
            sio=None,
            sid=None,
        )


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
    # No response object → not reported.
    assert extract_cost_from_response(None) == (None, False)
    # OpenRouter streamed usage.cost — zero and positive both count as reported.
    zero = SimpleNamespace(usage=SimpleNamespace(cost=0.0), _hidden_params={})
    assert extract_cost_from_response(zero) == (0.0, True)
    paid = SimpleNamespace(usage=SimpleNamespace(cost=0.02), _hidden_params={})
    assert extract_cost_from_response(paid) == (0.02, True)
    # Falls through to _hidden_params.response_cost when usage.cost absent.
    hidden = SimpleNamespace(usage=None, _hidden_params={"response_cost": 0.05})
    assert extract_cost_from_response(hidden) == (0.05, True)
    # OpenRouter's non-streaming header path.
    header = SimpleNamespace(
        usage=None,
        _hidden_params={"additional_headers": {"llm_provider-x-litellm-response-cost": "0.07"}},
    )
    assert extract_cost_from_response(header) == (0.07, True)
    # Truly missing cost across all paths.
    nothing = SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5), _hidden_params={})
    assert extract_cost_from_response(nothing) == (None, False)
