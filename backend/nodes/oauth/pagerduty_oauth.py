"""
PagerDuty OAuth 2.0 utility for handling token exchange and refresh.
Manages the authorization_code flow for PagerDuty API access.

PagerDuty OAuth uses:
- Authorization URL: https://identity.pagerduty.com/oauth/authorize
- Token URL:         https://identity.pagerduty.com/oauth/token
- Refresh:           POST token URL with grant_type=refresh_token
- User info:         GET https://api.pagerduty.com/users/me  (returns {"user": {...}})

PagerDuty (Classic User OAuth) access tokens are prefixed ``pdus+_`` and used as
``Authorization: Bearer ...`` (distinct from REST API keys, which use
``Authorization: Token token=...``). Access tokens are long-lived but the
refresh token is also issued, so we refresh on expiry. PagerDuty rotates the
refresh token on each refresh; we always persist the value the refresh response
returns (and fall back to the existing one if it omits a new one).

client_id / client_secret default to the PAGERDUTY_CLIENT_ID /
PAGERDUTY_CLIENT_SECRET env vars but accept user-supplied values so a "bring your
own app" custom OAuth client (x-oauth-supports-custom-client) can be used.

Documentation: https://developer.pagerduty.com/docs/oauth-functionality
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PAGERDUTY_AUTH_URL = "https://identity.pagerduty.com/oauth/authorize"
PAGERDUTY_TOKEN_URL = "https://identity.pagerduty.com/oauth/token"
PAGERDUTY_USERINFO_URL = "https://api.pagerduty.com/users/me"


class PagerDutyTokens(BaseModel):
    """Structured token response from PagerDuty OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "Bearer"


class PagerDutyUserInfo(BaseModel):
    """User info from PagerDuty (GET /users/me)."""

    id: str
    name: str
    email: Optional[str] = None


def get_pagerduty_client_config() -> Tuple[str, str]:
    """Get PagerDuty OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("PAGERDUTY_CLIENT_ID")
    client_secret = os.environ.get("PAGERDUTY_CLIENT_SECRET")

    if not client_id:
        raise ValueError("PAGERDUTY_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("PAGERDUTY_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_pagerduty_client_config()


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[PagerDutyTokens, PagerDutyUserInfo]:
    """Exchange authorization code for access token, then fetch user info.

    Args:
        code: Authorization code from PagerDuty OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        Tuple of (PagerDutyTokens, PagerDutyUserInfo)

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
        token_response = await client.post(
            PAGERDUTY_TOKEN_URL, data=data, headers=headers
        )

        if token_response.status_code != 200:
            logger.error(
                f"[PagerDutyOAuth] Token exchange failed: HTTP {token_response.status_code}"
            )
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[PagerDutyOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        expires_at = None
        if "expires_in" in token_data:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"])
            ).isoformat()

        tokens = PagerDutyTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        user_info = await _get_user_info(client, tokens.access_token)

        logger.info(
            f"[PagerDutyOAuth] Successfully exchanged code for tokens for user {user_info.name}"
        )
        return tokens, user_info


async def _get_user_info(
    client: httpx.AsyncClient, access_token: str
) -> PagerDutyUserInfo:
    """Fetch user info from PagerDuty's GET /users/me (returns {"user": {...}})."""
    response = await client.get(
        PAGERDUTY_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.pagerduty+json;version=2",
        },
    )

    if response.status_code != 200:
        logger.warning(f"[PagerDutyOAuth] Failed to get user info: HTTP {response.status_code}")
        return PagerDutyUserInfo(id="unknown", name="Unknown")

    payload = response.json()
    me = payload.get("user", payload) if isinstance(payload, dict) else {}
    return PagerDutyUserInfo(
        id=str(me.get("id", "unknown")),
        name=me.get("name", "Unknown"),
        email=me.get("email"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> PagerDutyTokens:
    """Refresh an expired access token using the refresh token.

    PagerDuty may rotate the refresh token on each refresh; we persist whatever
    the response returns and fall back to the existing one if it's omitted (the
    freshen choke point only overwrites refresh_token when present).

    Args:
        refresh_token: The refresh token stored in credentials
        client_id / client_secret: optional user-supplied OAuth client

    Returns:
        New PagerDutyTokens with updated access_token

    Raises:
        ValueError: If refresh fails
    """
    cid, csecret = _resolve_client(client_id, client_secret)

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "client_id": cid,
        "client_secret": csecret,
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(PAGERDUTY_TOKEN_URL, data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"[PagerDutyOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[PagerDutyOAuth] Token refresh failed: {error_msg}")
            error_code = (
                token_data.get("error") if isinstance(token_data, dict) else None
            )
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

        tokens = PagerDutyTokens(
            access_token=token_data["access_token"],
            # Keep the existing refresh token if the provider doesn't return a
            # fresh one on this refresh.
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[PagerDutyOAuth] Successfully refreshed access token")
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
        logger.error(f"[PagerDutyOAuth] Error parsing expiry time: {e}")
        return False


def get_pagerduty_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the PagerDuty OAuth authorization URL.

    PagerDuty expects space-delimited scopes.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in the URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        client_id: optional user-supplied OAuth client id

    Returns:
        Full authorization URL to redirect the user to
    """
    cid = client_id or get_pagerduty_client_config()[0]

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{PAGERDUTY_AUTH_URL}?{urlencode(params)}"


# Granular Scoped-OAuth scopes covering every scoped-OAuth-supporting endpoint the
# PagerDuty node implements (derived from PagerDuty's REST OpenAPI schema). Newer
# endpoints such as Audit Records ONLY accept Scoped OAuth — the classic read/write
# scopes cannot reach them (403 "Token missing required scopes"). Single source of
# truth: imported by the node's x-oauth-scopes and the frontend authorize route.
#
# NOTE: these must also be enabled on the PagerDuty app registration (console) —
# the token only carries scopes the app is configured to grant. Endpoints without
# a granular scope (Automation Actions, Response Plays — plan-gated/classic-only,
# and the Events API which uses a routing key) are intentionally not listed.
#
# Four entries here were previously invalid strings PagerDuty does not define:
# contact_methods.read/write, notifications.read and instances.write. The real
# scopes are namespaced under their parent resource — users:contact_methods.*,
# users:notifications.read, incident_workflows:instances.write — so the console
# registration may still hold the old, meaningless names.
PAGERDUTY_DEFAULT_SCOPES = [
    "abilities.read",
    "addons.read",
    "addons.write",
    "analytics.read",
    "analytics.write",
    "audit_records.read",
    "change_events.read",
    "custom_fields.read",
    "custom_fields.write",
    "escalation_policies.read",
    "escalation_policies.write",
    "event_orchestrations.read",
    "event_orchestrations.write",
    "event_rules.read",
    "event_rules.write",
    "extension_schemas.read",
    "extensions.read",
    "extensions.write",
    "incident_workflows.read",
    "incident_workflows.write",
    "incident_workflows:instances.write",
    "incidents.read",
    "incidents.write",
    "licenses.read",
    "oncalls.read",
    "priorities.read",
    "schedules.read",
    "schedules.write",
    "services.read",
    "services.write",
    "status_dashboards.read",
    "status_pages.read",
    "status_pages.write",
    "subscribers.read",
    "subscribers.write",
    "tags.read",
    "tags.write",
    "teams.read",
    "teams.write",
    "templates.read",
    "templates.write",
    "users.read",
    "users.write",
    "users:contact_methods.read",
    "users:contact_methods.write",
    # users:notifications.read (GET /notifications) is in PagerDuty's OpenAPI,
    # but the app-registration console offers no row that grants it (verified
    # 2026-07-22), and requesting an ungrantable scope breaks connect —
    # list_notifications sits in the registry's unmapped list instead.
    "vendors.read",
    "webhook_subscriptions.read",
    "webhook_subscriptions.write",
]
