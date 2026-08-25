"""Operator-controlled model settings for the community workflow builder.

The open build uses one generic configuration shape for each independent model
call. Installation operators choose the primary and optional fallback model
and may register another node drafter when they need different behavior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional


def _model(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name, "").strip()
    return value or default


COMMUNITY_MODEL = _model("WORKFLOW_BUILDER_MODEL", "openai/gpt-5-mini")
COMMUNITY_FALLBACK_MODEL = _model("WORKFLOW_BUILDER_FALLBACK_MODEL")

BRAIN_PRIMARY_MODEL = COMMUNITY_MODEL or "openai/gpt-5-mini"
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

    return ModelCallConfig(temperature=temperature, timeout=timeout)
