"""
API key management for external SDK authentication.

Keys are prefixed with 'nk_live_' for easy identification.
Only the SHA-256 hash is stored — raw keys are returned once at creation time.
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KEY_PREFIX = "nk_live_"
KEY_BYTES = 32  # 32 bytes = 64 hex chars


def generate_key() -> str:
    """Generate a new API key with prefix."""
    return KEY_PREFIX + secrets.token_hex(KEY_BYTES)


def hash_key(raw_key: str) -> str:
    """SHA-256 hash of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def key_prefix(raw_key: str) -> str:
    """Extract the identifiable prefix (first 12 chars) from a raw key."""
    return raw_key[:12]


@dataclass
class APIKeyInfo:
    id: str
    user_id: str
    name: str
    key_prefix: str
    workflow_id: Optional[str]
    permissions: List[str]
    created_at: str
    last_used_at: Optional[str]
    expires_at: Optional[str]
    revoked_at: Optional[str]


async def create_api_key(
    conn: Any,
    user_id: str,
    name: str,
    permissions: List[str],
    workflow_id: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> tuple[str, APIKeyInfo]:
    """
    Create a new API key.

    Returns (raw_key, key_info). The raw_key is only returned once — store it securely.
    """
    raw_key = generate_key()
    hashed = hash_key(raw_key)
    prefix = key_prefix(raw_key)

    row = await conn.fetchrow(
        """
        INSERT INTO api_keys (user_id, key_hash, key_prefix, name, workflow_id, permissions, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id, created_at
        """,
        user_id,
        hashed,
        prefix,
        name,
        workflow_id,
        permissions,
        expires_at,
    )

    info = APIKeyInfo(
        id=str(row["id"]),
        user_id=user_id,
        name=name,
        key_prefix=prefix,
        workflow_id=workflow_id,
        permissions=permissions,
        created_at=row["created_at"].isoformat(),
        last_used_at=None,
        expires_at=expires_at.isoformat() if expires_at else None,
        revoked_at=None,
    )

    logger.info("[API Keys] Created API key id=%s", info.id)
    return raw_key, info


async def validate_api_key(conn: Any, raw_key: str) -> Optional[Dict[str, Any]]:
    """
    Validate an API key and return the associated user info.

    Returns dict with user_id, workflow_id, permissions on success.
    Returns None if the key is invalid, expired, or revoked.
    Also updates last_used_at.
    """
    if not raw_key.startswith(KEY_PREFIX):
        return None

    hashed = hash_key(raw_key)

    row = await conn.fetchrow(
        """
        SELECT id, user_id, workflow_id, permissions, expires_at, revoked_at
        FROM api_keys
        WHERE key_hash = $1
        """,
        hashed,
    )

    if not row:
        return None

    # Check if revoked
    if row["revoked_at"] is not None:
        logger.warning("[API Keys] Rejected revoked API key id=%s", row["id"])
        return None

    # Check if expired
    if row["expires_at"] is not None and row["expires_at"] < datetime.now(row["expires_at"].tzinfo):
        logger.warning("[API Keys] Rejected expired API key id=%s", row["id"])
        return None

    # Update last_used_at (fire and forget — don't block auth on this)
    await conn.execute(
        "UPDATE api_keys SET last_used_at = now() WHERE id = $1",
        row["id"],
    )

    return {
        "key_id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "workflow_id": str(row["workflow_id"]) if row["workflow_id"] else None,
        "permissions": list(row["permissions"]),
    }


async def revoke_api_key(conn: Any, key_id: str, user_id: str) -> bool:
    """Revoke an API key. Returns True if found and revoked."""
    result = await conn.execute(
        "UPDATE api_keys SET revoked_at = now() WHERE id = $1 AND user_id = $2 AND revoked_at IS NULL",
        key_id,
        user_id,
    )
    return result == "UPDATE 1"


async def list_api_keys(conn: Any, user_id: str) -> List[APIKeyInfo]:
    """List all API keys for a user (active and revoked)."""
    rows = await conn.fetch(
        """
        SELECT id, user_id, key_prefix, name, workflow_id, permissions,
               created_at, last_used_at, expires_at, revoked_at
        FROM api_keys
        WHERE user_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )

    return [
        APIKeyInfo(
            id=str(r["id"]),
            user_id=str(r["user_id"]),
            name=r["name"],
            key_prefix=r["key_prefix"],
            workflow_id=str(r["workflow_id"]) if r["workflow_id"] else None,
            permissions=list(r["permissions"]),
            created_at=r["created_at"].isoformat(),
            last_used_at=r["last_used_at"].isoformat() if r["last_used_at"] else None,
            expires_at=r["expires_at"].isoformat() if r["expires_at"] else None,
            revoked_at=r["revoked_at"].isoformat() if r["revoked_at"] else None,
        )
        for r in rows
    ]
