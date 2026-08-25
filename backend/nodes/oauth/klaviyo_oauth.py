"""
Klaviyo OAuth 2.0 (PKCE) utility for token exchange and refresh.

Klaviyo requires PKCE (S256) for all client types. The authorize step lives in
the frontend route (it generates the code_verifier/challenge and round-trips the
verifier through state); this module handles the server-side token exchange +
refresh. Confidential clients authenticate to the token endpoint with HTTP Basic
(client_id:client_secret); the PKCE code_verifier is sent in the body.

- Authorize: https://www.klaviyo.com/oauth/authorize
- Token:     https://a.klaviyo.com/oauth/token
- Access tokens expire ~1 hour; refresh tokens are long-lived (die after 90d idle).

Klaviyo OAuth is for approved marketplace/public apps; the Private API Key
credential is the primary, unrestricted path.

Docs: https://developers.klaviyo.com/en/docs/set_up_oauth
"""

import base64
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

KLAVIYO_AUTHORIZE_URL = "https://www.klaviyo.com/oauth/authorize"
KLAVIYO_TOKEN_URL = "https://a.klaviyo.com/oauth/token"
KLAVIYO_REVOKE_URL = "https://a.klaviyo.com/oauth/revoke"


class KlaviyoTokens(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601
    token_type: str = "Bearer"


def get_klaviyo_client_config() -> Tuple[str, str]:
    client_id = os.environ.get("KLAVIYO_CLIENT_ID")
    client_secret = os.environ.get("KLAVIYO_CLIENT_SECRET")
    if not client_id:
        raise ValueError("KLAVIYO_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("KLAVIYO_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def _resolve_client(client_id: Optional[str], client_secret: Optional[str]) -> Tuple[str, str]:
    if client_id and client_secret:
        return client_id, client_secret
    return get_klaviyo_client_config()


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _tokens_from_response(token_data: dict) -> KlaviyoTokens:
    expires_at = None
    if "expires_in" in token_data:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])).isoformat()
    return KlaviyoTokens(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at,
        token_type=token_data.get("token_type", "Bearer"),
    )


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> KlaviyoTokens:
    """Exchange an authorization code (+ PKCE verifier) for tokens."""
    cid, csecret = _resolve_client(client_id, client_secret)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            KLAVIYO_TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": _basic_auth(cid, csecret)},
        )
        if resp.status_code != 200:
            logger.error(f"[KlaviyoOAuth] Token exchange failed: HTTP {resp.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {resp.status_code}")
        token_data = resp.json()
        if "error" in token_data:
            raise ValueError(f"Token exchange failed: {token_data.get('error_description', token_data['error'])}")
        logger.info("[KlaviyoOAuth] Exchanged code for tokens")
        return _tokens_from_response(token_data)


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> KlaviyoTokens:
    """Refresh an expired access token. Klaviyo access tokens live ~1 hour."""
    cid, csecret = _resolve_client(client_id, client_secret)
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            KLAVIYO_TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": _basic_auth(cid, csecret)},
        )
        if resp.status_code != 200:
            logger.error(f"[KlaviyoOAuth] Token refresh failed: HTTP {resp.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {resp.status_code}")
        token_data = resp.json()
        if "error" in token_data:
            error_code = token_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {token_data.get('error_description', error_code)}")
        tokens = _tokens_from_response(token_data)
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token  # keep existing if not rotated
        logger.info("[KlaviyoOAuth] Refreshed access token")
        return tokens


async def revoke_token(
    token: str,
    token_type_hint: str = "refresh_token",
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> bool:
    """Revoke an OAuth token at Klaviyo (RFC 7009).

    Called when a user disconnects the Klaviyo credential in NoClick so the app
    stops appearing as installed on Klaviyo's side. Revoking the refresh token
    invalidates the whole grant (access + refresh). Best-effort: returns True on
    a 2xx and never raises — a failed revoke must not block credential deletion.
    """
    if not token:
        return False
    try:
        cid, csecret = _resolve_client(client_id, client_secret)
    except ValueError as e:
        logger.warning(f"[KlaviyoOAuth] Cannot revoke token, client not configured: {e}")
        return False
    data = {"token": token, "token_type_hint": token_type_hint}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                KLAVIYO_REVOKE_URL, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": _basic_auth(cid, csecret)},
            )
        if 200 <= resp.status_code < 300:
            logger.info("[KlaviyoOAuth] Revoked token")
            return True
        logger.warning(f"[KlaviyoOAuth] Token revoke returned {resp.status_code}: HTTP {resp.status_code}")
        return False
    except Exception as e:
        logger.warning(f"[KlaviyoOAuth] Token revoke failed: {e}")
        return False


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    if not expires_at:
        return False
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[KlaviyoOAuth] Error parsing expiry time: {e}")
        return False


def get_klaviyo_auth_url(scopes: list[str], state: str, redirect_uri: str,
                         code_challenge: str, client_id: Optional[str] = None) -> str:
    """Generate the Klaviyo OAuth authorization URL (PKCE S256)."""
    cid = client_id or get_klaviyo_client_config()[0]
    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{KLAVIYO_AUTHORIZE_URL}?{urlencode(params)}"


KLAVIYO_DEFAULT_SCOPES = ["accounts:read", "profiles:read", "profiles:write", "lists:read", "lists:write"]
