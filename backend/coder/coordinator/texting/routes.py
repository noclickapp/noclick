"""The texting webhooks: Meta's for the WhatsApp number (the subscription handshake, then every delivery verified
against the app secret) and Sendblue's "receive" webhook for the iMessage line (checked against the shared secret).
Each delivery is acknowledged before any turn runs; a provider that gets no answer delivers again."""

from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from coder.coordinator.texting import imessage, whatsapp
from utils.async_helpers import spawn
from utils.capabilities import WHATSAPP_STATUSES, capability
from utils.database_pool import get_native_pool
from utils.sendblue import Sendblue
from utils.whatsapp_cloud_api import CloudApi

logger = logging.getLogger(__name__)

WHATSAPP_PATH = "/whatsapp/meta"
IMESSAGE_PATH = "/imessage/sendblue"
VERIFY_TOKEN_VAR = "WHATSAPP_WEBHOOK_VERIFY_TOKEN"
APP_SECRET_VAR = "WHATSAPP_APP_SECRET"

router = APIRouter()


@router.get(WHATSAPP_PATH)
async def verify_subscription(request: Request) -> PlainTextResponse:
    params = request.query_params
    expected = os.environ.get(VERIFY_TOKEN_VAR, "").strip()
    if (params.get("hub.mode") == "subscribe" and expected
            and hmac.compare_digest(params.get("hub.verify_token", ""), expected)):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="verification failed")


@router.post(WHATSAPP_PATH)
async def receive_whatsapp(request: Request) -> Dict[str, Any]:
    secret = os.environ.get(APP_SECRET_VAR, "").strip()
    api = CloudApi.from_env()
    if not secret or api is None:
        raise HTTPException(status_code=503, detail="whatsapp inbound is not configured")
    body = await request.body()
    if not whatsapp.verify_signature(secret, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="bad signature")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="not json")
    messages = whatsapp.parse_inbound(payload, phone_number_id=api.phone_number_id)
    for message in messages:
        spawn(whatsapp.handle_inbound(message, api), name=f"whatsapp-inbound:{message.wamid}")
    # A redelivery re-spawns its messages, which handle_inbound answers once. What a platform does with the
    # delivery's statuses runs before the acknowledgement, so a write that didn't land is redelivered.
    statuses = capability(WHATSAPP_STATUSES)
    if statuses is not None:
        await statuses(get_native_pool(), payload, phone_number_id=api.phone_number_id)
    return {"ok": True, "messages": len(messages)}


@router.post(IMESSAGE_PATH)
async def receive_imessage(request: Request) -> Dict[str, Any]:
    secret = imessage.webhook_secret()
    api = Sendblue.from_env()
    if not secret or api is None:
        raise HTTPException(status_code=503, detail="imessage inbound is not configured")
    if not imessage.verify_secret(secret, request.headers.get("sb-signing-secret")):
        raise HTTPException(status_code=403, detail="bad secret")
    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=400, detail="not json")
    message = imessage.parse_inbound(payload if isinstance(payload, dict) else {}, line=api.number)
    if message is not None:
        spawn(imessage.handle_inbound(message, api), name=f"imessage-inbound:{message.handle}")
    return {"ok": True, "messages": int(message is not None)}
