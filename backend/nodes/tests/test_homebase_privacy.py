"""Exercise global HTTPX instrumentation/logging with local collectors.

The synthetic transport makes no socket/provider/collector connection.
"""
import asyncio
import base64
import logging
from types import SimpleNamespace
import httpx
from httpcore._trace import Trace
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.utils import is_http_instrumentation_enabled
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, Sampler
from opentelemetry.trace import SpanKind
import pytest
from nodes import homebase_node as bk
from utils import ssrf
from utils.outbound_trace_privacy import OutboundTraceProvider
from nodes.tests.test_homebase_node_integration import CREDS, ME, wire


@pytest.fixture
def ensure_native_db_pool():
    yield


class ObservedSampler(Sampler):
    def __init__(self):
        self.attributes = []
    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None, trace_state=None):
        self.attributes.append(dict(attributes or {}))
        return ALWAYS_ON.should_sample(parent_context, trace_id, name, kind, attributes, links, trace_state)
    def get_description(self):
        return "Homebase local collector"


class Observer(SpanProcessor):
    def __init__(self):
        self.attributes = []
    def on_start(self, span, parent_context=None):
        self.attributes.append(dict(span.attributes or {}))


async def synthetic_homebase_transport(self, request):
    assert isinstance(self._homebase_transport, httpx.MockTransport)
    return await self._homebase_transport.handle_async_request(request)


class SyntheticTransport(httpx.AsyncHTTPTransport):
    def __init__(self, reply):
        super().__init__()
        self._homebase_transport = httpx.MockTransport(reply)


@pytest.fixture
def collectors(monkeypatch):
    sampler, observer, exporter = ObservedSampler(), Observer(), InMemorySpanExporter()
    provider = TracerProvider(sampler=sampler)
    provider.add_span_processor(observer)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor, hooks = HTTPXClientInstrumentor(), []
    previous = instrumentor.is_instrumented_by_opentelemetry
    if previous:
        instrumentor.uninstrument()
    async def hook(span, request):
        hooks.append(str(request.url))
    with monkeypatch.context() as patch:
        patch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", synthetic_homebase_transport)
        patch.setattr(trace, "get_tracer_provider", lambda: provider)
        patch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_REQUEST", ".*")
        patch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_RESPONSE", ".*")
        instrumentor.instrument(tracer_provider=provider, async_request_hook=hook)
        try:
            yield SimpleNamespace(provider=provider, sampler=sampler, observer=observer, exporter=exporter, hooks=hooks)
        finally:
            instrumentor.uninstrument()
    if previous:
        instrumentor.instrument(tracer_provider=OutboundTraceProvider())
    provider.shutdown()


@pytest.mark.asyncio
async def test_unprotected_collector_canary_reaches_actual_observers(caplog, collectors):
    url = "https://diagnostic.example.test/health?canary=" + CREDS["api_key"]
    caplog.set_level(logging.INFO, logger="httpx")
    async with httpx.AsyncClient(transport=SyntheticTransport(lambda request: httpx.Response(200, json={"ok": True})), trust_env=False) as client:
        assert (await client.get(url)).status_code == 200
    assert bk.PRIVATE_REQUEST.get() is False and collectors.hooks == [url]
    assert CREDS["api_key"] in caplog.text
    for observed in (collectors.sampler.attributes, collectors.observer.attributes):
        assert CREDS["api_key"] in repr(observed)
    assert CREDS["api_key"] in "".join(span.to_json() for span in collectors.exporter.get_finished_spans())


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_native_global_observers_key_header_logs_and_concurrent_diagnostics(wire, monkeypatch, caplog, collectors, fail):
    entered, release = asyncio.Event(), asyncio.Event()
    unrelated = "https://diagnostic.example.test/health?visible=diagnostic"
    async def respond(request):
        if request.url.path == "/company":
            assert not is_http_instrumentation_enabled()
            assert request.headers["Authorization"] == "Bearer " + CREDS["api_key"]
            entered.set()
            await release.wait()
            with Trace("receive_response_headers", logging.getLogger("httpcore.http11")) as event:
                event.return_value = (b"HTTP/1.1", 200, CREDS["api_key"].encode(), [(b"x-private", request.headers["Authorization"].encode())])
            if fail:
                raise httpx.ReadError("private " + CREDS["api_key"], request=request)
            return httpx.Response(200, json=ME)
        assert is_http_instrumentation_enabled() and bk.PRIVATE_REQUEST.get() is False
        return httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(ssrf, "_PinnedAsyncHTTPTransport", lambda **kwargs: SyntheticTransport(respond))
    monkeypatch.setattr(bk, "guarded_async_client", ssrf.guarded_async_client)
    caplog.set_level(logging.DEBUG, logger="httpcore")
    caplog.set_level(logging.INFO, logger="httpx")
    task = asyncio.create_task(bk._Client(bk._Authority(CREDS)).company())
    await asyncio.wait_for(entered.wait(), timeout=2)
    try:
        async with httpx.AsyncClient(transport=SyntheticTransport(respond), trust_env=False) as ordinary:
            assert (await ordinary.get(unrelated)).status_code == 200
    finally:
        release.set()
    if fail:
        with pytest.raises(ValueError, match="unverified") as error:
            await task
        assert error.value.__suppress_context__
    else:
        assert (await task) == {"name": "Fixture Company", "owner_id": 7}
    spans = collectors.exporter.get_finished_spans()
    observed = repr(collectors.sampler.attributes) + repr(collectors.observer.attributes) + repr(collectors.hooks) + repr([r.__dict__ for r in caplog.records]) + "".join(s.to_json() for s in spans)
    for secret in {CREDS["api_key"], base64.b64encode(CREDS["api_key"].encode()).decode(), CREDS["api_key"].encode().hex()}:
        assert secret not in observed
    assert collectors.hooks == [unrelated] and unrelated in caplog.text
    native = [s for s in spans if s.kind == SpanKind.CLIENT and s.attributes.get("url.full") == "https://api.joinhomebase.com/[native-resource]"]
    assert len(native) == 1 and all(s.attributes["http.request.method"] == "GET" for s in native)
    assert bk.PRIVATE_REQUEST.get() is False and is_http_instrumentation_enabled()


@pytest.mark.asyncio
async def test_cancel_restores_scoped_privacy_and_http_instrumentation(wire, monkeypatch):
    entered, restored = asyncio.Event(), []
    async def respond(request):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(bk, "guarded_async_client", lambda **kwargs: ssrf.guarded_async_client(**kwargs, transport=httpx.MockTransport(respond)))
    async def request():
        try:
            await bk._Client(bk._Authority(CREDS)).company()
        finally:
            restored.append((bk.PRIVATE_REQUEST.get(), is_http_instrumentation_enabled()))
    task = asyncio.create_task(request())
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert restored == [(False, True)]
