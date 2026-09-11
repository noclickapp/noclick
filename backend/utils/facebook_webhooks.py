"""Signed app-level Facebook callbacks with live Page/credential isolation."""

import hmac
import os
import re
from uuid import UUID

import httpx
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from utils.credential_loader import load_credential
from utils.facebook_events import (
    MAX_BODY_BYTES, facebook_event_guard, facebook_event_matches_config,
    facebook_page_id, facebook_trigger_credential_id, parse_facebook_webhook,
)
from utils.facebook_subscriptions import (
    _request, authorize_page, require_facebook_webhook_configuration, required_event_fields,
)
from utils.graph_nodes import node_config
from utils.meta_subscriptions import MetaAuthorizationDenied, read_subscribed_fields
from utils.webhook_signatures import verify_hmac_sha256_hex


def verify_facebook_webhook(pool, body, headers, request_url):
    del pool, request_url
    try:
        app = require_facebook_webhook_configuration()
    except ValueError:
        return False
    signature = headers.get("x-hub-signature-256")
    return bool(isinstance(signature, str) and re.fullmatch(r"sha256=[0-9a-f]{64}", signature)
                and verify_hmac_sha256_hex(body, app.app_secret, signature, prefix="sha256="))


def facebook_handshake(query):
    expected = os.environ.get("FACEBOOK_WEBHOOK_VERIFY_TOKEN") or ""
    supplied = query.get("hub.verify_token", "")
    if (not expected.strip() or not isinstance(supplied, str) or query.get("hub.mode") != "subscribe"
            or not hmac.compare_digest(expected.encode(), supplied.encode())):
        raise HTTPException(status_code=403, detail="Invalid Facebook webhook verification")
    try:
        require_facebook_webhook_configuration()
    except ValueError:
        raise HTTPException(status_code=503, detail="Facebook callback configuration is unavailable") from None
    challenge = query.get("hub.challenge")
    if not isinstance(challenge, str) or not 1 <= len(challenge) <= 1024:
        raise HTTPException(status_code=400, detail="Missing or invalid webhook challenge")
    return PlainTextResponse(challenge, headers={"Cache-Control": "no-store"})


async def facebook_live_scope_filter(pool, sub, payload, trigger_node):
    config = node_config(trigger_node)
    page = facebook_page_id(payload.get("page_id"))
    if (trigger_node.get("type") != "automation-facebook" or not facebook_event_matches_config(payload, config)
            or sub.get("provider") != "facebook" or sub.get("event_type") != payload.get("event_type")
            or str(sub.get("tenant_id")) != page):
        return "Facebook trigger or Page binding changed"
    credential_id = facebook_trigger_credential_id(config.get("credentialIds"))
    if credential_id != str(sub.get("credential_id")):
        return "Facebook credential binding changed"
    from utils.webhook_manager import _load_workflow_owner_and_nodes

    owner, _ = await _load_workflow_owner_and_nodes(pool, UUID(str(sub["workflow_id"])), include_nodes=False)
    if owner != str(sub["user_id"]):
        return "Facebook workflow ownership changed"
    credential = await load_credential(pool, str(sub["user_id"]), credential_id, raise_on_error=True)
    if not credential or credential.get("credential_type") != "facebook_oauth":
        return "Facebook credential is unavailable"
    from nodes.facebook_node import FacebookNode

    credential = await FacebookNode.freshen_credential(credential, pool=pool, user_id=str(sub["user_id"]), credential_id=credential_id)
    app = require_facebook_webhook_configuration()
    try:
        page_token = await authorize_page(credential, page, app, required_event_fields(config.get("operation")))
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {page_token}"}) as client:
            subscribed = await read_subscribed_fields(_request(client, page_token, app), page, {app.app_id},
                                                      label="Facebook", require_matching_if_nonempty=False)
        if payload.get("event_type") not in subscribed:
            return "Facebook Page subscription is no longer authorized"
    except MetaAuthorizationDenied:
        return "Facebook Page authorization is no longer available"
    # Unavailable/ambiguous verification raises; the dispatcher returns retryable 503.
    return None


FACEBOOK_WEBHOOK_ADAPTER = {
    "verify": verify_facebook_webhook,
    "handshake": lambda body: None,
    "parse": parse_facebook_webhook,
    "event_id": lambda payload: payload["event_id"],
    "event_guard": facebook_event_guard,
    "subscription_guard": facebook_event_guard,
    "subscription_event_id": lambda payload: payload["event_id"],
    "live_scope_filter": facebook_live_scope_filter,
    "max_body_bytes": MAX_BODY_BYTES,
    "fire_budget": True,
}
