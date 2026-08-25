"""Read-side access to an agent conversation's persistent workspace.

Backs the chat file view by listing the selected workspace and serving files
through signed streaming routes. A wired FilesystemNode supplies the volume
and mount path; otherwise a keyed conversation uses its default workspace.
One-off conversations have no durable workspace. Reads use the registered
volume backend, and remote backends may expose writes after a short commit
delay, so the UI owns refresh. File URLs are expiring JWT capabilities over
one volume and path.
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import jwt

from mcp_adapter.auth.tokens import get_mcp_signing_key
# The workspace read side follows the registered runtime's mount decision.
from utils.capabilities import WORKSPACE_VOLUME, capability

# Resolved per call, not at import: a platform registers during start-up, and
# binding here would capture whatever was true when this module happened to be
# imported first.
_FALLBACK_WORKSPACE_MOUNT = "/workspace"


def _workspace_mount() -> str:
    workspace = capability(WORKSPACE_VOLUME)
    return workspace.mount if workspace else _FALLBACK_WORKSPACE_MOUNT


def _workspace_volume_name(*args, **kwargs):
    """Return the registered durable-workspace name, if available."""
    workspace = capability(WORKSPACE_VOLUME)
    if workspace is None:
        return None
    return workspace.volume_name_for(*args, **kwargs)
from nodes.filesystem_node import get_volume_name as get_filesystem_volume_name

logger = logging.getLogger(__name__)

WORKSPACE_FILE_AUDIENCE = "noclick-workspace-file"
# Upload tokens are volume-scoped (the filename is chosen at upload time), so
# they get their own audience — a read token can never authorize a write.
WORKSPACE_UPLOAD_AUDIENCE = "noclick-workspace-upload"
FILE_TOKEN_TTL_SECONDS = 6 * 3600
# Write capabilities are more sensitive than per-file read links.  The UI gets
# a fresh one whenever it refreshes either file listing, so it does not need to
# remain usable for the full read-link lifetime.
UPLOAD_TOKEN_TTL_SECONDS = 15 * 60
# Listing cap — a workspace this large is degenerate; the UI shows "truncated".
MAX_LIST_ENTRIES = 2000


@dataclass
class WorkspaceSource:
    """Where a conversation's durable workspace lives."""

    volume_name: str
    mount_path: str


def resolve_workspace_source(
    workflow_id: str,
    agent_node_id: str,
    conversation_key: Optional[str],
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> Optional[WorkspaceSource]:
    """Resolve the workspace source from the stored graph:
    a FilesystemNode wired into the agent is the workspace (explicit persistent
    storage); else a conversation gets the per-CK default workspace volume;
    else there is no durable workspace (None).

    Edge matching REPLICATES the runtime's provider scoping
    (AgentNode._is_wired_tool_provider: ``source``/``target`` keys, and
    ``targetHandle == "bottom"``) — the panel must resolve the same volume the
    runtime mounts, so a shape the runtime rejects (fs wired on a
    non-tools handle) must be rejected here too, not tolerated. Known caveat:
    with MULTIPLE FilesystemNodes wired to one agent the runtime mounts
    ``filesystem_configs[0]`` by node-output order, which this stored-order
    scan cannot reproduce exactly — the shared-seam refactor tracks that."""
    for edge in edges or []:
        if edge.get("target") != agent_node_id or edge.get("targetHandle") != "bottom":
            continue
        source_id = edge.get("source")
        fs = next(
            (
                n for n in (nodes or [])
                if n.get("id") == source_id and n.get("type") == "filesystem"
            ),
            None,
        )
        if not fs:
            continue
        config = fs.get("config") or (fs.get("data") or {}).get("config") or {}
        volume_mode = config.get("volume_mode") or "common"
        return WorkspaceSource(
            volume_name=get_filesystem_volume_name(
                str(workflow_id), fs["id"], volume_mode, conversation_key
            ),
            mount_path=config.get("mount_path") or _workspace_mount(),
        )
    if conversation_key:
        if capability(WORKSPACE_VOLUME) is not None:
            # A registered backend supplies the canonical volume name.
            volume_name = _workspace_volume_name(
                "ws", str(workflow_id), agent_node_id, conversation_key
            )
        else:
            # The local backend stores workspaces in its volume directory.
            from utils.volume_backend import workspace_volume_name

            volume_name = workspace_volume_name(
                str(workflow_id), agent_node_id, str(conversation_key)
            )
        return WorkspaceSource(
            volume_name=volume_name,
            mount_path=_workspace_mount(),
        )
    return None


async def list_workspace_files(volume_name: str) -> Dict[str, Any]:
    """Recursive listing of a workspace volume via the volume backend.

    Returns {exists, truncated, files: [{path, size, mtime}]} — a volume that
    was never created (agent hasn't written anything) is exists=False with an
    empty list, not an error."""
    from utils.volume_backend import get_volume_backend

    listing = await get_volume_backend().list_files(volume_name)
    if not listing["exists"]:
        return {"exists": False, "truncated": False, "files": []}
    files = listing["files"]
    truncated = len(files) > MAX_LIST_ENTRIES
    return {"exists": True, "truncated": truncated, "files": files[:MAX_LIST_ENTRIES]}


def mint_file_token(volume_name: str, path: str, ttl_seconds: int = FILE_TOKEN_TTL_SECONDS) -> str:
    """Capability token for one file: JWT over (volume, path) with expiry."""
    return jwt.encode(
        {
            "aud": WORKSPACE_FILE_AUDIENCE,
            "exp": int(time.time()) + ttl_seconds,
            "vol": volume_name,
            "path": path,
        },
        get_mcp_signing_key(),
        algorithm="HS256",
    )


def verify_file_token(token: str) -> Optional[Dict[str, str]]:
    """{vol, path} for a valid, unexpired token; None otherwise."""
    try:
        claims = jwt.decode(
            token,
            get_mcp_signing_key(),
            algorithms=["HS256"],
            audience=WORKSPACE_FILE_AUDIENCE,
        )
    except jwt.PyJWTError:
        return None
    vol, path = claims.get("vol"), claims.get("path")
    if not vol or not path:
        return None
    return {"vol": vol, "path": path}


def file_url_path(volume_name: str, path: str) -> str:
    """Relative URL (on the backend origin) serving this file — the FE joins it
    with the socket origin. Append &dl=1 for a download disposition."""
    from urllib.parse import quote

    return f"/agent/workspace/file?token={quote(mint_file_token(volume_name, path))}"


def mint_upload_token(
    volume_name: str, ttl_seconds: int = UPLOAD_TOKEN_TTL_SECONDS
) -> str:
    """Capability token authorizing file uploads into one volume."""
    return jwt.encode(
        {
            "aud": WORKSPACE_UPLOAD_AUDIENCE,
            "exp": int(time.time()) + ttl_seconds,
            "vol": volume_name,
        },
        get_mcp_signing_key(),
        algorithm="HS256",
    )


def verify_upload_token(token: str) -> Optional[str]:
    """Volume name for a valid, unexpired upload token; None otherwise."""
    try:
        claims = jwt.decode(
            token,
            get_mcp_signing_key(),
            algorithms=["HS256"],
            audience=WORKSPACE_UPLOAD_AUDIENCE,
        )
    except jwt.PyJWTError:
        return None
    return claims.get("vol") or None


def upload_url_path(volume_name: str) -> str:
    """Relative URL (on the backend origin) accepting uploads into this volume —
    the FE appends &path=<filename> and POSTs the raw bytes."""
    from urllib.parse import quote

    return f"/agent/workspace/upload?token={quote(mint_upload_token(volume_name))}"
