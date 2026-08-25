"""
Calendly OAuth 2.0 utility for token exchange and refresh.

Calendly uses a standard OAuth 2.0 authorization_code flow on a dedicated auth
host (there is ONE shared NoClick app — client_id/secret from env):
- Authorization URL: https://auth.calendly.com/oauth/authorize
- Token URL:         https://auth.calendly.com/oauth/token
- Revocation URL:    https://auth.calendly.com/oauth/revoke
- User info:         GET https://api.calendly.com/users/me

Access tokens expire after ~2 hours. Refresh tokens are SINGLE-USE and rotate on
every refresh (Calendly is enforcing OAuth 2.1 rotation) — the previous refresh
token is revoked and a NEW one is returned that MUST be persisted, or the
credential bricks. This is why refresh_access_token goes through
``require_rotated_refresh_token`` (same contract as Slack/Linear/Twitter).

Identity for the credential display name comes from /users/me (name + email).

Documentation: https://developer.calendly.com/api-docs/3cefb59b832eb-calendly-o-auth-2-0
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

CALENDLY_AUTH_URL = "https://auth.calendly.com/oauth/authorize"
CALENDLY_TOKEN_URL = "https://auth.calendly.com/oauth/token"
CALENDLY_REVOKE_URL = "https://auth.calendly.com/oauth/revoke"
CALENDLY_USERINFO_URL = "https://api.calendly.com/users/me"


class CalendlyTokens(BaseModel):
    """Structured token response from Calendly OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "Bearer"
    scope: str = ""
    # Calendly returns the owner/organization URIs in the token response; they are
    # the URI-as-ID handles every subsequent API call needs, so capture them.
    owner: Optional[str] = None
    organization: Optional[str] = None


class CalendlyUserInfo(BaseModel):
    """Identity for the credential display name (from /users/me)."""

    id: str
    name: str
    email: Optional[str] = None
    uri: Optional[str] = None
    organization: Optional[str] = None


def get_calendly_client_config() -> Tuple[str, str]:
    """Return (client_id, client_secret) from environment.

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("CALENDLY_CLIENT_ID")
    client_secret = os.environ.get("CALENDLY_CLIENT_SECRET")
    if not client_id:
        raise ValueError("CALENDLY_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("CALENDLY_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def _expires_at(token_data: dict) -> Optional[str]:
    if "expires_in" not in token_data:
        return None
    return (
        datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
    ).isoformat()


def _tokens_from_response(token_data: dict, *, rotate: bool) -> CalendlyTokens:
    refresh = (
        require_rotated_refresh_token(token_data, provider="calendly")
        if rotate
        else token_data.get("refresh_token")
    )
    return CalendlyTokens(
        access_token=token_data["access_token"],
        refresh_token=refresh,
        expires_at=_expires_at(token_data),
        token_type=token_data.get("token_type", "Bearer"),
        scope=token_data.get("scope", ""),
        owner=token_data.get("owner"),
        organization=token_data.get("organization"),
    )


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[CalendlyTokens, CalendlyUserInfo]:
    """Exchange authorization code for tokens, then fetch user info.

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_calendly_client_config()

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_response = await client.post(CALENDLY_TOKEN_URL, data=data, headers=headers)
        if token_response.status_code != 200:
            logger.error(f"[CalendlyOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()
        if "error" in token_data:
            error_msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            logger.error(f"[CalendlyOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # First issue: the refresh token is present but not yet "rotated", so don't
        # enforce rotation on the initial exchange.
        tokens = _tokens_from_response(token_data, rotate=False)
        user_info = await _get_user_info(client, tokens.access_token)
        # Prefer the token response's owner/organization; fall back to /users/me.
        if not tokens.owner:
            tokens.owner = user_info.uri
        if not tokens.organization:
            tokens.organization = user_info.organization

        logger.info(f"[CalendlyOAuth] Successfully exchanged code for tokens for {user_info.name}")
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> CalendlyUserInfo:
    """Fetch identity from Calendly's /users/me endpoint."""
    response = await client.get(
        CALENDLY_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if response.status_code != 200:
        logger.warning(f"[CalendlyOAuth] Failed to get user info: HTTP {response.status_code}")
        return CalendlyUserInfo(id="unknown", name="Calendly User")

    resource = (response.json() or {}).get("resource", {})
    return CalendlyUserInfo(
        id=str(resource.get("uri") or "unknown"),
        name=resource.get("name") or resource.get("email") or "Calendly User",
        email=resource.get("email"),
        uri=resource.get("uri"),
        organization=resource.get("current_organization"),
    )


async def refresh_access_token(refresh_token: str) -> CalendlyTokens:
    """Refresh an expired access token using the (single-use, rotating) refresh token.

    Calendly rotates the refresh token on every successful refresh and revokes the
    previous one, so the returned refresh_token MUST be persisted — enforced via
    ``require_rotated_refresh_token`` (raises if the response omits a new one
    rather than silently reusing the consumed token).

    Raises:
        ValueError: If refresh fails
    """
    client_id, client_secret = get_calendly_client_config()

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(CALENDLY_TOKEN_URL, data=data, headers=headers)
        if response.status_code != 200:
            logger.error(f"[CalendlyOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()
        if "error" in token_data:
            error_msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            logger.error(f"[CalendlyOAuth] Token refresh failed: {error_msg}")
            error_code = token_data.get("error") if isinstance(token_data, dict) else None
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        tokens = _tokens_from_response(token_data, rotate=True)
        logger.info("[CalendlyOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Return True if the access token is expired or expiring within the buffer."""
    if not expires_at:
        return False
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[CalendlyOAuth] Error parsing expiry time: {e}")
        return True


def get_calendly_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Calendly OAuth authorization URL.

    Calendly's authorize endpoint takes the standard params. Scope handling: the
    param is sent ONLY when a non-empty scope list is supplied. Calendly's
    granular-scope model is new (2026) and the exact scope-token strings are not
    publicly documented, so ``CALENDLY_DEFAULT_SCOPES`` is intentionally empty —
    the shared NoClick app's registered access governs, and sending a guessed
    scope string would risk an ``invalid_scope`` at connect. Populate the list
    (here + x-oauth-scopes) once the exact strings are confirmed against a live
    Calendly app.
    """
    cid = client_id or get_calendly_client_config()[0]
    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    return f"{CALENDLY_AUTH_URL}?{urlencode(params)}"


# Intentionally empty — see get_calendly_auth_url. Calendly's 2026 granular-scope
# token strings aren't publicly documented; the registered app's access governs.
CALENDLY_DEFAULT_SCOPES: list[str] = []
