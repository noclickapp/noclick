"""
Canva OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 with PKCE flow for Canva Connect API access.

Canva OAuth uses:
- Authorization URL: https://www.canva.com/api/oauth/authorize
- Token URL: https://api.canva.com/rest/v1/oauth/token
- Access tokens expire after 4 hours
- Refresh tokens are provided and should be used to get new access tokens
- Uses PKCE (Proof Key for Code Exchange) with SHA-256

Documentation: https://www.canva.dev/docs/connect/authentication/
"""

import os
import logging
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel
from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

CANVA_AUTH_URL = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_USERINFO_URL = "https://api.canva.com/rest/v1/users/me/profile"


class CanvaTokens(BaseModel):
    """Structured token response from Canva OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class CanvaUserInfo(BaseModel):
    """User info from Canva"""

    user_id: str
    display_name: Optional[str] = None


def get_canva_client_config() -> Tuple[str, str]:
    """
    Get Canva OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("CANVA_CLIENT_ID")
    client_secret = os.environ.get("CANVA_CLIENT_SECRET")

    if not client_id:
        raise ValueError("CANVA_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("CANVA_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def generate_pkce_verifier() -> str:
    """
    Generate a PKCE code verifier.

    Returns:
        A cryptographically random code verifier string (43-128 chars)
    """
    return secrets.token_urlsafe(64)[:128]


def generate_pkce_challenge(verifier: str) -> str:
    """
    Generate a PKCE code challenge from a code verifier.

    Args:
        verifier: The code verifier string

    Returns:
        Base64url-encoded SHA256 hash of the verifier
    """
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> Tuple[CanvaTokens, CanvaUserInfo]:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from Canva OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        code_verifier: PKCE code verifier used during authorization

    Returns:
        Tuple of (CanvaTokens, CanvaUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_canva_client_config()

    # Prepare Basic auth header (required by Canva)
    auth_string = f"{client_id}:{client_secret}"
    auth_header = base64.b64encode(auth_string.encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            CANVA_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            error_data = token_response.json() if token_response.text else {}
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[CanvaOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # Calculate expiry time (Canva tokens expire in 4 hours = 14400 seconds)
        expires_in = token_data.get("expires_in", 14400)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = CanvaTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info
        userinfo_response = await client.get(
            CANVA_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens.access_token}"},
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                f"[CanvaOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            # Don't fail - user info is optional
            user_info = CanvaUserInfo(user_id="unknown")
        else:
            userinfo_data = userinfo_response.json()
            user_info = CanvaUserInfo(
                user_id=userinfo_data.get("user_id", "unknown"),
                display_name=userinfo_data.get("display_name"),
            )

        logger.info(
            f"[CanvaOAuth] Successfully exchanged code for tokens for user {user_info.user_id}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> CanvaTokens:
    """
    Refresh an expired access token using the refresh token.

    Note: Canva refresh tokens can only be used once. The response will
    contain a new refresh token that should replace the old one.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New CanvaTokens with updated access_token, refresh_token, and expires_at

    Raises:
        ValueError: If refresh fails (token revoked, etc.)
    """
    client_id, client_secret = get_canva_client_config()

    # Prepare Basic auth header
    auth_string = f"{client_id}:{client_secret}"
    auth_header = base64.b64encode(auth_string.encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            CANVA_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[CanvaOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(error_data, dict):
                error_code = error_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 14400)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = CanvaTokens(
            access_token=token_data["access_token"],
            refresh_token=require_rotated_refresh_token(token_data, provider="canva"),
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[CanvaOAuth] Successfully refreshed access token")
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
        logger.error(f"[CanvaOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_canva_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    code_challenge: str,
) -> str:
    """
    Generate Canva OAuth authorization URL with PKCE.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        code_challenge: PKCE code challenge (generated from code_verifier)

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_canva_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{CANVA_AUTH_URL}?{query_string}"


# Standard scopes for Canva workflow automation
CANVA_FULL_SCOPES = [
    "asset:read",
    "asset:write",
    "design:meta:read",
    "design:content:read",
    "design:content:write",
    "folder:read",
    "folder:write",
    "profile:read",
]
