"""
REST API routes for API key management.
Used by the settings UI to create, list, and revoke API keys.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from utils.api_keys import create_api_key, list_api_keys, revoke_api_key
from utils.auth import extract_token_from_cookies, verify_token
from utils.database_pool import get_native_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/keys", tags=["api-keys"])


async def _get_user_id(request: Request) -> str:
    """Extract and verify user_id from request cookies."""
    cookie = request.headers.get("cookie", "")
    if not cookie:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        token, user_id = await extract_token_from_cookies(cookie)
        await verify_token(token)
        return user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication")


class CreateKeyRequest(BaseModel):
    name: str
    workflow_id: Optional[str] = None
    permissions: List[str] = ["read", "execute", "write"]


class CreateKeyResponse(BaseModel):
    raw_key: str
    id: str
    name: str
    key_prefix: str
    workflow_id: Optional[str]
    permissions: List[str]
    created_at: str


class KeyInfo(BaseModel):
    id: str
    name: str
    key_prefix: str
    workflow_id: Optional[str]
    permissions: List[str]
    created_at: str
    last_used_at: Optional[str]
    expires_at: Optional[str]
    revoked_at: Optional[str]


@router.post("", response_model=CreateKeyResponse)
async def create_key(request: Request, body: CreateKeyRequest):
    """Create a new API key."""
    user_id = await _get_user_id(request)
    pool = get_native_pool()
    async with pool.acquire() as conn:
        raw_key, info = await create_api_key(
            conn,
            user_id=user_id,
            name=body.name,
            permissions=body.permissions,
            workflow_id=body.workflow_id,
        )
    return CreateKeyResponse(
        raw_key=raw_key,
        id=info.id,
        name=info.name,
        key_prefix=info.key_prefix,
        workflow_id=info.workflow_id,
        permissions=info.permissions,
        created_at=info.created_at,
    )


@router.get("", response_model=List[KeyInfo])
async def list_keys(request: Request):
    """List all API keys for the current user."""
    user_id = await _get_user_id(request)
    pool = get_native_pool()
    async with pool.acquire() as conn:
        keys = await list_api_keys(conn, user_id)
    return [
        KeyInfo(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            workflow_id=k.workflow_id,
            permissions=k.permissions,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            revoked_at=k.revoked_at,
        )
        for k in keys
    ]


@router.delete("/{key_id}")
async def revoke_key(request: Request, key_id: str):
    """Revoke an API key."""
    user_id = await _get_user_id(request)
    pool = get_native_pool()
    async with pool.acquire() as conn:
        success = await revoke_api_key(conn, key_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Key not found or already revoked")
    return {"success": True}
