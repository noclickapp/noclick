"""
Box OAuth 2.0 utility for handling token exchange and refresh.
Manages the Authorization Code (user-delegated, 3-legged) flow for Box API access.

Box OAuth uses:
- Authorization URL: https://account.box.com/api/oauth2/authorize
- Token URL:         https://api.box.com/oauth2/token
- Refresh:           POST token URL with grant_type=refresh_token
- User info:         GET https://api.box.com/2.0/users/me

Box access tokens expire after ~60 minutes. Refresh tokens last 60 days and are
SINGLE-USE / ROTATING — every refresh returns a NEW refresh token, so the newest
one must always be persisted (same single-use hazard as Slack). The freshen
choke point handles persistence; this util always surfaces the fresh
refresh_token from the response.

client_id / client_secret default to the BOX_CLIENT_ID / BOX_CLIENT_SECRET env
vars but accept user-supplied values so a "bring your own app" custom OAuth
client (x-oauth-supports-custom-client) can be used.

Documentation: https://developer.box.com/guides/authentication/oauth2/
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

BOX_AUTH_URL = "https://account.box.com/api/oauth2/authorize"
BOX_TOKEN_URL = "https://api.box.com/oauth2/token"
BOX_USERINFO_URL = "https://api.box.com/2.0/users/me"


class BoxTokens(BaseModel):
    """Structured token response from Box OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "Bearer"


class BoxUserInfo(BaseModel):
    """User info from Box (GET /users/me)."""

    id: str
    name: str
    email: Optional[str] = None


def get_box_client_config() -> Tuple[str, str]:
    """Get Box OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("BOX_CLIENT_ID")
    client_secret = os.environ.get("BOX_CLIENT_SECRET")

    if not client_id:
        raise ValueError("BOX_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("BOX_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_box_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[BoxTokens, BoxUserInfo]:
    """Exchange authorization code for access token, then fetch user info.

    Args:
        code: Authorization code from Box OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (BoxTokens, BoxUserInfo)

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
        token_response = await client.post(BOX_TOKEN_URL, data=data, headers=headers)

        if token_response.status_code != 200:
            logger.error(f"[BoxOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[BoxOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Box access tokens expire in ~60 minutes (expires_in seconds).
        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = BoxTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[BoxOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> BoxUserInfo:
    """Fetch user info from Box's GET /users/me."""
    response = await client.get(
        BOX_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[BoxOAuth] Failed to get user info: HTTP {response.status_code}")
        return BoxUserInfo(id="unknown", name="Unknown")

    me = response.json()
    if not isinstance(me, dict):
        me = {}
    return BoxUserInfo(
        id=str(me.get("id", "unknown")),
        name=me.get("name", "Unknown"),
        email=me.get("login"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> BoxTokens:
    """Refresh an expired access token using the refresh token.

    Box refresh tokens are SINGLE-USE and rotate on every refresh: the response
    always returns a fresh refresh_token which must be persisted (the freshen
    choke point CAS-persists the rotated token). If the provider somehow omits a
    new refresh_token we keep the existing one rather than dropping it.

    Args:
        refresh_token: The refresh token stored in credentials
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New BoxTokens with updated access_token and rotated refresh_token

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
        response = await client.post(BOX_TOKEN_URL, data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"[BoxOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[BoxOAuth] Token refresh failed: {error_msg}")
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

        tokens = BoxTokens(
            access_token=token_data["access_token"],
            # Rotating single-use refresh token: Box returns a fresh one on every
            # refresh. Require it (F05 prevention) — silently reusing the consumed
            # token would brick the credential on the next refresh.
            refresh_token=require_rotated_refresh_token(token_data, provider="box"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[BoxOAuth] Successfully refreshed access token")
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
        logger.error(f"[BoxOAuth] Error parsing expiry time: {e}")
        return False


def get_box_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Box OAuth authorization URL.

    Box scopes are configured ON THE APP in the Developer Console, not negotiated
    per OAuth request, so the ``scope`` param is optional at authorize time. We
    still pass it (space-delimited) when present for parity with other providers.

    Args:
        scopes: List of OAuth scopes (space-delimited in the URL; may be empty)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_box_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    return f"{BOX_AUTH_URL}?{urlencode(params)}"


# Default scopes for Box operations. Box configures scopes on the app in the
# Developer Console (not per-request), but we surface the canonical set here so
# the credential schema's x-oauth-scopes and the authorize route agree.
BOX_DEFAULT_SCOPES = [
    "root_readwrite",
    "manage_managed_users",
    "manage_groups",
    "manage_webhook",
    "manage_enterprise_properties",
]
