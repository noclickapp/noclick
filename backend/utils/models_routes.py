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

from dataclasses import asdict
from fastapi import APIRouter, Response

from utils.model_catalog import Model, list_all_models


router = APIRouter(prefix="/api/models", tags=["models"])


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
    }


@router.get("")
@router.get("/")
async def list_models(response: Response) -> dict:
    """List the unified model catalog.

    The list is built in-process from the OpenRouter API (10-min TTL cache
    in ``utils/openrouter_models.py``) plus ``litellm.model_cost`` plus a
    small static block for CLI agents and Kling. Same call the resolver's
    LazyOptionRegistry uses, so backend and frontend always see the same
    snapshot.
    """
    models = [_serialize(m) for m in list_all_models()]
    response.headers["Cache-Control"] = (
        "public, s-maxage=600, stale-while-revalidate=120"
    )
    return {"models": models, "count": len(models)}
