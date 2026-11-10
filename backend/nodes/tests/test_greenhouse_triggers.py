"""Exercise signed recruiting deliveries using Greenhouse's published examples.
The fixtures keep complete provider payloads and source URLs for review.
"""

import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.greenhouse_node import GREENHOUSE_EVENTS, GreenhouseNode, GreenhouseNodeConfig, GreenhouseOnEventConfig

EVENTS = json.loads((Path(__file__).parent / "fixtures/greenhouse/events.json").read_text())
CREDS = {"credential_type": "greenhouse_oauth_client", "client_id": "client", "client_secret": "secret"}


@pytest.mark.parametrize("action", GREENHOUSE_EVENTS)
def test_documented_event_reaches_workflow_and_agent(action):
    payload = EVENTS[action]["body"]
    config = {"operation": "on_event", "event_type": action, "signing_secret": "secret"}
    body = json.dumps(payload, ensure_ascii=True).encode()
    signature = "sha256 " + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert GreenhouseNode.handle_webhook_handshake(body, {}, config) is None
    assert GreenhouseNode.verify_webhook_signature(body, {"Signature": signature}, config)
    assert not GreenhouseNode.verify_webhook_signature(body + b" ", {"signature": signature}, config)
    assert not GreenhouseNode.verify_webhook_signature(body, {"signature": signature}, {})
    assert not GreenhouseNode.verify_webhook_signature(body, {}, config)
    assert not GreenhouseNode.verify_webhook_signature(body, {"signature": "sha256 ☃"}, config)
    assert GreenhouseNode.filter_trigger_payload(payload, config)
    output = GreenhouseNode.resolve_trigger_payload(payload, config)
    assert output["data"] == payload
    agent = GreenhouseNode.resolve_agent_event(output)
    record = payload["payload"]["candidate" if action == "update_candidate" else "application"]
    candidate = record if action == "update_candidate" else record["candidate"]
    assert candidate["first_name"] in agent["text"]
    assert str(candidate["id"]) in agent["text"]
    assert record["url"] in agent["text"]
    assert agent["conversation_key"] == f"{'candidate' if action == 'update_candidate' else 'application'}:{record['id']}"
    if action != "update_candidate":
        for job in record["jobs"]:
            assert job["name"] in agent["text"]
            assert str(job["id"]) in agent["text"]
    if action == "candidate_stage_change":
        assert record["current_stage"]["name"] in agent["text"]
    if action == "reject_candidate":
        assert record["rejection_reason"]["name"] in agent["text"]
    other = "update_candidate" if action != "update_candidate" else "hire_candidate"
    assert not GreenhouseNode.filter_trigger_payload(payload, {**config, "event_type": other})


@pytest.mark.asyncio
@pytest.mark.parametrize("action", GREENHOUSE_EVENTS)
async def test_partner_registration_and_teardown(action):
    calls = []
    webhook_url = "https://example.hooks.example.test/"
    def handler(request):
        calls.append(request)
        if request.url.host == "auth.greenhouse.io":
            assert request.content == b"grant_type=client_credentials"
            return httpx.Response(200, json={"access_token": "token"})
        assert request.headers["authorization"] == "Bearer token"
        if request.method == "POST":
            assert request.url.path == "/v3/webhooks"
            body = json.loads(request.content)
            assert body == {"endpoint_url": webhook_url, "name": "NoClick gh", "event_action_type": action,
                            "secret_key": body["secret_key"], "max_attempts": 6}
            assert len(body["secret_key"]) >= 32
            return httpx.Response(201, json={"id": 11866816, "deactivated": False})
        assert request.method == "DELETE"
        assert request.url.path == "/v3/webhooks/11866816"
        return httpx.Response(200, json={"message": "Webhook 11866816 deleted successfully"})
    original = httpx.AsyncClient
    with patch("nodes.greenhouse_node.httpx.AsyncClient", side_effect=lambda *a, **kw: original(transport=httpx.MockTransport(handler), **kw)):
        extra = await GreenhouseNode._register_external_webhook(webhook_url=webhook_url, credential=CREDS, config={"event_type": action}, node_id="gh")
        await GreenhouseNode._unregister_external_webhook(credential=CREDS, config=extra, node_id="gh")
    assert extra["external_webhook_id"] == "11866816"
    registered = json.loads(next(r.content for r in calls if r.url.path == "/v3/webhooks"))
    assert registered["secret_key"] == extra["signing_secret"]
    assert GreenhouseNode.registration_fingerprint_fields({"event_type": action}) == {"event_type": action}


@pytest.mark.asyncio
async def test_registration_and_teardown_report_provider_errors():
    original = httpx.AsyncClient
    def handler(request):
        if request.url.host == "auth.greenhouse.io":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(403, json={"message": "Partner permission required"})
    with patch("nodes.greenhouse_node.httpx.AsyncClient", side_effect=lambda *a, **kw: original(transport=httpx.MockTransport(handler), **kw)):
        with pytest.raises(ValueError, match="Partner permission required"):
            await GreenhouseNode._register_external_webhook(webhook_url="https://example.hooks.example.test/", credential=CREDS, config={}, node_id="gh")
        with pytest.raises(ValueError, match="Partner permission required"):
            await GreenhouseNode._unregister_external_webhook(credential=CREDS, config={"external_webhook_id": "11866816"}, node_id="gh")
    with pytest.raises(ValueError, match="Connect"):
        await GreenhouseNode._unregister_external_webhook(credential=None, config={"external_webhook_id": "11866816"}, node_id="gh")


@pytest.mark.asyncio
async def test_disabled_registration_is_removed_and_reported():
    methods = []
    original = httpx.AsyncClient
    def handler(request):
        if request.url.host == "auth.greenhouse.io":
            return httpx.Response(200, json={"access_token": "token"})
        methods.append(request.method)
        return httpx.Response(201, json={"id": 11866816, "deactivated": True}) if request.method == "POST" else httpx.Response(200, json={})
    with patch("nodes.greenhouse_node.httpx.AsyncClient", side_effect=lambda *a, **kw: original(transport=httpx.MockTransport(handler), **kw)):
        with pytest.raises(ValueError, match="ping failed"):
            await GreenhouseNode._register_external_webhook(webhook_url="https://example.hooks.example.test/", credential=CREDS, config={}, node_id="gh")
    assert methods == ["POST", "DELETE"]


@pytest.mark.asyncio
async def test_manual_execute_waits_without_registering():
    node = GreenhouseNode(node_id="gh", node_type="automation-greenhouse", node_data={},
                         config=GreenhouseNodeConfig(config=GreenhouseOnEventConfig(), credentials=CREDS), sio=Mock())
    with patch("nodes.greenhouse_node.httpx.AsyncClient", side_effect=AssertionError("must not register")):
        result = await node.execute({})
    assert result["awaiting_event"] is True
