"""Resolve a media-input value to bytes for upload nodes.

A media field on an upload node (YouTube video, Slack file, Twitter media, …)
can hold: a public URL, a workflow ``resource_id`` (from an HTTP file-download,
an interface upload, or agent-generated media), a ``data:`` URI, or raw base64.
:func:`resolve_media_input` turns any of those into bytes + mime + filename —
the single reader, mirror of ``utils.resource_store.create_resource_from_bytes``
(the single writer). It also returns a fetchable ``download_url`` for APIs that
take a URL rather than bytes (e.g. Telegram).
"""

import base64
import binascii
import logging
import mimetypes
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_DEFAULT_MAX_BYTES = 200 * 1024 * 1024  # 200 MB — videos are large
_CHUNK = 65536
_TRUSTED_MEDIA_URLS: ContextVar[frozenset[str]] = ContextVar(
    "trusted_media_urls", default=frozenset()
)
_MEDIA_WORKFLOW_ID: ContextVar[Optional[str]] = ContextVar(
    "media_workflow_id", default=None
)

# Outbound email attachment caps, shared by every send pathway.
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
ATTACHMENT_TOTAL_MAX_BYTES = 20 * 1024 * 1024


@dataclass
class ResolvedMedia:
    data: bytes
    mime_type: str
    filename: str
    # A URL the bytes can be fetched from again: the presigned URL for a
    # resource, or the original URL. None for inline (data URI / base64) inputs.
    download_url: Optional[str] = None

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode()


def _ext_for_mime(mime: str) -> str:
    ext = mimetypes.guess_extension((mime or "").split(";")[0].strip())
    return ext or ".bin"


def _filename_from_url(url: str, mime: str) -> str:
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    return name if name and "." in name else f"download{_ext_for_mime(mime)}"


async def _stream_to_bytes(
    url: str, max_bytes: int, *, trusted_initial_url: bool = False
) -> Tuple[bytes, str]:
    """Stream a URL into memory with a hard size cap; returns (bytes, content_type).

    SSRF-guarded on EVERY hop (the request hook re-validates each redirect target,
    so a public URL can't 30x-redirect to an internal/metadata address). Network
    failures (non-2xx, connect, timeout) surface as ValueError so callers that
    catch ValueError handle them uniformly; size-cap / SSRF errors are already
    ValueError and pass through unchanged."""
    from utils.ssrf import guarded_async_client

    normalized_url = str(httpx.URL(url))
    trusted_urls = _TRUSTED_MEDIA_URLS.get()
    normalized_trusted_url = (
        normalized_url
        if trusted_initial_url or url in trusted_urls or normalized_url in trusted_urls
        else None
    )

    try:
        async with guarded_async_client(
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
            trusted_exact_urls=(
                (normalized_trusted_url,) if normalized_trusted_url else ()
            ),
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                ct = (
                    resp.headers.get("content-type", "application/octet-stream")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                cl = resp.headers.get("content-length")
                if cl and int(cl) > max_bytes:
                    raise ValueError(
                        f"Media is too large ({int(cl) // 1024 // 1024}MB > "
                        f"{max_bytes // 1024 // 1024}MB limit)."
                    )
                chunks, received = [], 0
                async for chunk in resp.aiter_bytes(_CHUNK):
                    received += len(chunk)
                    if received > max_bytes:
                        raise ValueError(
                            f"Media download exceeded the {max_bytes // 1024 // 1024}MB limit."
                        )
                    chunks.append(chunk)
        return b"".join(chunks), ct
    except httpx.HTTPError as e:
        raise ValueError(f"Could not fetch media from URL: {e}")


def is_resource_id(value: str) -> bool:
    """True if *value* is a workflow resource UUID (not a URL/data-URI/base64)."""
    return bool(_UUID_RE.match((value or "").strip()))


def looks_like_media_ref(value: str) -> bool:
    """True if *value* is unambiguously a media reference — a resource UUID, an
    http(s) URL, or a data: URI. Used by nodes whose field also accepts plain
    text (e.g. Google Drive file content) to decide whether to resolve it."""
    v = (value or "").strip()
    return bool(
        _UUID_RE.match(v)
        or v.startswith("http://")
        or v.startswith("https://")
        or v.startswith("data:")
    )


def _media_resource_fields(value: Any) -> list[tuple[BaseModel, str, str]]:
    """Find UUID values in fields rendered by the durable media-upload widget."""
    found: list[tuple[BaseModel, str, str]] = []
    if isinstance(value, BaseModel):
        for name, field in type(value).model_fields.items():
            current = getattr(value, name, None)
            extra = field.json_schema_extra
            if (
                isinstance(extra, dict)
                and extra.get("ui:widget") == "media_upload"
                and isinstance(current, str)
                and is_resource_id(current)
            ):
                found.append((value, name, current.strip()))
            else:
                found.extend(_media_resource_fields(current))
    elif isinstance(value, dict):
        for current in value.values():
            found.extend(_media_resource_fields(current))
    elif isinstance(value, (list, tuple)):
        for current in value:
            found.extend(_media_resource_fields(current))
    return found


@asynccontextmanager
async def renewable_media_urls(
    config: Optional[BaseModel], workflow_id: Optional[str]
) -> AsyncIterator[None]:
    """Temporarily turn persisted resource IDs into fresh download URLs.

    Media-upload widgets persist the durable workflow resource UUID, never the
    expiring object-store URL. Immediately before a node executes, fields marked
    ``ui:widget=media_upload`` are replaced with a URL minted for that run. The
    original IDs are restored afterwards so a reused node instance renews the
    link again on its next run.

    The lookup is scoped to the current workflow. A UUID copied from another
    workflow is therefore not an ambient bearer credential.
    """
    workflow_token = _MEDIA_WORKFLOW_ID.set(workflow_id)
    replacements: list[tuple[BaseModel, str, str]] = []
    try:
        fields = _media_resource_fields(config)
        if not fields:
            yield
            return
        if not workflow_id:
            raise ValueError(
                "Uploaded media references require a workflow execution context."
            )

        from utils.database_pool import get_native_pool
        from utils.r2_cloudflare import get_public_download_url

        pool = get_native_pool()
        urls: dict[str, str] = {}
        for model, name, resource_id in fields:
            url = urls.get(resource_id)
            if url is None:
                row = await pool.fetchrow(
                    """
                    SELECT storage_ref
                    FROM workflow_resources
                    WHERE id = $1 AND workflow_id = $2
                    """,
                    resource_id,
                    workflow_id,
                )
                if not row or not row.get("storage_ref"):
                    raise ValueError(
                        "Uploaded media is missing or does not belong to this workflow."
                    )
                url = get_public_download_url(row["storage_ref"])
                urls[resource_id] = url
            setattr(model, name, url)
            replacements.append((model, name, resource_id))
        # Handlers that consume bytes call ``resolve_media_input`` with the
        # temporary URL. Trust only these exact ownership-checked URLs; their
        # redirects remain guarded by ``_stream_to_bytes``.
        trusted_token = _TRUSTED_MEDIA_URLS.set(frozenset(urls.values()))
        try:
            yield
        finally:
            _TRUSTED_MEDIA_URLS.reset(trusted_token)
    finally:
        for model, name, resource_id in reversed(replacements):
            setattr(model, name, resource_id)
        _MEDIA_WORKFLOW_ID.reset(workflow_token)


async def resolve_media_input(
    value: str,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    default_mime: str = "application/octet-stream",
    workflow_id: Optional[str] = None,
) -> ResolvedMedia:
    """Resolve a media value (URL / resource_id / data URI / base64) to bytes."""
    value = (value or "").strip()
    if not value:
        raise ValueError("No media value provided.")

    # data: URI — inline, no network
    if value.startswith("data:"):
        header, _, payload = value.partition(",")
        mime = header[5:].split(";")[0].strip().lower() or default_mime
        try:
            data = (
                base64.b64decode(payload)
                if ";base64" in header
                else unquote(payload).encode()
            )
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"Invalid data URI: {e}")
        _check_size(len(data), max_bytes)
        return ResolvedMedia(data, mime, f"file{_ext_for_mime(mime)}")

    # workflow resource_id — resolve via DB, stream from the presigned URL
    if _UUID_RE.match(value):
        from utils.database_pool import get_native_pool
        from utils.r2_cloudflare import generate_presigned_download_url

        resource_workflow_id = workflow_id or _MEDIA_WORKFLOW_ID.get()
        if not resource_workflow_id:
            raise ValueError(
                "Uploaded media references require a workflow execution context."
            )
        row = await get_native_pool().fetchrow(
            """
            SELECT storage_ref, mime_type, name, size_bytes
            FROM workflow_resources
            WHERE id = $1 AND workflow_id = $2
            """,
            value,
            resource_workflow_id,
        )
        if not row:
            raise ValueError(f"Resource not found: {value}")
        if row.get("size_bytes"):
            _check_size(row["size_bytes"], max_bytes)
        presigned = generate_presigned_download_url("workflow-resources", row["storage_ref"])
        data, ct = await _stream_to_bytes(
            presigned, max_bytes, trusted_initial_url=True
        )
        mime = (row.get("mime_type") or ct or default_mime).lower()
        filename = row.get("name") or f"file{_ext_for_mime(mime)}"
        return ResolvedMedia(data, mime, filename, download_url=presigned)

    # http(s) URL — SSRF-guarded stream
    if value.startswith("http://") or value.startswith("https://"):
        from utils.ssrf import assert_url_allowed

        await assert_url_allowed(value)
        data, ct = await _stream_to_bytes(value, max_bytes)
        mime = ct or default_mime
        return ResolvedMedia(data, mime, _filename_from_url(value, mime), download_url=value)

    # raw base64 (last resort — e.g. legacy base64-only media fields). Strip
    # whitespace first so line-wrapped base64 (MIME/PEM style) still decodes,
    # while validate=True keeps non-base64 text from being silently accepted.
    try:
        data = base64.b64decode("".join(value.split()), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(
            "Media value is not a URL, resource id, data URI, or base64 string."
        )
    _check_size(len(data), max_bytes)
    return ResolvedMedia(data, default_mime, f"file{_ext_for_mime(default_mime)}")


async def resolve_attachments(
    entries: List[str], *, workflow_id: Optional[str] = None
) -> List[ResolvedMedia]:
    """Resolve outbound email attachment entries (resource ids / URLs / data
    URIs) to bytes. Blank entries are ignored; a resolution failure or a cap
    breach (10MB per file, 20MB per send) raises ValueError — never a silent
    skip."""
    resolved: List[ResolvedMedia] = []
    total = 0
    for entry in entries or []:
        if not isinstance(entry, str) or not entry.strip():
            continue
        media = await resolve_media_input(
            entry.strip(),
            max_bytes=ATTACHMENT_MAX_BYTES,
            workflow_id=workflow_id,
        )
        total += len(media.data)
        if total > ATTACHMENT_TOTAL_MAX_BYTES:
            raise ValueError(
                f"Attachments exceed the {ATTACHMENT_TOTAL_MAX_BYTES // 1024 // 1024}MB "
                "total limit per send."
            )
        resolved.append(media)
    return resolved


def _check_size(size: int, max_bytes: int) -> None:
    if size > max_bytes:
        raise ValueError(
            f"Media is too large ({size // 1024 // 1024}MB > {max_bytes // 1024 // 1024}MB limit)."
        )
