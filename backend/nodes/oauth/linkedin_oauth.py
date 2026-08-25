"""
LinkedIn OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for LinkedIn API access.

LinkedIn OAuth uses:
- Authorization URL: https://www.linkedin.com/oauth/v2/authorization
- Token URL: https://www.linkedin.com/oauth/v2/accessToken
- Userinfo URL: https://api.linkedin.com/v2/userinfo
- LinkedIn access tokens expire after 60 days
- Refresh tokens have longer lifespan but are only available for select partners

Documentation: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"


class LinkedInTokens(BaseModel):
    """Structured token response from LinkedIn OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class LinkedInUserInfo(BaseModel):
    """User info from LinkedIn"""

    sub: str  # LinkedIn member ID
    email: Optional[str] = None
    email_verified: Optional[bool] = None
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    picture: Optional[str] = None


def get_linkedin_client_config() -> Tuple[str, str]:
    """
    Get LinkedIn OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("LINKEDIN_CLIENT_ID")
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET")

    if not client_id:
        raise ValueError("LINKEDIN_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("LINKEDIN_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[LinkedInTokens, LinkedInUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from LinkedIn OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (LinkedInTokens, LinkedInUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_linkedin_client_config()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            LINKEDIN_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            error_data = token_response.json() if token_response.content else {}
            error_msg = error_data.get(
                "error_description", error_data.get("error") or f"HTTP {token_response.status_code}"
            )
            logger.error(f"[LinkedInOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[LinkedInOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Calculate expiry time (LinkedIn tokens last 60 days by default)
        expires_in = token_data.get("expires_in", 5184000)  # Default 60 days in seconds
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        tokens = LinkedInTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info using the userinfo endpoint (requires openid scope)
        userinfo_response = await client.get(
            LINKEDIN_USERINFO_URL,
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
            },
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                f"[LinkedInOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            # Create minimal user info if userinfo fails
            user_info = LinkedInUserInfo(sub="unknown")
        else:
            userinfo_data = userinfo_response.json()
            user_info = LinkedInUserInfo(
                sub=userinfo_data.get("sub", "unknown"),
                email=userinfo_data.get("email"),
                email_verified=userinfo_data.get("email_verified"),
                name=userinfo_data.get("name"),
                given_name=userinfo_data.get("given_name"),
                family_name=userinfo_data.get("family_name"),
                picture=userinfo_data.get("picture"),
            )

        logger.info(
            f"[LinkedInOAuth] Successfully exchanged code for tokens for user {user_info.email or user_info.sub}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> LinkedInTokens:
    """
    Refresh an expired access token using the refresh token.
    Note: LinkedIn refresh tokens are only available for select partners.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New LinkedInTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails (token revoked, refresh tokens not enabled, etc.)
    """
    client_id, client_secret = get_linkedin_client_config()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            LINKEDIN_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get(
                "error_description", error_data.get("error") or f"HTTP {response.status_code}"
            )
            logger.error(f"[LinkedInOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(error_data, dict):
                error_code = error_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[LinkedInOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(token_data, dict):
                error_code = token_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 5184000)  # Default 60 days
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        tokens = LinkedInTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[LinkedInOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if no expiry or still valid
    """
    if not expires_at:
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[LinkedInOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_linkedin_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate LinkedIn OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_linkedin_client_config()

    # Build query parameters
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
    }

    query_string = urlencode(params)
    return f"{LINKEDIN_AUTH_URL}?{query_string}"


# Standard scopes for LinkedIn workflow operations
# openid, profile, email are required for Sign In with LinkedIn using OpenID Connect
# w_member_social is required for posting on behalf of the user
LINKEDIN_WORKFLOW_SCOPES = [
    "openid",  # OpenID Connect (required for userinfo)
    "profile",  # Read profile data
    "email",  # Read email address
    "w_member_social",  # Post, comment, and react on behalf of member
]

# Minimal scopes for read-only access
LINKEDIN_READONLY_SCOPES = [
    "openid",
    "profile",
    "email",
]
