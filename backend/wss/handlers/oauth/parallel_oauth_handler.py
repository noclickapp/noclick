"""Handler for Parallel OAuth operations (Authorization Code + PKCE)."""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.parallel_oauth import exchange_code_for_tokens, validate_api_key
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import ParallelOAuthExchangeResponse, ParallelOAuthValidateResponse
from wss.receiver.client_events import ParallelOAuthExchangeRequest, ParallelOAuthValidateRequest

logger = logging.getLogger(__name__)


class ParallelOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Parallel OAuth WebSocket events."""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "parallel:oauth:exchange": self.exchange_oauth_code,
            "parallel:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: ParallelOAuthExchangeRequest) -> None:
        """Exchange the PKCE authorization code for the user's Parallel API key."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ParallelOAuthExchangeResponse(success=False, message="User not authenticated").model_dump(),
                ))
                return

            try:
                tokens = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                    code_verifier=request.code_verifier,
                )
            except ValueError as e:
                logger.error(f"[ParallelOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ParallelOAuthExchangeResponse(success=False, message=str(e)).model_dump(),
                ))
                return

            credential_data = {"access_token": tokens.access_token}
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[ParallelOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ParallelOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump(),
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ParallelOAuthExchangeResponse(success=False, message="Database connection not available").model_dump(),
                ))
                return

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get("user_data", {}).get("subscription_tier", "free")
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, "parallel_oauth",
                    request.credential_name, encrypted_data,
                    {"provider": "parallel"},
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error,
                    ))
                    return

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ParallelOAuthExchangeResponse(
                        success=True,
                        credential_id=str(row["id"]),
                        credential_name=row["name"],
                        message="Parallel account connected successfully",
                    ).model_dump(),
                ))
                logger.info(f"[ParallelOAuthHandler] Created credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[ParallelOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ParallelOAuthExchangeResponse(success=False, message="Internal error").model_dump(),
            ))

    async def validate_oauth_token(self, sid: str, request: ParallelOAuthValidateRequest) -> None:
        """Verify the stored API key is still active with a live Parallel API call."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ParallelOAuthValidateResponse(valid=False, message="User not authenticated").model_dump(),
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ParallelOAuthValidateResponse(valid=False, message="Database connection not available").model_dump(),
                ))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT credential FROM credentials WHERE id = $1 AND owner_id = $2",
                    request.credential_id, user_id,
                )
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=ParallelOAuthValidateResponse(valid=False, message="Credential not found").model_dump(),
                    ))
                    return

            try:
                credential_data = self.encryption.decrypt_credential(row["credential"])
            except Exception:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ParallelOAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump(),
                ))
                return

            api_key = credential_data.get("access_token", "")
            is_valid = await validate_api_key(api_key)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ParallelOAuthValidateResponse(
                    valid=is_valid,
                    message="API key is active" if is_valid else "API key is invalid or revoked",
                ).model_dump(),
            ))

        except Exception as e:
            logger.error(f"[ParallelOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ParallelOAuthValidateResponse(valid=False, message="Internal error").model_dump(),
            ))
