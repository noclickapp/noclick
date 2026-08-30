"""S3-compatible object-storage helpers.

The public function names retain their historical ``r2`` spelling for API
compatibility, but the implementation uses only the operator-configured
``OBJECT_STORAGE_*`` contract. Latency-sensitive operations use presigned
URLs with a bounded async HTTP client; low-volume compatibility helpers
wrap boto3 work in a worker thread.
"""

import logging
import os
import base64
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
import boto3
import httpx

from utils import local_object_store as _local

logger = logging.getLogger(__name__)

# Cached S3 client — boto3 client creation is expensive (loads service models,
# creates connection pools). Creating one per call caused multi-GB memory growth.
_s3_client = None

# Shared httpx client for native-async R2 PUT / DELETE / GET via presigned
# URL. Bounded connection pool surfaces backpressure into httpx itself
# instead of letting unbounded parallel TLS handshakes spawn worker threads.
_R2_HTTP_TIMEOUT_S = 30.0
_R2_MAX_CONCURRENCY = 16
_r2_http_client: Optional[httpx.AsyncClient] = None
_r2_request_gate: Optional[asyncio.Semaphore] = None
_r2_gate_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_r2_http_client() -> httpx.AsyncClient:
    global _r2_http_client
    if _r2_http_client is None or _r2_http_client.is_closed:
        _r2_http_client = httpx.AsyncClient(
            timeout=_R2_HTTP_TIMEOUT_S,
            limits=httpx.Limits(
                max_connections=_R2_MAX_CONCURRENCY,
                max_keepalive_connections=_R2_MAX_CONCURRENCY,
            ),
        )
    return _r2_http_client


def _get_r2_request_gate() -> asyncio.Semaphore:
    """Cap in-flight requests on the shared client at its connection count.

    Excess callers wait here (O(1) FIFO wakeup) rather than in httpcore's
    request queue, which rescans queued requests on every completion and makes
    event-loop work quadratic under a large CAS chunk fan-out. Recreated per
    event loop, mirroring the client's own staleness handling.
    """
    global _r2_request_gate, _r2_gate_loop
    loop = asyncio.get_running_loop()
    if _r2_request_gate is None or _r2_gate_loop is not loop:
        _r2_request_gate = asyncio.Semaphore(_R2_MAX_CONCURRENCY)
        _r2_gate_loop = loop
    return _r2_request_gate


async def upload_bytes_to_r2_async(
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
) -> None:
    """Upload a single byte blob to R2 via presigned PUT URL + httpx.

    Native async — generate_presigned_url is local HMAC signing (microseconds,
    no I/O, safe on the loop); the PUT itself runs on the asyncio loop with
    backpressure flowing through httpx's bounded connection pool. No
    default-executor worker is reserved per upload.

    Raises httpx.HTTPStatusError on non-2xx response.
    """
    if _local.enabled():
        await asyncio.to_thread(_local.put, bucket, key, body, content_type)
        return
    url = generate_presigned_upload_url(
        bucket=bucket, key=key, content_type=content_type
    )
    client = _get_r2_http_client()
    async with _get_r2_request_gate():
        response = await client.put(
            url, content=body, headers={"Content-Type": content_type}
        )
    response.raise_for_status()


async def delete_files_from_r2_async_native(
    bucket: str,
    keys: List[str],
) -> int:
    """Delete multiple R2 objects via concurrent presigned-URL DELETEs + httpx.

    Native async — every signing is local HMAC (microseconds, safe on the
    loop) and the DELETEs run in parallel via ``asyncio.gather``, bounded
    by the shared httpx connection pool. No default-executor worker is
    reserved per delete. Idempotent — S3 returns 204 for missing keys.

    For very large key lists (>100s), the per-key fan-out becomes chattier
    than the boto3 batch ``delete_objects`` API; this helper is intended
    for the hot path (per-workflow-run retention cleanup, typically ≤20
    keys). Bulk cleanup paths (workflow deletion) can stay on
    ``delete_files_from_r2_async`` (the boto3 ``delete_objects`` wrapper).

    Returns the number of keys requested.
    """
    if _local.enabled():
        for k in keys:
            _local.delete(bucket, k)
        return len(keys)
    if not keys:
        return 0
    client = _get_r2_http_client()

    async def _delete_one(key: str) -> None:
        url = generate_presigned_delete_url(bucket=bucket, key=key)
        async with _get_r2_request_gate():
            response = await client.delete(url)
        # S3 returns 204 on success and on missing key (delete is idempotent).
        response.raise_for_status()

    await asyncio.gather(*[_delete_one(k) for k in keys])
    return len(keys)


async def download_bytes_from_r2_async_native(
    bucket: str,
    key: str,
) -> tuple[bytes, str]:
    """Download an R2 object via presigned GET URL + httpx.

    Native async — signing is local HMAC, the GET runs on the asyncio loop
    with backpressure via the shared httpx connection pool. No default-
    executor worker is reserved per download.

    Returns ``(content_bytes, content_type)``. Raises
    ``httpx.HTTPStatusError`` on non-2xx response.
    """
    if _local.enabled():
        return await asyncio.to_thread(_local.get, bucket, key)
    url = generate_presigned_download_url(bucket=bucket, key=key)
    client = _get_r2_http_client()
    async with _get_r2_request_gate():
        response = await client.get(url)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "application/octet-stream")
    return response.content, content_type


def create_s3_client():
    """
    Return a cached boto3 S3 client configured for R2.
    Creates the client on first call, reuses it thereafter.

    Returns:
        boto3 S3 client configured with R2 credentials

    Raises:
        ValueError: If required environment variables are missing
    """
    if _local.enabled():
        raise ValueError("Object storage runs on this instance's disk; set OBJECT_STORAGE_* for an S3 client")
    global _s3_client
    if _s3_client is not None:
        return _s3_client

    endpoint = os.getenv("OBJECT_STORAGE_ENDPOINT")
    access_key = os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID")
    secret_key = os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY")
    region = os.getenv("OBJECT_STORAGE_REGION", "us-east-1")
    missing = (
        "OBJECT_STORAGE_ENDPOINT, OBJECT_STORAGE_ACCESS_KEY_ID, and "
        "OBJECT_STORAGE_SECRET_ACCESS_KEY"
    )

    if not all([endpoint, access_key, secret_key]):
        raise ValueError(f"Object storage is not configured; set {missing}")

    logger.info("[OBJECT_STORAGE] Creating S3 client")
    logger.debug(f"[OBJECT_STORAGE] endpoint: {endpoint}")

    _s3_client = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    return _s3_client






async def upload_files_to_r2(
    bucket: str,
    prefix: str,
    files: Dict[str, Dict[str, Any]],
    metadata: Optional[Dict[str, str]] = None
) -> int:
    """
    Upload multiple files to R2 bucket with a common prefix.

    Args:
        bucket: R2 bucket name (e.g., "workflow-artifacts")
        prefix: Prefix for all file keys (e.g., "workflow-123" or "staging--<resource_id>")
        files: Dict mapping file paths to file data dicts with keys:
            - content: File content (str for text, base64 str for binary)
            - encoding: "utf-8" or "base64"
            - content_type: MIME type (e.g., "text/html")
            - content_length: File size in bytes (optional)
            - last_modified: ISO timestamp (optional)
        metadata: Optional dict of metadata key-value pairs to attach to all files
            Common keys: "resource_id", "owner", etc.

    Returns:
        Number of files successfully uploaded

    Raises:
        Exception: If any file upload fails

    Example:
        files = {
            "/index.html": {
                "content": "<html>...</html>",
                "encoding": "utf-8",
                "content_type": "text/html",
                "content_length": 1234
            },
            "/logo.png": {
                "content": "iVBORw0KGgo...",  # base64 encoded
                "encoding": "base64",
                "content_type": "image/png",
                "content_length": 5678
            }
        }
        count = await upload_files_to_r2(
            "workflow-artifacts",
            "workflow-123",
            files,
            metadata={"resource_id": "resource-123", "owner": "team-123"}
        )
    """
    if _local.enabled():
        for file_path, file_data in files.items():
            content = base64.b64decode(file_data["content"]) if file_data.get("encoding") == "base64" else file_data["content"].encode("utf-8")
            _local.put(bucket, f"{prefix}{file_path}", content, file_data.get("content_type") or "application/octet-stream", metadata)
        return len(files)
    s3_client = create_s3_client()

    logger.info(f"[R2] Starting upload of {len(files)} files to {bucket}/{prefix}")

    # boto3 is synchronous — running put_object on the asyncio main thread
    # blocks the loop for the full HTTPS round-trip per file. Push the entire
    # batch onto a worker thread so the loop stays responsive (one to_thread
    # for the whole batch since the uploads are sequential against a single
    # cached S3 client).
    def _upload_batch() -> int:
        count = 0
        for file_path, file_data in files.items():
            s3_key = f"{prefix}{file_path}"

            if file_data.get('encoding') == 'base64':
                file_content = base64.b64decode(file_data['content'])
            else:
                file_content = file_data['content'].encode('utf-8')

            file_metadata: Dict[str, str] = {}
            if metadata:
                file_metadata.update(metadata)
            if 'last_modified' in file_data:
                file_metadata['last_modified'] = file_data['last_modified']
            else:
                file_metadata['last_modified'] = datetime.now().isoformat()

            logger.debug(
                f"[R2] Uploading {s3_key}, size={len(file_content)} bytes, "
                f"type={file_data.get('content_type')}"
            )
            s3_client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=file_content,
                ContentType=file_data.get('content_type', 'application/octet-stream'),
                Metadata=file_metadata,
            )
            count += 1
            logger.debug(f"[R2] Uploaded {s3_key} ({file_data.get('content_type')})")
        return count

    upload_count = await asyncio.to_thread(_upload_batch)
    logger.info(f"[R2] Successfully uploaded {upload_count} files to {bucket}/{prefix}")
    return upload_count


def r2_prefix_exists(bucket: str, prefix: str) -> bool:
    """Check if any objects exist under a given prefix in an R2 bucket."""
    if _local.enabled():
        return bool(_local.list_keys(bucket, prefix))
    try:
        s3_client = create_s3_client()
        resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/", MaxKeys=1)
        return resp.get("KeyCount", 0) > 0
    except Exception as e:
        logger.warning(f"[R2] Failed to check prefix existence {bucket}/{prefix}: {e}")
        return False


def delete_files_from_r2(
    bucket: str,
    prefix: str,
    file_paths: List[str]
) -> int:
    """
    Delete multiple files from R2 bucket.

    Args:
        bucket: R2 bucket name (e.g., "workflow-artifacts")
        prefix: Prefix for all file keys (e.g., "workflow-123" or "staging--<resource_id>")
        file_paths: List of file paths to delete (e.g., ["/index.html", "/assets/main.js"])

    Returns:
        Number of files successfully deleted

    Note:
        - S3 delete is idempotent - no error if file doesn't exist
        - Empty file_paths list is handled gracefully (returns 0)
        - Uses batch delete_objects API for efficiency

    Example:
        deleted = delete_files_from_r2(
            "workflow-artifacts",
            "staging--resource-123",
            ["/old-file.js", "/removed.css"]
        )
    """
    if _local.enabled():
        for file_path in file_paths:
            _local.delete(bucket, f"{prefix}{file_path}")
        return len(file_paths)
    if not file_paths:
        logger.debug(f"[R2] No files to delete from {bucket}/{prefix}")
        return 0

    s3_client = create_s3_client()

    # Build S3 keys from prefix + file paths
    objects_to_delete = [
        {'Key': f"{prefix}{file_path}"}
        for file_path in file_paths
    ]

    logger.info(f"[R2] Deleting {len(objects_to_delete)} files from {bucket}/{prefix}")
    logger.debug(f"[R2] Files to delete: {file_paths[:10]}..." if len(file_paths) > 10 else f"[R2] Files to delete: {file_paths}")

    # Batch delete using delete_objects API
    response = s3_client.delete_objects(
        Bucket=bucket,
        Delete={'Objects': objects_to_delete}
    )

    # Count successful deletions
    deleted_count = len(response.get('Deleted', []))
    errors = response.get('Errors', [])

    if errors:
        logger.warning(f"[R2] {len(errors)} errors during deletion: {errors[:3]}...")

    logger.info(f"[R2] Successfully deleted {deleted_count}/{len(objects_to_delete)} files from {bucket}/{prefix}")
    return deleted_count


def fetch_etags_from_r2(
    bucket: str,
    prefix: str
) -> Dict[str, str]:
    """
    Fetch ETags for all files in a given R2 prefix.

    Args:
        bucket: R2 bucket name (e.g., "workflow-artifacts")
        prefix: Prefix to fetch ETags from (e.g., "staging--resource-123" or "published-version")

    Returns:
        Dict mapping file paths to ETags (with quotes stripped)
        File paths are relative (e.g., "/index.html", "/assets/main.js")

    Example:
        etags = fetch_etags_from_r2("workflow-artifacts", "staging--resource-123")
        # Returns: {"/index.html": "abc123", "/assets/main.js": "def456"}
    """
    if _local.enabled():
        return {"/" + k[len(prefix) + 1:]: _local.etag(bucket, k) for k in _local.list_keys(bucket, prefix)}
    try:
        from botocore.exceptions import ClientError

        s3_client = create_s3_client()

        response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix + "/"
        )

        etags = {}
        if 'Contents' in response:
            for obj in response['Contents']:
                # Key format: "prefix/path/to/file.js"
                full_key = obj['Key']
                # Remove prefix to get relative path (e.g., "/path/to/file.js")
                file_path = "/" + full_key[len(prefix) + 1:]  # +1 for the trailing slash
                # Get ETag (strip quotes)
                etag = obj['ETag'].strip('"')
                etags[file_path] = etag

        logger.debug(f"[R2] Fetched {len(etags)} ETags from {bucket}/{prefix}")
        return etags

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            logger.info(f"[R2] No existing files found at {bucket}/{prefix}")
            return {}
        raise


def generate_presigned_upload_url(
    bucket: str,
    key: str,
    content_type: str = "application/octet-stream",
    expires_in: int = 3600,
    *,
    content_length: Optional[int] = None,
) -> str:
    """
    Generate a presigned URL for uploading a file to R2.

    Args:
        bucket: R2 bucket name
        key: S3 object key
        content_type: MIME type of the file being uploaded
        expires_in: URL expiration time in seconds (default 1 hour)
        content_length: Exact upload size to bind into the signature. Optional
            for server-side callers that do not know the size in advance.

    Returns:
        Presigned PUT URL string
    """
    if _local.enabled():
        return _local.presign("PUT", bucket, key, expires_in=expires_in, content_type=content_type, content_length=content_length)
    s3_client = create_s3_client()
    params: Dict[str, Any] = {
        'Bucket': bucket,
        'Key': key,
        'ContentType': content_type,
    }
    if content_length is not None:
        params['ContentLength'] = content_length
    return s3_client.generate_presigned_url(
        'put_object',
        Params=params,
        ExpiresIn=expires_in,
    )


def get_public_download_url(key: str) -> str:
    """Return a browser-resolvable URL for a workflow resource.

    ``OBJECT_STORAGE_PUBLIC_BASE_URL`` enables stable public URLs. Private
    installations mint a short-lived URL on each read; their durable contract
    is the resource identifier, whose URL can be renewed through
    ``resource:download_url``.
    """
    public_base = os.getenv("OBJECT_STORAGE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if public_base:
        return f"{public_base}/{key.lstrip('/')}"
    return generate_presigned_download_url(
        "workflow-resources", key, expires_in=900,
    )

def generate_presigned_download_url(bucket: str, key: str, expires_in: int = 900) -> str:
    """
    Generate a presigned URL for downloading a file from R2.

    Args:
        bucket: R2 bucket name
        key: S3 object key
        expires_in: URL expiration time in seconds (default 15 minutes)

    Returns:
        Presigned GET URL string
    """
    if _local.enabled():
        return _local.presign("GET", bucket, key, expires_in=expires_in)
    s3_client = create_s3_client()
    return s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expires_in,
    )


def generate_presigned_delete_url(bucket: str, key: str, expires_in: int = 900) -> str:
    """
    Generate a presigned URL for deleting a file from R2.

    Args:
        bucket: R2 bucket name
        key: S3 object key
        expires_in: URL expiration time in seconds (default 15 minutes)

    Returns:
        Presigned DELETE URL string
    """
    if _local.enabled():
        return _local.presign("DELETE", bucket, key, expires_in=expires_in)
    s3_client = create_s3_client()
    return s3_client.generate_presigned_url(
        'delete_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expires_in,
    )


def download_from_r2(bucket: str, key: str) -> tuple[bytes, str]:
    """Download file from R2. Returns (content_bytes, content_type)."""
    if _local.enabled():
        return _local.get(bucket, key)
    s3_client = create_s3_client()
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content_bytes = response['Body'].read()
    content_type = response.get('ContentType', 'application/octet-stream')
    return content_bytes, content_type


async def copy_files_within_r2(
    bucket: str,
    source_prefix: str,
    dest_prefix: str
) -> int:
    """
    Copy all files from one prefix to another within the same R2 bucket.

    Args:
        bucket: R2 bucket name (e.g., "workflow-artifacts")
        source_prefix: Source prefix (e.g., "staging--resource-123")
        dest_prefix: Destination prefix (e.g., "published-version")

    Returns:
        Number of files successfully copied

    Raises:
        Exception: If source prefix has no files or copy operation fails

    Example:
        count = await copy_files_within_r2(
            "workflow-artifacts",
            "staging--resource-123",
            "published-version"
        )
    """
    if _local.enabled():
        keys = _local.list_keys(bucket, source_prefix)
        if not keys:
            raise Exception(f"No files found at {bucket}/{source_prefix}/")
        for k in keys:
            _local.copy(bucket, k, dest_prefix + k[len(source_prefix):])
        return len(keys)
    s3_client = create_s3_client()
    logger.info(f"[R2] Listing files in {bucket}/{source_prefix}/")

    # Same rationale as upload_files_to_r2: boto3 is synchronous, so the
    # list+copy loop must run on a worker thread to keep the event loop
    # responsive. One to_thread for the whole batch.
    def _list_and_copy() -> int:
        response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=source_prefix + "/",
        )
        if 'Contents' not in response or len(response['Contents']) == 0:
            raise Exception(f"No files found at {bucket}/{source_prefix}/")
        objects = response['Contents']
        logger.info(
            f"[R2] Found {len(objects)} files to copy from "
            f"{source_prefix}/ to {dest_prefix}/"
        )
        count = 0
        for obj in objects:
            source_key = obj['Key']
            relative_path = source_key[len(source_prefix):]
            dest_key = dest_prefix + relative_path
            logger.debug(f"[R2] Copying {source_key} → {dest_key}")
            s3_client.copy_object(
                Bucket=bucket,
                CopySource={'Bucket': bucket, 'Key': source_key},
                Key=dest_key,
                MetadataDirective='COPY',
            )
            count += 1
        return count

    copy_count = await asyncio.to_thread(_list_and_copy)
    logger.info(
        f"[R2] Successfully copied {copy_count} files from "
        f"{source_prefix}/ to {dest_prefix}/"
    )
    return copy_count


# ---------------------------------------------------------------------------
# Async wrappers for sync R2 helpers.
# Async callers MUST use these — see module docstring.
# ---------------------------------------------------------------------------

async def delete_files_from_r2_async(
    bucket: str,
    prefix: str,
    file_paths: List[str],
) -> int:
    """Async variant of `delete_files_from_r2` — runs on a worker thread."""
    return await asyncio.to_thread(delete_files_from_r2, bucket, prefix, file_paths)


async def r2_prefix_exists_async(bucket: str, prefix: str) -> bool:
    """Async variant of `r2_prefix_exists` — runs on a worker thread."""
    return await asyncio.to_thread(r2_prefix_exists, bucket, prefix)


async def download_from_r2_async(bucket: str, key: str) -> tuple[bytes, str]:
    """Async variant of `download_from_r2` — runs on a worker thread.

    Replaces the older `loop.run_in_executor(None, download_from_r2, ...)`
    idiom at gmail_node.py and matches the dual-API shape used elsewhere.
    """
    return await asyncio.to_thread(download_from_r2, bucket, key)
