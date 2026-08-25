"""
MCP-specific JWT token issuance and verification.

Issues short-lived, scoped tokens specifically for MCP access.
These tokens are separate from Supabase tokens and only grant access to MCP tools.
"""

import os
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from functools import lru_cache

import jwt

logger = logging.getLogger(__name__)

# Token configuration
MCP_TOKEN_AUDIENCE = "noclick-mcp"
MCP_TOKEN_ISSUER = "noclick"
DEFAULT_TOKEN_EXPIRY_HOURS = 24


@lru_cache()
def get_mcp_signing_key() -> str:
    """
    Get the MCP JWT signing key from environment.

    Falls back to generating a random key in development (logged as warning).
    Production deployments MUST set MCP_JWT_SIGNING_KEY.
    """
    key = os.getenv("MCP_JWT_SIGNING_KEY", "").strip()
    if key:
        return key

    # Development fallback - generate ephemeral key
    # This means tokens won't survive server restarts, which is fine for dev
    logger.warning(
        "[MCP Auth] MCP_JWT_SIGNING_KEY not set, generating ephemeral key. "
        "Tokens will not survive server restarts. Set MCP_JWT_SIGNING_KEY in production."
    )
    return secrets.token_hex(32)


def issue_mcp_token(
    user_id: str,
    client_id: str,
    scopes: list[str],
    expiry_hours: int = DEFAULT_TOKEN_EXPIRY_HOURS,
    extra_claims: dict | None = None,
) -> str:
    """
    Issue an MCP-specific JWT token.

    Args:
        user_id: NoClick user ID (from Supabase)
        client_id: The MCP client that was authorized
        scopes: List of granted scopes (e.g., ["mcp:tools"])
        expiry_hours: Token lifetime in hours (default 24)
        extra_claims: Additional installation-defined claims to embed

    Returns:
        Signed JWT token string
    """
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "client_id": client_id,
        "scope": " ".join(scopes),
        "aud": MCP_TOKEN_AUDIENCE,
        "iss": MCP_TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=expiry_hours),
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(payload, get_mcp_signing_key(), algorithm="HS256")

    logger.info(
        f"[MCP Auth] Issued token for user={user_id}, client={client_id}, "
        f"scopes={scopes}, expires_in={expiry_hours}h"
    )

    return token


def verify_mcp_token(token: str) -> dict:
    """
    Verify an MCP JWT token.

    Args:
        token: JWT token string (without "Bearer " prefix)

    Returns:
        Decoded token payload with keys: sub, client_id, scope, aud, iss, iat, exp

    Raises:
        jwt.InvalidTokenError: If token is invalid, expired, or has wrong audience/issuer
    """
    try:
        payload = jwt.decode(
            token,
            get_mcp_signing_key(),
            algorithms=["HS256"],
            audience=MCP_TOKEN_AUDIENCE,
            issuer=MCP_TOKEN_ISSUER,
            options={"require": ["sub", "client_id", "scope", "exp"]},
        )

        logger.debug(
            f"[MCP Auth] Verified token for user={payload.get('sub')}, "
            f"client={payload.get('client_id')}"
        )

        return payload

    except jwt.ExpiredSignatureError:
        logger.warning("[MCP Auth] Token expired")
        raise
    except jwt.InvalidAudienceError:
        logger.warning("[MCP Auth] Invalid token audience")
        raise
    except jwt.InvalidIssuerError:
        logger.warning("[MCP Auth] Invalid token issuer")
        raise
    except jwt.InvalidTokenError as e:
        logger.warning(f"[MCP Auth] Token verification failed: {e}")
        raise


def extract_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """
    Extract token from Authorization header.

    Args:
        authorization_header: Full Authorization header value (e.g., "Bearer xxx")

    Returns:
        Token string without prefix, or None if header is missing/malformed
    """
    if not authorization_header:
        return None

    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]
