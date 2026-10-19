"""OpenCode Zen inference gateway — tier registry + cached catalog fetchers.

OpenCode Zen is an OpenAI-compatible inference provider (like OpenRouter) with
two tiers sharing one OPENCODE_API_KEY: the standard ``opencode/*`` catalog and
the ``opencode-go/*`` subscription catalog, each served from its own base URL
(models.dev providers/{opencode,opencode-go} ``api``). This module is the single
source for the tier → base-URL map and the two cached fetches every consumer
composes: the tier's live servable id set (its keyless ``/models`` endpoint —
models.dev is a historical superset that keeps rotated-out models) and the raw
models.dev catalog (metadata: names, cost, context, tool_call).

Consumers: the SDK LLM path's gateway routing (nodes/agent/config/providers.py),
the unified model catalog (utils/model_catalog.py), and registered OpenCode CLI model pickers.

Both fetches serve their last good copy when a refresh fails, and a source that
just failed isn't asked again for a minute, so a turn that checks its model
(``harness_model_lists.opencode_model_refusal``) never waits on the same outage
twice.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# tier id (the model-id prefix sans "/") → gateway base URL.
ZEN_TIER_BASE_URLS: Dict[str, str] = {
    "opencode": "https://opencode.ai/zen/v1",
    "opencode-go": "https://opencode.ai/zen/go/v1",
}

_FETCH_TIMEOUT_S = 15.0

# Zen rotates its free tier fast — keep the servable window short. The last
# successfully-fetched set is served on a transient failure so an outage never
# reverts consumers to offering the unservable models.dev superset.
_SERVABLE_TTL_S = 300
_servable_cache: Dict[str, Tuple[set, float]] = {}

_MODELS_DEV_URL = "https://models.dev/api.json"
_MODELS_DEV_TTL_S = 3600
_models_dev_cache: Optional[Tuple[Dict[str, Any], float]] = None

# A source that failed is not asked again for this long; its last good copy
# (or nothing) answers instead of every caller waiting out the same outage.
_RETRY_AFTER_FAILURE_S = 60
_failed_at: Dict[str, float] = {}


def _failed_recently(source: str) -> bool:
    at = _failed_at.get(source)
    return at is not None and time.time() - at < _RETRY_AFTER_FAILURE_S


def _record(source: str, ok: bool) -> None:
    if ok:
        _failed_at.pop(source, None)
    else:
        _failed_at[source] = time.time()


async def _get_json(url: str, timeout: Optional[float]) -> Any:
    """GET ``url`` as JSON within ``timeout`` seconds of wall clock (httpx's own
    timeout bounds each phase, not the whole request)."""
    import httpx

    limit = timeout or _FETCH_TIMEOUT_S

    async def _fetch() -> Any:
        async with httpx.AsyncClient(timeout=limit) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    return await asyncio.wait_for(_fetch(), limit)


def _get_json_sync(url: str) -> Any:
    import httpx

    resp = httpx.get(url, timeout=_FETCH_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _parse_servable(payload: Dict[str, Any]) -> set:
    return {m["id"] for m in payload.get("data", []) if m.get("id")}


def _cached_servable(tier: str, *, allow_stale: bool) -> Optional[set]:
    hit = _servable_cache.get(tier)
    if hit is None:
        return None
    ids, fetched_at = hit
    if allow_stale or (time.time() - fetched_at) < _SERVABLE_TTL_S:
        return ids
    return None


def _store_servable(tier: str, ids: set) -> None:
    _servable_cache[tier] = (ids, time.time())


def zen_models_url(tier: str) -> str:
    return f"{ZEN_TIER_BASE_URLS[tier]}/models"


async def get_zen_servable_ids(tier: str, *, timeout: Optional[float] = None) -> Optional[set]:
    """Live set of model ids the tier's gateway will actually serve.

    Cached briefly (Zen rotates fast). Returns the last good set when a fetch
    fails or failed within the last minute, or None if it was never read:
    callers decide how to degrade (typically: drop the tier rather than offer
    the superset). ``timeout`` bounds the whole fetch, in seconds.
    """
    cached = _cached_servable(tier, allow_stale=False)
    if cached is not None:
        return cached
    if _failed_recently(tier):
        return _cached_servable(tier, allow_stale=True)
    try:
        ids = _parse_servable(await _get_json(zen_models_url(tier), timeout))
    except Exception as e:
        logger.warning("[opencode_zen] servable fetch failed for %s: %r", tier, e)
        _record(tier, ok=False)
        return _cached_servable(tier, allow_stale=True)
    _record(tier, ok=True)
    _store_servable(tier, ids)
    return ids


def get_zen_servable_ids_sync(tier: str) -> Optional[set]:
    """Sync sibling of :func:`get_zen_servable_ids` (same cache) for callers
    already off the event loop (the model catalog's thread-offloaded path)."""
    cached = _cached_servable(tier, allow_stale=False)
    if cached is not None:
        return cached
    if _failed_recently(tier):
        return _cached_servable(tier, allow_stale=True)
    try:
        ids = _parse_servable(_get_json_sync(zen_models_url(tier)))
    except Exception as e:
        logger.warning("[opencode_zen] servable fetch failed for %s: %r", tier, e)
        _record(tier, ok=False)
        return _cached_servable(tier, allow_stale=True)
    _record(tier, ok=True)
    _store_servable(tier, ids)
    return ids


def _models_dev_fresh() -> Optional[Dict[str, Any]]:
    if _models_dev_cache and (time.time() - _models_dev_cache[1]) < _MODELS_DEV_TTL_S:
        return _models_dev_cache[0]
    return None


def _models_dev_after_failure(error: Optional[Exception]) -> Dict[str, Any]:
    """The last good catalog once a refresh failed; raises if there never was one."""
    if _models_dev_cache:
        return _models_dev_cache[0]
    raise RuntimeError(f"models.dev could not be read: {error!r}" if error else
                       "models.dev could not be read in the last minute")


def _store_models_dev(data: Dict[str, Any]) -> Dict[str, Any]:
    global _models_dev_cache
    _models_dev_cache = (data, time.time())
    _record(_MODELS_DEV_URL, ok=True)
    return data


async def fetch_models_dev(*, timeout: Optional[float] = None) -> Dict[str, Any]:
    """The raw models.dev catalog (cached 1h). A failed refresh serves the last
    good copy; with none it raises — callers own their degrade policy.
    ``timeout`` bounds the whole fetch, in seconds."""
    fresh = _models_dev_fresh()
    if fresh is not None:
        return fresh
    if _failed_recently(_MODELS_DEV_URL):
        return _models_dev_after_failure(None)
    try:
        data = await _get_json(_MODELS_DEV_URL, timeout)
    except Exception as e:
        logger.warning("[opencode_zen] models.dev fetch failed: %r", e)
        _record(_MODELS_DEV_URL, ok=False)
        return _models_dev_after_failure(e)
    return _store_models_dev(data)


def read_models_dev_cache() -> Optional[Dict[str, Any]]:
    """The last models.dev catalog read, whatever its age, without reading it
    again; None before the first read."""
    return _models_dev_cache[0] if _models_dev_cache else None


def fetch_models_dev_sync() -> Dict[str, Any]:
    """Sync sibling of :func:`fetch_models_dev` (same cache)."""
    fresh = _models_dev_fresh()
    if fresh is not None:
        return fresh
    if _failed_recently(_MODELS_DEV_URL):
        return _models_dev_after_failure(None)
    try:
        data = _get_json_sync(_MODELS_DEV_URL)
    except Exception as e:
        logger.warning("[opencode_zen] models.dev fetch failed: %r", e)
        _record(_MODELS_DEV_URL, ok=False)
        return _models_dev_after_failure(e)
    return _store_models_dev(data)
