"""
Agent configuration — discriminated union of model-specific configs.

Each model type (LLM, image, video, codex, claude-code, opencode, kling)
has its own config class with only its relevant fields. Pydantic's
discriminated union validates the correct config based on model_type.
"""

from typing import Annotated, Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, Discriminator, Field, Tag, model_validator

from nodes.core.base import NodeConfig

from .base import BaseAgentFields, infer_model_type
from .llm import LLMAgentConfig
from .image import ImageConfig
from .video import VideoConfig
from .codex import CodexConfig
from .claude_code import ClaudeCodeConfig
from .opencode import OpenCodeConfig
from .openclaw import OpenClawConfig
from .kling import KlingConfig
from .hermes_agent import HermesAgentConfig
from .providers import (
    PROVIDER_REQUIRED_CREDENTIALS,
    WRAPPER_ID_BY_MODEL_TYPE,
    filter_provider_credential_env,
    get_provider_credentials,
    match_model_credential,
    model_credential_accepted_types,
    resolve_agent_cred_model,
)


# ============================================================================
# Credentials
# ============================================================================

class AgentCredentials(BaseModel):
    """
    Flexible credential storage for AI providers.

    Credentials are stored as environment variable name -> value pairs.
    The frontend determines which fields to show based on the selected model/provider.
    """
    credential_type: Literal["agent_api_key"] = Field("agent_api_key", json_schema_extra={"ui:hidden": True})
    credentials: Optional[Dict[str, str]] = Field(
        default=None,
        title="API Credentials",
        description="Provider credentials. The frontend renders fields dynamically based on selected model.",
        json_schema_extra={
            "ui:widget": "agent_credentials"
        }
    )

    @model_validator(mode='before')
    @classmethod
    def wrap_flat_credentials(cls, data: Any) -> Any:
        """Handle legacy flat credential format (no 'credentials' wrapper key)."""
        if isinstance(data, dict) and 'credentials' not in data:
            known_meta = {'credential_type'}
            env_vars = {k: v for k, v in data.items() if k not in known_meta and isinstance(v, str)}
            if env_vars:
                return {'credentials': env_vars, **{k: v for k, v in data.items() if k in known_meta}}
        return data


# The credentialIds key this bundle rides under. Non-primary: it never
# authenticates the agent itself, so utils.credentials.pick_credential_id skips it
# (see _NON_PRIMARY_CREDENTIAL_TYPES) and the model credential stays the primary.
AGENT_ENV_CREDENTIAL_TYPE = "agent_env"


class AgentEnvCredentials(BaseModel):
    """User-supplied environment variables for the agent's sandbox.

    Deliberately a CREDENTIAL and not a config field: a config field lands in
    the workflow graph blob, which syncs to collaborators over YJS and rides
    checkpoints, exports, share links and the AI builder's XML snapshot — all
    the wrong places for a Stripe key. As a credential the bundle is Fernet-
    encrypted at rest and reusable across agents.

    Kept separate from ``AgentCredentials`` (the model-provider key) on purpose:
    swapping model providers must not drag unrelated API keys along, and
    ``registered CLI runner.user_resource`` reads the provider credential as the BYOK
    billing signal — folding app secrets in there would silently reclassify
    platform-credit runs.
    """
    credential_type: Literal["agent_env"] = Field(
        AGENT_ENV_CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True}
    )
    env: Optional[Dict[str, str]] = Field(
        default=None,
        title="Environment Variables",
        description="NAME -> value pairs injected into the agent's sandbox shell.",
        json_schema_extra={"ui:widget": "agent_env"},
    )


# ============================================================================
# Discriminated Union
# ============================================================================

def _get_model_type_discriminator(data: Any) -> str:
    """Custom discriminator that infers model_type from model string if missing."""
    if isinstance(data, dict):
        data = infer_model_type(data)
        return data.get('model_type', 'llm')
    if hasattr(data, 'model_type'):
        return data.model_type
    return 'llm'


AgentConfig = Annotated[
    Union[
        Annotated[LLMAgentConfig, Tag('llm')],
        Annotated[ImageConfig, Tag('image')],
        Annotated[VideoConfig, Tag('video')],
        Annotated[CodexConfig, Tag('codex')],
        Annotated[ClaudeCodeConfig, Tag('claude_code')],
        Annotated[OpenCodeConfig, Tag('opencode')],
        Annotated[OpenClawConfig, Tag('openclaw')],
        Annotated[KlingConfig, Tag('kling')],
        Annotated[HermesAgentConfig, Tag('hermes_agent')],
    ],
    Discriminator(_get_model_type_discriminator),
]


class AgentNodeConfig(NodeConfig[AgentConfig, AgentCredentials]):
    """Full configuration for Agent node including optional credentials."""
    pass


# Re-export for convenience
__all__ = [
    'AGENT_ENV_CREDENTIAL_TYPE',
    'BaseAgentFields',
    'AgentConfig',
    'AgentCredentials',
    'AgentEnvCredentials',
    'AgentNodeConfig',
    'LLMAgentConfig',
    'ImageConfig',
    'VideoConfig',
    'CodexConfig',
    'ClaudeCodeConfig',
    'OpenCodeConfig',
    'OpenClawConfig',
    'KlingConfig',
    'HermesAgentConfig',
    'PROVIDER_REQUIRED_CREDENTIALS',
    'WRAPPER_ID_BY_MODEL_TYPE',
    'filter_provider_credential_env',
    'get_provider_credentials',
    'match_model_credential',
    'model_credential_accepted_types',
    'resolve_agent_cred_model',
    'infer_model_type',
]
