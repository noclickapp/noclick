# Universal interface file node — displays any uploaded/linked file
# (image, audio, video, PDF, or generic download) in the workflow interface.
# Supports uploaded R2 resources via resource_id or a direct URL from
# upstream nodes / config, and detects the media type for the renderer.

import logging
import os
from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus"}
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
_PDF_EXTS = {".pdf"}


def _detect_media_type(mime: Optional[str], name_or_url: Optional[str]) -> str:
    """Detect the media type from a MIME type first, else a filename/URL extension."""
    mime = (mime or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime == "application/pdf":
        return "pdf"

    path = (name_or_url or "").split("?", 1)[0].split("#", 1)[0]
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _PDF_EXTS:
        return "pdf"
    return "file"


class FileConfig(BaseModel):
    """Configuration for the universal file interface component."""

    src: str = Field(default="", title="Source URL",
                     json_schema_extra={"ui:placeholder": "https://example.com/file.pdf"})
    resource_id: str = Field(default="", title="Resource ID",
                             json_schema_extra={"ui:hidden": True})
    file_name: str = Field(default="", title="File Name",
                           json_schema_extra={"ui:placeholder": "document.pdf"})
    alt: Optional[str] = Field(default=None, title="Alt Text",
                               json_schema_extra={"ui:placeholder": "File description"})


class FileInterfaceNodeConfig(NodeConfig[FileConfig, None]):
    """Full configuration for file interface node (no credentials)."""
    pass


class FileInterfaceNode(WorkflowNode):
    """Universal file interface node — displays any file: image, audio, video, PDF, or download."""

    grid_layout = {"defaultW": 6, "defaultH": 5, "minW": 3, "minH": 3}
    edit_examples = [
        "Set the file source URL dynamically from upstream data",
        "Use an uploaded file resource (image, audio, video, PDF, or any file)",
        "Change the displayed file name or alt text",
        "Display a generated image, audio clip, or video",
        "Set a default file from config or upstream",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return FileInterfaceNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config: FileConfig = self._config.config if self._config else FileConfig()
        url = inputs.get("value", inputs.get("src", config.src))
        file_name = inputs.get("file_name", config.file_name)
        mime: Optional[str] = None

        if config.resource_id:
            from utils.database_pool import get_native_pool
            row = await get_native_pool().fetchrow(
                """
                SELECT storage_ref, mime_type, name
                FROM workflow_resources
                WHERE id = $1 AND workflow_id = $2
                """,
                config.resource_id,
                self.workflow_id,
            )
            if row and row.get("storage_ref"):
                from utils.r2_cloudflare import get_public_download_url
                url = get_public_download_url(row["storage_ref"])
                mime = row.get("mime_type")
                if not file_name and row.get("name"):
                    file_name = row["name"]

        if not file_name and url:
            file_name = os.path.basename(url.split("?", 1)[0].split("#", 1)[0])

        media_type = _detect_media_type(mime, file_name or url)
        output = {
            "url": url,
            "src": url,
            "type": media_type,
            "file_name": file_name,
            "mime_type": mime,
        }
        await self.emit(output)
        return output
