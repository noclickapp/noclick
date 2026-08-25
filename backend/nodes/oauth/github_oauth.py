"""
GitHub OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for GitHub API access.

GitHub OAuth uses:
- Authorization URL: https://github.com/login/oauth/authorize
- Token URL: https://github.com/login/oauth/access_token
- GitHub access tokens don't expire by default (unless using expiring tokens feature)
- Refresh tokens are only available if "Enable token expiration" is enabled for the OAuth App

Documentation: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

from nodes.scopes.github import GITHUB_REQUESTED_SCOPES

logger = logging.getLogger(__name__)

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


class GithubTokens(BaseModel):
    """Structured token response from GitHub OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[
        str
    ] = None  # ISO 8601 timestamp (only if expiring tokens enabled)
    scope: str
    token_type: str = "Bearer"


class GithubUserInfo(BaseModel):
    """User info from GitHub"""

    id: int
    login: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None


def get_github_client_config() -> Tuple[str, str]:
    """
    Get GitHub OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET")

    if not client_id:
        raise ValueError("GITHUB_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("GITHUB_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[GithubTokens, GithubUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from GitHub OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (GithubTokens, GithubUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_github_client_config()

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            GITHUB_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            logger.error(f"[GithubOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response (GitHub returns 200 even on errors)
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[GithubOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Calculate expiry time if provided (only for expiring tokens)
        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        tokens = GithubTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info
        userinfo_response = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
                "Accept": "application/vnd.github+json",
            },
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                f"[GithubOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            user_info = GithubUserInfo(id=0, login="unknown")
        else:
            userinfo_data = userinfo_response.json()
            user_info = GithubUserInfo(
                id=userinfo_data.get("id", 0),
                login=userinfo_data.get("login", "unknown"),
                email=userinfo_data.get("email"),
                name=userinfo_data.get("name"),
                avatar_url=userinfo_data.get("avatar_url"),
            )

        logger.info(
            f"[GithubOAuth] Successfully exchanged code for tokens for user {user_info.login}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> GithubTokens:
    """
    Refresh an expired access token using the refresh token.
    Note: Only works if the OAuth App has token expiration enabled.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New GithubTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails (token revoked, expiring tokens not enabled, etc.)
    """
    client_id, client_secret = get_github_client_config()

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"[GithubOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[GithubOAuth] Token refresh failed: {error_msg}")
            error_code = token_data.get("error") if isinstance(token_data, dict) else None
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        # Calculate new expiry time
        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        tokens = GithubTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[GithubOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.
    Note: GitHub tokens don't expire by default. Returns False if no expiry is set.

    Args:
        expires_at: ISO 8601 timestamp of token expiry (None if non-expiring)
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if no expiry or still valid
    """
    if not expires_at:
        # No expiry set - token doesn't expire
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[GithubOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume not expired (since GitHub tokens usually don't expire)
        return False


def get_github_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate GitHub OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_github_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{GITHUB_AUTH_URL}?{query_string}"


# Standard scopes for GitHub workflow operations. Same derived list the node's
# `x-oauth-scopes` publishes — see nodes/scopes/github.py, which is the only
# place a GitHub scope may be added.
GITHUB_WORKFLOW_SCOPES = list(GITHUB_REQUESTED_SCOPES)

# Minimal scopes for public repo access only
GITHUB_PUBLIC_SCOPES = [
    "public_repo",  # Access public repositories
    "read:user",  # Read user profile data
]
