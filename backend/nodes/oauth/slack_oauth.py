"""
Slack OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Slack workspace access.

Slack OAuth uses:
- Authorization URL: https://slack.com/oauth/v2/authorize
- Token URL: https://slack.com/api/oauth.v2.access
- Slack access tokens do expire and require refresh_token for renewal

Documentation: https://api.slack.com/authentication/oauth-v2
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

SLACK_AUTH_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_AUTH_TEST_URL = "https://slack.com/api/auth.test"


class SlackTokens(BaseModel):
    """Structured token response from Slack OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "bot"
    scope: str
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    bot_user_id: Optional[str] = None
    app_id: Optional[str] = None
    # ``authed_user.access_token`` from Slack's OAuth v2 exchange — the user
    # token (xoxp-) for the authorizing user. Node execution uses it for write
    # ops set to ``send_as=user`` (the default) and for the channel-scoped read
    # ops that are hard-coded to the user token (so reads see the channels the
    # user can, not just those the bot was invited to). It's also what lets
    # automated trigger tests post messages as a real user, which Slack delivers
    # to its own Event Subscriptions (bot-self messages are dropped before
    # delivery).
    user_access_token: Optional[str] = None
    user_refresh_token: Optional[str] = None
    user_expires_at: Optional[str] = None
    user_id_xoxp: Optional[str] = None


class SlackWorkspaceInfo(BaseModel):
    """Workspace info from Slack"""

    team_id: str
    team_name: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    bot_user_id: Optional[str] = None


def get_slack_client_config(
    custom_client_id: Optional[str] = None, custom_client_secret: Optional[str] = None
) -> Tuple[str, str]:
    """
    Get Slack OAuth client configuration.
    Uses custom credentials if provided, otherwise falls back to environment variables.

    Args:
        custom_client_id: Optional custom OAuth client ID
        custom_client_secret: Optional custom OAuth client secret

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required credentials are not available
    """
    # Use custom credentials if provided
    if custom_client_id and custom_client_secret:
        return custom_client_id, custom_client_secret

    # Fall back to environment variables
    client_id = os.environ.get("SLACK_CLIENT_ID")
    client_secret = os.environ.get("SLACK_CLIENT_SECRET")

    if not client_id:
        raise ValueError("SLACK_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("SLACK_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[SlackTokens, SlackWorkspaceInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from Slack OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id: Optional custom OAuth client ID (uses env if not provided)
        client_secret: Optional custom OAuth client secret (uses env if not provided)

    Returns:
        Tuple of (SlackTokens, SlackWorkspaceInfo)

    Raises:
        ValueError: If token exchange fails
    """
    resolved_client_id, resolved_client_secret = get_slack_client_config(
        client_id, client_secret
    )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "client_id": resolved_client_id,
        "client_secret": resolved_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            SLACK_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            logger.error(f"[SlackOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response (Slack returns 200 even on errors)
        if not token_data.get("ok", False):
            error_msg = token_data.get("error", "Unknown error")
            logger.error(f"[SlackOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Extract access token (can be in authed_user or at top level for bot tokens)
        access_token = token_data.get("access_token")
        if not access_token and "authed_user" in token_data:
            access_token = token_data["authed_user"].get("access_token")

        if not access_token:
            raise ValueError("No access token in response")

        # Calculate expiry time if provided
        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        # Extract team info
        team_info = token_data.get("team", {})
        team_id = team_info.get("id") or token_data.get("team_id")
        team_name = team_info.get("name") or token_data.get("team_name", "")

        # Capture the user token (authed_user.access_token, xoxp-) alongside
        # the bot token when Slack returns it. Production runtime keeps using
        # ``access_token`` (bot xoxb-) — the user token is for trigger tests
        # that need to post as a real user so the bot's own message-event
        # subscription catches the delivery (Slack drops same-app bot-self
        # messages before Event Subscriptions delivery).
        authed_user = token_data.get("authed_user") or {}
        # If the bot token IS the authed_user one (legacy flow with no separate
        # bot installation), don't duplicate it as a user token.
        user_access_token = authed_user.get("access_token")
        if user_access_token and user_access_token == access_token:
            user_access_token = None
        user_expires_at = None
        if user_access_token and "expires_in" in authed_user:
            user_expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=authed_user["expires_in"])
            ).isoformat()

        tokens = SlackTokens(
            access_token=access_token,
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "bot"),
            scope=token_data.get("scope", ""),
            team_id=team_id,
            team_name=team_name,
            bot_user_id=token_data.get("bot_user_id"),
            app_id=token_data.get("app_id"),
            user_access_token=user_access_token,
            user_refresh_token=authed_user.get("refresh_token") if user_access_token else None,
            user_expires_at=user_expires_at,
            user_id_xoxp=authed_user.get("id") if user_access_token else None,
        )

        # Get more detailed workspace info via auth.test
        workspace_info = SlackWorkspaceInfo(
            team_id=team_id or "unknown",
            team_name=team_name or "Unknown Workspace",
            bot_user_id=token_data.get("bot_user_id"),
        )

        # Optionally fetch more info via auth.test
        try:
            auth_test_response = await client.post(
                SLACK_AUTH_TEST_URL,
                headers={
                    "Authorization": f"Bearer {tokens.access_token}",
                },
            )
            if auth_test_response.status_code == 200:
                auth_data = auth_test_response.json()
                if auth_data.get("ok"):
                    workspace_info = SlackWorkspaceInfo(
                        team_id=auth_data.get("team_id", team_id or "unknown"),
                        team_name=auth_data.get(
                            "team", team_name or "Unknown Workspace"
                        ),
                        user_id=auth_data.get("user_id"),
                        user_name=auth_data.get("user"),
                        bot_user_id=auth_data.get("bot_id")
                        or token_data.get("bot_user_id"),
                    )
        except Exception as e:
            logger.warning(f"[SlackOAuth] Failed to get auth.test info: {e}")

        logger.info(
            f"[SlackOAuth] Successfully exchanged code for tokens for workspace {workspace_info.team_name}"
        )
        return tokens, workspace_info


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> SlackTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials
        client_id: Optional custom OAuth client ID (uses env if not provided)
        client_secret: Optional custom OAuth client secret (uses env if not provided)

    Returns:
        New SlackTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails
    """
    resolved_client_id, resolved_client_secret = get_slack_client_config(
        client_id, client_secret
    )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "client_id": resolved_client_id,
        "client_secret": resolved_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            SLACK_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"[SlackOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        # Check for error in response
        if not token_data.get("ok", False):
            error_msg = token_data.get("error", "Unknown error")
            logger.error(f"[SlackOAuth] Token refresh failed: {error_msg}")
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

        tokens = SlackTokens(
            access_token=token_data["access_token"],
            refresh_token=require_rotated_refresh_token(token_data, provider="slack"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "bot"),
            scope=token_data.get("scope", ""),
            team_id=token_data.get("team_id"),
            team_name=token_data.get("team_name"),
            bot_user_id=token_data.get("bot_user_id"),
            app_id=token_data.get("app_id"),
        )

        logger.info("[SlackOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry (None if non-expiring)
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if no expiry or still valid
    """
    if not expires_at:
        # No expiry set - assume token doesn't expire
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[SlackOAuth] Error parsing expiry time: {e}")
        return False


def get_slack_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    user_scopes: Optional[list[str]] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> str:
    """
    Generate Slack OAuth authorization URL.

    Args:
        scopes: List of bot OAuth scopes to request
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        user_scopes: Optional list of user scopes (for user token in addition to bot token)
        client_id: Optional custom OAuth client ID (uses env if not provided)
        client_secret: Optional custom OAuth client secret (uses env if not provided)

    Returns:
        Full authorization URL to redirect user to
    """
    resolved_client_id, _ = get_slack_client_config(client_id, client_secret)

    # Build query parameters
    params = {
        "client_id": resolved_client_id,
        "redirect_uri": redirect_uri,
        "scope": ",".join(scopes),
        "state": state,
    }

    if user_scopes:
        params["user_scope"] = ",".join(user_scopes)

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{SLACK_AUTH_URL}?{query_string}"


async def validate_token(
    access_token: str,
) -> Tuple[bool, Optional[SlackWorkspaceInfo]]:
    """
    Validate an access token by calling auth.test.

    Args:
        access_token: The Slack access token to validate

    Returns:
        Tuple of (is_valid, workspace_info or None)
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                SLACK_AUTH_TEST_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                },
            )

            if response.status_code != 200:
                return False, None

            data = response.json()
            if not data.get("ok"):
                return False, None

            workspace_info = SlackWorkspaceInfo(
                team_id=data.get("team_id", "unknown"),
                team_name=data.get("team", "Unknown Workspace"),
                user_id=data.get("user_id"),
                user_name=data.get("user"),
                bot_user_id=data.get("bot_id"),
            )
            return True, workspace_info

        except Exception as e:
            logger.error(f"[SlackOAuth] Token validation failed: {e}")
            return False, None


# Standard scopes for Slack workflow automation (bot scopes only - must match app config)
SLACK_WORKFLOW_SCOPES = [
    "channels:read",  # View basic channel info
    "channels:manage",  # Manage channels (replaces deprecated channels:write)
    "channels:history",  # View messages in public channels
    "chat:write",  # Send messages
    "users:read",  # View users
    "users:read.email",  # View user emails
    "reactions:read",  # View reactions
    "reactions:write",  # Add/remove reactions
    "pins:read",  # View pinned items
    "pins:write",  # Pin/unpin items
    "files:read",  # View files
    "files:write",  # Upload/delete files
    "bookmarks:read",  # View bookmarks
    "bookmarks:write",  # Add/edit/remove bookmarks
    "usergroups:read",  # View user groups
    "usergroups:write",  # Manage user groups
    "dnd:read",  # View DND status (dnd:write is user-only)
    "emoji:read",  # View custom emoji
    "team:read",  # View workspace info
    "groups:read",  # View private channels
    "groups:history",  # View messages in private channels
    "im:read",  # View direct messages
    "im:write",  # Manage DMs
    "im:history",  # View DM message history
    "mpim:read",  # View group DMs
    "mpim:history",  # View group DM message history
]

# Minimal scopes for read-only access
SLACK_READONLY_SCOPES = [
    "channels:read",
    "channels:history",
    "users:read",
    "reactions:read",
    "pins:read",
    "files:read",
    "team:read",
]
