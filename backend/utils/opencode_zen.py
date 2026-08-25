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
"""

from __future__ import annotations

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


async def get_zen_servable_ids(tier: str) -> Optional[set]:
    """Live set of model ids the tier's gateway will actually serve.

    Cached briefly (Zen rotates fast). Returns the last good set on a
    transient fetch failure, or None if never fetched — callers decide how
    to degrade (typically: drop the tier rather than offer the superset).
    """
    cached = _cached_servable(tier, allow_stale=False)
    if cached is not None:
        return cached

    import httpx
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S) as client:
            resp = await client.get(zen_models_url(tier))
            resp.raise_for_status()
            ids = _parse_servable(resp.json())
        _store_servable(tier, ids)
        return ids
    except Exception as e:
        logger.warning("[opencode_zen] servable fetch failed for %s: %s", tier, e)
        return _cached_servable(tier, allow_stale=True)


def get_zen_servable_ids_sync(tier: str) -> Optional[set]:
    """Sync sibling of :func:`get_zen_servable_ids` (same cache) for callers
    already off the event loop (the model catalog's thread-offloaded path)."""
    cached = _cached_servable(tier, allow_stale=False)
    if cached is not None:
        return cached

    import httpx
    try:
        resp = httpx.get(zen_models_url(tier), timeout=_FETCH_TIMEOUT_S)
        resp.raise_for_status()
        ids = _parse_servable(resp.json())
        _store_servable(tier, ids)
        return ids
    except Exception as e:
        logger.warning("[opencode_zen] servable fetch failed for %s: %s", tier, e)
        return _cached_servable(tier, allow_stale=True)


async def fetch_models_dev() -> Dict[str, Any]:
    """The raw models.dev catalog (cached 1h). Raises on a fetch failure with
    nothing cached — callers own their degrade policy."""
    global _models_dev_cache
    if _models_dev_cache and (time.time() - _models_dev_cache[1]) < _MODELS_DEV_TTL_S:
        return _models_dev_cache[0]

    import httpx
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S) as client:
        resp = await client.get(_MODELS_DEV_URL)
        resp.raise_for_status()
        data = resp.json()
    _models_dev_cache = (data, time.time())
    return data


def fetch_models_dev_sync() -> Dict[str, Any]:
    """Sync sibling of :func:`fetch_models_dev` (same cache)."""
    global _models_dev_cache
    if _models_dev_cache and (time.time() - _models_dev_cache[1]) < _MODELS_DEV_TTL_S:
        return _models_dev_cache[0]

    import httpx
    resp = httpx.get(_MODELS_DEV_URL, timeout=_FETCH_TIMEOUT_S)
    resp.raise_for_status()
    data = resp.json()
    _models_dev_cache = (data, time.time())
    return data
