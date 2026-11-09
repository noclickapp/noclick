"""Verify Syncro's request serialization and published response examples offline.

The fixture contains unchanged response examples from Syncro's pinned v1
OpenAPI contract at https://api-docs.syncromsp.com/swagger.json.
"""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import syncro_node as native
from nodes.core.registry import NodeFactory

RESPONSES = json.loads((Path(__file__).parent / "fixtures/syncro/responses.json").read_text())
TOKEN = "syncro-unit-test-token"
CREDENTIAL = {"credential_type": "syncro_api_token", "subdomain": "your-subdomain", "api_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **fields):
    return NodeFactory.create_node(node_id="syncro-test", node_type="automation-syncro",
        node_data={"config": {"operation": operation, **fields}, "credentials": CREDENTIAL})


def transport(monkeypatch, payload, status=200):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CONFIGS = {
    "get_current_user": {}, "list_customers": {"query": "Walkin"},
    "get_customer": {"customer_id": 1},
    "create_customer": {"firstname": "Walkin", "email": "walkin@somedomain.com"},
    "update_customer": {"customer_id": 1, "business_name": "Real Business"},
    "list_contacts": {"customer_id": 1}, "get_contact": {"contact_id": 1},
    "create_contact": {"customer_id": 1, "name": "Boba Fett"},
    "update_contact": {"contact_id": 1, "name": "Boba Fett"},
    "list_tickets": {"status": "New", "customer_id": 1}, "get_ticket": {"ticket_id": 5},
    "create_ticket": {"customer_id": 1, "subject": "New ticket"},
    "update_ticket": {"ticket_id": 5, "status": "Resolved"},
    "add_ticket_comment": {"ticket_id": 1, "body": "Updated ticket"},
    "list_invoices": {"paid": False}, "get_invoice": {"invoice_id": 4},
    "list_assets": {"query": "New Name"}, "get_asset": {"asset_id": 7},
    "create_asset": {"name": "New Name", "asset_type_name": "Dodrio", "customer_id": 1},
    "update_asset": {"asset_id": 7, "name": "New Name", "properties": {"OS": 4}},
    "list_rmm_alerts": {"status": "active"}, "get_rmm_alert": {"alert_id": 1},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_published_responses_and_exact_single_request(monkeypatch, operation):
    method, path, id_field, envelope = native.OPERATIONS[operation]
    payload = RESPONSES[method + " " + path]
    config = CONFIGS[operation]
    requests = transport(monkeypatch, payload)
    result = await node(operation, **config).execute({})
    assert result["status"] == "success", result
    assert result["data"] == (payload[envelope] if envelope else payload)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    expected_path = path.replace("{id}", str(config[id_field])) if id_field else path
    assert str(req.url).startswith("https://your-subdomain.syncromsp.com/api/v1" + expected_path)
    assert req.url.path == "/api/v1" + expected_path
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert "api_key" not in req.url.params and TOKEN not in str(req.url)
    expected = {key: value for key, value in config.items() if key != id_field}
    if operation.startswith("list_"):
        expected = {"page": 1, **expected}
    if operation == "add_ticket_comment":
        expected = {"hidden": True, "do_not_email": True, **expected}
    if method == "GET":
        assert dict(req.url.params) == {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in expected.items()}
        assert req.content == b""
    else:
        assert json.loads(req.content) == expected
        assert req.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_pagination_uses_provider_meta_and_keeps_filters(monkeypatch):
    payload = copy.deepcopy(RESPONSES["GET /customers"])
    payload["meta"].update(page=2, total_pages=3)
    requests = transport(monkeypatch, payload)
    result = await node("list_customers", page=2, query="Walkin + Customer").execute({})
    assert result["next_page"] == 3 and result["pagination_known"] is True
    assert dict(requests[0].url.params) == {"page": "2", "query": "Walkin + Customer"}
    assert len(requests) == 1
    payload["meta"]["page"] = 1
    result = await node("list_customers", page=2).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_assets_without_documented_meta_do_not_claim_complete(monkeypatch):
    transport(monkeypatch, RESPONSES["GET /customer_assets"])
    result = await node("list_assets").execute({})
    assert result["status"] == "success"
    assert result["pagination_known"] is False and result["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"error": "Not authorized"}), (422, {"success": False, "message": ["Invalid name"]}), (200, {"error": "Rejected"}), (200, {}), (200, {"customer": {"id": 2}})])
async def test_provider_errors_and_wrong_record_fail(monkeypatch, status, payload):
    transport(monkeypatch, payload, status)
    result = await node("get_customer", customer_id=1).execute({})
    assert result["status"] == "error" and "data" not in result
    if "error" in payload:
        assert result["error"] == payload["error"]


@pytest.mark.asyncio
async def test_failed_write_redacts_token_and_never_retries(monkeypatch):
    requests = transport(monkeypatch, {"error": "Rejected " + TOKEN}, 503)
    result = await node("create_customer", firstname="Walkin").execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown"
    assert TOKEN not in str(result) and len(requests) == 1
    transport(monkeypatch, {"customer": None})
    result = await node("create_customer", firstname="Walkin").execute({})
    assert result["write_outcome"] == "unknown"


@pytest.mark.asyncio
async def test_picker_uses_native_list_and_provider_pagination(monkeypatch):
    payload = copy.deepcopy(RESPONSES["GET /customers"])
    payload["meta"].update(total_pages=2)
    requests = transport(monkeypatch, payload)
    out = await native.SyncroNode.load_field_options("customer_id", CREDENTIAL)
    assert out == {"options": [{"value": "1", "label": "Walkin Customer"}], "next_page_token": "2"}
    assert len(requests) == 1 and requests[0].url.path == "/api/v1/customers"


@pytest.mark.parametrize("subdomain", ["https://example.syncromsp.com", "example.syncromsp.com", "a/b", "a@evil.com", "a:443", "../evil", "", "a\nother"])
def test_credentials_restrict_destination(subdomain):
    with pytest.raises(ValidationError):
        native.SyncroAPITokenCredential(subdomain=subdomain, api_token=TOKEN)


def test_manual_connect_default_and_normalization():
    value = native.SyncroAPITokenCredential(subdomain=" ACCOUNT ", api_token=" " + TOKEN + " ")
    assert value.credential_type == "syncro_api_token" and value.subdomain == "account" and value.api_token == TOKEN
    assert native.SyncroNode.connection_evidence.identity_operation == "get_current_user"


@pytest.mark.parametrize("operation,fields", [("update_customer", {"customer_id": 1}), ("update_ticket", {"ticket_id": 1}), ("get_ticket", {"ticket_id": "1/other"}), ("list_customers", {"page": 0}), ("update_contact", {"contact_id": 1}), ("create_asset", {"name": "Host"}), ("list_tickets", {"since_updated_at": "2026-11-09T12:00:00"})])
def test_invalid_configuration_fails_before_io(operation, fields):
    with pytest.raises(ValueError):
        node(operation, **fields)


@pytest.mark.asyncio
async def test_dates_and_times_are_serialized_as_documented(monkeypatch):
    requests = transport(monkeypatch, RESPONSES["PUT /tickets/{id}"])
    result = await node("update_ticket", ticket_id=5, due_date="2026-11-10", start_at="2026-11-09T12:00:00Z").execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == {"due_date": "2026-11-10", "start_at": "2026-11-09T12:00:00Z"}
