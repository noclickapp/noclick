"""Authenticated Pipedrive Marketplace installation exchange.

The frontend validates browser/owner-bound state before forwarding a code;
the backend independently verifies its session and configured redirect URI.
"""

import os
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from utils.auth import verify_token
from utils.database_pool import get_native_pool
from utils.pipedrive_connection import PipedriveConnectionError, connect_pipedrive

router = APIRouter(tags=["pipedrive-install"])


class PipedriveInstallExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    redirect_uri: str = Field(min_length=1, max_length=2048)


@router.post("/pipedrive/install/exchange")
async def exchange_public_install(
    request: Request, body: PipedriveInstallExchangeRequest
) -> dict:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = await verify_token(token)
        user_id = str(UUID(str(claims.get("sub") or "")))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication") from None

    configured_redirect = os.environ.get("PIPEDRIVE_REDIRECT_URI")
    if not configured_redirect or body.redirect_uri != configured_redirect:
        raise HTTPException(status_code=400, detail="Invalid Pipedrive redirect URI")
    try:
        return await connect_pipedrive(
            user_id=user_id,
            user_tier=str(claims.get("subscription_tier") or "free"),
            code=body.code,
            redirect_uri=configured_redirect,
            pool=get_native_pool(),
            installation=True,
        )
    except PipedriveConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception:
        raise HTTPException(
            status_code=502, detail="Could not finish the Pipedrive connection"
        ) from None
