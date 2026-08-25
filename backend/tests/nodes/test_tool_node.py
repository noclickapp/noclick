"""
Tests for ToolNode tool definition functionality.

Tests cover:
- ToolNode outputs correct tool definition schema
- Tool definition has correct LiteLLM format for LLM function calling
- Parameter schema validation and defaults
- AgentNode collecting tool definitions from ToolNode outputs
"""

import pytest
from nodes.tool_node import ToolNode, ToolNodeConfig, ToolConfig, ToolParameter
from nodes.agent_node import AgentNode, AgentNodeConfig
from nodes.agent.config import LLMAgentConfig


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def simple_tool_config():
    """Create a simple tool configuration with one required parameter."""
    return ToolNodeConfig(
        config=ToolConfig(
            tool_name="search_database",
            tool_description="Search the database for records matching a query",
            parameters=[
                ToolParameter(name="query", type="string", description="Search query", required=True),
            ],
        ),
        credentials=None,
    )


@pytest.fixture
def complex_tool_config():
    """Create a tool configuration with multiple parameters including optional ones."""
    return ToolNodeConfig(
        config=ToolConfig(
            tool_name="get_weather",
            tool_description="Get current weather for a city",
            parameters=[
                ToolParameter(name="city", type="string", description="City name", required=True),
                ToolParameter(name="units", type="string", description="Temperature units", required=False, default="celsius"),
                ToolParameter(name="include_forecast", type="boolean", description="Include 5-day forecast", required=False, default=False),
            ],
        ),
        credentials=None,
    )


@pytest.fixture
def tool_node(simple_tool_config):
    """Create a ToolNode instance."""
    return ToolNode(
        node_id="tool-1",
        node_type="tool",
        node_data={"config": simple_tool_config.model_dump()},
        config=simple_tool_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


@pytest.fixture
def complex_tool_node(complex_tool_config):
    """Create a ToolNode with complex configuration."""
    return ToolNode(
        node_id="tool-weather",
        node_type="tool",
        node_data={"config": complex_tool_config.model_dump()},
        config=complex_tool_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


@pytest.fixture
def agent_node():
    """Create an AgentNode instance for testing tool collection."""
    agent_config = AgentNodeConfig(
        config=LLMAgentConfig(
            system_prompt="You are a helpful assistant",
            message="Hello",
            model="openrouter/openai/gpt-4o-mini",
            temperature=0.7,
        ),
        credentials=None,
    )
    return AgentNode(
        node_id="agent-1",
        node_type="agent",
        node_data={"config": agent_config.model_dump()},
        config=agent_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


# ============================================================================
# ToolNode Definition Tests
# ============================================================================

class TestToolNodeDefinition:
    """Unit tests for ToolNode tool definition output."""

    @pytest.mark.asyncio
    async def test_tool_node_outputs_definition(self, tool_node):
        """Test that ToolNode.execute() returns correct tool definition."""
        result = await tool_node.execute({})

        assert result["type"] == "tool_definition"
        assert result["tool_name"] == "search_database"
        assert result["tool_description"] == "Search the database for records matching a query"

    @pytest.mark.asyncio
    async def test_tool_node_includes_parameters(self, tool_node):
        """Test that tool definition includes parameter schema."""
        result = await tool_node.execute({})

        params = result["parameters"]
        assert len(params) == 1

        query_param = params[0]
        assert query_param["name"] == "query"
        assert query_param["type"] == "string"
        assert query_param["required"] is True

    @pytest.mark.asyncio
    async def test_tool_node_with_multiple_parameters(self, complex_tool_node):
        """Test tool definition with multiple parameters including optional ones."""
        result = await complex_tool_node.execute({})

        params = result["parameters"]
        assert len(params) == 3

        city_param = next(p for p in params if p["name"] == "city")
        assert city_param["type"] == "string"
        assert city_param["required"] is True

        units_param = next(p for p in params if p["name"] == "units")
        assert units_param["required"] is False
        assert units_param["default"] == "celsius"

        forecast_param = next(p for p in params if p["name"] == "include_forecast")
        assert forecast_param["type"] == "boolean"
        assert forecast_param["default"] is False


# ============================================================================
# LiteLLM Format Tests
# ============================================================================

class TestToolDefinitionLLMFormat:
    """Tests for LiteLLM-compatible tool definition format."""

    def test_tool_definition_has_correct_structure(self, tool_node):
        """Test that get_tool_definition() returns correct LiteLLM schema."""
        tool_param = tool_node.get_tool_definition()

        assert tool_param["type"] == "function"
        assert "function" in tool_param

    def test_tool_definition_function_fields(self, tool_node):
        """Test that function definition has correct fields."""
        tool_param = tool_node.get_tool_definition()
        func = tool_param["function"]

        assert func["name"] == "search_database"
        assert func["description"] == "Search the database for records matching a query"
        assert "parameters" in func

    def test_tool_definition_parameters_schema(self, tool_node):
        """Test that parameters follow JSON schema format."""
        tool_param = tool_node.get_tool_definition()
        params = tool_param["function"]["parameters"]

        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params

    def test_required_parameters_in_schema(self, tool_node):
        """Test that required parameters are listed correctly."""
        tool_param = tool_node.get_tool_definition()
        params = tool_param["function"]["parameters"]

        assert "query" in params["properties"]
        assert "query" in params["required"]

    def test_optional_parameters_not_in_required(self, complex_tool_node):
        """Test that optional parameters are not in required list."""
        tool_param = complex_tool_node.get_tool_definition()
        params = tool_param["function"]["parameters"]

        assert "city" in params["required"]
        assert "units" not in params["required"]
        assert "include_forecast" not in params["required"]

    def test_parameter_types_in_schema(self, complex_tool_node):
        """Test that parameter types are correctly specified."""
        tool_param = complex_tool_node.get_tool_definition()
        properties = tool_param["function"]["parameters"]["properties"]

        assert properties["city"]["type"] == "string"
        assert properties["units"]["type"] == "string"
        assert properties["include_forecast"]["type"] == "boolean"

    def test_parameter_descriptions_in_schema(self, complex_tool_node):
        """Test that parameter descriptions are included."""
        tool_param = complex_tool_node.get_tool_definition()
        properties = tool_param["function"]["parameters"]["properties"]

        assert properties["city"]["description"] == "City name"
        assert properties["units"]["description"] == "Temperature units"


# ============================================================================
# Tool Parameter Model Tests
# ============================================================================

class TestToolParameter:
    """Tests for ToolParameter Pydantic model."""

    def test_parameter_with_defaults(self):
        """Test that parameters have sensible defaults."""
        param = ToolParameter(name="test")

        assert param.type == "string"
        assert param.description == ""
        assert param.required is True
        assert param.default is None

    def test_parameter_types(self):
        """Test all valid parameter types."""
        valid_types = ["string", "number", "boolean", "object", "array"]

        for param_type in valid_types:
            param = ToolParameter(name="test", type=param_type)
            assert param.type == param_type

    def test_parameter_name_validation(self):
        """Test that parameter names must be valid identifiers."""
        # Valid names
        ToolParameter(name="valid_name")
        ToolParameter(name="validName123")
        ToolParameter(name="_private")

        # Invalid names should raise validation error
        with pytest.raises(ValueError):
            ToolParameter(name="123invalid")

        with pytest.raises(ValueError):
            ToolParameter(name="invalid-name")

        with pytest.raises(ValueError):
            ToolParameter(name="")


# ============================================================================
# Tool Config Validation Tests
# ============================================================================

class TestToolConfigValidation:
    """Tests for ToolConfig validation and automatic name sanitization."""

    def test_tool_name_sanitization_spaces(self):
        """Test that spaces in tool names are converted to underscores."""
        config = ToolConfig(tool_name="send message", tool_description="Test")
        assert config.tool_name == "send_message"

    def test_tool_name_sanitization_hyphens(self):
        """Test that hyphens in tool names are converted to underscores."""
        config = ToolConfig(tool_name="send-message", tool_description="Test")
        assert config.tool_name == "send_message"

    def test_tool_name_sanitization_mixed(self):
        """Test that mixed spaces and hyphens are handled."""
        config = ToolConfig(tool_name="send message-now", tool_description="Test")
        assert config.tool_name == "send_message_now"

    def test_tool_name_sanitization_special_chars(self):
        """Test that special characters are removed."""
        config = ToolConfig(tool_name="send@message!", tool_description="Test")
        assert config.tool_name == "sendmessage"

    def test_tool_name_sanitization_leading_number(self):
        """Test that leading numbers get an underscore prefix."""
        config = ToolConfig(tool_name="123tool", tool_description="Test")
        assert config.tool_name == "_123tool"

    def test_tool_name_sanitization_multiple_underscores(self):
        """Test that multiple consecutive underscores are collapsed."""
        config = ToolConfig(tool_name="send   message", tool_description="Test")
        assert config.tool_name == "send_message"

    def test_tool_name_valid_unchanged(self):
        """Test that valid tool names are not modified."""
        config = ToolConfig(tool_name="send_message", tool_description="Test")
        assert config.tool_name == "send_message"

        config2 = ToolConfig(tool_name="tool123", tool_description="Test")
        assert config2.tool_name == "tool123"

    def test_tool_name_validation_empty_after_sanitization(self):
        """Test that names that become empty after sanitization are rejected."""
        with pytest.raises(ValueError):
            ToolConfig(tool_name="@#$%", tool_description="Test")

    def test_tool_description_required(self):
        """Test that tool description is required."""
        with pytest.raises(ValueError):
            ToolConfig(tool_name="tool", tool_description="")

    def test_tool_with_no_parameters(self):
        """Test that tools can have no parameters."""
        config = ToolConfig(
            tool_name="simple_tool",
            tool_description="A tool with no parameters"
        )
        assert config.parameters == []


# ============================================================================
# Integration Tests
# ============================================================================

class TestToolNodeIntegration:
    """Integration tests for ToolNode in workflow context."""

    @pytest.mark.asyncio
    async def test_tool_output_can_be_collected_by_agent(self, complex_tool_node):
        """Test that tool output format is compatible with agent collection."""
        output = await complex_tool_node.execute({})

        # This is the format expected by AgentNode._collect_tool_definitions
        assert output["type"] == "tool_definition"
        assert "tool_name" in output
        assert "tool_description" in output
        assert "parameters" in output

        # Verify parameters can be converted to LLM format
        tool_def = complex_tool_node.get_tool_definition()
        assert tool_def["function"]["name"] == output["tool_name"]

    def test_tool_node_from_workflow_json(self):
        """Test creating ToolNode from workflow JSON structure."""
        workflow_node = {
            "id": "tool-search",
            "type": "tool",
            "position": {"x": 100, "y": 100},
            "data": {
                "config": {
                    "tool_name": "search_products",
                    "tool_description": "Search for products in catalog",
                    "parameters": [
                        {"name": "query", "type": "string", "description": "Search terms", "required": True},
                        {"name": "limit", "type": "number", "description": "Max results", "required": False, "default": 10},
                    ],
                },
            },
        }

        config = ToolNodeConfig(
            config=ToolConfig(**workflow_node["data"]["config"]),
            credentials=None,
        )

        node = ToolNode(
            node_id=workflow_node["id"],
            node_type=workflow_node["type"],
            node_data=workflow_node["data"],
            config=config,
            sio=None,
            sid=None,
            workflow_id="test",
        )

        tool_def = node.get_tool_definition()
        assert tool_def["function"]["name"] == "search_products"
        assert len(tool_def["function"]["parameters"]["properties"]) == 2

    @pytest.mark.asyncio
    async def test_multiple_tools_unique_names(self):
        """Test that multiple tools can coexist with different names."""
        configs = [
            ToolNodeConfig(
                config=ToolConfig(tool_name="tool_a", tool_description="First tool"),
                credentials=None,
            ),
            ToolNodeConfig(
                config=ToolConfig(tool_name="tool_b", tool_description="Second tool"),
                credentials=None,
            ),
        ]

        outputs = []
        for i, config in enumerate(configs):
            node = ToolNode(
                node_id=f"tool-{i}",
                node_type="tool",
                node_data={},
                config=config,
                sio=None,
                sid=None,
                workflow_id="test",
            )
            outputs.append(await node.execute({}))

        # Verify unique names
        names = [o["tool_name"] for o in outputs]
        assert names == ["tool_a", "tool_b"]
        assert len(set(names)) == 2


# ============================================================================
# AgentNode Tool Collection Tests
# ============================================================================

class TestAgentNodeToolCollection:
    """Tests for AgentNode collecting tool definitions from upstream ToolNodes."""

    @pytest.mark.asyncio
    async def test_agent_collects_single_tool_from_inputs(self, tool_node, agent_node):
        """Test that AgentNode._collect_tool_definitions finds tool in inputs."""
        # Execute tool node to get its output
        tool_output = await tool_node.execute({})

        # Simulate workflow execution - tool output is passed to agent in inputs
        inputs = {tool_node.node_id: tool_output}

        # Collect tool definitions
        tool_params, tool_configs, _ = agent_node._collect_tool_definitions(inputs)

        # Verify tool was collected
        assert len(tool_params) == 1
        assert tool_params[0]["type"] == "function"
        assert tool_params[0]["function"]["name"] == "search_database"

        # Verify tool config was captured
        assert "search_database" in tool_configs
        assert tool_configs["search_database"]["node_id"] == tool_node.node_id

    @pytest.mark.asyncio
    async def test_agent_collects_multiple_tools_from_inputs(self, complex_tool_node, agent_node):
        """Test that AgentNode collects multiple tools from different upstream nodes."""
        # Create two tools with different configurations
        tool1_config = ToolNodeConfig(
            config=ToolConfig(
                tool_name="send_message",
                tool_description="Send a message to a user",
                parameters=[
                    ToolParameter(name="message", type="string", description="The message", required=True),
                ],
            ),
            credentials=None,
        )
        tool1 = ToolNode(
            node_id="tool-message",
            node_type="tool",
            node_data={},
            config=tool1_config,
            sio=None,
            sid=None,
            workflow_id="test",
        )

        tool2_config = ToolNodeConfig(
            config=ToolConfig(
                tool_name="get_data",
                tool_description="Fetch data from API",
                parameters=[
                    ToolParameter(name="endpoint", type="string", description="API endpoint", required=True),
                    ToolParameter(name="limit", type="number", description="Max results", required=False),
                ],
            ),
            credentials=None,
        )
        tool2 = ToolNode(
            node_id="tool-data",
            node_type="tool",
            node_data={},
            config=tool2_config,
            sio=None,
            sid=None,
            workflow_id="test",
        )

        # Get outputs from both tools
        tool1_output = await tool1.execute({})
        tool2_output = await tool2.execute({})

        # Simulate workflow execution - both tool outputs in agent inputs
        inputs = {
            tool1.node_id: tool1_output,
            tool2.node_id: tool2_output,
        }

        # Collect tool definitions
        tool_params, tool_configs, _ = agent_node._collect_tool_definitions(inputs)

        # Verify both tools were collected
        assert len(tool_params) == 2
        tool_names = {tp["function"]["name"] for tp in tool_params}
        assert tool_names == {"send_message", "get_data"}

        # Verify both tool configs were captured
        assert "send_message" in tool_configs
        assert "get_data" in tool_configs

    @pytest.mark.asyncio
    async def test_agent_ignores_non_tool_inputs(self, tool_node, agent_node):
        """Test that AgentNode ignores inputs that are not tool definitions."""
        # Get tool output
        tool_output = await tool_node.execute({})

        # Simulate workflow with mixed inputs - tool + regular node outputs
        inputs = {
            tool_node.node_id: tool_output,
            "http-node-1": {"status": 200, "data": {"message": "Hello"}},
            "text-node-1": {"text": "Some text output"},
            "iteration-node": {"type": "iteration_result", "items": [1, 2, 3]},
        }

        # Collect tool definitions
        tool_params, tool_configs, _ = agent_node._collect_tool_definitions(inputs)

        # Should only collect the actual tool
        assert len(tool_params) == 1
        assert tool_params[0]["function"]["name"] == "search_database"

    @pytest.mark.asyncio
    async def test_agent_collects_tool_with_all_parameter_types(self, agent_node):
        """Test that tools with various parameter types are collected correctly."""
        tool_config = ToolNodeConfig(
            config=ToolConfig(
                tool_name="complex_action",
                tool_description="A tool with all parameter types",
                parameters=[
                    ToolParameter(name="text", type="string", description="Text input", required=True),
                    ToolParameter(name="count", type="number", description="A number", required=True),
                    ToolParameter(name="enabled", type="boolean", description="Toggle", required=False, default=True),
                    ToolParameter(name="options", type="object", description="Options object", required=False),
                    ToolParameter(name="items", type="array", description="List of items", required=False),
                ],
            ),
            credentials=None,
        )
        tool = ToolNode(
            node_id="tool-complex",
            node_type="tool",
            node_data={},
            config=tool_config,
            sio=None,
            sid=None,
            workflow_id="test",
        )

        tool_output = await tool.execute({})
        inputs = {tool.node_id: tool_output}

        tool_params, _, _ = agent_node._collect_tool_definitions(inputs)

        assert len(tool_params) == 1
        func_params = tool_params[0]["function"]["parameters"]

        # Verify all parameter types are present
        props = func_params["properties"]
        assert props["text"]["type"] == "string"
        assert props["count"]["type"] == "number"
        assert props["enabled"]["type"] == "boolean"
        assert props["options"]["type"] == "object"
        assert props["items"]["type"] == "array"

        # Verify required list only contains required params
        assert set(func_params["required"]) == {"text", "count"}

    @pytest.mark.asyncio
    async def test_agent_returns_empty_when_no_tools_in_inputs(self, agent_node):
        """Test that AgentNode returns empty lists when no tools are in inputs."""
        # Inputs with no tool definitions
        inputs = {
            "http-node-1": {"status": 200, "data": {}},
            "text-node-1": {"text": "output"},
        }

        tool_params, tool_configs, _ = agent_node._collect_tool_definitions(inputs)

        assert tool_params == []
        assert tool_configs == {}

    @pytest.mark.asyncio
    async def test_agent_handles_empty_inputs(self, agent_node):
        """Test that AgentNode handles empty inputs gracefully."""
        tool_params, tool_configs, _ = agent_node._collect_tool_definitions({})

        assert tool_params == []
        assert tool_configs == {}

    @pytest.mark.asyncio
    async def test_collected_tool_format_matches_litellm(self, tool_node, agent_node):
        """Test that collected tools match LiteLLM ChatCompletionToolParam format."""
        tool_output = await tool_node.execute({})
        inputs = {tool_node.node_id: tool_output}

        tool_params, _, _ = agent_node._collect_tool_definitions(inputs)

        # Verify LiteLLM format requirements
        tool = tool_params[0]
        assert tool["type"] == "function"
        assert "function" in tool

        func = tool["function"]
        assert "name" in func
        assert "description" in func
        assert "parameters" in func

        params = func["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params


# ============================================================================
# Workflow Integration Tests - Frontend JSON Format
# ============================================================================

class TestToolNodeWorkflowJsonFormat:
    """
    Tests that verify ToolNode works correctly with the exact JSON format
    sent from the frontend workflow editor.

    These tests ensure the config transformation pipeline doesn't break:
    Frontend JSON → _resolve_credentials → NodeFactory.create_node → ToolNode
    """

    def test_tool_node_created_from_frontend_json_format(self):
        """
        Test creating ToolNode from exact frontend JSON structure.

        Frontend sends configs in flat format:
        { tool_name: "...", tool_description: "...", parameters: [...], credentialIds: {} }

        After _resolve_credentials, it becomes:
        { config: { tool_name: "...", ... }, credentials: None }
        """
        # This is what _resolve_credentials produces from frontend JSON
        resolved_node_data = {
            'config': {
                'tool_name': 'send_message',
                'tool_description': 'Use this tool to send a message to telegram',
                'parameters': [
                    {
                        'name': 'message',
                        'type': 'string',
                        'description': 'The message to send',
                        'required': True
                    }
                ]
            },
            'credentials': None
        }

        from nodes import NodeFactory

        node = NodeFactory.create_node(
            node_id="tool_kh6d",
            node_type="tool",
            node_data=resolved_node_data,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )

        # Verify node was created correctly
        assert node.node_id == "tool_kh6d"
        assert node.node_type == "tool"
        assert node.config is not None

        # Verify tool definition is correct
        tool_def = node.get_tool_definition()
        assert tool_def["function"]["name"] == "send_message"
        assert tool_def["function"]["description"] == "Use this tool to send a message to telegram"
        assert "message" in tool_def["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_tool_node_execute_from_frontend_json_format(self):
        """Test that ToolNode.execute() works with frontend JSON format."""
        resolved_node_data = {
            'config': {
                'tool_name': 'send_message',
                'tool_description': 'Send a message to telegram',
                'parameters': [
                    {'name': 'message', 'type': 'string', 'description': 'Message text', 'required': True}
                ]
            },
            'credentials': None
        }

        from nodes import NodeFactory

        node = NodeFactory.create_node(
            node_id="tool_test",
            node_type="tool",
            node_data=resolved_node_data,
            sio=None,
            sid=None,
            workflow_id="test"
        )

        output = await node.execute({})

        # Verify output is correct tool_definition format
        assert output["type"] == "tool_definition"
        assert output["tool_name"] == "send_message"
        assert output["tool_description"] == "Send a message to telegram"
        assert len(output["parameters"]) == 1
        assert output["parameters"][0]["name"] == "message"

    @pytest.mark.asyncio
    async def test_full_workflow_json_structure(self):
        """
        Test the exact workflow JSON structure from the user's E2E test.

        This tests the complete path from workflow JSON to tool collection.
        """
        # Exact structure from user's workflow JSON
        workflow_json = {
            "nodes": [
                {
                    "id": "agent_mhxu",
                    "type": "agent",
                    "position": {"x": 251.59, "y": 113.28},
                    "config": {
                        "model": "openrouter/openai/gpt-4o-mini",
                        "credentialIds": {},
                        "system_prompt": "You are a helpful assistant.",
                        "message": "Hello"  # Required field for AgentConfig
                    }
                },
                {
                    "id": "tool_kh6d",
                    "type": "tool",
                    "position": {"x": 306.81, "y": 307.23},
                    "config": {
                        "tool_name": "send_message",
                        "parameters": [
                            {
                                "name": "message",
                                "type": "string",
                                "required": True,
                                "description": "The message to send"
                            }
                        ],
                        "credentialIds": {},
                        "tool_description": "Use this tool to send a message to telegram"
                    }
                }
            ],
            "edges": [
                {
                    "id": "edge-1",
                    "source": "tool_kh6d",
                    "target": "agent_mhxu",
                    "sourceHandle": "top",
                    "targetHandle": "bottom"
                }
            ]
        }

        # Simulate _resolve_credentials transformation for tool node
        tool_config = workflow_json["nodes"][1]["config"]
        tool_resolved = {
            'config': {k: v for k, v in tool_config.items() if k != 'credentialIds'},
            'credentials': None
        }

        from nodes import NodeFactory

        tool_node = NodeFactory.create_node(
            node_id="tool_kh6d",
            node_type="tool",
            node_data=tool_resolved,
            sio=None,
            sid=None,
            workflow_id="test"
        )

        # Execute tool to get definition
        tool_output = await tool_node.execute({})

        # Verify tool definition output
        assert tool_output["type"] == "tool_definition"
        assert tool_output["tool_name"] == "send_message"

        # Now verify AgentNode can collect this tool
        agent_config = workflow_json["nodes"][0]["config"]
        agent_resolved = {
            'config': {k: v for k, v in agent_config.items() if k != 'credentialIds'},
            'credentials': None
        }

        agent_node = NodeFactory.create_node(
            node_id="agent_mhxu",
            node_type="agent",
            node_data=agent_resolved,
            sio=None,
            sid=None,
            workflow_id="test"
        )

        # Simulate workflow execution - tool output passed to agent
        inputs = {"tool_kh6d": tool_output}
        tool_params, tool_configs, _ = agent_node._collect_tool_definitions(inputs)

        # CRITICAL: Verify tool was collected
        assert len(tool_params) == 1, f"Expected 1 tool, got {len(tool_params)}"
        assert tool_params[0]["function"]["name"] == "send_message"
        assert "send_message" in tool_configs
