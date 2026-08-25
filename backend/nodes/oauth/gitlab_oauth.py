"""
GitLab OAuth 2.0 utility for handling token exchange and refresh.
Manages the authorization_code flow for GitLab API access.

GitLab OAuth uses:
- Authorization URL: https://gitlab.com/oauth/authorize
- Token URL:         https://gitlab.com/oauth/token
- Refresh:           POST token URL with grant_type=refresh_token
- User info:         GET https://gitlab.com/api/v4/user

GitLab access tokens expire after 2 hours; refresh tokens ARE single-use rotated
(the OAuth 2.1 draft GitLab follows rotates the refresh token on every refresh),
so a refresh response MUST return a new refresh_token. We require it via
require_rotated_refresh_token — silently reusing the consumed token would brick
the credential on the next refresh.

client_id / client_secret default to the GITLAB_CLIENT_ID / GITLAB_CLIENT_SECRET
env vars (NoClick's shared gitlab.com app).

Documentation: https://docs.gitlab.com/api/oauth2/
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

GITLAB_AUTH_URL = "https://gitlab.com/oauth/authorize"
GITLAB_TOKEN_URL = "https://gitlab.com/oauth/token"
GITLAB_USERINFO_URL = "https://gitlab.com/api/v4/user"


class GitLabTokens(BaseModel):
    """Structured token response from GitLab OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "Bearer"


class GitLabUserInfo(BaseModel):
    """User info from GitLab (GET /api/v4/user)."""

    id: str
    name: str
    email: Optional[str] = None


def get_gitlab_client_config() -> Tuple[str, str]:
    """Get GitLab OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("GITLAB_CLIENT_ID")
    client_secret = os.environ.get("GITLAB_CLIENT_SECRET")

    if not client_id:
        raise ValueError("GITLAB_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("GITLAB_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_gitlab_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[GitLabTokens, GitLabUserInfo]:
    """Exchange authorization code for access token, then fetch user info.

    Args:
        code: Authorization code from GitLab OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (GitLabTokens, GitLabUserInfo)

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
        token_response = await client.post(GITLAB_TOKEN_URL, data=data, headers=headers)

        if token_response.status_code != 200:
            logger.error(f"[GitLabOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[GitLabOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # GitLab access tokens expire in 2 hours (expires_in seconds).
        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = GitLabTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[GitLabOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> GitLabUserInfo:
    """Fetch user info from GitLab's GET /api/v4/user."""
    response = await client.get(
        GITLAB_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[GitLabOAuth] Failed to get user info: HTTP {response.status_code}")
        return GitLabUserInfo(id="unknown", name="Unknown")

    me = response.json()
    if not isinstance(me, dict):
        return GitLabUserInfo(id="unknown", name="Unknown")
    return GitLabUserInfo(
        id=str(me.get("id", "unknown")),
        name=me.get("name") or me.get("username") or "Unknown",
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> GitLabTokens:
    """Refresh an expired access token using the refresh token.

    GitLab rotates refresh tokens on every refresh, so the response normally
    carries a new refresh_token. We fall back to keeping the existing one only
    when the provider omits it (the freshen choke point overwrites refresh_token
    only when present).

    Args:
        refresh_token: The refresh token stored in credentials
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New GitLabTokens with updated access_token

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
        response = await client.post(GITLAB_TOKEN_URL, data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"[GitLabOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[GitLabOAuth] Token refresh failed: {error_msg}")
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

        tokens = GitLabTokens(
            access_token=token_data["access_token"],
            # GitLab rotates the refresh token (single-use). Require a fresh one —
            # reusing the consumed token bricks the credential next refresh.
            refresh_token=require_rotated_refresh_token(token_data, provider="gitlab"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[GitLabOAuth] Successfully refreshed access token")
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
        logger.error(f"[GitLabOAuth] Error parsing expiry time: {e}")
        return False


def get_gitlab_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the GitLab OAuth authorization URL.

    GitLab expects space-delimited scopes.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in the URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_gitlab_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{GITLAB_AUTH_URL}?{urlencode(params)}"


# Default scopes for GitLab operations. Mirrors the x-oauth-scopes in
# GitLabOAuthCredential so the authorize route and backend agree.
GITLAB_DEFAULT_SCOPES = [
    "api",
    "read_user",
]
