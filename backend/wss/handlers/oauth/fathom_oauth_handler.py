"""
Handler for Fathom OAuth token exchange.
"""

import logging
from typing import Callable, Dict

from nodes.oauth.fathom_oauth import (
    exchange_code_for_tokens,
    is_token_expired,
    refresh_access_token,
)
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from wss.receiver.client_events import (
    FathomOAuthExchangeRequest,
    FathomOAuthRefreshRequest,
    FathomOAuthValidateRequest,
)
from wss.schema import SocketIOHandler
from wss.sender import ResponseEvent, send_event
from wss.sender.responses import (
    FathomOAuthExchangeResponse,
    FathomOAuthRefreshResponse,
    FathomOAuthValidateResponse,
)

logger = logging.getLogger(__name__)


class FathomOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handle Fathom OAuth socket events."""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "fathom:oauth:exchange": self.exchange_oauth_code,
            "fathom:oauth:refresh": self.refresh_oauth_token,
            "fathom:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(
        self, sid: str, request: FathomOAuthExchangeRequest
    ) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthExchangeResponse(
                            success=False, message="User not authenticated"
                        ).model_dump(),
                    ),
                )
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code, redirect_uri=request.redirect_uri
                )
            except ValueError as e:
                logger.error("[FathomOAuthHandler] Token exchange failed: %s", e)
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthExchangeResponse(
                            success=False, message=str(e)
                        ).model_dump(),
                    ),
                )
                return

            credential_data = {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "expires_at": tokens.expires_at,
                "scope": tokens.scope,
                "token_type": tokens.token_type,
                "email": user_info.email,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error("[FathomOAuthHandler] Encryption failed: %s", e)
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthExchangeResponse(
                            success=False, message="Failed to encrypt credential"
                        ).model_dump(),
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthExchangeResponse(
                            success=False,
                            message="Database connection not available",
                        ).model_dump(),
                    ),
                )
                return

            credential_name = request.credential_name or "Fathom"
            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check

                user_tier = session.get("user_data", {}).get("subscription_tier", "free")
                row, error = await create_credential_with_limit_check(
                    conn,
                    user_id,
                    user_tier,
                    "fathom_oauth",
                    credential_name,
                    encrypted_data,
                    {
                        "provider": "fathom",
                        "scopes": request.scopes,
                        "expires_at": tokens.expires_at,
                    },
                )
                if error:
                    await send_event(
                        self.sio,
                        sid,
                        ResponseEvent(request_id=request.request_id, data={}, error=error),
                    )
                    return

            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id,
                    data=FathomOAuthExchangeResponse(
                        success=True,
                        credential_id=str(row["id"]),
                        credential_name=row["name"],
                        email=user_info.email,
                        message="Fathom account connected successfully",
                    ).model_dump(),
                ),
            )
        except Exception as e:
            logger.exception("[FathomOAuthHandler] Unexpected error: %s", e)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id,
                    data=FathomOAuthExchangeResponse(
                        success=False, message=f"Unexpected error: {str(e)}"
                    ).model_dump(),
                ),
            )

    async def refresh_oauth_token(
        self, sid: str, request: FathomOAuthRefreshRequest
    ) -> None:
        """Refresh a stored Fathom OAuth credential through the shared refresh path."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthRefreshResponse(
                            success=False, message="User not authenticated"
                        ).model_dump(),
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthRefreshResponse(
                            success=False,
                            message="Database connection not available",
                        ).model_dump(),
                    ),
                )
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="fathom",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error("[FathomOAuthHandler] Token refresh failed: %s", e)
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthRefreshResponse(
                            success=False, message=str(e)
                        ).model_dump(),
                    ),
                )
                return

            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id,
                    data=FathomOAuthRefreshResponse(
                        success=True,
                        expires_at=credential_data.get("expires_at"),
                        message="Token refreshed successfully",
                    ).model_dump(),
                ),
            )
            logger.info(
                "[FathomOAuthHandler] Refreshed token for credential %s",
                request.credential_id,
            )
        except Exception as e:
            logger.error(
                "[FathomOAuthHandler] Error in refresh_oauth_token: %s",
                e,
                exc_info=True,
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id,
                    data=FathomOAuthRefreshResponse(
                        success=False, message="Internal error"
                    ).model_dump(),
                ),
            )

    async def validate_oauth_token(
        self, sid: str, request: FathomOAuthValidateRequest
    ) -> None:
        """Validate whether a stored Fathom OAuth credential is still usable."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthValidateResponse(
                            valid=False, message="User not authenticated"
                        ).model_dump(),
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthValidateResponse(
                            valid=False,
                            message="Database connection not available",
                        ).model_dump(),
                    ),
                )
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, credential, metadata
                    FROM credentials
                    WHERE id = $1 AND owner_id = $2
                    """,
                    request.credential_id,
                    user_id,
                )

            if not row:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied",
                        ).model_dump(),
                    ),
                )
                return

            try:
                credential_data = self.encryption.decrypt_credential(row["credential"])
            except Exception as e:
                logger.error("[FathomOAuthHandler] Decryption failed: %s", e)
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential",
                        ).model_dump(),
                    ),
                )
                return

            expires_at = credential_data.get("expires_at")
            metadata = row["metadata"] or {}
            email = credential_data.get("email") or metadata.get("email")

            if not expires_at:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data=FathomOAuthValidateResponse(
                            valid=False,
                            email=email,
                            message="No expiry information available",
                        ).model_dump(),
                    ),
                )
                return

            is_expired = is_token_expired(expires_at, buffer_minutes=0)
            expires_soon = is_token_expired(expires_at)

            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id,
                    data=FathomOAuthValidateResponse(
                        valid=not is_expired,
                        expires_soon=expires_soon and not is_expired,
                        email=email,
                        message="Token is valid" if not is_expired else "Token has expired",
                    ).model_dump(),
                ),
            )
        except Exception as e:
            logger.error(
                "[FathomOAuthHandler] Error in validate_oauth_token: %s",
                e,
                exc_info=True,
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id,
                    data=FathomOAuthValidateResponse(
                        valid=False, message="Internal error"
                    ).model_dump(),
                ),
            )
