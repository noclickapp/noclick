"""HTTP request, credential, and signed-delivery checks for the Vendschat contract."""
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from nodes.vendschat_node import VendschatAPIKeyCredential, VendschatNode, VendschatNodeConfig

FIXTURES = Path(__file__).parent / "fixtures" / "vendschat"
EXAMPLES = json.loads((FIXTURES / "request_examples.json").read_text())["examples"]
DELIVERY = json.loads((FIXTURES / "incoming_whatsapp_text.json").read_text())["body"]
KEY = {"credential_type": "vendschat_api_key", "api_key": "test-vendschat-secret"}


def node(operation, **values):
    config = VendschatNodeConfig.model_validate({"config": {"operation": operation, **values}, "credentials": KEY})
    return VendschatNode(node_id="test", node_type="automation-vendschat", node_data={}, config=config)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,method,path,body", [
    ("get_workspace", {}, "GET", "/integrations/me", None),
    ("list_channels", {}, "GET", "/integrations/messages/channels", None),
    ("list_templates", {"channel_id": 15}, "GET", "/integrations/messages/templates?channel_id=15", None),
    ("get_template", {"channel_id": 15, "id": 88}, "GET", "/integrations/messages/templates/88?channel_id=15", None),
    ("send_message", EXAMPLES["sendIntegrationMessage"], "POST", "/integrations/messages/send", EXAMPLES["sendIntegrationMessage"]),
    ("lookup_contact", EXAMPLES["lookupIntegrationContact"], "POST", "/integrations/contacts/lookup", EXAMPLES["lookupIntegrationContact"]),
    ("create_contact", EXAMPLES["createIntegrationContact"], "POST", "/integrations/contacts", EXAMPLES["createIntegrationContact"]),
    ("update_contact", {"identifier_type": "contact_id", "identifier_value": "1001", "name": "Alex", "note": None}, "PATCH", "/integrations/contacts", {"identifier_type": "contact_id", "identifier_value": "1001", "name": "Alex", "note": None}),
    ("delete_contact", EXAMPLES["lookupIntegrationContact"], "DELETE", "/integrations/contacts", EXAMPLES["lookupIntegrationContact"]),
    ("set_contact_note", {**EXAMPLES["lookupIntegrationContact"], "note": None}, "PUT", "/integrations/contacts/note", {**EXAMPLES["lookupIntegrationContact"], "note": None}),
    ("add_contact_labels", EXAMPLES["addIntegrationContactLabels"], "POST", "/integrations/contacts/labels/add", EXAMPLES["addIntegrationContactLabels"]),
    ("remove_contact_labels", EXAMPLES["addIntegrationContactLabels"], "POST", "/integrations/contacts/labels/remove", EXAMPLES["addIntegrationContactLabels"]),
    ("list_labels", {}, "GET", "/integrations/labels", None),
    ("list_webhook_events", {}, "GET", "/integrations/webhooks/events", None),
])
async def test_request_matches_contract(operation, values, method, path, body):
    response = {"success": True}
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://api.vendschat.com/v1" + path).respond(200, json=response)
        result = await node(operation, **values).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-vendschat-secret"
    assert (json.loads(request.content) if request.content else None) == body
    assert result["data"] == response
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_connection_picker_uses_documented_envelope():
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.vendschat.com/v1/integrations/messages/channels").respond(200, json={"channels": [{"id": 15, "display_name": "BloomBox WhatsApp", "channel_type": "whatsapp"}]})
        result = await VendschatNode.load_field_options("channel_id", KEY)
    assert result == {"options": [{"value": 15, "label": "BloomBox WhatsApp"}], "next_page_token": None}


@pytest.mark.asyncio
async def test_template_picker_passes_channel():
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.vendschat.com/v1/integrations/messages/templates?channel_id=15").respond(200, json={"templates": [{"id": 88, "name": "order_update"}]})
        result = await VendschatNode.load_field_options("template_id", KEY, context={"channel_id": 15})
    assert result["options"][0] == {"value": 88, "label": "order_update"}


@pytest.mark.asyncio
async def test_rejection_preserves_provider_message():
    with respx.mock:
        respx.get("https://api.vendschat.com/v1/integrations/me").respond(401, json={"success": False, "error": {"code": "unauthorized", "message": "Invalid API key"}})
        with pytest.raises(ValueError, match="Invalid API key"):
            await node("get_workspace").execute({})


@pytest.mark.asyncio
async def test_register_unregister_signed_trigger():
    with respx.mock(assert_all_called=True) as router:
        create = router.post("https://api.vendschat.com/v1/integrations/webhooks/subscribe").respond(201, json={"id": "23", "signing_secret": "whsec_test"})
        delete = router.delete("https://api.vendschat.com/v1/integrations/webhooks/23").respond(200, json={"success": True, "id": "23"})
        config = await VendschatNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/test", credential=KEY, config={}, node_id="test")
        await VendschatNode._unregister_external_webhook(credential=KEY, config=config, node_id="test")
    assert config == {"external_webhook_id": "23", "signing_secret": "whsec_test"}
    assert json.loads(create.calls[0].request.content)["events"] == ["incoming.whatsapp.messages.text"]
    assert delete.call_count == 1


def sign(body, timestamp, secret="whsec_test"):
    return {"X-VendsChat-Timestamp": timestamp, "X-VendsChat-Signature": hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()}


def test_signature_raw_bytes_tampering_staleness_and_missing_secret():
    body = json.dumps(DELIVERY).encode()
    timestamp = str(int(time.time()))
    headers = sign(body, timestamp)
    config = {"signing_secret": "whsec_test"}
    assert VendschatNode.verify_webhook_signature(body, headers, config)
    assert not VendschatNode.verify_webhook_signature(body + b" ", headers, config)
    assert not VendschatNode.verify_webhook_signature(body, headers, {})
    assert not VendschatNode.verify_webhook_signature(body, sign(body, str(int(time.time()) - 600)), config)
    assert not VendschatNode.verify_webhook_signature(body, {}, config)


def test_documented_event_through_filter_payload_and_agent_turn():
    assert VendschatNode.filter_trigger_payload(DELIVERY, {})
    assert not VendschatNode.filter_trigger_payload({"type": "outgoing.whatsapp.status.read"}, {})
    output = VendschatNode.resolve_trigger_payload(DELIVERY, {})
    event = VendschatNode.resolve_agent_event(output)
    assert "workspace 123" in event["text"]
    assert DELIVERY["id"] in event["text"]
    assert "lookup_contact" in event["text"]


def test_manual_credentials_and_message_conditionals():
    assert VendschatAPIKeyCredential(api_key="key").credential_type == "vendschat_api_key"
    with pytest.raises(ValueError, match="channel and message type"):
        node("send_message", identifier_type="contact_id", identifier_value="1001", channel_mode="specific")
    with pytest.raises(ValueError, match="both|email"):
        node("create_contact", phone_number="+15551234567")
