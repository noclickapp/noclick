"""
ClickUp OAuth 2.0 utility for handling token exchange and refresh.
Manages the authorization_code flow for ClickUp API access.

ClickUp OAuth uses:
- Authorization URL: https://app.clickup.com/api
- Token URL:         https://api.clickup.com/api/v2/oauth/token
- Refresh:           ClickUp issues NO refresh token and the access token does
                     not currently expire, so refresh is effectively a no-op
                     that re-validates and keeps the existing token.
- User / account:    GET https://api.clickup.com/api/v2/user (returns the
                     authorized user) — used to label the credential.

ClickUp has no scope system: authorization is granted per-Workspace during the
consent step, and the access token does not expire (ClickUp notes this "is
subject to change"). Access tokens use the ``Bearer `` prefix.

client_id / client_secret default to the CLICKUP_CLIENT_ID / CLICKUP_CLIENT_SECRET
env vars but accept user-supplied values so a "bring your own app" custom OAuth
client (x-oauth-supports-custom-client) can be used.

Documentation: https://developer.clickup.com/docs/authentication
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

CLICKUP_AUTH_URL = "https://app.clickup.com/api"
CLICKUP_TOKEN_URL = "https://api.clickup.com/api/v2/oauth/token"
CLICKUP_USERINFO_URL = "https://api.clickup.com/api/v2/user"


class ClickUpTokens(BaseModel):
    """Structured token response from ClickUp OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp (ClickUp tokens don't expire)
    token_type: str = "Bearer"


class ClickUpUserInfo(BaseModel):
    """User info from ClickUp (GET /user)."""

    id: str
    name: str
    email: Optional[str] = None


def get_clickup_client_config() -> Tuple[str, str]:
    """Get ClickUp OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("CLICKUP_CLIENT_ID")
    client_secret = os.environ.get("CLICKUP_CLIENT_SECRET")

    if not client_id:
        raise ValueError("CLICKUP_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("CLICKUP_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_clickup_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[ClickUpTokens, ClickUpUserInfo]:
    """Exchange authorization code for an access token, then fetch user info.

    ClickUp's token endpoint takes ``client_id``, ``client_secret`` and ``code``
    (and accepts ``redirect_uri``), and returns only ``access_token`` — no
    refresh token and no expiry.

    Args:
        code: Authorization code from ClickUp OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (ClickUpTokens, ClickUpUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    data = {
        "client_id": cid,
        "client_secret": csecret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(CLICKUP_TOKEN_URL, params=data)

        if token_response.status_code != 200:
            logger.error(f"[ClickUpOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "err" in token_data or "error" in token_data:
            error_msg = token_data.get(
                "err", token_data.get("error", "Unknown error")
            )
            logger.error(f"[ClickUpOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("Token exchange failed: no access_token in response")

        tokens = ClickUpTokens(
            access_token=access_token,
            refresh_token=token_data.get("refresh_token"),
            expires_at=None,  # ClickUp access tokens do not expire.
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[ClickUpOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(
    client: httpx.AsyncClient, access_token: str
) -> ClickUpUserInfo:
    """Fetch user info from ClickUp's GET /user."""
    response = await client.get(
        CLICKUP_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[ClickUpOAuth] Failed to get user info: HTTP {response.status_code}")
        return ClickUpUserInfo(id="unknown", name="Unknown")

    payload = response.json()
    me = payload.get("user", payload) if isinstance(payload, dict) else {}
    return ClickUpUserInfo(
        id=str(me.get("id", "unknown")),
        name=me.get("username") or me.get("name") or "Unknown",
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> ClickUpTokens:
    """Refresh an access token.

    ClickUp does NOT issue refresh tokens and its access tokens do not expire,
    so there is nothing to exchange: we return the existing token unchanged
    (treating ``refresh_token`` as the still-valid access token). The non-rotating
    contract means callers keep the existing token when no fresh one is returned.

    Args:
        refresh_token: The token stored in credentials (ClickUp reuses the
            access token here since no separate refresh token exists)
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        ClickUpTokens carrying the (unchanged) access token

    Raises:
        ValueError: If the stored token is missing
    """
    # ClickUp has no refresh endpoint; the freshen choke point only overwrites
    # the stored token when the response carries a new one (it never will here).
    if not refresh_token:
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("oauth.provider_error_code", "no_refresh_token")
        raise ValueError("Token refresh failed: no token available")

    logger.info("[ClickUpOAuth] ClickUp tokens do not expire; keeping existing token")
    return ClickUpTokens(
        access_token=refresh_token,
        refresh_token=refresh_token,
        expires_at=None,
        token_type="Bearer",
    )


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Check if a token is expired or will expire within *buffer_minutes*.

    ClickUp tokens do not expire, so a credential with no stored expiry is never
    considered expired.

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
        logger.error(f"[ClickUpOAuth] Error parsing expiry time: {e}")
        return False


def get_clickup_auth_url(
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the ClickUp OAuth authorization URL.

    ClickUp has no scope system, so only client_id, redirect_uri and state are
    sent. The user selects which Workspace(s) to authorize on the consent screen.

    Args:
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_clickup_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{CLICKUP_AUTH_URL}?{urlencode(params)}"


# ClickUp has no scope system; authorization is per-Workspace. The empty list
# mirrors the x-oauth-scopes in ClickUpOAuthCredential.
CLICKUP_DEFAULT_SCOPES: list[str] = []
