"""Authenticated Pipedrive Marketplace installation and uninstall callbacks.

The frontend validates browser/owner-bound state before forwarding a code;
the backend independently verifies its session and configured redirect URI.
Uninstalls use provider Basic authentication and app/company/user-scoped cleanup.
"""

import base64
import hmac
import logging
import os
import re
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from nodes.oauth.pipedrive_oauth import get_pipedrive_client_config
from repositories.credentials import CredentialsRepo
from utils.auth import verify_token
from utils.database_pool import get_native_pool
from utils.pipedrive_connection import PipedriveConnectionError, connect_pipedrive

router = APIRouter(tags=["pipedrive-install"])
logger = logging.getLogger(__name__)


class PipedriveInstallExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    redirect_uri: str = Field(min_length=1, max_length=2048)


class PipedriveUninstallRequest(BaseModel):
    client_id: str = Field(strict=True, min_length=1, max_length=128)
    company_id: str
    user_id: str

    @field_validator("company_id", "user_id", mode="before")
    @classmethod
    def positive_provider_id(cls, value: object) -> str:
        if type(value) not in (int, str) or not re.fullmatch(
            r"[1-9][0-9]{0,19}", str(value)
        ):
            raise ValueError("Invalid Pipedrive identity")
        return str(value)


@router.post("/pipedrive/install/uninstall")
async def uninstall_public_install(request: Request) -> dict:
    """Authenticate the provider before atomically removing its exact grant."""
    try:
        client_id, client_secret = get_pipedrive_client_config()
    except ValueError:
        raise HTTPException(
            status_code=500, detail="Pipedrive is not configured"
        ) from None

    scheme, _, provided = request.headers.get("authorization", "").partition(" ")
    expected = base64.b64encode(f"{client_id}:{client_secret}".encode())
    if scheme.lower() != "basic" or not hmac.compare_digest(
        provided.encode(), expected
    ):
        raise HTTPException(status_code=401, detail="Invalid provider authentication")

    try:
        body = PipedriveUninstallRequest.model_validate(await request.json())
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid Pipedrive uninstall identity"
        ) from None
    if body.client_id != client_id:
        raise HTTPException(
            status_code=400, detail="Invalid Pipedrive uninstall client"
        )

    try:
        removed = await CredentialsRepo(get_native_pool()).remove_pipedrive_install(
            client_id, body.company_id, body.user_id
        )
    except Exception as exc:
        # SQL exception text can include credential data; retain only its type.
        logger.error("Pipedrive uninstall cleanup failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500, detail="Pipedrive cleanup failed"
        ) from None
    return {"success": True, "removed": removed}


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
