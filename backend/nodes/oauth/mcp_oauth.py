"""
MCP OAuth 2.1 Discovery and Token Management.

Implements RFC 9728 (Protected Resource Metadata) discovery to detect OAuth
requirements from external MCP servers and manage OAuth tokens for connecting
to them.
"""

import logging
import hashlib
import base64
import secrets
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import httpx
from opentelemetry import trace
from pydantic import BaseModel
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

# Constants
DISCOVERY_TIMEOUT = 10.0  # seconds
TOKEN_REFRESH_BUFFER_MINUTES = 5


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
    2. If 401, parse WWW-Authenticate header for metadata URL
    3. Fetch Protected Resource Metadata
    4. Fetch Authorization Server Metadata

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
            # Step 1: Make unauthenticated request
            response = await client.get(server_url)

            # If not 401, no OAuth required
            if response.status_code != 401:
                logger.info(
                    f"[MCP OAuth] No OAuth required (status={response.status_code})"
                )
                return OAuthDiscoveryResult(requires_oauth=False)

            # Step 2: Parse WWW-Authenticate header
            www_auth = response.headers.get("WWW-Authenticate", "")
            resource_metadata_url = _parse_resource_metadata_url(www_auth, server_url)

            if not resource_metadata_url:
                logger.info(
                    f"[MCP OAuth] No resource_metadata in WWW-Authenticate, trying well-known"
                )
                # Try well-known fallback
                resource_metadata_url = await _try_wellknown_discovery(
                    client, server_url
                )

            if not resource_metadata_url:
                logger.warning(
                    f"[MCP OAuth] Could not discover OAuth metadata for {server_url}"
                )
                return OAuthDiscoveryResult(
                    requires_oauth=True,
                    error="Server requires authentication but no OAuth metadata found",
                )

            # Step 3: Fetch Protected Resource Metadata
            logger.info(
                f"[MCP OAuth] Fetching resource metadata from {resource_metadata_url}"
            )
            resource_response = await client.get(resource_metadata_url)

            if resource_response.status_code != 200:
                return OAuthDiscoveryResult(
                    requires_oauth=True,
                    error=f"Failed to fetch resource metadata: {resource_response.status_code}",
                )

            resource_metadata = resource_response.json()
            authorization_servers = resource_metadata.get("authorization_servers", [])

            if not authorization_servers:
                return OAuthDiscoveryResult(
                    requires_oauth=True,
                    error="No authorization_servers in resource metadata",
                )

            # Use first authorization server
            auth_server = authorization_servers[0]

            # Step 4: Fetch Authorization Server Metadata
            auth_metadata = await _fetch_auth_server_metadata(client, auth_server)

            if not auth_metadata:
                return OAuthDiscoveryResult(
                    requires_oauth=True,
                    authorization_server=auth_server,
                    error="Failed to fetch authorization server metadata",
                )

            # Extract provider name from auth server URL
            provider_name = _extract_provider_name(auth_server)

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

    # Look for resource_metadata="..."
    import re

    match = re.search(r'resource_metadata="([^"]+)"', www_authenticate)
    if match:
        return match.group(1)

    return None


async def _try_wellknown_discovery(
    client: httpx.AsyncClient, server_url: str
) -> Optional[str]:
    """
    Try well-known URI discovery as fallback per RFC 9728.

    Tries:
    1. /.well-known/oauth-protected-resource/{path}
    2. /.well-known/oauth-protected-resource
    """
    from urllib.parse import urlparse, urljoin

    parsed = urlparse(server_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.strip("/")

    # Try path-specific first
    if path:
        wellknown_url = f"{base_url}/.well-known/oauth-protected-resource/{path}"
        try:
            response = await client.get(wellknown_url)
            if response.status_code == 200:
                return wellknown_url
        except Exception:
            pass

    # Try root
    wellknown_url = f"{base_url}/.well-known/oauth-protected-resource"
    try:
        response = await client.get(wellknown_url)
        if response.status_code == 200:
            return wellknown_url
    except Exception:
        pass

    return None


async def _fetch_auth_server_metadata(
    client: httpx.AsyncClient, auth_server: str
) -> Optional[Dict[str, Any]]:
    """
    Fetch Authorization Server Metadata per RFC 8414.

    Tries:
    1. /.well-known/oauth-authorization-server
    2. /.well-known/openid-configuration
    """
    from urllib.parse import urlparse

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
    from urllib.parse import urlparse

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


async def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    token_endpoint: str,
    client_id: str,
    redirect_uri: str,
    resource_url: Optional[str] = None,
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

    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(
            token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

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
        )


async def refresh_access_token(
    refresh_token: str,
    token_endpoint: str,
    client_id: str,
    resource_url: Optional[str] = None,
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

    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(
            token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

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
) -> Dict[str, Any]:
    """
    Register a dynamic OAuth client.

    Args:
        registration_endpoint: Dynamic registration endpoint URL
        client_name: Name for the client
        redirect_uris: List of redirect URIs
        client_uri: Optional client website URL

    Returns:
        Registration response with client_id
    """
    logger.info(f"[MCP OAuth] Registering dynamic client at {registration_endpoint}")

    data = {
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }

    if client_uri:
        data["client_uri"] = client_uri

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
