"""
Notion OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Notion API access.

Notion OAuth uses:
- Authorization URL: https://api.notion.com/v1/oauth/authorize
- Token URL: https://api.notion.com/v1/oauth/token
- Access tokens may or may not expire depending on integration type
- Refresh tokens are provided for public integrations

Documentation: https://developers.notion.com/docs/authorization
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

NOTION_AUTH_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token"
NOTION_USERS_ME_URL = "https://api.notion.com/v1/users/me"

NOTION_API_VERSION = "2022-06-28"


class NotionTokens(BaseModel):
    """Structured token response from Notion OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp, may be None if no expiry
    token_type: str = "bearer"
    bot_id: Optional[str] = None
    workspace_id: Optional[str] = None
    workspace_name: Optional[str] = None
    workspace_icon: Optional[str] = None
    duplicated_template_id: Optional[str] = None


class NotionWorkspaceInfo(BaseModel):
    """Workspace info from Notion OAuth"""

    workspace_id: str
    workspace_name: Optional[str] = None
    workspace_icon: Optional[str] = None
    bot_id: Optional[str] = None


def get_notion_client_config() -> Tuple[str, str]:
    """
    Get Notion OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("NOTION_CLIENT_ID")
    client_secret = os.environ.get("NOTION_CLIENT_SECRET")

    if not client_id:
        raise ValueError("NOTION_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("NOTION_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[NotionTokens, NotionWorkspaceInfo]:
    """
    Exchange authorization code for access and refresh tokens.

    Notion uses HTTP Basic Auth with client_id:client_secret for token exchange.

    Args:
        code: Authorization code from Notion OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (NotionTokens, NotionWorkspaceInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_notion_client_config()

    # Notion requires Basic auth with client_id:client_secret
    auth_string = f"{client_id}:{client_secret}"
    auth_header = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/json",
    }

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            NOTION_TOKEN_URL,
            json=body,
            headers=headers,
        )

        if token_response.status_code != 200:
            try:
                error_data = token_response.json()
                error_msg = error_data.get(
                    "message", error_data.get("error", "Unknown error")
                )
            except Exception:
                error_msg = f"HTTP {token_response.status_code}"
            logger.error(f"[NotionOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # Calculate expiry time if expires_in is provided
        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        tokens = NotionTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "bearer"),
            bot_id=token_data.get("bot_id"),
            workspace_id=token_data.get("workspace_id"),
            workspace_name=token_data.get("workspace_name"),
            workspace_icon=token_data.get("workspace_icon"),
            duplicated_template_id=token_data.get("duplicated_template_id"),
        )

        workspace_info = NotionWorkspaceInfo(
            workspace_id=token_data.get("workspace_id", "unknown"),
            workspace_name=token_data.get("workspace_name"),
            workspace_icon=token_data.get("workspace_icon"),
            bot_id=token_data.get("bot_id"),
        )

        logger.info(
            f"[NotionOAuth] Successfully exchanged code for tokens for workspace {workspace_info.workspace_name}"
        )
        return tokens, workspace_info


async def refresh_access_token(refresh_token: str) -> NotionTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New NotionTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails
    """
    client_id, client_secret = get_notion_client_config()

    # Notion requires Basic auth
    auth_string = f"{client_id}:{client_secret}"
    auth_header = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/json",
    }

    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            NOTION_TOKEN_URL,
            json=body,
            headers=headers,
        )

        if response.status_code != 200:
            error_data = None
            try:
                error_data = response.json()
                error_msg = error_data.get(
                    "message", error_data.get("error", "Unknown error")
                )
            except Exception:
                error_msg = f"HTTP {response.status_code}"
            logger.error(f"[NotionOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(error_data, dict):
                error_code = error_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        # Calculate new expiry time
        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        tokens = NotionTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "bearer"),
            bot_id=token_data.get("bot_id"),
            workspace_id=token_data.get("workspace_id"),
            workspace_name=token_data.get("workspace_name"),
        )

        logger.info("[NotionOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry (may be None)
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if no expiry set
    """
    if not expires_at:
        # Notion internal integration tokens don't expire
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[NotionOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_notion_auth_url(
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Notion OAuth authorization URL.

    Notion OAuth doesn't use scopes - permissions are selected by the user
    during authorization when they choose which pages to share.

    Args:
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_notion_client_config()

    from urllib.parse import urlencode

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "owner": "user",  # Required by Notion
        "state": state,
    }

    query_string = urlencode(params)
    return f"{NOTION_AUTH_URL}?{query_string}"
