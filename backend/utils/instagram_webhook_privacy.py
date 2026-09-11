"""Keep Instagram/Facebook callback verification material out of server telemetry.

Meta sends the verification token in a GET query, unlike signed POST bodies.
The request hook runs before routing; it preserves that query only for the
handshake and clears the shared ASGI query before response/access logging.
Proxy/platform access logs remain an operator configuration responsibility.
"""

from starlette.datastructures import QueryParams

_PATHS = {"/webhook/app/instagram", "/webhook/app/facebook"}
_QUERY_KEY = "_instagram_callback_query"


def instagram_webhook_request_hook(span, scope):
    if scope.get("path", "").rstrip("/") not in _PATHS:
        return
    raw_query = scope.get("query_string", b"")
    if raw_query:
        if scope.get("method") == "GET":
            scope[_QUERY_KEY] = raw_query
        scope["query_string"] = b""
    if not span or not span.is_recording():
        return
    # Auto-instrumentation has already collected request attributes. Keep
    # method/status/path diagnostics but no query or captured signature/header.
    for key, value in dict(getattr(span, "attributes", {}) or {}).items():
        if key in ("http.url", "url.full", "http.target") and isinstance(value, str):
            span.set_attribute(key, value.partition("?")[0])
        elif key == "url.query" or key.startswith("http.request.header."):
            span.set_attribute(key, "[REDACTED]")


def consume_instagram_verification_query(request):
    raw_query = request.scope.pop(_QUERY_KEY, request.scope.get("query_string", b""))
    request.scope["query_string"] = b""
    return QueryParams(raw_query)
