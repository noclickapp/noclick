"""
Airtable OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 with PKCE flow for Airtable API access.

Airtable OAuth uses:
- Authorization URL: https://airtable.com/oauth2/v1/authorize
- Token URL: https://airtable.com/oauth2/v1/token
- Access tokens expire after 60 minutes
- Refresh tokens are provided and should be used to get new access tokens

Documentation: https://airtable.com/developers/web/api/oauth-reference
"""

import os
import logging
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

AIRTABLE_AUTH_URL = "https://airtable.com/oauth2/v1/authorize"
AIRTABLE_TOKEN_URL = "https://airtable.com/oauth2/v1/token"
AIRTABLE_USERINFO_URL = "https://api.airtable.com/v0/meta/whoami"


class AirtableTokens(BaseModel):
    """Structured token response from Airtable OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class AirtableUserInfo(BaseModel):
    """User info from Airtable"""

    id: str
    email: Optional[str] = None


def get_airtable_client_config() -> Tuple[str, Optional[str]]:
    """
    Get Airtable OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret) - client_secret may be None for public clients

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("AIRTABLE_CLIENT_ID")
    client_secret = os.environ.get("AIRTABLE_CLIENT_SECRET")

    if not client_id:
        raise ValueError("AIRTABLE_CLIENT_ID environment variable is required")

    return client_id, client_secret


def generate_pkce_verifier() -> str:
    """
    Generate a PKCE code verifier.

    Returns:
        A cryptographically random code verifier string (43-128 chars)
    """
    return secrets.token_urlsafe(64)[:128]


def generate_pkce_challenge(verifier: str) -> str:
    """
    Generate a PKCE code challenge from a code verifier.

    Args:
        verifier: The code verifier string

    Returns:
        Base64url-encoded SHA256 hash of the verifier
    """
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> Tuple[AirtableTokens, AirtableUserInfo]:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from Airtable OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        code_verifier: PKCE code verifier used during authorization

    Returns:
        Tuple of (AirtableTokens, AirtableUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_airtable_client_config()

    # Prepare authorization header
    if client_secret:
        # Confidential client - use Basic auth
        auth_string = f"{client_id}:{client_secret}"
        auth_header = base64.b64encode(auth_string.encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
    else:
        # Public client - send client_id in body
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    if not client_secret:
        data["client_id"] = client_id

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            AIRTABLE_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if token_response.status_code != 200:
            error_data = token_response.json()
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[AirtableOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # Calculate expiry time (Airtable tokens expire in 60 minutes)
        expires_in = token_data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = AirtableTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info
        userinfo_response = await client.get(
            AIRTABLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens.access_token}"},
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                f"[AirtableOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            # Don't fail - user info is optional
            user_info = AirtableUserInfo(id="unknown")
        else:
            userinfo_data = userinfo_response.json()
            user_info = AirtableUserInfo(
                id=userinfo_data.get("id", "unknown"),
                email=userinfo_data.get("email"),
            )

        logger.info(
            f"[AirtableOAuth] Successfully exchanged code for tokens for user {user_info.id}"
        )
        return tokens, user_info


async def refresh_access_token(refresh_token: str) -> AirtableTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials

    Returns:
        New AirtableTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails (token revoked, etc.)
    """
    client_id, client_secret = get_airtable_client_config()

    # Prepare authorization header
    if client_secret:
        auth_string = f"{client_id}:{client_secret}"
        auth_header = base64.b64encode(auth_string.encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
    else:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    if not client_secret:
        data["client_id"] = client_id

    async with httpx.AsyncClient() as client:
        response = await client.post(
            AIRTABLE_TOKEN_URL,
            data=data,
            headers=headers,
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[AirtableOAuth] Token refresh failed: {error_msg}")
            error_code = None
            if isinstance(error_data, dict):
                error_code = error_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = AirtableTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get(
                "refresh_token", refresh_token
            ),  # May get new refresh token
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[AirtableOAuth] Successfully refreshed access token")
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
        logger.error(f"[AirtableOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_airtable_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    code_challenge: str,
) -> str:
    """
    Generate Airtable OAuth authorization URL with PKCE.

    Args:
        scopes: List of OAuth scopes to request (space-delimited in URL)
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback
        code_challenge: PKCE code challenge (generated from code_verifier)

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_airtable_client_config()

    # Build query parameters
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    # URL encode parameters
    from urllib.parse import urlencode

    query_string = urlencode(params)
    return f"{AIRTABLE_AUTH_URL}?{query_string}"


# Standard scopes for full Airtable access
AIRTABLE_FULL_SCOPES = [
    "data.records:read",
    "data.records:write",
    "data.recordComments:read",
    "data.recordComments:write",
    "schema.bases:read",
    "schema.bases:write",
    "webhook:manage",
]
