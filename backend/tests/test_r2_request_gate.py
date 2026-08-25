"""The shared R2 httpx client caps in-flight requests with an asyncio gate.

A CAS chunk fan-out must wait in the application-level semaphore (O(1) FIFO
wakeups), never inside httpcore's request queue, which rescans every
queued request on every completion, which is quadratic on-CPU load on the
event loop. The gate holds in-flight requests at exactly the client's
connection count, so httpcore's queue stays empty.
"""

import asyncio
from contextlib import ExitStack
from unittest.mock import patch

import httpx
import pytest

from utils import r2_cloudflare


class _CountingClient:
    """Fake AsyncClient tracking the concurrent-request high-water mark."""

    is_closed = False

    def __init__(self, latency_s: float = 0.02):
        self.latency_s = latency_s
        self.active = 0
        self.high_water = 0

    async def _serve(self, method: str, url: str) -> httpx.Response:
        self.active += 1
        self.high_water = max(self.high_water, self.active)
        await asyncio.sleep(self.latency_s)
        self.active -= 1
        return httpx.Response(
            204 if method == "DELETE" else 200,
            request=httpx.Request(method, url), content=b"x")

    async def get(self, url):
        return await self._serve("GET", url)

    async def put(self, url, content=None, headers=None):
        return await self._serve("PUT", url)

    async def delete(self, url):
        return await self._serve("DELETE", url)


def _patch_client(stack: ExitStack, client: _CountingClient) -> None:
    fake_sign = lambda **kw: f"https://fake-r2/{kw['bucket']}/{kw['key']}"  # noqa: E731
    stack.enter_context(patch.object(r2_cloudflare, "_get_r2_http_client", lambda: client))
    stack.enter_context(patch.object(r2_cloudflare, "generate_presigned_download_url", fake_sign))
    stack.enter_context(patch.object(r2_cloudflare, "generate_presigned_upload_url", fake_sign))
    stack.enter_context(patch.object(r2_cloudflare, "generate_presigned_delete_url", fake_sign))


@pytest.mark.asyncio
async def test_gate_caps_inflight_requests_across_ops():
    """100 concurrent GET/PUT/DELETE callers → at most _R2_MAX_CONCURRENCY
    requests ever inside the client at once, and all complete."""
    client = _CountingClient()
    with ExitStack() as stack:
        _patch_client(stack, client)
        results = await asyncio.gather(
            *[r2_cloudflare.download_bytes_from_r2_async_native("b", f"k{i}")
              for i in range(60)],
            *[r2_cloudflare.upload_bytes_to_r2_async(
                bucket="b", key=f"u{i}", body=b"x", content_type="text/plain")
              for i in range(30)],
            r2_cloudflare.delete_files_from_r2_async_native(
                "b", [f"d{i}" for i in range(10)]),
        )
    assert client.high_water == r2_cloudflare._R2_MAX_CONCURRENCY, (
        f"high-water {client.high_water} — requests are queueing inside "
        "httpcore (quadratic rescans) instead of the semaphore")
    content, ctype = results[0]
    assert content == b"x" and ctype == "application/octet-stream"
    assert results[-1] == 10  # delete returns the key count


def test_gate_rebinds_per_event_loop():
    """asyncio primitives bind to the loop that first awaits them under
    contention. pytest and asyncio.run both cycle event loops, so the gate
    must be recreated per loop — a module-level Semaphore would raise
    'bound to a different event loop' on the second run."""
    async def contended_burst():
        client = _CountingClient(latency_s=0.001)
        with ExitStack() as stack:
            _patch_client(stack, client)
            await asyncio.gather(
                *[r2_cloudflare.download_bytes_from_r2_async_native("b", f"k{i}")
                  for i in range(2 * r2_cloudflare._R2_MAX_CONCURRENCY)])

    asyncio.run(contended_burst())
    asyncio.run(contended_burst())  # fresh loop; must not raise
