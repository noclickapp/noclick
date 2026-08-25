"""
Filesystem node for workflow automation.

Connects to AI Agent nodes via top→bottom handle (like tool/alarm nodes).
Provides a persistent volume that the agent's sandbox mounts, so files
written by the agent survive across executions. Supports two modes:
- common: single shared volume for all executions
- per_conversation_key: isolated volume per conversation_key
"""

import hashlib
import logging
import posixpath
import uuid as uuid_module
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Upload Tool Definition
# ============================================================================

UPLOAD_FILE_TOOL_NAME = "upload_file"
UPLOAD_FILE_TOOL_DESCRIPTION = (
    "Upload a file from your sandbox to the workflow's resource storage and get a public URL. "
    "Use this when you need a URL for a file (e.g., to send an image via Telegram, attach a "
    "document to an email, or pass a file to a downstream node). Provide an absolute path to "
    "any file the sandbox can read (e.g., '/tmp/report.pdf', or '/workspace/...' if a "
    "workspace volume is mounted)."
)
UPLOAD_FILE_PARAMETERS: List[Dict[str, Any]] = [
    {
        "name": "file_path",
        "type": "string",
        "description": "Absolute path to the file in your sandbox (e.g., '/tmp/report.pdf')",
        "required": True,
    },
    {
        "name": "name",
        "type": "string",
        "description": "Display name for the uploaded resource (e.g., 'Monthly Report'). Defaults to filename.",
        "required": False,
    },
]


def get_upload_tool_definition() -> Dict[str, Any]:
    """Return the upload_file tool definition dict."""
    return {
        "type": "tool_definition",
        "tool_type": "filesystem",
        "tool_name": UPLOAD_FILE_TOOL_NAME,
        "tool_description": UPLOAD_FILE_TOOL_DESCRIPTION,
        "parameters": UPLOAD_FILE_PARAMETERS,
    }


# ============================================================================
# Volume Naming
# ============================================================================


def get_volume_name(
    workflow_id: str,
    node_id: str,
    volume_mode: str = "common",
    conversation_key: Optional[str] = None,
) -> str:
    """
    Compute a deterministic volume name.

    Common mode:  noclick-fs-{workflow_id}-{node_id_hash}
    Per-CK mode:  noclick-fs-{workflow_id}-{node_id_hash}-{ck_hash}

    Node ID hash is used because volume names have character restrictions
    and node IDs can be long/contain special characters.
    """
    # Volume names: lowercase alphanumeric + hyphens, max 64 chars
    node_hash = hashlib.sha256(node_id.encode()).hexdigest()[:8]
    base = f"noclick-fs-{workflow_id}-{node_hash}"

    if volume_mode == "per_conversation_key" and conversation_key:
        ck_hash = hashlib.sha256(str(conversation_key).encode()).hexdigest()[:12]
        return f"{base}-{ck_hash}"

    return base


# ============================================================================
# Configuration
# ============================================================================


class FilesystemConfig(BaseModel):
    """Configuration for the filesystem node."""

    volume_mode: str = Field(
        "common",
        title="Volume Mode",
        description="How volumes are scoped across executions",
        json_schema_extra={
            "enum": ["common", "per_conversation_key"],
            "enumNames": [
                "Shared (all executions)",
                "Per Conversation Key (isolated per user)",
            ],
            "x-enum-searchable": True,
        },
    )
    mount_path: str = Field(
        "/workspace",
        title="Mount Path",
        description="Absolute folder path where the files appear inside the agent's sandbox",
        json_schema_extra={
            "ui:help": "The agent reads/writes files at this path (e.g. /workspace or /assets). Files persist across executions. A missing leading slash is added automatically.",
            "ui:placeholder": "/workspace",
        },
    )
    file_browser: Optional[str] = Field(
        default=None,
        title="Files",
        json_schema_extra={
            "ui:widget": "file_browser",
        },
    )

    @field_validator("mount_path")
    @classmethod
    def _canonical_mount_path(cls, v: str) -> str:
        """Canonicalize the workspace mount to an absolute path.

        Normalize fixable input such as ``assets``, trailing slashes, and dot
        segments; reject a mount that resolves to the filesystem root.
        """
        path = (v or "").strip()
        if not path:
            return "/workspace"
        if not path.startswith("/"):
            path = "/" + path
        # normpath on an absolute path resolves every ".." against root, so the
        # result is always canonical; only a bare "/" is left to reject.
        path = posixpath.normpath(path)
        if path == "/":
            raise ValueError(
                "mount_path must be an absolute folder path like /workspace or /assets"
            )
        return path


class FilesystemNodeConfig(NodeConfig[FilesystemConfig, None]):
    """Full configuration for Filesystem node (no credentials needed)."""

    pass


# ============================================================================
# Filesystem Node Implementation
# ============================================================================


class FilesystemNode(WorkflowNode):
    """
    Filesystem node for persistent agent storage.

    Connects to AI agent nodes via top→bottom handle edges (same pattern as tool/alarm nodes).
    During workflow execution, returns filesystem_config with volume mode and mount path.
    The AgentNode picks this up and mounts the corresponding volume into the sandbox.
    """

    edit_examples = [
        "Switch to per-conversation storage mode",
        "Change mount path to /data",
        "Use shared volume for all executions",
        "Isolate storage per user conversation",
        "Change mount path to /tmp",
        "View files in persistent storage",
        "Browse uploaded resources",
    ]

    @classmethod
    def get_config_model(cls) -> type:
        return FilesystemNodeConfig

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: uuid_module.UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Load file listing from the node's volume for the file_browser widget.

        Context may include volume_mode and conversation_key to resolve
        the correct volume for per-conversation-key mode.
        """
        if field_name != "file_browser":
            return {"value": None}

        ctx = context or {}
        volume_mode = ctx.get("volume_mode", "common")
        conversation_key = ctx.get("conversation_key")
        volume_name = get_volume_name(
            str(workflow_id), node_id, volume_mode, conversation_key
        )

        try:
            from utils.access_control import Permission, check_resource_access
            from utils.volume_backend import get_volume_backend

            # load_field_value is reached through a workflow-access-gated
            # handler, but VIEW is sufficient for that handler.  Re-check the
            # effective permission here before minting a write capability so a
            # direct or future caller cannot accidentally widen access.
            can_upload = False
            if pool is not None:
                async with pool.acquire() as conn:
                    access = await check_resource_access(
                        conn, str(user_id), "workflow", str(workflow_id)
                    )
                can_upload = access.permission in (Permission.EDIT, Permission.OWNER)

            listing = await get_volume_backend().list_entries(volume_name)
            value = {
                "files": listing["entries"],
                "volume_name": volume_name,
                "count": len(listing["entries"]),
            }
            if can_upload:
                # Deferred: utils.agent_workspace imports this module at load time.
                from utils.agent_workspace import upload_url_path

                value["upload_url_path"] = upload_url_path(volume_name)
            if not listing["exists"]:
                value["empty"] = True
            return {"value": value}

        except Exception as e:
            logger.warning(f"[FilesystemNode] Error listing volume {volume_name}: {e}")
            return {
                "value": {
                    "files": [],
                    "volume_name": volume_name,
                    "count": 0,
                    "error": str(e),
                }
            }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return filesystem config and upload tool for the agent to pick up.

        The AgentNode reads this output and:
        1. Mounts the corresponding volume into the sandbox
        2. Injects the upload_file tool so the agent can publish files as URLs
        """
        config = (
            self.config.config
            if self.config and isinstance(self.config, FilesystemNodeConfig)
            else None
        )
        volume_mode = config.volume_mode if config else "common"
        mount_path = config.mount_path if config else "/workspace"

        return {
            "type": "filesystem_config",
            "volume_mode": volume_mode,
            "mount_path": mount_path,
            "node_id": self.node_id,
            "tools": [get_upload_tool_definition()],
        }
