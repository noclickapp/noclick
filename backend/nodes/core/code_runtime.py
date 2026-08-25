"""Python execution backend for the serverless-function node.

Registry seam (same pattern as nodes.agent.harness_registry): an installation
may register an isolated compute backend on first lookup; otherwise user code
runs locally as a subprocess of this machine's Python, with requested pip
packages installed into a cached per-requirement-set venv.

A runner receives the fully wrapped function source (the node builds the
wrapper + result protocol) and returns the raw process output:
    {"stdout": str, "stderr": str, "exit_code": int}
"""

import asyncio
import hashlib
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# async (*, function_code, kwargs_json, pip_packages, hardware, timeout_seconds,
#        region, emit_status, user_id, organization_id) -> {stdout, stderr, exit_code}
PythonRuntime = Callable[..., Awaitable[Dict[str, Any]]]

_runtime: Optional[PythonRuntime] = None
_initialized = False


def register_python_runtime(runner: PythonRuntime) -> None:
    global _runtime
    _runtime = runner


def get_python_runtime() -> PythonRuntime:
    _ensure_initialized()
    assert _runtime is not None
    return _runtime


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    if _runtime is not None:
        # An installation registered its backend at start-up.
        return
    register_python_runtime(run_python_locally)
    logger.info("[CodeRuntime] Using local subprocess Python runtime")


def clear() -> None:
    """Reset registration state (tests)."""
    global _runtime, _initialized
    _runtime = None
    _initialized = False


# ── Local implementation ─────────────────────────────────────────────────


def _parse_packages(pip_packages: Optional[str]) -> list:
    packages = []
    for line in (pip_packages or "").replace(",", "\n").split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            packages.append(line)
    return packages


async def _ensure_venv(packages: list) -> str:
    """Create (or reuse) a venv holding *packages*; returns its python path.

    Cached under ~/.noclick/pyenvs/{hash-of-requirements} so repeated runs
    with the same requirement set skip the install entirely.
    """
    key = hashlib.sha256("\n".join(sorted(packages)).encode()).hexdigest()[:16]
    from utils.volume_backend import noclick_home

    venv_dir = noclick_home() / "pyenvs" / key
    python = venv_dir / "bin" / "python"
    marker = venv_dir / ".ready"
    if marker.exists():
        return str(python)

    logger.info(f"[CodeRuntime] Building venv for {len(packages)} package(s) → {venv_dir}")
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "venv", str(venv_dir),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"venv creation failed: {err.decode(errors='replace')[:500]}")

    proc = await asyncio.create_subprocess_exec(
        str(python), "-m", "pip", "install", "--quiet", *packages,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"pip install of {packages} failed: {err.decode(errors='replace')[:800]}"
        )
    marker.touch()
    return str(python)


async def run_python_locally(
    *,
    function_code: str,
    kwargs_json: str,
    pip_packages: Optional[str] = None,
    hardware: Any = None,
    timeout_seconds: int = 300,
    region: Optional[str] = None,
    emit_status=None,
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the wrapped function as a local subprocess.

    Hardware requests (GPU/CPU shapes) don't apply to local execution —
    the code runs on this machine and GPU selections are logged and ignored.
    """
    gpu_type = getattr(hardware, "gpu_type", None) if hardware else None
    if gpu_type and gpu_type != "none":
        logger.warning(
            f"[CodeRuntime] GPU '{gpu_type}' requested — local execution runs on "
            "this machine's hardware; the request is ignored."
        )

    packages = _parse_packages(pip_packages)
    if packages:
        if emit_status:
            await emit_status("building_image")
        python = await _ensure_venv(packages)
    else:
        python = sys.executable

    if emit_status:
        await emit_status("running")

    with tempfile.TemporaryDirectory(prefix="noclick-code-") as workdir:
        # The wrapper protocol reads kwargs from /tmp/input_kwargs.json; keep
        # everything inside the scratch dir and point the code at it via cwd.
        code_path = os.path.join(workdir, "user_function.py")
        kwargs_path = os.path.join(workdir, "input_kwargs.json")
        with open(code_path, "w") as f:
            f.write(function_code.replace("/tmp/input_kwargs.json", "input_kwargs.json"))
        with open(kwargs_path, "w") as f:
            f.write(kwargs_json)

        proc = await asyncio.create_subprocess_exec(
            python, code_path,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "stdout": "",
                "stderr": f"Execution timed out after {timeout_seconds}s",
                "exit_code": 124,
            }

    return {
        "stdout": stdout_b.decode(errors="replace"),
        "stderr": stderr_b.decode(errors="replace"),
        "exit_code": proc.returncode or 0,
    }
