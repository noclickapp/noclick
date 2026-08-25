"""
Stripe Connect OAuth utility — token exchange, refresh, and auth-URL building.

Stripe Connect ("Connect with Stripe") uses a plain OAuth 2.0 authorization-code
flow (no PKCE):
- Authorization URL: https://connect.stripe.com/oauth/authorize
- Token URL:         https://connect.stripe.com/oauth/token
- Deauthorize:       https://connect.stripe.com/oauth/deauthorize

The token endpoint is authenticated with the platform's secret key (passed as
``client_secret``). The response carries the connected account's ``access_token``
(usable as a Bearer token), ``stripe_user_id`` (acct_…), ``refresh_token``, and
``stripe_publishable_key``. Connect access tokens DO NOT expire and refresh
tokens are NOT single-use, so refresh is optional.

Env: ``STRIPE_CONNECT_CLIENT_ID`` (ca_…), ``STRIPE_CONNECT_CLIENT_SECRET`` (the
platform secret key sk_…).

Docs: https://docs.stripe.com/connect/oauth-reference
"""

import logging
import os
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

STRIPE_AUTH_URL = "https://connect.stripe.com/oauth/authorize"
STRIPE_TOKEN_URL = "https://connect.stripe.com/oauth/token"
STRIPE_DEAUTHORIZE_URL = "https://connect.stripe.com/oauth/deauthorize"


class StripeTokens(BaseModel):
    """Structured token response from Stripe Connect OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # Connect tokens don't expire
    scope: Optional[str] = None
    token_type: str = "bearer"
    stripe_user_id: Optional[str] = None
    stripe_publishable_key: Optional[str] = None
    livemode: Optional[bool] = None


class StripeUserInfo(BaseModel):
    """Identifying info for the connected Stripe account."""

    id: str
    email: Optional[str] = None


def get_stripe_client_config() -> Tuple[str, str]:
    """Return (client_id, client_secret) from env.

    Raises:
        ValueError: if either env var is missing.
    """
    client_id = os.environ.get("STRIPE_CONNECT_CLIENT_ID")
    client_secret = os.environ.get("STRIPE_CONNECT_CLIENT_SECRET")
    if not client_id:
        raise ValueError("STRIPE_CONNECT_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("STRIPE_CONNECT_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def _tokens_from_response(token_data: dict, fallback_refresh: Optional[str] = None) -> StripeTokens:
    return StripeTokens(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token", fallback_refresh),
        expires_at=None,  # Stripe Connect access tokens do not expire
        scope=token_data.get("scope"),
        token_type=token_data.get("token_type", "bearer"),
        stripe_user_id=token_data.get("stripe_user_id"),
        stripe_publishable_key=token_data.get("stripe_publishable_key"),
        livemode=token_data.get("livemode"),
    )


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: Optional[str] = None,  # unused (Stripe Connect has no PKCE)
) -> Tuple[StripeTokens, StripeUserInfo]:
    """Exchange an authorization code for Stripe Connect tokens.

    Raises:
        ValueError: if the exchange fails.
    """
    _client_id, client_secret = get_stripe_client_config()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            STRIPE_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[StripeOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        tokens = _tokens_from_response(response.json())
        user_info = StripeUserInfo(id=tokens.stripe_user_id or "unknown")
        logger.info(
            f"[StripeOAuth] Connected Stripe account {user_info.id} (livemode={tokens.livemode})"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> StripeTokens:
    """Roll the Connect access token using the refresh token.

    Stripe Connect tokens don't expire, but this is provided for completeness and
    parity with other OAuth providers. Stripe does NOT rotate refresh tokens.

    Raises:
        ValueError: if the refresh fails.
    """
    _client_id, client_secret = get_stripe_client_config()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            STRIPE_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            error_code = error_data.get("error") if isinstance(error_data, dict) else None
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            logger.error(f"[StripeOAuth] Token refresh failed: {error_msg}")
            raise ValueError(f"Token refresh failed: {error_msg}")

        tokens = _tokens_from_response(response.json(), fallback_refresh=refresh_token)
        logger.info("[StripeOAuth] Refreshed Connect access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Stripe Connect access tokens never expire."""
    return False


def get_stripe_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    code_challenge: Optional[str] = None,  # unused (no PKCE)
) -> str:
    """Build the Stripe Connect authorization URL."""
    client_id, _ = get_stripe_client_config()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": (scopes[0] if scopes else "read_write"),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{STRIPE_AUTH_URL}?{urlencode(params)}"


# Default scope for full read/write access to the connected account.
STRIPE_FULL_SCOPES = ["read_write"]
