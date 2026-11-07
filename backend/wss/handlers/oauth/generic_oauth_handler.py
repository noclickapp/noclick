"""Standard OAuth2 credential operations, registered once for every declaration."""
import httpx

from nodes.core.oauth_refresh import (
    OAuthRefreshError,
    freshen_oauth_credential,
    is_token_expired,
)
from nodes.core.oauth_registry import get_oauth_provider, oauth_providers
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from wss.receiver.client_events import (
    OAuthExchangeRequest,
    OAuthRefreshRequest,
    OAuthValidateRequest,
)
from wss.schema import SocketIOHandler
from wss.sender import ResponseEvent, send_event
from wss.sender.responses import (
    OAuthExchangeResponse,
    OAuthRefreshResponse,
    OAuthValidateResponse,
)


class GenericOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    def __init__(self, sio):
        super().__init__(sio)
        oauth_providers()  # Refuse duplicate/invalid specs at startup, not first connect.
        self.encryption = get_encryption()

    def get_events(self):
        return {
            "oauth:exchange": self.exchange_oauth_code,
            "oauth:refresh": self.refresh_oauth_token,
            "oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid):
        pass

    async def _context(self, sid, provider):
        session = await self.sio.get_session(sid)
        if not session.get("user_id"):
            raise ValueError("User not authenticated")
        spec = get_oauth_provider(provider)
        pool = await self.get_pool()
        if pool is None:
            raise ValueError("Database connection not available")
        return session, spec, pool

    async def _credential(self, pool, user_id, credential_id, spec):
        from utils.credential_loader import load_credential

        credential = await load_credential(pool, user_id, credential_id)
        if not credential or credential.get("credential_type") != spec.credential_type:
            raise ValueError("Credential not found or provider does not match")
        return credential

    async def _reply(self, sid, request, response):
        await send_event(
            self.sio,
            sid,
            ResponseEvent(request_id=request.request_id, data=response.model_dump()),
        )

    async def exchange_oauth_code(
        self, sid: str, request: OAuthExchangeRequest
    ) -> None:
        try:
            session, spec, pool = await self._context(sid, request.provider)
            tokens, name = await spec.exchange(
                request.code, request.redirect_uri, request.code_verifier
            )
            credential = tokens.model_dump()
            credential["name"] = name
            encrypted = self.encryption.encrypt_credential(credential)
            from repositories.credentials import create_credential_with_limit_check

            async with pool.acquire() as conn:
                row, error = await create_credential_with_limit_check(
                    conn,
                    session["user_id"],
                    session.get("user_data", {}).get("subscription_tier", "free"),
                    spec.credential_type,
                    name,
                    encrypted,
                    {"provider": spec.provider, "name": name, "scopes": spec.scopes},
                )
            if error:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(request_id=request.request_id, data={}, error=error),
                )
                return
            response = OAuthExchangeResponse(
                success=True,
                credential_id=str(row["id"]),
                credential_name=row["name"],
                name=name,
            )
        except (ValueError, KeyError, httpx.HTTPError):
            response = OAuthExchangeResponse(
                success=False,
                message="OAuth connection failed; check provider configuration and try again",
            )
        await self._reply(sid, request, response)

    async def _freshen(self, session, spec, pool, credential_id):
        credential = await self._credential(
            pool, session["user_id"], credential_id, spec
        )
        if not credential.get("refresh_token"):
            raise ValueError("No refresh token available")
        await freshen_oauth_credential(
            credential,
            pool=pool,
            user_id=session["user_id"],
            credential_id=credential_id,
            refresh=spec.refresh,
            provider=spec.provider,
            caller_path="manual_refresh",
            additional_token_fields=spec.token_fields,
        )
        return credential

    async def refresh_oauth_token(self, sid: str, request: OAuthRefreshRequest) -> None:
        try:
            session, spec, pool = await self._context(sid, request.provider)
            credential = await self._freshen(session, spec, pool, request.credential_id)
            response = OAuthRefreshResponse(
                success=True, expires_at=credential.get("expires_at")
            )
        except OAuthRefreshError as exc:
            response = OAuthRefreshResponse(
                success=False,
                message=(
                    "OAuth refresh temporarily unavailable; try again"
                    if exc.transient
                    else "OAuth refresh rejected; reconnect the account"
                ),
            )
        except (ValueError, KeyError, httpx.HTTPError):
            response = OAuthRefreshResponse(
                success=False, message="OAuth refresh failed; reconnect the account"
            )
        await self._reply(sid, request, response)

    async def validate_oauth_token(
        self, sid: str, request: OAuthValidateRequest
    ) -> None:
        try:
            session, spec, pool = await self._context(sid, request.provider)
            credential = await self._credential(
                pool, session["user_id"], request.credential_id, spec
            )
            if not credential.get("access_token"):
                raise ValueError("Credential has no access token")
            expired = is_token_expired(credential.get("expires_at"), buffer_minutes=0)
            if not expired and spec.identity_url:
                await spec.account_name(credential["access_token"])
            response = OAuthValidateResponse(valid=not expired, expired=expired)
        except (ValueError, KeyError, httpx.HTTPError):
            response = OAuthValidateResponse(
                valid=False, message="OAuth credential could not be validated"
            )
        await self._reply(sid, request, response)
