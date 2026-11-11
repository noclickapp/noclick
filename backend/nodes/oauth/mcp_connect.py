"""Connecting an integration through its vendor's MCP server.

The MCP auth spec, run for an integration that declares its server
(``nodes.core.vendor_mcp.mcp_credential``), in two calls so either surface can
drive it: the signed-in app over the socket (``mcp:connect:start|finish``) and
a provide link over HTTP (``/api/credential-request/{token}/mcp/*``).

``start`` discovers the server's auth (RFC 9728 protected resource metadata,
then the authorization server's RFC 8414 metadata, ``nodes.oauth.mcp_oauth``),
gets NoClick's client there in the spec's order (the app NoClick registered
with the vendor when the declaration names one; else a Dynamic Client
Registration made once and kept for everyone, ``repositories.mcp_clients``;
else NoClick's Client ID Metadata Document), and answers the authorization URL
(PKCE S256, RFC 8707 resource, the scopes the resource names) with a sealed
``flow``: the verifier and everything ``finish`` needs, which only this backend
can open and which names who started it.

A server that answers with no OAuth metadata but still refuses an anonymous
client asks for a bearer key (``kind="key"``); one that needs nothing is
``kind="none"``.

``finish`` exchanges the code (or takes the key), then proves the account the
way every connect does here: the server must list its tools for that token
(``vendor_mcp.evidence``). A refusal stores nothing. The caller stores what
it returns, as its surface stores any credential.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlencode, urlsplit

logger = logging.getLogger(__name__)

#: Where the authorization server sends the person back (the app's own route).
CALLBACK_PATH = "/api/auth/mcp/callback"
#: NoClick's Client ID Metadata Document, on the same origin (the app's own route).
CLIENT_METADATA_PATH = "/mcp/client.json"
#: How long a started connect can be finished.
FLOW_TTL_S = 15 * 60
CLIENT_NAME = "NoClick"

Kind = Literal["oauth", "key", "none"]


class McpConnectError(ValueError):
    """A connect that can't go on, in words for the person connecting."""


@dataclass
class Started:
    kind: Kind
    flow: str
    authorization_url: Optional[str] = None
    state: Optional[str] = None


@dataclass
class Connected:
    credential_type: str
    credential_data: Dict[str, Any]
    name: str
    metadata: Dict[str, Any]
    evidence: Any = None
    account: Optional[str] = None


def allowed_callback(redirect_uri: str) -> bool:
    """Whether ``redirect_uri`` is this app's MCP callback: on the app's own
    origin or a subdomain of it (staging), or a loopback dev server. NoClick
    registers it with the vendor, so it must never be a page someone else serves."""
    from utils.hosted_defaults import frontend_url

    try:
        parts = urlsplit(redirect_uri)
    except ValueError:
        return False
    if parts.path != CALLBACK_PATH or parts.query or parts.fragment or parts.username or parts.password:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme == "http" and (host in ("localhost", "127.0.0.1") or host.endswith(".localhost")):
        return True
    app = urlsplit(frontend_url())
    app_host = (app.hostname or "").lower()
    if not app_host:
        return False
    if parts.scheme == app.scheme and parts.netloc.lower() == app.netloc.lower():
        return True
    return parts.scheme == "https" and host.endswith("." + app_host)


def _seal(payload: Dict[str, Any]) -> str:
    from utils.encryption import get_encryption

    return get_encryption().encrypt_credential(payload)


def _open(flow: str, principal: str) -> Dict[str, Any]:
    from utils.encryption import get_encryption

    try:
        payload = get_encryption().decrypt_credential(flow)
    except Exception:
        raise McpConnectError("This connection attempt isn't valid. Start connecting again.") from None
    if payload.get("principal") != principal:
        raise McpConnectError("This connection was started by someone else. Start connecting again.")
    if time.time() - float(payload.get("issued_at") or 0) > FLOW_TTL_S:
        raise McpConnectError("This connection attempt expired. Start connecting again.")
    return payload


def _server(credential_type: str):
    from nodes.core.vendor_mcp import server_of

    server = server_of(credential_type)
    if server is None:
        raise McpConnectError(f"{credential_type} doesn't connect through an MCP server.")
    return server


def metadata_document_url(redirect_uri: str) -> str:
    """NoClick's Client ID Metadata Document on the callback's own origin (the app
    serves it, ``routes/mcp.client[.]json.tsx``): its URL is the client id."""
    parts = urlsplit(redirect_uri)
    return f"{parts.scheme}://{parts.netloc}{CLIENT_METADATA_PATH}"


def _client_store(pool=None):
    """The kept registrations (``repositories.mcp_clients``), on ``pool`` or the app's."""
    from repositories.mcp_clients import McpClientRepo
    from utils.database_pool import get_native_pool

    return McpClientRepo(pool or get_native_pool())


async def _client_for(server, discovery, redirect_uri: str, scope: str, pool) -> Dict[str, Optional[str]]:
    """NoClick's client at this authorization server for this redirect URI, in the
    MCP spec's order: the app NoClick registered with the vendor, when the
    declaration names one; else a registration made once and kept for everyone
    (DCR); else NoClick's metadata document (CIMD), on a public origin only, since
    the server fetches it."""
    from nodes.oauth.mcp_oauth import register_dynamic_client
    from utils.encryption import get_encryption
    from utils.hosted_defaults import frontend_url

    issuer = discovery.issuer or discovery.authorization_server
    if server.client_env:
        registered = server.registered_client()
        if registered is None:
            raise McpConnectError(
                f"{server.app}'s MCP server signs in only through an app registered with {server.app}, and this "
                f"NoClick has none set up ({server.client_env}_CLIENT_ID)."
            )
        return {"client_id": registered[0], "client": "registered", "issuer": issuer}
    repo = _client_store(pool)
    known = await repo.get(issuer, redirect_uri)
    if known is None and not discovery.registration_endpoint:
        if discovery.client_id_metadata_document_supported and urlsplit(redirect_uri).scheme == "https":
            return {"client_id": metadata_document_url(redirect_uri), "client": "metadata_document", "issuer": issuer}
        raise McpConnectError(f"{server.app}'s MCP server lets only clients it approved sign in, and NoClick isn't one of them yet.")
    if known is None:
        try:
            registration = await register_dynamic_client(
                discovery.registration_endpoint, CLIENT_NAME, [redirect_uri], client_uri=frontend_url(), scope=scope or None,
            )
        except ValueError as e:
            raise McpConnectError(f"The MCP server wouldn't register NoClick as a client: {e}") from None
        client_id = registration.get("client_id")
        if not client_id:
            raise McpConnectError("The MCP server registered NoClick without a client id.")
        secret = registration.get("client_secret")
        kept = {k: v for k, v in registration.items() if k not in ("client_secret", "registration_access_token")}
        known = await repo.keep(
            issuer, redirect_uri, client_id, get_encryption().encrypt_credential({"secret": secret}) if secret else None,
            kept,
        )
        logger.info("[mcp_connect] registered a client at %s for %s", issuer, redirect_uri)
    secret = None
    if known.get("client_secret_sealed"):
        secret = get_encryption().decrypt_credential(known["client_secret_sealed"]).get("secret")
    return {"client_id": known["client_id"], "client_secret": secret, "client": "registration", "issuer": issuer}


async def start(credential_type: str, *, redirect_uri: str, principal: str, pool=None) -> Started:
    """Begin connecting ``credential_type`` for ``principal`` (``user:<id>`` or
    ``request:<id>``). Raises McpConnectError with words for the person."""
    from nodes.oauth.mcp_oauth import discover_oauth_requirements, generate_pkce_pair

    server = _server(credential_type)
    if not allowed_callback(redirect_uri):
        raise McpConnectError("This page can't receive the sign-in. Connect from NoClick itself.")
    discovery = await discover_oauth_requirements(server.url)
    base = {"v": 1, "principal": principal, "credential_type": credential_type, "server_url": server.url,
            "issued_at": time.time()}

    if not discovery.requires_oauth:
        if discovery.error:
            raise McpConnectError(f"Couldn't reach {server.app}'s MCP server: {discovery.error}")
        return Started(kind="none", flow=_seal({**base, "kind": "none"}))
    if not discovery.authorization_endpoint or not discovery.token_endpoint:
        if discovery.authorization_server:
            raise McpConnectError(f"{server.app}'s MCP server names a sign-in NoClick can't read: {discovery.error}")
        # It refuses anonymous clients but publishes no OAuth: it takes a bearer key.
        return Started(kind="key", flow=_seal({**base, "kind": "key"}))
    methods = discovery.code_challenge_methods_supported or ["S256"]
    if "S256" not in methods:
        raise McpConnectError(f"{server.app}'s MCP server doesn't support a secure (PKCE) sign-in.")

    scope = " ".join(discovery.resource_scopes or discovery.scopes_supported or [])
    client = await _client_for(server, discovery, redirect_uri, scope, pool)
    verifier, challenge = generate_pkce_pair()
    state = str(uuid.uuid4())
    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if discovery.resource_url:
        params["resource"] = discovery.resource_url
    if scope:
        params["scope"] = scope
    separator = "&" if "?" in discovery.authorization_endpoint else "?"
    authorization_url = f"{discovery.authorization_endpoint}{separator}{urlencode(params)}"
    await _preflight(authorization_url, server.app)
    flow = _seal({
        **base, "kind": "oauth", "state": state, "verifier": verifier, "redirect_uri": redirect_uri,
        "client_id": client["client_id"], "client_secret": client.get("client_secret"), "client": client["client"],
        "issuer": client["issuer"],
        "token_endpoint": discovery.token_endpoint, "resource_url": discovery.resource_url,
    })
    return Started(
        kind="oauth",
        flow=flow,
        authorization_url=authorization_url,
        state=state,
    )


async def _preflight(authorization_url: str, app: str) -> None:
    """Ask the authorization page what the popup would get. An authorization
    server shows a refused client or redirect URI as its own error page rather
    than sending the person back, so a 400 or 401 here is said in NoClick, in
    the server's words. Anything else goes on: a sign-in page, a redirect, or a
    bot wall that only a browser gets past (Canva's www.canva.com answers a
    server 403 ``cf-mitigated: challenge``), which proves nothing either way."""
    import httpx

    from nodes.core.connection_evidence import provider_message, summarize_provider_text
    from utils.ssrf import guarded_async_client

    try:
        async with guarded_async_client(timeout=15.0, follow_redirects=False) as client:
            response = await client.get(authorization_url)
    except httpx.HTTPError as e:
        logger.info("[mcp_connect] %s's authorization page could not be checked: %r", app, e)
        return
    if response.status_code not in (400, 401) or response.headers.get("cf-mitigated"):
        return
    said = summarize_provider_text(provider_message(response.text.strip()[:300]), response.status_code).rstrip(". ")
    raise McpConnectError(
        f"{app}'s MCP server refused NoClick's sign-in: {said or f'HTTP {response.status_code}'}. "
        f"It may let only apps it approved sign in from the web."
    )


async def finish(
    flow: str,
    *,
    principal: str,
    code: Optional[str] = None,
    state: Optional[str] = None,
    api_key: Optional[str] = None,
    pool=None,
) -> Connected:
    """Complete a started connect and prove it. Raises McpConnectError, storing nothing,
    when the exchange fails or the server refuses the account."""
    from nodes.core import vendor_mcp
    from nodes.oauth.mcp_oauth import exchange_code_for_tokens

    started = _open(flow, principal)
    credential_type = started["credential_type"]
    server = _server(credential_type)
    data: Dict[str, Any] = {"mcp_server_url": server.url}
    account = None
    if started["kind"] == "oauth":
        if not code:
            raise McpConnectError(f"{server.app} didn't send a sign-in code back.")
        if state != started["state"]:
            raise McpConnectError("This sign-in doesn't belong to this connection. Start connecting again.")
        # A registration's own secret rode the sealed flow; NoClick's registered app's is read where it's configured.
        secret = vendor_mcp.client_secret_for(
            server, {"client_id": started["client_id"], "client_secret": started.get("client_secret")})
        try:
            tokens = await exchange_code_for_tokens(
                code=code, code_verifier=started["verifier"], token_endpoint=started["token_endpoint"],
                client_id=started["client_id"], redirect_uri=started["redirect_uri"],
                resource_url=started.get("resource_url"), client_secret=secret,
            )
        except ValueError as e:
            if "invalid_client" in str(e) and started.get("client") == "registration":
                await _client_store(pool).forget(started["issuer"], started["redirect_uri"], started["client_id"])
            raise McpConnectError(f"{server.app} didn't accept the sign-in: {e}") from None
        account = vendor_mcp.account_from_tokens(tokens.raw)
        data.update({
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
            "token_type": tokens.token_type,
            "scope": tokens.scope,
            "token_endpoint": started["token_endpoint"],
            "client_id": started["client_id"],
            "client_secret": started.get("client_secret"),
            "resource_url": started.get("resource_url"),
            "account": account,
        })
    elif started["kind"] == "key":
        if not (api_key or "").strip():
            raise McpConnectError(f"Paste the key {server.app} gave you.")
        data["api_key"] = api_key.strip()
    data = {k: v for k, v in data.items() if v is not None}

    evidence = await vendor_mcp.evidence(credential_type, {**data, "credential_type": credential_type})
    if evidence.reachable is False:
        raise McpConnectError(evidence.error or f"{server.app}'s MCP server refused this account.")
    metadata: Dict[str, Any] = {"provider": "mcp", "mcp_server_url": server.url, "created_via": "mcp_connect"}
    if evidence.reachable:
        from datetime import datetime, timezone

        metadata["verified_at"] = datetime.now(timezone.utc).isoformat()
        if account:
            metadata["verified_as"] = account
        elif evidence.samples:
            metadata["verified_with"] = evidence.samples[0].label
    name = f"{server.app} (MCP{', ' + account if account else ''})"
    return Connected(credential_type=credential_type, credential_data=data, name=name, metadata=metadata,
                     evidence=evidence, account=account)
