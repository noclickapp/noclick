"""
Models registry — backed by the live unified catalog.

Pulls OpenRouter + LiteLLM + static stragglers via ``utils.model_catalog``,
converts each ``Model`` to an ``Option`` for the resolver. OpenRouter mirrors
are tagged ``preferred=True`` so fuzzy queries bias toward them; direct-provider
LiteLLM entries stay as alternatives. CLI agents (claude-code / codex /
opencode) and Kling remain in the static list because they aren't carried by
either upstream.

Phase 1 of the model-catalog migration (see docs/model-catalog-migration.md).
"""

from __future__ import annotations

import logging
from typing import List

from utils.model_catalog import Model, list_all_models

from .base import Option
from .lazy import LazyOptionRegistry

logger = logging.getLogger(__name__)


# ── Static fallback ──────────────────────────────────────────────────────
# Used only when the live catalog hasn't loaded yet. Just the CLI agents +
# a handful of Kling entries so the resolver can still route variant queries
# even with both upstreams down on cold start.

_STATIC_FALLBACK: tuple[Option, ...] = (
    Option(
        id="claude-code",
        label="Claude Code",
        description="Anthropic Claude Code CLI agent (variant chooses Opus/Sonnet/Haiku)",
        tags=("variant:claude_code", "provider:anthropic", "modality:text", "tools"),
        aliases=("anthropic claude code", "claude code cli"),
    ),
    Option(
        id="codex",
        label="OpenAI Codex",
        description="OpenAI Codex CLI agent (variant chooses GPT-5.x model)",
        tags=("variant:codex", "provider:openai", "modality:text", "tools"),
        aliases=("openai codex", "gpt codex"),
    ),
    Option(
        id="opencode",
        label="OpenCode",
        description="Multi-provider open-source coding agent",
        tags=("variant:opencode", "modality:text", "tools"),
    ),
    Option(
        id="kling/kling-v3",
        label="Kling V3",
        description="Kling V3 text/image-to-video",
        tags=("variant:kling", "provider:kling", "modality:video"),
        aliases=("kling", "kling v3"),
    ),
    Option(
        id="kling/kling-v2-master",
        label="Kling V2 Master",
        description="Kling V2 master tier — high-quality 'pro' video generation",
        tags=("variant:kling", "provider:kling", "modality:video"),
        aliases=("kling pro", "kling master"),
    ),
)


# ── Provider → variant mapping ───────────────────────────────────────────
# Drives the variant tag on each Option, which AgentConfig's
# ``infer_model_type`` discriminator reads to route into the right
# Pydantic union branch.

_CLI_PROVIDERS = {"claude_code", "codex", "opencode"}
_KLING_PROVIDERS = {"kling"}


def _variant_for(model: Model) -> str:
    """Pick the discriminator variant tag for a Model."""
    if model.provider in _CLI_PROVIDERS:
        return f"variant:{model.provider}"
    if model.provider in _KLING_PROVIDERS:
        return "variant:kling"
    # OpenRouter / LiteLLM models — variant follows output modality.
    if model.capabilities.video_generation or "video" in model.output_modalities:
        return "variant:video"
    if model.capabilities.image_generation or "image" in model.output_modalities:
        return "variant:image"
    return "variant:llm"


def _tags_for(model: Model) -> tuple[str, ...]:
    """Build the searchable tag tuple for an Option."""
    tags: list[str] = [_variant_for(model)]
    tags.append(f"provider:{model.provider}")
    if model.capabilities.tools:
        tags.append("tools")
    if model.capabilities.reasoning:
        tags.append("reasoning")
    if "text" in model.input_modalities:
        tags.append("modality:text")
    if "image" in model.output_modalities:
        tags.append("modality:image")
    if "video" in model.output_modalities:
        tags.append("modality:video")
    return tuple(tags)


def _label_for(model: Model) -> str:
    """Human-readable label. OpenRouter ships ``name``; otherwise fall back
    to the id."""
    if model.name:
        return model.name
    return model.id


def _description_for(model: Model) -> str:
    """Trim long descriptions to keep the alternatives block compact."""
    desc = (model.description or "").strip()
    if len(desc) > 200:
        return desc[:197] + "…"
    return desc


def _to_option(model: Model) -> Option:
    """Convert a unified Model into a registry Option.

    OpenRouter mirrors get ``preferred=True`` so the fuzzy resolver routes
    toward them by default, with direct-provider alternatives still surfaced
    in the alternatives column.
    """
    preferred = model.source == "openrouter"
    aliases = _ALIAS_OVERLAY.get(model.id, ())
    return Option(
        id=model.id,
        label=_label_for(model),
        description=_description_for(model),
        tags=_tags_for(model),
        aliases=aliases,
        preferred=preferred,
    )


# ── Alias overlay ────────────────────────────────────────────────────────
# Stable colloquial phrasings that fuzzy-matching alone routes wrong because
# they're short tokens that collide with other ids ("haiku" matching multiple
# Claude haiku versions, "kling pro" matching anything ending in "pro").
# Keys are canonical ids in the live catalog; values are aliases the resolver
# should treat as direct hits.
#
# This stays small on purpose — only well-known nicknames where the live id
# carries no signal of the colloquial phrasing. Version-specific aliases
# (e.g. "sonnet 4.6") are NOT here; they fuzzy-match the live id naturally.
_ALIAS_OVERLAY: dict[str, tuple[str, ...]] = {
    # Default Claude variants — point colloquial single-word queries at the
    # current generation rather than the oldest matching version.
    "openrouter/anthropic/claude-haiku-4.5": ("haiku", "claude haiku"),
    "openrouter/anthropic/claude-sonnet-4.6": ("sonnet", "claude sonnet"),
    "openrouter/anthropic/claude-opus-4.7": ("opus", "claude opus"),
    # Kling phrasings — the live ids ("kling/kling-v2-master") give no signal
    # that "pro" / "master" / "turbo" are tier nicknames.
    "kling/kling-v2-master": ("kling pro", "kling master"),
    "kling/kling-v2-5-turbo": ("kling turbo", "kling fast"),
    "kling/kling-v2-image": ("kling image",),
}


def _build_from_catalog() -> List[Option]:
    """Build the full options list from the live catalog.

    De-dupes by id, preferring the first source seen — list_all_models
    already orders OpenRouter → LiteLLM → static, so an OpenRouter mirror
    wins over a LiteLLM duplicate which wins over a static fallback.
    """
    seen: set[str] = set()
    options: list[Option] = []
    for m in list_all_models():
        if m.id in seen:
            continue
        seen.add(m.id)
        options.append(_to_option(m))
    return options


# ── The registry ─────────────────────────────────────────────────────────

_HINT = (
    "LiteLLM-style identifier (provider/model). Fuzzy input is resolved to "
    "the closest match against the live OpenRouter + LiteLLM catalogs. Write "
    "what the user said (e.g. `claude sonnet 4.6`, `opencode`, `flux pro`) — "
    "the registry will canonicalize. OpenRouter mirrors are the default "
    "route; pass an exact direct-provider id to bypass that. Coding-CLI ids "
    "(`claude-code`, `codex`, `opencode`) and Kling ids (`kling/...`) flip "
    "the active union branch."
)


MODELS_REGISTRY = LazyOptionRegistry(
    name="models",
    build=_build_from_catalog,
    hint=_HINT,
    ttl_seconds=600.0,           # 10 min — matches the OpenRouter cache TTL
    static_fallback=_STATIC_FALLBACK,
)
