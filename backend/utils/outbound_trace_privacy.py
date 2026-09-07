"""Keep queries, userinfo, headers and bodies out of HTTP client spans.

Wrap the public tracing API before sampling, not just the exporter: request
hooks run after span creation and cannot protect sampler/on_start observers.
Paths remain diagnostic data; caller spans and ordinary logs are not modified.
"""

from contextlib import contextmanager
import re
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import trace
from opentelemetry.trace import Link, SpanKind, Status


_URL_KEYS = {"http.url", "url.full", "http.target", "url.path"}
_DIAGNOSTIC_KEYS = {
    "http.method", "http.request.method", "http.status_code",
    "http.response.status_code", "http.flavor", "http.scheme", "url.scheme",
    "server.address", "server.port", "net.peer.name", "net.peer.port",
    "net.transport", "network.transport", "network.protocol.name",
    "network.protocol.version", "http.request.resend_count",
}
_TYPE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\Z")
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"}


def _safe_url(value, *, relative=False):
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return "[REDACTED]"
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            if not host or any(char.isspace() for char in host):
                return "[REDACTED]"
            host = f"[{host}]" if ":" in host else host
            netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
        elif relative and value.startswith("/") and not value.startswith("//") and not parsed.scheme and not parsed.netloc:
            netloc = ""
        else:
            return "[REDACTED]"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except ValueError:
        return "[REDACTED]"


def _safe_attributes(attributes):
    result = {}
    for key, value in (attributes or {}).items():
        if key in _URL_KEYS:
            result[key] = _safe_url(value, relative=key in {"http.target", "url.path"})
        elif key in _DIAGNOSTIC_KEYS:
            result[key] = value
        elif key == "error.type" and isinstance(value, str):
            result[key] = value if _TYPE_NAME.fullmatch(value) or value.isdecimal() else "Error"
    return result


class _PrivateHttpSpan(trace.Span):
    def __init__(self, span):
        self._span = span

    def get_span_context(self):
        return self._span.get_span_context()

    def is_recording(self):
        return self._span.is_recording()

    def end(self, end_time=None):
        self._span.end(end_time=end_time)

    def set_attribute(self, key, value):
        self.set_attributes({key: value})

    def set_attributes(self, attributes):
        self._span.set_attributes(_safe_attributes(attributes))

    def set_status(self, status, description=None):
        # Transport exception descriptions can embed URLs, headers or bodies.
        code = status.status_code if isinstance(status, Status) else status
        self._span.set_status(Status(code))

    def update_name(self, name):
        self._span.update_name(name if name in _HTTP_METHODS else "HTTP")

    def add_event(self, name, attributes=None, timestamp=None):
        safe = {}
        if name == "exception":
            attrs = attributes or {}
            exception_type = attrs.get("exception.type")
            if isinstance(exception_type, str) and _TYPE_NAME.fullmatch(exception_type):
                safe["exception.type"] = exception_type
            if isinstance(attrs.get("exception.escaped"), bool):
                safe["exception.escaped"] = attrs["exception.escaped"]
        self._span.add_event("exception" if name == "exception" else "http.event", safe, timestamp)

    def record_exception(self, exception, attributes=None, timestamp=None, escaped=False):
        exception_type = type(exception)
        self.add_event("exception", {
            "exception.type": f"{exception_type.__module__}.{exception_type.__qualname__}",
            "exception.escaped": escaped,
        }, timestamp)

    def add_link(self, context, attributes=None):
        self._span.add_link(context, attributes=_safe_attributes(attributes))


class _PrivateHttpTracer(trace.Tracer):
    def __init__(self, tracer):
        self._tracer = tracer

    def start_span(self, name, context=None, kind=SpanKind.INTERNAL, attributes=None,
                   links=None, start_time=None, record_exception=True,
                   set_status_on_exception=True):
        safe_name = name if name in _HTTP_METHODS else "HTTP"
        span = self._tracer.start_span(
            safe_name, context=context, kind=kind, attributes=_safe_attributes(attributes),
            links=[Link(link.context, _safe_attributes(link.attributes)) for link in (links or ())],
            start_time=start_time, record_exception=False, set_status_on_exception=False,
        )
        return _PrivateHttpSpan(span)

    @contextmanager
    def start_as_current_span(self, name, context=None, kind=SpanKind.INTERNAL,
                              attributes=None, links=None, start_time=None,
                              record_exception=True, set_status_on_exception=True,
                              end_on_exit=True):
        span = self.start_span(name, context, kind, attributes, links, start_time)
        with trace.use_span(span, end_on_exit=end_on_exit,
                            record_exception=record_exception,
                            set_status_on_exception=set_status_on_exception):
            yield span


class OutboundTraceProvider(trace.TracerProvider):
    """Delegate only HTTP client instrumentors through a privacy boundary."""

    def __init__(self, provider=None):
        self._provider = provider

    def get_tracer(self, instrumenting_module_name, instrumenting_library_version=None,
                   schema_url=None, attributes=None):
        provider = self._provider or trace.get_tracer_provider()
        tracer = provider.get_tracer(instrumenting_module_name, instrumenting_library_version,
                                     schema_url=schema_url, attributes=attributes)
        return _PrivateHttpTracer(tracer)
