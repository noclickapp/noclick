"""Catalog the node types that supply tools structurally, not by operation.

These nodes wire into an agent's bottom handle, but their tools do not come
from a Pydantic ``config.operation`` union.  Keeping this classification in
one backend module prevents the agentic builder from treating their UI config
as an executable operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class StructuralAgentToolProvider:
    """A node whose agent tools are emitted at runtime rather than selected.

    ``tool_definitions`` is present only when the node has a fixed tool
    surface.  Dynamic providers still belong here: their tool names depend on
    custom node configuration or a connected MCP server, so advertising made
    up config operations would be misleading.
    """

    node_type: str
    description: str
    tool_definitions: Optional[Callable[[], List[Dict[str, object]]]] = None


def _alarm_tools() -> List[Dict[str, object]]:
    from nodes.alarm_node import get_all_tool_definitions

    return get_all_tool_definitions()


def _filesystem_tools() -> List[Dict[str, object]]:
    from nodes.filesystem_node import get_upload_tool_definition

    return [get_upload_tool_definition()]


# This is deliberately declarative rather than inferred from a config schema:
# a structural provider's whole point is that its runtime tool surface is not a
# config-operation union.  The fixed definitions stay lazy so normal schema
# introspection does not import node implementations.
STRUCTURAL_AGENT_TOOL_PROVIDERS: tuple[StructuralAgentToolProvider, ...] = (
    StructuralAgentToolProvider(
        "tool",
        "Emits one custom workflow tool configured on the node (name, description, and parameters).",
    ),
    StructuralAgentToolProvider(
        "mcp-server",
        "Discovers tools from its configured external MCP server, or exposes hosted provider tools wired into it.",
    ),
    StructuralAgentToolProvider(
        "noclick",
        "Discovers the NoClick MCP tools available to the configured workflow scope.",
    ),
    StructuralAgentToolProvider(
        "alarm",
        "Provides the fixed native alarm-management tool surface.",
        _alarm_tools,
    ),
    StructuralAgentToolProvider(
        "filesystem",
        "Provides persistent sandbox storage and the fixed upload_file tool.",
        _filesystem_tools,
    ),
)

_BY_NODE_TYPE = {provider.node_type: provider for provider in STRUCTURAL_AGENT_TOOL_PROVIDERS}


def get_structural_agent_tool_provider(
    node_type: str,
) -> Optional[StructuralAgentToolProvider]:
    return _BY_NODE_TYPE.get(node_type)


def get_structural_agent_tool_definitions(node_type: str) -> List[Dict[str, object]]:
    """Return fixed definitions for a structural provider, if it has any."""
    provider = get_structural_agent_tool_provider(node_type)
    if not provider or not provider.tool_definitions:
        return []
    return provider.tool_definitions()


STRUCTURAL_AGENT_TOOL_TYPES = frozenset(_BY_NODE_TYPE)
