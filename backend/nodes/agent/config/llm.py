"""LLM agent config — catch-all for standard LiteLLM models (OpenAI, Anthropic, etc.)."""

from typing import Literal
from pydantic import Field

from .base import BaseAgentFields

# Single source of truth for the agent node's default model. The whole stack
# derives from this one literal: the Pydantic default below (so node execution
# runs it), the generated agent.json schema (so the frontend canvas/chat read
# it back — see frontend/app/lib/agentChat.ts), and the agentic builder prompt
# (coder/workflow/agentic/prompts.py). Change it here, regen schemas, and also
# update any hand-owned examples and registered CLI model defaults kept in
# sync with the generated schema.
DEFAULT_LLM_AGENT_MODEL = "openrouter/openai/gpt-5.6-luna"


class LLMAgentConfig(BaseAgentFields):
    """Configuration for standard LLM models via the in-process LiteLLM-backed agent."""
    model_type: Literal["llm"] = Field(
        default="llm",
        title="Model Type",
        json_schema_extra={"ui:hidden": True}
    )
    model: str = Field(
        default=DEFAULT_LLM_AGENT_MODEL,
        title="Model",
        description="LLM model to use for processing",
        json_schema_extra={
            "x-queryable-enum": "models",
            "x-enum-hint": (
                "LiteLLM identifier (provider/model). Fuzzy input is auto-resolved "
                "to the closest registered model id."
            ),
            "x-dynamic-options": {
                "field_name": "model",
                "placeholder": "Select a model...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": f"Or type a model id (e.g. {DEFAULT_LLM_AGENT_MODEL})",
            },
        },
    )
