"""
Mailchimp OAuth utility for handling token exchange.
Manages OAuth 2.0 Web Server Flow for Mailchimp Marketing API access.

Mailchimp OAuth uses:
- Authorization URL: https://login.mailchimp.com/oauth2/authorize
- Token URL: https://login.mailchimp.com/oauth2/token
- Metadata URL: https://login.mailchimp.com/oauth2/metadata
- Access tokens DO NOT expire (unique to Mailchimp)
- No refresh tokens needed

Documentation: https://mailchimp.com/developer/marketing/guides/access-user-data-oauth-2/
"""

import os
import logging
from typing import Tuple, Optional, Dict, Any
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAILCHIMP_AUTH_URL = "https://login.mailchimp.com/oauth2/authorize"
MAILCHIMP_TOKEN_URL = "https://login.mailchimp.com/oauth2/token"
MAILCHIMP_METADATA_URL = "https://login.mailchimp.com/oauth2/metadata"


class MailchimpTokens(BaseModel):
    """Structured token response from Mailchimp OAuth"""
    access_token: str
    token_type: str = "bearer"
    # Note: Mailchimp tokens don't expire, so no expires_at or refresh_token


class MailchimpUserInfo(BaseModel):
    """User info from Mailchimp metadata endpoint"""
    dc: str  # Data center (e.g., 'us1', 'us19')
    login_url: str
    api_endpoint: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None


def get_mailchimp_client_config() -> Tuple[str, str]:
    """
    Get Mailchimp OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get('MAILCHIMP_CLIENT_ID')
    client_secret = os.environ.get('MAILCHIMP_CLIENT_SECRET')

    if not client_id:
        raise ValueError("MAILCHIMP_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("MAILCHIMP_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[MailchimpTokens, MailchimpUserInfo]:
    """
    Exchange authorization code for access token and get user metadata.

    Args:
        code: Authorization code from Mailchimp OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Tuple of (MailchimpTokens, MailchimpUserInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_mailchimp_client_config()

    # Step 1: Exchange code for access token
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            logger.info(f"[Mailchimp OAuth] Exchanging code for tokens at {MAILCHIMP_TOKEN_URL}")
            response = await client.post(
                MAILCHIMP_TOKEN_URL,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )

            if response.status_code != 200:
                error_text = f"HTTP {response.status_code}"
                logger.error(f"[Mailchimp OAuth] Token exchange failed: {error_text}")
                raise ValueError(f"Failed to exchange code for tokens: {error_text}")

            token_response = response.json()
            logger.info(f"[Mailchimp OAuth] Token exchange successful")

            tokens = MailchimpTokens(
                access_token=token_response['access_token'],
                token_type=token_response.get('token_type', 'bearer')
            )

            # Step 2: Get user metadata (datacenter, account info)
            logger.info(f"[Mailchimp OAuth] Fetching user metadata from {MAILCHIMP_METADATA_URL}")
            metadata_response = await client.get(
                MAILCHIMP_METADATA_URL,
                headers={'Authorization': f'Bearer {tokens.access_token}'}
            )

            if metadata_response.status_code != 200:
                error_text = f"HTTP {metadata_response.status_code}"
                logger.error(f"[Mailchimp OAuth] Metadata fetch failed: {error_text}")
                raise ValueError(f"Failed to fetch user metadata: {error_text}")

            metadata = metadata_response.json()
            logger.info(f"[Mailchimp OAuth] Metadata fetch successful")

            # Extract datacenter from api_endpoint
            # api_endpoint format: "https://us19.api.mailchimp.com"
            api_endpoint = metadata.get('api_endpoint', '')
            dc = api_endpoint.split('//')[1].split('.')[0] if '//' in api_endpoint else 'us1'

            user_info = MailchimpUserInfo(
                dc=dc,
                login_url=metadata.get('login_url', ''),
                api_endpoint=api_endpoint,
                account_id=metadata.get('accountname'),
                account_name=metadata.get('accountname')
            )

            return tokens, user_info

        except httpx.TimeoutException:
            logger.error("[Mailchimp OAuth] Token exchange timed out")
            raise ValueError("Token exchange timed out")
        except KeyError as e:
            logger.error(f"[Mailchimp OAuth] Missing required field in response: {e}")
            raise ValueError(f"Invalid response: missing {e}")
        except Exception as e:
            logger.exception(f"[Mailchimp OAuth] Unexpected error during token exchange: {e}")
            raise ValueError(f"Token exchange failed: {str(e)}")
