"""
JavaScript Executor using QuickJS.

Provides secure, fast JavaScript execution with:
- Complete isolation (no filesystem, network, or process access)
- CPU time limits (kills infinite loops)
- Memory limits (prevents memory bombs)
- Fresh context per execution (no state persistence)

Usage:
    from utils.js_executor import execute_js

    result = execute_js(
        code="return inputs.data.map(x => x * 2)",
        inputs={"data": [1, 2, 3]},
        timeout_sec=30
    )
    # result = {"success": True, "result": [2, 4, 6], "stdout": "", "stderr": ""}
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Lazy import quickjs to avoid import errors if not installed
_quickjs = None


def _get_quickjs():
    """Lazy import of quickjs module."""
    global _quickjs
    if _quickjs is None:
        import quickjs
        _quickjs = quickjs
    return _quickjs


# Resource limits
DEFAULT_TIMEOUT_SEC = 3
MAX_TIMEOUT_SEC = 300
DEFAULT_MEMORY_BYTES = 15 * 1024 * 1024  # 15MB
MAX_MEMORY_BYTES = 500 * 1024 * 1024  # 500MB
MAX_OUTPUT_SIZE = 10 * 1024 * 1024  # 10MB result limit
MAX_LOG_SIZE = 1 * 1024 * 1024  # 1MB log limit


class JSExecutionError(Exception):
    """Error during JavaScript execution."""
    pass


def execute_js(
    code: str,
    inputs: Dict[str, Any],
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    memory_bytes: int = DEFAULT_MEMORY_BYTES,
) -> Dict[str, Any]:
    """
    Execute JavaScript code in a secure QuickJS sandbox.

    Security guarantees:
    - No filesystem access (no fs, no require)
    - No network access (no fetch, no XMLHttpRequest)
    - No process access (no process.env, no child_process)
    - No access to Python runtime
    - CPU time limited (kills infinite loops)
    - Memory limited (prevents memory bombs)
    - Fresh context per execution (no state persistence)

    Args:
        code: JavaScript code to execute. Can use `inputs` variable and `return`.
        inputs: Dictionary of inputs available as `inputs` in the code.
        timeout_sec: Maximum execution time in seconds (default 3, max 300).
        memory_bytes: Maximum memory usage in bytes (default 15MB, max 500MB).

    Returns:
        Dictionary with:
        - success: bool - Whether execution succeeded
        - result: Any - Return value from the code (JSON-serializable)
        - stdout: str - Console.log output
        - stderr: str - Console.error output
        - error: str (optional) - Error message if execution failed
        - execution_time_ms: float - Execution time in milliseconds
    """
    import time
    start_time = time.perf_counter()

    quickjs = _get_quickjs()

    # Validate and clamp limits
    timeout_sec = min(max(timeout_sec, 1), MAX_TIMEOUT_SEC)
    memory_bytes = min(max(memory_bytes, 1024 * 1024), MAX_MEMORY_BYTES)

    # Validate inputs can be serialized
    try:
        inputs_json = json.dumps(inputs)
        if len(inputs_json) > MAX_OUTPUT_SIZE:
            return {
                "success": False,
                "error": f"Inputs too large ({len(inputs_json)} bytes, max {MAX_OUTPUT_SIZE})",
                "result": None,
                "stdout": "",
                "stderr": "",
                "execution_time_ms": (time.perf_counter() - start_time) * 1000,
            }
    except (TypeError, ValueError) as e:
        return {
            "success": False,
            "error": f"Inputs not JSON-serializable: {e}",
            "result": None,
            "stdout": "",
            "stderr": "",
            "execution_time_ms": (time.perf_counter() - start_time) * 1000,
        }

    # Create fresh context for isolation
    ctx = quickjs.Context()

    # Set memory limit (can be set before time limit)
    ctx.set_memory_limit(memory_bytes)

    try:
        # Set up console that buffers to JS arrays (avoids Python callback issues with time limit)
        # We'll retrieve these arrays after execution
        ctx.eval("""
            // Internal buffers for console output
            const __stdout_buffer = [];
            const __stderr_buffer = [];
            const __max_log_size = 1048576;  // 1MB
            let __total_log_size = 0;

            function __format_arg(arg) {
                if (arg === null) return 'null';
                if (arg === undefined) return 'undefined';
                if (typeof arg === 'string') return arg;
                if (typeof arg === 'number' || typeof arg === 'boolean') return String(arg);
                try {
                    return JSON.stringify(arg);
                } catch (e) {
                    return String(arg);
                }
            }

            function __log_to_buffer(buffer, args) {
                const msg = args.map(__format_arg).join(' ');
                if (__total_log_size + msg.length < __max_log_size) {
                    buffer.push(msg);
                    __total_log_size += msg.length;
                }
            }

            // Console API
            const console = {
                log: (...args) => __log_to_buffer(__stdout_buffer, args),
                info: (...args) => __log_to_buffer(__stdout_buffer, args),
                debug: (...args) => __log_to_buffer(__stdout_buffer, args),
                warn: (...args) => __log_to_buffer(__stderr_buffer, args),
                error: (...args) => __log_to_buffer(__stderr_buffer, args),
            };
        """)

        # Inject inputs as frozen object (prevents modification)
        ctx.eval(f"const inputs = Object.freeze({inputs_json});")

        # Now set time limit (after console setup, before user code)
        ctx.set_time_limit(timeout_sec)

        # Wrap user code in a function to support return statements
        # Use strict mode for additional safety
        wrapped_code = f"""
        (function() {{
            "use strict";
            {code}
        }})()
        """

        # Execute
        result = ctx.eval(wrapped_code)

        # Convert result to JSON-serializable Python object
        result_json = _convert_result(result, ctx)

        # Retrieve console output buffers from JS
        stdout_lines = _convert_result(ctx.eval("__stdout_buffer"), ctx) or []
        stderr_lines = _convert_result(ctx.eval("__stderr_buffer"), ctx) or []
        stdout = "\n".join(stdout_lines) if stdout_lines else ""
        stderr = "\n".join(stderr_lines) if stderr_lines else ""

        # Check result size
        try:
            result_str = json.dumps(result_json)
            if len(result_str) > MAX_OUTPUT_SIZE:
                return {
                    "success": False,
                    "error": f"Result too large ({len(result_str)} bytes, max {MAX_OUTPUT_SIZE})",
                    "result": None,
                    "stdout": stdout,
                    "stderr": stderr,
                    "execution_time_ms": (time.perf_counter() - start_time) * 1000,
                }
        except (TypeError, ValueError):
            # Result not JSON-serializable, convert to string
            result_json = str(result_json)

        return {
            "success": True,
            "result": result_json,
            "stdout": stdout,
            "stderr": stderr,
            "execution_time_ms": (time.perf_counter() - start_time) * 1000,
        }

    except Exception as e:
        error_msg = str(e)

        # Provide helpful error messages
        if "interrupted" in error_msg.lower():
            error_msg = f"Execution timed out after {timeout_sec} seconds"
        elif "memory" in error_msg.lower():
            error_msg = f"Memory limit exceeded ({memory_bytes // (1024*1024)}MB)"

        logger.warning(f"[JSExecutor] Execution error: {error_msg}")

        # Try to retrieve console output even on error
        stdout = ""
        stderr = ""
        try:
            stdout_lines = _convert_result(ctx.eval("__stdout_buffer"), ctx) or []
            stderr_lines = _convert_result(ctx.eval("__stderr_buffer"), ctx) or []
            stdout = "\n".join(stdout_lines) if stdout_lines else ""
            stderr = "\n".join(stderr_lines) if stderr_lines else ""
        except Exception:
            pass  # Console retrieval failed, use empty strings

        return {
            "success": False,
            "error": error_msg,
            "result": None,
            "stdout": stdout,
            "stderr": stderr,
            "execution_time_ms": (time.perf_counter() - start_time) * 1000,
        }


def _serialize_arg(arg) -> str:
    """Serialize a console argument to string."""
    if arg is None:
        return "null"
    if isinstance(arg, bool):
        return "true" if arg else "false"
    if isinstance(arg, (int, float)):
        return str(arg)
    if isinstance(arg, str):
        return arg
    try:
        return json.dumps(arg)
    except (TypeError, ValueError):
        return str(arg)


def _convert_result(result, ctx) -> Any:
    """Convert QuickJS result to JSON-serializable Python object."""
    if result is None:
        return None
    if isinstance(result, (bool, int, float, str)):
        return result
    if isinstance(result, list):
        return [_convert_result(item, ctx) for item in result]
    if isinstance(result, dict):
        return {k: _convert_result(v, ctx) for k, v in result.items()}

    # Try to convert via JSON serialization in JS
    try:
        # QuickJS objects might have a json() method or need JSON.stringify
        if hasattr(result, 'json'):
            return json.loads(result.json())
    except Exception:
        pass

    # Last resort: string representation
    return str(result)


# Type alias for cleaner imports
JSResult = Dict[str, Any]
