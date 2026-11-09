"""WhatsAble wire tests using provider examples from its published OpenAPI.

Checks real factory parsing, every endpoint, bearer placement, pagination,
explicit note clearing, failed-send acknowledgements and credential redaction.
"""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import whatsable_ca185063_node as wa
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "whatsable_ca185063_api_key", "api_key": "nfy_live_fixture_secret"}
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/whatsable-ca185063/responses.json").read_text())["examples"]
CASES = [
    ("get_me", {}, "GET", "/v1/me", None, {}, "Me"),
    ("list_numbers", {"cursor": "opaque+/="}, "GET", "/v1/numbers", None, {"limit": "25", "cursor": "opaque+/="}, "Number"),
    ("get_number", {"number_id": "n1"}, "GET", "/v1/numbers/n1", None, {}, "Number"),
    ("list_templates", {"number_id": "n1", "status": "approved", "language": "en_US", "name": "order_shipped"}, "GET", "/v1/templates", None, {"limit": "25", "number_id": "n1", "status": "approved", "language": "en_US", "name": "order_shipped"}, "Template"),
    ("get_template", {"template_id": "t1"}, "GET", "/v1/templates/t1", None, {}, "Template"),
    ("send_message", {"to": "+5491155550000", "text": {"body": "Hi Ana"}, "from_number": "n1", "idempotency_key": "order-1042"}, "POST", "/v1/messages", {"to": "+5491155550000", "from": "n1", "type": "text", "text": {"body": "Hi Ana"}, "pause_ai": False}, {}, "Message"),
    ("list_messages", {"direction": "inbound", "query": "invoice", "created_after": "2026-10-20T12:00:00Z"}, "GET", "/v1/messages", None, {"limit": "25", "direction": "inbound", "query": "invoice", "created_after": "2026-10-20T12:00:00Z"}, "Message"),
    ("get_message", {"message_id": "m1"}, "GET", "/v1/messages/m1", None, {}, "Message"),
    ("list_conversations", {"unread": "false", "window_open": "true", "label_id": "l1"}, "GET", "/v1/conversations", None, {"limit": "25", "unread": "false", "window_open": "true", "label_id": "l1"}, "Conversation"),
    ("get_conversation", {"conversation_id": "c1"}, "GET", "/v1/conversations/c1", None, {}, "Conversation"),
    ("get_conversation_timeline", {"conversation_id": "c1", "types": "message,note"}, "GET", "/v1/conversations/c1/timeline", None, {"limit": "25", "types": "message,note"}, "TimelineEntry"),
    ("update_conversation_unread", {"conversation_id": "c1", "unread": False}, "PATCH", "/v1/conversations/c1/unread", {"unread": False}, {}, "Conversation"),
    ("create_conversation_note", {"conversation_id": "c1", "body": "Call back Monday"}, "POST", "/v1/conversations/c1/notes", {"body": "Call back Monday"}, {}, "ConversationNote"),
    ("schedule_message", {"to": "+5491155550000", "type": "template", "template": {"id": "t1", "variables": {"1": "Ana"}}, "send_at": "2027-10-22T09:00:00-03:00", "time_zone": "America/Argentina/Buenos_Aires"}, "POST", "/v1/scheduled-messages", {"to": "+5491155550000", "type": "template", "template": {"id": "t1", "variables": {"1": "Ana"}}, "send_at": "2027-10-22T09:00:00-03:00", "time_zone": "America/Argentina/Buenos_Aires"}, {}, "ScheduledMessage"),
    ("list_scheduled_messages", {"status": "pending"}, "GET", "/v1/scheduled-messages", None, {"limit": "25", "status": "pending"}, "ScheduledMessage"),
    ("get_scheduled_message", {"scheduled_message_id": "s1"}, "GET", "/v1/scheduled-messages/s1", None, {}, "ScheduledMessage"),
    ("cancel_scheduled_message", {"scheduled_message_id": "s1"}, "POST", "/v1/scheduled-messages/s1/cancel", None, {}, "ScheduledMessage"),
    ("list_contacts", {"phone": "+5491155550000"}, "GET", "/v1/contacts", None, {"limit": "25", "phone": "+5491155550000"}, "Contact"),
    ("create_contact", {"phone": "+5491155550000", "name": "Ana Pérez"}, "POST", "/v1/contacts", {"phone": "+5491155550000", "name": "Ana Pérez"}, {}, "Contact"),
    ("get_contact", {"contact_id": "k1"}, "GET", "/v1/contacts/k1", None, {}, "Contact"),
    ("update_contact", {"contact_id": "k1", "note": None}, "PATCH", "/v1/contacts/k1", {"note": None}, {}, "Contact"),
    ("add_contact_label", {"contact_id": "k1", "label": "VIP"}, "POST", "/v1/contacts/k1/labels", {"label": "VIP"}, {}, "Contact"),
    ("remove_contact_label", {"contact_id": "k1", "label_id": "l1"}, "DELETE", "/v1/contacts/k1/labels/l1", None, {}, "Contact"),
    ("list_labels", {}, "GET", "/v1/labels", None, {"limit": "25"}, "Label"),
    ("create_label", {"name": "VIP", "color": "label-2", "number_ids": [], "keywords": ["vip"]}, "POST", "/v1/labels", {"name": "VIP", "color": "label-2", "number_ids": [], "keywords": ["vip"]}, {}, "Label"),
]


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(wa, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, arguments=None):
    return NodeFactory.create_node(node_id="whatsable-test", node_type="automation-whatsable-ca185063",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body,query,example", CASES)
async def test_whatsable_ca185063_wire(transport, operation, arguments, method, path, body, query, example):
    requests, replies = transport
    resource = copy.deepcopy(EXAMPLES[example])
    page = operation.startswith("list_") or operation == "get_conversation_timeline"
    response = {"object": "list", "data": [resource], "has_more": True, "next_cursor": "cursor-two"} if page else resource
    replies.append((201 if operation in {"send_message", "schedule_message", "create_contact", "create_label", "create_conversation_note"} else 200, response))
    result = await node(operation, arguments).execute({})
    assert result["status"] == "success" and result["data"] == response
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.url.host == "api.whatsable.app"
    assert request.method == method and request.url.path == path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
    assert request.headers.get("Idempotency-Key") == arguments.get("idempotency_key")
    assert AUTH["api_key"] not in str(request.url)
    assert AUTH["api_key"] not in json.dumps(result)


@pytest.mark.asyncio
async def test_whatsable_ca185063_failed_send_is_not_delivery(transport):
    requests, replies = transport
    failed = {**EXAMPLES["Message"], "status": "failed", "error": {"code": "number_not_sending", "message": "Number is not sending"}}
    replies.append((201, failed))
    result = await node("send_message", {"to": "+5491155550000", "type": "template", "template": {"id": "t1", "variables": {"1": "Ana"}}}).execute({})
    assert result["data"]["status"] == "failed"
    assert result["data"]["error"] == failed["error"]
    assert result["http_status"] == 201
    assert json.loads(requests[0].content)["template"] == {"id": "t1", "variables": {"1": "Ana"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("code,error_code", [(401, "invalid_api_key"), (403, "insufficient_scope"), (429, "rate_limited"), (500, "internal_error")])
async def test_whatsable_ca185063_provider_errors(transport, code, error_code):
    requests, replies = transport
    replies.append((code, {"error": {"code": error_code, "message": "Provider rejected " + AUTH["api_key"]}}))
    result = await node("get_me").execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert result["error_code"] == error_code
    assert result["error"] == "Provider rejected [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"object": "list", "data": None, "next_cursor": None}])
async def test_whatsable_ca185063_rejects_malformed_page(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    assert (await node("list_contacts").execute({}))["status"] == "error"


@pytest.mark.parametrize("operation,arguments", [
    ("get_contact", {"contact_id": "../other"}),
    ("list_contacts", {"limit": 101}),
    ("create_contact", {}),
    ("create_contact", {"phone": "+15551234567", "wa_user_id": "US.12345678"}),
    ("update_contact", {"contact_id": "k1"}),
    ("send_message", {"to": "+15551234567"}),
    ("send_message", {"to": "+15551234567", "type": "template", "template": {"id": "t1"}, "reply_to_message_id": "m1"}),
    ("send_message", {"to": "+15551234567", "text": {"body": "Hi"}, "idempotency_key": "x\r\ny"}),
    ("schedule_message", {"to": "+15551234567", "text": {"body": "Hi"}, "send_at": "2027-01-01T12:00:00"}),
])
def test_whatsable_ca185063_refuses_invalid_configs(operation, arguments):
    with pytest.raises(ValueError):
        node(operation, arguments)


def test_whatsable_ca185063_manual_credential_and_evidence():
    credential = wa.WhatsAbleAPIKeyCredential(api_key=" nfy_live_fixture_secret ")
    assert credential.credential_type == AUTH["credential_type"]
    assert credential.api_key == AUTH["api_key"]
    assert wa.WhatsAbleNode.connection_evidence.identity_operation == "get_me"
    for key in ["Bearer has-space", "a\r\nb"]:
        with pytest.raises(ValidationError):
            wa.WhatsAbleAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
async def test_whatsable_ca185063_business_scoped_address(transport):
    requests, replies = transport
    replies.append((201, EXAMPLES["Contact"]))
    address = "US." + "1" * 100
    await node("create_contact", {"wa_user_id": address}).execute({})
    assert json.loads(requests[0].content) == {"wa_user_id": address}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example", [("send_message", "Message"), ("schedule_message", "ScheduledMessage")])
async def test_whatsable_ca185063_documented_template_contract(transport, operation, example):
    # The provider's broken discriminator references a nonexistent named schema.
    # Independently judge the emitted body against its original inline branch.
    from jsonschema import Draft202012Validator, FormatChecker
    fixture = json.loads((Path(__file__).parent / "fixtures/whatsable-ca185063/message-contract.json").read_text())
    config = copy.deepcopy(fixture["examples"][operation])
    config["from_number"] = config.pop("from")
    requests, replies = transport
    replies.append((201, EXAMPLES[example]))
    result = await node(operation, config).execute({})
    assert result["status"] == "success"
    body = json.loads(requests[0].content)
    Draft202012Validator(fixture["branches"][operation], format_checker=FormatChecker()).validate(body)
    assert body == {**fixture["examples"][operation], **({"pause_ai": False} if operation == "send_message" else {})}
