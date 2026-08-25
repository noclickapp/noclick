"""Regression test for aiohttp client OpenTelemetry instrumentation.

LiteLLM's streaming completion path drops to aiohttp instead of httpx, so
without ``AioHttpClientInstrumentor`` those outbound calls show up as
unattributed client time in request traces. This test
verifies that:

1. After both ``AioHttpClientInstrumentor`` and ``HTTPXClientInstrumentor``
   are wired against the same TracerProvider, an aiohttp request emits
   exactly one CLIENT span (no double-count from the two instrumentors).
2. An httpx request still emits exactly one CLIENT span — the aiohttp
   instrumentor does not steal or duplicate httpx traffic.
"""

import aiohttp
import httpx
import pytest
import pytest_asyncio
from aiohttp import web
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


_AIOHTTP_SCOPE_PREFIX = "opentelemetry.instrumentation.aiohttp_client"
_HTTPX_SCOPE_PREFIX = "opentelemetry.instrumentation.httpx"


@pytest_asyncio.fixture
async def echo_server():
    """Tiny in-process aiohttp server bound to a random localhost port."""
    async def hello(_request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", hello)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        await runner.cleanup()


@pytest.fixture
def instrumented_exporter():
    """Spin up a fresh TracerProvider + InMemorySpanExporter, wire both
    HTTP-client instrumentors against it, and tear them down afterwards."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    aiohttp_instr = AioHttpClientInstrumentor()
    httpx_instr = HTTPXClientInstrumentor()

    # Both instrumentors are singletons globally, so uninstrument first to
    # shake off any state left by server instrumentation or earlier tests.
    aiohttp_instr.uninstrument()
    httpx_instr.uninstrument()
    aiohttp_instr.instrument(tracer_provider=provider)
    httpx_instr.instrument(tracer_provider=provider)
    try:
        yield exporter
    finally:
        aiohttp_instr.uninstrument()
        httpx_instr.uninstrument()


def _scope_buckets(spans):
    aiohttp_spans = [
        s for s in spans
        if s.instrumentation_scope.name.startswith(_AIOHTTP_SCOPE_PREFIX)
    ]
    httpx_spans = [
        s for s in spans
        if s.instrumentation_scope.name.startswith(_HTTPX_SCOPE_PREFIX)
    ]
    return aiohttp_spans, httpx_spans


async def test_aiohttp_request_emits_one_client_span_no_httpx_double_count(
    echo_server, instrumented_exporter,
):
    """An aiohttp request must produce exactly one aiohttp client span and
    zero httpx spans even though both instrumentors are active."""
    async with aiohttp.ClientSession() as session:
        async with session.get(echo_server) as resp:
            assert resp.status == 200

    aiohttp_spans, httpx_spans = _scope_buckets(
        instrumented_exporter.get_finished_spans()
    )
    assert len(aiohttp_spans) == 1, (
        f"expected exactly one aiohttp client span, got {len(aiohttp_spans)} "
        "— double-count regression?"
    )
    assert len(httpx_spans) == 0, (
        f"expected zero httpx spans for an aiohttp request, got {len(httpx_spans)}"
    )


async def test_httpx_request_still_emits_one_client_span_under_aiohttp_instr(
    echo_server, instrumented_exporter,
):
    """Adding the aiohttp instrumentor must not steal or duplicate httpx
    spans — the existing httpx coverage stays intact."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(echo_server)
        assert resp.status_code == 200

    aiohttp_spans, httpx_spans = _scope_buckets(
        instrumented_exporter.get_finished_spans()
    )
    assert len(httpx_spans) == 1, (
        f"expected exactly one httpx client span, got {len(httpx_spans)}"
    )
    assert len(aiohttp_spans) == 0, (
        f"expected zero aiohttp spans for an httpx request, got {len(aiohttp_spans)}"
    )
