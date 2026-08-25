"""
QuickBooks (Intuit) OAuth 2.0 utility for token exchange and refresh.
Manages the authorization_code flow for the QuickBooks Online Accounting API.

QuickBooks Online uses Intuit's OAuth 2.0 authorization_code flow:
- Authorization URL: https://appcenter.intuit.com/connect/oauth2
- Token URL:         https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer
  (POST with HTTP Basic header of client_id:client_secret)
- Refresh:           POST token URL with grant_type=refresh_token
- Revocation URL:    https://developer.api.intuit.com/v2/oauth2/tokens/revoke
- User info:         GET https://accounts.platform.intuit.com/v1/openid_connect/userinfo
- Access tokens expire after 3600s (1 hour).
- Refresh tokens ROTATE on every refresh and expire after 100 days of
  inactivity, so the rotated refresh token MUST be persisted each time.

The OAuth callback also returns a ``realmId`` (company ID) that scopes every
subsequent API call — it is part of the request URL path, not a header — so it
must be stored alongside the tokens.

client_id / client_secret default to the QUICKBOOKS_CLIENT_ID /
QUICKBOOKS_CLIENT_SECRET env vars, falling back to INTUIT_CLIENT_ID /
INTUIT_CLIENT_SECRET for shared Intuit app setups, but accept user-supplied
values so a "bring your own app" custom OAuth client
(x-oauth-supports-custom-client) can be used.

Documentation: https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization/oauth-2.0
"""

import os
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

QUICKBOOKS_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QUICKBOOKS_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QUICKBOOKS_REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
QUICKBOOKS_USERINFO_URL = "https://accounts.platform.intuit.com/v1/openid_connect/userinfo"

# QuickBooks scopes requested together at connect time (standard OAuth-app
# pattern — no per-scope picker). Only the scopes the Intuit app is actually
# provisioned for may be requested: Intuit rejects the ENTIRE authorization with
# `invalid_scope` if any requested scope isn't enabled on the app. The shared
# NoClick app requests Accounting only (the Payments API surface was removed);
# keep this list in lockstep with the app's Permissions page.
QUICKBOOKS_FULL_SCOPES = [
    "com.intuit.quickbooks.accounting",
    "openid",
    "profile",
    "email",
]


class QuickBooksTokens(BaseModel):
    """Structured token response from Intuit OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str  # ISO 8601 timestamp
    token_type: str = "Bearer"
    realm_id: Optional[str] = None  # company ID captured at OAuth time


class QuickBooksUserInfo(BaseModel):
    """User info from Intuit's OpenID Connect userinfo endpoint."""

    id: str
    name: str
    email: Optional[str] = None


def get_quickbooks_client_config() -> Tuple[str, str]:
    """Return (client_id, client_secret) from environment.

    Intuit is always a confidential client (the token endpoint requires HTTP
    Basic auth), so both values are required.

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("QUICKBOOKS_CLIENT_ID") or os.environ.get("INTUIT_CLIENT_ID")
    client_secret = os.environ.get("QUICKBOOKS_CLIENT_SECRET") or os.environ.get("INTUIT_CLIENT_SECRET")
    if not client_id:
        raise ValueError("QUICKBOOKS_CLIENT_ID or INTUIT_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("QUICKBOOKS_CLIENT_SECRET or INTUIT_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_quickbooks_client_config()


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    """Build the HTTP Basic ``Authorization`` header Intuit's token endpoint
    requires (base64 of ``client_id:client_secret``)."""
    return base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    realm_id: Optional[str] = None,
) -> Tuple[QuickBooksTokens, QuickBooksUserInfo]:
    """Exchange authorization code for tokens, then fetch user info.

    Intuit returns a ``realmId`` (company ID) on the callback query string, not
    in the token body, so it is passed in and threaded onto the returned tokens.

    Args:
        code: Authorization code from the Intuit OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client
        realm_id: company ID captured from the OAuth callback (``realmId`` param)

    Returns:
        Tuple of (QuickBooksTokens, QuickBooksUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {
        "Authorization": f"Basic {_basic_auth_header(cid, csecret)}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_response = await client.post(
            QUICKBOOKS_TOKEN_URL, data=data, headers=headers
        )

        if token_response.status_code != 200:
            logger.error(
                f"[QuickBooksOAuth] Token exchange failed: HTTP {token_response.status_code}"
            )
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[QuickBooksOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Intuit access tokens expire in 1 hour (expires_in seconds).
        expires_in = token_data.get("expires_in", 3600)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        tokens = QuickBooksTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
            realm_id=realm_id,
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[QuickBooksOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(
    client: httpx.AsyncClient, access_token: str
) -> QuickBooksUserInfo:
    """Fetch user info from Intuit's OpenID Connect userinfo endpoint."""
    response = await client.get(
        QUICKBOOKS_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[QuickBooksOAuth] Failed to get user info: HTTP {response.status_code}")
        return QuickBooksUserInfo(id="unknown", name="Unknown")

    me = response.json() if response.content else {}
    name = me.get("givenName") or me.get("email") or "QuickBooks User"
    if me.get("givenName") and me.get("familyName"):
        name = f"{me['givenName']} {me['familyName']}"
    return QuickBooksUserInfo(
        id=str(me.get("sub", "unknown")),
        name=name,
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> QuickBooksTokens:
    """Refresh an expired access token using the (rotating) refresh token.

    Intuit rotates the refresh token on every successful refresh and invalidates
    the previous one, so the returned ``refresh_token`` must be persisted. If a
    refresh response somehow omits one, we keep the existing token rather than
    blanking the credential.

    Args:
        refresh_token: The refresh token stored in credentials
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New QuickBooksTokens with updated access_token

    Raises:
        ValueError: If refresh fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)
    headers = {
        "Authorization": f"Basic {_basic_auth_header(cid, csecret)}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(QUICKBOOKS_TOKEN_URL, data=data, headers=headers)
        if response.status_code != 200:
            try:
                error_data = response.json()
                error_msg = error_data.get(
                    "error_description", error_data.get("error") or f"HTTP {response.status_code}"
                )
                error_code = (
                    error_data.get("error") if isinstance(error_data, dict) else None
                )
            except Exception:
                error_msg = f"HTTP {response.status_code}"
                error_code = None
            logger.error(f"[QuickBooksOAuth] Token refresh failed: {error_msg}")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()
        expires_in = token_data.get("expires_in", 3600)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
        return QuickBooksTokens(
            access_token=token_data["access_token"],
            # Rotating refresh token: persist the new one; keep the old as a
            # safeguard if the response unexpectedly omits it.
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )


def is_token_expired(expires_at: str, buffer_minutes: int = 5) -> bool:
    """Return True if the access token is expired or expiring within the buffer."""
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[QuickBooksOAuth] Error parsing expiry time: {e}")
        return True


def get_quickbooks_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Intuit OAuth authorization URL.

    Intuit expects space-delimited scopes (it requires ``com.intuit.quickbooks.accounting``
    plus the OpenID scopes used for the userinfo lookup).

    Args:
        scopes: List of OAuth scopes to request (space-delimited in the URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_quickbooks_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{QUICKBOOKS_AUTH_URL}?{urlencode(params)}"
