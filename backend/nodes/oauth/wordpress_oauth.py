"""
WordPress.com OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for WordPress.com API access.

WordPress.com OAuth uses:
- Authorization URL: https://public-api.wordpress.com/oauth2/authorize
- Token URL: https://public-api.wordpress.com/oauth2/token
- Access tokens do not expire (long-lived)
- Refresh tokens are not provided by default

Documentation: https://developer.wordpress.com/docs/api/oauth2/
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

WORDPRESS_AUTH_URL = "https://public-api.wordpress.com/oauth2/authorize"
WORDPRESS_TOKEN_URL = "https://public-api.wordpress.com/oauth2/token"
WORDPRESS_USERINFO_URL = "https://public-api.wordpress.com/rest/v1.1/me"


class WordPressTokens(BaseModel):
    """Structured token response from WordPress.com OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[
        str
    ] = None  # ISO 8601 timestamp (WordPress.com tokens don't expire)
    scope: str = "global"
    token_type: str = "Bearer"


class WordPressUserInfo(BaseModel):
    """User info from WordPress.com"""

    id: int
    username: str
    email: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    primary_site_url: Optional[str] = None


def get_wordpress_client_config() -> Tuple[str, str]:
    """
    Get WordPress.com OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("WORDPRESS_CLIENT_ID")
    client_secret = os.environ.get("WORDPRESS_CLIENT_SECRET")

    if not client_id:
        raise ValueError("WORDPRESS_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("WORDPRESS_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[WordPressTokens, WordPressUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from WordPress.com OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (WordPressTokens, WordPressUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_wordpress_client_config()

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            WORDPRESS_TOKEN_URL,
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
            error_data = (
                token_response.json()
                if token_response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )
            error_msg = error_data.get(
                "error_description",
                error_data.get("error", token_response.text or "Unknown error"),
            )
            logger.error(f"[WordPressOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # WordPress.com tokens are long-lived and don't expire
        # Set a far future expiry date
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=3650)
        ).isoformat()  # 10 years

        tokens = WordPressTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            scope=token_data.get("scope", "global"),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info
        userinfo_response = await client.get(
            WORDPRESS_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens.access_token}"},
        )

        if userinfo_response.status_code != 200:
            logger.error(
                f"[WordPressOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            raise ValueError("Failed to get user info from WordPress.com")

        userinfo_data = userinfo_response.json()
        user_info = WordPressUserInfo(
            id=userinfo_data.get("ID", 0),
            username=userinfo_data.get("username", ""),
            email=userinfo_data.get("email", ""),
            display_name=userinfo_data.get("display_name"),
            avatar_url=userinfo_data.get("avatar_URL"),
            primary_site_url=userinfo_data.get("primary_blog_url"),
        )

        logger.info(
            f"[WordPressOAuth] Successfully exchanged code for tokens for user {user_info.username}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> WordPressTokens:
    """
    Refresh an expired access token using the refresh token.

    Note: WordPress.com access tokens are long-lived and typically don't expire.
    This function is provided for completeness but may not be needed.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New WordPressTokens with updated access_token

    Raises:
        ValueError: If refresh fails (token revoked, etc.)
    """
    client_id, client_secret = get_wordpress_client_config()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            WORDPRESS_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            error_data = (
                response.json()
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )
            error_msg = error_data.get(
                "error_description",
                error_data.get("error", response.text or "Unknown error"),
            )
            logger.error(f"[WordPressOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(error_data, dict):
                error_code = error_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        # Set far future expiry date
        expires_at = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()

        tokens = WordPressTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            scope=token_data.get("scope", "global"),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[WordPressOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry (can be None for WordPress.com)
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon
    """
    # WordPress.com tokens don't expire, so return False if no expiry
    if not expires_at:
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[WordPressOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume not expired for WordPress.com
        return False


def get_wordpress_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate WordPress.com OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (WordPress.com uses 'global' scope)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_wordpress_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes) if scopes else "global",
        "state": state,
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{WORDPRESS_AUTH_URL}?{query_string}"


# Standard scope for WordPress.com (typically just 'global')
WORDPRESS_DEFAULT_SCOPES = ["global"]
