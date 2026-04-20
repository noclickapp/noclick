"""
Agent node package — modular architecture for AI agent handlers.

Config classes are available directly from this package.
AgentNode is imported from nodes.agent_node (not here, to avoid circular imports).
"""

from nodes.agent.config import (
    AgentConfig,
    AgentCredentials,
    AgentNodeConfig,
    get_provider_credentials,
    PROVIDER_REQUIRED_CREDENTIALS,
)

__all__ = [
    'AgentConfig',
    'AgentCredentials',
    'AgentNodeConfig',
    'get_provider_credentials',
    'PROVIDER_REQUIRED_CREDENTIALS',
]
