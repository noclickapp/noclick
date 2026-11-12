"""
MCP OAuth 2.1 Discovery and Token Management.

Implements RFC 9728 (Protected Resource Metadata) discovery to detect OAuth
requirements from external MCP servers and manage OAuth tokens for connecting
to them.
"""

import logging
import hashlib
import base64
import re
import secrets
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlparse

import httpx
from opentelemetry import trace
from pydantic import BaseModel, Field
from utils.ssrf import SSRFError, guarded_async_client

logger = logging.getLogger(__name__)

# Constants
DISCOVERY_TIMEOUT = 10.0  # seconds
TOKEN_REFRESH_BUFFER_MINUTES = 5
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "NoClick", "version": "1"}},
}


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class OAuthDiscoveryResult:
    """Result of MCP OAuth discovery."""

    requires_oauth: bool
    provider_name: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    registration_endpoint: Optional[str] = None
    scopes_supported: Optional[List[str]] = None
    resource_url: Optional[str] = None
    authorization_server: Optional[str] = None
    # For custom OAuth apps
    supports_dynamic_registration: bool = False
    code_challenge_methods_supported: Optional[List[str]] = None
    error: Optional[str] = None
    # The scopes the resource itself names (its WWW-Authenticate ``scope``, else
    # its protected resource metadata): what a client asks for, per the MCP spec.
    resource_scopes: Optional[List[str]] = None
    issuer: Optional[str] = None
    # The server takes a Client ID Metadata Document's URL as a client_id.
    client_id_metadata_document_supported: bool = False
    # How its token endpoint takes a client's credentials (RFC 8414), as listed.
    token_endpoint_auth_methods_supported: Optional[List[str]] = None
    # The protected resource metadata its 401 named, read or not.
    resource_metadata_url: Optional[str] = None


class MCPOAuthTokens(BaseModel):
    """OAuth tokens for MCP server connection."""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_at: Optional[datetime] = None
    scope: Optional[str] = None
    # Server info for refresh
    token_endpoint: Optional[str] = None
    client_id: Optional[str] = None
    # The token endpoint's whole answer (an id_token, an account name).
    raw: Optional[Dict[str, Any]] = Field(default=None, exclude=True)


# ============================================================================
# PKCE Utilities
# ============================================================================


def generate_pkce_pair() -> tuple[str, str]:
    """
    Generate PKCE code_verifier and code_challenge pair.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    # Generate random verifier (43-128 chars)
    code_verifier = secrets.token_urlsafe(64)

    # Compute S256 challenge
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return code_verifier, code_challenge


# ============================================================================
# OAuth Discovery
# ============================================================================


async def discover_oauth_requirements(server_url: str) -> OAuthDiscoveryResult:
    """
    Discover OAuth requirements for an MCP server.

    Implements RFC 9728 discovery:
    1. Make unauthenticated request to MCP server
    2. Read the Protected Resource Metadata its 401 names (WWW-Authenticate
       ``resource_metadata``), else at the well-known URLs
    3. Fetch Authorization Server Metadata (RFC 8414)

    A server that answers an anonymous client still requires OAuth when its
    resource metadata names an authorization server: what it serves without a
    token is nobody's account.

    Args:
        server_url: URL of the MCP server endpoint

    Returns:
        OAuthDiscoveryResult with OAuth configuration or requires_oauth=False
    """
    logger.info(f"[MCP OAuth] Discovering OAuth requirements for {server_url}")

    async with guarded_async_client(
        timeout=DISCOVERY_TIMEOUT, follow_redirects=True
    ) as client:
        try:
            # Step 1: Make unauthenticated request. A Streamable HTTP server may
            # answer a GET 405 before it checks auth, so a GET that isn't 401 is
            # asked again as the client's first POST (initialize).
            response = await client.get(server_url)
            if response.status_code != 401:
                response = await client.post(
                    server_url,
                    json=_INITIALIZE,
                    headers={"Accept": "application/json, text/event-stream"},
                )
            challenged = response.status_code == 401

            # Step 2: Protected Resource Metadata
            www_auth = response.headers.get("WWW-Authenticate", "") if challenged else ""
            named = _parse_resource_metadata_url(www_auth, server_url)
            challenge_scope = _parse_challenge_param(www_auth, "scope")
            resource_metadata, unread = await _fetch_resource_metadata(client, named, server_url)

            if resource_metadata is None and not challenged:
                logger.info(
                    f"[MCP OAuth] No OAuth required (status={response.status_code})"
                )
                return OAuthDiscoveryResult(requires_oauth=False)
            if resource_metadata is None and named:
                return OAuthDiscoveryResult(
                    requires_oauth=True, resource_metadata_url=named, error=unread
                )
            if resource_metadata is None:
                # The 2025-03-26 revision of the spec has no resource metadata: the
                # MCP server's own origin is its authorization server.
                parsed = urlparse(server_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                if await _fetch_auth_server_metadata(client, origin) is None:
                    logger.warning(
                        f"[MCP OAuth] Could not discover OAuth metadata for {server_url}"
                    )
                    return OAuthDiscoveryResult(
                        requires_oauth=True,
                        error="Server requires authentication but no OAuth metadata found",
                    )
                resource_metadata = {"authorization_servers": [origin]}

            # Use first authorization server
            auth_server = resource_metadata["authorization_servers"][0]

            # Step 3: Fetch Authorization Server Metadata
            auth_metadata = await _fetch_auth_server_metadata(client, auth_server)

            if not auth_metadata:
                return OAuthDiscoveryResult(
                    requires_oauth=True,
                    authorization_server=auth_server,
                    resource_metadata_url=named,
                    error="Failed to fetch authorization server metadata",
                )

            # Extract provider name from auth server URL
            provider_name = _extract_provider_name(auth_server)
            resource_scopes = challenge_scope.split() if challenge_scope else resource_metadata.get("scopes_supported")
            auth_methods = auth_metadata.get("token_endpoint_auth_methods_supported")

            return OAuthDiscoveryResult(
                requires_oauth=True,
                provider_name=provider_name,
                authorization_endpoint=auth_metadata.get("authorization_endpoint"),
                token_endpoint=auth_metadata.get("token_endpoint"),
                registration_endpoint=auth_metadata.get("registration_endpoint"),
                scopes_supported=auth_metadata.get("scopes_supported"),
                resource_url=resource_metadata.get("resource", server_url),
                authorization_server=auth_server,
                supports_dynamic_registration=auth_metadata.get("registration_endpoint")
                is not None,
                code_challenge_methods_supported=auth_metadata.get(
                    "code_challenge_methods_supported", ["S256"]
                ),
                resource_scopes=resource_scopes if isinstance(resource_scopes, list) else None,
                issuer=auth_metadata.get("issuer") or auth_server,
                client_id_metadata_document_supported=auth_metadata.get(
                    "client_id_metadata_document_supported"
                ) is True,
                token_endpoint_auth_methods_supported=auth_methods if isinstance(auth_methods, list) else None,
                resource_metadata_url=named,
            )

        except httpx.TimeoutException:
            logger.error(f"[MCP OAuth] Timeout discovering OAuth for {server_url}")
            return OAuthDiscoveryResult(
                requires_oauth=False, error="Timeout connecting to MCP server"
            )
        except Exception as e:
            logger.error(
                f"[MCP OAuth] Error discovering OAuth for {server_url}: {e}",
                exc_info=True,
            )
            return OAuthDiscoveryResult(requires_oauth=False, error=str(e))


def _parse_resource_metadata_url(
    www_authenticate: str, server_url: str
) -> Optional[str]:
    """
    Parse resource_metadata URL from WWW-Authenticate header.

    Example header:
    Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"
    """
    if not www_authenticate:
        return None

    return _parse_challenge_param(www_authenticate, "resource_metadata")


def _parse_challenge_param(www_authenticate: str, name: str) -> Optional[str]:
    """One parameter of a WWW-Authenticate challenge, quoted (``scope="a b"``) or a
    bare token (``resource_metadata=https://…``); names match in any case (RFC 9110)."""
    match = re.search(
        rf'(?:^|[\s,]){name}=(?:"([^"]*)"|([^\s,"]+))', www_authenticate or "", re.IGNORECASE
    )
    return (match.group(1) if match.group(1) is not None else match.group(2)) if match else None


async def _fetch_resource_metadata(
    client: httpx.AsyncClient, named: Optional[str], server_url: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    The Protected Resource Metadata (RFC 9728) that names an authorization
    server, and why none was read when it wasn't.

    Tries the URL the server's challenge named, then the well-known URIs:
    1. /.well-known/oauth-protected-resource/{path}
    2. /.well-known/oauth-protected-resource
    Some servers name a URL they don't serve, and some answer the path-specific
    one with a document of their own, so each must hold ``authorization_servers``.
    """
    parsed = urlparse(server_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.strip("/")
    urls = [named] if named else []
    if path:
        urls.append(f"{base_url}/.well-known/oauth-protected-resource/{path}")
    urls.append(f"{base_url}/.well-known/oauth-protected-resource")

    unread = None
    for url in dict.fromkeys(urls):
        try:
            response = await client.get(url)
        except (httpx.HTTPError, SSRFError) as e:
            logger.debug(f"[MCP OAuth] Failed to fetch {url}: {e}")
            unread = unread or f"Failed to fetch resource metadata: {e!r}"
            continue
        if response.status_code != 200:
            unread = unread or f"Failed to fetch resource metadata: {response.status_code}"
            continue
        try:
            metadata = response.json()
        except ValueError:
            metadata = None
        servers = metadata.get("authorization_servers") if isinstance(metadata, dict) else None
        if isinstance(servers, list) and servers and isinstance(servers[0], str):
            return metadata, None
        unread = unread or "No authorization_servers in resource metadata"
    return None, unread


async def _fetch_auth_server_metadata(
    client: httpx.AsyncClient, auth_server: str
) -> Optional[Dict[str, Any]]:
    """
    Fetch Authorization Server Metadata per RFC 8414.

    Tries:
    1. /.well-known/oauth-authorization-server
    2. /.well-known/openid-configuration
    """
    parsed = urlparse(auth_server)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.strip("/")

    urls_to_try = []

    if path:
        urls_to_try.extend(
            [
                f"{base_url}/.well-known/oauth-authorization-server/{path}",
                f"{base_url}/.well-known/openid-configuration/{path}",
                f"{auth_server}/.well-known/openid-configuration",
            ]
        )
    else:
        urls_to_try.extend(
            [
                f"{base_url}/.well-known/oauth-authorization-server",
                f"{base_url}/.well-known/openid-configuration",
            ]
        )

    for url in urls_to_try:
        try:
            logger.debug(f"[MCP OAuth] Trying auth metadata URL: {url}")
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"[MCP OAuth] Failed to fetch {url}: {e}")
            continue

    return None


def _extract_provider_name(auth_server: str) -> str:
    """Extract a friendly provider name from the auth server URL."""
    parsed = urlparse(auth_server)
    host = parsed.netloc.lower()

    # Known providers
    provider_map = {
        "notion.com": "Notion",
        "api.notion.com": "Notion",
        "brave.com": "Brave",
        "api.brave.com": "Brave",
        "github.com": "GitHub",
        "api.github.com": "GitHub",
        "google.com": "Google",
        "accounts.google.com": "Google",
        "googleapis.com": "Google",
        "slack.com": "Slack",
        "api.slack.com": "Slack",
        "dropbox.com": "Dropbox",
        "api.dropboxapi.com": "Dropbox",
        "linear.app": "Linear",
        "api.linear.app": "Linear",
        "atlassian.com": "Atlassian",
        "auth.atlassian.com": "Atlassian",
    }

    for domain, name in provider_map.items():
        if domain in host:
            return name

    # Fallback: use domain name
    parts = host.split(".")
    if len(parts) >= 2:
        return parts[-2].capitalize()
    return host


# ============================================================================
# Token Management
# ============================================================================


def _authenticate_client(
    data: Dict[str, str], client_secret: Optional[str], auth_method: Optional[str]
) -> Dict[str, str]:
    """The token request's headers, with a confidential client's secret where it
    registered to send it: HTTP Basic for ``client_secret_basic`` (RFC 6749
    §2.3.1, which then leaves ``client_id`` out of ``data``), else in ``data``."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if not client_secret:
        return headers
    if auth_method == "client_secret_basic":
        pair = f"{quote(data.pop('client_id'), safe='')}:{quote(client_secret, safe='')}"
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
    else:
        data["client_secret"] = client_secret
    return headers


async def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    token_endpoint: str,
    client_id: str,
    redirect_uri: str,
    resource_url: Optional[str] = None,
    client_secret: Optional[str] = None,
    auth_method: Optional[str] = None,
) -> MCPOAuthTokens:
    """
    Exchange authorization code for OAuth tokens.

    Args:
        code: Authorization code from OAuth callback
        code_verifier: PKCE code verifier
        token_endpoint: Token endpoint URL
        client_id: OAuth client ID
        redirect_uri: Redirect URI used in authorization
        resource_url: Resource URL for RFC 8707 resource indicator

    Returns:
        MCPOAuthTokens with access token and optional refresh token
    """
    logger.info(f"[MCP OAuth] Exchanging code at {token_endpoint}")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }

    # Add resource indicator if provided (RFC 8707)
    if resource_url:
        data["resource"] = resource_url
    headers = _authenticate_client(data, client_secret, auth_method)

    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(token_endpoint, data=data, headers=headers)

        if response.status_code != 200:
            error_data = (
                response.json()
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )
            error_msg = error_data.get(
                "error_description", error_data.get("error") or f"HTTP {response.status_code}"
            )
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = response.json()

        # Calculate expiration time
        expires_at = None
        if "expires_in" in token_data:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=token_data["expires_in"]
            )

        return MCPOAuthTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_type=token_data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scope=token_data.get("scope"),
            token_endpoint=token_endpoint,
            client_id=client_id,
            raw=token_data,
        )


async def refresh_access_token(
    refresh_token: str,
    token_endpoint: str,
    client_id: str,
    resource_url: Optional[str] = None,
    client_secret: Optional[str] = None,
    auth_method: Optional[str] = None,
) -> MCPOAuthTokens:
    """
    Refresh an expired access token.

    Args:
        refresh_token: Refresh token
        token_endpoint: Token endpoint URL
        client_id: OAuth client ID
        resource_url: Resource URL for RFC 8707 resource indicator

    Returns:
        MCPOAuthTokens with new access token
    """
    logger.info(f"[MCP OAuth] Refreshing token at {token_endpoint}")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }

    if resource_url:
        data["resource"] = resource_url
    headers = _authenticate_client(data, client_secret, auth_method)

    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(token_endpoint, data=data, headers=headers)

        if response.status_code != 200:
            error_data = (
                response.json()
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )
            error_msg = error_data.get(
                "error_description", error_data.get("error") or f"HTTP {response.status_code}"
            )
            error_code = None
            if isinstance(error_data, dict):
                error_code = error_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        expires_at = None
        if "expires_in" in token_data:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=token_data["expires_in"]
            )

        return MCPOAuthTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get(
                "refresh_token", refresh_token
            ),  # Keep old if not returned
            token_type=token_data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scope=token_data.get("scope"),
            token_endpoint=token_endpoint,
            client_id=client_id,
        )


def is_token_expired(
    expires_at: Optional[datetime], buffer_minutes: int = TOKEN_REFRESH_BUFFER_MINUTES
) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: Token expiration time (None = never expires)
        buffer_minutes: Minutes before expiration to consider expired

    Returns:
        True if token is expired or will expire within buffer
    """
    if expires_at is None:
        return False

    # Ensure timezone-aware comparison
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    threshold = datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes)
    return expires_at <= threshold


# ============================================================================
# Dynamic Client Registration (RFC 7591)
# ============================================================================


async def register_dynamic_client(
    registration_endpoint: str,
    client_name: str,
    redirect_uris: List[str],
    client_uri: Optional[str] = None,
    scope: Optional[str] = None,
    token_endpoint_auth_method: str = "none",
) -> Dict[str, Any]:
    """
    Register a dynamic OAuth client.

    Args:
        registration_endpoint: Dynamic registration endpoint URL
        client_name: Name for the client
        redirect_uris: List of redirect URIs
        client_uri: Optional client website URL
        token_endpoint_auth_method: ``none`` for a public client, else how a
            confidential one sends the secret the server issues it

    Returns:
        Registration response with client_id
    """
    logger.info(f"[MCP OAuth] Registering dynamic client at {registration_endpoint}")

    data = {
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": token_endpoint_auth_method,
    }

    if client_uri:
        data["client_uri"] = client_uri
    if scope:
        data["scope"] = scope

    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(
            registration_endpoint,
            json=data,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code not in (200, 201):
            error_data = (
                response.json()
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )
            error_msg = error_data.get(
                "error_description", error_data.get("error") or f"HTTP {response.status_code}"
            )
            raise ValueError(f"Client registration failed: {error_msg}")

        return response.json()
