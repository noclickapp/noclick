"""Verify node-local transport privacy under real HTTPX tracing and logging."""
import asyncio
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
from nodes import followupboss_node as bk
from utils.outbound_trace_privacy import OutboundTraceProvider
from tests.test_followupboss_native import CREDS, factory, wire


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
        return "Follow Up Boss local collector"


class Observer(SpanProcessor):
    def __init__(self):
        self.attributes = []
    def on_start(self, span, parent_context=None):
        self.attributes.append(dict(span.attributes or {}))


async def synthetic_followupboss_transport(self, request):
    assert isinstance(self._followupboss_transport, httpx.MockTransport)
    return await self._followupboss_transport.handle_async_request(request)


class SyntheticTransport(httpx.AsyncHTTPTransport):
    def __init__(self, reply):
        super().__init__()
        self._followupboss_transport = httpx.MockTransport(reply)


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
        patch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", synthetic_followupboss_transport)
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
async def test_unprotected_collector_canary_reaches_actual_observers(monkeypatch, caplog, collectors):
    url = "https://diagnostic.example.test/health?canary=" + CREDS["system_key"]
    caplog.set_level(logging.INFO, logger="httpx")
    async with httpx.AsyncClient(transport=SyntheticTransport(lambda request: httpx.Response(200, json={"ok": True})), trust_env=False) as client:
        assert (await client.get(url)).status_code == 200
    assert bk.PRIVATE_REQUEST.get() is None and collectors.hooks == [url]
    assert CREDS["system_key"] in caplog.text
    for observed in (collectors.sampler.attributes, collectors.observer.attributes):
        assert CREDS["system_key"] in repr(observed)
    assert CREDS["system_key"] in "".join(span.to_json() for span in collectors.exporter.get_finished_spans())


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_native_real_global_observers_headers_logs_and_concurrent_diagnostics(wire, monkeypatch, caplog, collectors, fail):
    entered, release, requests = asyncio.Event(), asyncio.Event(), []
    safe = bk.BASE + "/[native-resource]"
    unrelated = "https://diagnostic.example.test/health?visible=diagnostic"
    async def respond(request):
        requests.append(request)
        if request.url.host == "api.followupboss.com":
            assert not is_http_instrumentation_enabled()
            assert request.headers["X-System-Key"] == CREDS["system_key"]
            entered.set()
            await release.wait()
            # Actual HTTPcore eager rendering, including protected headers.
            with Trace("receive_response_headers", logging.getLogger("httpcore.http11")) as event:
                event.return_value = (b"HTTP/1.1", 200, CREDS["api_key"].encode(), [(b"x-private", CREDS["system_key"].encode())])
            if fail:
                raise httpx.ReadError("private " + CREDS["system_key"], request=request)
            return httpx.Response(200, json={"id": 1, "account": 7, "name": "Fixture User"})
        assert is_http_instrumentation_enabled() and bk.PRIVATE_REQUEST.get() is None
        return httpx.Response(200, json={"ok": True})
    original = httpx.AsyncClient
    def client(**kwargs):
        return original(**kwargs, transport=SyntheticTransport(respond))
    monkeypatch.setattr(bk, "_http_client", client)
    caplog.set_level(logging.DEBUG, logger="httpcore")
    caplog.set_level(logging.INFO, logger="httpx")
    authority = bk._Authority(CREDS)
    task = asyncio.create_task(bk._Client(authority).request("GET", "/me"))
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
        assert (await task)["id"] == 1
    spans = collectors.exporter.get_finished_spans()
    observed = repr(collectors.sampler.attributes) + repr(collectors.observer.attributes) + repr(collectors.hooks) + repr([r.__dict__ for r in caplog.records]) + "".join(s.to_json() for s in spans)
    for secret in bk._secrets(bk._credential(CREDS)):
        assert secret not in observed
    assert collectors.hooks == [unrelated] and unrelated in caplog.text
    native, = [s for s in spans if s.kind == SpanKind.CLIENT and s.attributes.get("url.full") == safe]
    assert native.attributes["http.request.method"] == "GET"
    assert bk.PRIVATE_REQUEST.get() is None and is_http_instrumentation_enabled()


@pytest.mark.asyncio
async def test_cancellation_restores_native_scopes(wire, monkeypatch):
    entered, restored = asyncio.Event(), []
    async def respond(request):
        entered.set()
        await asyncio.Event().wait()
    original = httpx.AsyncClient
    monkeypatch.setattr(bk, "_http_client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    async def request():
        try:
            await bk._Client(bk._Authority(CREDS)).request("GET", "/me")
        finally:
            restored.append((bk.PRIVATE_REQUEST.get(), is_http_instrumentation_enabled()))
    task = asyncio.create_task(request())
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert restored == [(None, True)]
