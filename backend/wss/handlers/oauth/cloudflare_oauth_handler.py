"""Handler for Cloudflare OAuth 2.0 token exchange, refresh, and validation."""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.cloudflare_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    CloudflareOAuthExchangeResponse,
    CloudflareOAuthRefreshResponse,
    CloudflareOAuthValidateResponse,
)
from wss.receiver.client_events import (
    CloudflareOAuthExchangeRequest,
    CloudflareOAuthRefreshRequest,
    CloudflareOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class CloudflareOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Cloudflare OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "cloudflare:oauth:exchange": self.exchange_oauth_code,
            "cloudflare:oauth:refresh": self.refresh_oauth_token,
            "cloudflare:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: CloudflareOAuthExchangeRequest) -> None:
        """Exchange authorization code for tokens and store as credential."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[CloudflareOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            credential_data = {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "expires_at": tokens.expires_at,
                "scope": tokens.scope,
                "email": user_info.email,
                "cloudflare_user_id": user_info.id,
                "account_id": user_info.account_id,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[CloudflareOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthExchangeResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            credential_name = user_info.name or user_info.email or f"Cloudflare ({user_info.id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get("user_data", {}).get("subscription_tier", "free")
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, "cloudflare_oauth",
                    credential_name, encrypted_data, {
                        "provider": "cloudflare",
                        "email": user_info.email,
                        "cloudflare_user_id": user_info.id,
                        "scopes": request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthExchangeResponse(
                        success=True,
                        credential_id=str(row["id"]),
                        credential_name=row["name"],
                        email=user_info.email,
                        message="Cloudflare account connected successfully",
                    ).model_dump()
                ))
                logger.info(f"[CloudflareOAuthHandler] Created credential {row['id']} for user {user_id} ({user_info.email})")

        except Exception as e:
            logger.error(f"[CloudflareOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CloudflareOAuthExchangeResponse(success=False, message="Internal error").model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: CloudflareOAuthRefreshRequest) -> None:
        """Refresh an expired OAuth token via the shared choke point."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthRefreshResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthRefreshResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential
            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="cloudflare",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[CloudflareOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthRefreshResponse(success=False, message=str(e)).model_dump()
                ))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CloudflareOAuthRefreshResponse(
                    success=True,
                    expires_at=credential_data.get("expires_at"),
                    message="Token refreshed successfully",
                ).model_dump()
            ))
            logger.info(f"[CloudflareOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[CloudflareOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CloudflareOAuthRefreshResponse(success=False, message="Internal error").model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: CloudflareOAuthValidateRequest) -> None:
        """Check whether a stored Cloudflare OAuth credential is still valid."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthValidateResponse(valid=False, message="Database connection not available").model_dump()
                ))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, credential, metadata FROM credentials WHERE id = $1 AND owner_id = $2",
                    request.credential_id, user_id,
                )
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=CloudflareOAuthValidateResponse(valid=False, message="Credential not found or access denied").model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row["credential"])
                except Exception as e:
                    logger.error(f"[CloudflareOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=CloudflareOAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump()
                    ))
                    return

                expires_at = credential_data.get("expires_at")
                email = credential_data.get("email") or (row["metadata"] or {}).get("email")
                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=60)

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CloudflareOAuthValidateResponse(
                        valid=not is_expired,
                        expires_soon=expires_soon and not is_expired,
                        email=email,
                        message="Token is valid" if not is_expired else "Token has expired",
                    ).model_dump()
                ))

        except Exception as e:
            logger.error(f"[CloudflareOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CloudflareOAuthValidateResponse(valid=False, message="Internal error").model_dump()
            ))
