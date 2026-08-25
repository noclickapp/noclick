"""
Instagram Login OAuth utility (Instagram API *with Instagram Login*).

This is the newer, Meta-recommended Instagram business API where the user logs
in with their INSTAGRAM account directly — NO Facebook account and NO Facebook
Page required. It is a DIFFERENT auth model from `facebook_oauth.py` (Instagram
API with Facebook Login), with its own app credentials (an "Instagram App ID/
Secret", not the Facebook App ID), its own hosts, and its own scope vocabulary
(`instagram_business_*`). Tokens are served from graph.instagram.com.

Flow (parallels Threads):
  1. Authorize:  https://www.instagram.com/oauth/authorize (browser)
  2. Exchange code -> short-lived token (1h):
       POST https://api.instagram.com/oauth/access_token (grant_type=authorization_code)
  3. Short-lived -> long-lived token (60d):
       GET  https://graph.instagram.com/access_token (grant_type=ig_exchange_token)
  4. Refresh long-lived (extends 60d, token must be >=24h old):
       GET  https://graph.instagram.com/refresh_access_token (grant_type=ig_refresh_token)

Docs: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional, List
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

INSTAGRAM_API_BASE = "https://graph.instagram.com"
INSTAGRAM_AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_LONG_LIVED_URL = f"{INSTAGRAM_API_BASE}/access_token"
INSTAGRAM_REFRESH_URL = f"{INSTAGRAM_API_BASE}/refresh_access_token"


class InstagramLoginTokens(BaseModel):
    """Structured token response from the Instagram Login OAuth flow."""

    access_token: str
    expires_at: str  # ISO 8601 timestamp
    token_type: str = "Bearer"
    instagram_user_id: Optional[str] = None


class InstagramLoginAccountInfo(BaseModel):
    """Basic profile metadata for a connected Instagram professional account."""

    instagram_user_id: Optional[str] = None
    username: Optional[str] = None
    name: Optional[str] = None
    account_type: Optional[str] = None


def get_instagram_client_config() -> Tuple[str, str]:
    """Return the Instagram app (client_id, client_secret) from the environment.

    The Instagram product in the Meta app dashboard generates an *Instagram App
    ID/Secret* distinct from the app's Facebook App ID/Secret — these are the
    ones that must be used here (the Facebook App ID will NOT work).
    """
    client_id = os.environ.get("INSTAGRAM_CLIENT_ID") or os.environ.get("INSTAGRAM_APP_ID")
    client_secret = os.environ.get("INSTAGRAM_CLIENT_SECRET") or os.environ.get("INSTAGRAM_APP_SECRET")
    if not client_id:
        raise ValueError("INSTAGRAM_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("INSTAGRAM_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def get_instagram_auth_url(scopes: List[str], state: str, redirect_uri: str) -> str:
    """Generate the Instagram Login OAuth authorization URL."""
    client_id, _ = get_instagram_client_config()
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
    return f"{INSTAGRAM_AUTHORIZE_URL}?{query_string}"


def _short_token_fields(payload: dict) -> Tuple[str, Optional[str]]:
    """Instagram returns the short-lived token either flat or wrapped in `data`."""
    obj = payload
    if isinstance(payload.get("data"), list) and payload["data"]:
        obj = payload["data"][0]
    token = obj.get("access_token")
    uid = obj.get("user_id")
    return token, (str(uid) if uid is not None else None)


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[InstagramLoginTokens, InstagramLoginAccountInfo]:
    """Exchange an authorization code for a long-lived Instagram token + profile."""
    client_id, client_secret = get_instagram_client_config()

    async with httpx.AsyncClient() as client:
        # Step 1: code -> short-lived token (form-encoded POST). Instagram strips
        # any URL fragment it may have appended to the code (`#_`).
        token_response = await client.post(
            INSTAGRAM_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code.split("#")[0],
            },
        )
        if token_response.status_code != 200:
            error_msg = _err(token_response)
            logger.error(f"[InstagramLoginOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        short_lived_token, instagram_user_id = _short_token_fields(token_response.json())
        if not short_lived_token:
            raise ValueError("Instagram token exchange returned no access_token")

        # Step 2: short-lived -> long-lived token (60 days)
        long_response = await client.get(
            INSTAGRAM_LONG_LIVED_URL,
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": client_secret,
                "access_token": short_lived_token,
            },
        )
        if long_response.status_code != 200:
            error_msg = _err(long_response)
            logger.error(f"[InstagramLoginOAuth] Long-lived token exchange failed: {error_msg}")
            raise ValueError(f"Failed to get long-lived token: {error_msg}")

        long_data = long_response.json()
        expires_in = long_data.get("expires_in", 5184000)  # 60 days
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        tokens = InstagramLoginTokens(
            access_token=long_data["access_token"],
            expires_at=expires_at.isoformat(),
            token_type=long_data.get("token_type", "Bearer"),
            instagram_user_id=instagram_user_id,
        )

        # Step 3: best-effort profile for display / credential naming. On Instagram
        # Login the graph id used in API paths is the `user_id` field.
        info = InstagramLoginAccountInfo(instagram_user_id=instagram_user_id)
        try:
            me = await client.get(
                f"{INSTAGRAM_API_BASE}/me",
                params={
                    "fields": "user_id,username,name,account_type",
                    "access_token": tokens.access_token,
                },
            )
            if me.status_code == 200:
                me_data = me.json()
                info.instagram_user_id = str(me_data.get("user_id") or instagram_user_id or "")
                info.username = me_data.get("username")
                info.name = me_data.get("name")
                info.account_type = me_data.get("account_type")
                tokens.instagram_user_id = info.instagram_user_id
        except Exception:
            pass

        logger.info(f"[InstagramLoginOAuth] Connected Instagram account @{info.username}")
        return tokens, info


async def refresh_access_token(
    current_token: str,
    last_refreshed_at: Optional[str] = None,
) -> InstagramLoginTokens:
    """Refresh a long-lived Instagram token (must be >=24h old and unexpired)."""
    if last_refreshed_at:
        try:
            last = datetime.fromisoformat(last_refreshed_at.replace("Z", "+00:00"))
            hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            if hours < 24:
                raise ValueError(
                    f"Token refresh too soon: last refreshed {hours:.1f}h ago. "
                    "Instagram requires 24 hours between refreshes."
                )
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[InstagramLoginOAuth] Could not parse last_refreshed_at: {e}")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            INSTAGRAM_REFRESH_URL,
            params={
                "grant_type": "ig_refresh_token",
                "access_token": current_token,
            },
        )
        if response.status_code != 200:
            error_msg = _err(response)
            logger.error(f"[InstagramLoginOAuth] Token refresh failed: {error_msg}")
            raise ValueError(f"Token refresh failed: {error_msg}")

        data = response.json()
        expires_in = data.get("expires_in", 5184000)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        logger.info("[InstagramLoginOAuth] Successfully refreshed access token")
        return InstagramLoginTokens(
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
        logger.error(f"[InstagramLoginOAuth] Error parsing expiry time: {e}")
        return True


def _err(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error", {})
        if isinstance(err, dict):
            return err.get("message") or err.get("error_message") or str(data)
        return data.get("error_message") or data.get("error_type") or str(data)
    except Exception:
        return f"HTTP {response.status_code}"