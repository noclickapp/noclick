"""OpenClaw CLI agent config."""

from typing import Literal

from pydantic import Field

from .base import BaseAgentFields
from ._cli_models_loader import harness_default_model


class OpenClawConfig(BaseAgentFields):
    """Configuration for the OpenClaw local CLI runtime."""

    model_type: Literal["openclaw"] = Field(
        default="openclaw",
        title="Model Type",
        json_schema_extra={"ui:hidden": True},
    )
    model: str = Field(
        default="openclaw",
        title="Model",
        json_schema_extra={"ui:hidden": True},
    )
    openclaw_model: str = Field(
        default=harness_default_model("openclaw"),
        title="Model",
        description=(
            "LLM to run inside OpenClaw. Use a tool-capable chat model in "
            "provider/model format, for example openrouter/anthropic/claude-sonnet-4-5."
        ),
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "openclaw_model",
                "placeholder": "Search models...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "e.g. openrouter/openai/gpt-5.4-mini",
            },
            "ui:show-if": {"field": "model", "contains": "openclaw"},
        },
    )
    timeout_seconds: int = Field(
        default=600,
        ge=0,
        le=3600,
        title="Timeout Seconds",
        description="Per-run OpenClaw timeout. Set 0 to disable the CLI timeout.",
        json_schema_extra={
            "ui:category": "Advanced",
            "ui:show-if": {"field": "model", "contains": "openclaw"},
        },
    )
