"""
MCP Server Node for workflow automation.

Connects to external MCP (Model Context Protocol) servers and exposes their tools
to AI Agent nodes. This enables agents to use tools from any MCP-compatible server
(e.g., brave-search, filesystem, database tools) within workflows.
"""

import logging
from typing import Dict, Any, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# MCP Server Credentials Schema
# ============================================================================

class MCPServerCredentials(BaseModel):
    """Credentials for authenticating with MCP servers.

    Supports both API key and OAuth authentication. For OAuth, the access_token
    is fetched from the stored credential and passed at execution time.
    """
    auth_type: Literal['none', 'api_key', 'oauth'] = Field(
        default='none',
        title="Authentication Type",
        description="Authentication type: none, api_key, or oauth"
    )
    # API Key authentication fields
    api_key: Optional[str] = Field(
        default=None,
        title="API Key",
        description="API key for authenticating with the MCP server"
    )
    custom_headers: Optional[Dict[str, str]] = Field(
        default=None,
        title="Custom Headers",
        description="Additional HTTP headers to send with MCP requests"
    )
    # OAuth authentication fields
    oauth_credential_id: Optional[str] = Field(
        default=None,
        title="OAuth Credential ID",
        description="ID of the stored OAuth credential"
    )
    oauth_server_url: Optional[str] = Field(
        default=None,
        title="OAuth Server URL",
        description="The MCP server URL this OAuth credential is for"
    )
    # Populated at execution time from stored OAuth credential
    access_token: Optional[str] = Field(
        default=None,
        title="Access Token",
        description="OAuth access token (populated at execution time)"
    )


# ============================================================================
# MCP Server Configuration
# ============================================================================

class MCPServerConfig(BaseModel):
    """Configuration for connecting to an MCP server.

    Two either-or modes, resolved at execute time from the wiring:
    - EXTERNAL: ``server_url`` set, no bottom-wired providers — discovers and
      proxies the external server's tools (the original behavior).
    - HOSTING: tool-provider nodes wired into the bottom handle, no
      ``server_url`` — aggregates their allowlisted operations into one named
      tool bundle (and optionally serves it externally via a hosted link).
    """
    server_url: Optional[str] = Field(
        default=None,
        title="Server URL",
        description="URL of an external MCP server endpoint. Leave empty when hosting: wire tool nodes into the bottom handle instead.",
        json_schema_extra={"placeholder": "https://api.example.com/mcp"}
    )
    transport_type: Literal['shttp', 'sse'] = Field(
        default='shttp',
        title="Transport Type",
        description="MCP transport protocol (shttp for Streamable HTTP, sse for Server-Sent Events)"
    )
    tool_prefix: Optional[str] = Field(
        default=None,
        title="Tool Prefix",
        description="Prefix to add to all tool names from this server (helps avoid name conflicts)",
        json_schema_extra={"placeholder": "brave_"}
    )
    tool_filter: Optional[List[str]] = Field(
        default=None,
        title="Tool Filter",
        description="List of tool names to include (empty = include all tools)"
    )


class MCPServerNodeConfig(NodeConfig[MCPServerConfig, MCPServerCredentials]):
    """Full configuration for MCP Server node including optional credentials."""

    @model_validator(mode='before')
    @classmethod
    def transform_flat_config(cls, data: Any) -> Any:
        """
        Transform flat frontend config data into nested structure.

        Frontend sends config fields at root level (e.g., server_url, transport_type),
        but NodeConfig expects nested structure (config: {...}, credentials: {...}).
        This validator detects flat data and wraps it appropriately.

        Also handles OAuth credential data from the database which has access_token
        but no auth_type field - we infer auth_type='oauth' from the presence of
        access_token.
        """
        if not isinstance(data, dict):
            return data

        # If already has nested 'config', check if credentials need auth_type inference
        if 'config' in data:
            credentials = data.get('credentials')
            if credentials and isinstance(credentials, dict):
                # Infer auth_type from credential data structure
                if credentials.get('access_token') and not credentials.get('auth_type'):
                    # Has access_token but no auth_type -> OAuth credential from database
                    credentials['auth_type'] = 'oauth'
                    logger.info(f"[MCPServerNodeConfig] Inferred auth_type='oauth' from access_token presence")
                elif credentials.get('api_key') and not credentials.get('auth_type'):
                    # Has api_key but no auth_type -> API key credential
                    credentials['auth_type'] = 'api_key'
            return data

        # Detect flat structure by looking for config fields at root level
        config_fields = {'server_url', 'transport_type', 'tool_prefix', 'tool_filter'}
        if any(field in data for field in config_fields):
            # Extract config fields
            config_data = {}
            credentials_data = {}
            remaining = {}

            for key, value in data.items():
                if key in config_fields:
                    config_data[key] = value
                elif key in {'auth_type', 'api_key', 'custom_headers', 'oauth_credential_id', 'oauth_server_url', 'access_token', 'refresh_token', 'token_type', 'expires_at', 'scope', 'token_endpoint', 'client_id', 'resource_url'}:
                    credentials_data[key] = value
                else:
                    # Keep other fields (like configValid, credentialIds) in remaining
                    remaining[key] = value

            # Build nested structure
            result = {'config': config_data}
            if credentials_data:
                # Infer auth_type from credential data structure
                if credentials_data.get('access_token') and not credentials_data.get('auth_type'):
                    credentials_data['auth_type'] = 'oauth'
                    logger.info(f"[MCPServerNodeConfig] Inferred auth_type='oauth' from access_token presence (flat)")
                elif credentials_data.get('api_key') and not credentials_data.get('auth_type'):
                    credentials_data['auth_type'] = 'api_key'
                result['credentials'] = credentials_data

            return result

        return data


# ============================================================================
# MCP Server Node Implementation
# ============================================================================

class MCPServerNode(WorkflowNode):
    """
    MCP Server node for connecting to external MCP servers.

    This node discovers tools from an MCP server and outputs tool definitions
    that can be collected by AI Agent nodes. When the agent calls one of these
    tools, the agent executes it via the MCP protocol.

    The node connects to the MCP server at execution time to discover available
    tools, then outputs their definitions in a format the Agent can use.
    """

    edit_examples = [
        "Change server URL to a new endpoint",
        "Switch transport type to SSE",
        "Add API key authentication",
        "Set up OAuth token for authentication",
        "Filter tools by name prefix",
        "Add custom headers for the request",
        "Restrict available tools for this agent",
    ]

    @classmethod
    def get_config_model(cls) -> type:
        """Get Pydantic config model for MCP Server node."""
        return MCPServerNodeConfig


    async def _discover_tools(self, config: MCPServerConfig, credentials: Optional[MCPServerCredentials]) -> List[Dict[str, Any]]:
        """Connect to the MCP server and return its tools' definitions.

        Each tool's ``mcp_server_config`` is a signed reference to how the server signs in, never the token, key or
        headers: the definitions are this step's output, saved and read back by people and models. Discovery signs
        in through the same reference an agent's calls resolve (``nodes.agent.mcp_auth``), an OAuth token refreshed
        first through the refresh choke point.
        """
        from coder.openai_agent.mcp import discover_tools as mcp_discover_tools
        from nodes.agent import mcp_auth

        reference = mcp_auth.reference(
            workflow_id=self.workflow_id, step_id=self.node_id, url=config.server_url,
            transport_type=config.transport_type, credential_id=(self.node_data or {}).get('credential_id'),
            step=credentials,
        )
        logger.info(f"[MCPServerNode] Signing in to {config.server_url}: {reference.get('auth') or 'none'}")
        raw_tools = await mcp_discover_tools(await mcp_auth.server_config(
            reference, workflow_id=self.workflow_id, step_id=self.node_id, user_id=self.user_id,
            organization_id=self.organization_id, step=credentials,
        ))

        tools: List[Dict[str, Any]] = []
        for raw in raw_tools:
            tool_name = raw['name']

            if config.tool_filter and tool_name not in config.tool_filter:
                continue

            prefixed_name = (
                f"{config.tool_prefix}{tool_name}" if config.tool_prefix else tool_name
            )

            parameters: List[Dict[str, Any]] = []
            input_schema = raw.get('inputSchema') or {}
            if isinstance(input_schema, dict):
                properties = input_schema.get('properties', {})
                required = input_schema.get('required', [])
                for param_name, param_schema in properties.items():
                    parameters.append({
                        'name': param_name,
                        'type': param_schema.get('type', 'string'),
                        'description': param_schema.get('description', f"Parameter: {param_name}"),
                        'required': param_name in required,
                        'default': param_schema.get('default'),
                    })

            tools.append({
                'type': 'tool_definition',
                'tool_type': 'mcp',
                'tool_name': prefixed_name,
                'original_tool_name': tool_name,
                'tool_description': raw.get('description') or f"MCP tool: {tool_name}",
                'parameters': parameters,
                'mcp_server_config': reference,
            })

            logger.info(f"[MCPServerNode] Discovered tool: {prefixed_name}")

        return tools

    @staticmethod
    def collect_provider_bundle(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Bundle entries from bottom-wired provider outputs in *inputs*.

        Each entry is the provider's node_op_tool_provider output plus its
        node_id (the inputs key), the shape AgentNode._collect_node_op_provider
        and the hosted endpoint both consume. Shared with the hosted-link
        resolver so the external tool list can't drift from the in-workflow one.
        """
        providers = []
        for provider_id, output in inputs.items():
            if isinstance(output, dict) and output.get('type') == 'node_op_tool_provider':
                providers.append({**output, 'node_id': provider_id})
        return providers

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the MCP Server node in one of two either-or modes:

        HOSTING — provider nodes wired into the bottom handle (their
        node_op_tool_provider outputs arrive in *inputs*): aggregate them into
        one bundle for downstream agents. No external connection is made.

        EXTERNAL — ``server_url`` configured: connect, discover tools, and
        output their definitions for the Agent node to collect.
        """
        logger.info(f"[MCPServerNode] Executing node {self.node_id}")

        if not self.config or not isinstance(self.config, MCPServerNodeConfig):
            return {'error': 'MCP Server node has no valid configuration'}

        config = self.config.config
        credentials = self.config.credentials

        providers = self.collect_provider_bundle(inputs)
        server_url = (config.server_url or '').strip()

        if providers:
            # Either-or is enforced at wiring time (canvas + both DSLs); a
            # legacy combo resolves hosting-wins with a loud error instead of
            # silently picking a side.
            if server_url:
                return {
                    'type': 'node_op_tool_provider_bundle',
                    'error': (
                        'MCP node has BOTH a server_url and tool nodes wired into its '
                        'bottom handle — these modes are either-or. Clear server_url to '
                        'host the wired tools, or remove the wired tools to proxy the '
                        'external server.'
                    ),
                    'providers': [],
                    'provider_count': 0,
                }
            tool_count = sum(len(p.get('allowed_operations') or []) for p in providers)
            logger.info(
                f"[MCPServerNode] Hosting mode: bundling {len(providers)} provider(s), "
                f"{tool_count} allowlisted operation(s)"
            )
            return {
                'type': 'node_op_tool_provider_bundle',
                'server_name': config.tool_prefix.rstrip('_') if config.tool_prefix else 'mcp_server',
                'provider_count': len(providers),
                'tool_count': tool_count,
                'providers': providers,
            }

        if not server_url:
            return {
                'type': 'mcp_tool_definitions',
                'error': (
                    'MCP node has no server_url and no tool nodes wired into its bottom '
                    'handle. Set server_url to connect to an external MCP server, or '
                    'wire tool nodes in to host them.'
                ),
                'tool_count': 0,
                'tools': [],
            }

        try:
            # Discover tools from the external MCP server
            tools = await self._discover_tools(config, credentials)

            logger.info(f"[MCPServerNode] Discovered {len(tools)} tools from {server_url}")

            # Return in a format that Agent node can collect
            return {
                'type': 'mcp_tool_definitions',
                'server_name': config.tool_prefix.rstrip('_') if config.tool_prefix else 'mcp_server',
                'server_url': server_url,
                'tool_count': len(tools),
                'tools': tools,
            }

        except Exception as e:
            logger.error(f"[MCPServerNode] Error: {e}", exc_info=True)
            return {
                'type': 'mcp_tool_definitions',
                'error': str(e),
                'server_url': server_url,
                'tool_count': 0,
                'tools': [],
            }
