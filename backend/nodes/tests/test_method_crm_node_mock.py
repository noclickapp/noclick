"""Exercise Method CRM through discovery with mocked HTTP and publisher examples.

The tests pin each operation's single request and cover scalar, empty and
dynamic-record responses, without signing in or using a live API key.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import method_crm_node as native
from nodes.core.registry import NodeFactory

KEY = "method-fixture-secret-123"
FILE = "2a5e1cbc-c9c7-4d72-b554-026e8467cd7f"
DOCS = json.loads((Path(__file__).parent / "fixtures/method-crm/documented_responses.json").read_text())["responses"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="method-fixture", node_type="automation-method-crm",
        node_data={"config": config, "credentials": credentials or {"credential_type": "method_crm_api_key", "api_key": KEY}})


def transport(monkeypatch, status=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_tables"}, "GET", "/tables", 200, DOCS["GET /api/v1/tables"]),
    ({"operation": "get_table_fields", "table": "Invoice"}, "GET", "/tables/Invoice/fields", 200, DOCS["GET /api/v1/tables/{table}/fields"]),
    ({"operation": "query_records", "table": "Contacts", "filter": "FirstName eq 'Amy'", "select": "RecordID,Email", "top": 2, "skip": 0}, "GET", "/tables/Contacts", 200, DOCS["GET /api/v1/tables/{table}"]),
    ({"operation": "get_record", "table": "Contacts", "record_id": 5, "select": "RecordID,Email", "expand": "Entity"}, "GET", "/tables/Contacts/5", 200, DOCS["GET /api/v1/tables/{table}/{recordId}"]),
    ({"operation": "create_record", "table": "Contacts", "record_json": '{"FirstName":"David","Email":"david@landscaping.com"}'}, "POST", "/tables/Contacts", 201, 5),
    ({"operation": "update_record", "table": "Contacts", "record_id": 5, "record_json": '{"IsActive":false}'}, "PATCH", "/tables/Contacts/5", 204, None),
    ({"operation": "delete_record", "table": "Contacts", "record_id": 5}, "DELETE", "/tables/Contacts/5", 204, None),
    ({"operation": "count_records", "table": "Contacts", "filter": "BillAddressCountry eq 'Canada'"}, "GET", "/tables/Contacts/count", 200, 0),
    ({"operation": "sync_record", "table": "Invoice", "record_id": 10}, "POST", "/tables/Invoice/10/Sync", 204, None),
    ({"operation": "list_files", "table": "Contacts", "record_id": 4}, "GET", "/files", 200, DOCS["GET /api/v1/files"]),
    ({"operation": "get_file_url", "file_id": FILE}, "GET", f"/files/{FILE}/url", 200, "https://files.example.test/report.pdf"),
    ({"operation": "update_file_link", "file_id": FILE, "table": "Contacts", "record_id": 4, "attach_to_email": False}, "PUT", f"/files/{FILE}/link", 204, None),
    ({"operation": "delete_file", "file_id": FILE}, "DELETE", f"/files/{FILE}", 204, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,status,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_method_crm_one_contract_operation(monkeypatch, config, method, path, status, body):
    requests = transport(monkeypatch, status, body)
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1" + path
    assert request.url.host == "rest.method.me"
    assert request.headers["Authorization"] == "APIKey " + KEY
    name = config["operation"]
    if name in {"create_record", "update_record"}:
        assert json.loads(request.content) == json.loads(config["record_json"])
    elif name == "update_file_link":
        assert json.loads(request.content) == {"tableName": "Contacts", "recordId": 4, "attachToEmail": False}
    else:
        assert not request.content
    if name == "query_records":
        assert dict(request.url.params) == {"filter": config["filter"], "select": config["select"], "top": "2", "skip": "0"}
        assert result["next_link"] == body["nextLink"]
        assert result["items"] == body["value"]
    elif name == "list_files":
        assert dict(request.url.params) == {"table": "Contacts", "recordId": "4"}
    elif name == "get_record":
        assert dict(request.url.params) == {"select": config["select"], "expand": "Entity"}
        assert result["data"] == body
    elif name == "create_record":
        assert result == {"record_id": 5}
    elif name == "count_records":
        assert result == {"count": 0}
    elif status == 204:
        assert result == {"success": True}


@pytest.mark.asyncio
async def test_method_crm_empty_tables_are_a_successful_read(monkeypatch):
    transport(monkeypatch, body={"count": 0, "value": []})
    assert await node({"operation": "list_tables"}).execute({}) == {"items": [], "count": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_method_crm_rejection_keeps_provider_reason_and_redacts_key(monkeypatch, status):
    transport(monkeypatch, status, {"detail": "Rejected " + KEY})
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_tables"}).execute({})
    assert f"HTTP {status}" in str(error.value) and "Rejected" in str(error.value)
    assert KEY not in str(error.value)


@pytest.mark.parametrize("body", ['[]', '{}', '{"__InvoiceLine":[]}', '{"Name":NaN}', '{"Name":"x","__InvoiceLine":' + json.dumps([{}] * 51) + '}'])
def test_method_crm_invalid_record_body_rejected(body):
    with pytest.raises(ValueError):
        node({"operation": "create_record", "table": "Invoice", "record_json": body})


@pytest.mark.parametrize("table", ["../Contacts", "Contacts/5", "Contacts?select=Email", ".."])
def test_method_crm_path_injection_rejected(table):
    with pytest.raises(ValueError):
        node({"operation": "get_table_fields", "table": table})


def test_method_crm_credential_type_defaults_for_manual_connect():
    credential = native.MethodCRMAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == "method_crm_api_key"
    assert set(native.MethodCRMAPIKeyCredential.model_fields) == {"credential_type", "api_key"}
