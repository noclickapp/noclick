"""HubSpot authorization-code and refresh grants using the versioned OAuth API.

https://developers.hubspot.com/docs/api-reference/latest/authentication/manage-oauth-tokens
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HUBSPOT_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/2026-03/token"
_OAUTH_ERROR_CODES = frozenset({
    "invalid_request", "invalid_client", "invalid_grant", "unauthorized_client",
    "unsupported_grant_type", "invalid_scope", "access_denied", "server_error",
    "temporarily_unavailable",
})


class HubSpotTokens(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: str
    token_type: str = "bearer"


class HubSpotUserInfo(BaseModel):
    hub_id: str
    user_id: Optional[str] = None
    hub_domain: Optional[str] = None


def get_hubspot_client_config() -> Tuple[str, str]:
    client_id = os.environ.get("HUBSPOT_CLIENT_ID")
    client_secret = os.environ.get("HUBSPOT_CLIENT_SECRET")
    if not client_id:
        raise ValueError("HUBSPOT_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("HUBSPOT_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


async def _request_tokens(data: dict) -> Tuple[HubSpotTokens, HubSpotUserInfo]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                HUBSPOT_TOKEN_URL, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.TimeoutException:
            raise ValueError("HubSpot OAuth token request timed out") from None
        except httpx.RequestError:
            raise ValueError("HubSpot OAuth token request failed") from None

    if response.status_code != 200:
        # Retain standard failure classification, never provider text or echoed inputs.
        code = None
        try:
            error = response.json()
            candidate = error.get("error") if isinstance(error, dict) else None
            if isinstance(candidate, str) and candidate in _OAUTH_ERROR_CODES:
                code = candidate
        except ValueError:
            pass
        span = trace.get_current_span()
        if code and span and span.is_recording():
            span.set_attribute("oauth.provider_error_code", code)
        detail = f"HTTP {response.status_code}" + (f" ({code})" if code else "")
        logger.error("[HubSpot OAuth] Token request failed: %s", detail)
        raise ValueError(f"HubSpot OAuth token request failed: {detail}")

    try:
        payload = response.json()
    except ValueError:
        raise ValueError("HubSpot OAuth invalid token response") from None
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("HubSpot OAuth invalid token response")

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    token_type = payload.get("token_type", "bearer")
    expires_in = payload.get("expires_in")
    hub_id = payload.get("hub_id", "")
    hub_domain = payload.get("hub_domain")
    if (
        any(not isinstance(value, str) or not value.strip()
            for value in (access_token, refresh_token, token_type))
        or type(expires_in) is not int or expires_in <= 0
        or type(hub_id) not in (str, int)
        or (hub_domain is not None and not isinstance(hub_domain, str))
    ):
        raise ValueError("HubSpot OAuth invalid token response")
    try:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    except OverflowError:
        raise ValueError("HubSpot OAuth invalid token lifetime") from None

    return (
        HubSpotTokens(
            access_token=access_token, refresh_token=refresh_token,
            expires_at=expires_at.isoformat(), token_type=token_type,
        ),
        HubSpotUserInfo(hub_id=str(hub_id), hub_domain=hub_domain),
    )


async def exchange_code_for_tokens(
    code: str, redirect_uri: str,
) -> Tuple[HubSpotTokens, HubSpotUserInfo]:
    client_id, client_secret = get_hubspot_client_config()
    return await _request_tokens({
        "grant_type": "authorization_code", "code": code,
        "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    })


async def refresh_access_token(refresh_token: str) -> HubSpotTokens:
    client_id, client_secret = get_hubspot_client_config()
    tokens, _ = await _request_tokens({
        "grant_type": "refresh_token", "refresh_token": refresh_token,
        "client_id": client_id, "client_secret": client_secret,
    })
    return tokens
