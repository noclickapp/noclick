"""Single writer for binary workflow resources (R2 + the workflow_resources table).

A node or handler that has produced bytes — a generated image, an email
attachment, an agent-uploaded file, an HTTP download — turns them into a
resolvable ``resource_id`` by calling :func:`create_resource_from_bytes`. This
replaces the "upload to R2 + INSERT workflow_resources" block that was
copy-pasted across the agent node, agent tool execution, the MCP tools,
and inbound-email attachments, and is the seam the HTTP node's file-download
path also uses.

Lives in ``utils`` (depends only on ``utils.r2_cloudflare`` /
``utils.database_pool``) so both nodes and other utils can import it without a
layering cycle.
"""

import json
import logging
import mimetypes
import os
import re
import uuid
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlsplit

from utils import database_pool
from utils.capabilities import FILE_DOWNLOAD_URL, capability
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


def file_name(name: str, mime: str, *, source: str = "") -> str:
    """``name`` ending in the extension of what the file holds, from ``source`` (the path it came from) or else its
    type, when it names none: a download then opens as that file, and a chat shows it as one. A type that names
    nothing (``application/octet-stream``) adds nothing."""
    base = (mime or "").split(";")[0].strip().lower()
    ext = os.path.splitext(source)[1] or (mimetypes.guess_extension(base) if base != "application/octet-stream" else "")
    if not ext or name.lower().endswith(ext.lower()) or mimetypes.guess_type(name)[0]:
        return name
    return f"{name}{ext}"


# The first bytes of the files people are sent most, by their type.
_SIGNATURES = ((b"%PDF-", "application/pdf"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
               (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"), (b"PK\x03\x04", "application/zip"))


def content_type(data: bytes) -> Optional[str]:
    """What ``data`` is, read from its own bytes when nothing else names it (a file named "Neon Blocks"): a PDF, an
    image, a zip, an HTML page, JSON or other text; None when it's none of these (XML and SVG among them)."""
    found = next((mime for magic, mime in _SIGNATURES if data.startswith(magic)), None)
    if found or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return found or "image/webp"
    try:
        text = data.decode("utf-8").lstrip("﻿ \t\r\n")
    except UnicodeDecodeError:
        return None
    head = text[:1024].lower()
    if head.startswith(("<!doctype html", "<html")):
        return "text/html"
    if head.startswith(("<?xml", "<svg")):
        return None
    if head.startswith(("{", "[")):
        try:
            json.loads(text)
            return "application/json"
        except ValueError:
            pass
    return "text/plain"


# A resource's key as ``upload_resource_bytes`` writes it: owner / workflow (or "account") / id / file name.
_KEY = re.compile(r"[0-9a-f-]{36}/(?:[0-9a-f-]{36}|account)/[0-9a-f-]{36}/[^/]+$", re.I)


def resource_key_at(url: str) -> Optional[str]:
    """The key of the resource ``url`` downloads (a URL ``get_public_download_url`` made), else None."""
    parts = urlsplit(url)
    path = unquote(parts.path)
    match = _KEY.search(path)
    if match is None:
        return None
    try:
        ours = urlsplit(get_public_download_url(match.group(0)))
    except ValueError:  # this instance keeps no files
        return None
    return match.group(0) if (ours.scheme, ours.netloc, unquote(ours.path)) == (parts.scheme, parts.netloc, path) else None


def is_resource_key(key: str) -> bool:
    """Whether ``key`` has the shape ``upload_resource_bytes`` writes."""
    return _KEY.fullmatch(key) is not None


def download_url(url: str) -> Optional[str]:
    """The link that saves the stored file at ``url`` (``FILE_DOWNLOAD_URL``); None for a URL that isn't one of this
    instance's files, or where the platform makes no such link."""
    make = capability(FILE_DOWNLOAD_URL)
    key = resource_key_at(url) if make is not None else None
    return make(key) if key else None


async def create_resource_from_bytes(
    *,
    user_id: str,
    workflow_id: Optional[str],
    node_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    body: bytes,
    content_type: str,
    filename: str,
    resource_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    resource_id: Optional[str] = None,
    connection=None,
) -> Dict[str, Any]:
    """Upload *body* to R2 and record a ``workflow_resources`` row.

    Returns ``{resource_id, name, mime_type, size_bytes, storage_ref,
    download_url}`` — the shape every consumer (and the media resolver) expects.
    The storage key is ``{owner}/{workflow}/{resource_id}/{filename}``; an
    account-level resource (no workflow, e.g. the coordinator's media) keys
    under ``{owner}/account/``.
    Supply a stable ID and pinned connection to commit a file with its producer's
    ledger/outbox; callers must guard retries before uploading.
    """
    resource_id = resource_id or str(uuid.uuid4())
    storage_ref = await upload_resource_bytes(user_id=user_id, workflow_id=workflow_id, resource_id=resource_id,
                                              filename=filename, body=body, content_type=content_type)
    return await record_resource(
        user_id=user_id, workflow_id=workflow_id, node_id=node_id, organization_id=organization_id,
        resource_id=resource_id, storage_ref=storage_ref, size_bytes=len(body), content_type=content_type,
        filename=filename, resource_type=resource_type, metadata=metadata, connection=connection,
    )


async def upload_resource_bytes(*, user_id: str, workflow_id: Optional[str], resource_id: str, filename: str,
                                body: bytes, content_type: str) -> str:
    """Put *body* where resource ``resource_id`` keeps it; its storage ref. ``record_resource`` then makes the row,
    so a caller can read a file while it uploads."""
    storage_ref = f"{user_id}/{workflow_id or 'account'}/{resource_id}/{filename}"
    await upload_bytes_to_r2_async(
        bucket=RESOURCE_BUCKET, key=storage_ref, body=body, content_type=content_type
    )
    return storage_ref


async def record_resource(
    *,
    user_id: str,
    workflow_id: Optional[str],
    resource_id: str,
    storage_ref: str,
    size_bytes: int,
    content_type: str,
    filename: str,
    node_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    connection=None,
) -> Dict[str, Any]:
    """The ``workflow_resources`` row for bytes already uploaded (``upload_resource_bytes``)."""
    rtype = resource_type or resource_type_for_mime(content_type)
    await (connection or database_pool.get_native_pool()).execute(
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


def uploaded(*, url: str, resource_id: str, name: str, size_bytes: int, mime_type: str) -> Dict[str, Any]:
    """What an agent's ``upload_file`` answers, on either runtime: where the file now is, and that uploading it sent
    it to no one."""
    return {
        "success": True, "url": url, "resource_id": resource_id, "name": name, "size_bytes": size_bytes,
        "mime_type": mime_type,
        "message": (f"Uploaded, not sent: nobody has it yet. It reaches someone only in words of yours that carry "
                    f"it, ![{name}]({url}), or through a tool you give this URL to. When they want it now, those are "
                    "the next words you write, even the line beside your next call; never a line calling it ready "
                    "or sent without it."),
    }
