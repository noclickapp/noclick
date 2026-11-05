"""``create_resource_from_stream``: a body of unknown length becomes a resource
without being held in memory, or left half-written when it fails."""

import asyncio
import gc
import tracemalloc
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from utils import resource_store
from utils.resource_store import STREAM_PART_BYTES as PART, create_resource_from_stream

CHUNK = 64 * 1024


class _Store(httpx.AsyncBaseTransport):
    """boto3's control calls plus the part PUTs, read off the request's stream and
    kept nowhere as a real transport does (MockTransport keeps them on the request).
    A test can slow or fail them."""

    def __init__(self, monkeypatch, *, fail_part=None, put_delay=0.0):
        self.parts, self.completed, self.aborted = [], [], []
        self.row = AsyncMock()
        self.acked = 0
        self.fail_part = fail_part
        self.put_delay = put_delay
        s3 = MagicMock()
        s3.create_multipart_upload.return_value = {"UploadId": "up-1"}
        s3.generate_presigned_url.side_effect = lambda op, Params: f"https://r2.test/?part={Params['PartNumber']}"
        s3.complete_multipart_upload.side_effect = lambda **kw: self.completed.append(kw)
        s3.abort_multipart_upload.side_effect = lambda **kw: self.aborted.append(kw)
        self.s3 = s3
        http = httpx.AsyncClient(transport=self)
        monkeypatch.setattr("utils.r2_cloudflare.create_s3_client", lambda: s3)
        monkeypatch.setattr("utils.r2_cloudflare._get_r2_http_client", lambda: http)
        monkeypatch.setattr(resource_store.local_object_store, "enabled", lambda: False)
        monkeypatch.setattr(resource_store, "get_public_download_url", lambda key: f"https://assets.test/{key}")
        monkeypatch.setattr(resource_store.database_pool, "get_native_pool", lambda: MagicMock(execute=self.row))

    async def handle_async_request(self, request):
        await asyncio.sleep(self.put_delay)
        number = int(request.url.params["part"])
        if number == self.fail_part:
            return httpx.Response(500)
        size = 0
        async for piece in request.stream:
            size += len(piece)
        # R2 takes no chunked upload.
        assert int(request.headers["content-length"]) == size and "transfer-encoding" not in request.headers
        self.parts.append((number, size))
        self.acked += size
        return httpx.Response(200, headers={"ETag": f'"etag-{number}"'})

    async def dropped(self) -> bool:
        for _ in range(200):
            if self.aborted:
                return True
            await asyncio.sleep(0.005)
        return False


async def _stream(total, on_chunk=None):
    chunk = bytes(CHUNK)
    sent = 0
    while sent < total:
        piece = chunk[: min(CHUNK, total - sent)]
        sent += len(piece)
        if on_chunk:
            on_chunk(sent)
        yield piece


def _create(chunks):
    return create_resource_from_stream(
        user_id="owner", workflow_id="wf", node_id="n", chunks=chunks,
        content_type="video/mp4", filename="clip.mp4", metadata={"source": "test"},
    )


@pytest.mark.asyncio
async def test_a_long_body_goes_up_in_parts_of_one_size(monkeypatch):
    store = _Store(monkeypatch)
    size = 3 * PART + 123

    resource = await _create(_stream(size))

    # R2 refuses an upload whose parts but the last differ in size.
    assert sorted(store.parts) == [(1, PART), (2, PART), (3, PART), (4, 123)]
    (done,) = store.completed
    assert done["MultipartUpload"]["Parts"] == [{"PartNumber": n, "ETag": f"etag-{n}"} for n in (1, 2, 3, 4)]
    assert done["Key"] == resource["storage_ref"] and done["Bucket"] == "workflow-resources"
    assert store.s3.create_multipart_upload.call_args.kwargs["ContentType"] == "video/mp4"
    assert resource["size_bytes"] == size and resource["resource_id"] in resource["storage_ref"]
    assert store.row.await_args.args[9] == size
    assert not store.aborted


@pytest.mark.asyncio
async def test_at_most_two_parts_are_held_however_long_the_body(monkeypatch):
    store = _Store(monkeypatch, put_delay=0.01)
    held = []
    await _create(_stream(10 * PART, on_chunk=lambda sent: held.append(sent - store.acked)))

    assert max(held) <= 2 * PART + CHUNK
    # And the read overlapped the upload: it went on past a whole part while one was on its way.
    assert max(held) > PART + CHUNK


@pytest.mark.asyncio
async def test_a_sent_part_is_gone_without_waiting_for_the_garbage_collector(monkeypatch):
    _Store(monkeypatch)
    gc.collect()
    gc.disable()
    tracemalloc.start()
    try:
        await _create(_stream(10 * PART))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        gc.enable()
    # One filling, one sending, one being cut from the buffer. Parts left in httpx's
    # reference cycle (``content=``) would add up to the whole body here.
    assert peak < 4 * PART


@pytest.mark.asyncio
async def test_a_short_body_goes_up_whole(monkeypatch):
    store = _Store(monkeypatch)
    whole = AsyncMock(return_value={"resource_id": "r"})
    monkeypatch.setattr(resource_store, "create_resource_from_bytes", whole)

    assert await _create(_stream(PART - 1)) == {"resource_id": "r"}

    assert whole.await_args.kwargs["body"] == bytes(PART - 1)
    store.s3.create_multipart_upload.assert_not_called()


@pytest.mark.asyncio
async def test_the_store_on_an_instances_disk_takes_the_whole_body(monkeypatch):
    store = _Store(monkeypatch)
    monkeypatch.setattr(resource_store.local_object_store, "enabled", lambda: True)
    whole = AsyncMock(return_value={"resource_id": "r"})
    monkeypatch.setattr(resource_store, "create_resource_from_bytes", whole)

    await _create(_stream(2 * PART))

    assert len(whole.await_args.kwargs["body"]) == 2 * PART
    store.s3.create_multipart_upload.assert_not_called()


@pytest.mark.asyncio
async def test_the_stream_raising_drops_the_upload(monkeypatch):
    store = _Store(monkeypatch)

    class Stop(Exception):
        pass

    async def stopping():
        async for chunk in _stream(2 * PART):
            yield chunk
        raise Stop

    with pytest.raises(Stop):
        await _create(stopping())

    assert await store.dropped() and not store.completed
    store.row.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_refused_part_drops_the_upload(monkeypatch):
    store = _Store(monkeypatch, fail_part=2)

    with pytest.raises(httpx.HTTPStatusError):
        await _create(_stream(4 * PART))

    assert await store.dropped() and not store.completed
    store.row.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_deadline_drops_the_upload_without_waiting_for_the_cleanup(monkeypatch):
    store = _Store(monkeypatch)

    async def stalled():
        async for chunk in _stream(2 * PART):
            yield chunk
        await asyncio.sleep(60)

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.2):
            await _create(stalled())

    assert await store.dropped() and not store.completed
