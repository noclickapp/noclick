"""
Zoom OAuth 2.0 utility for handling token exchange and refresh.
Manages the user-delegated authorization_code flow for the Zoom REST API.

Zoom OAuth uses:
- Authorization URL: https://zoom.us/oauth/authorize
- Token URL:         https://zoom.us/oauth/token  (HTTP Basic client_id:client_secret)
- Refresh:           POST token URL with grant_type=refresh_token
- User info:         GET https://api.zoom.us/v2/users/me

Zoom access tokens expire after 1 hour. Refresh tokens ARE single-use rotated
(each refresh returns a new refresh_token and the old one is invalidated) and
expire after 90 days of non-use, so a refresh response always carries a new
refresh_token — but if Zoom ever omits one we keep the existing one rather than
dropping it.

client_id / client_secret default to the ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET
env vars but accept user-supplied values so a "bring your own app" custom OAuth
client (x-oauth-supports-custom-client) can be used.

Documentation: https://developers.zoom.us/docs/integrations/oauth/
"""

import os
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

ZOOM_AUTH_URL = "https://zoom.us/oauth/authorize"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_REVOKE_URL = "https://zoom.us/oauth/revoke"
ZOOM_USERINFO_URL = "https://api.zoom.us/v2/users/me"


class ZoomTokens(BaseModel):
    """Structured token response from Zoom OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "Bearer"
    scope: str = ""


class ZoomUserInfo(BaseModel):
    """User info from Zoom (GET /users/me)."""

    id: str
    name: str
    email: Optional[str] = None


def get_zoom_client_config() -> Tuple[str, str]:
    """Get Zoom OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("ZOOM_CLIENT_ID")
    client_secret = os.environ.get("ZOOM_CLIENT_SECRET")

    if not client_id:
        raise ValueError("ZOOM_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("ZOOM_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_zoom_client_config()


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    """Zoom's token endpoint authenticates the client via HTTP Basic."""
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return f"Basic {encoded}"


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[ZoomTokens, ZoomUserInfo]:
    """Exchange authorization code for access token, then fetch user info.

    Args:
        code: Authorization code from Zoom OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (ZoomTokens, ZoomUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {
        "Authorization": _basic_auth_header(cid, csecret),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(ZOOM_TOKEN_URL, data=data, headers=headers)

        if token_response.status_code != 200:
            logger.error(f"[ZoomOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[ZoomOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Zoom access tokens expire in 1 hour (expires_in seconds).
        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = ZoomTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope", ""),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[ZoomOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> ZoomUserInfo:
    """Fetch user info from Zoom's GET /users/me."""
    response = await client.get(
        ZOOM_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[ZoomOAuth] Failed to get user info: HTTP {response.status_code}")
        return ZoomUserInfo(id="unknown", name="Unknown")

    me = response.json()
    if not isinstance(me, dict):
        me = {}
    name = (
        f"{me.get('first_name', '')} {me.get('last_name', '')}".strip()
        or me.get("display_name")
        or me.get("email")
        or "Unknown"
    )
    return ZoomUserInfo(
        id=str(me.get("id", "unknown")),
        name=name,
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> ZoomTokens:
    """Refresh an expired access token using the refresh token.

    Zoom refresh tokens are single-use rotated: each refresh returns a new
    refresh_token and invalidates the old one. We persist the returned token,
    but defensively keep the existing one if the response ever omits it.

    Args:
        refresh_token: The refresh token stored in credentials
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New ZoomTokens with updated access_token (and rotated refresh_token)

    Raises:
        ValueError: If refresh fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {
        "Authorization": _basic_auth_header(cid, csecret),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ZOOM_TOKEN_URL, data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"[ZoomOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[ZoomOAuth] Token refresh failed: {error_msg}")
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

        tokens = ZoomTokens(
            access_token=token_data["access_token"],
            # Zoom rotates single-use refresh tokens: the old one is invalidated,
            # so we REQUIRE a fresh one in the response (never fall back to the
            # consumed token, which would brick the credential — F05 prevention).
            refresh_token=require_rotated_refresh_token(token_data, provider="zoom"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[ZoomOAuth] Successfully refreshed access token")
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
        logger.error(f"[ZoomOAuth] Error parsing expiry time: {e}")
        return False


def get_zoom_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Zoom OAuth authorization URL.

    Zoom's authorize endpoint takes response_type=code, client_id, redirect_uri,
    and an optional state. Scopes are configured on the Marketplace app; Zoom
    rejects caller-supplied scopes after sign-in, so they must be omitted.

    Args:
        scopes: Retained for caller compatibility; Zoom ignores this argument.
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_zoom_client_config()[0]

    _ = scopes
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{ZOOM_AUTH_URL}?{urlencode(params)}"


# Default granular scopes for Zoom operations. Mirrors the x-oauth-scopes in
# ZoomOAuthCredential so the authorize route and backend agree.
ZOOM_DEFAULT_SCOPES = [
    "meeting:read:meeting",
    "meeting:write:meeting",
    "meeting:read:list_meetings",
    "meeting:read:list_registrants",
    "meeting:write:registrant",
    "meeting:read:invitation",
    "meeting:read:past_meeting",
    "meeting:read:list_past_participants",
    "webinar:read:webinar",
    "webinar:write:webinar",
    "webinar:read:list_webinars",
    "webinar:read:list_registrants",
    "webinar:write:registrant",
    "user:read:user",
    "user:write:user",
    "user:read:list_users",
    "cloud_recording:read:list_user_recordings",
    "cloud_recording:read:list_account_recordings",
    "cloud_recording:read:list_recording_files",
    "cloud_recording:delete:meeting_recordings",
    "phone:read:list_call_logs",
    "chat_message:write:message",
]
