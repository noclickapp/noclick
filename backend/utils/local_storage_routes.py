"""The local object store's HTTP face: /storage/{bucket}/{key}.

Signed URLs minted by ``utils.local_object_store.presign`` land here. The URL
is the capability — no session, no cookie — exactly like an S3 presigned URL,
which is what the browser upload hook and the media readers expect.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from utils import local_object_store as store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage")


def _authorize(request: Request, method: str, bucket: str, key: str) -> None:
    q = request.query_params
    if not store.verify(method, bucket, key, q.get("exp", ""), q.get("sig", ""), q.get("ct", ""), q.get("len", "")):
        raise HTTPException(status_code=403, detail="This storage link is invalid or has expired")
    try:
        store.object_path(bucket, key)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid object key")


@router.put("/{bucket}/{key:path}")
async def put_object(bucket: str, key: str, request: Request) -> Response:
    _authorize(request, "PUT", bucket, key)
    body = await request.body()
    expected_len = request.query_params.get("len")
    if expected_len and int(expected_len) != len(body):
        raise HTTPException(status_code=400, detail="Upload size does not match the signed length")
    content_type = request.query_params.get("ct") or request.headers.get("content-type") or "application/octet-stream"
    tag = store.put(bucket, key, body, content_type)
    return Response(status_code=200, headers={"ETag": f'"{tag}"'})


@router.get("/{bucket}/{key:path}")
async def get_object(bucket: str, key: str, request: Request) -> Response:
    _authorize(request, "GET", bucket, key)
    try:
        body, content_type = store.get(bucket, key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No such object")
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "private, max-age=0"})


@router.delete("/{bucket}/{key:path}")
async def delete_object(bucket: str, key: str, request: Request) -> Response:
    _authorize(request, "DELETE", bucket, key)
    store.delete(bucket, key)
    return Response(status_code=204)
