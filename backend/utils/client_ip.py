"""The address a request came from: the one rule every per-visitor limit and record of a caller keys on.

Kept apart from any route module so code that only needs the address doesn't import one.

Behind Cloudflare the visitor's address is ``cf-connecting-ip``, but anyone who reaches the origin directly can send
that header too. So it counts only on a request NoClick's own proxy forwarded, which carries ``PROXY_HEADER`` set to
the secret ``PROXY_SECRET_ENV`` names (infra/cloudflare/internal-api-proxy sends it; the origin holds the same
value). Every other request is its connection's peer: the server's own view of the client (uvicorn's, with its
trusted-proxy rules; Modal's, which sets it from the connection).
"""

import hmac
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

PROXY_HEADER = "x-noclick-proxy-secret"
PROXY_SECRET_ENV = "API_PROXY_SECRET"
FORWARDED_HEADER = "cf-connecting-ip"
_unconfigured_logged = False


def _from_proxy(header: Callable[[str], Optional[str]]) -> bool:
    global _unconfigured_logged
    sent = header(PROXY_HEADER)
    if sent is None:
        return False
    secret = os.environ.get(PROXY_SECRET_ENV)
    if not secret:
        if not _unconfigured_logged:
            _unconfigured_logged = True
            logger.error("client_ip: a request carries %s but %s isn't set, so its address is its peer's",
                         PROXY_HEADER, PROXY_SECRET_ENV)
        return False
    return hmac.compare_digest(sent.encode(), secret.encode())


def address(header: Callable[[str], Optional[str]], peer: Optional[str]) -> str:
    """The address of a request whose headers ``header`` reads (by lowercase name) and whose connection's peer is
    ``peer``."""
    forwarded = header(FORWARDED_HEADER) if _from_proxy(header) else None
    if forwarded and forwarded.strip():
        return forwarded.strip()
    return peer or "unknown"


def client_ip(request) -> str:
    return address(request.headers.get, request.client.host if request.client else None)


def environ_ip(environ: dict) -> Optional[str]:
    """The same for an ASGI request seen as a WSGI-style environ (a socket.io connect), whose peer is its scope's."""
    client = (environ.get("asgi.scope") or {}).get("client") or (environ.get("REMOTE_ADDR"), None)
    found = address(lambda name: environ.get("HTTP_" + name.upper().replace("-", "_")), client[0])
    return None if found == "unknown" else found
