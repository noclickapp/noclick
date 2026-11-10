"""Wire-level tests plus replay of provider-published webhook examples."""
import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.funnelchat_node import (
    BASE_URL, CONFIG_MODELS, WEBHOOK_EVENTS, FunnelchatAPIKeyCredential,
    FunnelchatNode, FunnelchatNodeConfig,
)

CREDENTIAL = {"credential_type": "funnelchat_api_key", "api_key": "1|fc_live_test_credential"}
EVENTS = json.loads((Path(__file__).parent / "fixtures/funnelchat/events.json").read_text())["events"]


def node(operation, **config):
    result = object.__new__(FunnelchatNode)
    result._config = FunnelchatNodeConfig(config={"operation": operation, **config}, credentials=CREDENTIAL)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,expected", [
    ("create_contact", {"phone": "+5491100000000", "name": "Ana", "custom_fields": [{"id": 12, "value": "1500"}]}, "POST", "/api/v1/contacts", {"phone": "+5491100000000", "name": "Ana", "custom_fields": [{"id": 12, "value": "1500"}]}),
    ("upsert_contact", {"phone": "+5491100000000"}, "POST", "/api/v1/contacts/update-or-create", {"phone": "+5491100000000"}),
    ("update_contact", {"contact": 2001, "email": None, "favorite": False}, "PUT", "/api/v1/contacts/2001", {"email": None, "favorite": False}),
    ("add_contact_tag", {"contactId": 2001, "tag_id": 4001}, "POST", "/api/v1/contacts/add-tags", [{"contactId": 2001, "tag": {"id": 4001}}]),
    ("remove_contact_tag", {"contactId": 2001, "tag_id": 4001}, "POST", "/api/v1/contacts/remove-tags", [{"contactId": 2001, "tag": {"id": 4001}}]),
    ("set_contact_custom_field", {"contactId": 2001, "customFieldId": 12, "value": "1500"}, "POST", "/api/v1/contacts/attach-custom-field", [{"contactId": 2001, "customFieldId": 12, "value": "1500"}]),
    ("remove_contact_custom_field", {"contactId": 2001, "customFieldId": 12}, "POST", "/api/v1/contacts/detach-custom-field", [{"contactId": 2001, "customFieldId": 12}]),
    ("send_message", {"device_id": 4521, "contact_id": 2001, "text": "Hola"}, "POST", "/api/v1/message/send-message", {"device_id": 4521, "contact_id": 2001, "text": "Hola"}),
    ("send_template", {"device": 4521, "template": "welcome/es", "phone": "+5491100000000", "template_variables": {"body": ["Ana"]}}, "POST", "/api/v1/devices/4521/templates/welcome%2Fes/send-template", {"phone": "+5491100000000", "template_variables": {"body": ["Ana"]}}),
])
async def test_mutation_wire_shapes(monkeypatch, operation, config, method, path, expected):
    request = AsyncMock(return_value={"message": {"status": "queued"}})
    monkeypatch.setattr(FunnelchatNode, "_request", request)
    result = await node(operation, **config).execute({})
    request.assert_awaited_once_with(CREDENTIAL, method, path, params=None, body=expected)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_cursor_and_false_query_are_preserved(monkeypatch):
    request = AsyncMock(return_value={"data": [], "meta": {"next_cursor": "next"}})
    monkeypatch.setattr(FunnelchatNode, "_request", request)
    result = await node("list_conversations", cursor="opaque", unreadMessages=False, perPage=10).execute({})
    assert request.call_args.kwargs["params"] == {"cursor": "opaque", "unreadMessages": False, "perPage": 10}
    assert result["data"]["meta"]["next_cursor"] == "next"


@pytest.mark.asyncio
async def test_bulk_item_failure_is_not_success(monkeypatch):
    monkeypatch.setattr(FunnelchatNode, "_request", AsyncMock(return_value=[{"status": 403, "message": "No autorizado"}]))
    assert (await node("add_contact_tag", contactId=2001, tag_id=4001).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_http_auth_and_provider_rejection(monkeypatch):
    requests = []
    real_client = httpx.AsyncClient
    def handler(request):
        requests.append(request)
        return httpx.Response(403, json={"error": "permission_denied", "message": "Missing numbers permission"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(ValueError, match="403: Missing numbers permission"):
        await FunnelchatNode._request(CREDENTIAL, "GET", "/api/v1/devices")
    assert requests[0].headers["Authorization"] == "Bearer " + CREDENTIAL["api_key"]
    assert str(requests[0].url) == BASE_URL + "/api/v1/devices"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_no_redirects_or_secret_in_errors(monkeypatch):
    real_client = httpx.AsyncClient
    def handler(request):
        return httpx.Response(302, headers={"Location": "https://other.example"}, json={"message": CREDENTIAL["api_key"]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(ValueError) as error:
        await FunnelchatNode._request(CREDENTIAL, "POST", "/api/v1/contacts", body={"phone": "+5491100000000"})
    assert CREDENTIAL["api_key"] not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", WEBHOOK_EVENTS)
async def test_documented_event_lifecycle(monkeypatch, kind):
    request = AsyncMock(return_value={"id": "00000000-0000-4000-8000-000000000001", "secret": "whsec_example"})
    monkeypatch.setattr(FunnelchatNode, "_request", request)
    config = {"operation": "on_event", "event_type": kind}
    registration = await FunnelchatNode._register_external_webhook(webhook_url="https://hooks.example/funnelchat", credential=CREDENTIAL, config=config, node_id="node1")
    assert request.call_args.kwargs["body"] == {"url": "https://hooks.example/funnelchat", "events": [kind]}
    timestamp = str(int(time.time()))
    body = json.dumps(EVENTS[kind], ensure_ascii=False).encode()
    signature = hmac.new(b"whsec_example", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"X-Funnelchat-Signature": f"t={timestamp},v1={signature}"}
    assert FunnelchatNode.verify_webhook_signature(body, headers, registration)
    assert not FunnelchatNode.verify_webhook_signature(body + b" ", headers, registration)
    assert not FunnelchatNode.verify_webhook_signature(body, headers, {"signing_secret": "wrong"})
    assert FunnelchatNode.filter_trigger_payload(EVENTS[kind], config)
    assert not FunnelchatNode.filter_trigger_payload({"type": "webhook.test"}, config)
    assert FunnelchatNode.should_propagate_output(EVENTS[kind], config)
    assert not FunnelchatNode.should_propagate_output({"type": "webhook.test"}, config)
    event = FunnelchatNode.resolve_agent_event(EVENTS[kind])
    assert kind in event["text"]
    assert event["conversation_key"]
    if kind == "message.received":
        assert "Hola, quiero más información" in event["text"]
        assert "4521" in event["text"] and "2001" in event["text"]
    await FunnelchatNode._unregister_external_webhook(credential=CREDENTIAL, config=registration, node_id="node1")
    assert request.call_args.args[1:] == ("DELETE", "/api/v1/webhooks/00000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("header", ["", "t=0,v1=abc", "t=bad,v1=abc", "t=1,t=2,v1=abc", "t=999999999999999999999999999999999999,v1=abc"])
def test_invalid_and_stale_signatures_fail_closed(header):
    assert not FunnelchatNode.verify_webhook_signature(b"{}", {"x-funnelchat-signature": header}, {"signing_secret": "whsec_example"})


def test_manual_credential_and_input_boundaries():
    assert FunnelchatAPIKeyCredential(api_key=CREDENTIAL["api_key"]).credential_type == "funnelchat_api_key"
    with pytest.raises(ValidationError):
        FunnelchatAPIKeyCredential(api_key="Bearer key")
    for op, config in [("send_message", {"device_id": 1, "text": "hi"}), ("update_contact", {"contact": 1}), ("list_contacts", {"perPage": 101})]:
        with pytest.raises(ValidationError): CONFIG_MODELS[op](**config)


@pytest.mark.asyncio
async def test_manual_trigger_does_not_fabricate_event():
    result = await node("on_event").execute({})
    assert result["status"] == "no_event"
