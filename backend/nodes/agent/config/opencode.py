"""OpenCode CLI agent config."""

from typing import Literal
from pydantic import Field

from .base import BaseAgentFields
from ._cli_models_loader import harness_default_model


class OpenCodeConfig(BaseAgentFields):
    """Configuration for OpenCode multi-provider CLI agent."""
    model_type: Literal["opencode"] = Field(
        default="opencode",
        title="Model Type",
        json_schema_extra={"ui:hidden": True}
    )
    model: str = Field(
        default="opencode",
        title="Model",
        json_schema_extra={"ui:hidden": True}
    )
    opencode_model: str = Field(
        # Must be a model OpenCode runs today (opencode_model_refusal); Zen
        # rotates its free tier, and nodes/tests/test_opencode_default_model_live.py
        # fails daily once this one goes: change default_model in _cli_models.json.
        default=harness_default_model("opencode"),
        title="OpenCode Model",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "opencode_model",
                "placeholder": "Search models...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter provider/model ID",
            },
            "ui:show-if": {"field": "model", "contains": "opencode"},
        }
    )
