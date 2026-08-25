"""Bash runtime for the OpenAI Agents SDK-backed Agent.

The SDK has no built-in shell tool, so workflow agents expose an
``execute_bash`` FunctionTool backed by this runtime registry. An edition
may register another implementation before first use; otherwise commands
run as local subprocesses with durable per-conversation workspaces. Wired
FilesystemNodes, git mounts, and user environment variables shape the
workspace without gating access to the shell tool.

Runtime implementations provide ``persistent``, ``mount_path``, and async
methods to initialize, run commands, read files, and close resources.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

_LOCAL_TIMEOUT_S = 600


class AgentSandboxRuntime(Protocol):
    """Structural contract implemented by every registered runtime."""

    mount_path: str

    @property
    def persistent(self) -> bool: ...
    async def ensure_sandbox(self) -> bool: ...
    async def run_bash(self, command: str) -> Dict[str, Any]: ...
    async def read_file(self, path: str) -> Optional[bytes]: ...
    async def close(self) -> None: ...

_runtime_factory = None
_initialized = False


def register_sandbox_runtime(factory) -> None:
    global _runtime_factory
    _runtime_factory = factory


def create_sandbox_runtime(**kwargs) -> "AgentSandboxRuntime":
    _ensure_initialized()
    assert _runtime_factory is not None
    return _runtime_factory(**kwargs)


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    if _runtime_factory is not None:
        # An edition-specific runtime was registered at start-up.
        return
    register_sandbox_runtime(LocalSandboxRuntime)
    logger.info("[sandbox] Using local subprocess sandbox runtime")


def clear() -> None:
    """Reset registration state (tests)."""
    global _runtime_factory, _initialized
    _runtime_factory = None
    _initialized = False


class LocalSandboxRuntime:
    """Run execute_bash on the local machine.

    The working directory selects the command workspace:
      - FilesystemNode wired → the node's local volume directory (shared
        with utils.volume_backend, so the file browser lists these files);
      - conversation-keyed run → a durable per-conversation workspace dir;
      - one-off run → a temp dir wiped on close.

    ``mount_path`` (what the model is told, e.g. /workspace) maps onto the
    working directory: commands run with it as cwd, and reads translate a
    mount-path prefix back to it.
    """

    def __init__(
        self,
        *,
        filesystem_configs: List[Dict[str, Any]],
        workflow_id: Optional[str],
        node_id: Optional[str],
        conversation_key: Optional[str] = None,
        sandbox_setups: Optional[List[Dict[str, Any]]] = None,
        user_env: Optional[Dict[str, str]] = None,
    ) -> None:
        if not workflow_id:
            raise ValueError("LocalSandboxRuntime requires workflow_id for workspace naming")

        # The runtime contract uses the first filesystem workspace source.
        self._fs_config = filesystem_configs[0] if filesystem_configs else None
        self._workflow_id = str(workflow_id)
        self._node_id = str(node_id) if node_id else None
        self._conversation_key = conversation_key
        self.sandbox_setups: List[Dict[str, Any]] = sandbox_setups or []
        self.user_env: Dict[str, str] = user_env or {}

        self.mount_path: str = (
            self._fs_config.get("mount_path", "/workspace")
            if self._fs_config else "/workspace"
        )

        self._workdir: Optional[Path] = None
        self._tempdir: Optional[tempfile.TemporaryDirectory] = None
        self._closed = False
        self._boot_error: Optional[str] = None
        self._boot_lock = asyncio.Lock()
        self._booted = False

    @property
    def persistent(self) -> bool:
        """Durable unless this is a ck-less one-off run (nothing to resume)."""
        return self._fs_config is not None or bool(self._conversation_key and self._node_id)

    def _resolve_workdir(self) -> Path:
        if self._fs_config is not None:
            from nodes.filesystem_node import get_volume_name
            from utils.volume_backend import local_volume_root

            name = get_volume_name(
                self._workflow_id,
                self._fs_config["node_id"],
                self._fs_config.get("volume_mode", "common"),
                self._conversation_key,
            )
            return local_volume_root() / name
        if self._conversation_key and self._node_id:
            from utils.volume_backend import local_volume_root, workspace_volume_name

            return local_volume_root() / workspace_volume_name(
                self._workflow_id, self._node_id, str(self._conversation_key)
            )
        self._tempdir = tempfile.TemporaryDirectory(prefix="noclick-sdk-sandbox-")
        return Path(self._tempdir.name)

    async def ensure_sandbox(self) -> bool:
        if self._closed:
            logger.warning("[sandbox] ensure_sandbox called after close — refusing")
            return False
        if self._booted:
            return True
        async with self._boot_lock:
            if self._closed or self._booted:
                return self._booted and not self._closed
            try:
                self._workdir = self._resolve_workdir()
                self._workdir.mkdir(parents=True, exist_ok=True)
                if self.sandbox_setups:
                    from nodes.agent.git_mounts import apply_git_mounts_local

                    await apply_git_mounts_local(self.sandbox_setups, str(self._workdir))
                self._booted = True
                logger.info("[sandbox] local sandbox ready at %s", self._workdir)
                return True
            except Exception as e:
                logger.error("[sandbox] local sandbox boot failed: %s", e, exc_info=True)
                self._boot_error = str(e)
                return False

    def _translate(self, path: str) -> Path:
        """Map a model-visible path onto the working directory."""
        mount = self.mount_path.rstrip("/")
        if path == mount or path.startswith(mount + "/"):
            rel = path[len(mount):].lstrip("/")
            return self._workdir / rel if rel else self._workdir
        if os.path.isabs(path):
            return Path(path)
        return self._workdir / path

    async def run_bash(self, command: str) -> Dict[str, Any]:
        if not await self.ensure_sandbox():
            detail = f": {self._boot_error}" if self._boot_error else ""
            return {"error": f"Sandbox unavailable{detail}"}

        env = {**os.environ, **self.user_env}
        shell_cmd = f"cd {shlex.quote(str(self._workdir))} && {command} </dev/null"
        try:
            process = await asyncio.create_subprocess_exec(
                "sh", "-c", shell_cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    process.communicate(), timeout=_LOCAL_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {"error": f"Command timed out after {_LOCAL_TIMEOUT_S}s"}
        except Exception as e:
            logger.error("[sandbox] run_bash failed: %s", e, exc_info=True)
            return {"error": f"Command execution failed: {e}"}

        return {
            "stdout": stdout_b.decode(errors="replace"),
            "stderr": stderr_b.decode(errors="replace"),
            "exit_code": process.returncode or 0,
        }

    async def read_file(self, path: str) -> Optional[bytes]:
        if not await self.ensure_sandbox():
            return None
        try:
            return self._translate(path).read_bytes()
        except Exception as e:
            logger.warning("[sandbox] read_file %s failed: %s", path, e)
            return None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None
