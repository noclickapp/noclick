"""
Discord OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Discord API access.

Discord OAuth uses:
- Authorization URL: https://discord.com/oauth2/authorize
- Token URL: https://discord.com/api/oauth2/token
- Discord access tokens expire after ~7 days and need refresh

Documentation: https://discord.com/developers/docs/topics/oauth2
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DISCORD_AUTH_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/v10/users/@me"
DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordTokens(BaseModel):
    """Structured token response from Discord OAuth"""

    access_token: str
    refresh_token: str
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"
    # Populated when bot scope is requested — the guild the bot was installed into
    guild_id: Optional[str] = None
    guild_name: Optional[str] = None


class DiscordUserInfo(BaseModel):
    """User info from Discord"""

    id: str
    username: str
    discriminator: str
    email: Optional[str] = None
    avatar: Optional[str] = None
    global_name: Optional[str] = None


def get_discord_client_config() -> Tuple[str, str]:
    """
    Get Discord OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("DISCORD_CLIENT_ID")
    client_secret = os.environ.get("DISCORD_CLIENT_SECRET")

    if not client_id:
        raise ValueError("DISCORD_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("DISCORD_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[DiscordTokens, DiscordUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from Discord OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (DiscordTokens, DiscordUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_discord_client_config()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            DISCORD_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            logger.error(f"[DiscordOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[DiscordOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Calculate expiry time (Discord tokens expire in ~604800 seconds = 7 days)
        expires_in = token_data.get("expires_in", 604800)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        # Extract guild info (present when bot scope was requested)
        guild = token_data.get("guild") or {}
        tokens = DiscordTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
            guild_id=str(guild["id"]) if guild.get("id") else None,
            guild_name=guild.get("name"),
        )

        # Get user info
        userinfo_response = await client.get(
            DISCORD_USER_URL,
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
            },
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                f"[DiscordOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            user_info = DiscordUserInfo(
                id="0", username="unknown", discriminator="0000"
            )
        else:
            userinfo_data = userinfo_response.json()
            user_info = DiscordUserInfo(
                id=userinfo_data.get("id", "0"),
                username=userinfo_data.get("username", "unknown"),
                discriminator=userinfo_data.get("discriminator", "0000"),
                email=userinfo_data.get("email"),
                avatar=userinfo_data.get("avatar"),
                global_name=userinfo_data.get("global_name"),
            )

        logger.info(
            f"[DiscordOAuth] Successfully exchanged code for tokens for user {user_info.username}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> DiscordTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New DiscordTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails
    """
    client_id, client_secret = get_discord_client_config()

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
            DISCORD_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"[DiscordOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[DiscordOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(token_data, dict):
                error_code = token_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 604800)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        tokens = DiscordTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[DiscordOAuth] Successfully refreshed access token")
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
        return True  # No expiry set - treat as expired to be safe

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[DiscordOAuth] Error parsing expiry time: {e}")
        return True  # If we can't parse, treat as expired


def get_discord_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Discord OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_discord_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{DISCORD_AUTH_URL}?{query_string}"


# Standard scopes for Discord workflow operations
DISCORD_WORKFLOW_SCOPES = [
    "identify",  # Access user's username, avatar, etc.
    "email",  # Access user's email
    "guilds",  # Access list of user's guilds
    "connections",  # Access user's linked third-party accounts
    "gdm.join",  # Join users to group DM (rarely used)
]

# Bot scopes for direct channel access
DISCORD_BOT_SCOPES = [
    "bot",  # Bot user access
    "applications.commands",  # Slash commands
]
