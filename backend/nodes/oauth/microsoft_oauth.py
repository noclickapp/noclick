"""
Microsoft OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Microsoft Graph API (Outlook, OneDrive, etc.).
Uses Azure AD v2.0 endpoint for modern authentication.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Microsoft OAuth endpoints (using common tenant for multi-tenant apps)
MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_GRAPH_URL = "https://graph.microsoft.com/v1.0"
MICROSOFT_REVOKE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/logout"


class MicrosoftTokens(BaseModel):
    """Structured token response from Microsoft OAuth"""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: str  # ISO 8601 timestamp
    scope: str
    token_type: str = "Bearer"


class MicrosoftUserInfo(BaseModel):
    """User info from Microsoft Graph"""

    email: str
    name: Optional[str] = None
    id: Optional[str] = None


def get_microsoft_client_config() -> Tuple[str, str]:
    """
    Get Microsoft OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("MICROSOFT_CLIENT_ID")
    client_secret = os.environ.get("MICROSOFT_CLIENT_SECRET")

    if not client_id:
        raise ValueError("MICROSOFT_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("MICROSOFT_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[MicrosoftTokens, MicrosoftUserInfo]:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from Microsoft OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (MicrosoftTokens, MicrosoftUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_microsoft_client_config()

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            error_data = token_response.json()
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[MicrosoftOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()

        # Calculate expiry time
        expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = MicrosoftTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Get user info from Microsoft Graph
        userinfo_response = await client.get(
            f"{MICROSOFT_GRAPH_URL}/me",
            headers={"Authorization": f"Bearer {tokens.access_token}"},
        )

        if userinfo_response.status_code != 200:
            logger.error(
                f"[MicrosoftOAuth] Failed to get user info: HTTP {userinfo_response.status_code}"
            )
            raise ValueError("Failed to get user info from Microsoft Graph")

        userinfo_data = userinfo_response.json()

        # Microsoft Graph returns mail or userPrincipalName for email
        email = userinfo_data.get("mail") or userinfo_data.get("userPrincipalName", "")

        user_info = MicrosoftUserInfo(
            email=email,
            name=userinfo_data.get("displayName"),
            id=userinfo_data.get("id"),
        )

        logger.info(
            f"[MicrosoftOAuth] Successfully exchanged code for tokens for user {user_info.email}"
        )
        return tokens, user_info


async def refresh_access_token(
    refresh_token: str, scope: Optional[str] = None
) -> MicrosoftTokens:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token stored in credentials
        scope: Optional space-delimited scope to request. Azure AD honors a
            ``scope`` on the refresh-token grant to mint a token for a SPECIFIC
            resource/audience. OneLake needs this because its DFS/Table surface
            and its Fabric Core surface have different ``aud`` claims, so a
            single token can't cover both — the node redeems the same refresh
            token once per audience. Omitted (None) preserves the original
            behavior (token for the originally-consented default resource).

    Returns:
        New MicrosoftTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails (token revoked, etc.)
    """
    client_id, client_secret = get_microsoft_client_config()

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if scope:
        payload["scope"] = scope

    async with httpx.AsyncClient() as client:
        response = await client.post(
            MICROSOFT_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get(
                "error_description", error_data.get("error", "Unknown error")
            )
            logger.error(f"[MicrosoftOAuth] Token refresh failed: {error_msg}")
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

        # Microsoft may return a new refresh token
        new_refresh_token = token_data.get("refresh_token", refresh_token)

        tokens = MicrosoftTokens(
            access_token=token_data["access_token"],
            refresh_token=new_refresh_token,
            expires_at=expires_at.isoformat(),
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[MicrosoftOAuth] Successfully refreshed access token")
        return tokens


async def validate_token(access_token: str) -> bool:
    """
    Validate if an access token is still valid by making a test API call.

    Args:
        access_token: The access token to validate

    Returns:
        True if valid, False if expired/invalid
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{MICROSOFT_GRAPH_URL}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        return response.status_code == 200


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
        logger.error(f"[MicrosoftOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_microsoft_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Microsoft OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request
        state: State parameter for CSRF protection (should be base64-encoded JSON)
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_microsoft_client_config()

    # Microsoft requires offline_access scope for refresh tokens
    all_scopes = list(set(scopes) | {"offline_access", "openid", "profile", "email"})

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(all_scopes),
        "response_mode": "query",
        "prompt": "consent",  # Always show consent to ensure refresh token
        "state": state,
    }

    query_string = "&".join(
        f'{k}={httpx.URL("", params={k: v}).params[k]}' for k, v in params.items()
    )
    return f"{MICROSOFT_AUTH_URL}?{query_string}"


async def revoke_token(token: str) -> bool:
    """
    Revoke a Microsoft OAuth token.

    Note: Microsoft's logout endpoint doesn't actually invalidate tokens,
    it just clears the session. Tokens remain valid until expiry.
    For true revocation, use Azure AD admin center.

    Args:
        token: The token to attempt to revoke

    Returns:
        True (Microsoft doesn't provide true programmatic revocation)
    """
    logger.info("[MicrosoftOAuth] Token revocation requested (session logout only)")
    # Microsoft doesn't have a true token revocation endpoint
    # The token will remain valid until it expires
    return True
