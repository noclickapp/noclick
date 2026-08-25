"""The public /api/models route must build the catalog without blocking the
event loop.

Regression guard for the perf finding where the async route called the sync
``list_all_models`` → ``get_openrouter_models_sync`` → ``requests.get`` chain,
blocking the asyncio loop for the full OpenRouter SSL round-trip (up to ~9s on
cache miss). The async path must await the httpx-based ``get_openrouter_models``
and never invoke the ``requests``-based sync fetch.
"""

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils import model_catalog, models_routes


@pytest.fixture(autouse=True)
def _clear_payload_cache():
    """The route caches its rendered body process-wide; isolate each test."""
    models_routes._payload_cache.clear()
    yield
    models_routes._payload_cache.clear()


def _boom_sync(*args, **kwargs):
    raise AssertionError(
        "get_openrouter_models_sync (requests.get) was called on the async path — "
        "this blocks the event loop"
    )


async def test_list_all_models_async_uses_async_fetch_not_requests():
    async_fetch = AsyncMock(return_value=[])
    with patch.object(model_catalog, "get_openrouter_models", async_fetch), \
         patch.object(model_catalog, "get_openrouter_models_sync", _boom_sync):
        models = await model_catalog.list_all_models_async()

    # The async fetch was awaited (not the blocking sync one, which would have raised).
    async_fetch.assert_awaited_once()
    # Aggregator still returns the in-memory litellm + static slices.
    assert isinstance(models, list)
    assert all(isinstance(m, model_catalog.Model) for m in models)


async def test_list_all_models_async_translates_openrouter_entries():
    raw = [{
        "id": "openai/gpt-4o",
        "name": "GPT-4o",
        "context_length": 128000,
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
    }]
    with patch.object(model_catalog, "get_openrouter_models", AsyncMock(return_value=raw)), \
         patch.object(model_catalog, "get_openrouter_models_sync", _boom_sync):
        models = await model_catalog.list_all_models_async()

    # _translate_openrouter prefixes the routing provider onto the id.
    assert any(m.id == "openrouter/openai/gpt-4o" and m.source == "openrouter" for m in models), \
        "OpenRouter entry not translated into the async catalog"


async def test_models_route_handler_does_not_block_loop():
    response = MagicMock()
    response.headers = {}
    with patch.object(models_routes, "list_all_models_async", AsyncMock(return_value=[])) as agg:
        result = await models_routes.list_models(response)

    agg.assert_awaited_once()
    assert result == {"models": [], "count": 0}
    assert "Cache-Control" in response.headers


# ── The CPU half ──────────────────────────────────────────────────────────
# Awaiting the fetch fixed the I/O half of this route; the translation that
# turns raw payloads into Model objects stayed inline and remained CPU-bound.
# Both CPU slices must run off the loop thread, and repeat requests must not
# redo the work at all.

async def test_openrouter_translation_runs_off_the_loop_thread():
    seen: list[threading.Thread] = []

    def record(raw):
        seen.append(threading.current_thread())
        return []

    with patch.object(model_catalog, "get_openrouter_models", AsyncMock(return_value=[{"id": "x"}])), \
         patch.object(model_catalog, "get_openrouter_models_sync", _boom_sync), \
         patch.object(model_catalog, "_translate_openrouter_all", record):
        await model_catalog.list_openrouter_models_async()

    assert seen, "translation never ran"
    assert seen[0] is not threading.main_thread(), \
        "OpenRouter translation ran on the event loop thread"


async def test_litellm_slice_runs_off_the_loop_thread():
    seen: list[threading.Thread] = []

    def record():
        seen.append(threading.current_thread())
        return []

    with patch.object(model_catalog, "get_openrouter_models", AsyncMock(return_value=[])), \
         patch.object(model_catalog, "get_openrouter_models_sync", _boom_sync), \
         patch.object(model_catalog, "list_opencode_zen_models_async", AsyncMock(return_value=[])), \
         patch.object(model_catalog, "list_litellm_models", record):
        await model_catalog.list_all_models_async()

    assert seen, "litellm slice never ran"
    assert seen[0] is not threading.main_thread(), \
        "litellm catalog walk ran on the event loop thread"


async def test_route_serves_repeat_requests_from_cache():
    response = MagicMock()
    response.headers = {}
    with patch.object(models_routes, "list_all_models_async", AsyncMock(return_value=[])) as agg:
        first = await models_routes.list_models(response)
        second = await models_routes.list_models(response)

    agg.assert_awaited_once()  # the second request rebuilt nothing
    assert first == second == {"models": [], "count": 0}


async def test_route_payload_serialization_runs_off_the_loop_thread():
    response = MagicMock()
    response.headers = {}
    seen: list[threading.Thread] = []
    real_build = models_routes._build_payload

    def record(models):
        seen.append(threading.current_thread())
        return real_build(models)

    with patch.object(models_routes, "list_all_models_async", AsyncMock(return_value=[])), \
         patch.object(models_routes, "_build_payload", record):
        await models_routes.list_models(response)

    assert seen, "payload was never built"
    assert seen[0] is not threading.main_thread(), \
        "response body serialization ran on the event loop thread"
