"""
Threads OAuth utility for token exchange and refresh.

The Threads API (graph.threads.net) uses its OWN OAuth flow and app credentials
— a Threads user access token is app-scoped and is NOT interchangeable with a
Facebook/Instagram Graph API token. Flow:

  1. Authorize:  https://threads.net/oauth/authorize (browser)
  2. Exchange code -> short-lived token (1h):
       POST https://graph.threads.net/oauth/access_token (grant_type=authorization_code)
  3. Short-lived -> long-lived token (60d):
       GET  https://graph.threads.net/access_token (grant_type=th_exchange_token)
  4. Refresh long-lived (extends 60d, token must be >=24h old):
       GET  https://graph.threads.net/refresh_access_token (grant_type=th_refresh_token)

Only steps 2/3 use the app secret (server-side). Threads does not use
appsecret_proof on API calls.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional, List
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

THREADS_API_BASE = "https://graph.threads.net"
THREADS_AUTHORIZE_URL = "https://threads.net/oauth/authorize"
THREADS_TOKEN_URL = f"{THREADS_API_BASE}/oauth/access_token"
THREADS_LONG_LIVED_URL = f"{THREADS_API_BASE}/access_token"
THREADS_REFRESH_URL = f"{THREADS_API_BASE}/refresh_access_token"


class ThreadsTokens(BaseModel):
    """Structured token response from the Threads OAuth flow."""

    access_token: str
    expires_at: str  # ISO 8601 timestamp
    token_type: str = "Bearer"
    threads_user_id: Optional[str] = None


class ThreadsAccountInfo(BaseModel):
    """Basic profile metadata for a connected Threads account."""

    threads_user_id: Optional[str] = None
    username: Optional[str] = None
    name: Optional[str] = None


def get_threads_client_config() -> Tuple[str, str]:
    """Return the Threads app (client_id, client_secret) from the environment.

    The Threads use case generates a Threads App ID/Secret distinct from the
    app's Facebook App ID/Secret — these are the ones that must be used here.
    """
    client_id = os.environ.get("THREADS_CLIENT_ID") or os.environ.get("THREADS_APP_ID")
    client_secret = os.environ.get("THREADS_CLIENT_SECRET") or os.environ.get("THREADS_APP_SECRET")
    if not client_id:
        raise ValueError("THREADS_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("THREADS_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def get_threads_auth_url(scopes: List[str], state: str, redirect_uri: str) -> str:
    """Generate the Threads OAuth authorization URL."""
    client_id, _ = get_threads_client_config()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(scopes),
        "state": state,
    }
    query_string = "&".join(
        f'{k}={httpx.URL("", params={k: v}).params[k]}' for k, v in params.items()
    )
    return f"{THREADS_AUTHORIZE_URL}?{query_string}"


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[ThreadsTokens, ThreadsAccountInfo]:
    """Exchange an authorization code for a long-lived Threads token + profile."""
    client_id, client_secret = get_threads_client_config()

    async with httpx.AsyncClient() as client:
        # Step 1: code -> short-lived token (form-encoded POST)
        token_response = await client.post(
            THREADS_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if token_response.status_code != 200:
            error_msg = _err(token_response)
            logger.error(f"[ThreadsOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        short_data = token_response.json()
        short_lived_token = short_data["access_token"]
        threads_user_id = str(short_data.get("user_id")) if short_data.get("user_id") is not None else None

        # Step 2: short-lived -> long-lived token (60 days)
        long_response = await client.get(
            THREADS_LONG_LIVED_URL,
            params={
                "grant_type": "th_exchange_token",
                "client_secret": client_secret,
                "access_token": short_lived_token,
            },
        )
        if long_response.status_code != 200:
            error_msg = _err(long_response)
            logger.error(f"[ThreadsOAuth] Long-lived token exchange failed: {error_msg}")
            raise ValueError(f"Failed to get long-lived token: {error_msg}")

        long_data = long_response.json()
        expires_in = long_data.get("expires_in", 5184000)  # 60 days
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        tokens = ThreadsTokens(
            access_token=long_data["access_token"],
            expires_at=expires_at.isoformat(),
            token_type=long_data.get("token_type", "Bearer"),
            threads_user_id=threads_user_id,
        )

        # Step 3: best-effort profile for display / credential naming
        info = ThreadsAccountInfo(threads_user_id=threads_user_id)
        try:
            me = await client.get(
                f"{THREADS_API_BASE}/v1.0/me",
                params={
                    "fields": "id,username,name",
                    "access_token": tokens.access_token,
                },
            )
            if me.status_code == 200:
                me_data = me.json()
                info.threads_user_id = str(me_data.get("id") or threads_user_id or "")
                info.username = me_data.get("username")
                info.name = me_data.get("name")
        except Exception:
            pass

        logger.info(f"[ThreadsOAuth] Connected Threads account @{info.username}")
        return tokens, info


async def refresh_access_token(
    current_token: str,
    last_refreshed_at: Optional[str] = None,
) -> ThreadsTokens:
    """Refresh a long-lived Threads token (must be >=24h old and unexpired)."""
    if last_refreshed_at:
        try:
            last = datetime.fromisoformat(last_refreshed_at.replace("Z", "+00:00"))
            hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            if hours < 24:
                raise ValueError(
                    f"Token refresh too soon: last refreshed {hours:.1f}h ago. "
                    "Threads requires 24 hours between refreshes."
                )
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[ThreadsOAuth] Could not parse last_refreshed_at: {e}")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            THREADS_REFRESH_URL,
            params={
                "grant_type": "th_refresh_token",
                "access_token": current_token,
            },
        )
        if response.status_code != 200:
            error_msg = _err(response)
            logger.error(f"[ThreadsOAuth] Token refresh failed: {error_msg}")
            raise ValueError(f"Token refresh failed: {error_msg}")

        data = response.json()
        expires_in = data.get("expires_in", 5184000)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        logger.info("[ThreadsOAuth] Successfully refreshed access token")
        return ThreadsTokens(
            access_token=data["access_token"],
            expires_at=expires_at.isoformat(),
            token_type=data.get("token_type", "Bearer"),
        )


def is_token_expired(expires_at: str, buffer_days: int = 7) -> bool:
    """True if the token is expired or expires within buffer_days (60-day tokens)."""
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(days=buffer_days) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[ThreadsOAuth] Error parsing expiry time: {e}")
        return True


def _err(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error", {})
        if isinstance(err, dict):
            return err.get("message") or err.get("error_message") or str(data)
        return data.get("error_message") or str(data)
    except Exception:
        return f"HTTP {response.status_code}"