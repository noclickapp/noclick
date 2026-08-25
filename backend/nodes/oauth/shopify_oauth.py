"""
Shopify OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Shopify Admin API access.

Shopify OAuth uses:
- Authorization URL: https://{shop}.myshopify.com/admin/oauth/authorize
- Token URL: https://{shop}.myshopify.com/admin/oauth/access_token
- Shopify access tokens do not expire by default
- No refresh tokens are provided (tokens are permanent until revoked)

Documentation: https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/authorization-code-grant
"""

import os
import logging
from datetime import datetime, timezone
from typing import Tuple, Optional
import httpx
from pydantic import BaseModel
from utils.ssrf import normalize_provider_subdomain

logger = logging.getLogger(__name__)
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-01")


class ShopifyTokens(BaseModel):
    """Structured token response from Shopify OAuth"""
    access_token: str
    scope: str
    expires_at: Optional[str] = None  # Always None for Shopify (tokens don't expire)
    token_type: str = "Bearer"


class ShopifyShopInfo(BaseModel):
    """Shop info from Shopify"""
    id: int
    name: str
    email: Optional[str] = None
    shop_owner: Optional[str] = None
    domain: str


def get_shopify_client_config(
    custom_client_id: Optional[str] = None,
    custom_client_secret: Optional[str] = None
) -> Tuple[str, str]:
    """
    Get Shopify OAuth client configuration.

    Supports custom OAuth app credentials for users with their own Shopify apps.
    Falls back to NoClick's default OAuth app if custom credentials not provided.

    Args:
        custom_client_id: Optional custom OAuth app client ID
        custom_client_secret: Optional custom OAuth app client secret

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If neither custom credentials nor environment variables are set
    """
    # Use custom credentials if provided
    if custom_client_id and custom_client_secret:
        logger.info("[ShopifyOAuth] Using custom OAuth app credentials")
        return custom_client_id, custom_client_secret

    # Fall back to default NoClick OAuth app from environment
    client_id = os.environ.get('SHOPIFY_CLIENT_ID')
    client_secret = os.environ.get('SHOPIFY_CLIENT_SECRET')

    if not client_id:
        raise ValueError("SHOPIFY_CLIENT_ID environment variable is required (or provide custom_client_id)")
    if not client_secret:
        raise ValueError("SHOPIFY_CLIENT_SECRET environment variable is required (or provide custom_client_secret)")

    logger.info("[ShopifyOAuth] Using default NoClick OAuth app")
    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    shop: str,
    redirect_uri: str,
    custom_client_id: Optional[str] = None,
    custom_client_secret: Optional[str] = None,
) -> Tuple[ShopifyTokens, ShopifyShopInfo]:
    """
    Exchange authorization code for access token.

    Args:
        code: Authorization code from Shopify OAuth callback
        shop: Shop name (e.g., 'my-store' from 'my-store.myshopify.com')
        redirect_uri: Must match the redirect_uri used in authorization
        custom_client_id: Optional custom OAuth app client ID
        custom_client_secret: Optional custom OAuth app client secret

    Returns:
        Tuple of (ShopifyTokens, ShopifyShopInfo)

    Raises:
        ValueError: If token exchange fails
    """
    client_id, client_secret = get_shopify_client_config(custom_client_id, custom_client_secret)
    shop = normalize_provider_subdomain(
        shop, "myshopify.com", field_name="Shopify store name"
    )

    # Construct token URL for the specific shop
    token_url = f"https://{shop}.myshopify.com/admin/oauth/access_token"
    shop_url = f"https://{shop}.myshopify.com/admin/api/{SHOPIFY_API_VERSION}/shop.json"

    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code,
    }

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            token_url,
            data=data,
        )

        if token_response.status_code != 200:
            logger.error(f"[ShopifyOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()

        # Check for error in response
        if 'error' in token_data:
            error_msg = token_data.get('error_description', token_data.get('error', 'Unknown error'))
            logger.error(f"[ShopifyOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        # Shopify tokens don't expire
        tokens = ShopifyTokens(
            access_token=token_data['access_token'],
            scope=token_data.get('scope', ''),
            expires_at=None,  # Shopify tokens don't expire
            token_type='Bearer',
        )

        # Get shop info
        shopinfo_response = await client.get(
            shop_url,
            headers={
                'X-Shopify-Access-Token': tokens.access_token,
            },
        )

        if shopinfo_response.status_code != 200:
            logger.warning(f"[ShopifyOAuth] Failed to get shop info: HTTP {shopinfo_response.status_code}")
            shop_info = ShopifyShopInfo(
                id=0,
                name=shop,
                domain=f"{shop}.myshopify.com"
            )
        else:
            shopinfo_data = shopinfo_response.json().get('shop', {})
            shop_info = ShopifyShopInfo(
                id=shopinfo_data.get('id', 0),
                name=shopinfo_data.get('name', shop),
                email=shopinfo_data.get('email'),
                shop_owner=shopinfo_data.get('shop_owner'),
                domain=shopinfo_data.get('domain', f"{shop}.myshopify.com"),
            )

        logger.info(f"[ShopifyOAuth] Successfully exchanged code for tokens for shop {shop_info.name}")
        return tokens, shop_info


async def refresh_access_token(refresh_token: str) -> ShopifyTokens:
    """
    Refresh an expired access token.
    Note: Shopify tokens don't expire, so this function is not used.

    Args:
        refresh_token: Not used for Shopify

    Returns:
        Raises ValueError as Shopify doesn't support token refresh

    Raises:
        ValueError: Always - Shopify tokens don't expire
    """
    raise ValueError("Shopify tokens don't expire and don't support refresh")


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """
    Check if a token is expired or will expire soon.
    Note: Shopify tokens don't expire. Always returns False.

    Args:
        expires_at: Not used for Shopify (always None)
        buffer_minutes: Not used for Shopify

    Returns:
        Always False - Shopify tokens don't expire
    """
    # Shopify tokens never expire
    return False


# Standard scopes for Shopify workflow operations
SHOPIFY_WORKFLOW_SCOPES = [
    "read_products",           # Read products
    "write_products",          # Modify products
    "read_orders",             # Read orders
    "write_orders",            # Modify orders
    "read_customers",          # Read customers
    "write_customers",         # Modify customers
    "read_inventory",          # Read inventory
    "write_inventory",         # Modify inventory
]

# Minimal scopes for read-only access
SHOPIFY_READ_ONLY_SCOPES = [
    "read_products",
    "read_orders",
    "read_customers",
]
