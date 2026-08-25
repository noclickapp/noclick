"""
Supabase Management API OAuth utility for handling token exchange, refresh, and project key retrieval.

Supabase OAuth uses PKCE flow with:
- Authorization URL: https://api.supabase.com/v1/oauth/authorize
- Token URL: https://api.supabase.com/v1/oauth/token
- Access tokens expire after ~1 hour (respects expires_in from response)
- Refresh tokens are rotated on each use

After token exchange, project API keys (anon + service_role) are fetched once via the
Management API and cached in the credential so subsequent node executions use them directly
without additional Management API calls.

Documentation: https://supabase.com/docs/guides/platform/oauth-apps/build-a-supabase-integration
"""

import base64
import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import httpx
from opentelemetry import trace
from pydantic import BaseModel
from nodes.core.oauth_refresh import require_rotated_refresh_token

logger = logging.getLogger(__name__)

SUPABASE_AUTH_URL = "https://api.supabase.com/v1/oauth/authorize"
SUPABASE_TOKEN_URL = "https://api.supabase.com/v1/oauth/token"
SUPABASE_MANAGEMENT_API = "https://api.supabase.com/v1"


class SupabaseTokens(BaseModel):
    """Structured token response from Supabase OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str  # ISO 8601 timestamp
    token_type: str = "Bearer"


class SupabaseProjectKeys(BaseModel):
    """API keys fetched from the Supabase Management API for a specific project."""

    anon_key: Optional[str] = None
    service_role_key: Optional[str] = None


def get_supabase_client_config() -> Tuple[str, str]:
    """Return (client_id, client_secret) from environment variables."""
    client_id = os.environ.get("SUPABASE_CLIENT_ID")
    client_secret = os.environ.get("SUPABASE_CLIENT_SECRET")
    if not client_id:
        raise ValueError("SUPABASE_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("SUPABASE_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


def generate_pkce_verifier() -> str:
    """Generate a cryptographically random PKCE code verifier (up to 128 chars)."""
    return secrets.token_urlsafe(64)[:128]


def generate_pkce_challenge(verifier: str) -> str:
    """Generate the S256 PKCE code challenge from a verifier."""
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def extract_project_ref(project_url: str) -> str:
    """
    Extract the project reference ID from a Supabase project URL.

    Example: 'https://xxxx.supabase.co' → 'xxxx'
    """
    match = re.match(r"https?://([^.]+)\.supabase\.co", project_url.strip())
    if not match:
        raise ValueError(
            f"Invalid Supabase project URL: {project_url!r}. "
            "Expected format: https://<ref>.supabase.co"
        )
    return match.group(1)


def get_supabase_auth_url(
    state: str,
    redirect_uri: str,
    code_challenge: str,
) -> str:
    """Build the Supabase OAuth authorization URL with PKCE."""
    client_id, _ = get_supabase_client_config()
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{SUPABASE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> SupabaseTokens:
    """
    Exchange an authorization code for access + refresh tokens.

    Args:
        code: Authorization code from the OAuth callback
        redirect_uri: Must exactly match the URI used during authorization
        code_verifier: PKCE verifier (plain text) corresponding to the code_challenge sent
    """
    client_id, client_secret = get_supabase_client_config()
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            SUPABASE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )

    if response.status_code not in (200, 201):
        error_data = response.json() if response.text else {}
        error_msg = error_data.get(
            "error_description", error_data.get("error", "Unknown error")
        )
        logger.error(
            f"[SupabaseOAuth] Token exchange failed ({response.status_code}): {error_msg}"
        )
        raise ValueError(f"Token exchange failed: {error_msg}")

    token_data = response.json()
    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    logger.info("[SupabaseOAuth] Token exchange successful")
    return SupabaseTokens(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at.isoformat(),
        token_type=token_data.get("token_type", "Bearer"),
    )


async def refresh_access_token(refresh_token: str) -> SupabaseTokens:
    """
    Refresh an expired access token.

    Note: Supabase rotates refresh tokens — the response contains a new refresh token
    that must replace the old one.
    """
    client_id, client_secret = get_supabase_client_config()
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            SUPABASE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )

    if response.status_code not in (200, 201):
        error_data = response.json() if response.text else {}
        error_msg = error_data.get(
            "error_description", error_data.get("error", "Unknown error")
        )
        logger.error(
            f"[SupabaseOAuth] Token refresh failed ({response.status_code}): {error_msg}"
        )
        error_code = None
        if isinstance(error_data, dict):
            error_code = error_data.get("error")
        span = trace.get_current_span()
        if span and span.is_recording() and error_code:
            span.set_attribute("oauth.provider_error_code", str(error_code))
        raise ValueError(f"Token refresh failed: {error_msg}")

    token_data = response.json()
    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    logger.info("[SupabaseOAuth] Token refresh successful")
    return SupabaseTokens(
        access_token=token_data["access_token"],
        # Supabase rotates refresh tokens — a response without one means the
        # consumed token is all we have; raise instead of bricking the next refresh.
        refresh_token=require_rotated_refresh_token(token_data, provider="supabase"),
        expires_at=expires_at.isoformat(),
        token_type=token_data.get("token_type", "Bearer"),
    )


async def fetch_project_api_keys(
    access_token: str, project_ref: str
) -> SupabaseProjectKeys:
    """
    Fetch the anon and service_role API keys for a project via the Management API.

    Requires the `secrets:read` scope on the OAuth token.
    Keys are cached in the credential after this call — no need to re-fetch on each execution.
    """
    anon_key: Optional[str] = None
    service_role_key: Optional[str] = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{SUPABASE_MANAGEMENT_API}/projects/{project_ref}/api-keys",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

    if response.status_code == 200:
        keys = response.json()
        for key_info in keys:
            name = (key_info.get("name") or "").lower()
            api_key = key_info.get("api_key", "")
            if "anon" in name:
                anon_key = api_key
            elif "service_role" in name or "service" in name:
                service_role_key = api_key
        logger.info(
            f"[SupabaseOAuth] Fetched API keys for project {project_ref!r}: "
            f"anon={'yes' if anon_key else 'no'}, service_role={'yes' if service_role_key else 'no'}"
        )
    else:
        logger.warning(
            f"[SupabaseOAuth] Failed to fetch API keys for {project_ref!r} "
            f"({response.status_code}): HTTP {response.status_code}"
        )

    return SupabaseProjectKeys(anon_key=anon_key, service_role_key=service_role_key)


async def list_projects(access_token: str) -> List[dict]:
    """
    List all Supabase projects accessible with the given Management API access token.
    Returns a list of project dicts with at minimum 'id', 'name', 'ref', 'organization_id'.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{SUPABASE_MANAGEMENT_API}/projects",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
    if response.status_code != 200:
        logger.warning(
            f"[SupabaseOAuth] Failed to list projects ({response.status_code}): HTTP {response.status_code}"
        )
        return []
    projects = response.json()
    logger.info(f"[SupabaseOAuth] Found {len(projects)} project(s)")
    return projects if isinstance(projects, list) else []


def is_token_expired(expires_at: str, buffer_minutes: int = 5) -> bool:
    """Return True if the token is expired or will expire within buffer_minutes."""
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return (
            datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes)
            >= expiry_time
        )
    except (ValueError, TypeError) as e:
        logger.error(f"[SupabaseOAuth] Error parsing expiry time: {e}")
        return True  # Assume expired if we can't parse
