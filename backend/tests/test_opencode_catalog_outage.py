"""An outage of Zen's /models and models.dev costs an OpenCode turn one short,
bounded wait, not two sequential 15s timeouts on every turn: the pre-flight
reads both at once under its own bound, a failed source is remembered for a
minute, and models.dev serves its last good copy once a refresh fails."""

import asyncio
import time

import httpx
import pytest

import nodes.agent.config.harness_model_lists as lists
import utils.opencode_zen as zen

BOUND_S = 0.5


@pytest.fixture
def outage(monkeypatch):
    """Both catalogs hang; returns the URLs asked for."""
    asked = []
    real_client = httpx.AsyncClient

    async def hang(request):
        asked.append(str(request.url))
        await asyncio.sleep(30)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(hang), **kw))
    monkeypatch.setattr(lists, "_PREFLIGHT_TIMEOUT_S", BOUND_S)
    monkeypatch.setattr(zen, "_servable_cache", {})
    monkeypatch.setattr(zen, "_models_dev_cache", None)
    monkeypatch.setattr(zen, "_failed_at", {})
    return asked


async def _timed_refusal(model):
    started = time.perf_counter()
    refusal = await lists.opencode_model_refusal(model, catalog_is_the_cli_list=True)
    return refusal, time.perf_counter() - started


@pytest.mark.asyncio
async def test_an_outage_costs_one_bounded_wait_then_none(outage):
    refusal, first = await _timed_refusal("opencode/deepseek-v4-flash-free")
    assert refusal is None  # nothing could be read, so nothing is judged
    # Both reads ran at once: one bound, not two in a row.
    assert first < 1.8 * BOUND_S, first
    assert sorted(outage) == ["https://models.dev/api.json", "https://opencode.ai/zen/v1/models"]

    refusal, second = await _timed_refusal("opencode/deepseek-v4-flash-free")
    assert refusal is None
    assert second < 0.1, second  # the failure is remembered: no new request, no wait
    assert len(outage) == 2


@pytest.mark.asyncio
async def test_a_failed_refresh_serves_the_last_good_catalogs(outage, monkeypatch):
    catalog = {"opencode": {"models": {"big-pickle": {"tool_call": True}}}}
    stale = time.time() - 2 * zen._MODELS_DEV_TTL_S
    monkeypatch.setattr(zen, "_models_dev_cache", (catalog, stale))
    monkeypatch.setattr(zen, "_servable_cache", {"opencode": ({"big-pickle"}, stale)})

    assert await zen.fetch_models_dev(timeout=BOUND_S) is catalog
    assert await zen.get_zen_servable_ids("opencode", timeout=BOUND_S) == {"big-pickle"}
    # ...and the pre-flight still judges with them, at once.
    refusal, took = await _timed_refusal("opencode/deepseek-v4-flash-free")
    assert "OpenCode Zen no longer serves it" in refusal
    assert took < 0.1, took


@pytest.mark.asyncio
async def test_models_dev_with_no_copy_raises_and_is_not_retried_at_once(outage):
    with pytest.raises(Exception):
        await zen.fetch_models_dev(timeout=BOUND_S)
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="could not be read"):
        await zen.fetch_models_dev(timeout=BOUND_S)
    assert time.perf_counter() - started < 0.1
    assert outage == ["https://models.dev/api.json"]
