"""
Handler for Mailchimp OAuth operations.
Manages OAuth 2.0 Web Server Flow for Mailchimp Marketing API access.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.mailchimp_oauth import exchange_code_for_tokens
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import MailchimpOAuthExchangeResponse
from wss.receiver.client_events import MailchimpOAuthExchangeRequest

logger = logging.getLogger(__name__)


class MailchimpOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Mailchimp OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Mailchimp OAuth events"""
        return {
            "mailchimp:oauth:exchange": self.exchange_oauth_code,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: MailchimpOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.

        Note: Mailchimp OAuth tokens don't expire, so no refresh mechanism is needed.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MailchimpOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Exchange code for tokens
            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[MailchimpOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MailchimpOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data
            # Note: Mailchimp tokens don't expire, so no expires_at or refresh_token
            credential_data = {
                'access_token': tokens.access_token,
                'token_type': tokens.token_type,
                'server_prefix': user_info.dc,  # Datacenter (e.g., 'us1', 'us19')
                'api_endpoint': user_info.api_endpoint,
                'login_url': user_info.login_url,
                'account_id': user_info.account_id,
                'account_name': user_info.account_name,
            }

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[MailchimpOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MailchimpOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MailchimpOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Use the credential_name from request, or default to account name
            credential_name = request.credential_name or user_info.account_name or f"Mailchimp ({user_info.dc})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'mailchimp_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'mailchimp',
                        'server_prefix': user_info.dc,
                        'account_id': user_info.account_id,
                        'account_name': user_info.account_name,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = MailchimpOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    server_prefix=user_info.dc,
                    email=user_info.account_name,  # Mailchimp doesn't provide email in metadata
                    message="Mailchimp account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[MailchimpOAuthHandler] Created Mailchimp credential {row['id']} for user {user_id} (dc: {user_info.dc})")

        except Exception as e:
            logger.error(f"[MailchimpOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=MailchimpOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))
