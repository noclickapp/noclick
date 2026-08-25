"""
PostHog OAuth 2.0 utility (public client + PKCE, CIMD registration).

PostHog's OAuth server is standards-clean (RFC 8414). Registration is via a
Client ID Metadata Document (CIMD): the ``client_id`` is literally an HTTPS URL to
a JSON document NoClick hosts (see docs/oauth) — supplied via POSTHOG_CLIENT_ID.
No client secret (public client, ``token_endpoint_auth_method: none``); the flow
is authorization_code + PKCE (S256, verifier from the frontend).

- Region-agnostic host: https://oauth.posthog.com (routes US/EU transparently).
- Authorize: {host}/oauth/authorize/   Token: {host}/oauth/token/  (trailing slash)
- Access tokens (``pha_...``) last ~10h; refresh tokens (``phr_...``) are SINGLE-USE
  and ROTATE — the new refresh token MUST be persisted every refresh (enforced via
  require_rotated_refresh_token, like Slack/Linear).
- After exchange, /oauth/userinfo/ yields identity + the region's data-plane base
  URL (posthog_base_url) that subsequent REST calls must target.

Docs: https://posthog.com/docs/api/oauth
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel

from nodes.core.oauth_refresh import require_rotated_refresh_token
from utils.ssrf import SSRFError, assert_exact_url_origin

logger = logging.getLogger(__name__)

POSTHOG_DATA_ORIGINS = (
    "https://us.posthog.com",
    "https://eu.posthog.com",
)


def normalize_posthog_oauth_base_url(value: str) -> str:
    """Return the canonical PostHog Cloud data origin for an OAuth grant.

    ``posthog_base_url`` arrives in provider userinfo and is persisted, so it
    must not become an arbitrary destination for the OAuth bearer on connect or
    on later executions. PostHog OAuth is Cloud-only; manually configured
    self-hosted API-key credentials keep their separate custom-host path.
    """
    raw = str(value or "").strip()
    try:
        parsed = httpx.URL(raw)
    except (TypeError, ValueError) as e:
        raise SSRFError("PostHog OAuth returned an invalid data URL") from e
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise SSRFError("PostHog OAuth data URL must be a provider origin")
    for origin in POSTHOG_DATA_ORIGINS:
        try:
            assert_exact_url_origin(raw, origin)
        except SSRFError:
            continue
        return origin
    raise SSRFError("PostHog OAuth data URL is not an approved PostHog Cloud origin")


def _oauth_host() -> str:
    return os.environ.get("POSTHOG_OAUTH_HOST", "https://oauth.posthog.com").rstrip("/")


def _authorize_url() -> str:
    return f"{_oauth_host()}/oauth/authorize/"


def _token_url() -> str:
    return f"{_oauth_host()}/oauth/token/"


def _userinfo_url() -> str:
    return f"{_oauth_host()}/oauth/userinfo/"


# Default OAuth scopes — mirror the personal-API-key scope model (resource:read/
# resource:write). Requesting broad read/write so the node's ops work; scopes are
# space-delimited. openid for the userinfo/identity lookup.
POSTHOG_DEFAULT_SCOPES = [
    "openid", "email",
    "project:read", "organization:read", "user:read",
    "insight:read", "insight:write", "dashboard:read", "dashboard:write",
    "feature_flag:read", "feature_flag:write", "experiment:read", "experiment:write",
    "query:read", "person:read", "person:write", "cohort:read", "cohort:write",
    "annotation:read", "annotation:write", "survey:read", "survey:write",
    "action:read", "action:write",
    "session_recording:read", "session_recording:write",
    "group:read",
    "organization_member:read", "organization_member:write",
    "event_definition:read", "property_definition:read",
    "hog_function:read", "hog_function:write",
    "notebook:read", "notebook:write", "early_access_feature:read", "early_access_feature:write",
    "batch_export:read", "activity_log:read",
]


def get_posthog_client_id() -> str:
    """Return the CIMD client_id URL from POSTHOG_CLIENT_ID."""
    client_id = os.environ.get("POSTHOG_CLIENT_ID")
    if not client_id:
        raise ValueError("POSTHOG_CLIENT_ID environment variable is required (the CIMD document URL)")
    return client_id


class PostHogTokens(BaseModel):
    """Structured token response from PostHog OAuth.

    ``scoped_organizations`` / ``scoped_teams`` mirror the access level the user
    picked on the consent screen (all / one organization / specific projects).
    A team-scoped token 403s on org-level endpoints, so scoped_teams is the
    AUTHORITATIVE project resolver for such grants — persist it on the credential.
    """

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601
    token_type: str = "Bearer"
    scope: str = ""
    scoped_organizations: Optional[list] = None
    scoped_teams: Optional[list] = None


class PostHogUserInfo(BaseModel):
    """Identity + region data-plane base URL from /oauth/userinfo/."""

    id: str
    name: str
    email: Optional[str] = None
    base_url: str = "https://us.posthog.com"
    region: str = "us"


def _expires_at(token_data: dict) -> Optional[str]:
    if "expires_in" not in token_data:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])).isoformat()


async def exchange_code_for_tokens(
    code: str, redirect_uri: str, code_verifier: str,
) -> Tuple[PostHogTokens, PostHogUserInfo]:
    """Exchange the authorization code (+ PKCE verifier) for tokens, then fetch
    identity + region base URL.

    Raises ValueError on failure.
    """
    client_id = get_posthog_client_id()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_token_url(), data=data, headers=headers)
        if resp.status_code != 200:
            logger.error(f"[PostHogOAuth] Token exchange failed: HTTP {resp.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {resp.status_code}")
        token_data = resp.json()
        if "error" in token_data:
            msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            raise ValueError(f"Token exchange failed: {msg}")

        # Initial exchange: refresh token present but not yet rotated.
        tokens = PostHogTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=_expires_at(token_data),
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope", ""),
            scoped_organizations=token_data.get("scoped_organizations") or None,
            scoped_teams=token_data.get("scoped_teams") or None,
        )
        user_info = await _get_user_info(client, tokens.access_token)
        logger.info(f"[PostHogOAuth] Exchanged code for tokens ({user_info.email or user_info.id}, region {user_info.region})")
        return tokens, user_info


async def _get_user_info(client: httpx.AsyncClient, access_token: str) -> PostHogUserInfo:
    """Identity + region base URL from /oauth/userinfo/."""
    try:
        resp = await client.get(_userinfo_url(), headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
        if resp.status_code != 200:
            logger.warning(f"[PostHogOAuth] userinfo failed: HTTP {resp.status_code}")
            return PostHogUserInfo(id="unknown", name="PostHog User")
        d = resp.json() or {}
        base_url = normalize_posthog_oauth_base_url(
            d.get("posthog_base_url") or "https://us.posthog.com"
        )
        region = d.get("posthog_region") or ("eu" if "eu." in base_url else "us")
        return PostHogUserInfo(
            id=str(d.get("sub") or d.get("email") or "unknown"),
            name=d.get("name") or d.get("email") or "PostHog User",
            email=d.get("email"),
            base_url=base_url.rstrip("/"),
            region=region,
        )
    except Exception as e:
        logger.warning(f"[PostHogOAuth] userinfo error: {e}")
        return PostHogUserInfo(id="unknown", name="PostHog User")


async def refresh_access_token(refresh_token: str) -> PostHogTokens:
    """Refresh with the single-use rotating refresh token.

    PostHog invalidates the previous access + refresh tokens and returns new ones;
    the new refresh token MUST be persisted (require_rotated_refresh_token raises if
    the response omits one rather than reusing the consumed token).

    Raises ValueError on failure.
    """
    client_id = get_posthog_client_id()
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_token_url(), data=data, headers=headers)
        if resp.status_code != 200:
            logger.error(f"[PostHogOAuth] Token refresh failed: HTTP {resp.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {resp.status_code}")
        token_data = resp.json()
        if "error" in token_data:
            msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            error_code = token_data.get("error") if isinstance(token_data, dict) else None
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {msg}")

        return PostHogTokens(
            access_token=token_data["access_token"],
            refresh_token=require_rotated_refresh_token(token_data, provider="posthog"),
            expires_at=_expires_at(token_data),
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope", ""),
        )


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry
    except (ValueError, TypeError) as e:
        logger.error(f"[PostHogOAuth] Error parsing expiry: {e}")
        return True


def get_posthog_auth_url(scopes: list[str], state: str, redirect_uri: str, code_challenge: str, client_id: Optional[str] = None) -> str:
    """Build the PostHog authorize URL (PKCE S256, public client)."""
    cid = client_id or get_posthog_client_id()
    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    return f"{_authorize_url()}?{urlencode(params)}"
