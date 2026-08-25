"""
Webflow OAuth 2.0 utility for handling token exchange.
Manages the authorization_code flow for Webflow Data API (v2) access.

Webflow OAuth uses:
- Authorization URL: https://webflow.com/oauth/authorize
- Token URL:         https://api.webflow.com/oauth/access_token
- User info:         GET https://api.webflow.com/v2/token/authorized_by

Webflow OAuth access tokens are LONG-LIVED and do NOT expire — there is no
refresh-token flow. The token response carries only an ``access_token`` (and
``token_type``); no ``refresh_token`` / ``expires_in`` is returned. We therefore
store no ``expires_at`` and never refresh. ``refresh_access_token`` is kept (a
no-op shaped like its Asana sibling) so the credential's freshen contract stays
uniform; it would only fire if a refresh_token were somehow stored, which never
happens for Webflow.

client_id / client_secret default to the WEBFLOW_CLIENT_ID / WEBFLOW_CLIENT_SECRET
env vars but accept user-supplied values so a "bring your own app" custom OAuth
client (x-oauth-supports-custom-client) can be used.

Documentation: https://developers.webflow.com/data/reference/oauth-app
"""

import os
import logging
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

WEBFLOW_AUTH_URL = "https://webflow.com/oauth/authorize"
WEBFLOW_TOKEN_URL = "https://api.webflow.com/oauth/access_token"
WEBFLOW_REVOKE_URL = "https://webflow.com/oauth/revoke_authorization"
WEBFLOW_USERINFO_URL = "https://api.webflow.com/v2/token/authorized_by"


class WebflowTokens(BaseModel):
    """Structured token response from Webflow OAuth.

    Webflow tokens are long-lived and non-expiring, so refresh_token/expires_at
    are always None — the fields exist only to keep the credential shape uniform
    with rotating-token providers.
    """

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp (always None for Webflow)
    token_type: str = "Bearer"


class WebflowUserInfo(BaseModel):
    """User info from Webflow (GET /v2/token/authorized_by)."""

    id: str
    name: str
    email: Optional[str] = None


def get_webflow_client_config() -> Tuple[str, str]:
    """Get Webflow OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("WEBFLOW_CLIENT_ID")
    client_secret = os.environ.get("WEBFLOW_CLIENT_SECRET")

    if not client_id:
        raise ValueError("WEBFLOW_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("WEBFLOW_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_webflow_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[WebflowTokens, WebflowUserInfo]:
    """Exchange authorization code for access token, then fetch user info.

    Args:
        code: Authorization code from Webflow OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (WebflowTokens, WebflowUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "client_id": cid,
        "client_secret": csecret,
        "redirect_uri": redirect_uri,
        "code": code,
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(WEBFLOW_TOKEN_URL, data=data, headers=headers)

        if token_response.status_code != 200:
            logger.error(f"[WebflowOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[WebflowOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Webflow tokens are long-lived and non-expiring — no expires_in returned.
        tokens = WebflowTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=None,
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[WebflowOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> WebflowUserInfo:
    """Fetch user info from Webflow's GET /v2/token/authorized_by."""
    response = await client.get(
        WEBFLOW_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[WebflowOAuth] Failed to get user info: HTTP {response.status_code}")
        return WebflowUserInfo(id="unknown", name="Unknown")

    me = response.json()
    if not isinstance(me, dict):
        return WebflowUserInfo(id="unknown", name="Unknown")

    first = me.get("firstName") or ""
    last = me.get("lastName") or ""
    name = (f"{first} {last}").strip() or me.get("email") or "Unknown"
    return WebflowUserInfo(
        id=str(me.get("id", "unknown")),
        name=name,
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> WebflowTokens:
    """Refresh an access token using the refresh token.

    Webflow OAuth access tokens are long-lived and non-expiring; Webflow does
    not issue refresh tokens or expose a refresh flow. This function exists only
    to satisfy the uniform freshen contract — it is never reached at runtime
    because no refresh_token is ever stored for a Webflow credential (the
    freshen choke point short-circuits to a no-op when refresh_token is absent).

    Raises:
        ValueError: always, since Webflow provides no refresh endpoint
    """
    raise ValueError(
        "Webflow OAuth tokens are non-expiring and cannot be refreshed; "
        "reconnect the account if the token has been revoked."
    )


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Check if a token is expired.

    Webflow tokens are non-expiring, so ``expires_at`` is always None and this
    always returns False. Kept for interface parity with rotating providers.
    """
    return False


def get_webflow_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Webflow OAuth authorization URL.

    Webflow expects space-delimited scopes at the authorize endpoint.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in the URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_webflow_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{WEBFLOW_AUTH_URL}?{urlencode(params)}"


# Default scopes for Webflow operations. Mirrors the x-oauth-scopes in
# WebflowOAuthCredential so the authorize route and backend agree.
WEBFLOW_DEFAULT_SCOPES = [
    "sites:read",
    "sites:write",
    "pages:read",
    "pages:write",
    "cms:read",
    "cms:write",
    "custom_code:read",
    "custom_code:write",
    "forms:read",
    "forms:write",
    "ecommerce:read",
    "ecommerce:write",
    "assets:read",
    "assets:write",
    "components:read",
    "components:write",
    "comments:read",
    "comments:write",
    "site_config:read",
    "site_config:write",
    "site_activity:read",
    "workspace:read",
    "workspace:write",
    "authorized_user:read",
]
