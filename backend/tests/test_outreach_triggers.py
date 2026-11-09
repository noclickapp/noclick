"""Outreach registration and delivery contracts, from its provider-authored examples."""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.oauth.outreach_oauth import OAUTH_PROVIDER
from nodes.outreach_node import OUTREACH_WEBHOOK_EVENTS, OutreachNode, OutreachOnEventConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures/outreach/webhooks.json").read_text())


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_documented_deliveries_reach_agent(version):
    payload = FIXTURE[version]
    config = {"operation": "on_event", "event_type": "task.completed", "signing_secret": "foo"}
    body = json.dumps(payload).encode()
    signature = hmac.new(b"foo", body, hashlib.sha256).hexdigest()
    headers = {"Outreach-Webhook-Signature": signature}
    assert OutreachNode.verify_webhook_signature(body, headers, config)
    assert not OutreachNode.verify_webhook_signature(body + b" ", headers, config)
    assert OutreachNode.filter_trigger_payload(payload, config)
    output = OutreachNode.resolve_trigger_payload(payload, config)
    event = OutreachNode.resolve_agent_event(output)
    assert event["conversation_key"] == "task:1"
    for fragment in ["task.completed", "task 1", "completedAt", "2017-01-01T00:00:01", "id=1"]:
        assert fragment in event["text"]
    assert "signing_secret" not in event["text"]
    assert not OutreachNode.filter_trigger_payload(payload, {"event_type": "prospect.created"})


@pytest.mark.parametrize("header", ["", "bad", "é" * 64, "0" * 64])
def test_bad_signatures_are_rejected(header):
    assert not OutreachNode.verify_webhook_signature(b"{}", {"outreach-webhook-signature": header}, {"signing_secret": "foo"})
    assert not OutreachNode.verify_webhook_signature(b"{}", {"outreach-webhook-signature": header}, {})


@pytest.mark.parametrize("event_type", OUTREACH_WEBHOOK_EVENTS)
@pytest.mark.asyncio
async def test_registration_uses_documented_resource_action_pairs(event_type):
    calls = []
    def respond(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(201, json=FIXTURE["registration"])
        return httpx.Response(204)

    real_client = httpx.AsyncClient
    config = OutreachOnEventConfig(event_type=event_type).model_dump()
    with patch("nodes.outreach_node.httpx.AsyncClient", side_effect=lambda **kw: real_client(
        transport=httpx.MockTransport(respond), **kw
    )):
        registered = await OutreachNode._register_external_webhook(
            webhook_url="https://foo.bar/webhooks", credential={"access_token": "access"},
            config=config, node_id="test")
        await OutreachNode._unregister_external_webhook(
            credential={"access_token": "access"}, config=registered, node_id="test")
    body = json.loads(calls[0].content)
    resource, action = event_type.split(".")
    assert body == {"data": {"type": "webhook", "attributes": {
        "resource": resource, "action": action, "url": "https://foo.bar/webhooks",
        "secret": registered["signing_secret"],
    }}}
    assert registered["external_webhook_id"] == "1"
    assert calls[1].method == "DELETE"
    assert calls[1].url.path == "/api/v2/webhooks/1"
    assert OutreachNode.registration_fingerprint_fields(config) == {"event_type": event_type}


@pytest.mark.asyncio
async def test_registration_refuses_missing_id_and_credentials():
    with pytest.raises(ValueError, match="Connect Outreach"):
        await OutreachNode._register_external_webhook(webhook_url="https://foo.bar/webhooks", credential={}, config={}, node_id="test")
    with patch.object(OutreachNode, "_request", new=AsyncMock(return_value={"data": {}})):
        with pytest.raises(ValueError, match="webhook ID"):
            await OutreachNode._register_external_webhook(webhook_url="https://foo.bar/webhooks", credential={"access_token": "access"}, config={}, node_id="test")
    with pytest.raises(ValidationError):
        OutreachOnEventConfig(event_type="unsupported.event")


@pytest.mark.parametrize("status,raises", [(404, False), (401, True)])
@pytest.mark.asyncio
async def test_unregistration_only_tolerates_already_deleted(status, raises):
    with patch.object(OutreachNode, "_request", new=AsyncMock(side_effect=ValueError(f"Outreach API error {status}: request failed"))):
        args = dict(credential={"access_token": "access"}, config={"external_webhook_id": "1"}, node_id="test")
        if raises:
            with pytest.raises(ValueError):
                await OutreachNode._unregister_external_webhook(**args)
        else:
            await OutreachNode._unregister_external_webhook(**args)


@pytest.mark.parametrize("payload", [{"data": []}, {"data": [{"attributes": {"name": ""}}]}, {"errors": []}])
@pytest.mark.asyncio
async def test_oauth_identity_requires_visible_member(payload):
    real_client = httpx.AsyncClient
    with patch("nodes.oauth.outreach_oauth.guarded_async_client", side_effect=lambda **kw: real_client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)), **kw
    )):
        with pytest.raises(ValueError):
            await OAUTH_PROVIDER.account_name("access")
