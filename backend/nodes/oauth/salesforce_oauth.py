"""
Salesforce OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 Web Server Flow for Salesforce API access.

Salesforce OAuth uses:
- Authorization URL: https://login.salesforce.com/services/oauth2/authorize
- Token URL: https://login.salesforce.com/services/oauth2/token
- For sandbox: https://test.salesforce.com/...
- Access tokens typically expire after 2 hours (configurable per org)
- Refresh tokens are provided and should be used to get new access tokens

Documentation: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_oauth_and_connected_apps.htm
"""

import os
import logging
import base64
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel, field_validator

from utils.ssrf import assert_exact_url_origin, normalize_provider_https_origin

logger = logging.getLogger(__name__)

SALESFORCE_AUTH_URL = "https://login.salesforce.com/services/oauth2/authorize"
SALESFORCE_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"
SALESFORCE_SANDBOX_AUTH_URL = "https://test.salesforce.com/services/oauth2/authorize"
SALESFORCE_SANDBOX_TOKEN_URL = "https://test.salesforce.com/services/oauth2/token"
SALESFORCE_LOGIN_ORIGIN = "https://login.salesforce.com"
SALESFORCE_SANDBOX_ORIGIN = "https://test.salesforce.com"


def normalize_salesforce_instance_url(value: str) -> str:
    """Validate and canonicalize a Salesforce-owned tenant origin."""
    return normalize_provider_https_origin(
        value,
        "salesforce.com",
        field_name="Salesforce instance URL",
        allow_nested_labels=True,
    )


class SalesforceTokens(BaseModel):
    """Structured token response from Salesforce OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    instance_url: str  # The Salesforce instance URL (e.g., https://na1.salesforce.com)
    expires_at: str  # ISO 8601 timestamp
    token_type: str = "Bearer"
    scope: Optional[str] = None

    @field_validator("instance_url")
    @classmethod
    def validate_instance_url(cls, value: str) -> str:
        return normalize_salesforce_instance_url(value)


class SalesforceUserInfo(BaseModel):
    """User info from Salesforce"""

    user_id: str
    organization_id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None


def get_salesforce_client_config() -> Tuple[str, str]:
    """
    Get Salesforce OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("SALESFORCE_CLIENT_ID")
    client_secret = os.environ.get("SALESFORCE_CLIENT_SECRET")

    if not client_id:
        raise ValueError("SALESFORCE_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("SALESFORCE_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    is_sandbox: bool = False,
    code_verifier: Optional[str] = None,
) -> Tuple[SalesforceTokens, SalesforceUserInfo]:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from Salesforce OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        is_sandbox: Whether to use sandbox endpoints
        code_verifier: PKCE code verifier (required if PKCE was used in authorization)

    Returns:
        Tuple of (SalesforceTokens, SalesforceUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_salesforce_client_config()
    token_url = SALESFORCE_SANDBOX_TOKEN_URL if is_sandbox else SALESFORCE_TOKEN_URL

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }

    # Add PKCE code_verifier if provided
    if code_verifier:
        data["code_verifier"] = code_verifier

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            error_data = token_response.json()
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[SalesforceOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # Salesforce returns issued_at (Unix timestamp in ms) instead of expires_in
        # Default token lifetime is 2 hours (7200 seconds)
        issued_at_ms = int(
            token_data.get("issued_at", datetime.now(timezone.utc).timestamp() * 1000)
        )
        expires_in = 7200  # 2 hours default
        expires_at = datetime.fromtimestamp(
            issued_at_ms / 1000, tz=timezone.utc
        ) + timedelta(seconds=expires_in)

        tokens = SalesforceTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            instance_url=token_data["instance_url"],
            expires_at=expires_at.isoformat(),
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope"),
        )

        # Get user info from the id URL provided in token response
        id_url = token_data.get("id")
        if id_url:
            identity_origin = (
                SALESFORCE_SANDBOX_ORIGIN if is_sandbox else SALESFORCE_LOGIN_ORIGIN
            )
            assert_exact_url_origin(id_url, identity_origin)
            userinfo_response = await client.get(
                id_url,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
            )

            if userinfo_response.status_code == 200:
                userinfo_data = userinfo_response.json()
                user_info = SalesforceUserInfo(
                    user_id=userinfo_data.get("user_id", "unknown"),
                    organization_id=userinfo_data.get("organization_id", "unknown"),
                    username=userinfo_data.get("username"),
                    display_name=userinfo_data.get("display_name"),
                    email=userinfo_data.get("email"),
                )
            else:
                logger.warning(
                    f"[SalesforceOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
                )
                user_info = SalesforceUserInfo(
                    user_id="unknown", organization_id="unknown"
                )
        else:
            user_info = SalesforceUserInfo(user_id="unknown", organization_id="unknown")

        logger.info(
            f"[SalesforceOAuth] Successfully exchanged code for tokens for user {user_info.user_id}"
        )
        return tokens, user_info


async def refresh_access_token(
    refresh_token: str,
    instance_url: str,
    is_sandbox: bool = False,
) -> SalesforceTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials
        instance_url: The Salesforce instance URL
        is_sandbox: Whether to use sandbox endpoints

    Returns:
        New SalesforceTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails (token revoked, etc.)
    """
    client_id, client_secret = get_salesforce_client_config()
    instance_url = normalize_salesforce_instance_url(instance_url)
    token_url = SALESFORCE_SANDBOX_TOKEN_URL if is_sandbox else SALESFORCE_TOKEN_URL

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[SalesforceOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(error_data, dict):
                error_code = error_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        # Calculate new expiry time
        issued_at_ms = int(
            token_data.get("issued_at", datetime.now(timezone.utc).timestamp() * 1000)
        )
        expires_in = 7200  # 2 hours default
        expires_at = datetime.fromtimestamp(
            issued_at_ms / 1000, tz=timezone.utc
        ) + timedelta(seconds=expires_in)

        tokens = SalesforceTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", refresh_token),
            instance_url=token_data.get("instance_url", instance_url),
            expires_at=expires_at.isoformat(),
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope"),
        )

        logger.info("[SalesforceOAuth] Successfully refreshed access token")
        return tokens


def is_token_expired(expires_at: str, buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_minutes: Consider expired if expires within this many minutes

    Returns:
        True if expired or expiring soon
    """
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[SalesforceOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_salesforce_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    is_sandbox: bool = False,
) -> str:
    """
    Generate Salesforce OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        is_sandbox: Whether to use sandbox endpoints

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_salesforce_client_config()
    auth_url = SALESFORCE_SANDBOX_AUTH_URL if is_sandbox else SALESFORCE_AUTH_URL

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{auth_url}?{query_string}"


# Standard scopes for Salesforce API access
SALESFORCE_FULL_SCOPES = [
    "api",  # Access and manage your data
    "refresh_token",  # Perform requests on your behalf at any time
    "full",  # Full access (includes api, web, and refresh_token)
]

# Minimal scopes for read-only access
SALESFORCE_READ_SCOPES = [
    "api",
    "refresh_token",
]
