"""Wire behavior and signed deliveries from OpenWA's published examples."""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import openwa_node as ow
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "openwa_api_key", "server_url": "https://openwa.example.com", "api_key": "fixture-openwa-key"}
SESSION = "8f3c2b1a-9d4e-4c7a-8b2f-1e6d5a4c3b2a"
CHAT = "12025550101@c.us"
MESSAGE = "true_12025550101@c.us_3EB0ABCD"
EVENT = json.loads((Path(__file__).parent / "fixtures/openwa/message_received.json").read_text())["body"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.headers["X-API-Key"] == AUTH["api_key"]
        assert request.url.host == "openwa.example.com"
        code, body = responses.pop(0)
        return httpx.Response(code, json=body) if body is not None else httpx.Response(code)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(ow, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(operation, **arguments):
    return await run_node_operation(node_type="automation-openwa", operation=operation, arguments=arguments,
        credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,tail,body", [
    ("send_text", "send-text", {"chatId": CHAT, "text": "Hello from OpenWA!", "linkPreview": False}),
    ("reply", "reply", {"chatId": CHAT, "quotedMessageId": MESSAGE, "text": "Replying to you"}),
    ("send_image", "send-image", {"chatId": CHAT, "url": "https://example.com/image.jpg", "caption": "Check out this image!"}),
    ("send_document", "send-document", {"chatId": CHAT, "url": "https://example.com/document.pdf", "filename": "document.pdf"}),
    ("react", "react", {"chatId": CHAT, "messageId": MESSAGE, "emoji": ""}),
    ("forward_message", "forward", {"fromChatId": CHAT, "toChatId": "12025550107@c.us", "messageId": MESSAGE}),
    ("edit_message", "edit", {"chatId": CHAT, "messageId": MESSAGE, "body": "Corrected text"}),
    ("delete_message", "delete", {"chatId": CHAT, "messageId": MESSAGE, "forEveryone": False}),
    ("send_template", "send-template", {"chatId": CHAT, "templateId": "b1c2d3e4-f5a6-7890-bcde-f01234567890", "vars": {"customer": "Alice", "orderId": "1234"}}),
])
async def test_message_writes(wire, operation, tail, body):
    requests, responses = wire
    responses.append((201, {"id": MESSAGE, "status": "sent"}))
    result = await run(operation, sessionId=SESSION, **body)
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == f"/api/sessions/{SESSION}/messages/{tail}"
    assert json.loads(request.content) == body
    assert result["data"]["id"] == MESSAGE


@pytest.mark.asyncio
async def test_list_filters_and_result_are_preserved(wire):
    requests, responses = wire
    payload = {"messages": [], "total": 132, "unknownTimestampTotal": 2}
    responses.append((200, payload))
    result = await run("list_messages", sessionId=SESSION, chatId=CHAT, sender=CHAT,
        limit=50, after="cursor-id", inlineMedia=False, since=1700000000000,
        until=1800000000000, direction="incoming", orderBy="timestamp")
    assert result["data"] == payload
    assert requests[0].url.params["from"] == CHAT
    assert requests[0].url.params["inlineMedia"] == "false"
    assert requests[0].url.params["since"] == "1700000000000.0"
    assert "sender" not in requests[0].url.params


@pytest.mark.asyncio
async def test_session_picker_and_paging(wire):
    requests, responses = wire
    responses.append((200, [{"id": SESSION, "name": "Sales"}]))
    result = await ow.OpenWANode.load_field_options("sessionId", AUTH, page_token="100", search="sales")
    assert result == {"options": [{"value": SESSION, "label": "Sales"}], "next_page_token": None}
    assert dict(requests[0].url.params) == {"limit": "100", "offset": "100"}


@pytest.mark.asyncio
async def test_signed_trigger_registration_delivery_and_removal(wire):
    requests, responses = wire
    responses.extend([(201, {"id": "webhook-id"}), (204, None)])
    state = await ow.OpenWANode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/event", credential=AUTH,
        config={"operation": "on_message", "sessionId": SESSION}, node_id="node")
    body = json.loads(requests[0].content)
    assert body["events"] == ["message.received"] and len(body["secret"]) == 64
    assert state["signing_secret"] == body["secret"]
    config = {"operation": "on_message", "sessionId": SESSION, **state}
    raw = json.dumps(EVENT).encode()
    signature = "sha256=" + hmac.new(body["secret"].encode(), raw, hashlib.sha256).hexdigest()
    assert ow.OpenWANode.verify_webhook_signature(raw, {"X-OpenWA-Signature": signature}, config)
    assert not ow.OpenWANode.verify_webhook_signature(raw + b" ", {"X-OpenWA-Signature": signature}, config)
    assert not ow.OpenWANode.verify_webhook_signature(raw, {}, config)
    assert ow.OpenWANode.filter_trigger_payload(EVENT, config)
    assert not ow.OpenWANode.filter_trigger_payload({**EVENT, "sessionId": "other"}, config)
    assert not ow.OpenWANode.filter_trigger_payload({**EVENT, "event": "message.sent"}, config)
    output = ow.OpenWANode.resolve_trigger_payload(EVENT, config)
    turn = ow.OpenWANode.resolve_agent_event(output)
    assert "Hello!" in turn["text"] and EVENT["data"]["id"] in turn["text"]
    assert turn["conversation_key"] == f"openwa:{SESSION}:{CHAT}"
    await ow.OpenWANode._unregister_external_webhook(credential=AUTH, config={**config, "sessionId": "new-session"}, node_id="node")
    assert requests[1].method == "DELETE"
    assert requests[1].url.path == f"/api/sessions/{SESSION}/webhooks/webhook-id"


@pytest.mark.asyncio
async def test_manual_trigger_does_not_fabricate_an_event():
    config = ow.OpenWANodeConfig.model_validate({"config": {"operation": "on_message", "sessionId": SESSION}, "credentials": AUTH})
    node = ow.OpenWANode(node_id="node", node_type="automation-openwa", node_data={}, config=config, sio=Mock())
    result = await node.execute({"private_other_node_output": "must not escape"})
    assert result["status"] == "no_event" and "private_other_node_output" not in str(result)


@pytest.mark.asyncio
async def test_no_redirect_or_retry_after_rejected_write(wire):
    requests, responses = wire
    responses.append((403, {"message": "API key not authorized for this session"}))
    with pytest.raises(ValueError, match="API key not authorized for this session"):
        await run("send_text", sessionId=SESSION, chatId=CHAT, text="hi")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_private_destination_is_refused_before_sending(wire, monkeypatch):
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock(side_effect=ssrf.SSRFError("Private destination refused")))
    with pytest.raises(ssrf.SSRFError):
        await ow.OpenWANode._request(AUTH, "GET", "/api/sessions")
    assert not wire[0]


@pytest.mark.parametrize("change", [{"server_url": "http://openwa.example.com"}, {"server_url": "https://user:pass@openwa.example.com"}, {"api_key": "line\nbreak"}])
def test_manual_credential_validation(change):
    with pytest.raises(ValidationError):
        ow.OpenWAAPIKeyCredential.model_validate({**AUTH, **change})


def test_manual_credential_and_fixed_contract():
    value = ow.OpenWAAPIKeyCredential.model_validate({"server_url": "openwa.example.com/api/docs", "api_key": AUTH["api_key"]})
    assert value.credential_type == "openwa_api_key" and value.server_url == AUTH["server_url"]
    assert len(ow.OPERATIONS) == 22
    assert len({op.contract_id for op in ow.OPERATIONS.values()}) == 22
