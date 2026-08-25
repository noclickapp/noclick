"""
Cal.com OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 (authorization-code) flow for Cal.com API v2 access.

Cal.com OAuth uses:
- Authorization URL: https://app.cal.com/auth/oauth2/authorize
- Token URL: https://api.cal.com/v2/auth/oauth2/token (JSON body)
- Access tokens expire after 30 minutes (expires_in: 1800); refresh tokens rotate
- Bearer access token is a drop-in replacement for the API key on v2 endpoints

Documentation: https://cal.com/docs/api-reference/v2/oauth
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CALCOM_AUTH_URL = "https://app.cal.com/auth/oauth2/authorize"
CALCOM_TOKEN_URL = "https://api.cal.com/v2/auth/oauth2/token"
CALCOM_ME_URL = "https://api.cal.com/v2/me"
CALCOM_ME_API_VERSION = "2024-08-13"

# User-level scopes covering every operation the node exposes (bookings,
# event types, schedules, availability, profile). Space- or comma-separated
# are both accepted by Cal.com; we send space-separated (the documented form).
CALCOM_DEFAULT_SCOPES = [
    "BOOKING_READ",
    "BOOKING_WRITE",
    "EVENT_TYPE_READ",
    "EVENT_TYPE_WRITE",
    "SCHEDULE_READ",
    "SCHEDULE_WRITE",
    "PROFILE_READ",
    "PROFILE_WRITE",
    "WEBHOOK_READ",
    "WEBHOOK_WRITE",
]


class CalComTokens(BaseModel):
    """Structured token response from Cal.com OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    scope: str = ""
    token_type: str = "Bearer"


class CalComUserInfo(BaseModel):
    """User info from Cal.com /me"""

    id: str
    name: str
    email: Optional[str] = None
    username: Optional[str] = None


def get_calcom_client_config() -> Tuple[str, str]:
    """Return (client_id, client_secret) from env. Raises if unset."""
    client_id = os.environ.get("CALCOM_CLIENT_ID")
    client_secret = os.environ.get("CALCOM_CLIENT_SECRET")
    if not client_id:
        raise ValueError("CALCOM_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("CALCOM_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def _tokens_from_response(token_data: dict) -> CalComTokens:
    expires_at = None
    if "expires_in" in token_data:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))
        ).isoformat()
    return CalComTokens(
        access_token=token_data["access_token"],
        # Cal.com may or may not rotate the refresh token on refresh; the shared
        # choke point keeps the previous one when this is absent, so no
        # require_rotated_refresh_token here.
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at,
        scope=token_data.get("scope", ""),
        token_type=token_data.get("token_type", "Bearer"),
    )


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[CalComTokens, CalComUserInfo]:
    """Exchange an authorization code for access + refresh tokens."""
    client_id, client_secret = get_calcom_client_config()

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            CALCOM_TOKEN_URL,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/json"},
        )

        if token_response.status_code != 200:
            logger.error(f"[CalComOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()
        # Cal.com v2 wraps some responses in {status, data}; unwrap if present.
        if isinstance(token_data, dict) and "access_token" not in token_data and isinstance(token_data.get("data"), dict):
            token_data = token_data["data"]
        if "error" in token_data:
            error_msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            logger.error(f"[CalComOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        tokens = _tokens_from_response(token_data)
        user_info = await _get_user_info(client, tokens.access_token)
        logger.info(f"[CalComOAuth] Exchanged code for tokens (user {user_info.name})")
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> CalComUserInfo:
    """Fetch the authenticated user's profile from Cal.com /me."""
    try:
        response = await client.get(
            CALCOM_ME_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "cal-api-version": CALCOM_ME_API_VERSION,
            },
        )
        if response.status_code != 200:
            logger.warning(f"[CalComOAuth] Failed to get user info: HTTP {response.status_code}")
            return CalComUserInfo(id="unknown", name="Unknown")
        payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        return CalComUserInfo(
            id=str(data.get("id", "unknown")),
            name=data.get("name") or data.get("username") or "Cal.com user",
            email=data.get("email"),
            username=data.get("username"),
        )
    except Exception as e:
        logger.warning(f"[CalComOAuth] Error fetching user info: {e}")
        return CalComUserInfo(id="unknown", name="Unknown")


async def refresh_access_token(refresh_token: str) -> CalComTokens:
    """Refresh an expired access token using the refresh token."""
    client_id, client_secret = get_calcom_client_config()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            CALCOM_TOKEN_URL,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            logger.error(f"[CalComOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()
        if isinstance(token_data, dict) and "access_token" not in token_data and isinstance(token_data.get("data"), dict):
            token_data = token_data["data"]
        if "error" in token_data:
            error_msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            logger.error(f"[CalComOAuth] Token refresh failed: {error_msg}")
            span = trace.get_current_span()
            if span and span.is_recording():
                span.set_attribute("oauth.provider_error_code", str(token_data.get("error")))
            raise ValueError(f"Token refresh failed: {error_msg}")

        logger.info("[CalComOAuth] Successfully refreshed access token")
        return _tokens_from_response(token_data)


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """True if the token is expired or expiring within buffer_minutes."""
    if not expires_at:
        return False
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[CalComOAuth] Error parsing expiry time: {e}")
        return False


def get_calcom_auth_url(scopes: list[str], state: str, redirect_uri: str) -> str:
    """Build the Cal.com authorization URL (space-separated scopes)."""
    client_id, _ = get_calcom_client_config()
    from urllib.parse import urlencode

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{CALCOM_AUTH_URL}?{urlencode(params)}"
