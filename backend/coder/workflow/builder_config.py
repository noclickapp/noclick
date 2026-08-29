"""Operator-controlled model settings for the community workflow builder.

The open build uses one generic configuration shape for each independent model
call. Installation operators choose the primary and optional fallback model
and may register another node drafter when they need different behavior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from nodes.agent.config.providers import get_provider_credentials


def _model(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name, "").strip()
    return value or default


def resolve_brain_model() -> str:
    """The builder's model for a run starting now.

    WORKFLOW_BUILDER_MODEL wins. Otherwise the default follows the key the
    instance actually has, so one OpenRouter key saved in Settings is enough
    to build with — and with no key at all the OpenRouter route is named,
    which is the key the builder then asks for inline.
    """
    configured = _model("WORKFLOW_BUILDER_MODEL")
    if configured:
        return configured
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return "openrouter/openai/gpt-5-mini"
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "openai/gpt-5-mini"
    return "openrouter/openai/gpt-5-mini"


def missing_brain_key(model: str) -> Optional[Tuple[str, str]]:
    """(env_var, provider) the model needs and the environment lacks, else None."""
    env_vars, provider = get_provider_credentials(model)
    for name in env_vars:
        if not os.environ.get(name, "").strip():
            return name, provider
    return None


COMMUNITY_MODEL = resolve_brain_model()
COMMUNITY_FALLBACK_MODEL = _model("WORKFLOW_BUILDER_FALLBACK_MODEL")

BRAIN_PRIMARY_MODEL = COMMUNITY_MODEL
BRAIN_FALLBACK_MODEL = COMMUNITY_FALLBACK_MODEL
BRAIN_PROVIDER_ORDER: List[str] = []


@dataclass
class ModelCallConfig:
    """Model and provider preferences for one community-builder call."""

    model: str = BRAIN_PRIMARY_MODEL
    provider_order: Optional[List[str]] = None
    provider_sort: Optional[str] = None
    temperature: float = 0.3
    timeout: int = 60
    fallback_model: Optional[str] = BRAIN_FALLBACK_MODEL
    fallback_provider_order: Optional[List[str]] = None


def model_call_config(*, temperature: float = 0.3, timeout: int = 60) -> ModelCallConfig:
    """Build a model configuration from this installation's environment."""

    return ModelCallConfig(model=resolve_brain_model(), temperature=temperature, timeout=timeout)
