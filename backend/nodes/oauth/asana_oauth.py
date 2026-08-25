"""
Asana OAuth 2.0 utility for handling token exchange and refresh.
Manages the authorization_code flow for Asana API access.

Asana OAuth uses:
- Authorization URL: https://app.asana.com/-/oauth_authorize
- Token URL:         https://app.asana.com/-/oauth_token
- Refresh:           POST token URL with grant_type=refresh_token
- User info:         GET https://app.asana.com/api/1.0/users/me

Asana access tokens expire after 1 hour; refresh tokens are long-lived (they are
NOT single-use rotated), so a refresh response may legitimately omit a new
refresh_token — in which case we keep the existing one.

client_id / client_secret default to the ASANA_CLIENT_ID / ASANA_CLIENT_SECRET
env vars but accept user-supplied values so a "bring your own app" custom OAuth
client (x-oauth-supports-custom-client) can be used.

Documentation: https://developers.asana.com/docs/oauth
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

ASANA_AUTH_URL = "https://app.asana.com/-/oauth_authorize"
ASANA_TOKEN_URL = "https://app.asana.com/-/oauth_token"
ASANA_REVOKE_URL = "https://app.asana.com/-/oauth_revoke"
ASANA_USERINFO_URL = "https://app.asana.com/api/1.0/users/me"


class AsanaTokens(BaseModel):
    """Structured token response from Asana OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "Bearer"


class AsanaUserInfo(BaseModel):
    """User info from Asana (GET /users/me)."""

    id: str
    name: str
    email: Optional[str] = None


def get_asana_client_config() -> Tuple[str, str]:
    """Get Asana OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("ASANA_CLIENT_ID")
    client_secret = os.environ.get("ASANA_CLIENT_SECRET")

    if not client_id:
        raise ValueError("ASANA_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("ASANA_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_asana_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[AsanaTokens, AsanaUserInfo]:
    """Exchange authorization code for access token, then fetch user info.

    Args:
        code: Authorization code from Asana OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (AsanaTokens, AsanaUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
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
        token_response = await client.post(ASANA_TOKEN_URL, data=data, headers=headers)

        if token_response.status_code != 200:
            logger.error(f"[AsanaOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[AsanaOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Asana access tokens expire in 1 hour (expires_in seconds).
        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = AsanaTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[AsanaOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> AsanaUserInfo:
    """Fetch user info from Asana's GET /users/me."""
    response = await client.get(
        ASANA_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[AsanaOAuth] Failed to get user info: HTTP {response.status_code}")
        return AsanaUserInfo(id="unknown", name="Unknown")

    payload = response.json()
    me = payload.get("data", payload) if isinstance(payload, dict) else {}
    return AsanaUserInfo(
        id=str(me.get("gid", "unknown")),
        name=me.get("name", "Unknown"),
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> AsanaTokens:
    """Refresh an expired access token using the refresh token.

    Asana refresh tokens are long-lived and NOT single-use rotated, so the
    response may omit a new refresh_token — in that case we keep the existing
    one (the freshen choke point only overwrites refresh_token when present).

    Args:
        refresh_token: The refresh token stored in credentials
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New AsanaTokens with updated access_token

    Raises:
        ValueError: If refresh fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "client_id": cid,
        "client_secret": csecret,
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ASANA_TOKEN_URL, data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"[AsanaOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[AsanaOAuth] Token refresh failed: {error_msg}")
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

        tokens = AsanaTokens(
            access_token=token_data["access_token"],
            # Long-lived non-rotating refresh token: keep the existing one if the
            # provider doesn't return a fresh one.
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[AsanaOAuth] Successfully refreshed access token")
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
    except (ValueError, TypeError):
        # Unparseable expiry — treat as expired (fail-safe: force a refresh).
        return True


def get_asana_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Asana OAuth authorization URL.

    Asana expects space-delimited scopes. Apps registered with granular scopes
    must pass the scope param at the authorize endpoint.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in the URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_asana_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{ASANA_AUTH_URL}?{urlencode(params)}"


# Default scopes for Asana operations (granular, non-inheriting). Mirrors the
# x-oauth-scopes in AsanaOAuthCredential so the authorize route and backend agree.
ASANA_DEFAULT_SCOPES = [
    "tasks:read",
    "tasks:write",
    "tasks:delete",
    "projects:read",
    "projects:write",
    "projects:delete",
    "stories:read",
    "stories:write",
    "users:read",
    "workspaces:read",
    "teams:read",
    "tags:read",
    "tags:write",
    "custom_fields:read",
    "webhooks:read",
    "webhooks:write",
    "webhooks:delete",
]
