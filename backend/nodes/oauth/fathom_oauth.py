"""
Fathom OAuth utility for token exchange and refresh.

Primary sources:
- https://developers.fathom.ai/oauth.md
- https://developers.fathom.ai/sdks/oauth.md
- Official SDK package `fathom-typescript@0.0.41`
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx
from pydantic import BaseModel

from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

FATHOM_OAUTH_AUTHORIZE_URL = "https://fathom.video/external/v1/oauth2/authorize"
FATHOM_OAUTH_TOKEN_URL = "https://fathom.video/external/v1/oauth2/token"


class FathomTokens(BaseModel):
    """Structured token response from Fathom OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str
    scope: Optional[str] = None
    token_type: str = "Bearer"


class FathomUserInfo(BaseModel):
    """Minimal user info carried with the exchanged credential."""

    id: str = "fathom_user"
    email: Optional[str] = None


def get_fathom_client_config() -> Tuple[str, str]:
    """Load Fathom OAuth client credentials from environment variables."""
    client_id = os.environ.get("FATHOM_CLIENT_ID")
    client_secret = os.environ.get("FATHOM_CLIENT_SECRET")

    if not client_id:
        raise ValueError("FATHOM_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("FATHOM_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Return True when the OAuth access token is expired or near expiry."""
    if not expires_at:
        return True

    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True

    return expiry <= datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes)


async def exchange_code_for_tokens(
    code: str, redirect_uri: str
) -> Tuple[FathomTokens, FathomUserInfo]:
    """Exchange an OAuth authorization code for access and refresh tokens."""
    client_id, client_secret = get_fathom_client_config()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(FATHOM_OAUTH_TOKEN_URL, data=data, headers=headers)

    if response.status_code != 200:
        try:
            error_data = response.json()
            error_msg = error_data.get("error_description") or error_data.get("error") or str(
                error_data
            )
        except Exception:
            error_msg = f"HTTP {response.status_code}"
        logger.error("[FathomOAuth] Token exchange failed: %s", error_msg)
        raise ValueError(f"Token exchange failed: {error_msg}")

    token_data = response.json()
    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    tokens = FathomTokens(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at.isoformat(),
        scope=token_data.get("scope"),
        token_type=token_data.get("token_type", "Bearer"),
    )
    return tokens, FathomUserInfo()


async def refresh_access_token(refresh_token: str) -> FathomTokens:
    """Refresh an expired Fathom OAuth access token."""
    client_id, client_secret = get_fathom_client_config()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(FATHOM_OAUTH_TOKEN_URL, data=data, headers=headers)

    if response.status_code != 200:
        try:
            error_data = response.json()
            error_msg = error_data.get("error_description") or error_data.get("error") or str(
                error_data
            )
        except Exception:
            error_msg = f"HTTP {response.status_code}"
        logger.error("[FathomOAuth] Token refresh failed: %s", error_msg)
        raise ValueError(f"Token refresh failed: {error_msg}")

    token_data = response.json()
    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    new_refresh_token = require_rotated_refresh_token(token_data, provider="fathom")

    return FathomTokens(
        access_token=token_data["access_token"],
        refresh_token=new_refresh_token,
        expires_at=expires_at.isoformat(),
        scope=token_data.get("scope"),
        token_type=token_data.get("token_type", "Bearer"),
    )
