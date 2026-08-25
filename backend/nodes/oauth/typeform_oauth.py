"""
Typeform OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Typeform API access.

Typeform OAuth uses:
- Authorization URL: https://api.typeform.com/oauth/authorize
- Token URL: https://api.typeform.com/oauth/token
- Access tokens expire after 1 week by default
- Refresh tokens are provided when 'offline' scope is included

Documentation: https://www.typeform.com/developers/get-started/applications/
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

TYPEFORM_AUTH_URL = "https://api.typeform.com/oauth/authorize"
TYPEFORM_TOKEN_URL = "https://api.typeform.com/oauth/token"


class TypeformTokens(BaseModel):
    """Structured token response from Typeform OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class TypeformUserInfo(BaseModel):
    """User info from Typeform"""

    id: str = "typeform_user"
    email: Optional[str] = None


def get_typeform_client_config() -> Tuple[str, str]:
    """
    Get Typeform OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("TYPEFORM_CLIENT_ID")
    client_secret = os.environ.get("TYPEFORM_CLIENT_SECRET")

    if not client_id:
        raise ValueError("TYPEFORM_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("TYPEFORM_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[TypeformTokens, TypeformUserInfo]:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from Typeform OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (TypeformTokens, TypeformUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_typeform_client_config()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # Log request details (redact secret)
    logger.info(
        f"[TypeformOAuth] Exchanging code for tokens with redirect_uri: {redirect_uri}"
    )

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            TYPEFORM_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            # Record the status without copying the provider response
            logger.error(
                f"[TypeformOAuth] Token exchange failed with status {token_response.status_code}"
            )
            try:
                error_data = token_response.json()
                error_msg = error_data.get(
                    "error_description",
                    error_data.get(
                        "error",
                        f"HTTP {token_response.status_code}: HTTP {token_response.status_code}",
                    ),
                )
            except Exception as e:
                logger.error(f"[TypeformOAuth] Failed to parse error JSON: {e}")
                error_msg = f"HTTP {token_response.status_code}: HTTP {token_response.status_code}"

            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # Calculate expiry time (default is 1 week = 604800 seconds)
        expires_in = token_data.get("expires_in", 604800)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = TypeformTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Typeform doesn't provide a separate user info endpoint in the docs
        # We'll use a generic user info object
        user_info = TypeformUserInfo(
            id="typeform_user",
            email=None,
        )

        logger.info(f"[TypeformOAuth] Successfully exchanged code for tokens")
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> TypeformTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New TypeformTokens with updated access_token, refresh_token, and expires_at

    Raises:
        ValueError: If refresh fails (token revoked, etc.)

    Note:
        Typeform invalidates the old refresh token and returns a new one
    """
    client_id, client_secret = get_typeform_client_config()

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    logger.info("[TypeformOAuth] Refreshing access token")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            TYPEFORM_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            # Record the status without copying the provider response
            logger.error(
                f"[TypeformOAuth] Token refresh failed with status {response.status_code}"
            )
            error_code = None
            try:
                error_data = response.json()
                if isinstance(error_data, dict):
                    error_code = error_data.get("error")
                error_msg = error_data.get(
                    "error_description",
                    error_data.get(
                        "error", f"HTTP {response.status_code}: HTTP {response.status_code}"
                    ),
                )
            except Exception as e:
                logger.error(f"[TypeformOAuth] Failed to parse error JSON: {e}")
                error_msg = f"HTTP {response.status_code}: HTTP {response.status_code}"

            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 604800)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = TypeformTokens(
            access_token=token_data["access_token"],
            refresh_token=require_rotated_refresh_token(token_data, provider="typeform"),
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[TypeformOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: str, buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon
    """
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[TypeformOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_typeform_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Typeform OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_typeform_client_config()

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
    return f"{TYPEFORM_AUTH_URL}?{query_string}"


# Standard scopes for full Typeform access.
#
# `offline` is not an API permission — it is what makes Typeform return a
# refresh token ("Always add the offline scope to receive a refresh token",
# https://www.typeform.com/developers/get-started/scopes/). Without it the
# access token simply expires and the credential is dead rather than refreshed.
# It is authorize-URL-only — Typeform's app registration has no scopes field —
# but a legacy app configured for UNLIMITED token expiry rejects the exchange
# with "this kind of access tokens cannot have refresh tokens".
TYPEFORM_FULL_SCOPES = [
    "offline",
    "accounts:read",
    "forms:read",
    "forms:write",
    "images:read",
    "images:write",
    "themes:read",
    "themes:write",
    "responses:read",
    "responses:write",
    "webhooks:read",
    "webhooks:write",
    "workspaces:read",
    "workspaces:write",
]
