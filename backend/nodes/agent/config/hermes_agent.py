"""
Hermes Agent CLI config.
Config model for the NousResearch Hermes Agent CLI sandbox — a general-purpose
agent with 68+ built-in tools (web search, browser automation, code execution, etc.).
"""

from typing import Literal
from pydantic import Field

from .base import BaseAgentFields
from ._cli_models_loader import harness_default_model


class HermesAgentConfig(BaseAgentFields):
    """Configuration for NousResearch Hermes Agent CLI sandbox."""
    model_type: Literal["hermes_agent"] = Field(
        default="hermes_agent",
        title="Model Type",
        json_schema_extra={"ui:hidden": True}
    )
    model: str = Field(
        default="hermes",
        title="Model",
        json_schema_extra={"ui:hidden": True}
    )
    hermes_agent_model: str = Field(
        default=harness_default_model("hermes"),
        title="Model",
        description=(
            "LLM to run inside Hermes Agent. Must support tool/function calling. "
            "Use chat models (e.g. claude-3.5-sonnet, gpt-4o, hermes-3-70b) — "
            "reasoning models like DeepSeek R1 do not support tool use."
        ),
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "hermes_agent_model",
                "placeholder": "Search models...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "e.g. openrouter/nousresearch/hermes-4-70b",
            },
            "ui:show-if": {"field": "model", "contains": "hermes"},
        }
    )
    max_iterations: int = Field(
        default=50,
        ge=1,
        le=200,
        title="Max Iterations",
        description="Maximum number of tool-calling iterations per run.",
        json_schema_extra={
            "ui:category": "Advanced",
            "ui:show-if": {"field": "model", "contains": "hermes"},
        }
    )
    enable_browser: str = Field(
        default="false",
        title="Enable Browser Tools",
        description=(
            "Enable Playwright browser automation (browser_navigate, browser_click, etc.). "
            "Requires a larger container build."
        ),
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes — enable Playwright browser", "No — text/code tools only"],
            "x-enum-searchable": True,
            "ui:category": "Advanced",
            "ui:show-if": {"field": "model", "contains": "hermes"},
        }
    )
