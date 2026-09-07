"""Real pinned instrumentors and observers, with synthetic in-memory transports."""

import ast
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import httpx
from multidict import CIMultiDict
import pytest
from yarl import URL
from opentelemetry import trace
from opentelemetry.instrumentation.aiohttp_client import create_trace_config
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, Sampler
from opentelemetry.trace import SpanKind, Status, StatusCode

from utils.outbound_trace_privacy import OutboundTraceProvider, _safe_url


SECRET = "SYNTHETIC_PRIVATE_TOKEN"
CONTENT = "SYNTHETIC_PRIVATE_COMMENT"
URL_WITH_DATA = f"https://alice:{SECRET}@graph.instagram.com/v21.0/123/replies?access_token={SECRET}&message={CONTENT}#private-fragment"
SAFE_URL = "https://graph.instagram.com/v21.0/123/replies"


class RecordingSampler(Sampler):
    def __init__(self):
        self.observed = []

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None,
                      links=None, trace_state=None):
        self.observed.append((name, dict(attributes or {})))
        return ALWAYS_ON.should_sample(parent_context, trace_id, name, kind, attributes,
                                       links, trace_state)

    def get_description(self):
        return "offline-recording"


class StartObserver(SpanProcessor):
    def __init__(self):
        self.observed = []

    def on_start(self, span, parent_context=None):
        self.observed.append((span.name, dict(span.attributes or {})))


@pytest.fixture
def tracing():
    sampler, observer, exporter = RecordingSampler(), StartObserver(), InMemorySpanExporter()
    provider = TracerProvider(sampler=sampler)
    provider.add_span_processor(observer)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield SimpleNamespace(provider=provider, adapter=OutboundTraceProvider(provider),
                          sampler=sampler, observer=observer, exporter=exporter)
    provider.shutdown()


def assert_private(tracing):
    finished = tracing.exporter.get_finished_spans()
    assert finished
    serialized = repr(tracing.sampler.observed) + repr(tracing.observer.observed)
    for span in finished:
        serialized += span.to_json()
    for forbidden in (SECRET, CONTENT, "alice", "private-fragment", "access_token=", "message="):
        assert forbidden not in serialized
    return finished


@pytest.mark.parametrize("value,expected", [
    (URL_WITH_DATA, SAFE_URL),
    ("https://u:p@[::1]:443/a?q=private#fragment", "https://[::1]:443/a"),
    ("/path?private=value#fragment", "[REDACTED]"),
    ("https://example.test/a%20b?x=1&x=2", "https://example.test/a%20b"),
    ("https://example.test:bad/a?x=1", "[REDACTED]"),
    ("https://[bad/a", "[REDACTED]"),
    ("user:secret@example.test/path", "[REDACTED]"),
    ("ftp://user:secret@example.test/path", "[REDACTED]"),
    ("relative-private-value", "[REDACTED]"),
    ("https://bad host/path", "[REDACTED]"),
    ("https://example.test/\nprivate", "[REDACTED]"),
    (None, "[REDACTED]"),
])
def test_url_redaction(value, expected):
    assert _safe_url(value) == expected


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", [False, True])
async def test_httpx_global_instrumentation_before_observers(monkeypatch, tracing, asynchronous, failure):
    seen = []
    wire_url = URL_WITH_DATA.replace(f"alice:{SECRET}@", "")
    instrumentor = HTTPXClientInstrumentor()
    instrumentor.uninstrument()  # Other test modules can import server.py first.

    def respond(request):
        seen.append(request)
        if failure:
            raise httpx.ConnectError(f"failed {URL_WITH_DATA} body={CONTENT}", request=request)
        return httpx.Response(503, headers={"Set-Cookie": SECRET, "X-Private": CONTENT}, request=request)

    def sync_transport(self, request):
        return respond(request)

    async def async_transport(self, request):
        return respond(request)

    # Patch the real transport boundary before installing the real instrumentor.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_transport)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_transport)
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_REQUEST", ".*")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_RESPONSE", ".*")
    instrumentor.instrument(tracer_provider=tracing.adapter)
    try:
        with tracing.provider.get_tracer("offline-parent").start_as_current_span("parent", record_exception=False, set_status_on_exception=False) as parent:
            try:
                if asynchronous:
                    async with httpx.AsyncClient(trust_env=False) as client:
                        response = await client.post(wire_url, headers={"Authorization": f"Bearer {SECRET}"}, json={"message": CONTENT})
                else:
                    with httpx.Client(trust_env=False) as client:
                        response = client.post(wire_url, headers={"Authorization": f"Bearer {SECRET}"}, json={"message": CONTENT})
            except httpx.ConnectError as exc:
                assert failure
                assert SECRET in str(exc)  # Application errors are not modified.
            else:
                assert not failure and response.status_code == 503
        assert len(seen) == 1
        assert seen[0].url.params["access_token"] == SECRET
        assert seen[0].url.params["message"] == CONTENT
        assert CONTENT.encode() in seen[0].content
        assert seen[0].headers["Authorization"] == f"Bearer {SECRET}"
        assert "traceparent" in seen[0].headers
        spans = assert_private(tracing)
        client_span = next(span for span in spans if span.kind == SpanKind.CLIENT)
        assert client_span.parent.span_id == parent.get_span_context().span_id
        assert client_span.attributes.get("http.url", client_span.attributes.get("url.full")) == SAFE_URL
        assert client_span.attributes.get("http.method", client_span.attributes.get("http.request.method")) == "POST"
        assert client_span.status.status_code == StatusCode.ERROR
        if not failure:
            assert client_span.attributes.get("http.status_code", client_span.attributes.get("http.response.status_code")) == 503
        else:
            assert client_span.events[0].attributes["exception.type"].endswith("ConnectError")
    finally:
        instrumentor.uninstrument()


@pytest.mark.parametrize("failure", [False, True])
async def test_aiohttp_real_trace_callbacks_before_observers(monkeypatch, tracing, failure):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_REQUEST", ".*")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_RESPONSE", ".*")
    config = create_trace_config(tracer_provider=tracing.adapter)
    config.freeze()
    ctx = config.trace_config_ctx()
    headers = CIMultiDict({"Authorization": f"Bearer {SECRET}", "X-Private": CONTENT})
    url = URL(URL_WITH_DATA)
    await config.on_request_start.send(None, ctx, aiohttp.TraceRequestStartParams("POST", url, headers))
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert "traceparent" in headers
    if failure:
        error = aiohttp.ClientConnectionError(f"{URL_WITH_DATA} {CONTENT}")
        await config.on_request_exception.send(None, ctx, aiohttp.TraceRequestExceptionParams("POST", url, headers, error))
    else:
        response = SimpleNamespace(status=200, headers=CIMultiDict({"Set-Cookie": SECRET, "X-Private": CONTENT}))
        await config.on_request_end.send(None, ctx, aiohttp.TraceRequestEndParams("POST", url, headers, response))
    span, = assert_private(tracing)
    assert span.attributes.get("http.url", span.attributes.get("url.full")) == SAFE_URL
    assert span.attributes.get("http.method", span.attributes.get("http.request.method")) == "POST"
    if failure:
        assert span.status.status_code == StatusCode.ERROR
        assert span.events[0].attributes["exception.type"].endswith("ClientConnectionError")
    else:
        assert span.attributes.get("http.status_code", span.attributes.get("http.response.status_code")) == 200


def test_late_attributes_events_links_status_and_semconv_variants(tracing):
    tracer = tracing.adapter.get_tracer("offline-http")
    with tracer.start_as_current_span("POST", kind=SpanKind.CLIENT, attributes={"url.full": URL_WITH_DATA, "http.request.header.authorization": (SECRET,)}) as span:
        span.set_attributes({"http.url": URL_WITH_DATA, "http.target": f"/replies?message={CONTENT}", "url.query": SECRET,
                             "http.response.header.set_cookie": (SECRET,), "http.request.body": CONTENT,
                             "url.fragment": SECRET, "server.address": "graph.instagram.com", "server.port": 443,
                             "http.response.status_code": 200})
        span.set_attribute("http.request.header.x_private", CONTENT)
        span.add_event("exception", {"exception.type": "ValueError", "exception.message": CONTENT, "exception.stacktrace": SECRET})
        span.record_exception(ValueError(f"{URL_WITH_DATA} {CONTENT}"))
        span.add_link(span.get_span_context(), {"url.full": URL_WITH_DATA, "body": CONTENT})
        span.set_status(Status(StatusCode.ERROR, CONTENT))
        span.update_name(SECRET)
    finished, = assert_private(tracing)
    assert finished.attributes["url.full"] == SAFE_URL
    assert finished.attributes["http.url"] == SAFE_URL
    assert finished.attributes["http.target"] == "/replies"
    assert finished.attributes["server.address"] == "graph.instagram.com"
    assert finished.status.description is None
    assert finished.links[0].attributes["url.full"] == SAFE_URL
    assert finished.name == "HTTP"


def test_context_manager_flags_propagation_and_exception_identity(tracing):
    tracer = tracing.adapter.get_tracer("offline-http")
    error = RuntimeError(CONTENT)
    with pytest.raises(RuntimeError) as raised:
        with tracer.start_as_current_span("GET", kind=SpanKind.CLIENT) as span:
            assert trace.get_current_span() is span
            raise error
    assert raised.value is error
    finished, = assert_private(tracing)
    assert finished.status.status_code == StatusCode.ERROR
    assert finished.events[0].attributes["exception.type"] == "builtins.RuntimeError"
    with tracer.start_as_current_span("GET", record_exception=False, set_status_on_exception=False, end_on_exit=False) as held:
        pass
    assert held.is_recording()
    held.end()
    assert len(tracing.exporter.get_finished_spans()) == 2


def test_provider_late_binding_does_not_pin_noop(monkeypatch, tracing):
    proxy_provider = trace.ProxyTracerProvider()
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None)
    monkeypatch.setattr(trace, "_PROXY_TRACER_PROVIDER", proxy_provider)
    tracer = OutboundTraceProvider().get_tracer("offline-http")
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", tracing.provider)
    with tracer.start_as_current_span("GET", kind=SpanKind.CLIENT, attributes={"http.url": URL_WITH_DATA}):
        pass
    assert len(assert_private(tracing)) == 1


def test_both_server_client_instrumentors_use_adapter():
    tree = ast.parse((Path(__file__).parents[1] / "server.py").read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "instrument" and isinstance(node.func.value, ast.Call)
             and isinstance(node.func.value.func, ast.Name)
             and node.func.value.func.id in {"HTTPXClientInstrumentor", "AioHttpClientInstrumentor"}]
    assert len(calls) == 2
    assert all(any(k.arg == "tracer_provider" and isinstance(k.value, ast.Name) and k.value.id == "_outbound_trace_provider" for k in call.keywords) for call in calls)
