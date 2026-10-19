"""Describe a failed token-endpoint response without echoing the provider.

Provider bodies can carry codes, tokens or echoed inputs, so a failure keeps
only its status and a standard OAuth error code: the code is what the refresh
choke point classifies (``invalid_grant`` means reconnect).
"""

import httpx
from opentelemetry import trace

OAUTH_ERROR_CODES = frozenset({
    "invalid_request", "invalid_client", "invalid_grant", "unauthorized_client",
    "unsupported_grant_type", "invalid_scope", "access_denied", "server_error",
    "temporarily_unavailable",
})


def token_error_detail(response: httpx.Response) -> str:
    """``HTTP 400 (invalid_grant)``, or ``HTTP 502`` when the body has no standard code."""
    try:
        body = response.json()
    except ValueError:
        body = None
    code = body.get("error") if isinstance(body, dict) else None
    if not isinstance(code, str) or code not in OAUTH_ERROR_CODES:
        return f"HTTP {response.status_code}"
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute("oauth.provider_error_code", code)
    return f"HTTP {response.status_code} ({code})"
