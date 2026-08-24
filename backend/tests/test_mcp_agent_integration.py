"""
Integration tests for MCP Server Node + Agent Node tool collection.

Tests that the Agent node can properly collect tool definitions from
an MCP Server node and recognize them for execution.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nodes.mcp_server_node import (
    MCPServerNode,
    MCPServerConfig,
    MCPServerCredentials,
    MCPServerNodeConfig,
)
from nodes.agent_node import AgentNode, AgentConfig, AgentNodeConfig
from nodes.agent.tool_execution import _execute_mcp_tool


def _wired(tool_params):
    """User-wired tools only — upload_file is ambient on every SDK agent."""
    return [p for p in tool_params if p["function"]["name"] != "upload_file"]


def _wired_cfg(tool_configs):
    return {k: v for k, v in tool_configs.items() if k != "upload_file"}


class TestMCPAgentIntegration:
    """Test that Agent node can collect and use MCP tools."""

    @pytest.mark.asyncio
    async def test_agent_collects_mcp_tool_definitions(self):
        """Agent should collect tool definitions from MCP Server node output."""
        # Simulate MCP Server node output
        mcp_server_output = {
            'type': 'mcp_tool_definitions',
            'server_name': 'test_server',
            'server_url': 'https://api.example.com/mcp',
            'tool_count': 2,
            'tools': [
                {
                    'type': 'tool_definition',
                    'tool_type': 'mcp',
                    'tool_name': 'brave_web_search',
                    'original_tool_name': 'web_search',
                    'tool_description': 'Search the web using Brave',
                    'parameters': [
                        {'name': 'query', 'type': 'string', 'description': 'Search query', 'required': True}
                    ],
                    'mcp_server_config': {
                        'url': 'https://api.example.com/mcp',
                        'api_key': 'test-key',
                        'transport_type': 'shttp',
                    }
                },
                {
                    'type': 'tool_definition',
                    'tool_type': 'mcp',
                    'tool_name': 'brave_news_search',
                    'original_tool_name': 'news_search',
                    'tool_description': 'Search news using Brave',
                    'parameters': [
                        {'name': 'query', 'type': 'string', 'description': 'News query', 'required': True},
                        {'name': 'count', 'type': 'number', 'description': 'Number of results', 'required': False}
                    ],
                    'mcp_server_config': {
                        'url': 'https://api.example.com/mcp',
                        'api_key': 'test-key',
                        'transport_type': 'shttp',
                    }
                }
            ]
        }

        # Create Agent node (no config needed for this test)
        agent = AgentNode(
            node_id='agent_1',
            node_type='agent',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='test_wf'
        )

        # Collect tool definitions
        inputs = {'mcp_server_1': mcp_server_output}
        tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)

        # Verify tools were collected
        assert len(_wired(tool_params)) == 2
        assert len(_wired_cfg(tool_configs)) == 2

        # Verify first tool
        assert tool_configs['brave_web_search']['tool_type'] == 'mcp'
        assert tool_configs['brave_web_search']['original_tool_name'] == 'web_search'
        assert tool_configs['brave_web_search']['mcp_server_config']['url'] == 'https://api.example.com/mcp'

        # Verify second tool
        assert tool_configs['brave_news_search']['tool_type'] == 'mcp'
        assert tool_configs['brave_news_search']['original_tool_name'] == 'news_search'

        # Verify tool params have correct structure for LLM
        tool_names = [t['function']['name'] for t in _wired(tool_params)]
        assert 'brave_web_search' in tool_names
        assert 'brave_news_search' in tool_names

    @pytest.mark.asyncio
    async def test_agent_collects_mixed_tool_types(self):
        """Agent should collect both MCP and workflow tools."""
        # MCP tool output
        mcp_output = {
            'type': 'mcp_tool_definitions',
            'tools': [
                {
                    'type': 'tool_definition',
                    'tool_type': 'mcp',
                    'tool_name': 'mcp_search',
                    'original_tool_name': 'search',
                    'tool_description': 'MCP search tool',
                    'parameters': [],
                    'mcp_server_config': {'url': 'https://example.com/mcp'}
                }
            ]
        }

        # Workflow tool output (from ToolNode)
        workflow_output = {
            'type': 'tool_definition',
            'tool_type': 'workflow',
            'tool_name': 'workflow_tool',
            'tool_description': 'Workflow tool',
            'parameters': []
        }

        agent = AgentNode(
            node_id='agent_1',
            node_type='agent',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='test_wf'
        )

        inputs = {
            'mcp_node': mcp_output,
            'tool_node': workflow_output
        }
        tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)

        # Should have both tools
        assert len(_wired(tool_params)) == 2
        assert len(_wired_cfg(tool_configs)) == 2

        # Verify types are different
        assert tool_configs['mcp_search']['tool_type'] == 'mcp'
        assert tool_configs['workflow_tool']['tool_type'] == 'workflow'

    @pytest.mark.asyncio
    async def test_agent_execute_mcp_tool_routing(self):
        """Agent should route MCP tools to _execute_mcp_tool."""
        agent = AgentNode(
            node_id='agent_1',
            node_type='agent',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='test_wf'
        )

        tool_configs = {
            'mcp_tool': {
                'tool_type': 'mcp',
                'original_tool_name': 'original_tool',
                'mcp_server_config': {
                    'url': 'https://example.com/mcp',
                    'transport_type': 'shttp'
                }
            }
        }

        # Mock the MCP execution at module level
        with patch('nodes.agent.tool_execution._execute_mcp_tool', new_callable=AsyncMock) as mock_mcp:
            mock_mcp.return_value = {'success': True, 'result': 'test result'}

            result = await agent._execute_tool('mcp_tool', {'arg': 'value'}, tool_configs)

            mock_mcp.assert_called_once_with(
                agent,
                'mcp_tool',
                {'arg': 'value'},
                tool_configs['mcp_tool']
            )
            assert result['success'] is True

    @pytest.mark.asyncio
    async def test_agent_execute_workflow_tool_routing(self):
        """Agent should route workflow tools to _execute_workflow_tool."""
        agent = AgentNode(
            node_id='agent_1',
            node_type='agent',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='test_wf'
        )

        tool_configs = {
            'workflow_tool': {
                'tool_type': 'workflow',
                'node_id': 'tool_node_1'
            }
        }

        # Mock the workflow execution at module level
        with patch('nodes.agent.tool_execution._execute_workflow_tool', new_callable=AsyncMock) as mock_workflow:
            mock_workflow.return_value = {'success': True, 'result': 'workflow result'}

            result = await agent._execute_tool('workflow_tool', {'arg': 'value'}, tool_configs)

            mock_workflow.assert_called_once_with(
                agent,
                'workflow_tool',
                {'arg': 'value'},
                tool_configs['workflow_tool']
            )
            assert result['success'] is True


class TestMCPToolExecution:
    """Test MCP tool execution via Agent node."""

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_success(self):
        """Should successfully execute MCP tool via OpenHands utilities."""
        agent = AgentNode(
            node_id='agent_1',
            node_type='agent',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='test_wf'
        )

        tool_info = {
            'tool_type': 'mcp',
            'original_tool_name': 'web_search',
            'mcp_server_config': {
                'url': 'https://api.example.com/mcp',
                'api_key': 'test-key',
                'transport_type': 'shttp'
            }
        }

        # The MCP execution path now goes through coder.openai_agent.mcp.call_tool
        # which returns the {success, result|error} envelope directly. Lifecycle
        # is owned by the helper — no per-client cleanup loop to verify here.
        with patch(
            'coder.openai_agent.mcp.call_tool', new_callable=AsyncMock,
        ) as mock_call:
            mock_call.return_value = {"success": True, "result": "Search results here"}

            result = await _execute_mcp_tool(
                agent,
                'brave_web_search',
                {'query': 'test search'},
                tool_info
            )

            # Verify the helper was called with the original (unprefixed) name
            # and the right arguments.
            mock_call.assert_called_once()
            args, _ = mock_call.call_args
            server_config, tool_name, arguments = args
            assert tool_name == 'web_search'  # Original name, not prefixed
            assert arguments == {'query': 'test search'}
            # Server config dict shape (api_key/oauth flattened by tool_execution)
            assert server_config['url'] == 'https://api.example.com/mcp'
            assert server_config['transport_type'] == 'shttp'
            assert server_config['api_key'] == 'test-key'

            # Verify result envelope
            assert result['success'] is True
            assert result['result'] == 'Search results here'

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_missing_config(self):
        """Should return error when MCP server config is missing."""
        agent = AgentNode(
            node_id='agent_1',
            node_type='agent',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='test_wf'
        )

        tool_info = {
            'tool_type': 'mcp',
            'original_tool_name': 'web_search',
            # Missing mcp_server_config
        }

        result = await _execute_mcp_tool(agent, 'test_tool', {}, tool_info)

        assert result['success'] is False
        assert 'no MCP server configuration' in result['error']
