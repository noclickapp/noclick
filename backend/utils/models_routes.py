"""
Public model catalog endpoint.

Returns the unified model list (OpenRouter + LiteLLM + static stragglers)
that powers the backend resolver registry. Phase 2 of the model-catalog
migration (see docs/model-catalog-migration.md): the frontend currently
fetches OpenRouter + LiteLLM directly via separate hooks, which means two
parallel translation paths. After this endpoint is live, phase 3 migrates
the frontend to consume it instead, and the FE translators get retired —
leaving a single source of truth in ``utils/model_catalog.py``.

The endpoint is unauthenticated and CDN-cacheable: it returns only
provider + model metadata, no user data.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from cachetools import TTLCache
from fastapi import APIRouter, Response

from utils.model_catalog import Model, list_all_models_async


router = APIRouter(prefix="/api/models", tags=["models"])

# The rendered response body, cached for the same window this route already
# advertises as `s-maxage`. The catalog runs to ~3,250 models, so building and
# serializing it is seconds of CPU; without this every request repeated the
# whole thing. Payload is provider metadata only (no user data), so one
# process-wide entry serves everyone.
_PAYLOAD_TTL_S = 600
_payload_cache: TTLCache = TTLCache(maxsize=1, ttl=_PAYLOAD_TTL_S)
_PAYLOAD_KEY = "payload"


def _serialize(model: Model) -> dict:
    """Map the Python Model dataclass to the JSON shape the FE expects.

    Mirrors ``frontend/app/types/model.tsx`` (the Model interface) — keys
    use snake_case for arrays (input_modalities / output_modalities) to
    match the existing FE schema, and capabilities is flattened to camelCase
    flags to match the existing useModels.ts consumers.
    """
    cap = model.capabilities
    return {
        "id": model.id,
        "provider": model.provider,
        "name": model.name,
        "description": model.description,
        "input_modalities": list(model.input_modalities),
        "output_modalities": list(model.output_modalities),
        "capabilities": {
            "imageAnalysis": cap.image_analysis,
            "imageGeneration": cap.image_generation,
            "reasoning": cap.reasoning,
            "tools": cap.tools,
            "videoGeneration": cap.video_generation,
        },
        "source": model.source,
        "created": model.created,
        "free": model.free,
    }


def _build_payload(models: list[Model]) -> dict:
    """Render the response body. Pure CPU over the whole catalog, so callers
    run it off the event loop."""
    return {"models": [_serialize(m) for m in models], "count": len(models)}


@router.get("")
@router.get("/")
async def list_models(response: Response) -> dict:
    """List the unified model catalog.

    The list is built in-process from the OpenRouter API (10-min TTL cache
    in ``utils/openrouter_models.py``) plus ``litellm.model_cost`` plus a
    small static block for CLI agents and Kling. Same call the resolver's
    LazyOptionRegistry uses, so backend and frontend always see the same
    snapshot.

    Served from ``_payload_cache`` when warm. On a miss the aggregator awaits
    its network slices and every remaining CPU step runs off-thread, so a
    cold request can never stall co-resident socket traffic.
    """
    payload = _payload_cache.get(_PAYLOAD_KEY)
    if payload is None:
        models = await list_all_models_async()
        payload = await asyncio.to_thread(_build_payload, models)
        _payload_cache[_PAYLOAD_KEY] = payload

    response.headers["Cache-Control"] = (
        f"public, s-maxage={_PAYLOAD_TTL_S}, stale-while-revalidate=120"
    )
    return payload
