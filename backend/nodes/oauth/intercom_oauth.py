"""
Intercom OAuth 2.0 utility for handling the token exchange.
Manages the authorization_code flow for Intercom API access.

Intercom OAuth uses:
- Authorization URL: https://app.intercom.com/oauth
- Token URL:         https://api.intercom.io/auth/eagle/token
- User info:         GET https://api.intercom.io/me

Intercom OAuth peculiarities (https://developers.intercom.com/docs/build-an-integration/learn-more/authentication/setting-up-oauth):
- Access tokens are LONG-LIVED — they do not expire unless revoked.
- There are NO refresh tokens. The token URL only supports grant_type=authorization_code;
  there is no refresh grant, so ``refresh_access_token`` is a hard error.
- There is NO ``scope`` URL param — scopes are fixed per app in the Developer Hub.
- The authorize endpoint takes only ``client_id`` and ``state`` (plus an optional
  ``redirect_uri`` to pick among the app's registered redirect URLs).

client_id / client_secret default to the INTERCOM_CLIENT_ID / INTERCOM_CLIENT_SECRET
env vars but accept user-supplied values so a "bring your own app" custom OAuth
client (x-oauth-supports-custom-client) can be used.

Documentation: https://developers.intercom.com/docs/build-an-integration/learn-more/authentication
"""

import os
import logging
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

INTERCOM_AUTH_URL = "https://app.intercom.com/oauth"
INTERCOM_TOKEN_URL = "https://api.intercom.io/auth/eagle/token"
INTERCOM_USERINFO_URL = "https://api.intercom.io/me"


class IntercomTokens(BaseModel):
    """Structured token response from Intercom OAuth.

    Intercom access tokens are long-lived (no expiry) and there is no refresh
    token, so ``refresh_token`` and ``expires_at`` are always None — they exist
    only to keep the shape consistent with other OAuth providers.
    """

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # always None for Intercom (non-expiring)
    token_type: str = "Bearer"


class IntercomUserInfo(BaseModel):
    """User/workspace info from Intercom (GET /me)."""

    id: str
    name: str
    email: Optional[str] = None


def get_intercom_client_config() -> Tuple[str, str]:
    """Get Intercom OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("INTERCOM_CLIENT_ID")
    client_secret = os.environ.get("INTERCOM_CLIENT_SECRET")

    if not client_id:
        raise ValueError("INTERCOM_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("INTERCOM_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_intercom_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[IntercomTokens, IntercomUserInfo]:
    """Exchange authorization code for an access token, then fetch user info.

    Intercom's token endpoint takes ``code``, ``client_id`` and ``client_secret``
    and returns ``{ token_type, token, access_token }``. The token never expires
    and no refresh token is issued.

    Args:
        code: Authorization code from Intercom OAuth callback
        redirect_uri: Accepted for API consistency; Intercom validates against the
            app's registered redirect URLs and does not require it in this call.
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (IntercomTokens, IntercomUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)
    _ = redirect_uri  # Intercom ignores it on the token call; kept for symmetry.

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "code": code,
        "client_id": cid,
        "client_secret": csecret,
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            INTERCOM_TOKEN_URL, data=data, headers=headers
        )

        if token_response.status_code != 200:
            logger.error(
                f"[IntercomOAuth] Token exchange failed: HTTP {token_response.status_code}"
            )
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[IntercomOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Intercom returns the token under both ``access_token`` and ``token``.
        access_token = token_data.get("access_token") or token_data.get("token")
        if not access_token:
            logger.error(
                f"[IntercomOAuth] Token exchange returned no token: {token_data}"
            )
            raise ValueError("Token exchange returned no access token")

        tokens = IntercomTokens(
            access_token=access_token,
            refresh_token=None,
            expires_at=None,
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[IntercomOAuth] Successfully exchanged code for token for {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(
    client: httpx.AsyncClient, access_token: str
) -> IntercomUserInfo:
    """Fetch the authenticated admin/workspace from Intercom's GET /me."""
    response = await client.get(
        INTERCOM_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[IntercomOAuth] Failed to get user info: HTTP {response.status_code}")
        return IntercomUserInfo(id="unknown", name="Unknown")

    me = response.json()
    if not isinstance(me, dict):
        return IntercomUserInfo(id="unknown", name="Unknown")

    # GET /me returns the admin object; the owning workspace is under ``app``.
    app = me.get("app") if isinstance(me.get("app"), dict) else {}
    name = me.get("name") or app.get("name") or "Unknown"
    return IntercomUserInfo(
        id=str(me.get("id", "unknown")),
        name=name,
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> IntercomTokens:
    """Intercom does not support refresh tokens.

    Access tokens are long-lived and never expire, so there is nothing to
    refresh. This exists to keep the provider surface consistent (the OAuth
    handler / freshen choke point import it) but calling it is a programming
    error and raises loudly rather than silently returning a stale token.

    Raises:
        ValueError: always — Intercom has no refresh grant.
    """
    _ = (refresh_token, client_id, client_secret)
    raise ValueError(
        "Intercom OAuth tokens are long-lived and cannot be refreshed "
        "(Intercom issues no refresh token)."
    )


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Intercom access tokens never expire, so a credential is never stale.

    Kept for signature-compatibility with other providers; always returns False
    (a None ``expires_at`` is the normal, valid state for Intercom).
    """
    _ = (expires_at, buffer_minutes)
    return False


def get_intercom_auth_url(
    state: str,
    redirect_uri: Optional[str] = None,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Intercom OAuth authorization URL.

    Intercom's authorize endpoint takes ``client_id`` and ``state`` only — there
    is no ``scope`` param (scopes are fixed per app in the Developer Hub). A
    ``redirect_uri`` may be passed to pick among the app's registered redirect
    URLs.

    Args:
        state: State parameter for CSRF protection
        redirect_uri: optional redirect URI (must be registered on the app)
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_intercom_client_config()[0]

    params = {"client_id": cid, "state": state}
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    return f"{INTERCOM_AUTH_URL}?{urlencode(params)}"


# Default scopes for Intercom operations. Intercom does NOT accept a scope URL
# param (scopes are fixed per app in the Developer Hub), so this list is
# informational only — it mirrors x-oauth-scopes in IntercomOAuthCredential and
# is surfaced in the UI so users know which permissions to enable on their app.
INTERCOM_DEFAULT_SCOPES = [
    "read_write_users",
    "read_write_companies",
    "read_write_conversations",
    "read_write_tags",
    "read_write_events",
    "read_write_tickets",
    "read_admins",
    "read_teams",
]
