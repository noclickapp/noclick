"""Contract-backed request routing and signed delivery tests."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock
import jwt
import pytest
from nodes.ringover_node import RingoverNode, RingoverNodeConfig, OPERATIONS

CREDENTIAL = {"credential_type": "ringover_api_key", "api_key": "test-ringover-key"}
FIXTURES = Path(__file__).parent / "fixtures" / "ringover"

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", [
    ("create_contacts", {"contacts": [{"firstname": "John", "lastname": "Doe"}]}, "POST", "/contacts", {"contacts": [{"firstname": "John", "lastname": "Doe"}]}),
    ("get_team", {}, "GET", "/teams", None),
    ("get_call", {"callId": "123"}, "GET", "/calls/123", None),
    ("send_sms", {"from_number": "+33744332211", "to_number": "+33611223344", "content": "Hello World!"}, "POST", "/push/sms", {"from_number": "+33744332211", "to_number": "+33611223344", "content": "Hello World!"}),
    ("start_callback", {"to_number": 33611223344, "device": "ALL"}, "POST", "/callback", {"to_number": 33611223344, "device": "ALL", "timeout": 20, "clir": False}),
    ("delete_contact", {"contactId": 123}, "DELETE", "/contacts/123", None),
])
async def test_requests(monkeypatch, operation, config, method, path, body):
    request = AsyncMock(return_value={"result": "accepted"})
    monkeypatch.setattr(RingoverNode, "_request", request)
    model = RingoverNodeConfig.model_validate({"config": {"operation": operation, **config}, "credentials": CREDENTIAL})
    node = RingoverNode(node_id="test", node_type="automation-ringover", node_data={}, config=model)
    result = await node.execute({})
    assert result["data"] == {"result": "accepted"}
    assert request.call_args.args[1:] == (method, path)
    assert request.call_args.kwargs["body"] == body

@pytest.mark.asyncio
async def test_webhook_lifecycle(monkeypatch):
    request = AsyncMock(return_value={"uuid": "bc5c5a41-44c5-5b7c-a521-45bf56d82cbe", "signing_key": "secret"})
    monkeypatch.setattr(RingoverNode, "_request", request)
    state = await RingoverNode._register_external_webhook(webhook_url="https://example.com/hook", credential=CREDENTIAL, config={"event_type": "call.missed"}, node_id="n")
    assert state["signing_secret"] == "secret"
    assert request.call_args.kwargs["body"] == {"target_url": "https://example.com/hook", "events": ["call.missed"]}
    await RingoverNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="n")
    assert request.call_args.args[1:] == ("DELETE", "/webhooks/" + state["external_webhook_id"])

@pytest.mark.parametrize("event", ["hangup", "missed", "ringing", "answered", "voicemail"])
def test_documented_call_events(event):
    payload = json.loads((FIXTURES / ("call_" + event + ".json")).read_text())
    config = {"signing_secret": "secret", "webhook_url": "https://example.com/hook", "event_type": next(k for k,v in __import__('nodes.ringover_node', fromlist=['CALL_EVENTS']).CALL_EVENTS.items() if v == event)}
    body = json.dumps(payload).encode()
    message = b"POSThttps://example.com/hook" + body + b"1554823493"
    signature = base64.b64encode(hmac.new(b"secret", message, hashlib.sha256).digest()).decode()
    headers = {"X-Ringover-Webhook-Signature-V3": signature, "X-Ringover-Request-Signature-V3-Timestamp": "1554823493"}
    assert RingoverNode.verify_webhook_signature(body, headers, config)
    assert not RingoverNode.verify_webhook_signature(body+b" ", headers, config)
    token = jwt.encode({"url": config["webhook_url"], "payload": payload}, "secret", algorithm="HS512")
    assert RingoverNode.verify_webhook_signature(body, {"X-Ringover-Webhook-Signature": token}, config)
    assert not RingoverNode.verify_webhook_signature(body, {}, config)
    assert RingoverNode.filter_trigger_payload(payload, config)
    output = RingoverNode.resolve_trigger_payload(payload, config)
    event = RingoverNode.resolve_agent_event(output)
    assert str(payload["data"]["call_id"]) in event["text"]
    assert payload["data"]["from_number"] in event["text"]


def test_agent_hook_handles_unrelated_outputs():
    event = RingoverNode.resolve_agent_event({"status": "success", "data": {"event": "other"}})
    assert event is None or isinstance(event["text"], str)
