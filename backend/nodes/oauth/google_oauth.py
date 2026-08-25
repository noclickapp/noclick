"""
Google OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Google Sheets and other Google APIs.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"


class GoogleTokens(BaseModel):
    """Structured token response from Google OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class GoogleUserInfo(BaseModel):
    """User info from Google"""

    email: str
    name: Optional[str] = None
    picture: Optional[str] = None


def get_google_client_config() -> Tuple[str, str]:
    """
    Get Google OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("GOOGLE_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    custom_client_id: Optional[str] = None,
    custom_client_secret: Optional[str] = None,
) -> Tuple[GoogleTokens, GoogleUserInfo]:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from Google OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (GoogleTokens, GoogleUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    if custom_client_id and custom_client_secret:
        client_id, client_secret = custom_client_id, custom_client_secret
    else:
        client_id, client_secret = get_google_client_config()

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            error_data = token_response.json()
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[GoogleOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # Calculate expiry time
        expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = GoogleTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens.access_token}"},
        )

        if userinfo_response.status_code != 200:
            logger.error(
                f"[GoogleOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            raise ValueError("Failed to get user info from Google")

        userinfo_data = userinfo_response.json()
        user_info = GoogleUserInfo(
            email=userinfo_data.get("email", ""),
            name=userinfo_data.get("name"),
            picture=userinfo_data.get("picture"),
        )

        logger.info(
            f"[GoogleOAuth] Successfully exchanged code for tokens for user {user_info.email}"
        )
        return tokens, user_info


async def refresh_access_token(
    refresh_token: str,
    custom_client_id: Optional[str] = None,
    custom_client_secret: Optional[str] = None,
) -> GoogleTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New GoogleTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails (token revoked, etc.)
    """
    if custom_client_id and custom_client_secret:
        client_id, client_secret = custom_client_id, custom_client_secret
    else:
        client_id, client_secret = get_google_client_config()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[GoogleOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(error_data, dict):
                error_code = error_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            # Include the raw OAuth error code (e.g. "invalid_grant") in the
            # message so oauth_refresh._extract_provider_error_code can classify
            # the revoke reason — Google returns the code only under "error",
            # while error_msg is the human "error_description". Without this the
            # audit row's provider_error_code is blank and revocations get
            # misclassified as F29_user_revoked.
            raise ValueError(
                f"Token refresh failed: {error_msg}"
                + (f" ({error_code})" if error_code else "")
            )

        token_data = response.json()

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = GoogleTokens(
            access_token=token_data["access_token"],
            refresh_token=refresh_token,  # Refresh token usually doesn't change
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[GoogleOAuth] Successfully refreshed access token")
        return tokens


async def validate_token(access_token: str) -> bool:
    """
    Validate if an access token is still valid.

    Args:
        access_token: The access token to validate

    Returns:
        True if valid, False if expired/invalid
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GOOGLE_TOKEN_INFO_URL,
            params={"access_token": access_token},
        )

        if response.status_code != 200:
            return False

        token_info = response.json()
        # Check if token has remaining validity
        expires_in = int(token_info.get("expires_in", 0))
        return expires_in > 0


def is_token_expired(expires_at: str, buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon
    """
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[GoogleOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_google_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Google OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request
        state: State parameter for CSRF protection (should be base64-encoded JSON)
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_google_client_config()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",  # Get refresh token
        "prompt": "consent",  # Always show consent to ensure refresh token
        "state": state,
    }

    query_string = "&".join(
        f'{k}={httpx.URL("", params={k: v}).params[k]}' for k, v in params.items()
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"


GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


async def revoke_token(token: str) -> bool:
    """
    Revoke a Google OAuth token (access or refresh token).

    This should be called when a user disconnects their Google account
    to properly clean up access on Google's side.

    Args:
        token: Either an access_token or refresh_token to revoke

    Returns:
        True if revocation succeeded, False otherwise
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_REVOKE_URL,
                params={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code == 200:
                logger.info("[GoogleOAuth] Token revoked successfully")
                return True
            else:
                # Google returns 400 if token is already invalid/revoked
                logger.warning(
                    f"[GoogleOAuth] Token revocation returned {response.status_code}: HTTP {response.status_code}"
                )
                return response.status_code == 400  # Already revoked is still "success"

    except Exception as e:
        logger.error(f"[GoogleOAuth] Error revoking token: {e}")
        return False
