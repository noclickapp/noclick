"""SSRF guard for user-configured outbound URLs and service connections.

A multi-tenant SaaS that lets users fire arbitrary HTTP requests must refuse to
let them reach internal infrastructure — above all the cloud metadata endpoint
(``169.254.169.254`` / ``fd00:ec2::254``), which hands out the platform's IAM
credentials. This module is the one guard: it validates URL schemes and resolves
hostnames, blocking any request whose host *is* or *resolves to* a private,
loopback, link-local, or otherwise non-public address. It covers both HTTP
endpoints and raw host/port connectors (for example PostgreSQL).

It is wired as an httpx ``request`` event hook (``ssrf_request_hook``), so httpx
calls it for every request it sends — including each redirect hop — closing the
``200 -> 302 -> internal`` redirect bypass.

Guarded HTTP clients also pin each socket connection to an address returned by
the validation lookup. The TLS server name and HTTP Host remain the original
hostname, but the network backend receives the validated IP literal, closing
the usual validate-one-DNS-answer/connect-to-another rebinding bypass.

Local development and trusted self-hosted installs can opt out via
``OUTBOUND_ALLOW_PRIVATE_IPS=true``. The original
``HTTP_NODE_ALLOW_PRIVATE_IPS`` name remains a backwards-compatible alias. Both
are deliberately independent of ``DEV_MODE``, so a leaked dev flag cannot
silently disable this in production.
"""

import asyncio
import ipaddress
import logging
import os
import re
import socket
from collections.abc import Iterable
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = ("http", "https")
_PROVIDER_SUBDOMAIN_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)


class SSRFError(ValueError):
    """An outbound request was blocked because its target is not a public host."""


def normalize_https_origin(
    value: str,
    *,
    field_name: str = "allowed origin",
) -> str:
    """Return a canonical exact HTTPS origin for a user-supplied API host.

    Credential-bearing generic HTTP requests need an explicit destination
    boundary.  Accept a bare HTTPS origin (including an intentional non-default
    port), then remove harmless casing, IDNA, trailing-dot, default-port, and
    trailing-slash differences.  Paths, userinfo, queries, and fragments are
    rejected so a saved credential cannot disguise a broader or different
    authority in this field.
    """
    raw = str(value or "").strip()
    if not raw:
        raise SSRFError(f"{field_name} is required")

    try:
        origin = httpx.URL(raw)
    except (TypeError, ValueError, httpx.InvalidURL) as e:
        raise SSRFError(f"{field_name} is invalid") from e

    if (
        not origin.is_absolute_url
        or origin.scheme != "https"
        or not origin.host
        or bool(origin.username)
        or bool(origin.password)
        or origin.path not in ("", "/")
        or "?" in raw
        or "#" in raw
    ):
        raise SSRFError(f"{field_name} must be an exact HTTPS origin")

    try:
        raw_host = origin.raw_host.decode("ascii").lower().rstrip(".")
        port = origin.port
    except (UnicodeDecodeError, ValueError) as e:
        raise SSRFError(f"{field_name} is invalid") from e
    if not raw_host:
        raise SSRFError(f"{field_name} is invalid")

    # HTTPX exposes an IPv6 raw host without brackets; put them back when
    # serializing the authority. Explicit :443 is already normalized away.
    serialized_host = f"[{raw_host}]" if ":" in raw_host else raw_host
    serialized_port = f":{port}" if port is not None else ""
    return f"https://{serialized_host}{serialized_port}"


def normalize_provider_subdomain(
    value: str,
    provider_domain: str,
    *,
    field_name: str = "account subdomain",
    allow_nested_labels: bool = False,
) -> str:
    """Return a safe tenant label for a code-owned provider domain.

    Tenant-scoped APIs commonly build a host such as
    ``https://{shop}.myshopify.com``. Simply interpolating a credential field
    lets URL delimiters (for example ``127.0.0.1#``) replace the intended host.
    Accept a bare label or a full URL under the expected provider domain, then
    require RFC-compatible DNS labels before interpolation. Most providers use
    exactly one tenant label; providers such as Snowflake may explicitly opt in
    to a validated multi-label account identifier.

    This is deliberately separate from :func:`assert_url_allowed`: the final
    provider host is code-owned and need not opt in to private-host access, but
    its user-controlled tenant component must not be able to change that host.
    """
    raw = str(value or "").strip()
    if not raw:
        raise SSRFError(f"{field_name} is required")

    domain = str(provider_domain or "").strip().lower().rstrip(".")
    if not domain:
        raise ValueError("provider_domain is required")

    try:
        parts = urlsplit(raw if "://" in raw else f"//{raw}")
        port = parts.port
    except ValueError as e:
        raise SSRFError(f"{field_name} is invalid") from e

    if parts.scheme and parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise SSRFError(f"{field_name} must use http or https")
    if parts.username is not None or parts.password is not None or port is not None:
        raise SSRFError(f"{field_name} must not contain credentials or a port")

    host = (parts.hostname or "").lower().rstrip(".")
    suffix = f".{domain}"
    label = host[: -len(suffix)] if host.endswith(suffix) else host
    labels = label.split(".") if allow_nested_labels else [label]
    if (
        not labels
        or (not allow_nested_labels and "." in label)
        or any(not _PROVIDER_SUBDOMAIN_RE.fullmatch(part) for part in labels)
    ):
        qualifier = "valid DNS labels" if allow_nested_labels else "a single DNS label"
        raise SSRFError(f"{field_name} must contain {qualifier}")
    return label


def normalize_provider_https_origin(
    value: str,
    provider_domain: str,
    *,
    field_name: str = "provider origin",
    allow_nested_labels: bool = False,
) -> str:
    """Return a canonical HTTPS origin below a code-owned provider domain.

    OAuth token responses sometimes supply the origin that will receive the
    newly issued bearer token.  Treat that value as untrusted: it may select a
    tenant below the provider suffix, but it may not select a scheme, port,
    path, query, fragment, or userinfo.  Bare legacy host values are accepted
    and canonicalized to an HTTPS origin.
    """
    raw = str(value or "").strip()
    if not raw:
        raise SSRFError(f"{field_name} is required")

    domain = str(provider_domain or "").strip().lower().rstrip(".")
    if not domain:
        raise ValueError("provider_domain is required")
    if "://" in raw:
        candidate = raw
    elif "." not in raw.rstrip("/"):
        candidate = f"https://{raw}.{domain}"
    else:
        candidate = f"https://{raw}"
    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError as e:
        raise SSRFError(f"{field_name} is invalid") from e

    if (
        parts.scheme.lower() != "https"
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or parts.path not in ("", "/")
        or bool(parts.query)
        or bool(parts.fragment)
    ):
        raise SSRFError(f"{field_name} must be a canonical HTTPS origin")

    host = (parts.hostname or "").lower().rstrip(".")
    if not host.endswith(f".{domain}"):
        raise SSRFError(f"{field_name} must be hosted below {domain}")

    label = normalize_provider_subdomain(
        candidate,
        domain,
        field_name=field_name,
        allow_nested_labels=allow_nested_labels,
    )
    return f"https://{label}.{domain}"


def allow_private_hosts() -> bool:
    """Whether private/loopback targets are permitted (local dev & tests only)."""
    truthy = {"1", "true", "yes"}
    current = os.environ.get("OUTBOUND_ALLOW_PRIVATE_IPS", "").strip().lower()
    if current:
        return current in truthy
    legacy = os.environ.get("HTTP_NODE_ALLOW_PRIVATE_IPS", "").strip().lower()
    return legacy in truthy


# Ranges that some Python versions don't flag via is_private/is_reserved but that
# must never be reachable (CGNAT can route to internal infra; the rest are
# special-purpose / not globally routable).
_EXTRA_BLOCKED_NETS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "100.64.0.0/10",  # CGNAT / shared address space
        "192.0.0.0/24",  # IETF protocol assignments
        "192.0.2.0/24",  # TEST-NET-1
        "198.18.0.0/15",  # benchmarking
        "198.51.100.0/24",  # TEST-NET-2
        "203.0.113.0/24",  # TEST-NET-3
        "64:ff9b::/96",  # NAT64
    )
)


def is_blocked_ip(ip_str: str) -> bool:
    """True if *ip_str* is an address an outbound user request must not reach."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable — refuse rather than guess
    # IPv4-mapped IPv6 (e.g. ::ffff:10.0.0.1) — judge by the embedded v4 address
    # so the mapping can't be used to smuggle a private target past the checks.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private  # RFC1918, ULA fc00::/7, 0.0.0.0/8, ...
        or ip.is_loopback  # 127.0.0.0/8, ::1
        or ip.is_link_local  # 169.254.0.0/16 (incl. metadata), fe80::/10
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified  # 0.0.0.0, ::
        or not ip.is_global  # catch-all for anything not publicly routable
    ):
        return True
    return any(ip in net for net in _EXTRA_BLOCKED_NETS)


def _assert_ip_allowed(ip_str: str) -> None:
    if is_blocked_ip(ip_str):
        raise SSRFError(f"Refusing to connect to non-public address {ip_str}")


async def _resolve_host_addresses(
    host: str,
    port: int,
    *,
    permit_non_public: bool = False,
) -> list[str]:
    """Resolve once and return addresses safe to pass to a socket backend."""
    normalized_host = str(host or "").strip().removeprefix("[").removesuffix("]")
    if not normalized_host:
        raise SSRFError("Connection target has no host")

    try:
        literal = ipaddress.ip_address(normalized_host)
    except ValueError:
        pass
    else:
        address = str(literal)
        if not permit_non_public:
            _assert_ip_allowed(address)
        return [address]

    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(
            normalized_host,
            port,
            type=socket.SOCK_STREAM,
        )
    except (OSError, UnicodeError) as e:
        raise SSRFError(f"Could not resolve host '{normalized_host}': {e}") from e

    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if address in addresses:
            continue
        if not permit_non_public and is_blocked_ip(address):
            raise SSRFError(
                f"Refusing to connect to '{normalized_host}' — it resolves to "
                f"non-public address {address}"
            )
        addresses.append(address)
    if not addresses:
        raise SSRFError(f"Host '{normalized_host}' did not resolve to any address")
    return addresses


async def assert_host_allowed(host: str, port: int | None = None) -> None:
    """Resolve *host* and block non-public connection targets.

    Use this for user-configured non-HTTP connectors. URL callers should use
    :func:`assert_url_allowed`, which also enforces the scheme and parses the
    port. Resolution errors fail closed.
    """
    host = str(host or "").strip().removeprefix("[").removesuffix("]")
    if not host:
        raise SSRFError("Connection target has no host")
    if port is not None and (
        isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
    ):
        raise SSRFError(f"Connection target has an invalid port: {port!r}")

    if allow_private_hosts():
        return

    await _resolve_host_addresses(host, port or 0)


async def resolve_host_addresses(host: str, port: int) -> list[str]:
    """Resolve once and return the exact addresses a raw client may dial.

    Validation followed by handing the hostname to a database driver leaves a
    DNS-rebinding window: the driver can resolve a different address. Raw
    connectors use this helper and pass one of the returned IP literals to
    their socket layer. The explicit private-host development override is
    honored, but resolution is still pinned to one lookup.
    """
    normalized_host = str(host or "").strip().removeprefix("[").removesuffix("]")
    if not normalized_host:
        raise SSRFError("Connection target has no host")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SSRFError(f"Connection target has an invalid port: {port!r}")
    return await _resolve_host_addresses(
        normalized_host,
        port,
        permit_non_public=allow_private_hosts(),
    )


async def assert_url_allowed(url: str) -> None:
    """Validate scheme and resolve the host, blocking non-public targets.

    Raises :class:`SSRFError` if the scheme is not http(s), the URL has no host,
    the host cannot be resolved, or the host is/resolves to a private, loopback,
    link-local, or reserved address.
    """
    try:
        parts = urlsplit(url)
    except ValueError as e:
        raise SSRFError("URL is invalid") from e
    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFError(
            f"Unsupported URL scheme '{parts.scheme or ''}'. Only http and https are allowed."
        )
    host = parts.hostname
    if not host:
        raise SSRFError("URL has no host")

    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as e:
        raise SSRFError("URL has an invalid port") from e
    await assert_host_allowed(host, port)


def assert_exact_url_origin(url: str, allowed_origin: str) -> None:
    """Require *url* to use one exact HTTPS origin.

    This is for opaque pagination/delta URLs that are later sent with a
    provider bearer token.  Comparing HTTPX's parsed origin (rather than a
    string prefix) rejects userinfo tricks, suffix hosts, alternate ports, and
    parser ambiguities before the credential is attached to the request.
    """
    try:
        target = httpx.URL(url)
        allowed = httpx.URL(allowed_origin)
    except (TypeError, ValueError) as e:
        raise SSRFError("URL is invalid") from e

    if allowed.scheme != "https" or not allowed.host:
        raise RuntimeError("allowed_origin must be an absolute HTTPS origin")
    if allowed.username or allowed.password or allowed.path not in ("", "/"):
        raise RuntimeError("allowed_origin must not include credentials or a path")

    target_port = target.port or (443 if target.scheme == "https" else None)
    allowed_port = allowed.port or 443
    if (
        not target.is_absolute_url
        or target.scheme != "https"
        or bool(target.username)
        or bool(target.password)
        or (target.host or "").lower().rstrip(".")
        != allowed.host.lower().rstrip(".")
        or target_port != allowed_port
    ):
        raise SSRFError(
            f"Refusing credentialed request outside {allowed.scheme}://{allowed.host}"
        )


def ssrf_request_hook():
    """An httpx ``request`` event hook that blocks SSRF targets on every hop."""

    async def _hook(request: httpx.Request) -> None:
        await assert_url_allowed(str(request.url))

    return _hook


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve, validate, and connect to that exact IP address.

    HTTP Core still owns the origin hostname, so its later TLS call uses the
    correct SNI/certificate name and HTTPX sends the original Host header. Only
    the TCP dial target is replaced with the validated IP literal.
    """

    def __init__(
        self,
        *,
        trusted_dial_context: ContextVar[tuple[str, int] | None] | None = None,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._trusted_dial_context = trusted_dial_context
        self._backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if allow_private_hosts():
            return await self._backend.connect_tcp(
                host,
                port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )

        normalized_target = (host.lower().rstrip("."), port)
        trusted = bool(
            self._trusted_dial_context
            and self._trusted_dial_context.get() == normalized_target
        )
        addresses = await _resolve_host_addresses(
            host,
            port,
            permit_non_public=trusted,
        )
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as e:
                last_error = e
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise SSRFError("Unix sockets are not allowed for guarded HTTP requests")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport whose HTTP Core pool uses the pinned network backend."""

    def __init__(
        self,
        *,
        trusted_dial_context: ContextVar[tuple[str, int] | None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        # HTTPX/httpcore are lockfile-pinned. Fail closed on an incompatible
        # upgrade rather than silently falling back to the default resolver.
        if not hasattr(self._pool, "_network_backend"):
            raise RuntimeError("HTTP transport does not expose a pinnable network backend")
        self._pool._network_backend = _PinnedNetworkBackend(  # type: ignore[attr-defined]
            trusted_dial_context=trusted_dial_context
        )


def guarded_async_client(
    *, trusted_exact_urls: Iterable[str] = (), **kwargs
) -> httpx.AsyncClient:
    """Return an ``httpx`` client guarded on every request and redirect hop.

    Existing event hooks are preserved. Dynamic-destination call sites should
    use this factory instead of constructing ``httpx.AsyncClient`` directly.
    Fixed, code-owned provider endpoints do not need it.

    ``trusted_exact_urls`` is only for an exact URL minted after an ownership
    check (for example a workflow-scoped object-store URL). Those exact URLs
    may resolve privately; every other request, including any redirect target,
    remains guarded. Never pass raw user input through this escape hatch.
    """
    normalized_trusted_urls: dict[str, tuple[str, int]] = {}
    for raw_url in trusted_exact_urls:
        if not str(raw_url).strip():
            continue
        parsed = httpx.URL(raw_url)
        if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.host:
            raise ValueError("trusted_exact_urls entries must be absolute HTTP(S) URLs")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        normalized_trusted_urls[str(parsed)] = (
            parsed.host.lower().rstrip("."),
            port,
        )
    trusted_host_ports = set(normalized_trusted_urls.values())

    # Trust is scoped to the exact request whose hook just ran, not to the
    # whole host for the lifetime of the client. Otherwise a redirect to a
    # different path on the same storage host could inherit the private-host
    # escape hatch, and a second DNS answer could rebind it internally.
    trusted_dial_context: ContextVar[tuple[str, int] | None] = ContextVar(
        "guarded_http_trusted_dial", default=None
    )

    async def _guard_request(request: httpx.Request) -> None:
        trusted_target = normalized_trusted_urls.get(str(request.url))
        trusted_dial_context.set(trusted_target)
        if trusted_target is not None:
            return
        request_port = request.url.port or (
            443 if request.url.scheme == "https" else 80
        )
        request_host_port = (
            (request.url.host or "").lower().rstrip("."),
            request_port,
        )
        if request_host_port in trusted_host_ports:
            # The exact URL may already have opened a pooled connection to a
            # private object-store host. Never let a non-exact redirect/request
            # reuse that connection; only separately ownership-checked exact
            # URLs in the input set may use this host within this client.
            raise SSRFError(
                "Refusing non-exact request on an exact-trust storage origin"
            )
        await assert_url_allowed(str(request.url))

    event_hooks = {
        name: list(hooks)
        for name, hooks in (kwargs.pop("event_hooks", None) or {}).items()
    }
    event_hooks.setdefault("request", []).insert(0, _guard_request)

    supplied_transport = kwargs.get("transport")
    if supplied_transport is not None:
        # MockTransport performs no network I/O and is used by unit tests. An
        # arbitrary transport could dial around the pinned backend, so reject it.
        if not isinstance(supplied_transport, httpx.MockTransport):
            raise ValueError("guarded_async_client does not accept custom network transports")
    else:
        if kwargs.get("proxy") is not None or kwargs.get("mounts") is not None:
            raise ValueError("guarded_async_client does not allow proxy or mount bypasses")
        transport_kwargs = {
            name: kwargs[name]
            for name in ("verify", "cert", "trust_env", "http1", "http2", "limits")
            if name in kwargs
        }
        kwargs["transport"] = _PinnedAsyncHTTPTransport(
            trusted_dial_context=trusted_dial_context,
            **transport_kwargs,
        )
    return httpx.AsyncClient(event_hooks=event_hooks, **kwargs)
