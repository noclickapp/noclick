"""Codex CLI agent config."""

from typing import Literal
from pydantic import Field

from .base import BaseAgentFields
from ._cli_models_loader import harness_default_model


class CodexConfig(BaseAgentFields):
    """Configuration for OpenAI Codex CLI agent."""
    model_type: Literal["codex"] = Field(
        default="codex",
        title="Model Type",
        json_schema_extra={"ui:hidden": True}
    )
    model: str = Field(
        default="codex",
        title="Model",
        json_schema_extra={"ui:hidden": True}
    )
    codex_model: str = Field(
        default=harness_default_model("codex"),
        title="Codex Model",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "codex_model",
                "placeholder": "Search Codex models...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a model id",
            },
            "ui:show-if": {"field": "model", "contains": "codex"},
        }
    )
