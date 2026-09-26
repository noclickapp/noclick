"""Bearer-authenticated owner actions for paid credential requests.

Possession of a public credential link alone never grants spending authority.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from billing.gates import GateDenied

from utils.auth import verify_token
from utils.database_pool import get_native_pool
from utils.feature_gates import FeatureNotAvailable
from utils.phone_purchase import PhonePurchase
from wss.handlers.phone_number_handler import PhoneNumberError

router = APIRouter()


async def owner(authorization: str = Header(default="")):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Sign in to the account that requested this number.")
    try:
        claims = await verify_token(token)
        user_id = str(UUID(claims["sub"]))
    except Exception:
        raise HTTPException(401, "Sign in to the account that requested this number.") from None
    return PhonePurchase(get_native_pool(), user_id)


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str = "US"
    area_code: str | None = None
    contains: str | None = None
    limit: int = Field(default=10, ge=1, le=20)


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_number: str = Field(max_length=30)


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID


async def response(operation):
    try:
        return await operation
    except FeatureNotAvailable as exc:
        raise HTTPException(403, str(exc)) from None
    except (PhoneNumberError, GateDenied) as exc:
        raise HTTPException(400, {"error": str(exc), "kind": exc.kind}) from None


@router.get("/{token}/phone")
async def status(token: str, service=Depends(owner)):
    return await service.status(token)


@router.post("/{token}/phone/search")
async def search(token: str, body: Search, service=Depends(owner)):
    await service.request(token)
    return await response(service.search(**body.model_dump()))


@router.post("/{token}/phone/quote")
async def quote(token: str, body: Quote, service=Depends(owner)):
    return await response(service.quote(token, body.phone_number))


@router.post("/{token}/phone/confirm")
async def confirm(token: str, body: Confirm, service=Depends(owner)):
    return await response(service.confirm(token, str(body.quote_id)))
