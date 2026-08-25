"""
Unified model catalog: live data from OpenRouter + LiteLLM + a small static
list of stragglers (CLI agents, Kling).

Single source of truth for model metadata across the platform. The frontend's
``useModels`` hook fetches this list via ``GET /api/models``; the backend's
option-registry resolver consumes it directly. The translators here started
as Python ports of the now-deleted FE hooks ``useOpenRouterModels.ts`` and
``useLiteLLMModels.ts`` — kept structurally aligned with the FE's ``Model``
interface so the JSON shape served by ``/api/models`` is the same one the FE
already understood.

See docs/model-catalog-migration.md for the migration history.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .openrouter_models import get_openrouter_models, get_openrouter_models_sync

logger = logging.getLogger(__name__)


# ── Video-gen pattern allowlist ──────────────────────────────────────────
# Mirrors frontend/app/config/videoGenerationModels.ts. Neither OpenRouter
# nor LiteLLM reliably tag video-gen models, so we keyword-match the id.
_VIDEO_GENERATION_PATTERNS: tuple[str, ...] = (
    "sora", "veo", "runway", "runwayml", "gen-3", "gen3", "gen-4", "gen4",
    "kling", "luma", "dream-machine", "pika", "hailuo", "seedance",
    "cogvideo", "hunyuan-video", "mochi", "ltx-video", "stable-video",
    "text-to-video", "image-to-video", "video-to-video", "video-generat",
)


def _is_video_generation_model(model_id: str) -> bool:
    lower = model_id.lower()
    return any(p in lower for p in _VIDEO_GENERATION_PATTERNS)


# ── Unified Model dataclass ──────────────────────────────────────────────
# Mirrors frontend/app/types/model.tsx (Model interface).

@dataclass
class Capabilities:
    image_analysis: bool = False
    image_generation: bool = False
    reasoning: bool = False
    tools: bool = False
    video_generation: bool = False


@dataclass
class Model:
    id: str
    provider: str                                  # litellm_provider string or "openrouter"
    name: Optional[str] = None                     # human-readable label (OR ships this)
    description: Optional[str] = None
    input_modalities: List[str] = field(default_factory=lambda: ["text"])
    output_modalities: List[str] = field(default_factory=lambda: ["text"])
    capabilities: Capabilities = field(default_factory=Capabilities)
    source: str = "static"                         # 'openrouter' | 'opencode-zen' | 'litellm' | 'static'
    # Unix epoch (seconds) when the model was first published. Only populated
    # for the OpenRouter source; other sources omit it. Used by the FE picker
    # to weight recency when matching free-form model queries.
    created: Optional[int] = None
    # Provider serves this model at $0 (per its own pricing data). Drives the
    # "Free" tag + search term in the FE model picker and the config-panel
    # dropdown label. Conservative: only set when the source EXPLICITLY prices
    # both input and output at zero — absent pricing means unknown, not free.
    free: bool = False


# ── OpenRouter translator ────────────────────────────────────────────────
# Originally a Python port of translateOpenRouterModel from
# frontend/app/hooks/useOpenRouterModels.ts (now deleted — FE consumes
# /api/models directly). Output shape stays aligned with the FE Model type.

def _openrouter_is_free(pricing: Any) -> bool:
    """OpenRouter prices as decimal strings ("0" on :free routes). Explicit
    zero on both prompt and completion = free; missing/unparseable = unknown."""
    if not isinstance(pricing, dict):
        return False
    try:
        return (
            "prompt" in pricing and "completion" in pricing
            and float(pricing["prompt"]) == 0
            and float(pricing["completion"]) == 0
        )
    except (TypeError, ValueError):
        return False


def _translate_openrouter(api_model: Dict[str, Any]) -> Model:
    arch = api_model.get("architecture") or {}
    input_modalities = arch.get("input_modalities") or ["text"]
    output_modalities = arch.get("output_modalities") or ["text"]
    supported_parameters = api_model.get("supported_parameters") or []
    or_id = api_model.get("id") or ""

    raw_created = api_model.get("created")
    created: Optional[int] = int(raw_created) if isinstance(raw_created, (int, float)) else None

    return Model(
        id=f"openrouter/{or_id}",
        provider="openrouter",
        name=api_model.get("name"),
        description=api_model.get("description"),
        input_modalities=list(input_modalities),
        output_modalities=list(output_modalities),
        capabilities=Capabilities(
            image_analysis="image" in input_modalities,
            image_generation="image" in output_modalities,
            reasoning="include_reasoning" in supported_parameters,
            tools="tools" in supported_parameters,
            video_generation=(
                "video" in output_modalities
                or _is_video_generation_model(or_id)
            ),
        ),
        source="openrouter",
        created=created,
        free=_openrouter_is_free(api_model.get("pricing")),
    )


def _translate_openrouter_all(raw: List[Dict[str, Any]]) -> List[Model]:
    """Translate a raw OpenRouter payload. Pure CPU — no I/O, so the async
    path can hand it to a worker thread."""
    return [_translate_openrouter(m) for m in raw]


def list_openrouter_models() -> List[Model]:
    """Return the live OpenRouter catalog as Model objects.

    Uses the existing 10-min TTL cache in utils/openrouter_models.py — first
    call fetches, subsequent calls are in-memory.
    """
    try:
        raw = get_openrouter_models_sync() or []
    except Exception as e:
        logger.warning(f"[model_catalog] OpenRouter fetch failed: {e}")
        return []
    return _translate_openrouter_all(raw)


async def list_openrouter_models_async() -> List[Model]:
    """Async sibling of :func:`list_openrouter_models`. Awaits the httpx-based
    cached fetch (``get_openrouter_models``) instead of the ``requests``-based
    ``get_openrouter_models_sync``, so an async caller (the ``/models`` route)
    never blocks the event loop on the catalog's SSL round-trip on cache miss.
    Shares the same 10-min TTL cache and translation as the sync path.

    The fetch was already off the loop; the translation was not. Building the
    ~340 Model objects is pure CPU, and on a contended container it was
    measured blocking the loop for 74s, so it runs off-thread too."""
    try:
        raw = await get_openrouter_models() or []
    except Exception as e:
        logger.warning(f"[model_catalog] OpenRouter fetch failed: {e}")
        return []
    return await asyncio.to_thread(_translate_openrouter_all, raw)


# ── LiteLLM translator ───────────────────────────────────────────────────
# Originally a Python port of translateLiteLLMModel from
# frontend/app/hooks/useLiteLLMModels.ts (now deleted — FE consumes
# /api/models directly). Skips deprecated / sample_spec entries.

def _determine_litellm_modalities(
    model_data: Dict[str, Any],
) -> tuple[List[str], List[str]]:
    """Determine input/output modalities from LiteLLM mode + supports_* flags."""
    input_modalities: List[str] = ["text"]
    output_modalities: List[str] = ["text"]

    if model_data.get("supports_vision"):
        input_modalities.append("image")
    if model_data.get("supports_audio_input"):
        input_modalities.append("audio")
    if model_data.get("supports_video_input"):
        input_modalities.append("video")
    if model_data.get("supports_pdf_input"):
        input_modalities.append("pdf")

    if model_data.get("supports_audio_output"):
        output_modalities.append("audio")

    mode = model_data.get("mode")
    if mode == "embedding":
        output_modalities[0:1] = ["embedding"]
    elif mode == "image_generation":
        output_modalities[0:1] = ["image"]
    elif mode == "audio_transcription":
        input_modalities.append("audio")
    elif mode == "audio_speech":
        output_modalities.append("audio")
    elif mode == "video_generation":
        output_modalities[0:1] = ["video"]
    elif mode == "moderation":
        output_modalities[0:1] = ["moderation"]

    return input_modalities, output_modalities


# Mirrors mapLiteLLMProvider() in frontend/app/hooks/useLiteLLMModels.ts.
# LiteLLM splits some providers into sub-models (vertex_ai-chat-models,
# vertex_ai-image-models, etc.); the FE consolidates them under the
# matching ModelProvider enum value. Doing the mapping here means the
# /api/models endpoint serves the same provider strings the FE already
# expects.
_LITELLM_PROVIDER_OVERRIDES: Dict[str, str] = {
    "vertex_ai-chat-models": "vertex_ai",
    "vertex_ai-text-models": "vertex_ai",
    "vertex_ai-embedding-models": "vertex_ai",
    "vertex_ai-image-models": "vertex_ai",
    "vertex_ai-language-models": "vertex_ai",
    "vertex_ai-vision-models": "vertex_ai",
    "vertex_ai-video-models": "vertex_ai",
    "vertex_ai-code-chat-models": "vertex_ai",
    "vertex_ai-code-text-models": "vertex_ai",
    "vertex_ai-anthropic_models": "vertex_ai",
    "vertex_ai-openai_models": "vertex_ai",
    "vertex_ai-mistral_models": "vertex_ai",
    "vertex_ai-llama_models": "vertex_ai",
    "vertex_ai-deepseek_models": "vertex_ai",
    "vertex_ai-qwen_models": "vertex_ai",
    "vertex_ai-ai21_models": "vertex_ai",
    "vertex_ai-minimax_models": "vertex_ai",
    "text-completion-openai": "openai",
    "cohere_chat": "cohere",
    "fireworks_ai-embedding-models": "fireworks_ai-embedding-models",
}


def _normalize_litellm_provider(litellm_provider: str) -> str:
    """Return the FE-canonical provider string for a litellm_provider value.

    Explicit overrides win first; otherwise any ``vertex_ai-<sub>`` family
    member collapses to ``vertex_ai`` (LiteLLM keeps adding sub-categories).
    """
    if litellm_provider in _LITELLM_PROVIDER_OVERRIDES:
        return _LITELLM_PROVIDER_OVERRIDES[litellm_provider]
    if litellm_provider.startswith("vertex_ai-"):
        return "vertex_ai"
    return litellm_provider


def _translate_litellm(model_id: str, api_model: Dict[str, Any]) -> Optional[Model]:
    if model_id == "sample_spec":
        return None
    if api_model.get("deprecation_date"):
        return None

    raw_provider = api_model.get("litellm_provider")
    if not raw_provider:
        return None
    provider = _normalize_litellm_provider(raw_provider)

    input_modalities, output_modalities = _determine_litellm_modalities(api_model)

    desc_parts: list[str] = []
    mode = api_model.get("mode")
    if mode and mode != "chat":
        desc_parts.append(f"Mode: {mode}.")
    if api_model.get("max_input_tokens"):
        desc_parts.append(f"Max input: {api_model['max_input_tokens']} tokens.")
    if api_model.get("max_output_tokens"):
        desc_parts.append(f"Max output: {api_model['max_output_tokens']} tokens.")
    description = " ".join(desc_parts).strip() or None

    return Model(
        id=model_id,
        provider=provider,
        name=None,
        description=description,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
        capabilities=Capabilities(
            image_analysis=bool(api_model.get("supports_vision"))
                            or "image" in input_modalities,
            image_generation="image" in output_modalities,
            reasoning=bool(api_model.get("supports_reasoning")),
            tools=bool(api_model.get("supports_function_calling")),
            video_generation=(
                "video" in output_modalities
                or _is_video_generation_model(model_id)
            ),
        ),
        source="litellm",
        # Deliberately never `free`: litellm's zero costs mean "unpriced here"
        # (rerank models, LoRA adapters), not a $0 serving commitment.
    )


def list_litellm_models() -> List[Model]:
    """Return LiteLLM's bundled catalog as Model objects.

    Reads ``litellm.model_cost`` directly — the dict is loaded into memory by
    the litellm package itself from the same JSON the FE fetches at runtime,
    so no network call is needed on the backend.
    """
    try:
        import litellm  # type: ignore
    except ImportError:
        logger.warning("[model_catalog] litellm not installed; skipping")
        return []

    raw = getattr(litellm, "model_cost", None) or {}
    out: List[Model] = []
    skipped_deprecated = 0
    for model_id, api_model in raw.items():
        if not isinstance(api_model, dict):
            continue
        if api_model.get("deprecation_date"):
            skipped_deprecated += 1
            continue
        m = _translate_litellm(model_id, api_model)
        if m is not None:
            out.append(m)
    logger.info(
        f"[model_catalog] LiteLLM: {len(out)} models loaded "
        f"(skipped {skipped_deprecated} deprecated)"
    )
    return out


# ── OpenCode Zen translator ──────────────────────────────────────────────
# OpenCode Zen/Go are OpenAI-compatible inference gateways (one shared
# OPENCODE_API_KEY; see utils/opencode_zen.py). Their models run on the
# in-process SDK LLM path — no sandbox — via the gateway routing in
# nodes/agent/config/providers.py:resolve_zen_gateway_route. Metadata comes
# from models.dev, filtered to each tier's live /models set (models.dev is a
# historical superset that keeps rotated-out models). provider is "opencode"
# for BOTH tiers — the FE resolves credential type catalog-first, and the two
# tiers share one credential (ModelProvider.OPENCODE fold).

_ZEN_TIER_LABELS: Dict[str, str] = {
    "opencode": "OpenCode Zen",
    "opencode-go": "OpenCode Go",
}


def _translate_zen_model(tier: str, model_id: str, meta: Dict[str, Any]) -> Optional[Model]:
    if not meta.get("tool_call", False):
        return None  # agents lean on tool calls; mirrors the CLI picker filter
    modalities = meta.get("modalities") or {}
    input_modalities = list(modalities.get("input") or ["text"])
    output_modalities = list(modalities.get("output") or ["text"])
    cost = meta.get("cost") or {}
    is_free = (
        "input" in cost and "output" in cost
        and not cost["input"] and not cost["output"]
    )

    desc_parts = [_ZEN_TIER_LABELS[tier]]
    ctx = (meta.get("limit") or {}).get("context") or 0
    if ctx:
        desc_parts.append(f"{ctx // 1000}K context")
    desc_parts.append(
        "Free" if is_free
        else f"${cost.get('input', 0)}/M in, ${cost.get('output', 0)}/M out"
    )
    return Model(
        id=f"{tier}/{model_id}",
        provider="opencode",
        name=meta.get("name") or model_id,
        description=" · ".join(desc_parts),
        input_modalities=input_modalities,
        output_modalities=output_modalities,
        capabilities=Capabilities(
            image_analysis="image" in input_modalities,
            reasoning=bool(meta.get("reasoning")),
            tools=True,
        ),
        source="opencode-zen",
        free=is_free,
    )


def _zen_tier_models(
    tier: str, catalog: Dict[str, Any], servable: Optional[set]
) -> List[Model]:
    if servable is None:
        # Never offer the models.dev superset unvalidated — a rotated-out
        # model fails at run time with an opaque gateway error.
        logger.warning(f"[model_catalog] no live servable set for {tier}; dropping tier")
        return []
    provider = catalog.get(tier) or {}
    out: List[Model] = []
    for model_id, meta in (provider.get("models") or {}).items():
        if model_id not in servable or not isinstance(meta, dict):
            continue
        m = _translate_zen_model(tier, model_id, meta)
        if m is not None:
            out.append(m)
    return out


def list_opencode_zen_models() -> List[Model]:
    """Return the live OpenCode Zen + Go catalogs as Model objects."""
    from .opencode_zen import (
        ZEN_TIER_BASE_URLS,
        fetch_models_dev_sync,
        get_zen_servable_ids_sync,
    )

    try:
        catalog = fetch_models_dev_sync()
    except Exception as e:
        logger.warning(f"[model_catalog] models.dev fetch failed: {e}")
        return []
    out: List[Model] = []
    for tier in ZEN_TIER_BASE_URLS:
        out.extend(_zen_tier_models(tier, catalog, get_zen_servable_ids_sync(tier)))
    return out


async def list_opencode_zen_models_async() -> List[Model]:
    """Async sibling of :func:`list_opencode_zen_models` (same caches)."""
    from .opencode_zen import (
        ZEN_TIER_BASE_URLS,
        fetch_models_dev,
        get_zen_servable_ids,
    )

    try:
        catalog = await fetch_models_dev()
    except Exception as e:
        logger.warning(f"[model_catalog] models.dev fetch failed: {e}")
        return []
    out: List[Model] = []
    for tier in ZEN_TIER_BASE_URLS:
        out.extend(_zen_tier_models(tier, catalog, await get_zen_servable_ids(tier)))
    return out


# ── Static stragglers ────────────────────────────────────────────────────
# Originally mirrored STATIC_MODELS + KLING_MODELS from the FE hooks; those
# are now deleted and this list is the only source. CLI agents and Kling
# aren't carried by OpenRouter or LiteLLM but are real options for the
# agent node's discriminated union, so they live here.

_STATIC_MODELS: List[Model] = [
    Model(
        id="codex",
        provider="codex",
        description="OpenAI Codex coding agent",
        input_modalities=["text"],
        output_modalities=["text"],
        capabilities=Capabilities(tools=True),
    ),
    Model(
        id="claude-code",
        provider="claude_code",
        description="Anthropic Claude Code coding agent",
        input_modalities=["text"],
        output_modalities=["text"],
        capabilities=Capabilities(tools=True),
    ),
    Model(
        id="opencode",
        provider="opencode",
        description="OpenCode multi-provider coding agent",
        input_modalities=["text"],
        output_modalities=["text"],
        capabilities=Capabilities(tools=True),
    ),
    Model(
        id="openclaw",
        provider="openclaw",
        description="OpenClaw embedded local agent runtime",
        input_modalities=["text"],
        output_modalities=["text"],
        capabilities=Capabilities(tools=True),
    ),
    Model(
        id="hermes",
        provider="hermes_agent",
        description="NousResearch Hermes Agent — general-purpose agent with 68+ built-in tools",
        input_modalities=["text"],
        output_modalities=["text"],
        capabilities=Capabilities(tools=True),
    ),
    # Kling — mirrors frontend/app/config/klingModels.ts. Kept in Python as a
    # static list because Kling isn't covered by OpenRouter or LiteLLM.
    Model(
        id="kling/kling-v3-omni",
        provider="kling",
        description="Latest Kling model with native audio + video. Text/image-to-video.",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        capabilities=Capabilities(video_generation=True),
    ),
    Model(
        id="kling/kling-v3",
        provider="kling",
        description="Kling V3 text/image-to-video.",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        capabilities=Capabilities(video_generation=True),
    ),
    Model(
        id="kling/kling-video-o1",
        provider="kling",
        description="Unified multimodal video model.",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        capabilities=Capabilities(video_generation=True),
    ),
    Model(
        id="kling/kling-v2-6",
        provider="kling",
        description="Native audio + motion control. 5s or 10s videos.",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        capabilities=Capabilities(video_generation=True),
    ),
    Model(
        id="kling/kling-v2-5-turbo",
        provider="kling",
        description="Fastest Kling video generation.",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        capabilities=Capabilities(video_generation=True),
    ),
    Model(
        id="kling/kling-v2-1-master",
        provider="kling",
        description="High quality master-tier video generation.",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        capabilities=Capabilities(video_generation=True),
    ),
    Model(
        id="kling/kling-v2-master",
        provider="kling",
        description="Kling V2 master tier — high-quality 'pro' video generation.",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        capabilities=Capabilities(video_generation=True),
    ),
    Model(
        id="kling/kling-v1-6",
        provider="kling",
        description="Camera control support. 5s or 10s videos.",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        capabilities=Capabilities(video_generation=True),
    ),
    Model(
        id="kling/kling-image-o1",
        provider="kling",
        description="Latest Kling image generation. Text-to-image and image-to-image.",
        input_modalities=["text", "image"],
        output_modalities=["image"],
        capabilities=Capabilities(image_generation=True),
    ),
    Model(
        id="kling/kling-v2-1-image",
        provider="kling",
        description="Kling V2.1 image generation. Text-to-image.",
        input_modalities=["text"],
        output_modalities=["image"],
        capabilities=Capabilities(image_generation=True),
    ),
    Model(
        id="kling/kling-v2-image",
        provider="kling",
        description="Kling V2 image generation.",
        input_modalities=["text", "image"],
        output_modalities=["image"],
        capabilities=Capabilities(image_generation=True),
    ),
]


def list_static_models() -> List[Model]:
    return list(_STATIC_MODELS)


# ── Aggregator ────────────────────────────────────────────────────────────

def list_all_models() -> List[Model]:
    """Return the unified live catalog: OpenRouter + OpenCode Zen/Go + LiteLLM
    + static stragglers.

    Order: OpenRouter first (the preferred default route), then the Zen
    gateways, then LiteLLM direct-provider entries (alternatives), then the
    static CLI / Kling list. Caller is responsible for resolving any same-id
    collisions if it cares.
    """
    return [
        *list_openrouter_models(),
        *list_opencode_zen_models(),
        *list_litellm_models(),
        *list_static_models(),
    ]


async def list_all_models_async() -> List[Model]:
    """Async sibling of :func:`list_all_models` for callers on the event loop
    (the ``/models`` route). The OpenRouter + Zen slices do network I/O, so
    they're the parts awaited; LiteLLM + static entries are in-memory and
    reused as-is. Same order and contents as the sync aggregator.

    "In-memory" is not "free": the LiteLLM slice walks every entry in
    ``litellm.model_cost`` (thousands) building Model objects, which blocked
    the loop for seconds per call, so it goes to a worker thread. The static
    slice is a list copy and stays inline."""
    return [
        *(await list_openrouter_models_async()),
        *(await list_opencode_zen_models_async()),
        *(await asyncio.to_thread(list_litellm_models)),
        *list_static_models(),
    ]
