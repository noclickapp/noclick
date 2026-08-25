"""
Attio OAuth 2.0 utility for token exchange, refresh, and introspection.

Attio OAuth uses:
- Authorization URL: https://app.attio.com/authorize
- Token URL: https://app.attio.com/oauth/token
- Access tokens are long-lived and non-expiring in the classic authorization-code
  flow (GET /v2/self reports exp: null); no refresh token is issued. Refresh is
  implemented defensively for the rare case a refresh_token IS returned.

Register an OAuth app at: https://app.attio.com/_workos/settings/developers
Documentation: https://docs.attio.com/rest-api/how-to/oauth
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

ATTIO_AUTH_URL = "https://app.attio.com/authorize"
ATTIO_TOKEN_URL = "https://app.attio.com/oauth/token"
ATTIO_SELF_URL = "https://api.attio.com/v2/self"

# Requested at authorization — the full set matching the node's API coverage.
# read-write on everything the node writes; read on the view-only surfaces.
# webhook:read-write is REQUIRED for the trigger node's webhook registration;
# call_recording:read lets the catch-all trigger receive call-recording.created.
ATTIO_DEFAULT_SCOPES = [
    "user_management:read",
    "record_permission:read-write",
    "object_configuration:read-write",
    "list_entry:read-write",
    "list_configuration:read-write",
    "comment:read-write",
    "note:read-write",
    "task:read-write",
    "meeting:read",
    "call_recording:read",
    "webhook:read-write",
    "file:read",
]


class AttioTokens(BaseModel):
    """Structured token response from Attio OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601, None when non-expiring
    scope: str = ""
    token_type: str = "Bearer"


class AttioUserInfo(BaseModel):
    """Workspace identity resolved from GET /v2/self."""

    id: str  # workspace_id
    name: str  # workspace_name
    email: Optional[str] = None
    workspace_member_id: Optional[str] = None


def get_attio_client_config() -> Tuple[str, str]:
    """Read the Attio OAuth client_id/client_secret from the environment."""
    client_id = os.environ.get("ATTIO_CLIENT_ID")
    client_secret = os.environ.get("ATTIO_CLIENT_SECRET")
    if not client_id:
        raise ValueError("ATTIO_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("ATTIO_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def get_attio_auth_url(scopes: list[str], state: str, redirect_uri: str) -> str:
    """Build the Attio authorization URL to redirect the user to."""
    client_id, _ = get_attio_client_config()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{ATTIO_AUTH_URL}?{urlencode(params)}"


def _expires_at_from(token_data: dict) -> Optional[str]:
    if "expires_in" in token_data and token_data["expires_in"]:
        return (
            datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))
        ).isoformat()
    return None


async def exchange_code_for_tokens(
    code: str, redirect_uri: str
) -> Tuple[AttioTokens, AttioUserInfo]:
    """Exchange an authorization code for an access token + workspace identity."""
    client_id, client_secret = get_attio_client_config()
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            ATTIO_TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_response.status_code != 200:
            logger.error(f"[AttioOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")
        token_data = token_response.json()
        if "error" in token_data:
            msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            raise ValueError(f"Token exchange failed: {msg}")

        tokens = AttioTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=_expires_at_from(token_data),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )
        user_info = await _get_user_info(client, tokens.access_token)
        logger.info(f"[AttioOAuth] Exchanged code for tokens (workspace {user_info.name})")
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> AttioUserInfo:
    """Resolve the workspace identity from GET /v2/self."""
    response = await client.get(
        ATTIO_SELF_URL, headers={"Authorization": f"Bearer {access_token}"}
    )
    if response.status_code != 200:
        logger.warning(f"[AttioOAuth] Failed to get workspace info: HTTP {response.status_code}")
        return AttioUserInfo(id="unknown", name="Attio Workspace")
    data = response.json()
    return AttioUserInfo(
        id=data.get("workspace_id", "unknown"),
        name=data.get("workspace_name", "Attio Workspace"),
        workspace_member_id=data.get("authorized_by_workspace_member_id"),
    )


async def refresh_access_token(refresh_token: str) -> AttioTokens:
    """Refresh an access token. Attio classic tokens don't rotate, but the token
    endpoint supports the refresh_token grant when a refresh token was issued."""
    client_id, client_secret = get_attio_client_config()
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            ATTIO_TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            logger.error(f"[AttioOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")
        token_data = response.json()
        if "error" in token_data:
            msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            raise ValueError(f"Token refresh failed: {msg}")
        return AttioTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=_expires_at_from(token_data),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """True if the token expires within buffer_minutes. Non-expiring tokens (no
    expires_at) are always valid."""
    if not expires_at:
        return False
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[AttioOAuth] Error parsing expiry time: {e}")
        return False
