"""
TikTok Open Platform OAuth 2.0 utilities.
Handles token exchange, refresh, and validation for TikTok API v2.

Key differences from standard OAuth:
- Uses 'client_key' instead of 'client_id' in auth URL and token requests
- Access tokens expire in 24 hours (86400 seconds)
- Refresh tokens rotate on each refresh — always save the new refresh_token
- Token response includes 'open_id' (user's unique ID per app)
- Token endpoint uses form-encoded body (not JSON)

Research API:
- Uses client_credentials grant (app-level token, not per-user)
- Client access tokens expire in 2 hours (7200 seconds)
- Use get_client_access_token() for Research API operations
"""
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple
from pydantic import BaseModel
import httpx
from opentelemetry import trace
from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

# OAuth endpoints
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"

# Client credentials from environment
# TikTok uses 'client_key' naming convention
TIKTOK_CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")


class TikTokTokenResponse(BaseModel):
    """TikTok OAuth token response model."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int  # seconds (typically 86400 = 24 hours)
    refresh_token: Optional[str] = None
    refresh_expires_in: Optional[int] = None  # seconds (~1 year)
    open_id: str  # user's unique ID per app
    scope: Optional[str] = None
    # Calculated fields (added after parsing)
    expires_at: Optional[str] = None
    refresh_expires_at: Optional[str] = None


class TikTokUserInfo(BaseModel):
    """TikTok user information from the user/info endpoint."""

    open_id: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


def calculate_expires_at(expires_in: int) -> str:
    """Calculate ISO 8601 expiry time from expires_in seconds."""
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    return expires_at.isoformat() + "Z"


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 60) -> bool:
    """
    Check if OAuth token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp string, or None
        buffer_minutes: Consider expired if within this many minutes.
                        Default 60 — warn 1 hour before expiry since
                        TikTok access tokens only last 24 hours.

    Returns:
        True if expired or expiring soon (or if expires_at is None)
    """
    if not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = datetime.utcnow().replace(tzinfo=expiry.tzinfo)
        buffer = timedelta(minutes=buffer_minutes)
        return now >= (expiry - buffer)
    except Exception as e:
        logger.error(f"[TikTokOAuth] Error parsing expiry time: {e}")
        return True  # Assume expired on error


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_key: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[TikTokTokenResponse, TikTokUserInfo]:
    """
    Exchange authorization code for access/refresh tokens.

    TikTok uses standard Authorization Code grant (no PKCE required).
    Token endpoint expects JSON body with client_key (not client_id).

    Args:
        code: Authorization code from OAuth callback
        redirect_uri: Redirect URI used in authorization request
        client_key: Optional custom client key (uses env if not provided)
        client_secret: Optional custom client secret (uses env if not provided)

    Returns:
        Tuple of (TikTokTokenResponse, TikTokUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_key = client_key or TIKTOK_CLIENT_KEY
    client_secret = client_secret or TIKTOK_CLIENT_SECRET

    if not client_key or not client_secret:
        raise ValueError(
            "TikTok OAuth client credentials not configured. "
            "Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET environment variables."
        )

    payload = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    try:
        async with httpx.AsyncClient() as client:
            logger.info("[TikTokOAuth] Exchanging authorization code for tokens")
            # TikTok token endpoint requires form-encoded body, not JSON
            response = await client.post(
                TIKTOK_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )

            token_data = response.json() if response.content else {}
            if response.status_code != 200 or "access_token" not in token_data:
                error_msg = (
                    token_data.get("error_description")
                    or token_data.get("message")
                    or f"HTTP {response.status_code}"
                )
                logger.error(
                    f"[TikTokOAuth] Token exchange failed ({response.status_code}): {error_msg}"
                )
                raise ValueError(f"Token exchange failed: {error_msg}")

            logger.info("[TikTokOAuth] Successfully exchanged code for tokens")

            expires_in = token_data.get("expires_in", 86400)
            refresh_expires_in = token_data.get("refresh_expires_in")

            tokens = TikTokTokenResponse(
                access_token=token_data["access_token"],
                token_type=token_data.get("token_type", "Bearer"),
                expires_in=expires_in,
                refresh_token=token_data.get("refresh_token"),
                refresh_expires_in=refresh_expires_in,
                open_id=token_data["open_id"],
                scope=token_data.get("scope"),
                expires_at=calculate_expires_at(expires_in),
                refresh_expires_at=calculate_expires_at(refresh_expires_in)
                if refresh_expires_in
                else None,
            )

            # Fetch basic user info (display_name, avatar_url)
            user_info = await get_user_info(tokens.access_token)

            return (tokens, user_info)

    except httpx.TimeoutException:
        logger.error("[TikTokOAuth] Token exchange timed out")
        raise ValueError("Token exchange request timed out")
    except httpx.RequestError as e:
        logger.error(f"[TikTokOAuth] Token exchange request failed: {e}")
        raise ValueError(f"Token exchange request failed: {str(e)}")


async def refresh_access_token(
    refresh_token: str,
    client_key: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> TikTokTokenResponse:
    """
    Refresh an expired access token.

    IMPORTANT: TikTok rotates refresh tokens on each refresh.
    Always save BOTH the new access_token AND the new refresh_token returned here.

    Args:
        refresh_token: Current refresh token
        client_key: Optional custom client key
        client_secret: Optional custom client secret

    Returns:
        New TikTokTokenResponse with rotated tokens

    Raises:
        ValueError: If token refresh fails
    """
    client_key = client_key or TIKTOK_CLIENT_KEY
    client_secret = client_secret or TIKTOK_CLIENT_SECRET

    if not client_key or not client_secret:
        raise ValueError(
            "TikTok OAuth client credentials not configured. "
            "Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET environment variables."
        )

    payload = {
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    try:
        async with httpx.AsyncClient() as client:
            logger.info("[TikTokOAuth] Refreshing access token")
            # TikTok token endpoint requires form-encoded body, not JSON
            response = await client.post(
                TIKTOK_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )

            token_data = response.json() if response.content else {}
            if response.status_code != 200 or "access_token" not in token_data:
                error_msg = (
                    token_data.get("error_description")
                    or token_data.get("message")
                    or f"HTTP {response.status_code}"
                )
                logger.error(
                    f"[TikTokOAuth] Token refresh failed ({response.status_code}): {error_msg}"
                )
                error_code = None
                if isinstance(token_data, dict):
                    error_code = token_data.get("error")
                span = trace.get_current_span()
                if span and span.is_recording() and error_code:
                    span.set_attribute("oauth.provider_error_code", str(error_code))
                raise ValueError(f"Token refresh failed: {error_msg}")

            logger.info("[TikTokOAuth] Successfully refreshed access token")

            expires_in = token_data.get("expires_in", 86400)
            refresh_expires_in = token_data.get("refresh_expires_in")

            return TikTokTokenResponse(
                access_token=token_data["access_token"],
                token_type=token_data.get("token_type", "Bearer"),
                expires_in=expires_in,
                # TikTok rotates refresh tokens — a response without one means the
                # consumed token is all we have; raise instead of bricking the next refresh.
                refresh_token=require_rotated_refresh_token(token_data, provider="tiktok"),
                refresh_expires_in=refresh_expires_in,
                open_id=token_data.get("open_id", ""),
                scope=token_data.get("scope"),
                expires_at=calculate_expires_at(expires_in),
                refresh_expires_at=calculate_expires_at(refresh_expires_in)
                if refresh_expires_in
                else None,
            )

    except httpx.TimeoutException:
        logger.error("[TikTokOAuth] Token refresh timed out")
        raise ValueError("Token refresh request timed out")
    except httpx.RequestError as e:
        logger.error(f"[TikTokOAuth] Token refresh request failed: {e}")
        raise ValueError(f"Token refresh request failed: {str(e)}")


# Module-level cache for the Research API client access token
_client_token_cache: dict = {}  # keys: "token" (str), "expires_at" (float unix ts)


async def get_client_access_token() -> str:
    """
    Get an app-level client access token for the TikTok Research API.

    Uses client_credentials grant (no user authorization required).
    Tokens expire in 2 hours; cached in-memory with a 10-minute buffer.

    Returns:
        Client access token string (prefixed with 'clt.')

    Raises:
        ValueError: If env vars are missing or token request fails
    """
    now = time.time()
    if _client_token_cache.get("token") and now < _client_token_cache.get(
        "expires_at", 0
    ):
        return _client_token_cache["token"]

    if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
        raise ValueError(
            "TikTok Research API requires TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET "
            "environment variables. Register at developers.tiktok.com."
        )

    try:
        async with httpx.AsyncClient() as client:
            logger.info(
                "[TikTokOAuth] Fetching client credentials token for Research API"
            )
            response = await client.post(
                TIKTOK_TOKEN_URL,
                data={
                    "client_key": TIKTOK_CLIENT_KEY,
                    "client_secret": TIKTOK_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )

            data = response.json() if response.content else {}
            if response.status_code != 200 or "access_token" not in data:
                error_msg = (
                    data.get("error_description")
                    or data.get("message")
                    or f"HTTP {response.status_code}"
                )
                logger.error(
                    f"[TikTokOAuth] Client credentials token failed ({response.status_code}): {error_msg}"
                )
                raise ValueError(f"Research API token request failed: {error_msg}")

            expires_in = data.get("expires_in", 7200)
            _client_token_cache["token"] = data["access_token"]
            _client_token_cache["expires_at"] = now + expires_in - 600  # 10-min buffer

            logger.info("[TikTokOAuth] Successfully obtained Research API client token")
            return _client_token_cache["token"]

    except httpx.TimeoutException:
        raise ValueError("Research API token request timed out")
    except httpx.RequestError as e:
        raise ValueError(f"Research API token request failed: {str(e)}")


async def get_user_info(access_token: str) -> TikTokUserInfo:
    """
    Fetch authenticated user's basic profile information.

    Args:
        access_token: Valid TikTok access token

    Returns:
        TikTokUserInfo with open_id, display_name, and avatar_url

    Raises:
        ValueError: If request fails
    """
    try:
        async with httpx.AsyncClient() as client:
            logger.info("[TikTokOAuth] Fetching user info")
            response = await client.get(
                TIKTOK_USER_INFO_URL,
                params={"fields": "open_id,display_name,avatar_url"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )

            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                logger.error(f"[TikTokOAuth] Failed to get user info: {error_msg}")
                raise ValueError(f"Failed to get user info: {error_msg}")

            data = response.json()
            user_data = data.get("data", {}).get("user", {})

            return TikTokUserInfo(
                open_id=user_data.get("open_id", ""),
                display_name=user_data.get("display_name"),
                avatar_url=user_data.get("avatar_url"),
            )

    except httpx.TimeoutException:
        logger.error("[TikTokOAuth] User info request timed out")
        raise ValueError("User info request timed out")
    except httpx.RequestError as e:
        logger.error(f"[TikTokOAuth] User info request failed: {e}")
        raise ValueError(f"User info request failed: {str(e)}")
