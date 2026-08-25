"""
Dropbox OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Dropbox API access.

Dropbox OAuth uses:
- Authorization URL: https://www.dropbox.com/oauth2/authorize
- Token URL: https://api.dropboxapi.com/oauth2/token
- Dropbox access tokens don't expire by default (short-lived tokens optional)

Documentation: https://developers.dropbox.com/oauth-guide
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DROPBOX_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DROPBOX_USER_URL = "https://api.dropboxapi.com/2/users/get_current_account"
DROPBOX_API_BASE = "https://api.dropboxapi.com/2"


class DropboxTokens(BaseModel):
    """Structured token response from Dropbox OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    scope: str = ""
    token_type: str = "Bearer"
    account_id: Optional[str] = None


class DropboxUserInfo(BaseModel):
    """User info from Dropbox"""

    account_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    display_name: Optional[str] = None


def get_dropbox_client_config() -> Tuple[str, str]:
    """
    Get Dropbox OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("DROPBOX_CLIENT_ID")
    client_secret = os.environ.get("DROPBOX_CLIENT_SECRET")

    if not client_id:
        raise ValueError("DROPBOX_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("DROPBOX_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[DropboxTokens, DropboxUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from Dropbox OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (DropboxTokens, DropboxUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_dropbox_client_config()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            DROPBOX_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            logger.error(f"[DropboxOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[DropboxOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Calculate expiry time if using short-lived tokens
        expires_in = token_data.get("expires_in")
        expires_at = None
        if expires_in:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        tokens = DropboxTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
            account_id=token_data.get("account_id"),
        )

        # Get user info
        userinfo_response = await client.post(
            DROPBOX_USER_URL,
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
                "Content-Type": "application/json",
            },
            json=None,
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                f"[DropboxOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            # Fallback - use account_id from token response if available
            user_info = DropboxUserInfo(
                account_id=tokens.account_id or "0",
                email=None,
                name=None,
                display_name=None,
            )
        else:
            userinfo_data = userinfo_response.json()
            user_info = DropboxUserInfo(
                account_id=userinfo_data.get("account_id", "0"),
                email=userinfo_data.get("email"),
                name=userinfo_data.get("name", {}).get("display_name"),
                display_name=userinfo_data.get("name", {}).get("display_name"),
            )

        logger.info(
            f"[DropboxOAuth] Successfully exchanged code for tokens for account {user_info.account_id}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> DropboxTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New DropboxTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails
    """
    client_id, client_secret = get_dropbox_client_config()

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
            DROPBOX_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"[DropboxOAuth] Token refresh failed: HTTP {response.status_code}")
            error_code = None
            try:
                body = response.json()
                if isinstance(body, dict):
                    error_code = body.get("error")
            except Exception:
                pass
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[DropboxOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(token_data, dict):
                error_code = token_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        # Calculate new expiry time
        expires_in = token_data.get("expires_in")
        expires_at = None
        if expires_in:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        tokens = DropboxTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
            account_id=token_data.get("account_id"),
        )

        logger.info("[DropboxOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if still valid
    """
    if not expires_at:
        # Dropbox tokens without expiry are long-lived and don't expire
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[DropboxOAuth] Error parsing expiry time: {e}")
        return True  # If we can't parse, treat as expired


def get_dropbox_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    token_access_type: str = "offline",
) -> str:
    """
    Generate Dropbox OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        token_access_type: "offline" for refresh tokens, "online" for long-lived tokens

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_dropbox_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "token_access_type": token_access_type,
    }

    # Only add scope if scopes are specified
    if scopes:
        params["scope"] = " ".join(scopes)

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{DROPBOX_AUTH_URL}?{query_string}"


# Standard scopes for Dropbox workflow operations
DROPBOX_WORKFLOW_SCOPES = [
    "account_info.read",  # Access account information
    "files.metadata.read",  # Read file/folder metadata
    "files.metadata.write",  # Write file/folder metadata
    "files.content.read",  # Download/read file contents
    "files.content.write",  # Upload/write file contents
    "sharing.read",  # Access sharing information
    "sharing.write",  # Manage sharing settings
    "file_requests.read",  # Access file requests
    "file_requests.write",  # Create/modify file requests
]
