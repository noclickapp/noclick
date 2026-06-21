"""
Central seam for nodes that produce binary media (downloaded or generated).

Instead of base64-encoding bytes inline into its output (the unusable "wall of
characters" shape), a node returns a ``BinaryOutput`` marker carrying the raw
bytes + content type + filename. ``resolve_binary_outputs`` — run by
``WorkflowNode.run`` right after ``execute`` — deep-walks the output, stores each
marker's bytes in R2 via the shared writer, and replaces it with a usable
``{url, mime_type, name, size_bytes}`` file reference (the same shape the HTTP
node emits). When there's no workflow context to store into, it falls back to a
self-describing base64 dict so context-less runs still return the data.

This keeps the bytes -> usable-URL logic in ONE place: a media node just hands
back ``BinaryOutput(...)`` and the resolver does the rest. Outputs with no marker
are returned untouched (cheap pre-scan), so non-media nodes pay nothing.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from utils.resource_store import create_resource_from_bytes


@dataclass
class BinaryOutput:
    """A node's raw binary media result, resolved to a file reference by the
    executor. ``metadata`` lets a node attach extra fields (e.g. timestamps) that
    are merged alongside the resolved ``{url, ...}``."""

    data: bytes
    content_type: str = "application/octet-stream"
    filename: str = "download"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def _base64_ref(self) -> Dict[str, Any]:
        return {
            "base64": base64.b64encode(self.data).decode("utf-8"),
            "mime_type": self.content_type,
            "name": self.filename,
            "size_bytes": len(self.data),
            "is_base64": True,
            **self.metadata,
        }


def _contains_marker(value: Any) -> bool:
    """Fast read-only scan: True if a BinaryOutput hides anywhere in ``value``.
    Recurses only into containers, so a large text/JSON output is cheap."""
    if isinstance(value, BinaryOutput):
        return True
    if isinstance(value, dict):
        return any(_contains_marker(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_marker(v) for v in value)
    return False


async def resolve_binary_outputs(
    value: Any,
    *,
    user_id: Optional[str],
    workflow_id: Optional[str],
    node_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> Any:
    """Replace every ``BinaryOutput`` in ``value`` with a stored ``{url, mime_type,
    name, size_bytes}`` reference (or a base64 dict when there's no workflow
    context to store into). Non-marker data is returned unchanged."""
    if not _contains_marker(value):
        return value

    has_context = bool(user_id and workflow_id)

    async def store(marker: BinaryOutput) -> Dict[str, Any]:
        if not has_context:
            return marker._base64_ref()
        ref = await create_resource_from_bytes(
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
            organization_id=organization_id,
            body=marker.data,
            content_type=marker.content_type,
            filename=marker.filename,
        )
        return {
            "url": ref["download_url"],
            "mime_type": ref["mime_type"],
            "name": ref["name"],
            "size_bytes": ref["size_bytes"],
            **marker.metadata,
        }

    async def walk(v: Any) -> Any:
        if isinstance(v, BinaryOutput):
            return await store(v)
        if isinstance(v, dict):
            return {k: await walk(item) for k, item in v.items()}
        if isinstance(v, list):
            return [await walk(item) for item in v]
        if isinstance(v, tuple):
            return tuple([await walk(item) for item in v])
        return v

    return await walk(value)
