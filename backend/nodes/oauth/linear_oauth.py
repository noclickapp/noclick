"""
Linear OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Linear API access.

Linear OAuth uses:
- Authorization URL: https://linear.app/oauth/authorize
- Token URL: https://api.linear.app/oauth/token
- Access tokens expire after 10 years (effectively non-expiring for most use cases)
- Revoke URL: https://api.linear.app/oauth/revoke

Documentation: https://developers.linear.app/docs/oauth/authentication
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel
from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

LINEAR_AUTH_URL = "https://linear.app/oauth/authorize"
LINEAR_TOKEN_URL = "https://api.linear.app/oauth/token"
LINEAR_REVOKE_URL = "https://api.linear.app/oauth/revoke"
LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"


class LinearTokens(BaseModel):
    """Structured token response from Linear OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class LinearUserInfo(BaseModel):
    """User info from Linear"""

    id: str
    name: str
    email: Optional[str] = None
    display_name: Optional[str] = None


def get_linear_client_config() -> Tuple[str, str]:
    """
    Get Linear OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("LINEAR_CLIENT_ID")
    client_secret = os.environ.get("LINEAR_CLIENT_SECRET")

    if not client_id:
        raise ValueError("LINEAR_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("LINEAR_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[LinearTokens, LinearUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from Linear OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (LinearTokens, LinearUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_linear_client_config()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            LINEAR_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            logger.error(f"[LinearOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[LinearOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Linear tokens expire after 10 years by default
        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        tokens = LinearTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info via GraphQL
        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[LinearOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(
    client: httpx.AsyncClient, access_token: str
) -> LinearUserInfo:
    """Fetch user info from Linear GraphQL API"""
    query = """
    query {
        viewer {
            id
            name
            email
            displayName
        }
    }
    """

    response = await client.post(
        LINEAR_GRAPHQL_URL,
        json={"query": query},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[LinearOAuth] Failed to get user info: HTTP {response.status_code}")
        return LinearUserInfo(id="unknown", name="Unknown")

    data = response.json()
    if "errors" in data:
        logger.warning(f"[LinearOAuth] GraphQL errors: {data['errors']}")
        return LinearUserInfo(id="unknown", name="Unknown")

    viewer = data.get("data", {}).get("viewer", {})
    return LinearUserInfo(
        id=viewer.get("id", "unknown"),
        name=viewer.get("name", "Unknown"),
        email=viewer.get("email"),
        display_name=viewer.get("displayName"),
    )


async def refresh_access_token(refresh_token: str) -> LinearTokens:
    """
    Refresh an expired access token using the refresh token.
    Note: Linear tokens are long-lived, so refresh is rarely needed.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New LinearTokens with updated access_token

    Raises:
        ValueError: If refresh fails
    """
    client_id, client_secret = get_linear_client_config()

    headers = {
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
            LINEAR_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"[LinearOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[LinearOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(token_data, dict):
                error_code = token_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        tokens = LinearTokens(
            access_token=token_data["access_token"],
            refresh_token=require_rotated_refresh_token(token_data, provider="linear"),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[LinearOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.
    Note: Linear tokens are typically long-lived (10 years).

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
        logger.error(f"[LinearOAuth] Error parsing expiry time: {e}")
        return False


def get_linear_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Linear OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (comma-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_linear_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(scopes),
        "state": state,
        "prompt": "consent",  # Always show consent screen
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{LINEAR_AUTH_URL}?{query_string}"


async def revoke_token(access_token: str) -> bool:
    """
    Revoke a Linear OAuth token.

    Args:
        access_token: The access token to revoke

    Returns:
        True if revocation succeeded, False otherwise
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                LINEAR_REVOKE_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

            if response.status_code == 200:
                logger.info("[LinearOAuth] Token revoked successfully")
                return True
            else:
                logger.warning(
                    f"[LinearOAuth] Token revocation returned {response.status_code}: HTTP {response.status_code}"
                )
                return False

    except Exception as e:
        logger.error(f"[LinearOAuth] Error revoking token: {e}")
        return False


# Standard scopes for Linear operations
LINEAR_DEFAULT_SCOPES = [
    "read",  # Read access to user data
    "write",  # Write access (create/update issues, etc.)
    "issues:create",  # Create issues
    "comments:create",  # Create comments
    # webhookCreate / webhookDelete require workspace admin scope on the OAuth
    # token regardless of the user's actual workspace role. Without this our
    # Linear trigger registration fails with "Invalid role: admin required"
    # even when the authorizing user IS a workspace admin. Existing tokens
    # don't auto-upgrade — users need to re-authorize Linear after this
    # change for the new scope to apply.
    "admin",
]
