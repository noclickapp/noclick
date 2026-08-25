"""
Meta (Marketing / Ads / Business) OAuth utility — token exchange, refresh, expiry.

Self-contained for the Meta node (Marketing API, Conversions API, Lead Ads,
Business Management). Uses Facebook Login OAuth against the same Graph endpoint
as the Facebook node but requests ads/business scopes. Mints a long-lived user
token; System User tokens are the production alternative (supplied manually via
the access-token credential). Env: META_APP_ID / META_APP_SECRET.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

META_GRAPH_API = "https://graph.facebook.com/v25.0"
META_TOKEN_URL = f"{META_GRAPH_API}/oauth/access_token"


class MetaTokens(BaseModel):
    access_token: str
    expires_at: str  # ISO 8601
    token_type: str = "Bearer"


class MetaUserInfo(BaseModel):
    facebook_user_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None


def get_meta_client_config() -> Tuple[str, str]:
    client_id = os.environ.get("META_APP_ID")
    client_secret = os.environ.get("META_APP_SECRET")
    if not client_id:
        raise ValueError("META_APP_ID environment variable is required")
    if not client_secret:
        raise ValueError("META_APP_SECRET environment variable is required")
    return client_id, client_secret


async def exchange_code_for_meta_tokens(code: str, redirect_uri: str) -> Tuple[MetaTokens, MetaUserInfo]:
    """Exchange a Facebook Login code for a long-lived USER token (60 days) +
    basic /me info. Marketing API scopes are set at authorize time, not here."""
    client_id, client_secret = get_meta_client_config()
    async with httpx.AsyncClient() as client:
        short = await client.get(META_TOKEN_URL, params={
            "client_id": client_id, "client_secret": client_secret,
            "code": code, "redirect_uri": redirect_uri})
        if short.status_code != 200:
            raise ValueError(f"Token exchange failed: {short.json().get('error', {}).get('message', 'Unknown error')}")
        long = await client.get(META_TOKEN_URL, params={
            "grant_type": "fb_exchange_token", "client_id": client_id,
            "client_secret": client_secret, "fb_exchange_token": short.json()["access_token"]})
        if long.status_code != 200:
            raise ValueError(f"Failed to get long-lived token: {long.json().get('error', {}).get('message', 'Unknown error')}")
        data = long.json()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 5184000))
        tokens = MetaTokens(access_token=data["access_token"], expires_at=expires_at.isoformat(),
                            token_type=data.get("token_type", "Bearer"))
        info = MetaUserInfo()
        try:
            me = await client.get(f"{META_GRAPH_API}/me",
                                  params={"access_token": tokens.access_token, "fields": "id,name,email"})
            if me.status_code == 200:
                d = me.json()
                info = MetaUserInfo(facebook_user_id=d.get("id"), name=d.get("name"), email=d.get("email"))
        except Exception:
            pass
        return tokens, info


async def refresh_access_token(current_token: str, last_refreshed_at: Optional[str] = None) -> MetaTokens:
    """Refresh a long-lived user token via fb_exchange_token. System User tokens
    (the manual access-token method) don't ride this path."""
    client_id, client_secret = get_meta_client_config()
    async with httpx.AsyncClient() as client:
        resp = await client.get(META_TOKEN_URL, params={
            "grant_type": "fb_exchange_token", "client_id": client_id,
            "client_secret": client_secret, "fb_exchange_token": current_token})
        if resp.status_code != 200:
            raise ValueError(f"Token refresh failed: {resp.json().get('error', {}).get('message', 'Unknown error')}")
        data = resp.json()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 5184000))
        return MetaTokens(access_token=data["access_token"], expires_at=expires_at.isoformat(),
                          token_type=data.get("token_type", "Bearer"))


def is_token_expired(expires_at: str, buffer_days: int = 7) -> bool:
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(days=buffer_days) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[MetaOAuth] Error parsing expiry time: {e}")
        return True
