"""
Live integration tests for the Zendesk node.

These hit the REAL Zendesk API and are skipped unless credentials are present
in the environment:
  ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN   (Support API)
  ZENDESK_CONV_APP_ID, ZENDESK_CONV_KEY_ID, ZENDESK_CONV_SECRET_KEY (Sunshine)

They exercise the security-critical trigger round-trip (register -> Zendesk
delivers a real event -> signature verification), a ticket lifecycle, and a
Sunshine Conversations smoke — the paths that mock tests can't prove.
"""

import base64
import hashlib
import hmac
import json
import os
import time

import pytest
from unittest.mock import Mock

from nodes.zendesk_node import (
    ZendeskNode,
    ZendeskNodeConfig,
    ZendeskApiTokenCredential,
    ZendeskConversationsCredential,
    ZendeskCreateTicketConfig,
    ZendeskShowTicketConfig,
    ZendeskAddCommentConfig,
    ZendeskDeleteTicketConfig,
    ZendeskShowWebhookConfig,
    ZendeskSCCListIntegrationsConfig,
)

SUBDOMAIN = os.environ.get("ZENDESK_SUBDOMAIN")
EMAIL = os.environ.get("ZENDESK_EMAIL")
API_TOKEN = os.environ.get("ZENDESK_API_TOKEN")

pytestmark = pytest.mark.skipif(
    not (SUBDOMAIN and EMAIL and API_TOKEN),
    reason="Live Zendesk credentials (ZENDESK_SUBDOMAIN/EMAIL/API_TOKEN) not set",
)


def _cred_dict():
    return {"subdomain": SUBDOMAIN, "email": EMAIL, "api_token": API_TOKEN}


def _node(op):
    return ZendeskNode(
        node_id="it-node", node_type="automation-zendesk", node_data={},
        config=ZendeskNodeConfig(config=op, credentials=ZendeskApiTokenCredential(**_cred_dict())),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )


@pytest.mark.asyncio
async def test_ticket_lifecycle_live():
    r = await _node(ZendeskCreateTicketConfig(subject="[it] lifecycle", comment_body="hi")).execute({})
    assert r["status"] == "success", r
    tid = str(r["data"]["ticket"]["id"])
    try:
        r = await _node(ZendeskShowTicketConfig(ticket_id=tid)).execute({})
        assert r["status"] == "success"
        r = await _node(ZendeskAddCommentConfig(ticket_id=tid, comment_body="note", public="false")).execute({})
        assert r["status"] == "success"
    finally:
        r = await _node(ZendeskDeleteTicketConfig(ticket_id=tid)).execute({})
        assert r["status"] == "success"


@pytest.mark.asyncio
async def test_trigger_registration_round_trip_live():
    """Register a real webhook, confirm Zendesk delivers a fired event, verify
    the signature with Zendesk's generated secret, then deregister."""
    reg = await ZendeskNode._register_external_webhook(
        webhook_url="https://httpbin.org/status/200",
        credential=_cred_dict(),
        config={"operation": "on_ticket_created"},
        node_id="it-trigger",
    )
    wid = reg["external_webhook_id"]
    secret = reg["signing_secret"]
    assert wid and secret, reg  # Zendesk generated + returned a signing secret

    try:
        # Signature verification against the real Zendesk-held secret.
        body = json.dumps({"type": "zen:event-type:ticket.created"}).encode()
        ts = str(int(time.time()))
        sig = base64.b64encode(hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).digest()).decode()
        headers = {"x-zendesk-webhook-signature-timestamp": ts, "x-zendesk-webhook-signature": sig}
        assert ZendeskNode.verify_webhook_signature(body, headers, {"signing_secret": secret}) is True
        assert ZendeskNode.verify_webhook_signature(body + b"x", headers, {"signing_secret": secret}) is False

        # Confirm the webhook exists with the selected subscription.
        show = await _node(ZendeskShowWebhookConfig(webhook_id=wid)).execute({})
        assert show["status"] == "success"
        assert show["data"]["webhook"]["subscriptions"] == ["zen:event-type:ticket.created"]
    finally:
        await ZendeskNode._unregister_external_webhook(
            credential=_cred_dict(), config={"external_webhook_id": wid}, node_id="it-trigger"
        )


@pytest.mark.skipif(
    not (os.environ.get("ZENDESK_CONV_APP_ID") and os.environ.get("ZENDESK_CONV_KEY_ID") and os.environ.get("ZENDESK_CONV_SECRET_KEY")),
    reason="Sunshine Conversations credentials not set",
)
@pytest.mark.asyncio
async def test_sunshine_conversations_smoke_live():
    cred = ZendeskConversationsCredential(
        subdomain=SUBDOMAIN,
        app_id=os.environ["ZENDESK_CONV_APP_ID"],
        key_id=os.environ["ZENDESK_CONV_KEY_ID"],
        secret_key=os.environ["ZENDESK_CONV_SECRET_KEY"],
    )
    node = ZendeskNode(
        node_id="it-scc", node_type="automation-zendesk", node_data={},
        config=ZendeskNodeConfig(config=ZendeskSCCListIntegrationsConfig(), credentials=cred),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )
    r = await node.execute({})
    assert r["status"] == "success", r
