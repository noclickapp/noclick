"""HTTP surface for agent-workspace files: signed, streamed file reads and
signed uploads.

`GET /agent/workspace/file?token=...[&dl=1]` verifies the capability token
(minted by the agent_workspace:list socket handler — utils/agent_workspace.py)
and streams the file straight off the workspace volume. `dl=1` switches
the disposition to attachment; otherwise the file is served inline so the
chat's preview pane (text/markdown/images) can fetch or embed it directly.

`POST /agent/workspace/upload?token=...&path=<name>` verifies a volume-scoped
upload token (minted by FilesystemNode.load_field_value for the file browser)
and writes the raw request body to that path on the volume.

CORS is open: the token IS the auth (same stance as the presence routes), and
the FE fetches previews cross-origin from the app origin to the backend.
"""
import logging
import mimetypes
import os
import posixpath
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from utils.agent_workspace import verify_file_token, verify_upload_token

logger = logging.getLogger(__name__)

router = APIRouter()

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

MAX_UPLOAD_BYTES = 100 * 1024 * 1024

# Extensions the browser should render as text even though mimetypes maps them
# elsewhere (or not at all) — agent workspaces are full of these.
_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".log", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".csv", ".tsv", ".py", ".ts", ".tsx", ".js",
    ".jsx", ".sh", ".sql", ".html", ".css", ".xml", ".env",
    # svg MUST stay text: image/svg+xml served inline renders as a DOCUMENT
    # and executes embedded scripts — the exact agent-authored-markup XSS the
    # text/plain rule exists to prevent (the FE also previews svg as text).
    ".svg",
}


def _content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _TEXT_EXTENSIONS:
        # text/plain (not text/html etc.) so an inline preview can never execute
        # agent-authored markup in the app's browsing context.
        return "text/plain; charset=utf-8"
    guessed, _ = mimetypes.guess_type(path)
    if guessed and (guessed.startswith("image/") or guessed.startswith("video/")
                    or guessed.startswith("audio/") or guessed == "application/pdf"):
        return guessed
    return "application/octet-stream"


@router.options("/agent/workspace/file")
async def workspace_file_preflight() -> Response:
    return Response(status_code=204, headers=_CORS_HEADERS)


@router.get("/agent/workspace/file")
async def workspace_file(request: Request):
    token = request.query_params.get("token", "")
    claims = verify_file_token(token)
    if not claims:
        return JSONResponse(
            {"error": "invalid or expired file link"},
            status_code=403, headers=_CORS_HEADERS,
        )
    vol_name, path = claims["vol"], claims["path"]

    from utils.volume_backend import VolumeFileNotFound, get_volume_backend

    filename = os.path.basename(path) or "file"
    download = request.query_params.get("dl") == "1"
    content_type = "application/octet-stream" if download else _content_type(path)
    disposition = "attachment" if download else "inline"

    # Backends surface a missing volume/file eagerly (before any bytes
    # stream), so the error can be a clean 404 instead of a mid-stream abort.
    try:
        body = await get_volume_backend().iter_file(vol_name, path)
    except VolumeFileNotFound:
        return JSONResponse(
            {"error": "file not found in workspace"},
            status_code=404, headers=_CORS_HEADERS,
        )
    except Exception as e:
        logger.error(f"[workspace-file] read failed for {vol_name}:{path}: {e}")
        return JSONResponse(
            {"error": "failed to read file"},
            status_code=502, headers=_CORS_HEADERS,
        )

    return StreamingResponse(
        body,
        media_type=content_type,
        headers={
            **_CORS_HEADERS,
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "private, max-age=60",
        },
    )


def _sanitize_upload_path(raw: str) -> str | None:
    """Volume-relative path for an upload, or None when unusable. Normalizes
    and refuses anything that escapes the volume root."""
    path = posixpath.normpath(raw.strip().lstrip("/"))
    if not path or path in (".", "..") or path.startswith("../"):
        return None
    return path


@router.options("/agent/workspace/upload")
async def workspace_upload_preflight() -> Response:
    return Response(status_code=204, headers=_CORS_HEADERS)


@router.post("/agent/workspace/upload")
async def workspace_upload(request: Request):
    volume_name = verify_upload_token(request.query_params.get("token", ""))
    if not volume_name:
        return JSONResponse(
            {"error": "invalid or expired upload link"},
            status_code=403, headers=_CORS_HEADERS,
        )
    path = _sanitize_upload_path(request.query_params.get("path", ""))
    if not path:
        return JSONResponse(
            {"error": "invalid file path"},
            status_code=400, headers=_CORS_HEADERS,
        )

    # Reject a declared oversize body before reading it into process memory.
    # The streaming counter below remains authoritative for absent or false
    # Content-Length headers and transfer-encoded requests.
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            declared_bytes = int(declared_length)
        except ValueError:
            declared_bytes = -1
        if declared_bytes < 0:
            return JSONResponse(
                {"error": "invalid Content-Length"},
                status_code=400, headers=_CORS_HEADERS,
            )
        if declared_bytes > MAX_UPLOAD_BYTES:
            return JSONResponse(
                {"error": f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit"},
                status_code=413, headers=_CORS_HEADERS,
            )

    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_UPLOAD_BYTES:
            return JSONResponse(
                {"error": f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit"},
                status_code=413, headers=_CORS_HEADERS,
            )
        chunks.append(chunk)

    from utils.volume_backend import get_volume_backend

    try:
        await get_volume_backend().write_file(volume_name, path, b"".join(chunks))
    except Exception as e:
        logger.error(f"[workspace-upload] write failed for {volume_name}:{path}: {e}")
        return JSONResponse(
            {"error": "failed to write file"},
            status_code=502, headers=_CORS_HEADERS,
        )

    return JSONResponse({"success": True, "path": path}, headers=_CORS_HEADERS)
