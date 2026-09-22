"""The web's phone sign-in (the login page's fourth option). Supabase Auth
sends and checks the SMS code and issues the session; these two routes keep
it pointed at the right NoClick account:

- ``POST /api/auth/phone/prepare`` (public), before the code is sent: a number
  bound to an account becomes that account's auth phone, so the code signs
  into it. Same answer whether or not the number is bound.
- ``POST /api/auth/phone/confirmed`` (the new session's bearer token), after:
  a number that signed in without a binding (a first phone sign-in) is bound
  to its new account, so WhatsApp from it reaches the same place.
"""

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from utils.auth import verify_token
from utils.phone_identity import PhoneLinkError, default_service
from utils.supabase_admin import SupabaseAdminError

router = APIRouter(prefix="/api/auth/phone")


class Prepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(max_length=32)


@router.post("/prepare")
async def prepare(body: Prepare):
    try:
        phone = await default_service().prepare_sign_in(body.phone)
    except PhoneLinkError as exc:
        raise HTTPException(400, {"error": str(exc), "kind": exc.kind}) from None
    except SupabaseAdminError as exc:
        raise HTTPException(503, {"error": "Phone sign-in is unavailable right now", "kind": "unavailable"}) from exc
    return {"phone": phone}


@router.post("/confirmed")
async def confirmed(authorization: str = Header(default="")):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Sign in first")
    try:
        user_id = str(UUID((await verify_token(token))["sub"]))
    except Exception:
        raise HTTPException(401, "Sign in first") from None
    return {"phone": await default_service().bind_signed_in(user_id)}
