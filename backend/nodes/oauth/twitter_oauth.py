"""
Twitter/X OAuth 2.0 utilities with PKCE flow support.
Handles token exchange, refresh, and validation for Twitter API v2.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from pydantic import BaseModel
import httpx
from opentelemetry import trace
from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

# OAuth endpoints
TWITTER_TOKEN_URL = "https://api.x.com/2/oauth2/token"
TWITTER_REVOKE_URL = "https://api.x.com/2/oauth2/revoke"

# Client credentials from environment
TWITTER_CLIENT_ID = os.environ.get("X_CLIENT_ID", "")
TWITTER_CLIENT_SECRET = os.environ.get("X_CLIENT_SECRET", "")


class TwitterTokenResponse(BaseModel):
    """Twitter OAuth token response model."""

    access_token: str
    token_type: str
    expires_in: int  # seconds
    expires_at: Optional[str] = None  # ISO 8601 timestamp, computed from expires_in
    refresh_token: Optional[str] = None
    scope: Optional[str] = None


class TwitterUserInfo(BaseModel):
    """Twitter user information from OAuth."""

    id: str
    name: str
    username: str


def calculate_expires_at(expires_in: int) -> str:
    """Calculate ISO 8601 expiry time from expires_in seconds."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return expires_at.isoformat().replace("+00:00", "Z")


def is_token_expired(expires_at: str, buffer_minutes: int = 5) -> bool:
    """
    Check if OAuth token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp
        buffer_minutes: Consider expired if within this many minutes

    Returns:
        True if expired or expiring soon
    """
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=buffer_minutes)
        return now >= (expiry - buffer)
    except Exception as e:
        logger.error(f"[TwitterOAuth] Error parsing expiry time: {e}")
        return True  # Assume expired on error


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[TwitterTokenResponse, TwitterUserInfo]:
    """
    Exchange authorization code for access/refresh tokens using PKCE.

    Args:
        code: Authorization code from OAuth callback
        redirect_uri: Redirect URI used in authorization
        code_verifier: PKCE code verifier
        client_id: Optional custom client ID (uses env if not provided)
        client_secret: Optional custom client secret (uses env if not provided)

    Returns:
        Tuple of (tokens, user_info)

    Raises:
        ValueError: If token exchange fails
    """
    # Use provided credentials or fall back to environment
    client_id = client_id or TWITTER_CLIENT_ID
    client_secret = client_secret or TWITTER_CLIENT_SECRET

    if not client_id or not client_secret:
        raise ValueError("Twitter OAuth client credentials not configured")

    # Prepare token request.
    # X requires client_id in the body for PKCE flows even when Basic Auth is used.
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "client_id": client_id,
    }

    auth = (client_id, client_secret)

    try:
        async with httpx.AsyncClient() as client:
            logger.info("[TwitterOAuth] Exchanging authorization code for tokens")
            response = await client.post(
                TWITTER_TOKEN_URL, data=data, auth=auth, timeout=30.0
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error_description") or f"HTTP {response.status_code}"
                logger.error(f"[TwitterOAuth] Token exchange failed: {error_msg}")
                raise ValueError(f"Token exchange failed: {error_msg}")

            token_data = response.json()
            logger.info("[TwitterOAuth] Successfully exchanged code for tokens")

            expires_in = token_data.get("expires_in", 7200)
            tokens = TwitterTokenResponse(
                access_token=token_data["access_token"],
                token_type=token_data.get("token_type", "bearer"),
                expires_in=expires_in,
                expires_at=calculate_expires_at(expires_in),
                refresh_token=token_data.get("refresh_token"),
                scope=token_data.get("scope"),
            )

            # Get user information
            user_info = await get_user_info(tokens.access_token)

            return (tokens, user_info)

    except httpx.TimeoutException:
        logger.error("[TwitterOAuth] Token exchange timed out")
        raise ValueError("Token exchange request timed out")
    except httpx.RequestError as e:
        logger.error(f"[TwitterOAuth] Token exchange request failed: {e}")
        raise ValueError(f"Token exchange request failed: {str(e)}")


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> TwitterTokenResponse:
    """
    Refresh an expired access token.

    Args:
        refresh_token: Refresh token from OAuth
        client_id: Optional custom client ID
        client_secret: Optional custom client secret

    Returns:
        New tokens

    Raises:
        ValueError: If token refresh fails
    """
    client_id = client_id or TWITTER_CLIENT_ID
    client_secret = client_secret or TWITTER_CLIENT_SECRET

    if not client_id or not client_secret:
        raise ValueError("Twitter OAuth client credentials not configured")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }

    auth = (client_id, client_secret)

    try:
        async with httpx.AsyncClient() as client:
            logger.info("[TwitterOAuth] Refreshing access token")
            response = await client.post(
                TWITTER_TOKEN_URL, data=data, auth=auth, timeout=30.0
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error_description") or f"HTTP {response.status_code}"
                logger.error(f"[TwitterOAuth] Token refresh failed: {error_msg}")
                error_code = None
                if isinstance(error_data, dict):
                    error_code = error_data.get("error")
                span = trace.get_current_span()
                if span and span.is_recording() and error_code:
                    span.set_attribute("oauth.provider_error_code", str(error_code))
                raise ValueError(f"Token refresh failed: {error_msg}")

            token_data = response.json()
            logger.info("[TwitterOAuth] Successfully refreshed access token")

            expires_in = token_data.get("expires_in", 7200)
            return TwitterTokenResponse(
                access_token=token_data["access_token"],
                token_type=token_data.get("token_type", "bearer"),
                expires_in=expires_in,
                expires_at=calculate_expires_at(expires_in),
                refresh_token=require_rotated_refresh_token(token_data, provider="twitter"),
                scope=token_data.get("scope"),
            )

    except httpx.TimeoutException:
        logger.error("[TwitterOAuth] Token refresh timed out")
        raise ValueError("Token refresh request timed out")
    except httpx.RequestError as e:
        logger.error(f"[TwitterOAuth] Token refresh request failed: {e}")
        raise ValueError(f"Token refresh request failed: {str(e)}")


async def get_user_info(access_token: str) -> Optional[TwitterUserInfo]:
    """
    Get authenticated user information.

    Returns None (non-fatal) if the request fails — e.g. when the X app is not
    yet attached to a Developer Project, which causes a 403 on v2 endpoints even
    though the tokens themselves are valid.

    Args:
        access_token: Valid access token

    Returns:
        TwitterUserInfo with user details, or None on failure
    """
    try:
        async with httpx.AsyncClient() as client:
            logger.info("[TwitterOAuth] Fetching user information")
            response = await client.get(
                "https://api.x.com/2/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.warning(
                    f"[TwitterOAuth] Could not fetch user info (non-fatal, status={response.status_code}): "
                    f"HTTP {response.status_code}"
                )
                return None

            data = response.json()
            user_data = data.get("data", {})

            return TwitterUserInfo(
                id=user_data.get("id", ""),
                name=user_data.get("name", "Unknown"),
                username=user_data.get("username", "unknown"),
            )

    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.warning(f"[TwitterOAuth] Could not fetch user info (non-fatal): {e}")
        return None


async def revoke_token(
    token: str,
    token_type_hint: str = "access_token",
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> bool:
    """
    Revoke an access or refresh token.

    Args:
        token: Token to revoke
        token_type_hint: "access_token" or "refresh_token"
        client_id: Optional custom client ID
        client_secret: Optional custom client secret

    Returns:
        True if successful

    Raises:
        ValueError: If revocation fails
    """
    client_id = client_id or TWITTER_CLIENT_ID
    client_secret = client_secret or TWITTER_CLIENT_SECRET

    if not client_id or not client_secret:
        raise ValueError("Twitter OAuth client credentials not configured")

    data = {
        "token": token,
        "token_type_hint": token_type_hint,
        "client_id": client_id,
    }

    auth = (client_id, client_secret)

    try:
        async with httpx.AsyncClient() as client:
            logger.info(f"[TwitterOAuth] Revoking {token_type_hint}")
            response = await client.post(
                TWITTER_REVOKE_URL, data=data, auth=auth, timeout=30.0
            )

            if response.status_code == 200:
                logger.info("[TwitterOAuth] Token revoked successfully")
                return True
            else:
                error_msg = f"HTTP {response.status_code}"
                logger.error(f"[TwitterOAuth] Token revocation failed: {error_msg}")
                raise ValueError(f"Token revocation failed: {error_msg}")

    except httpx.TimeoutException:
        logger.error("[TwitterOAuth] Token revocation timed out")
        raise ValueError("Token revocation request timed out")
    except httpx.RequestError as e:
        logger.error(f"[TwitterOAuth] Token revocation request failed: {e}")
        raise ValueError(f"Token revocation request failed: {str(e)}")
