"""Bearer-authenticated owner actions for paid credential requests.

Possession of a public credential link alone never grants spending authority.

``documents_router`` takes the file a number's requirement asks for at the
short-lived link ``document_upload_path`` signed for one account and
requirement (no session: the link is the capability, so the browser posts the
bytes straight here, past the page's server).
"""
from uuid import UUID

from typing import Dict, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from billing.gates import GateDenied

from utils.auth import acting_user_id, verify_token
from utils.database_pool import get_native_pool
from utils.feature_gates import FeatureNotAvailable
from utils.phone_numbers import PhoneDocumentRefused
from utils.phone_purchase import PhonePurchase
from utils.capabilities import PHONE_NUMBERS, capability
from wss.handlers.phone_number_handler import (
    DOCUMENT_UPLOAD_PATH, PhoneNumberError, contact_phone, document_upload_claims, number_query, sold_coverage,
)
from wss.receiver.client_events import ANSWERS, PhoneNumberHolder, PhoneNumberType, requirement_answers

router = APIRouter()
documents_router = APIRouter()
# The carrier's limit for a document; a body past it isn't read.
DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
_CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS",
         "Access-Control-Allow-Headers": "Content-Type"}


async def owner(request: Request, authorization: str = Header(default="")):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Sign in to the account that requested this number.")
    try:
        claims = await verify_token(token)
        user_id = str(UUID(claims["sub"]))
    except Exception:
        raise HTTPException(401, "Sign in to the account that requested this number.") from None
    return PhonePurchase(get_native_pool(), await acting_user_id(request, user_id, claims))


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str = "US"
    number_type: PhoneNumberType = "local"
    area_code: Optional[str] = None
    locality: Optional[str] = None
    region: Optional[str] = None
    contains: Optional[str] = None
    starts_with: Optional[str] = None
    ends_with: Optional[str] = None
    features: Literal["voice", "voice_sms"] = "voice"
    limit: int = Field(default=10, ge=1, le=20)


class Places(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str
    number_type: PhoneNumberType = "local"


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_number: str = Field(max_length=30)
    country: str = Field("US", max_length=2)  # older pages quote a US local number
    number_type: PhoneNumberType = "local"


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID
    holder: Optional[PhoneNumberHolder] = None
    answers: Dict[str, str] = Field(default_factory=dict, description=ANSWERS)

    @field_validator("answers")
    @classmethod
    def _answers(cls, value: Dict[str, str]) -> Dict[str, str]:
        return requirement_answers(value)


class Resubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    holder: Optional[PhoneNumberHolder] = None
    answers: Dict[str, str] = Field(default_factory=dict, description=ANSWERS)

    @field_validator("answers")
    @classmethod
    def _answers(cls, value: Dict[str, str]) -> Dict[str, str]:
        return requirement_answers(value)


class DocumentUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str = Field(..., pattern=r"^[A-Z]{2}$")
    number_type: PhoneNumberType = "local"
    requirement_id: str = Field(..., min_length=1, max_length=64)


class DocumentRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(..., min_length=1, max_length=64)


async def response(operation):
    try:
        return await operation
    except FeatureNotAvailable as exc:
        raise HTTPException(403, str(exc)) from None
    except PhoneNumberError as exc:
        raise HTTPException(400, {"error": str(exc), "kind": exc.kind, **exc.details}) from None
    except PhoneDocumentRefused as exc:
        raise HTTPException(400, {"error": str(exc), "kind": "document"}) from None
    except GateDenied as exc:
        raise HTTPException(400, {"error": str(exc), "kind": exc.kind}) from None


@router.get("/{token}/phone")
async def status(token: str, service=Depends(owner)):
    return await service.status(token)


@router.post("/{token}/phone/coverage")
async def coverage(token: str, service=Depends(owner)):
    await service.request(token)

    async def read():
        await service.actor()
        return {"countries": await sold_coverage(),
                "contact_phone": await contact_phone(service.pool, service.user_id)}

    return await response(read())


@router.post("/{token}/phone/places")
async def places(token: str, body: Places, service=Depends(owner)):
    await service.request(token)

    async def read():
        await service.actor()
        query = number_query(country=body.country, number_type=body.number_type)
        return {"places": await capability(PHONE_NUMBERS).places(query["country"], query["number_type"])}

    return await response(read())


@router.post("/{token}/phone/search")
async def search(token: str, body: Search, service=Depends(owner)):
    await service.request(token)
    return await response(service.search(**body.model_dump()))


@router.post("/{token}/phone/quote")
async def quote(token: str, body: Quote, service=Depends(owner)):
    return await response(service.quote(token, body.phone_number, country=body.country,
                                         number_type=body.number_type))


@router.post("/{token}/phone/confirm")
async def confirm(token: str, body: Confirm, service=Depends(owner)):
    holder = body.holder.model_dump() if body.holder is not None else None
    return await response(service.confirm(token, str(body.quote_id), holder, body.answers))


@router.post("/{token}/phone/resubmit")
async def resubmit(token: str, body: Resubmit, service=Depends(owner)):
    holder = body.holder.model_dump() if body.holder is not None else None
    return await response(service.resubmit(token, holder, body.answers))


@router.post("/{token}/phone/documents")
async def documents(token: str, service=Depends(owner)):
    await service.request(token)

    async def read():
        await service.actor()
        return {"documents": await capability(PHONE_NUMBERS).documents(service.user_id)}

    return await response(read())


@router.post("/{token}/phone/document_upload")
async def document_upload(token: str, body: DocumentUpload, service=Depends(owner)):
    await service.request(token)
    return await response(service.document_upload(**body.model_dump()))


@router.post("/{token}/phone/document_remove")
async def document_remove(token: str, body: DocumentRemove, service=Depends(owner)):
    await service.request(token)

    async def remove():
        await service.actor()
        return await capability(PHONE_NUMBERS).remove_document(service.user_id, body.document_id)

    return await response(remove())


@documents_router.options(DOCUMENT_UPLOAD_PATH)
async def document_preflight() -> Response:
    return Response(status_code=204, headers=_CORS)


@documents_router.post(DOCUMENT_UPLOAD_PATH)
async def upload_document(request: Request):
    """A document's bytes for the requirement and account its link was signed for, held by the carrier."""
    claims = document_upload_claims(request.query_params.get("token", ""))
    if claims is None:
        return JSONResponse({"error": "This upload link has expired. Choose the file again."}, status_code=403,
                            headers=_CORS)
    numbers = capability(PHONE_NUMBERS)
    if numbers is None:
        return JSONResponse({"error": "Phone numbers cannot be bought on this instance."}, status_code=404,
                            headers=_CORS)
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > DOCUMENT_MAX_BYTES:
        return JSONResponse({"error": f"A document is up to {DOCUMENT_MAX_BYTES // (1024 * 1024)} MB."},
                            status_code=413, headers=_CORS)
    chunks, received = [], 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > DOCUMENT_MAX_BYTES:
            return JSONResponse({"error": f"A document is up to {DOCUMENT_MAX_BYTES // (1024 * 1024)} MB."},
                                status_code=413, headers=_CORS)
        chunks.append(chunk)
    try:
        document = await numbers.upload_document(
            claims["user_id"], country=claims["country"], number_type=claims["number_type"],
            requirement_id=claims["requirement_id"], filename=request.query_params.get("filename", ""),
            content=b"".join(chunks))
    except PhoneDocumentRefused as exc:
        return JSONResponse({"error": str(exc), "kind": "document"}, status_code=400, headers=_CORS)
    return JSONResponse({"document": document}, headers=_CORS)
