"""Mateo request, connect and trigger regressions against the published contract.

HTTP tests use a local transport; event fixtures are copied verbatim from Mateo's docs.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import mateo_node as native
from nodes.core.registry import NodeFactory

ID = "3c90c3cc-0d44-4b50-8888-8dd25736052a"
KEY = "mateo-test-secret-42"
CREDS = {"credential_type": "mateo_api_key", "api_key": KEY}
EVENTS = json.loads((Path(__file__).parent / "fixtures/mateo/events.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    instance = NodeFactory.create_node(node_id="mateo-test", node_type="automation-mateo", node_data={"config": config, "credentials": CREDS})
    instance.emit = AsyncMock()
    return instance

def transport(monkeypatch, *, status=200, body=None):
    requests = []
    client = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status) if status == 204 else httpx.Response(status, json=body)
    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    return requests

CASES = [
    ("list_contacts", {}, "GET", "/contact"),
    ("create_contact", {"full_name": "Max Mustermann"}, "POST", "/contact"),
    ("update_contact", {"id": ID, "email": "person@example.test"}, "PATCH", "/contact"),
    ("delete_contact", {"id": ID}, "DELETE", "/contact"),
    ("list_contact_lists", {}, "GET", "/contact_list"),
    ("create_contact_list", {"name": "Customers"}, "POST", "/contact_list"),
    ("update_contact_list", {"id": ID, "name": "Clients"}, "PATCH", "/contact_list"),
    ("delete_contact_list", {"id": ID}, "DELETE", "/contact_list"),
    ("list_contact_list_contacts", {"contact_list_id": ID}, "GET", "/contact_list_contact"),
    ("add_contact_to_list", {"contact_id": ID, "contact_list_id": ID}, "POST", "/contact_list_contact"),
    ("remove_contact_from_list", {"contact_id": ID, "contact_list_id": ID}, "DELETE", "/contact_list_contact"),
    ("list_contact_notes", {"contact_id": ID}, "GET", "/contact_note"),
    ("create_contact_note", {"contact_id": ID, "text": "Follow up"}, "POST", "/contact_note"),
    ("update_contact_note", {"id": ID, "text": "Done"}, "PATCH", "/contact_note"),
    ("delete_contact_note", {"id": ID}, "DELETE", "/contact_note"),
    ("list_deals", {}, "GET", "/deal"),
    ("create_deal", {"contact_id": ID, "name": "Renewal", "type_key": "sales", "status_key": "open"}, "POST", "/deal"),
    ("update_deal", {"id": ID, "status_key": "won"}, "PATCH", "/deal"),
    ("list_channels", {}, "GET", "/channel"),
    ("list_messages", {}, "GET", "/message"),
    ("send_message", {"channel_id": ID, "contact_id": ID, "text": "Hello"}, "POST", "/send_message"),
    ("list_conversations", {}, "GET", "/conversation"),
    ("update_conversation", {"id": ID, "status": "closed"}, "PATCH", "/conversation"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path", CASES)
async def test_mateo_one_contract_operation_per_action(monkeypatch, operation, config, method, path):
    requests = transport(monkeypatch, body=[] if method == "GET" else {"id": ID})
    output = await node({"operation": operation, **config}).execute({})
    assert output["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1" + path
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert request.url.host == "integration.getmateo.com"
    if method in {"PATCH", "DELETE"}:
        for field in native.OPERATIONS[operation].filters:
            assert request.url.params[field] == "eq." + config[field]
    if operation == "send_message":
        assert json.loads(request.content) == {"from": ID, "to": [{"contact_id": ID}], "text": "Hello"}
    elif method in {"POST", "PATCH"}:
        body = json.loads(request.content)
        for field, value in config.items():
            if field not in native.OPERATIONS[operation].filters:
                assert body[field] == value
        assert "id" not in body
    elif method == "DELETE":
        assert not request.content

@pytest.mark.asyncio
async def test_mateo_pagination_and_exact_filters(monkeypatch):
    requests = transport(monkeypatch, body=[{"id": ID}])
    output = await node({"operation": "list_contacts", "email": "me+one@example.test", "limit": 1, "offset": 4}).execute({})
    assert dict(requests[0].url.params) == {"email": "eq.me+one@example.test", "limit": "1", "offset": "4"}
    assert output["next_offset"] == 5

@pytest.mark.asyncio
async def test_mateo_empty_page(monkeypatch):
    transport(monkeypatch, body=[])
    assert (await node({"operation": "list_contacts"}).execute({}))["next_offset"] is None

@pytest.mark.asyncio
async def test_mateo_no_content_write_acknowledgement(monkeypatch):
    transport(monkeypatch, status=204)
    assert (await node({"operation": "delete_contact", "id": ID}).execute({}))["data"] is None

@pytest.mark.asyncio
async def test_mateo_error_keeps_provider_message_redacts_key(monkeypatch):
    transport(monkeypatch, status=403, body={"message": "Invalid API key " + KEY})
    with pytest.raises(ValueError, match=r"Mateo API 403: Invalid API key \[redacted\]"):
        await node({"operation": "list_contacts"}).execute({})

@pytest.mark.asyncio
async def test_mateo_unexpected_list_shape_is_not_connection_success(monkeypatch):
    transport(monkeypatch, body={"error": "denied"})
    with pytest.raises(ValueError, match="unexpected list response"):
        await node({"operation": "list_contacts"}).execute({})

@pytest.mark.parametrize("operation", ["update_contact", "delete_contact", "update_deal", "delete_contact_list"])
def test_mateo_write_requires_exact_resource(operation):
    for config in [{"operation": operation}, {"operation": operation, "id": "not.eq.all"}]:
        with pytest.raises(ValidationError):
            native.MateoNodeConfig.model_validate({"config": config, "credentials": CREDS})

@pytest.mark.asyncio
async def test_mateo_empty_update_never_reaches_api(monkeypatch):
    requests = transport(monkeypatch)
    with pytest.raises(ValueError, match="Provide a contact field"):
        await node({"operation": "update_contact", "id": ID}).execute({})
    assert requests == []

def test_mateo_hand_connect_defaults_type_and_validates_key():
    assert native.MateoAPIKeyCredential(api_key=KEY).credential_type == "mateo_api_key"
    assert native.MateoAPIKeyCredential(api_key=" " + KEY + " ").api_key == KEY
    for value in ["", "Bearer " + KEY, "https://example.test", "<token>"]:
        with pytest.raises(ValidationError):
            native.MateoAPIKeyCredential(api_key=value)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event", list(native.TRIGGERS.items()))
async def test_mateo_documented_webhook_lifecycle_and_agent_event(monkeypatch, operation, event):
    requests = transport(monkeypatch, status=204)
    config = {"operation": operation}
    state = await native.MateoNode._register_external_webhook(webhook_url="https://webhook.example.test/mateo", credential=CREDS, config=config, node_id="test")
    registration = json.loads(requests[0].content)
    assert registration["event"] == event and registration["method"] == "POST"
    assert registration["source"] == "authenticated" and registration["active"] is True
    assert registration["id"] == state["external_webhook_id"]
    assert registration["target_url"] == "https://webhook.example.test/mateo"
    payload = EVENTS[event]["body"]
    assert native.MateoNode.verify_webhook_signature(json.dumps(payload).encode(), {}, config)
    assert native.MateoNode.filter_trigger_payload(payload, config)
    agent = native.MateoNode.resolve_agent_event(native.MateoNode.resolve_trigger_payload(payload, config))
    contact = payload.get("contact_id") or payload["id"]
    assert contact in agent["text"] and agent["conversation_key"] == contact and "To act:" in agent["text"]
    await native.MateoNode._unregister_external_webhook(credential=CREDS, config={**config, **state}, node_id="test")
    assert requests[-1].method == "DELETE" and requests[-1].url.params["id"] == "eq." + state["external_webhook_id"]

@pytest.mark.asyncio
async def test_mateo_manual_trigger_run_produces_no_event():
    assert (await node({"operation": "on_contact_created"}).execute({}))["status"] == "no_event"
