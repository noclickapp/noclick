"""Named-volume backend — durable file storage agents and nodes share.

Registry seam (same pattern as nodes.agent.harness_registry): the hosted
platform registers its volume backend on first lookup; without it, volumes
are directories under ~/.noclick/volumes/<name>/ — the same directories the
local sandbox runtimes use as their working directories, so the
FilesystemNode file browser and the workspace Files panel list exactly what
local agents wrote.

Backend surface:
    async list_entries(name, path="/", recursive=False)
        -> {exists, entries: [{path, type, size, mtime}]}   (type "dir" or "file")
    async list_files(name) -> {exists, files: [{path, size, mtime}]}   (recursive)
    def  iter_file(name, path) -> async byte-chunk iterator (VolumeFileNotFound)
    async write_file(name, path, data) -> None   (creates the volume if missing)
    async write_files(name, files) -> None       ({path: data}, in one commit)
    async delete_file(name, path) -> None        (idempotent — no-op if absent)
    async remove_path(name, path, recursive=False) -> None
        (a file or a folder; idempotent; a non-empty folder needs recursive,
        else VolumeDirectoryNotEmpty)
    async copy_file(name, src, dst) -> None      (one file, replacing dst)
    async delete_volume(name) -> bool
    async list_volume_names() -> [str]
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class VolumeFileNotFound(Exception):
    """The requested file (or volume) does not exist."""


class VolumeDirectoryNotEmpty(Exception):
    """A folder with entries was removed without ``recursive``."""


class VolumeBackend(Protocol):
    """The contract every volume backend implements (structural typing —
    the hosted implementation registers itself; no inheritance required)."""

    async def list_entries(self, name: str, path: str = "/", recursive: bool = False) -> Dict[str, Any]: ...
    async def list_files(self, name: str) -> Dict[str, Any]: ...
    async def iter_file(self, name: str, path: str) -> Any: ...
    async def write_file(self, name: str, path: str, data: bytes) -> None: ...
    async def write_files(self, name: str, files: Dict[str, bytes]) -> None: ...
    async def delete_file(self, name: str, path: str) -> None: ...
    async def remove_path(self, name: str, path: str, recursive: bool = False) -> None: ...
    async def copy_file(self, name: str, src: str, dst: str) -> None: ...
    async def delete_volume(self, name: str) -> bool: ...
    async def list_volume_names(self) -> List[str]: ...


_backend: Optional[VolumeBackend] = None
_initialized = False


def register_volume_backend(backend: VolumeBackend) -> None:
    global _backend
    _backend = backend


def get_volume_backend() -> VolumeBackend:
    _ensure_initialized()
    assert _backend is not None
    return _backend


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    if _backend is not None:
        # The hosted platform registered its backend at start-up. Public
        # code never reaches for it by name — the edition bootstrap handles registration.
        return
    register_volume_backend(LocalVolumeBackend())
    logger.info("[VolumeBackend] Using local directory volume backend")


def clear() -> None:
    """Reset registration state (tests)."""
    global _backend, _initialized
    _backend = None
    _initialized = False


def workspace_volume_name(
    workflow_id: str, node_id: str, conversation_key: str
) -> str:
    """Per-(workflow, node, conversation) agent-workspace volume name.

    Same `noclick-<family>-<workflow>` shape every agent volume family uses,
    so workflow-deletion cleanup (is_workflow_volume) sweeps these too.
    """
    import hashlib

    node_hash = hashlib.sha256(str(node_id).encode()).hexdigest()[:8]
    ck_hash = hashlib.sha256(str(conversation_key).encode()).hexdigest()[:12]
    return f"noclick-ws-{workflow_id}-{node_hash}-{ck_hash}"


def noclick_home() -> Path:
    """Base directory for all local state. NOCLICK_HOME lets a second install
    (or a throwaway test) stay fully isolated from the default ~/.noclick."""
    return Path(os.environ.get("NOCLICK_HOME") or (Path.home() / ".noclick"))


def local_volume_root() -> Path:
    return noclick_home() / "volumes"


class LocalVolumeBackend:
    """Volumes as local directories under ~/.noclick/volumes/<name>/."""

    _CHUNK = 256 * 1024

    def _dir(self, name: str) -> Path:
        # Volume names are backend-generated slugs; refuse anything path-like.
        if "/" in name or name.startswith("."):
            raise ValueError(f"invalid volume name: {name!r}")
        return local_volume_root() / name

    def _file(self, name: str, path: str) -> Path:
        base = self._dir(name).resolve()
        target = (base / path.lstrip("/")).resolve()
        if not str(target).startswith(str(base) + os.sep) and target != base:
            raise ValueError(f"path escapes volume: {path!r}")
        return target

    async def list_entries(self, name: str, path: str = "/", recursive: bool = False) -> Dict[str, Any]:
        base = self._dir(name)
        target = self._file(name, path)
        if not base.is_dir() or not target.is_dir():
            return {"exists": False, "entries": []}
        children = target.rglob("*") if recursive else target.iterdir()
        entries = []
        for child in sorted(children):
            stat = child.stat()
            entries.append({
                "path": str(child.relative_to(base)),
                "type": "dir" if child.is_dir() else "file",
                "size": stat.st_size if child.is_file() else 0,
                "mtime": int(stat.st_mtime),
            })
        return {"exists": True, "entries": entries}

    async def list_files(self, name: str) -> Dict[str, Any]:
        base = self._dir(name)
        if not base.is_dir():
            return {"exists": False, "files": []}
        files: List[Dict[str, Any]] = []
        for child in base.rglob("*"):
            if child.is_file():
                stat = child.stat()
                files.append({
                    "path": str(child.relative_to(base)),
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                })
        files.sort(key=lambda f: f["path"])
        return {"exists": True, "files": files}

    async def iter_file(self, name: str, path: str):
        target = self._file(name, path)
        if not target.is_file():
            raise VolumeFileNotFound(f"{name}:{path}")

        async def _chunks():
            with open(target, "rb") as f:
                while True:
                    chunk = f.read(self._CHUNK)
                    if not chunk:
                        return
                    yield chunk

        return _chunks()

    async def write_file(self, name: str, path: str, data: bytes) -> None:
        target = self._file(name, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    async def write_files(self, name: str, files: Dict[str, bytes]) -> None:
        for path, data in files.items():
            await self.write_file(name, path, data)

    async def delete_file(self, name: str, path: str) -> None:
        target = self._file(name, path)
        if target.is_file():
            target.unlink()

    async def remove_path(self, name: str, path: str, recursive: bool = False) -> None:
        import shutil

        target = self._file(name, path)
        if target.is_dir():
            if not recursive and any(target.iterdir()):
                raise VolumeDirectoryNotEmpty(f"{name}:{path}")
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    async def copy_file(self, name: str, src: str, dst: str) -> None:
        import shutil

        source = self._file(name, src)
        if not source.is_file():
            raise VolumeFileNotFound(f"{name}:{src}")
        target = self._file(name, dst)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    async def delete_volume(self, name: str) -> bool:
        import shutil

        base = self._dir(name)
        if not base.is_dir():
            return False
        shutil.rmtree(base, ignore_errors=True)
        return True

    async def list_volume_names(self) -> List[str]:
        root = local_volume_root()
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir())
