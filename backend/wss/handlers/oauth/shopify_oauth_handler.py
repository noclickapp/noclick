"""
Handler for Shopify OAuth operations.
Manages OAuth 2.0 flow for Shopify Admin API access.
"""

import logging
import os
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.shopify_oauth import (
    exchange_code_for_tokens,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    ShopifyOAuthExchangeResponse,
    ShopifyOAuthRefreshResponse,
    ShopifyOAuthValidateResponse,
)
from wss.receiver.client_events import (
    ShopifyOAuthExchangeRequest,
    ShopifyOAuthRefreshRequest,
    ShopifyOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class ShopifyOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Shopify OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Shopify OAuth events"""
        return {
            "shopify:oauth:exchange": self.exchange_oauth_code,
            "shopify:oauth:refresh": self.refresh_oauth_token,
            "shopify:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: ShopifyOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ShopifyOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Exchange code for tokens
            try:
                configured_redirect_uri = os.environ.get('SHOPIFY_REDIRECT_URI')
                if configured_redirect_uri and request.redirect_uri != configured_redirect_uri:
                    raise ValueError("Invalid redirect URI")

                tokens, shop_info = await exchange_code_for_tokens(
                    code=request.code,
                    shop=request.shop,
                    redirect_uri=request.redirect_uri,
                    custom_client_id=request.custom_client_id,
                    custom_client_secret=request.custom_client_secret,
                )
            except ValueError as e:
                logger.error(f"[ShopifyOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ShopifyOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data
            credential_data = {
                'credential_type': 'shopify_oauth',
                'access_token': tokens.access_token,
                'scope': tokens.scope,
                'store_name': request.shop,
                'shop_owner': shop_info.shop_owner,
                'email': shop_info.email,
                'expires_at': None,
                # Custom Shopify apps need their own secret for webhook HMAC.
                # The default public app resolves its secret from the server
                # environment and does not duplicate it per credential.
                'api_secret_key': request.custom_client_secret or None,
            }

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[ShopifyOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ShopifyOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ShopifyOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Use the shop name or domain as the credential name
            credential_name = shop_info.name or shop_info.domain or f"Shopify ({shop_info.id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'shopify_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'shopify',
                        # Canonical key used by Shopify compliance webhooks.
                        # shop_info.domain can be the merchant's custom domain;
                        # the OAuth `shop` parameter is always *.myshopify.com.
                        'myshopify_domain': f"{request.shop}.myshopify.com",
                        'shop_name': shop_info.name,
                        'shop_domain': shop_info.domain,
                        'shop_owner': shop_info.shop_owner,
                        'email': shop_info.email,
                        'shop_id': shop_info.id,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = ShopifyOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    shop_name=shop_info.name,
                    email=shop_info.email,
                    message="Shopify store connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[ShopifyOAuthHandler] Created Shopify credential {row['id']} for user {user_id} ({shop_info.name})")

        except Exception as e:
            logger.error(f"[ShopifyOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ShopifyOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: ShopifyOAuthRefreshRequest) -> None:
        """
        Refresh an expired OAuth token.
        Note: Shopify tokens don't expire, so this always returns an error.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ShopifyOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Shopify tokens don't expire
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ShopifyOAuthRefreshResponse(
                    success=False,
                    message="Shopify tokens don't expire and don't support refresh"
                ).model_dump()
            ))

        except Exception as e:
            logger.error(f"[ShopifyOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ShopifyOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: ShopifyOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        Note: Shopify tokens don't expire, so they're always valid unless revoked.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ShopifyOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ShopifyOAuthValidateResponse(
                        valid=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            async with pool.acquire() as conn:
                # Fetch credential (verify ownership)
                row = await conn.fetchrow("""
                    SELECT id, credential, metadata
                    FROM credentials
                    WHERE id = $1 AND owner_id = $2
                """, request.credential_id, user_id)

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=ShopifyOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                # Decrypt credential
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[ShopifyOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=ShopifyOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                shop_name = credential_data.get('shop_name') or row['metadata'].get('shop_name')
                email = credential_data.get('email') or row['metadata'].get('email')

                # Shopify tokens don't expire - always valid
                response = ShopifyOAuthValidateResponse(
                    valid=True,
                    expires_soon=False,
                    shop_name=shop_name,
                    email=email,
                    message="Token is valid (non-expiring)"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[ShopifyOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ShopifyOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
