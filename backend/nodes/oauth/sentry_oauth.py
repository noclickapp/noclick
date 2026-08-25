"""
Sentry OAuth 2.0 utility for token exchange and refresh.

Sentry supports a standard OAuth 2.0 authorization_code flow via an OAuth
Application (there is ONE shared NoClick app — client_id/secret from env):
- Authorization URL: https://sentry.io/oauth/authorize/
- Token URL:         https://sentry.io/oauth/token/

Access tokens last ~30 days; the token response carries a ``refresh_token`` used
to mint a new access token via ``grant_type=refresh_token``. Sentry returns a
fresh refresh token on refresh; it is persisted when present (rotation is not
strictly enforced here since Sentry's generic OAuth app is not documented as
single-use — the previous token is kept as a fallback so a non-rotating response
can't brick the credential).

Identity for the credential display name comes from the token response's ``user``
object, falling back to the first accessible organization.

Docs: https://docs.sentry.io/api/auth/
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

SENTRY_AUTH_URL = "https://sentry.io/oauth/authorize/"
SENTRY_TOKEN_URL = "https://sentry.io/oauth/token/"

# Broad scope set covering the node's read + write operations. Sentry has no
# dedicated alerts scope — alert endpoints ride project/org scopes.
SENTRY_DEFAULT_SCOPES = [
    "org:read", "org:write",
    "project:read", "project:write", "project:admin", "project:releases",
    "team:read", "team:write", "team:admin",
    "member:read", "member:write",
    "event:read", "event:write", "event:admin",
]


class SentryTokens(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601
    token_type: str = "bearer"
    scope: str = ""


class SentryUserInfo(BaseModel):
    id: str
    name: str
    email: Optional[str] = None


def get_sentry_client_config() -> Tuple[str, str]:
    """Return (client_id, client_secret) from environment."""
    client_id = os.environ.get("SENTRY_CLIENT_ID")
    client_secret = os.environ.get("SENTRY_CLIENT_SECRET")
    if not client_id:
        raise ValueError("SENTRY_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("SENTRY_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def _expires_at(token_data: dict) -> Optional[str]:
    if token_data.get("expires_at"):
        return str(token_data["expires_at"])
    if "expires_in" not in token_data:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))).isoformat()


def _tokens_from_response(
    token_data: dict, *, prev_refresh: Optional[str] = None, require_rotation: bool = False
) -> SentryTokens:
    # Sentry rotates its refresh token single-use and invalidates the prior
    # access token on every refresh (empirically verified 2026-07-31). On the
    # REFRESH path we therefore REQUIRE a rotated token rather than falling back
    # to the consumed one — keeping the consumed token would brick the
    # credential the next time it's used (the F05 failure class).
    if require_rotation:
        refresh_token = require_rotated_refresh_token(token_data, provider="sentry")
    else:
        refresh_token = token_data.get("refresh_token") or prev_refresh
    return SentryTokens(
        access_token=token_data["access_token"],
        refresh_token=refresh_token,
        expires_at=_expires_at(token_data),
        token_type=token_data.get("token_type", "bearer"),
        scope=token_data.get("scope", ""),
    )


def _user_from_response(token_data: dict) -> SentryUserInfo:
    user = token_data.get("user") or {}
    return SentryUserInfo(
        id=str(user.get("id") or "unknown"),
        name=user.get("name") or user.get("email") or "Sentry User",
        email=user.get("email"),
    )


async def exchange_code_for_tokens(code: str, redirect_uri: str) -> Tuple[SentryTokens, SentryUserInfo]:
    """Exchange an authorization code for tokens (+ identity)."""
    client_id, client_secret = get_sentry_client_config()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(SENTRY_TOKEN_URL, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
        if resp.status_code != 200:
            logger.error(f"[SentryOAuth] Token exchange failed: HTTP {resp.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {resp.status_code}")
        token_data = resp.json()
        if "error" in token_data:
            msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            raise ValueError(f"Token exchange failed: {msg}")
        tokens = _tokens_from_response(token_data)
        user_info = _user_from_response(token_data)
        logger.info(f"[SentryOAuth] Exchanged code for tokens ({user_info.name})")
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> SentryTokens:
    """Refresh the access token using the refresh token."""
    client_id, client_secret = get_sentry_client_config()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(SENTRY_TOKEN_URL, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
        if resp.status_code != 200:
            logger.error(f"[SentryOAuth] Token refresh failed: HTTP {resp.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {resp.status_code}")
        token_data = resp.json()
        if "error" in token_data:
            msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            raise ValueError(f"Token refresh failed: {msg}")
        tokens = _tokens_from_response(token_data, require_rotation=True)
        logger.info("[SentryOAuth] Refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry
    except (ValueError, TypeError):
        return True


def get_sentry_auth_url(scopes: list, state: str, redirect_uri: str, client_id: Optional[str] = None) -> str:
    """Build the Sentry OAuth authorization URL."""
    cid = client_id or get_sentry_client_config()[0]
    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(scopes or SENTRY_DEFAULT_SCOPES),
    }
    return f"{SENTRY_AUTH_URL}?{urlencode(params)}"
