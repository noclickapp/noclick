"""Claude Code CLI agent config."""

from typing import Literal
from pydantic import Field

from .base import BaseAgentFields
from ._cli_models_loader import harness_default_model


class ClaudeCodeConfig(BaseAgentFields):
    """Configuration for Anthropic Claude Code CLI agent."""
    model_type: Literal["claude_code"] = Field(
        default="claude_code",
        title="Model Type",
        json_schema_extra={"ui:hidden": True}
    )
    model: str = Field(
        default="claude-code",
        title="Model",
        json_schema_extra={"ui:hidden": True}
    )
    claude_code_model: str = Field(
        default=harness_default_model("claude_code"),
        title="Claude Code Model",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "claude_code_model",
                "placeholder": "Search Claude Code models...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a pinned model id",
            },
            "ui:show-if": {"field": "model", "contains": "claude-code"},
        }
    )
