"""Native factory wire-contract regressions, without a provider account."""
import base64
import json
import httpx
import pytest
from nodes import bulksmscom_node as native
from nodes.core.registry import NodeFactory

CREDS = {"credential_type": "bulksmscom_api_token", "token_id": "synthetic-id", "token_secret": "synthetic-secret"}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="bulksmscom-test", node_type="automation-bulksmscom", node_data={"config": config, "credentials": CREDS})

def transport(monkeypatch, data=None, status=200, empty=False):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, content=b"") if empty else httpx.Response(status, json=data)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests

CASES = [
    ({"operation": "get_profile"}, "GET", "/profile", {"id": "account-1", "username": "owner"}),
    ({"operation": "send_messages", "to": ["+27001234567"], "body": "Hello World!"}, "POST", "/messages", [{"id": "4023457654"}]),
    ({"operation": "list_messages"}, "GET", "/messages", []),
    ({"operation": "get_message", "message_id": "4023457654"}, "GET", "/messages/4023457654", {"id": "4023457654"}),
    ({"operation": "list_related_messages", "message_id": "4023457654"}, "GET", "/messages/4023457654/relatedReceivedMessages", []),
    ({"operation": "list_blocked_numbers"}, "GET", "/blocked-numbers", [{"id": 234, "phoneNumber": "+27001234567"}]),
    ({"operation": "create_blocked_numbers", "phone_numbers": ["+27001234567"]}, "POST", "/blocked-numbers", None),
    ({"operation": "list_webhooks"}, "GET", "/webhooks", []),
    ({"operation": "get_webhook", "webhook_id": "234"}, "GET", "/webhooks/234", {"id": 234}),
    ({"operation": "create_webhook", "name": "My MT Webhook", "url": "https://www.example.com", "trigger_scope": "SENT", "contact_email_address": "tech_team@example.com"}, "POST", "/webhooks", {"id": 234}),
    ({"operation": "update_webhook", "webhook_id": "234", "name": "My MT Webhook", "url": "https://www.example.com", "trigger_scope": "RECEIVED", "active": False}, "POST", "/webhooks/234", {"id": 234}),
    ({"operation": "delete_webhook", "webhook_id": "234"}, "DELETE", "/webhooks/234", None),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,response", CASES)
async def test_each_operation_native_request(monkeypatch, config, method, path, response):
    empty = config["operation"] in {"delete_webhook", "create_blocked_numbers"}
    requests = transport(monkeypatch, response, 201 if config["operation"] == "send_messages" else 200, empty)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (method, "/v1" + path)
    assert request.url.host == "api.bulksms.com"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"synthetic-id:synthetic-secret").decode()
    assert request.headers["Content-Type"] == "application/json"
    if "webhook" in config["operation"] and method == "POST":
        body = json.loads(request.content)
        assert body["triggerScope"] == config["trigger_scope"] and body["url"] == config["url"]
        assert body["active"] is config.get("active", True)
        assert "webhook_id" not in body
        if config.get("contact_email_address") is not None:
            assert body["contactEmailAddress"] == config["contact_email_address"]
        else:
            assert "contactEmailAddress" not in body
    if config["operation"] == "create_blocked_numbers":
        assert json.loads(request.content) == config["phone_numbers"]

@pytest.mark.asyncio
async def test_sms_structured_recipients_options_and_schedule(monkeypatch):
    requests = transport(monkeypatch, [{"id": "4023457654"}], 201)
    await node({"operation": "send_messages", "to": ["+27001234567", "+27002345678"], "body": "Hello World!", "sender_address": "NoClick", "encoding": "UNICODE", "routing_group": "STANDARD", "user_supplied_id": "submission-12765", "long_message_max_parts": 3, "delivery_reports": "ALL", "auto_unicode": False, "deduplication_id": 123, "schedule_date": "2027-01-01T10:00:00+01:00", "schedule_description": "Reminder"}).execute({})
    assert json.loads(requests[0].content) == [{"to": [{"type": "INTERNATIONAL", "address": "+27001234567"}, {"type": "INTERNATIONAL", "address": "+27002345678"}], "body": "Hello World!", "from": {"type": "ALPHANUMERIC", "address": "NoClick"}, "encoding": "UNICODE", "routingGroup": "STANDARD", "userSuppliedId": "submission-12765", "longMessageMaxParts": 3, "deliveryReports": "ALL"}]
    assert dict(requests[0].url.params) == {"auto-unicode": "false", "deduplication-id": "123", "schedule-date": "2027-01-01T10:00:00+01:00", "schedule-description": "Reminder"}

@pytest.mark.asyncio
async def test_filter_encoded_once_and_pagination(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({"operation": "list_messages", "filter": "type=SENT&id<123456", "limit": 50, "sort_order": "ASCENDING"}).execute({})
    assert dict(requests[0].url.params) == {"filter": "type=SENT&id<123456", "limit": "50", "sortOrder": "ASCENDING"}
    await node({"operation": "list_blocked_numbers", "min_id": 235, "limit": 25}).execute({})
    assert dict(requests[1].url.params) == {"min-id": "235", "limit": "25"}

@pytest.mark.asyncio
async def test_provider_rejection_and_redaction(monkeypatch):
    transport(monkeypatch, {"detail": "Rejected synthetic-secret"}, 401)
    assert await node({"operation": "get_profile"}).execute({}) == {"status": "error", "http_status": 401, "error": "Rejected [redacted]"}

@pytest.mark.asyncio
async def test_parser_rejects_wrong_shape(monkeypatch):
    transport(monkeypatch, {"unexpected": True})
    with pytest.raises(ValueError, match="response shape"):
        await node({"operation": "list_messages"}).execute({})

@pytest.mark.asyncio
async def test_profile_must_identify_an_account(monkeypatch):
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="did not identify an account"):
        await node({"operation": "get_profile"}).execute({})

@pytest.mark.parametrize("config", [
    {"operation": "get_message", "message_id": "../profile"},
    {"operation": "send_messages", "to": [], "body": "Hi"},
    {"operation": "send_messages", "to": ["bad"], "body": "Hi"},
    {"operation": "send_messages", "to": ["+27001234567"], "body": "Hi", "schedule_date": "tomorrow"},
    {"operation": "create_blocked_numbers", "phone_numbers": []},
    {"operation": "create_webhook", "name": "Test", "url": "file:///etc/passwd", "trigger_scope": "SENT"},
])
def test_invalid_inputs(config):
    with pytest.raises(ValueError): node(config)

def test_manual_credential_defaults_and_evidence():
    parsed = native.BulkSMSComAPITokenCredential(token_id="synthetic-id", token_secret="synthetic-secret")
    assert parsed.credential_type == "bulksmscom_api_token"
    assert native.BulkSMSComNode.connection_evidence.identity_operation == "get_profile"
    assert native.BulkSMSComNode.connection_evidence.identity_keys == ("username", "id")


def test_pinned_contract_fixtures_and_operation_mapping():
    import hashlib
    from pathlib import Path
    fixtures = Path(__file__).parent / "fixtures" / "bulksmscom"
    manifest = json.loads((fixtures / "manifest.json").read_text())["bulksmscom"]
    for pin in (manifest, manifest["original_contract"]):
        assert hashlib.sha256((fixtures / pin["file"]).read_bytes()).hexdigest() == pin["sha256"]
    contract = json.loads((fixtures / manifest["file"]).read_text())
    operations = set()
    for method, route in native.ROUTES.values():
        path = route.replace("{message_id}", "{id}").replace("{webhook_id}", "{id}")
        assert method.lower() in contract["paths"][path]
        operations.add((method, path))
    assert len(operations) == 12
