"""
Tests for the MCP Server node implementation.

These tests verify the MCPServerNode configuration, tool discovery,
and output format. Uses mocking to avoid requiring actual MCP servers.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nodes.mcp_server_node import (
    MCPServerNode,
    MCPServerConfig,
    MCPServerCredentials,
    MCPServerNodeConfig,
)


class TestMCPServerConfig:
    """Test MCPServerConfig Pydantic model."""

    def test_minimal_config(self):
        """Should accept minimal config with just server_url."""
        config = MCPServerConfig(server_url="https://api.example.com/mcp")
        assert config.server_url == "https://api.example.com/mcp"
        assert config.transport_type == "shttp"  # Default
        assert config.tool_prefix is None
        assert config.tool_filter is None

    def test_full_config(self):
        """Should accept all fields."""
        config = MCPServerConfig(
            server_url="https://api.example.com/mcp",
            transport_type="sse",
            tool_prefix="brave_",
            tool_filter=["search", "news"]
        )
        assert config.server_url == "https://api.example.com/mcp"
        assert config.transport_type == "sse"
        assert config.tool_prefix == "brave_"
        assert config.tool_filter == ["search", "news"]

    def test_server_url_optional(self):
        """server_url is optional: a hosting-mode node (tool providers wired
        into its bottom handle) has no external server. The no-url-no-providers
        case errors at execute time instead (see TestHostingMode)."""
        config = MCPServerConfig()
        assert config.server_url is None


class TestMCPServerCredentials:
    """Test MCPServerCredentials Pydantic model."""

    def test_empty_credentials(self):
        """Should allow empty credentials."""
        creds = MCPServerCredentials()
        assert creds.api_key is None
        assert creds.custom_headers is None

    def test_full_credentials(self):
        """Should accept all credential fields."""
        creds = MCPServerCredentials(
            api_key="sk-test-123",
            custom_headers={"X-Custom": "value"}
        )
        assert creds.api_key == "sk-test-123"
        assert creds.custom_headers == {"X-Custom": "value"}


class TestMCPServerNodeConfig:
    """Test the full node config model."""

    def test_config_with_nested_config(self):
        """Should properly nest the config."""
        node_config = MCPServerNodeConfig(
            config=MCPServerConfig(server_url="https://example.com/mcp"),
            credentials=MCPServerCredentials(api_key="test-key")
        )
        assert node_config.config.server_url == "https://example.com/mcp"
        assert node_config.credentials.api_key == "test-key"

    def test_config_schema_generation(self):
        """Should generate valid JSON schema."""
        schema = MCPServerNodeConfig.model_json_schema()
        assert 'properties' in schema


class TestMCPServerNodeExecution:
    """Test the execute method."""

    @pytest.mark.asyncio
    async def test_execute_outputs_tool_definitions(self):
        """Should output discovered tool definitions."""
        # The MCP discovery path now goes through coder.openai_agent.mcp.discover_tools
        # which returns plain dicts (name/description/inputSchema). MCPServerNode
        # transforms those into the wire-format tool_definitions downstream.
        discovered = [{
            "name": "web_search",
            "description": "Search the web",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        }]

        with patch(
            'coder.openai_agent.mcp.discover_tools',
            new_callable=AsyncMock,
        ) as mock_discover:
            mock_discover.return_value = discovered

            node_config = MCPServerNodeConfig(
                config=MCPServerConfig(
                    server_url="https://api.example.com/mcp",
                    tool_prefix="brave_"
                ),
                credentials=MCPServerCredentials(api_key="test-key")
            )

            node = MCPServerNode(
                node_id='mcp_node_1',
                node_type='mcp-server',
                node_data={},
                config=node_config,
                sio=None,
                sid=None,
                workflow_id='wf_123'
            )

            result = await node.execute({})

            # Verify output structure
            assert result['type'] == 'mcp_tool_definitions'
            assert result['server_url'] == 'https://api.example.com/mcp'
            assert result['tool_count'] == 1
            assert len(result['tools']) == 1

            # Verify tool definition
            tool = result['tools'][0]
            assert tool['type'] == 'tool_definition'
            assert tool['tool_type'] == 'mcp'
            assert tool['tool_name'] == 'brave_web_search'  # Prefixed
            assert tool['original_tool_name'] == 'web_search'
            assert tool['tool_description'] == 'Search the web'
            assert len(tool['parameters']) == 1
            assert tool['parameters'][0]['name'] == 'query'
            assert tool['parameters'][0]['type'] == 'string'
            assert tool['parameters'][0]['required'] is True

            # Verify mcp_server_config is included
            assert 'mcp_server_config' in tool
            assert tool['mcp_server_config']['url'] == 'https://api.example.com/mcp'
            assert tool['mcp_server_config']['api_key'] == 'test-key'

    @pytest.mark.asyncio
    async def test_execute_applies_tool_filter(self):
        """Should filter tools based on tool_filter config."""
        discovered = [
            {"name": "search", "description": "Search",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "other", "description": "Other",
             "inputSchema": {"type": "object", "properties": {}}},
        ]

        with patch(
            'coder.openai_agent.mcp.discover_tools',
            new_callable=AsyncMock,
        ) as mock_discover:
            mock_discover.return_value = discovered

            node_config = MCPServerNodeConfig(
                config=MCPServerConfig(
                    server_url="https://api.example.com/mcp",
                    tool_filter=["search"]  # Only include "search"
                )
            )

            node = MCPServerNode(
                node_id='mcp_node_1',
                node_type='mcp-server',
                node_data={},
                config=node_config,
                sio=None,
                sid=None,
                workflow_id='wf_123'
            )

            result = await node.execute({})

            # Should only have the filtered tool
            assert result['tool_count'] == 1
            assert len(result['tools']) == 1
            assert result['tools'][0]['tool_name'] == 'search'

    @pytest.mark.asyncio
    async def test_execute_handles_connection_error(self):
        """Should handle connection errors gracefully."""
        with patch(
            'coder.openai_agent.mcp.discover_tools',
            new_callable=AsyncMock,
        ) as mock_discover:
            mock_discover.side_effect = Exception("Connection refused")

            node_config = MCPServerNodeConfig(
                config=MCPServerConfig(server_url="https://api.example.com/mcp")
            )

            node = MCPServerNode(
                node_id='mcp_node_1',
                node_type='mcp-server',
                node_data={},
                config=node_config,
                sio=None,
                sid=None,
                workflow_id='wf_123'
            )

            result = await node.execute({})

            # Should return error info
            assert result['type'] == 'mcp_tool_definitions'
            assert 'error' in result
            assert 'Connection refused' in result['error']
            assert result['tool_count'] == 0
            assert result['tools'] == []

    @pytest.mark.asyncio
    async def test_execute_without_config(self):
        """Should return error when no config provided."""
        node = MCPServerNode(
            node_id='mcp_node_1',
            node_type='mcp-server',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='wf_123'
        )

        result = await node.execute({})

        assert 'error' in result


class TestMCPServerNodeRegistration:
    """Test node registration in registry."""

    def test_node_is_registered(self):
        """Should be registered in NODE_REGISTRY."""
        from nodes.core.registry import NODE_REGISTRY
        assert 'mcp-server' in NODE_REGISTRY
        assert NODE_REGISTRY['mcp-server'] == MCPServerNode

    def test_config_model_available(self):
        """Should return config model."""
        model = MCPServerNode.get_config_model()
        assert model == MCPServerNodeConfig
