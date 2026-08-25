"""
HubSpot OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 Web Server Flow for HubSpot API access.

HubSpot OAuth uses:
- Authorization URL: https://app.hubspot.com/oauth/authorize
- Token URL: https://api.hubapi.com/oauth/v1/token
- Access tokens typically expire after 6 hours
- Refresh tokens are provided and should be used to get new access tokens

Documentation: https://developers.hubspot.com/docs/api/oauth/overview
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import httpx
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HUBSPOT_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"


class HubSpotTokens(BaseModel):
    """Structured token response from HubSpot OAuth"""

    access_token: str
    refresh_token: str
    expires_at: str  # ISO 8601 timestamp
    token_type: str = "bearer"


class HubSpotUserInfo(BaseModel):
    """User info from HubSpot"""

    hub_id: str
    user_id: Optional[str] = None
    hub_domain: Optional[str] = None


def get_hubspot_client_config() -> Tuple[str, str]:
    """
    Get HubSpot OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("HUBSPOT_CLIENT_ID")
    client_secret = os.environ.get("HUBSPOT_CLIENT_SECRET")

    if not client_id:
        raise ValueError("HUBSPOT_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("HUBSPOT_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[HubSpotTokens, HubSpotUserInfo]:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from HubSpot OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (HubSpotTokens, HubSpotUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_hubspot_client_config()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            logger.info(
                f"[HubSpot OAuth] Exchanging code for tokens at {HUBSPOT_TOKEN_URL}"
            )
            response = await client.post(
                HUBSPOT_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                error_text = f"HTTP {response.status_code}"
                logger.error(f"[HubSpot OAuth] Token exchange failed: {error_text}")
                raise ValueError(f"Failed to exchange code for tokens: {error_text}")

            token_response = response.json()
            logger.info(f"[HubSpot OAuth] Token exchange successful")

            # Calculate expiration time
            expires_in = token_response.get("expires_in", 1800)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            tokens = HubSpotTokens(
                access_token=token_response["access_token"],
                refresh_token=token_response["refresh_token"],
                expires_at=expires_at.isoformat(),
                token_type=token_response.get("token_type", "bearer"),
            )

            # Get user info (hub_id is in the token response)
            user_info = HubSpotUserInfo(
                hub_id=str(token_response.get("hub_id", "")),
                hub_domain=token_response.get("hub_domain"),
            )

            return tokens, user_info

        except httpx.TimeoutException:
            logger.error("[HubSpot OAuth] Token exchange timed out")
            raise ValueError("Token exchange timed out")
        except KeyError as e:
            logger.error(
                f"[HubSpot OAuth] Missing required field in token response: {e}"
            )
            raise ValueError(f"Invalid token response: missing {e}")
        except Exception as e:
            logger.exception(
                f"[HubSpot OAuth] Unexpected error during token exchange: {e}"
            )
            raise ValueError(f"Token exchange failed: {str(e)}")


async def refresh_access_token(refresh_token: str) -> HubSpotTokens:
    """
    Refresh an expired access token using a refresh token.

    Args:
        refresh_token: HubSpot refresh token

    Returns:
        New HubSpotTokens with fresh access token

    Raises:
        ValueError: If token refresh fails
    """
    client_id, client_secret = get_hubspot_client_config()

    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            logger.info("[HubSpot OAuth] Refreshing access token")
            response = await client.post(
                HUBSPOT_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                error_text = f"HTTP {response.status_code}"
                logger.error(f"[HubSpot OAuth] Token refresh failed: {error_text}")
                error_code = None
                try:
                    error_data = response.json()
                    if isinstance(error_data, dict):
                        error_code = error_data.get("error")
                except Exception:
                    error_code = None
                span = trace.get_current_span()
                if span and span.is_recording() and error_code:
                    span.set_attribute("oauth.provider_error_code", str(error_code))
                raise ValueError(f"Failed to refresh token: {error_text}")

            token_response = response.json()
            logger.info("[HubSpot OAuth] Token refresh successful")

            # Calculate expiration time
            expires_in = token_response.get("expires_in", 1800)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            return HubSpotTokens(
                access_token=token_response["access_token"],
                refresh_token=token_response["refresh_token"],
                expires_at=expires_at.isoformat(),
                token_type=token_response.get("token_type", "bearer"),
            )

        except httpx.TimeoutException:
            logger.error("[HubSpot OAuth] Token refresh timed out")
            raise ValueError("Token refresh timed out")
        except KeyError as e:
            logger.error(
                f"[HubSpot OAuth] Missing required field in refresh response: {e}"
            )
            raise ValueError(f"Invalid refresh response: missing {e}")
        except Exception as e:
            logger.exception(
                f"[HubSpot OAuth] Unexpected error during token refresh: {e}"
            )
            raise ValueError(f"Token refresh failed: {str(e)}")
