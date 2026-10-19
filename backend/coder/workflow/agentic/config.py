"""Operator-controlled configuration for the community workflow builder."""

from dataclasses import dataclass, field
from typing import List, Optional

from ..builder_config import (
    BRAIN_PROVIDER_ORDER,
    ModelCallConfig,
    model_call_config,
    resolve_brain_fallback_model,
    resolve_brain_model,
)


@dataclass
class AgenticBuilderConfig:
    """Models and safety limits for conversational workflow generation."""

    # Resolved per run, so a key saved while the instance runs is used at once.
    brain_model: str = field(default_factory=resolve_brain_model)
    brain_provider_order: Optional[List[str]] = field(
        default_factory=lambda: list(BRAIN_PROVIDER_ORDER)
    )
    brain_provider_sort: Optional[str] = None
    brain_fallback_model: Optional[str] = field(default_factory=resolve_brain_fallback_model)
    brain_fallback_provider_order: Optional[List[str]] = None

    node_drafter: ModelCallConfig = field(
        default_factory=lambda: model_call_config(temperature=0.2, timeout=120)
    )
    max_turns: int = 25
    brain_temperature: float = 0.3
    brain_timeout: int = 120
    max_ops_per_turn_soft: int = 20
    max_ops_per_turn_kill: int = 25


DEFAULT_AGENTIC_CONFIG = AgenticBuilderConfig()
