"""
Tests for NoClickNode — verifies tool discovery with standard MCP tool definitions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nodes.noclick_node import NoClickNode


class FakeMCPTool:
    """Mimics FastMCP's Tool object returned by get_tools()."""

    def __init__(self, name: str, description: str, input_schema: dict):
        self.name = name
        self.description = description
        self._input_schema = input_schema

    def to_mcp_tool(self):
        obj = MagicMock()
        obj.inputSchema = self._input_schema
        return obj


def _make_noclick_node(node_id="noclick-1", user_id="test-user-123", workflow_id="wf-abc"):
    return NoClickNode(
        node_id=node_id,
        node_type="noclick",
        node_data={},
        config=None,
        user_id=user_id,
        workflow_id=workflow_id,
    )


def _make_fake_tools():
    return {
        "list_workflows": FakeMCPTool(
            "list_workflows",
            "List user workflows",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["query"],
            },
        ),
        "create_workflow": FakeMCPTool(
            "create_workflow",
            "Create a new workflow",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name"},
                },
                "required": ["name"],
            },
        ),
        "open_workflow": FakeMCPTool(
            "open_workflow", "Open workflow in editor",
            {"type": "object", "properties": {}},
        ),
        "report_bug": FakeMCPTool(
            "report_bug", "Report a bug",
            {"type": "object", "properties": {}},
        ),
    }


def _make_fake_tools_with_workflow_id():
    return {
        "get_workflow": FakeMCPTool(
            "get_workflow", "Get workflow details",
            {"type": "object", "properties": {"workflow_id": {"type": "string", "description": "Workflow ID"}}, "required": ["workflow_id"]},
        ),
        "list_workflows": FakeMCPTool(
            "list_workflows", "List user workflows",
            {"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}}, "required": []},
        ),
        "create_workflow": FakeMCPTool(
            "create_workflow", "Create a new workflow",
            {"type": "object", "properties": {"name": {"type": "string", "description": "Name"}}, "required": ["name"]},
        ),
    }


@pytest.mark.asyncio
async def test_noclick_node_discovers_tools():
    """Should discover tools and filter excluded ones."""
    node = _make_noclick_node()
    mock_server = MagicMock()
    mock_server.mcp.get_tools = AsyncMock(return_value=_make_fake_tools())

    with patch("mcp_server.get_mcp_server", return_value=mock_server), \
         patch.object(node, "_issue_token", return_value="tok"), \
         patch.object(node, "_get_mcp_server_url", return_value="http://localhost:8000/mcp"):
        result = await node.execute({})

    assert result["type"] == "mcp_tool_definitions"
    assert result["tool_count"] == 2
    tool_names = {t["tool_name"] for t in result["tools"]}
    assert "noclick_list_workflows" in tool_names
    assert "noclick_create_workflow" in tool_names
    assert "noclick_open_workflow" not in tool_names
    assert "noclick_report_bug" not in tool_names


@pytest.mark.asyncio
async def test_noclick_node_produces_standard_mcp_tools():
    """Tool definitions should use standard 'mcp' tool_type with mcp_server_config."""
    node = _make_noclick_node()
    mock_server = MagicMock()
    mock_server.mcp.get_tools = AsyncMock(return_value=_make_fake_tools())

    with patch("mcp_server.get_mcp_server", return_value=mock_server), \
         patch.object(node, "_issue_token", return_value="test-jwt"), \
         patch.object(node, "_get_mcp_server_url", return_value="http://localhost:8000/mcp"):
        result = await node.execute({})

    tool = next(t for t in result["tools"] if t["tool_name"] == "noclick_list_workflows")
    assert tool["tool_type"] == "mcp"
    assert tool["original_tool_name"] == "list_workflows"
    assert tool["mcp_server_config"]["url"] == "http://localhost:8000/mcp"
    assert tool["mcp_server_config"]["access_token"] == "test-jwt"
    assert tool["mcp_server_config"]["auth_type"] == "oauth"
    assert tool["mcp_server_config"]["transport_type"] == "shttp"


@pytest.mark.asyncio
async def test_noclick_node_handles_no_server():
    """Should return error when MCP server is not initialized."""
    node = _make_noclick_node()

    with patch("mcp_server.get_mcp_server", return_value=None):
        result = await node.execute({})

    assert result["tool_count"] == 0
    assert "error" in result


@pytest.mark.asyncio
async def test_noclick_node_this_workflow_scope_filters_global_tools():
    """When scoped to this_workflow, global-only tools should be hidden."""
    node = NoClickNode(
        node_id="noclick-1", node_type="noclick",
        node_data={"scope": "this_workflow"},
        config=None, user_id="u1", workflow_id="wf-abc",
    )
    mock_server = MagicMock()
    mock_server.mcp.get_tools = AsyncMock(return_value=_make_fake_tools_with_workflow_id())

    with patch("mcp_server.get_mcp_server", return_value=mock_server), \
         patch.object(node, "_issue_token", return_value="tok"), \
         patch.object(node, "_get_mcp_server_url", return_value="http://localhost:8000/mcp"):
        result = await node.execute({})

    tool_names = {t["tool_name"] for t in result["tools"]}
    assert "noclick_get_workflow" in tool_names
    assert "noclick_list_workflows" not in tool_names
    assert "noclick_create_workflow" not in tool_names


@pytest.mark.asyncio
async def test_noclick_node_this_workflow_scope_hides_workflow_id_param():
    """When scoped, workflow_id param should be hidden from tool definitions."""
    node = NoClickNode(
        node_id="noclick-1", node_type="noclick",
        node_data={"scope": "this_workflow"},
        config=None, user_id="u1", workflow_id="wf-abc",
    )
    mock_server = MagicMock()
    mock_server.mcp.get_tools = AsyncMock(return_value=_make_fake_tools_with_workflow_id())

    with patch("mcp_server.get_mcp_server", return_value=mock_server), \
         patch.object(node, "_issue_token", return_value="tok"), \
         patch.object(node, "_get_mcp_server_url", return_value="http://localhost:8000/mcp"):
        result = await node.execute({})

    get_wf = next(t for t in result["tools"] if t["tool_name"] == "noclick_get_workflow")
    param_names = {p["name"] for p in get_wf["parameters"]}
    assert "workflow_id" not in param_names
