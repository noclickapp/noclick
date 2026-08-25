"""
Tests for Serverless Function node.
Tests JavaScript execution via QuickJS (fast, in-process).
Python execution backends are tested separately in integration tests.
"""

import pytest
from unittest.mock import AsyncMock, patch
from nodes.serverless_function_node import (
    ServerlessFunctionNode,
    ServerlessFunctionNodeConfig,
    ServerlessFunctionInnerConfig,
    PythonRuntimeConfig,
    JavaScriptRuntimeConfig,
    FunctionInput,
    HardwareConfig,
    GPU_OPTIONS,
    REGION_OPTIONS,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_emit():
    """Create a mock emit function for capturing node outputs."""
    return AsyncMock()


def create_node(
    config: ServerlessFunctionInnerConfig,
    node_id: str = "serverless_1",
    emit_fn: AsyncMock = None,
) -> ServerlessFunctionNode:
    """Helper to create a ServerlessFunctionNode with given config."""
    node_config = ServerlessFunctionNodeConfig(config=config)
    node = ServerlessFunctionNode(
        node_id=node_id,
        node_type="automation-serverless-function",
        node_data={},
        config=node_config,
    )
    if emit_fn:
        node.emit = emit_fn
    else:
        node.emit = AsyncMock()
    return node


# ============================================================================
# JavaScript Execution Tests
# ============================================================================


class TestJavaScriptExecution:
    """Test JavaScript runtime execution."""

    @pytest.mark.asyncio
    async def test_simple_javascript_execution(self, mock_emit):
        """Test simple JavaScript code execution."""
        config = JavaScriptRuntimeConfig(
            function_body="return 42;", function_inputs=None
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["type"] == "serverless_function"
        assert result["status"] == "completed"
        assert result["runtime"] == "javascript"
        assert result["result"] == 42
        assert result["exit_code"] == 0
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_javascript_with_inputs(self, mock_emit):
        """Test JavaScript with function inputs."""
        config = JavaScriptRuntimeConfig(
            function_body="return inputs.a + inputs.b;",
            function_inputs=[
                FunctionInput(name="a", value=10),
                FunctionInput(name="b", value=32),
            ],
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"] == 42

    @pytest.mark.asyncio
    async def test_javascript_array_transformation(self, mock_emit):
        """Test JavaScript array transformation."""
        config = JavaScriptRuntimeConfig(
            function_body="return inputs.data.map(x => x * 2);",
            function_inputs=[
                FunctionInput(name="data", value=[1, 2, 3, 4, 5]),
            ],
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"] == [2, 4, 6, 8, 10]

    @pytest.mark.asyncio
    async def test_javascript_object_return(self, mock_emit):
        """Test JavaScript returning an object."""
        config = JavaScriptRuntimeConfig(
            function_body="return { name: inputs.name, processed: true };",
            function_inputs=[
                FunctionInput(name="name", value="test"),
            ],
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"]["name"] == "test"
        assert result["result"]["processed"] is True

    @pytest.mark.asyncio
    async def test_javascript_error_handling(self, mock_emit):
        """Test JavaScript error handling."""
        config = JavaScriptRuntimeConfig(
            function_body='throw new Error("Test error");', function_inputs=None
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["exit_code"] == 1
        assert "Test error" in result["error"]

    @pytest.mark.asyncio
    async def test_javascript_console_output(self, mock_emit):
        """Test JavaScript console.log capture."""
        config = JavaScriptRuntimeConfig(
            function_body="""
                console.log("Hello from JS");
                console.error("Warning!");
                return "done";
            """,
            function_inputs=None,
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert "Hello from JS" in result["stdout"]
        assert "Warning!" in result["stderr"]

    @pytest.mark.asyncio
    async def test_javascript_execution_time_tracked(self, mock_emit):
        """Test that JavaScript execution time is tracked."""
        config = JavaScriptRuntimeConfig(
            function_body="return 42;", function_inputs=None
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert "execution_time_ms" in result
        assert result["execution_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_javascript_emits_running_status(self, mock_emit):
        """Test that JavaScript execution emits running status."""
        config = JavaScriptRuntimeConfig(
            function_body="return 42;", function_inputs=None
        )
        node = create_node(config, emit_fn=mock_emit)

        await node.execute({})

        # Should have emitted at least 2 events: running and completed
        assert mock_emit.call_count >= 2
        first_emit = mock_emit.call_args_list[0][0][0]
        assert first_emit["status"] == "running"
        assert first_emit["runtime"] == "javascript"


# ============================================================================
# Operation Routing Tests
# ============================================================================


class TestOperationRouting:
    """Test that the node correctly routes to different operations (runtimes)."""

    def test_python_operation_config(self):
        """Test that Python config has correct operation."""
        config = PythonRuntimeConfig(function_body="return 42", function_inputs=None)
        # Verify the operation field is set correctly
        assert config.operation == "run_python_function"

    @pytest.mark.asyncio
    async def test_javascript_routing(self, mock_emit):
        """Test that JavaScript operation routes correctly."""
        config = JavaScriptRuntimeConfig(
            function_body="return 'js';", function_inputs=None
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["runtime"] == "javascript"
        assert result["result"] == "js"


# ============================================================================
# Function Input Tests
# ============================================================================


class TestFunctionInputs:
    """Test function input handling."""

    @pytest.mark.asyncio
    async def test_no_inputs(self, mock_emit):
        """Test execution with no inputs."""
        config = JavaScriptRuntimeConfig(
            function_body="return Object.keys(inputs).length;", function_inputs=None
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"] == 0

    @pytest.mark.asyncio
    async def test_empty_inputs_list(self, mock_emit):
        """Test execution with empty inputs list."""
        config = JavaScriptRuntimeConfig(
            function_body="return Object.keys(inputs).length;", function_inputs=[]
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"] == 0

    @pytest.mark.asyncio
    async def test_multiple_inputs(self, mock_emit):
        """Test execution with multiple inputs."""
        config = JavaScriptRuntimeConfig(
            function_body="return { sum: inputs.a + inputs.b, product: inputs.a * inputs.b };",
            function_inputs=[
                FunctionInput(name="a", value=5),
                FunctionInput(name="b", value=7),
            ],
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"]["sum"] == 12
        assert result["result"]["product"] == 35

    @pytest.mark.asyncio
    async def test_complex_input_types(self, mock_emit):
        """Test execution with complex input types."""
        config = JavaScriptRuntimeConfig(
            function_body="""
                return {
                    arrayLen: inputs.arr.length,
                    objKeys: Object.keys(inputs.obj).length,
                    nested: inputs.nested.level1.level2
                };
            """,
            function_inputs=[
                FunctionInput(name="arr", value=[1, 2, 3, 4, 5]),
                FunctionInput(name="obj", value={"a": 1, "b": 2, "c": 3}),
                FunctionInput(name="nested", value={"level1": {"level2": "deep"}}),
            ],
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"]["arrayLen"] == 5
        assert result["result"]["objKeys"] == 3
        assert result["result"]["nested"] == "deep"


# ============================================================================
# Dynamic Options Tests
# ============================================================================


class TestDynamicOptions:
    """Test dynamic field options loading."""

    @pytest.mark.asyncio
    async def test_load_gpu_options(self):
        """Test loading GPU options."""
        result = await ServerlessFunctionNode.load_field_options(
            field_name="gpu_type", credential_data={}, context=None
        )

        assert "options" in result
        assert len(result["options"]) > 0
        values = [opt["value"] for opt in result["options"]]
        assert "none" in values
        assert "T4" in values

    @pytest.mark.asyncio
    async def test_load_region_options(self):
        """Test loading region options."""
        result = await ServerlessFunctionNode.load_field_options(
            field_name="region", credential_data={}, context=None
        )

        assert "options" in result
        values = [opt["value"] for opt in result["options"]]
        assert "" in values  # Auto option
        assert "us-east" in values

    @pytest.mark.asyncio
    async def test_load_unknown_field_options(self):
        """Test loading options for unknown field."""
        result = await ServerlessFunctionNode.load_field_options(
            field_name="unknown_field", credential_data={}, context=None
        )

        assert result["options"] == []


# ============================================================================
# Config Model Tests
# ============================================================================


class TestConfigModels:
    """Test configuration model validation."""

    def test_function_input_validation(self):
        """Test FunctionInput name pattern validation."""
        # Valid names
        valid = FunctionInput(name="validName", value=42)
        assert valid.name == "validName"

        valid = FunctionInput(name="_private", value=42)
        assert valid.name == "_private"

        valid = FunctionInput(name="name123", value=42)
        assert valid.name == "name123"

    def test_function_input_invalid_name(self):
        """Test FunctionInput rejects invalid names."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            FunctionInput(name="123invalid", value=42)

        with pytest.raises(Exception):
            FunctionInput(name="with-dash", value=42)

        with pytest.raises(Exception):
            FunctionInput(name="with space", value=42)

    def test_hardware_config_defaults(self):
        """Test HardwareConfig default values."""
        config = HardwareConfig()
        assert config.gpu_type == "none"
        assert config.gpu_count == 1
        assert config.cpu_cores == 1.0
        assert config.memory_mb == 1024

    def test_hardware_config_custom(self):
        """Test HardwareConfig with custom values."""
        config = HardwareConfig(
            gpu_type="A100-40GB", gpu_count=2, cpu_cores=4.0, memory_mb=8192
        )
        assert config.gpu_type == "A100-40GB"
        assert config.gpu_count == 2
        assert config.cpu_cores == 4.0
        assert config.memory_mb == 8192

    def test_python_config_defaults(self):
        """Test PythonRuntimeConfig defaults."""
        config = PythonRuntimeConfig(function_body="return 42")
        assert config.operation == "run_python_function"
        assert config.function_inputs is None
        assert config.pip_packages is None
        assert config.timeout_seconds == 300
        assert config.region is None

    def test_javascript_config(self):
        """Test JavaScriptRuntimeConfig."""
        config = JavaScriptRuntimeConfig(function_body="return 42")
        assert config.operation == "run_javascript_function"
        # JavaScript has no configurable timeout (fixed at 3s for shared container)


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_missing_config(self):
        """Test handling missing config."""
        node = ServerlessFunctionNode(
            node_id="serverless_1",
            node_type="automation-serverless-function",
            node_data={},
            config=None,
        )
        node.emit = AsyncMock()

        with pytest.raises(ValueError, match="Configuration required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_syntax_error_in_javascript(self, mock_emit):
        """Test handling JavaScript syntax errors."""
        config = JavaScriptRuntimeConfig(
            function_body="return {invalid syntax", function_inputs=None
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["exit_code"] == 1
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_unicode_in_code_and_inputs(self, mock_emit):
        """Test handling unicode in code and inputs."""
        config = JavaScriptRuntimeConfig(
            function_body='return inputs.emoji + " " + inputs.text;',
            function_inputs=[
                FunctionInput(name="emoji", value="🚀"),
                FunctionInput(name="text", value="こんにちは"),
            ],
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"] == "🚀 こんにちは"

    @pytest.mark.asyncio
    async def test_large_data_processing(self, mock_emit):
        """Test handling large data arrays."""
        large_array = list(range(10000))
        config = JavaScriptRuntimeConfig(
            function_body="return inputs.data.reduce((a, b) => a + b, 0);",
            function_inputs=[
                FunctionInput(name="data", value=large_array),
            ],
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        # Sum of 0 to 9999
        assert result["result"] == sum(range(10000))

    @pytest.mark.asyncio
    async def test_null_and_undefined_handling(self, mock_emit):
        """Test handling null values."""
        config = JavaScriptRuntimeConfig(
            function_body="""
                return {
                    nullValue: inputs.nullVal,
                    isNull: inputs.nullVal === null,
                    undefinedCheck: inputs.missing === undefined
                };
            """,
            function_inputs=[
                FunctionInput(name="nullVal", value=None),
            ],
        )
        node = create_node(config, emit_fn=mock_emit)

        result = await node.execute({})

        assert result["status"] == "completed"
        assert result["result"]["nullValue"] is None
        assert result["result"]["isNull"] is True
