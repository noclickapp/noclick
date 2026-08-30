"""Object storage on the instance's own disk (self-hosted only).

The single-origin image runs GoTrue and PostgREST but no S3 service, so with
nothing configured every presigned upload answered 404 and "file and media
features stay disabled" was the documented state — on a deploy that promises
to need nothing but a database. This is the object store for that case:
objects live under ``NOCLICK_HOME/storage/<bucket>/<key>`` (the instance's
persistent volume), and the backend serves them itself at
``/storage/{bucket}/{key}`` through signed URLs with the same PUT / GET /
DELETE shape S3's presigned URLs have — so the browser upload hook and every
reader work unchanged. Set ``OBJECT_STORAGE_*`` for an S3-compatible bucket and
this steps aside entirely.

Signed URLs are capabilities: HMAC over (method, bucket, key, expiry, content
type, length) with the instance's ``WORKFLOW_JWT_SECRET``, so a GET link cannot
be replayed as a PUT and a PUT link cannot change what it uploads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from utils.edition import is_local_edition

_BUCKET = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def enabled() -> bool:
    """The local store answers when this is the self-hosted edition and no
    S3-compatible endpoint is configured."""
    return is_local_edition() and not os.environ.get("OBJECT_STORAGE_ENDPOINT", "").strip()


def storage_root() -> Path:
    return Path(os.environ.get("NOCLICK_HOME") or (Path.home() / ".noclick")) / "storage"


def _secret() -> bytes:
    secret = os.environ.get("WORKFLOW_JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("WORKFLOW_JWT_SECRET is required to sign local storage URLs")
    return secret.encode()


def _origin() -> str:
    origin = (os.environ.get("PUBLIC_API_URL") or "").strip().rstrip("/")
    if not origin:
        from utils.webhook_tunnel import get_webhook_base_url

        origin = get_webhook_base_url()
    if not origin:
        raise RuntimeError("PUBLIC_API_URL is required to mint local storage URLs")
    return origin


def object_path(bucket: str, key: str) -> Path:
    """The file for ``bucket/key``, refusing anything that would leave the
    bucket's directory. Keys are the S3-style ``a/b/c.ext`` callers already use."""
    if not _BUCKET.match(bucket):
        raise ValueError(f"invalid bucket name: {bucket!r}")
    key = key.lstrip("/")
    parts = key.split("/")
    if not key or any(p in ("", ".", "..") for p in parts) or "\x00" in key:
        raise ValueError(f"invalid object key: {key!r}")
    root = (storage_root() / bucket).resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError(f"invalid object key: {key!r}")
    return path


def _meta_path(bucket: str, key: str) -> Path:
    # A parallel tree, so no reserved suffix can collide with a real key.
    return (storage_root() / bucket / ".meta" / key.lstrip("/")).with_name(
        Path(key).name + ".json"
    )


# ── Signed URLs ──────────────────────────────────────────────────────────────


def _signature(method: str, bucket: str, key: str, expires_at: int, content_type: str, content_length: str) -> str:
    message = "\n".join([method.upper(), bucket, key.lstrip("/"), str(expires_at), content_type, content_length])
    return hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()


def presign(
    method: str,
    bucket: str,
    key: str,
    *,
    expires_in: int,
    content_type: str = "",
    content_length: Optional[int] = None,
) -> str:
    key = key.lstrip("/")
    expires_at = int(time.time()) + int(expires_in)
    length = "" if content_length is None else str(int(content_length))
    query = {"exp": str(expires_at), "sig": _signature(method, bucket, key, expires_at, content_type, length)}
    if content_type:
        query["ct"] = content_type
    if length:
        query["len"] = length
    return f"{_origin()}/storage/{bucket}/{quote(key, safe='/')}?{urlencode(query)}"


def verify(method: str, bucket: str, key: str, exp: str, sig: str, content_type: str, content_length: str) -> bool:
    try:
        expires_at = int(exp)
    except (TypeError, ValueError):
        return False
    if expires_at < int(time.time()):
        return False
    expected = _signature(method, bucket, key, expires_at, content_type or "", content_length or "")
    return hmac.compare_digest(expected, sig or "")


# ── Objects ──────────────────────────────────────────────────────────────────


def put(bucket: str, key: str, body: bytes, content_type: str = "application/octet-stream", metadata: Optional[Dict[str, str]] = None) -> str:
    """Store an object; returns its ETag (the MD5 of the body, as S3 would)."""
    path = object_path(bucket, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(body)
    os.replace(tmp, path)
    meta = _meta_path(bucket, key)
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({"content_type": content_type or "application/octet-stream", "metadata": metadata or {}}))
    return hashlib.md5(body).hexdigest()


def get(bucket: str, key: str) -> Tuple[bytes, str]:
    path = object_path(bucket, key)
    body = path.read_bytes()  # FileNotFoundError is the S3 NoSuchKey
    return body, content_type(bucket, key)


def content_type(bucket: str, key: str) -> str:
    meta = _meta_path(bucket, key)
    if meta.exists():
        try:
            return json.loads(meta.read_text()).get("content_type") or "application/octet-stream"
        except (OSError, ValueError):
            pass
    return "application/octet-stream"


def delete(bucket: str, key: str) -> bool:
    """Idempotent, like S3: deleting what is not there is not an error."""
    path = object_path(bucket, key)
    existed = path.exists()
    if existed:
        path.unlink()
    meta = _meta_path(bucket, key)
    if meta.exists():
        meta.unlink()
    return existed


def list_keys(bucket: str, prefix: str) -> List[str]:
    """Keys under ``prefix/`` (S3 list semantics), relative to the bucket."""
    root = storage_root() / bucket
    base = object_path(bucket, prefix) if prefix else root
    if not base.is_dir():
        return []
    keys = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and ".meta" not in p.relative_to(root).parts and not p.name.endswith(".part"):
            keys.append(p.relative_to(root).as_posix())
    return keys


def etag(bucket: str, key: str) -> str:
    return hashlib.md5(object_path(bucket, key).read_bytes()).hexdigest()


def copy(bucket: str, source_key: str, dest_key: str) -> None:
    body, ctype = get(bucket, source_key)
    put(bucket, dest_key, body, ctype)


# ── Off-loop I/O, bounded ─────────────────────────────────────────────────────
# Disk writes and reads leave the event loop, but never one executor worker per
# call: a single small gate bounds them, the same discipline the S3 path keeps
# through httpx's connection pool (an unbounded default executor grew under
# sustained uploads once — the 2026-05-27 leak).
_IO_GATE: Optional["asyncio.Semaphore"] = None
_IO_GATE_LOOP = None


def _gate():
    import asyncio

    global _IO_GATE, _IO_GATE_LOOP
    loop = asyncio.get_running_loop()
    if _IO_GATE is None or _IO_GATE_LOOP is not loop:
        _IO_GATE, _IO_GATE_LOOP = asyncio.Semaphore(8), loop
    return _IO_GATE


async def put_async(bucket: str, key: str, body: bytes, content_type: str = "application/octet-stream") -> str:
    import asyncio

    async with _gate():
        return await asyncio.to_thread(put, bucket, key, body, content_type)


async def get_async(bucket: str, key: str) -> Tuple[bytes, str]:
    import asyncio

    async with _gate():
        return await asyncio.to_thread(get, bucket, key)
