"""
Serverless Function Node - Executes user-defined code in multiple runtimes.

Supports two operations (runtimes):
- python: isolated compute with GPU, pip packages, configurable hardware
- javascript: Fast QuickJS execution (~1-5ms, no cold start)

Users define named input parameters that map to values from upstream nodes,
write a function body, and the system executes it in the selected runtime.
"""

import logging
import asyncio
import textwrap
import json
import re
import time
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, Field, Discriminator

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# GPU options with metadata for display
GPU_OPTIONS = [
    {
        "value": "none",
        "label": "CPU Only",
        "metadata": {"description": "No GPU, CPU-only execution"},
    },
    {
        "value": "T4",
        "label": "NVIDIA T4",
        "metadata": {"description": "16GB VRAM, good for inference"},
    },
    {
        "value": "L4",
        "label": "NVIDIA L4",
        "metadata": {"description": "24GB VRAM, efficient inference"},
    },
    {
        "value": "A10G",
        "label": "NVIDIA A10G",
        "metadata": {"description": "24GB VRAM, versatile"},
    },
    {
        "value": "A100-40GB",
        "label": "NVIDIA A100 (40GB)",
        "metadata": {"description": "40GB VRAM, high performance"},
    },
    {
        "value": "A100-80GB",
        "label": "NVIDIA A100 (80GB)",
        "metadata": {"description": "80GB VRAM, large models"},
    },
    {
        "value": "H100",
        "label": "NVIDIA H100",
        "metadata": {"description": "80GB VRAM, fastest available"},
    },
]

# Region options with metadata
REGION_OPTIONS = [
    {
        "value": "",
        "label": "Auto (nearest)",
        "metadata": {"description": "Automatically select nearest region"},
    },
    {
        "value": "us-east",
        "label": "US East",
        "metadata": {"description": "Virginia, USA"},
    },
    {
        "value": "us-west",
        "label": "US West",
        "metadata": {"description": "Oregon, USA"},
    },
    {"value": "eu-west", "label": "EU West", "metadata": {"description": "Ireland"}},
    {
        "value": "eu-central",
        "label": "EU Central",
        "metadata": {"description": "Frankfurt, Germany"},
    },
]


class FunctionInput(BaseModel):
    """A single named input parameter for the function."""

    name: str = Field(
        ...,
        title="Parameter Name",
        description="Variable name (valid identifier)",
        pattern=r"^[a-zA-Z_$][a-zA-Z0-9_$]*$",
    )
    value: Any = Field(
        ...,
        title="Value",
        description="Value reference from upstream node (e.g., {{node-id.field}})",
    )


class HardwareConfig(BaseModel):
    """Hardware configuration for the serverless function sandbox."""

    gpu_type: str = Field(
        default="none",
        title="GPU Type",
        description="GPU type to use. Select 'CPU Only' for no GPU.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "gpu_type",
                "placeholder": "Select GPU type...",
                "searchable": False,
                "allow_custom": False,
            }
        },
    )

    gpu_count: int = Field(
        default=1,
        ge=1,
        le=8,
        title="GPU Count",
        description="Number of GPUs (only applies if GPU type is not 'CPU Only')",
    )

    cpu_cores: float = Field(
        default=1.0,
        ge=0.25,
        le=16.0,
        title="CPU Cores",
        description="Number of CPU cores (can be fractional, e.g., 0.5)",
    )

    memory_mb: int = Field(
        default=1024,
        ge=256,
        le=65536,
        title="Memory (MB)",
        description="Memory limit in MiB",
    )


# ============================================================================
# Operation-specific configurations
# ============================================================================


class PythonRuntimeConfig(BaseModel):
    """Python Runtime — isolated compute with GPU & packages."""

    operation: Literal["run_python_function"] = Field(
        "run_python_function",
        title="Run Python Function",
        description="For computationally heavy tasks, GPU workloads, or when you need pip packages",
        json_schema_extra={
            "ui:hidden": True,
            "const": "run_python_function",
            "x-category": "Runtime",
            "x-is-trigger": False,
            "x-display-name": "Run Python Function",
        },
    )

    function_inputs: Optional[List[FunctionInput]] = Field(
        default=None,
        title="Function Inputs",
        description="Named input parameters for the function",
        json_schema_extra={"ui:widget": "function_inputs"},
    )

    function_body: str = Field(
        ...,
        min_length=1,
        title="Function Body",
        description=(
            "Python code for the function body. Declared function inputs are "
            "available as parameters (an input named `x` is just `x`). To inline "
            "an upstream value directly in code, wrap the reference in quoted "
            "double curly braces — e.g. `x = float(\"{{ $('node_id').field }}\")` "
            "— substitution is textual, and a bare $('node_id') outside {{ }} is "
            "a NameError at run time."
        ),
        json_schema_extra={
            "ui:widget": "python_editor",
            "placeholder": "# Use your input variables here\nresult = [x * 2 for x in data]\nreturn {'processed': result}",
        },
    )

    pip_packages: Optional[str] = Field(
        default=None,
        title="Requirements",
        description="Python packages to install (one per line)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "numpy\npandas\nrequests>=2.28.0",
        },
    )

    hardware: Optional[HardwareConfig] = Field(
        default_factory=HardwareConfig,
        title="Hardware",
        description="Hardware resources for function execution",
    )

    timeout_seconds: int = Field(
        default=300,
        ge=1,
        le=3600,
        title="Timeout (seconds)",
        description="Maximum execution time",
    )

    region: Optional[str] = Field(
        default=None,
        title="Region",
        description="Preferred cloud region",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "region",
                "placeholder": "Select region...",
                "searchable": False,
                "allow_custom": False,
            }
        },
    )


class JavaScriptRuntimeConfig(BaseModel):
    """JavaScript Runtime - Fast QuickJS execution."""

    operation: Literal["run_javascript_function"] = Field(
        "run_javascript_function",
        title="Run Javascript Function",
        description="For quick data transformations and simple logic without external dependencies",
        json_schema_extra={
            "ui:hidden": True,
            "const": "run_javascript_function",
            "x-category": "Runtime",
            "x-is-trigger": False,
            "x-display-name": "Run Javascript Function",
        },
    )

    function_inputs: Optional[List[FunctionInput]] = Field(
        default=None,
        title="Function Inputs",
        description="Named input parameters for the function",
        json_schema_extra={"ui:widget": "function_inputs"},
    )

    function_body: str = Field(
        ...,
        min_length=1,
        title="Function Body",
        description=(
            "JavaScript code for the function body. Declared function inputs are "
            "available as bare variables (an input named `x` is just `x`, also "
            "`inputs.x`). To inline an upstream value directly in code, wrap the "
            "reference in quoted double curly braces — e.g. "
            "`const x = Number(\"{{ $('node_id').field }}\");` — substitution is "
            "textual, and a bare $('node_id') outside {{ }} is a ReferenceError "
            "at run time."
        ),
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "javascript",
            "placeholder": "// Use your input variables here\nconst result = data.map(x => x * 2);\nreturn { processed: result };",
        },
    )


# Discriminated union of all runtime configs
ServerlessFunctionInnerConfig = Annotated[
    Union[
        JavaScriptRuntimeConfig,
        PythonRuntimeConfig,
    ],
    Discriminator("operation"),
]


class ServerlessFunctionNodeConfig(NodeConfig[ServerlessFunctionInnerConfig, None]):
    """Full configuration for serverless function node (no credentials needed)."""

    pass


class ServerlessFunctionNode(WorkflowNode):
    """
    Serverless Function workflow node.

    Executes user Python code on the registered compute backend with configurable hardware.
    Users define named input parameters that become function arguments.
    """

    edit_examples = [
        "Switch runtime from Python to JavaScript",
        "Add GPU support with A100 GPU",
        "Increase timeout to 600 seconds",
        "Install numpy and pandas packages",
        "Add function input parameter",
        "Set region to EU West",
        "Allocate 4 CPU cores and 8GB memory",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        return ServerlessFunctionNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic options for dropdown fields."""
        logger.info(f"[ServerlessFunctionNode] load_field_options: field={field_name}")

        if field_name == "gpu_type":
            return {"options": GPU_OPTIONS, "next_page_token": None}
        elif field_name == "region":
            return {"options": REGION_OPTIONS, "next_page_token": None}

        return {"options": [], "next_page_token": None}

    def _resolve_reference(self, reference: str, inputs: Dict[str, Any]) -> Any:
        """
        Resolve a {{node-id.field.subfield}} reference to its actual value.

        Args:
            reference: Reference string like "{{sheets-1.values}}" or just "sheets-1.values"
            inputs: Dict of upstream node outputs keyed by node_id

        Returns:
            The resolved value, or None if not found
        """
        # Strip {{ }} if present
        path = reference.strip()
        if path.startswith("{{") and path.endswith("}}"):
            path = path[2:-2].strip()

        if not path:
            return None

        parts = path.split(".")
        if not parts:
            return None

        # Navigate the path
        value = inputs
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
            if value is None:
                return None

        return value

    def _get_function_params(
        self, function_inputs: Optional[List[FunctionInput]]
    ) -> List[str]:
        """Get list of parameter names from function inputs."""
        if not function_inputs:
            return []
        return [inp.name for inp in function_inputs if inp.name]

    def _build_function_code(self, function_body: str, param_names: List[str]) -> str:
        """
        Wrap user's function body in a proper function definition.

        The user's code is wrapped in an inner function so that their `return` statement
        properly returns a value we can capture, rather than exiting the wrapper function.

        Args:
            function_body: User's Python code
            param_names: List of parameter names for the function signature
        """
        # Build parameter list for function signature
        params = ", ".join(param_names) if param_names else ""

        # Dedent the function body
        dedented_body = textwrap.dedent(function_body)

        # Indent body for the inner user function (4 spaces)
        indented_body = textwrap.indent(dedented_body, "    ")

        wrapper = f'''import sys
import io
import json
import traceback

def _user_function({params}):
    """User-defined function body."""
{indented_body}

def run_function({params}):
    """Wrapper that captures stdout/stderr and return value."""
    # Capture stdout/stderr
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    sys.stdout = stdout_capture
    sys.stderr = stderr_capture

    result = None
    error = None
    exit_code = 0

    try:
        result = _user_function({params})
    except Exception as e:
        error = str(e)
        traceback.print_exc()
        exit_code = 1
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return {{
        'result': result,
        'stdout': stdout_capture.getvalue(),
        'stderr': stderr_capture.getvalue(),
        'error': error,
        'exit_code': exit_code
    }}

# Execute with provided arguments from file
if __name__ == "__main__":
    # Read kwargs from file instead of command line to avoid ARG_MAX limit
    try:
        with open('/tmp/input_kwargs.json', 'r') as f:
            kwargs = json.load(f)
    except FileNotFoundError:
        kwargs = {{}}

    output = run_function(**kwargs)
    print("__RESULT_START__")
    print(json.dumps(output))
    print("__RESULT_END__")
'''
        return wrapper

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the function in the selected runtime."""
        logger.info(f"[ServerlessFunctionNode] Executing node {self.node_id}")
        logger.info(
            f"[ServerlessFunctionNode] Received inputs keys: {list(inputs.keys())}"
        )
        logger.debug(f"[ServerlessFunctionNode] Full inputs: {inputs}")

        node_config = self.config
        if not node_config or not isinstance(node_config, ServerlessFunctionNodeConfig):
            raise ValueError(f"Configuration required for node {self.node_id}")

        config = node_config.config
        operation = config.operation

        # Check for state injection from a connected State Manager node
        state_input = self.node_data.get("__state_input__")
        state_node_id = state_input.get("node_id") if state_input else None
        injected_state = state_input.get("state", {}) if state_input else None
        state_var_name = (
            state_input.get("variable_name", "state") if state_input else "state"
        )
        # If state comes from a function_input, skip separate injection (already resolved)
        state_from_func_input = (
            state_input.get("from_function_input", False) if state_input else False
        )

        if state_input:
            logger.info(
                f"[ServerlessFunctionNode] State from node {state_node_id}, var='{state_var_name}', from_func_input={state_from_func_input}"
            )

        # Route to appropriate executor based on operation
        if operation == "run_javascript_function":
            output = await self._execute_javascript(
                inputs, config, injected_state, state_var_name, state_from_func_input
            )
        else:
            output = await self._execute_python(
                inputs, config, injected_state, state_var_name, state_from_func_input
            )

        # Persist mutated state back to the State Manager's record
        # Users can return state in several ways:
        #   1. { __state__: { counter: 1 } } - explicit state return (highest priority)
        #   2. { state: { counter: 1 } } - convenient alternative
        #   3. Return the state object directly: return state; (result IS the new state)
        #   4. Auto-capture: mutations to `state` variable are captured automatically (no return needed)
        if state_node_id:
            result = output.get("result")
            mutated_state = None

            if isinstance(result, dict):
                # Check for explicit __state__ key (highest priority)
                if "__state__" in result:
                    mutated_state = result["__state__"]
                    del result["__state__"]
                # Check for variable name key as convenient alternative (e.g., return { state: {...} })
                elif state_var_name in result and isinstance(
                    result[state_var_name], dict
                ):
                    mutated_state = result[state_var_name]
                # If injected_state exists and result has at least some of its keys, treat result as state
                # This handles: state.counter++; return state;
                elif injected_state is not None:
                    # Check if result contains any of the original state keys (loose match)
                    original_keys = set(injected_state.keys())
                    result_keys = set(result.keys())
                    if original_keys and original_keys.issubset(result_keys):
                        mutated_state = result

            # Fallback: use auto-captured state from js_executor if no explicit return
            # This allows mutations without explicit return: state.counter += 1;
            if mutated_state is None and "__mutated_state__" in output:
                mutated_state = output.get("__mutated_state__")
                # Clean up internal field from output
                del output["__mutated_state__"]
                logger.info(
                    f"[ServerlessFunctionNode] Using auto-captured state for persistence"
                )

            if mutated_state is not None:
                await self._persist_state_to_manager(
                    state_node_id, mutated_state, state_var_name
                )
                logger.info(
                    f"[ServerlessFunctionNode] Persisted state with {len(mutated_state)} keys"
                )

        return output

    async def _persist_state_to_manager(
        self, state_node_id: str, state: Dict[str, Any], variable_name: str = "state"
    ) -> None:
        """Persist mutated state back to the State Manager node's record."""
        if not self.workflow_id:
            logger.warning(
                "[ServerlessFunctionNode] Cannot persist state: workflow_id not set"
            )
            return

        try:
            from utils.database_pool import get_native_pool

            # Use INSERT ... ON CONFLICT to upsert state
            await get_native_pool().execute(
                """
                INSERT INTO workflow_node_state (workflow_id, node_id, state, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (workflow_id, node_id)
                DO UPDATE SET state = $3, updated_at = NOW()
                """,
                self.workflow_id,
                state_node_id,
                state,
            )

            # Emit updated output for the State Manager node so frontend auto-syncs
            # This ensures the State Manager shows the latest persisted value immediately
            if self.sio and self.sid:
                from wss.sender.events import WorkflowNodeOutputEvent
                from wss.sender import send_event

                await send_event(
                    self.sio,
                    self.sid,
                    WorkflowNodeOutputEvent(
                        workflow_id=self.workflow_id,
                        node_id=state_node_id,
                        node_type="state-manager",
                        output={
                            "type": "state_manager",
                            "status": "success",
                            "state": state,
                        },
                    ),
                )

            logger.info(
                f"[ServerlessFunctionNode] Persisted mutated state to State Manager {state_node_id}"
            )
        except Exception as e:
            logger.error(f"[ServerlessFunctionNode] Failed to persist state: {e}")

    async def _execute_javascript(
        self,
        inputs: Dict[str, Any],
        config: ServerlessFunctionInnerConfig,
        injected_state: Optional[Dict[str, Any]] = None,
        state_var_name: str = "state",
        state_from_func_input: bool = False,
    ) -> Dict[str, Any]:
        """Execute JavaScript code using QuickJS."""
        logger.info(
            f"[ServerlessFunctionNode] Executing JavaScript for node {self.node_id}"
        )

        # Emit starting status
        await self.emit(
            {
                "type": "serverless_function",
                "status": "running",
                "runtime": "javascript",
            }
        )

        try:
            # Gather function inputs
            resolved_inputs = {}
            if config.function_inputs:
                for inp in config.function_inputs:
                    if inp.name:
                        resolved_inputs[inp.name] = inp.value
                        logger.debug(
                            f"[ServerlessFunctionNode] Input '{inp.name}': {type(inp.value).__name__}"
                        )

            # Inject state if provided from State Manager (skip if already in function_inputs)
            if injected_state is not None and not state_from_func_input:
                resolved_inputs[state_var_name] = injected_state
                logger.info(
                    f"[ServerlessFunctionNode] Injected state as '{state_var_name}' with {len(injected_state)} keys"
                )

            # Import async executor (lazy import to avoid issues if quickjs not installed).
            # execute_js_async routes through the dedicated `js_executor` thread pool
            # in utils.threaded_executors — separate from asyncio's default pool so
            # JS execution doesn't compete with other sync wrappers for thread slots.
            from utils.js_executor import execute_js_async

            result = await execute_js_async(
                code=config.function_body,
                inputs=resolved_inputs,
                timeout_sec=3,
                state_var_names=[state_var_name] if injected_state is not None else [],
            )

            # Build output
            output = {
                "type": "serverless_function",
                "status": "completed" if result["success"] else "error",
                "runtime": "javascript",
                "result": result.get("result"),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "error": result.get("error"),
                "exit_code": 0 if result["success"] else 1,
                "execution_time_ms": result.get("execution_time_ms", 0),
            }

            # Include auto-captured state for persistence (internal, removed before final output)
            if "__mutated_state__" in result:
                output["__mutated_state__"] = result["__mutated_state__"]

            if result["success"]:
                logger.info(
                    f"[ServerlessFunctionNode] JavaScript completed in {result.get('execution_time_ms', 0):.2f}ms"
                )
            else:
                logger.warning(
                    f"[ServerlessFunctionNode] JavaScript failed: {result.get('error')}"
                )

            await self.emit(output)
            return output

        except ImportError as e:
            logger.error(f"[ServerlessFunctionNode] QuickJS not installed: {e}")
            error_output = {
                "type": "serverless_function",
                "status": "error",
                "runtime": "javascript",
                "error": "JavaScript execution not available. QuickJS package not installed.",
                "exit_code": 1,
                "result": None,
                "stdout": "",
                "stderr": "",
            }
            await self.emit(error_output)
            raise RuntimeError("QuickJS not installed") from e

        except Exception as e:
            logger.error(
                f"[ServerlessFunctionNode] JavaScript error: {e}", exc_info=True
            )
            error_output = {
                "type": "serverless_function",
                "status": "error",
                "runtime": "javascript",
                "error": str(e),
                "exit_code": 1,
                "result": None,
                "stdout": "",
                "stderr": "",
            }
            await self.emit(error_output)
            raise

    async def _execute_python(
        self,
        inputs: Dict[str, Any],
        config: ServerlessFunctionInnerConfig,
        injected_state: Optional[Dict[str, Any]] = None,
        state_var_name: str = "state",
        state_from_func_input: bool = False,
    ) -> Dict[str, Any]:
        """Execute Python code on the registered compute backend."""
        # Pre-flight credit gate on the pool the charge lands on (organization attribution policy).
        # Raises InsufficientBalanceError before any sandbox is provisioned, so an
        # out-of-credits run never spends compute.
        if self.user_id:
            from billing.usage_tracker import usage_tracker

            await usage_tracker.enforce_credit_gate(
                self.user_id,
                organization_id=self.organization_id,
                sio=self.sio,
                sid=self.sid,
                user_resource=False,
                surface="serverless_function",
            )

        hardware = config.hardware or HardwareConfig()

        # Emit starting status
        await self.emit(
            {
                "type": "serverless_function",
                "status": "starting",
                "runtime": "python",
                "hardware": {
                    "gpu_type": hardware.gpu_type,
                    "gpu_count": hardware.gpu_count,
                    "cpu_cores": hardware.cpu_cores,
                    "memory_mb": hardware.memory_mb,
                },
            }
        )

        try:
            # Gather function inputs - values are already resolved by the workflow executor
            resolved_kwargs = {}
            param_names = []

            logger.info(
                f"[ServerlessFunctionNode] Function inputs config: {config.function_inputs}"
            )

            if config.function_inputs:
                for inp in config.function_inputs:
                    if inp.name:
                        param_names.append(inp.name)
                        resolved_kwargs[inp.name] = inp.value
                        value_preview = (
                            str(inp.value)[:200] if inp.value is not None else "None"
                        )
                        logger.info(
                            f"[ServerlessFunctionNode] Input '{inp.name}' resolved:"
                        )
                        logger.info(f"  - Type: {type(inp.value).__name__}")
                        logger.info(f"  - Value: {value_preview}")
                        if inp.value is None:
                            logger.warning(
                                f"[ServerlessFunctionNode] Input '{inp.name}' is None!"
                            )

            # Inject state if provided from State Manager (skip if already in function_inputs)
            if injected_state is not None and not state_from_func_input:
                param_names.append(state_var_name)
                resolved_kwargs[state_var_name] = injected_state
                logger.info(
                    f"[ServerlessFunctionNode] Injected state as '{state_var_name}' with {len(injected_state)} keys"
                )

            # Build the wrapped function code
            function_code = self._build_function_code(config.function_body, param_names)
            kwargs_json = json.dumps(resolved_kwargs)

            async def emit_status(status: str) -> None:
                await self.emit(
                    {
                        "type": "serverless_function",
                        "status": status,
                        "runtime": "python",
                    }
                )

            from nodes.core.code_runtime import get_python_runtime

            run_python = get_python_runtime()
            raw = await run_python(
                function_code=function_code,
                kwargs_json=kwargs_json,
                pip_packages=config.pip_packages,
                hardware=hardware,
                timeout_seconds=config.timeout_seconds,
                region=config.region,
                emit_status=emit_status,
                user_id=self.user_id,
                organization_id=self.organization_id,
            )
            stdout = raw["stdout"]
            stderr = raw["stderr"]
            exit_code = raw["exit_code"]

            # Parse result
            result = None
            clean_stdout = stdout
            inner_error = None

            if "__RESULT_START__" in stdout and "__RESULT_END__" in stdout:
                start = stdout.index("__RESULT_START__") + len("__RESULT_START__")
                end = stdout.index("__RESULT_END__")
                result_json = stdout[start:end].strip()
                try:
                    parsed = json.loads(result_json)
                    result = parsed.get("result")
                    clean_stdout = parsed.get("stdout", "")
                    inner_stderr = parsed.get("stderr", "")
                    inner_error = parsed.get("error")
                    inner_exit_code = parsed.get("exit_code", 0)

                    if inner_stderr:
                        stderr = inner_stderr + ("\n" + stderr if stderr else "")
                    if inner_error:
                        exit_code = inner_exit_code
                except json.JSONDecodeError:
                    result = {"raw_output": result_json}
                    clean_stdout = stdout[
                        : stdout.index("__RESULT_START__")
                    ].strip()
            else:
                result = {"raw_output": stdout}

            output = {
                "type": "serverless_function",
                "status": "completed",
                "runtime": "python",
                "result": result,
                "stdout": clean_stdout,
                "stderr": stderr,
                "error": inner_error,
                "exit_code": exit_code,
                "hardware": {
                    "gpu_type": hardware.gpu_type,
                    "gpu_count": hardware.gpu_count,
                    "cpu_cores": hardware.cpu_cores,
                    "memory_mb": hardware.memory_mb,
                },
            }

            await self.emit(output)
            return output

        except Exception as e:
            logger.error(f"[ServerlessFunctionNode] Python error: {e}", exc_info=True)
            error_output = {
                "type": "serverless_function",
                "status": "error",
                "runtime": "python",
                "error": str(e),
                "exit_code": 1,
                "result": None,
                "stdout": "",
                "stderr": "",
                "hardware": {
                    "gpu_type": hardware.gpu_type,
                    "gpu_count": hardware.gpu_count,
                    "cpu_cores": hardware.cpu_cores,
                    "memory_mb": hardware.memory_mb,
                },
            }
            await self.emit(error_output)
            raise
