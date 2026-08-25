"""
Redis storage for MCP OAuth data.

Stores:
- Client registrations (persistent)
- Authorization codes (short-lived, single-use)
- Refresh tokens (medium-lived)

Uses the shared Redis client pattern from utils/snapshot_cache.py.
"""

import os
import json
import logging
import secrets
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as redis

from mcp_adapter.auth.models import (
    StoredClient,
    StoredAuthorizationCode,
    StoredRefreshToken,
)

logger = logging.getLogger(__name__)

# Key prefixes for Redis storage
KEY_PREFIX_CLIENT = "mcp:oauth:client:"
KEY_PREFIX_AUTH_CODE = "mcp:oauth:authcode:"
KEY_PREFIX_REFRESH_TOKEN = "mcp:oauth:refresh:"

# TTLs
AUTH_CODE_TTL_SECONDS = 600  # 10 minutes (codes should be exchanged quickly)
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days
CLIENT_TTL_SECONDS = 365 * 24 * 3600  # 1 year (effectively permanent)


def _create_redis_client() -> Optional[redis.Redis]:
    """Create Redis client for MCP OAuth storage."""
    from utils.redis_client import RESILIENCE_KWARGS, redis_url_or_none

    redis_url = redis_url_or_none()
    if not redis_url:
        logger.info("[MCP OAuth] No REDIS_URL — OAuth client registrations are not persisted")
        return None
    try:
        client = redis.from_url(redis_url, **RESILIENCE_KWARGS)
        logger.info("[MCP OAuth] Created Redis client for OAuth storage")
        return client
    except Exception as e:
        logger.error(f"[MCP OAuth] Failed to create Redis client: {e}")
        return None


# Shared Redis client instance
_SHARED_REDIS_CLIENT = _create_redis_client()


class MCPOAuthStorage:
    """
    Redis-backed storage for MCP OAuth data.

    Handles client registrations, authorization codes, and refresh tokens
    with appropriate TTLs and atomic operations.
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize OAuth storage.

        Args:
            redis_client: Optional Redis client for testing. If not provided,
                         uses the shared module-level client.
        """
        self.redis = redis_client if redis_client is not None else _SHARED_REDIS_CLIENT

    # =========================================================================
    # Client Registration
    # =========================================================================

    async def store_client(self, client: StoredClient) -> bool:
        """
        Store a registered client.

        Args:
            client: Client registration data

        Returns:
            True if successful
        """
        if not self.redis:
            logger.error("[MCP OAuth] Redis not available for client storage")
            return False

        try:
            key = f"{KEY_PREFIX_CLIENT}{client.client_id}"
            data = client.model_dump_json()

            await asyncio.wait_for(
                self.redis.setex(key, CLIENT_TTL_SECONDS, data),
                timeout=5.0,
            )

            logger.info(
                f"[MCP OAuth] Stored client registration: {client.client_id} "
                f"({client.client_name})"
            )
            return True

        except asyncio.TimeoutError:
            logger.error("[MCP OAuth] Redis timeout storing client")
            return False
        except Exception as e:
            logger.error(f"[MCP OAuth] Error storing client: {e}")
            return False

    async def get_client(self, client_id: str) -> Optional[StoredClient]:
        """
        Retrieve a registered client.

        Args:
            client_id: The client ID to look up

        Returns:
            StoredClient if found, None otherwise
        """
        if not self.redis:
            return None

        try:
            key = f"{KEY_PREFIX_CLIENT}{client_id}"

            data = await asyncio.wait_for(self.redis.get(key), timeout=2.0)

            if not data:
                logger.debug(f"[MCP OAuth] Client not found: {client_id}")
                return None

            client = StoredClient.model_validate_json(data)
            logger.debug(f"[MCP OAuth] Retrieved client: {client_id}")
            return client

        except asyncio.TimeoutError:
            logger.error("[MCP OAuth] Redis timeout getting client")
            return None
        except Exception as e:
            logger.error(f"[MCP OAuth] Error getting client: {e}")
            return None

    async def find_client_by_redirect_uris(self, redirect_uris: list[str]) -> Optional[StoredClient]:
        """Find an existing client by redirect_uris for idempotent DCR.

        Uses a deterministic client_id derived from redirect_uris, so the lookup
        is just a regular get_client call — no reverse index needed.
        """
        if not redirect_uris:
            return None
        client_id = self.deterministic_client_id(redirect_uris)
        return await self.get_client(client_id)

    @staticmethod
    def deterministic_client_id(redirect_uris: list[str]) -> str:
        """Derive a stable client_id from redirect_uris for idempotent DCR."""
        import hashlib
        import base64
        content = ",".join(sorted(redirect_uris))
        digest = hashlib.sha256(content.encode()).digest()
        return base64.urlsafe_b64encode(digest[:16]).rstrip(b"=").decode()

    # =========================================================================
    # Authorization Codes
    # =========================================================================

    async def store_authorization_code(
        self,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        scope: str,
        code_challenge: str,
    ) -> Optional[str]:
        """
        Generate and store an authorization code.

        Args:
            client_id: The client requesting authorization
            user_id: The user granting authorization
            redirect_uri: Redirect URI for this authorization
            scope: Granted scopes
            code_challenge: PKCE code challenge

        Returns:
            The generated authorization code, or None on failure
        """
        if not self.redis:
            logger.error("[MCP OAuth] Redis not available for auth code storage")
            return None

        try:
            # Generate secure random code
            code = secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc)

            auth_code = StoredAuthorizationCode(
                code=code,
                client_id=client_id,
                user_id=user_id,
                redirect_uri=redirect_uri,
                scope=scope,
                code_challenge=code_challenge,
                created_at=now,
                expires_at=now + timedelta(seconds=AUTH_CODE_TTL_SECONDS),
            )

            key = f"{KEY_PREFIX_AUTH_CODE}{code}"
            data = auth_code.model_dump_json()

            await asyncio.wait_for(
                self.redis.setex(key, AUTH_CODE_TTL_SECONDS, data),
                timeout=5.0,
            )

            logger.info(
                f"[MCP OAuth] Stored authorization code for user={user_id}, "
                f"client={client_id}"
            )
            return code

        except asyncio.TimeoutError:
            logger.error("[MCP OAuth] Redis timeout storing auth code")
            return None
        except Exception as e:
            logger.error(f"[MCP OAuth] Error storing auth code: {e}")
            return None

    async def consume_authorization_code(
        self, code: str
    ) -> Optional[StoredAuthorizationCode]:
        """
        Retrieve and delete an authorization code (single-use).

        Args:
            code: The authorization code to consume

        Returns:
            StoredAuthorizationCode if valid, None otherwise
        """
        if not self.redis:
            return None

        try:
            key = f"{KEY_PREFIX_AUTH_CODE}{code}"

            # Atomic get-and-delete using pipeline
            async with self.redis.pipeline() as pipe:
                pipe.get(key)
                pipe.delete(key)
                results = await asyncio.wait_for(pipe.execute(), timeout=5.0)

            data = results[0]
            if not data:
                logger.warning(f"[MCP OAuth] Authorization code not found or expired")
                return None

            auth_code = StoredAuthorizationCode.model_validate_json(data)

            # Verify not expired (belt and suspenders with TTL)
            if datetime.now(timezone.utc) > auth_code.expires_at:
                logger.warning("[MCP OAuth] Authorization code expired")
                return None

            logger.info(
                f"[MCP OAuth] Consumed authorization code for user={auth_code.user_id}"
            )
            return auth_code

        except asyncio.TimeoutError:
            logger.error("[MCP OAuth] Redis timeout consuming auth code")
            return None
        except Exception as e:
            logger.error(f"[MCP OAuth] Error consuming auth code: {e}")
            return None

    # =========================================================================
    # Refresh Tokens
    # =========================================================================

    async def store_refresh_token(
        self,
        client_id: str,
        user_id: str,
        scope: str,
    ) -> Optional[str]:
        """
        Generate and store a refresh token.

        Args:
            client_id: The client this token is for
            user_id: The user this token is for
            scope: Granted scopes

        Returns:
            The generated refresh token, or None on failure
        """
        if not self.redis:
            logger.error("[MCP OAuth] Redis not available for refresh token storage")
            return None

        try:
            token = secrets.token_urlsafe(48)
            now = datetime.now(timezone.utc)

            refresh = StoredRefreshToken(
                token=token,
                client_id=client_id,
                user_id=user_id,
                scope=scope,
                created_at=now,
                expires_at=now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
            )

            key = f"{KEY_PREFIX_REFRESH_TOKEN}{token}"
            data = refresh.model_dump_json()

            await asyncio.wait_for(
                self.redis.setex(key, REFRESH_TOKEN_TTL_SECONDS, data),
                timeout=5.0,
            )

            logger.info(
                f"[MCP OAuth] Stored refresh token for user={user_id}, "
                f"client={client_id}"
            )
            return token

        except asyncio.TimeoutError:
            logger.error("[MCP OAuth] Redis timeout storing refresh token")
            return None
        except Exception as e:
            logger.error(f"[MCP OAuth] Error storing refresh token: {e}")
            return None

    async def get_refresh_token(self, token: str) -> Optional[StoredRefreshToken]:
        """
        Retrieve a refresh token.

        Args:
            token: The refresh token to look up

        Returns:
            StoredRefreshToken if valid, None otherwise
        """
        if not self.redis:
            return None

        try:
            key = f"{KEY_PREFIX_REFRESH_TOKEN}{token}"

            data = await asyncio.wait_for(self.redis.get(key), timeout=2.0)

            if not data:
                logger.warning("[MCP OAuth] Refresh token not found or expired")
                return None

            refresh = StoredRefreshToken.model_validate_json(data)

            # Verify not expired
            if datetime.now(timezone.utc) > refresh.expires_at:
                logger.warning("[MCP OAuth] Refresh token expired")
                return None

            return refresh

        except asyncio.TimeoutError:
            logger.error("[MCP OAuth] Redis timeout getting refresh token")
            return None
        except Exception as e:
            logger.error(f"[MCP OAuth] Error getting refresh token: {e}")
            return None

    async def revoke_refresh_token(self, token: str) -> bool:
        """
        Revoke (delete) a refresh token.

        Args:
            token: The refresh token to revoke

        Returns:
            True if deleted, False otherwise
        """
        if not self.redis:
            return False

        try:
            key = f"{KEY_PREFIX_REFRESH_TOKEN}{token}"

            deleted = await asyncio.wait_for(self.redis.delete(key), timeout=2.0)

            if deleted:
                logger.info("[MCP OAuth] Revoked refresh token")
            return bool(deleted)

        except asyncio.TimeoutError:
            logger.error("[MCP OAuth] Redis timeout revoking refresh token")
            return False
        except Exception as e:
            logger.error(f"[MCP OAuth] Error revoking refresh token: {e}")
            return False

    async def rotate_refresh_token(
        self, old_token: str
    ) -> Optional[tuple[str, StoredRefreshToken]]:
        """
        Rotate a refresh token (revoke old, issue new).

        This is a security best practice for public clients.

        Args:
            old_token: The current refresh token

        Returns:
            Tuple of (new_token, stored_data) or None on failure
        """
        # Get existing token data
        existing = await self.get_refresh_token(old_token)
        if not existing:
            return None

        # Revoke old token
        await self.revoke_refresh_token(old_token)

        # Issue new token with same claims
        new_token = await self.store_refresh_token(
            client_id=existing.client_id,
            user_id=existing.user_id,
            scope=existing.scope,
        )

        if not new_token:
            return None

        # Get the newly stored token data
        new_data = await self.get_refresh_token(new_token)
        if not new_data:
            return None

        return new_token, new_data
