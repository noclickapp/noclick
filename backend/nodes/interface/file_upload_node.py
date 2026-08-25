# Interface file upload node for accepting file uploads in the workflow interface.
# Renders a file upload zone with configurable accepted types and size limits.
# When resource_ids are set (by the frontend after uploading to R2), execute()
# resolves them to presigned download URLs for downstream nodes.

import logging
from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig
# Hoisted from the inline `execute()` import: triggers `cloudflare` +
# `boto3` regex compiles, which were caught blocking the asyncio loop on
# first-call paths (file_upload_node.py:67 in event_loop.block stacks,
# 2026-05-21 incident).
from utils.r2_cloudflare import get_public_download_url

logger = logging.getLogger(__name__)


class FileUploadConfig(BaseModel):
    """Configuration for the file upload interface component."""

    accepted_types: str = Field(default="", title="Accepted Types",
                                json_schema_extra={"ui:placeholder": ".pdf,.csv,.xlsx",
                                                   "ui:help": "Comma-separated file extensions"})
    max_size_mb: str = Field(default="10", title="Max Size (MB)",
                             json_schema_extra={"ui:placeholder": "10"})
    resource_ids: str = Field(default="", title="Resource IDs",
                              json_schema_extra={"ui:hidden": True})


class FileUploadInterfaceNodeConfig(NodeConfig[FileUploadConfig, None]):
    """Full configuration for file upload interface node (no credentials)."""
    pass


class FileUploadInterfaceNode(WorkflowNode):
    """File upload interface node — accepts file uploads from users."""

    grid_layout = {"defaultW": 4, "defaultH": 3, "minW": 3, "minH": 2}
    edit_examples = [
        "Change accepted file types to only CSV/PDF",
        "Increase max file size limit to 50MB",
        "Pre-populate with uploaded files",
        "Allow multiple files or single file only",
        "Show a custom drag-and-drop message",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return FileUploadInterfaceNodeConfig

    def _parse_resource_ids(self, raw: str) -> List[str]:
        return [rid.strip() for rid in raw.split(",") if rid.strip()]

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config: FileUploadConfig = self._config.config if self._config else FileUploadConfig()

        files = []
        if config.resource_ids:
            ids = self._parse_resource_ids(config.resource_ids)
            from utils.database_pool import get_native_pool
            pool = get_native_pool()

            for rid in ids:
                row = await pool.fetchrow(
                    "SELECT name, mime_type, size_bytes, storage_ref "
                    "FROM workflow_resources WHERE id = $1 AND workflow_id = $2",
                    rid,
                    self.workflow_id,
                )
                if row and row.get("storage_ref"):
                    url = get_public_download_url(row["storage_ref"])
                    files.append({
                        "resource_id": rid,
                        "name": row["name"],
                        "mime_type": row.get("mime_type"),
                        "size_bytes": row.get("size_bytes", 0),
                        "download_url": url,
                    })

        output = {
            "type": "file_upload",
            "accepted_types": config.accepted_types,
            "max_size_mb": config.max_size_mb,
            "files": files,
            **inputs,
        }
        await self.emit(output)
        return output
