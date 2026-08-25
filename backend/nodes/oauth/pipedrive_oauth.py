"""
Pipedrive OAuth 2.0 utility for handling token exchange and refresh.
Manages the authorization_code flow for Pipedrive API access.

Pipedrive OAuth uses:
- Authorization URL: https://oauth.pipedrive.com/oauth/authorize
- Token URL:         https://oauth.pipedrive.com/oauth/token
- Client auth:       HTTP Basic header — Authorization: Basic base64(client_id:client_secret)
- Refresh:           POST token URL with grant_type=refresh_token
- User info:         GET {api_domain}/api/v1/users/me

Pipedrive access tokens expire after 60 minutes. The token response includes an
``api_domain`` — the company-specific base URL all subsequent API requests MUST
be sent to (e.g. https://acme.pipedrive.com). We persist it on the credential.

Pipedrive refresh tokens rotate on use, but a refresh response may legitimately
omit a new one; in that case we keep the existing refresh_token (the freshen
choke point only overwrites refresh_token when present).

client_id / client_secret default to the PIPEDRIVE_CLIENT_ID /
PIPEDRIVE_CLIENT_SECRET env vars but accept user-supplied values so a "bring
your own app" custom OAuth client (x-oauth-supports-custom-client) can be used.

Documentation: https://pipedrive.readme.io/docs/marketplace-oauth-authorization
"""

import os
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel, field_validator

from utils.ssrf import normalize_provider_https_origin

logger = logging.getLogger(__name__)

PIPEDRIVE_AUTH_URL = "https://oauth.pipedrive.com/oauth/authorize"
PIPEDRIVE_TOKEN_URL = "https://oauth.pipedrive.com/oauth/token"
PIPEDRIVE_USERINFO_PATH = "/api/v1/users/me"


def normalize_pipedrive_api_domain(value: str) -> str:
    """Validate and canonicalize a Pipedrive-owned tenant origin."""
    return normalize_provider_https_origin(
        value,
        "pipedrive.com",
        field_name="Pipedrive API domain",
    )


class PipedriveTokens(BaseModel):
    """Structured token response from Pipedrive OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    api_domain: Optional[str] = None  # company-specific base URL for API calls
    token_type: str = "Bearer"

    @field_validator("api_domain")
    @classmethod
    def validate_api_domain(cls, value: Optional[str]) -> Optional[str]:
        return normalize_pipedrive_api_domain(value) if value is not None else None


class PipedriveUserInfo(BaseModel):
    """User info from Pipedrive (GET /api/v1/users/me)."""

    id: str
    name: str
    email: Optional[str] = None
    company_id: Optional[str] = None  # Pipedrive company id — matches the uninstall callback
    api_domain: Optional[str] = None  # echoed so the handler can persist it


def get_pipedrive_client_config() -> Tuple[str, str]:
    """Get Pipedrive OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("PIPEDRIVE_CLIENT_ID")
    client_secret = os.environ.get("PIPEDRIVE_CLIENT_SECRET")

    if not client_id:
        raise ValueError("PIPEDRIVE_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("PIPEDRIVE_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_pipedrive_client_config()


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    """Pipedrive expects HTTP Basic client authentication at the token endpoint."""
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[PipedriveTokens, PipedriveUserInfo]:
    """Exchange authorization code for access token, then fetch user info.

    Args:
        code: Authorization code from Pipedrive OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (PipedriveTokens, PipedriveUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": _basic_auth_header(cid, csecret),
    }
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            PIPEDRIVE_TOKEN_URL, data=data, headers=headers
        )

        if token_response.status_code != 200:
            logger.error(
                f"[PipedriveOAuth] Token exchange failed: HTTP {token_response.status_code}"
            )
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[PipedriveOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Pipedrive access tokens expire in 60 minutes (expires_in seconds).
        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = PipedriveTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            api_domain=token_data.get("api_domain"),
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(
            client, tokens.access_token, tokens.api_domain
        )

        logger.info(
            f"[PipedriveOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(
    client: httpx.AsyncClient, access_token: str, api_domain: Optional[str]
) -> PipedriveUserInfo:
    """Fetch user info from Pipedrive's GET /api/v1/users/me.

    Requests MUST go to the company-specific ``api_domain`` returned in the token
    response. If it is missing we can't resolve the user; return a placeholder
    while still carrying the (None) api_domain through.
    """
    if not api_domain:
        logger.warning("[PipedriveOAuth] No api_domain in token response")
        return PipedriveUserInfo(id="unknown", name="Unknown", api_domain=None)

    base = normalize_pipedrive_api_domain(api_domain)
    response = await client.get(
        f"{base}{PIPEDRIVE_USERINFO_PATH}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[PipedriveOAuth] Failed to get user info: HTTP {response.status_code}")
        return PipedriveUserInfo(id="unknown", name="Unknown", api_domain=base)

    payload = response.json()
    me = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(me, dict):
        me = {}
    return PipedriveUserInfo(
        id=str(me.get("id", "unknown")),
        name=me.get("name", "Unknown"),
        email=me.get("email"),
        company_id=str(me["company_id"]) if me.get("company_id") is not None else None,
        api_domain=base,
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> PipedriveTokens:
    """Refresh an expired access token using the refresh token.

    Pipedrive refresh tokens rotate on use, but a refresh response may omit a new
    refresh_token — in that case we keep the existing one (the freshen choke
    point only overwrites refresh_token when present).

    Args:
        refresh_token: The refresh token stored in credentials
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New PipedriveTokens with updated access_token

    Raises:
        ValueError: If refresh fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": _basic_auth_header(cid, csecret),
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(PIPEDRIVE_TOKEN_URL, data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"[PipedriveOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[PipedriveOAuth] Token refresh failed: {error_msg}")
            error_code = token_data.get("error") if isinstance(token_data, dict) else None
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = PipedriveTokens(
            access_token=token_data["access_token"],
            # Keep the existing refresh token if the provider doesn't return a
            # fresh one (rotation is not guaranteed on every refresh).
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            api_domain=token_data.get("api_domain"),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[PipedriveOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Check if a token is expired or will expire within *buffer_minutes*.

    Args:
        expires_at: ISO 8601 timestamp of token expiry (None if non-expiring)
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if no expiry or still valid
    """
    if not expires_at:
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return now + timedelta(minutes=buffer_minutes) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[PipedriveOAuth] Error parsing expiry time: {e}")
        return False


def get_pipedrive_auth_url(
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the Pipedrive OAuth authorization URL.

    Pipedrive scopes are configured per-app at registration in the Developer Hub
    and are NOT passed at the authorize endpoint, so only client_id, redirect_uri,
    and state are required.

    Args:
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_pipedrive_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{PIPEDRIVE_AUTH_URL}?{urlencode(params)}"


# Default scopes for Pipedrive operations. Pipedrive scopes are granted per-app
# at registration (not at the authorize endpoint), so this list is informational
# — it mirrors the x-oauth-scopes in PipedriveOAuthCredential for documentation
# and so the credential schema advertises what the NoClick app requests.
PIPEDRIVE_DEFAULT_SCOPES = [
    "base",
    "deals:full",
    "contacts:full",
    "activities:full",
    "leads:full",
    "products:full",
    "users:read",
    "search:read",
    "recents:read",
    "webhooks:full",
]
