"""Single writer for binary workflow resources (R2 + the workflow_resources table).

A node or handler that has produced bytes — a generated image, an email
attachment, an agent-uploaded file, an HTTP download — turns them into a
resolvable ``resource_id`` by calling :func:`create_resource_from_bytes`. This
replaces the "upload to R2 + INSERT workflow_resources" block that was
copy-pasted across the agent node, agent tool execution, the MCP delegated tools,
and inbound-email attachments, and is the seam the HTTP node's file-download
path also uses.

Lives in ``utils`` (depends only on ``utils.r2_cloudflare`` /
``utils.database_pool``) so both nodes and other utils can import it without a
layering cycle.
"""

import logging
import uuid
from typing import Any, Dict, Optional

from utils.database_pool import get_native_pool
from utils.r2_cloudflare import get_public_download_url, upload_bytes_to_r2_async

logger = logging.getLogger(__name__)

RESOURCE_BUCKET = "workflow-resources"


def resource_type_for_mime(mime: str) -> str:
    """Map a MIME type to a ``workflow_resources.resource_type`` CHECK value."""
    m = (mime or "").lower()
    if m.startswith("image/"):
        return "image"
    if m.startswith("video/"):
        return "video"
    if m.startswith("audio/"):
        return "audio"
    if (
        m == "application/pdf"
        or m.startswith("text/")
        or "word" in m
        or "officedocument" in m
        or "spreadsheet" in m
        or "presentation" in m
    ):
        return "document"
    return "file"


async def create_resource_from_bytes(
    *,
    user_id: str,
    workflow_id: str,
    node_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    body: bytes,
    content_type: str,
    filename: str,
    resource_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Upload *body* to R2 and record a ``workflow_resources`` row.

    Returns ``{resource_id, name, mime_type, size_bytes, storage_ref,
    download_url}`` — the shape every consumer (and the media resolver) expects.
    The storage key is ``{owner}/{workflow}/{resource_id}/{filename}``.
    """
    resource_id = str(uuid.uuid4())
    storage_ref = f"{user_id}/{workflow_id}/{resource_id}/{filename}"
    rtype = resource_type or resource_type_for_mime(content_type)
    size_bytes = len(body)

    await upload_bytes_to_r2_async(
        bucket=RESOURCE_BUCKET, key=storage_ref, body=body, content_type=content_type
    )

    await get_native_pool().execute(
        """
        INSERT INTO workflow_resources
            (id, owner_id, organization_id, workflow_id, node_id, resource_type,
             name, mime_type, size_bytes, storage_ref, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        # metadata passed raw — the runtime pool's asyncpg jsonb codec serializes
        # it; json.dumps()-ing here would double-encode (see CLAUDE.md).
        resource_id, user_id, organization_id, workflow_id, node_id, rtype,
        filename, content_type, size_bytes, storage_ref, metadata or {},
    )

    logger.info(
        f"[resource_store] stored {rtype} resource {resource_id} "
        f"({size_bytes} bytes, {content_type}) at {storage_ref}"
    )
    return {
        "resource_id": resource_id,
        "name": filename,
        "mime_type": content_type,
        "size_bytes": size_bytes,
        "storage_ref": storage_ref,
        "download_url": get_public_download_url(storage_ref),
    }
