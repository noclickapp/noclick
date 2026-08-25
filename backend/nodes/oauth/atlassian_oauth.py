"""
Atlassian OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 (3LO) flow for Jira and Confluence API access.

Atlassian OAuth uses:
- Authorization URL: https://auth.atlassian.com/authorize
- Token URL: https://auth.atlassian.com/oauth/token
- Accessible Resources: https://api.atlassian.com/oauth/token/accessible-resources

Documentation: https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional, List
import httpx
from opentelemetry import trace
from pydantic import BaseModel

from nodes.scopes.jira import JIRA_REQUESTED_SCOPES

logger = logging.getLogger(__name__)

ATLASSIAN_AUTH_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"


class AtlassianTokens(BaseModel):
    """Structured token response from Atlassian OAuth"""

    access_token: str
    refresh_token: str
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class AtlassianResource(BaseModel):
    """Accessible Atlassian resource (Jira/Confluence site)"""

    id: str  # cloud_id
    name: str
    url: str
    scopes: List[str]
    avatar_url: Optional[str] = None


class AtlassianUserInfo(BaseModel):
    """User info from Atlassian"""

    cloud_id: str
    site_name: str
    site_url: str
    email: Optional[str] = None


class AtlassianSiteAccessError(ValueError):
    """Raised when the authorized account cannot access the requested Jira site."""

    def __init__(self, requested_site: str, available_sites: List[dict]):
        self.requested_site = requested_site
        self.available_sites = available_sites
        sites_label = ", ".join(
            str(site.get("url") or site.get("name") or site.get("id"))
            for site in available_sites
        )
        super().__init__(
            f"Your Atlassian account does not have access to {requested_site}. "
            f"Available Jira sites: {sites_label or 'none'}."
        )


def get_atlassian_client_config() -> Tuple[str, str]:
    """
    Get Atlassian OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("ATLASSIAN_CLIENT_ID")
    client_secret = os.environ.get("ATLASSIAN_CLIENT_SECRET")

    if not client_id:
        raise ValueError("ATLASSIAN_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("ATLASSIAN_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    jira_site: Optional[str] = None,
) -> Tuple[AtlassianTokens, AtlassianUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from Atlassian OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (AtlassianTokens, AtlassianUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_atlassian_client_config()

    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            ATLASSIAN_TOKEN_URL,
            json=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            logger.error(
                f"[AtlassianOAuth] Token exchange failed: HTTP {token_response.status_code}"
            )
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[AtlassianOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Calculate expiry time
        expires_in = token_data.get("expires_in", 3600)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        tokens = AtlassianTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get accessible resources (Jira/Confluence sites)
        resources_response = await client.get(
            ATLASSIAN_RESOURCES_URL,
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
                "Accept": "application/json",
            },
        )

        if resources_response.status_code != 200:
            logger.error(
                f"[AtlassianOAuth] Failed to get accessible resources: HTTP {resources_response.status_code}"
            )
            raise ValueError("Failed to get accessible Jira sites")

        resources = resources_response.json()

        if not resources:
            raise ValueError(
                "No accessible Jira sites found. Please ensure you have access to at least one Jira site."
            )

        primary_resource = _select_jira_resource(resources, jira_site)
        user_info = AtlassianUserInfo(
            cloud_id=primary_resource["id"],
            site_name=primary_resource["name"],
            site_url=primary_resource["url"],
            email=None,  # Not directly available in resources endpoint
        )

        logger.info(
            f"[AtlassianOAuth] Successfully exchanged code for tokens for site {user_info.site_name}"
        )
        return tokens, user_info


def _normalize_jira_site(site: str) -> str:
    normalized = site.strip().lower()
    normalized = normalized.removeprefix("https://").removeprefix("http://")
    normalized = normalized.split("/", 1)[0]
    normalized = normalized.removesuffix(".atlassian.net")
    return normalized


def _select_jira_resource(
    resources: List[dict],
    jira_site: Optional[str],
) -> dict:
    if not jira_site:
        return resources[0]

    requested = _normalize_jira_site(jira_site)
    for resource in resources:
        resource_url = str(resource.get("url", ""))
        resource_name = str(resource.get("name", ""))
        if requested in {
            _normalize_jira_site(resource_url),
            _normalize_jira_site(resource_name),
        }:
            return resource

    raise AtlassianSiteAccessError(jira_site, resources)


async def refresh_access_token(refresh_token: str) -> AtlassianTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New AtlassianTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails
    """
    client_id, client_secret = get_atlassian_client_config()

    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            ATLASSIAN_TOKEN_URL,
            json=data,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"[AtlassianOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[AtlassianOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(token_data, dict):
                error_code = token_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 3600)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        tokens = AtlassianTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get(
                "refresh_token", refresh_token
            ),  # May get new refresh token
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[AtlassianOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: str, buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if still valid
    """
    if not expires_at:
        return True

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[AtlassianOAuth] Error parsing expiry time: {e}")
        return True  # Assume expired if we can't parse


def get_atlassian_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Atlassian OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_atlassian_client_config()

    # Build query parameters
    params = {
        "audience": "api.atlassian.com",
        "client_id": client_id,
        "scope": " ".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{ATLASSIAN_AUTH_URL}?{query_string}"


# Standard scopes for Jira workflow operations. Same derived list the node's
# `x-oauth-scopes` publishes — see nodes/scopes/jira.py, which is the only place
# a Jira scope may be added.
JIRA_WORKFLOW_SCOPES = list(JIRA_REQUESTED_SCOPES)

# Minimal scopes for read-only access
JIRA_READ_ONLY_SCOPES = [
    "read:jira-work",
    "read:jira-user",
    "offline_access",
]
