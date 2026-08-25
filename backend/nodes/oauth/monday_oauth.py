"""
monday.com OAuth 2.0 utility for handling token exchange and refresh.
Manages the authorization_code flow for the monday.com Platform API.

monday OAuth uses:
- Authorization URL: https://auth.monday.com/oauth2/authorize
- Token URL:         https://auth.monday.com/oauth2/token
- Refresh:           POST token URL with grant_type=refresh_token
- User info:         POST https://api.monday.com/v2 with a GraphQL `me` query

monday OAuth access tokens do NOT expire — they remain valid until the user
uninstalls the app — so a token response may legitimately omit both expires_in
and refresh_token. We persist whatever monday returns and never require a
rotated refresh token (if a refresh response omits one we keep the existing).

GOTCHA: monday passes the access token as the *bare* ``Authorization: <token>``
header value — NO ``Bearer`` prefix (unlike most OAuth APIs).

client_id / client_secret default to the MONDAY_CLIENT_ID / MONDAY_CLIENT_SECRET
env vars but accept user-supplied values so a "bring your own app" custom OAuth
client (x-oauth-supports-custom-client) can be used.

Documentation: https://developer.monday.com/apps/docs/oauth
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

MONDAY_AUTH_URL = "https://auth.monday.com/oauth2/authorize"
MONDAY_TOKEN_URL = "https://auth.monday.com/oauth2/token"
MONDAY_API_URL = "https://api.monday.com/v2"


class MondayTokens(BaseModel):
    """Structured token response from monday.com OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp (None — monday tokens don't expire)
    token_type: str = "Bearer"


class MondayUserInfo(BaseModel):
    """User info from monday.com (GraphQL `me` query)."""

    id: str
    name: str
    email: Optional[str] = None


def get_monday_client_config() -> Tuple[str, str]:
    """Get monday.com OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("MONDAY_CLIENT_ID")
    client_secret = os.environ.get("MONDAY_CLIENT_SECRET")

    if not client_id:
        raise ValueError("MONDAY_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("MONDAY_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_monday_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[MondayTokens, MondayUserInfo]:
    """Exchange authorization code for an access token, then fetch user info.

    Args:
        code: Authorization code from monday OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (MondayTokens, MondayUserInfo)

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
        token_response = await client.post(MONDAY_TOKEN_URL, data=data, headers=headers)

        if token_response.status_code != 200:
            logger.error(f"[MondayOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[MondayOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # monday OAuth tokens generally do not expire, but if monday ever returns
        # an expires_in we honor it.
        expires_at = None
        if token_data.get("expires_in"):
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = MondayTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[MondayOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> MondayUserInfo:
    """Fetch user info from monday's GraphQL `me` query.

    monday's token is sent as the *bare* Authorization value (no Bearer prefix).
    """
    response = await client.post(
        MONDAY_API_URL,
        headers={
            "Authorization": access_token,  # bare token — monday does NOT use Bearer
            "Content-Type": "application/json",
            "API-Version": "2025-04",
        },
        json={"query": "query { me { id name email } }"},
    )

    if response.status_code != 200:
        logger.warning(f"[MondayOAuth] Failed to get user info: HTTP {response.status_code}")
        return MondayUserInfo(id="unknown", name="Unknown")

    payload = response.json()
    me = ((payload.get("data") or {}).get("me")) if isinstance(payload, dict) else None
    if not isinstance(me, dict):
        logger.warning(f"[MondayOAuth] Unexpected me response: {payload}")
        return MondayUserInfo(id="unknown", name="Unknown")
    return MondayUserInfo(
        id=str(me.get("id", "unknown")),
        name=me.get("name", "Unknown"),
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> MondayTokens:
    """Refresh an access token using the refresh token.

    monday OAuth tokens do not normally expire, but apps configured with token
    rotation can issue refresh tokens. monday's refresh tokens are NOT single-use
    rotated, so the response may omit a new refresh_token — in that case we keep
    the existing one.

    Args:
        refresh_token: The refresh token stored in credentials
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New MondayTokens with an updated access_token

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
        response = await client.post(MONDAY_TOKEN_URL, data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"[MondayOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[MondayOAuth] Token refresh failed: {error_msg}")
            error_code = token_data.get("error") if isinstance(token_data, dict) else None
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        expires_at = None
        if token_data.get("expires_in"):
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = MondayTokens(
            access_token=token_data["access_token"],
            # Non-rotating refresh token: keep the existing one if the provider
            # doesn't return a fresh one.
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[MondayOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Check if a token is expired or will expire within *buffer_minutes*.

    monday tokens are non-expiring (expires_at is None), in which case this
    always returns False.

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
        logger.error(f"[MondayOAuth] Error parsing expiry time: {e}")
        return False


def get_monday_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the monday.com OAuth authorization URL.

    monday expects space-delimited scopes at the authorize endpoint.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in the URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_monday_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{MONDAY_AUTH_URL}?{urlencode(params)}"


# Default scopes for monday operations. Mirrors the x-oauth-scopes in
# MondayOAuthCredential so the authorize route and backend agree.
MONDAY_DEFAULT_SCOPES = [
    "account:read",
    "boards:read",
    "boards:write",
    "docs:read",
    "docs:write",
    "workspaces:read",
    "workspaces:write",
    "users:read",
    "users:write",
    "teams:read",
    "teams:write",
    "updates:read",
    "updates:write",
    "notifications:write",
    "webhooks:read",
    "webhooks:write",
    "assets:read",
    "tags:read",
    "me:read",
]
