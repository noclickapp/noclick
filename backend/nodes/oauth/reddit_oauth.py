"""
Reddit OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Reddit API access.

Reddit OAuth uses:
- Authorization URL: https://www.reddit.com/api/v1/authorize
- Token URL: https://www.reddit.com/api/v1/access_token
- Reddit access tokens expire after 1 hour
- Refresh tokens are long-lived and used to get new access tokens

Documentation: https://github.com/reddit-archive/reddit/wiki/OAuth2
"""

import os
import logging
import base64
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

REDDIT_AUTH_URL = "https://www.reddit.com/api/v1/authorize"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_USER_URL = "https://oauth.reddit.com/api/v1/me"
USER_AGENT = "NoClick/1.0 (workflow automation)"


class RedditTokens(BaseModel):
    """Structured token response from Reddit OAuth"""

    access_token: str
    refresh_token: str
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class RedditUserInfo(BaseModel):
    """User info from Reddit"""

    id: str
    name: str  # Reddit uses 'name' for username
    icon_img: Optional[str] = None


def get_reddit_client_config() -> Tuple[str, str]:
    """
    Get Reddit OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")

    if not client_id:
        raise ValueError("REDDIT_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("REDDIT_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _get_basic_auth_header() -> str:
    """Generate HTTP Basic Auth header for Reddit API."""
    client_id, client_secret = get_reddit_client_config()
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[RedditTokens, RedditUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from Reddit OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (RedditTokens, RedditUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    headers = {
        "Authorization": _get_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            REDDIT_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            logger.error(f"[RedditOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get("error", "Unknown error")
            logger.error(f"[RedditOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Calculate expiry time (Reddit tokens expire in 1 hour = 3600 seconds)
        expires_in = token_data.get("expires_in", 3600)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        tokens = RedditTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info
        userinfo_response = await client.get(
            REDDIT_USER_URL,
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
                "User-Agent": USER_AGENT,
            },
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                f"[RedditOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            user_info = RedditUserInfo(id="unknown", name="unknown")
        else:
            userinfo_data = userinfo_response.json()
            user_info = RedditUserInfo(
                id=userinfo_data.get("id", "unknown"),
                name=userinfo_data.get("name", "unknown"),
                icon_img=userinfo_data.get("icon_img"),
            )

        logger.info(
            f"[RedditOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> RedditTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New RedditTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails
    """
    headers = {
        "Authorization": _get_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            REDDIT_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"[RedditOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get("error", "Unknown error")
            logger.error(f"[RedditOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(token_data, dict):
                error_code = token_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 3600)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        # Reddit may or may not return a new refresh token
        new_refresh_token = token_data.get("refresh_token", refresh_token)

        tokens = RedditTokens(
            access_token=token_data["access_token"],
            refresh_token=new_refresh_token,
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[RedditOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False otherwise
    """
    if not expires_at:
        # No expiry set - assume expired to be safe
        return True

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[RedditOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired to be safe
        return True


def get_reddit_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    duration: str = "permanent",
) -> str:
    """
    Generate Reddit OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        duration: Token duration - "temporary" (1 hour) or "permanent" (with refresh)

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_reddit_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": redirect_uri,
        "duration": duration,
        "scope": " ".join(scopes),
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{REDDIT_AUTH_URL}?{query_string}"


# Standard scopes for Reddit workflow operations
REDDIT_WORKFLOW_SCOPES = [
    "identity",  # Access user identity
    "read",  # Read public content
    "submit",  # Submit posts and comments
    "vote",  # Vote on posts and comments
    "edit",  # Edit user content
    "history",  # View user history
    "privatemessages",  # Read and send private messages
    "mysubreddits",  # Access subscribed subreddits
    "save",  # Save/unsave content
    "subscribe",  # Manage subscriptions
]
