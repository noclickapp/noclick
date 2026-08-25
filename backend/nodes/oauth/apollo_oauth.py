"""
Apollo.io OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Apollo.io API access.

Apollo OAuth uses:
- Authorization URL: https://app.apollo.io/#/oauth/authorize
- Token URL: https://app.apollo.io/api/v1/oauth/token
- Access tokens expire after 30 days
- Refresh tokens are supported for automatic renewal

Documentation: https://docs.apollo.io/docs/use-oauth-20-authorization-flow-to-access-apollo-user-information-partners
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

APOLLO_AUTH_URL = "https://app.apollo.io/#/oauth/authorize"
APOLLO_TOKEN_URL = "https://app.apollo.io/api/v1/oauth/token"
APOLLO_USER_URL = "https://app.apollo.io/api/v1/users/api_profile"


class ApolloTokens(BaseModel):
    """Structured token response from Apollo OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    scope: str = ""
    token_type: str = "Bearer"


class ApolloUserInfo(BaseModel):
    """User info from Apollo"""

    id: str
    email: str
    name: Optional[str] = None
    team_id: Optional[str] = None
    team_name: Optional[str] = None


def get_apollo_client_config() -> Tuple[str, str]:
    """
    Get Apollo OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("APOLLO_CLIENT_ID")
    client_secret = os.environ.get("APOLLO_CLIENT_SECRET")

    if not client_id:
        raise ValueError("APOLLO_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("APOLLO_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[ApolloTokens, ApolloUserInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from Apollo OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (ApolloTokens, ApolloUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_apollo_client_config()

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            APOLLO_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            logger.error(f"[ApolloOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[ApolloOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Calculate expiry time (Apollo tokens expire after 30 days)
        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()
        else:
            # Default to 30 days if not provided
            expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        tokens = ApolloTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info
        userinfo_response = await client.get(
            APOLLO_USER_URL,
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
                "Accept": "application/json",
            },
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                f"[ApolloOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            user_info = ApolloUserInfo(id="unknown", email="unknown@unknown.com")
        else:
            userinfo_data = userinfo_response.json()
            user_data = userinfo_data.get("user", userinfo_data)
            user_info = ApolloUserInfo(
                id=str(user_data.get("id", "unknown")),
                email=user_data.get("email", "unknown@unknown.com"),
                name=user_data.get("name"),
                team_id=str(user_data.get("team_id"))
                if user_data.get("team_id")
                else None,
                team_name=user_data.get("team", {}).get("name")
                if user_data.get("team")
                else None,
            )

        logger.info(
            f"[ApolloOAuth] Successfully exchanged code for tokens for user {user_info.email}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> ApolloTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New ApolloTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails
    """
    client_id, client_secret = get_apollo_client_config()

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            APOLLO_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"[ApolloOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        token_data = response.json()

        # Check for error in response
        if "error" in token_data:
            error_msg = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"[ApolloOAuth] Token refresh failed: {error_msg}")
            raise ValueError(f"Token refresh failed: {error_msg}")

        # Calculate new expiry time
        expires_at = None
        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()
        else:
            # Default to 30 days if not provided
            expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        tokens = ApolloTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[ApolloOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon, False if still valid
    """
    if not expires_at:
        # No expiry set - assume valid
        return False

    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[ApolloOAuth] Error parsing expiry time: {e}")
        return False


def get_apollo_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Apollo OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_apollo_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "response_type": "code",
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{APOLLO_AUTH_URL}?{query_string}"


# Standard scopes for Apollo workflow operations (must match scopes approved on the OAuth client)
APOLLO_WORKFLOW_SCOPES = [
    "read_user_profile",
    "people_match", "people_bulk_match",
    "organizations_enrich", "organizations_bulk_enrich", "organizations_search", "organization_read",
    "mixed_people_api_search", "mixed_companies_search",
    "contacts_search", "contact_read", "contact_write", "contact_update",
    "contacts_bulk_create", "contacts_bulk_update",
    "contact_stages_list", "contact_stages_update", "contact_owners_update",
    "account_read", "account_write", "account_update", "accounts_search",
    "account_bulk_create", "account_stages_list", "account_stages_update", "account_owners_update",
    "opportunity_read", "opportunity_write", "opportunity_update", "opportunities_list", "opportunity_stages_list",
    "emailer_campaigns_search", "emailer_campaigns_create", "emailer_campaigns_update",
    "emailer_campaigns_add_contact_ids", "emailer_campaigns_remove_or_stop_contact_ids",
    "emailer_schedules_list", "emailer_messages_search",
    "tasks_create", "tasks_list",
    "notes_list", "users_list", "tags_list",
    "custom_fields_list", "custom_field_write",
    "lists_create", "lists_update", "lists_add_entities", "lists_remove_entities",
    "organizations_job_posting", "organizations_news_articles",
    "person_read",
]
