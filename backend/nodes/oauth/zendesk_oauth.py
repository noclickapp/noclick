"""
Zendesk OAuth 2.0 utility for handling token exchange and refresh.
Manages the authorization_code flow for the Zendesk Support REST API.

Zendesk OAuth is subdomain-scoped — both the authorize and token endpoints live
under the customer's own Zendesk account host, so the subdomain must be threaded
through every call:
- Authorization URL: https://{subdomain}.zendesk.com/oauth/authorizations/new
- Token URL:         https://{subdomain}.zendesk.com/oauth/tokens
- Refresh:           POST token URL with grant_type=refresh_token
- User info:         GET https://{subdomain}.zendesk.com/api/v2/users/me

Zendesk access tokens expire (expires_in seconds) and ship a refresh token. The
refresh token is long-lived and NOT single-use rotated, so a refresh response
may legitimately omit a new refresh_token — in which case we keep the existing
one.

client_id / client_secret default to the ZENDESK_CLIENT_ID / ZENDESK_CLIENT_SECRET
env vars but accept user-supplied values so a "bring your own app" custom OAuth
client (x-oauth-supports-custom-client) can be used.

Documentation: https://developer.zendesk.com/documentation/api-basics/authentication/using-oauth-to-authenticate-zendesk-api-requests-in-a-web-app/
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel
from utils.ssrf import normalize_provider_subdomain

logger = logging.getLogger(__name__)


def _auth_url(subdomain: str) -> str:
    tenant = normalize_provider_subdomain(
        subdomain, "zendesk.com", field_name="Zendesk subdomain"
    )
    return f"https://{tenant}.zendesk.com/oauth/authorizations/new"


def _token_url(subdomain: str) -> str:
    tenant = normalize_provider_subdomain(
        subdomain, "zendesk.com", field_name="Zendesk subdomain"
    )
    return f"https://{tenant}.zendesk.com/oauth/tokens"


def _userinfo_url(subdomain: str) -> str:
    tenant = normalize_provider_subdomain(
        subdomain, "zendesk.com", field_name="Zendesk subdomain"
    )
    return f"https://{tenant}.zendesk.com/api/v2/users/me.json"


class ZendeskTokens(BaseModel):
    """Structured token response from Zendesk OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "Bearer"


class ZendeskUserInfo(BaseModel):
    """User info from Zendesk (GET /api/v2/users/me)."""

    id: str
    name: str
    email: Optional[str] = None


def get_zendesk_client_config() -> Tuple[str, str]:
    """Get Zendesk OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("ZENDESK_CLIENT_ID")
    client_secret = os.environ.get("ZENDESK_CLIENT_SECRET")

    if not client_id:
        raise ValueError("ZENDESK_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("ZENDESK_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_zendesk_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    subdomain: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[ZendeskTokens, ZendeskUserInfo]:
    """Exchange authorization code for access token, then fetch user info.

    Args:
        code: Authorization code from Zendesk OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        subdomain: The customer's Zendesk subdomain (scopes the host)
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (ZendeskTokens, ZendeskUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    if not subdomain:
        raise ValueError("A Zendesk subdomain is required to exchange the code")
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "client_id": cid,
        "client_secret": csecret,
        "redirect_uri": redirect_uri,
        "code": code,
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(_token_url(subdomain), data=data, headers=headers)

        if token_response.status_code != 200:
            logger.error(f"[ZendeskOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[ZendeskOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Zendesk access tokens carry an expires_in (seconds) when issued with an
        # expiry; long-lived tokens omit it.
        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = ZendeskTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, subdomain, tokens.access_token)

        logger.info(
            f"[ZendeskOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(
    client: httpx.AsyncClient, subdomain: str, access_token: str
) -> ZendeskUserInfo:
    """Fetch user info from Zendesk's GET /api/v2/users/me."""
    response = await client.get(
        _userinfo_url(subdomain),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[ZendeskOAuth] Failed to get user info: HTTP {response.status_code}")
        return ZendeskUserInfo(id="unknown", name="Unknown")

    payload = response.json()
    me = payload.get("user", payload) if isinstance(payload, dict) else {}
    return ZendeskUserInfo(
        id=str(me.get("id", "unknown")),
        name=me.get("name", "Unknown"),
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    subdomain: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> ZendeskTokens:
    """Refresh an expired access token using the refresh token.

    Zendesk's token endpoint is subdomain-scoped, so the subdomain is required.
    Refresh tokens are long-lived and NOT single-use rotated, so the response
    may omit a new refresh_token — in that case we keep the existing one (the
    freshen choke point only overwrites refresh_token when present).

    Args:
        refresh_token: The refresh token stored in credentials
        subdomain: The customer's Zendesk subdomain (scopes the host)
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New ZendeskTokens with updated access_token

    Raises:
        ValueError: If refresh fails
    """
    if not subdomain:
        raise ValueError("A Zendesk subdomain is required to refresh the token")
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "client_id": cid,
        "client_secret": csecret,
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(_token_url(subdomain), data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"[ZendeskOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[ZendeskOAuth] Token refresh failed: {error_msg}")
            error_code = token_data.get("error") if isinstance(token_data, dict) else None
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = ZendeskTokens(
            access_token=token_data["access_token"],
            # Long-lived non-rotating refresh token: keep the existing one if the
            # provider doesn't return a fresh one.
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[ZendeskOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Check if a token is expired or will expire within *buffer_minutes*.

    Args:
        expires_at: ISO 8601 timestamp of token expiry (None if non-expiring)
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if no expiry or still valid
    """
    if not expires_at:
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return now + timedelta(minutes=buffer_minutes) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[ZendeskOAuth] Error parsing expiry time: {e}")
        return False


def get_zendesk_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    subdomain: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Zendesk OAuth authorization URL.

    Zendesk expects space-delimited scopes and a subdomain-scoped authorize host.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in the URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        subdomain: The customer's Zendesk subdomain (scopes the host)
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_zendesk_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{_auth_url(subdomain)}?{urlencode(params)}"


# Default scopes for Zendesk operations. Mirrors the x-oauth-scopes in
# ZendeskOAuthCredential so the authorize route and backend agree. `read`/`write`
# are the broad global scopes the Support REST API honors across endpoints.
ZENDESK_DEFAULT_SCOPES = [
    "read",
    "write",
]
