"""Offline requests through the real factory; synthetic responses, no account sign-in."""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import rocketadmin_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-rocketadmin-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credentials):
    return NodeFactory.create_node(node_id="rocketadmin-test", node_type="automation-rocketadmin",
        node_data={"config": config, "credentials": {"credential_type": "rocketadmin_api_key", "api_key": TOKEN, **credentials}})


def transport(monkeypatch, response, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,body", [
    ("list_connections", "GET", "/connections", {"connections": [{"connection": {"id": "db-1", "title": "Sales"}, "accessLevel": "read"}], "connectionsCount": 1}),
    ("list_tables", "GET", "/connection/tables/db-1", []),
    ("list_tables_with_categories", "GET", "/connection/tables/v2/db-1", {"tables": [], "table_categories": []}),
    ("get_table_structure", "GET", "/table/structure/db-1", {"structure": []}),
    ("get_table_structure_uncached", "GET", "/table/structure/no-cache/db-1", {"structure": []}),
    ("list_rows", "POST", "/table/crud/rows/db-1", {"rows": [{"id": 42}], "pagination": {"currentPage": 2, "lastPage": 3}}),
    ("get_row", "GET", "/table/crud/db-1", {"row": {"id": 42}}),
    ("create_row", "POST", "/table/crud/db-1", {"row": {"id": 42}}),
    ("update_row", "PUT", "/table/crud/db-1", {"row": {"id": 42}}),
    ("delete_row", "DELETE", "/table/crud/db-1", {"row": {"id": 42}}),
])
async def test_published_routes_auth_query_and_body(monkeypatch, operation, method, path, body):
    cfg = {"operation": operation}
    if operation != "list_connections": cfg["connection_id"] = "db-1"
    if operation not in {"list_connections", "list_tables", "list_tables_with_categories"}: cfg["table_name"] = "Orders + café"
    if operation in {"get_row", "update_row", "delete_row"}: cfg["primary_key"] = '{"id":42,"tenant":"a+b"}'
    if operation in {"create_row", "update_row"}: cfg["values"] = '{"name":"Ada"}'
    if operation == "list_rows": cfg.update(page=2, per_page=5, filters={"id": {"eq": 42}}, search="A+B")
    requests = transport(monkeypatch, body, 201 if operation == "create_row" else 200)
    result = await node(cfg, master_password="synthetic-master-42").execute({})
    assert result["status"] == "success" and TOKEN not in str(result)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/api" + path
    assert req.url.host == "app.rocketadmin.com"
    assert req.headers["x-api-key"] == TOKEN and req.headers["masterpwd"] == "synthetic-master-42"
    assert "Authorization" not in req.headers
    if "table_name" in cfg: assert req.url.params["tableName"] == cfg["table_name"]
    if "primary_key" in cfg: assert req.url.params["id"] == "42" and req.url.params["tenant"] == "a+b"
    if "values" in cfg: assert json.loads(req.content) == {"name": "Ada"}
    if operation == "list_rows":
        assert json.loads(req.content) == {"filters": {"id": {"eq": 42}}}
        assert dict(req.url.params) == {"tableName": cfg["table_name"], "page": "2", "perPage": "5", "search": "A+B"}
        assert result["pagination"]["lastPage"] == 3
    if operation == "list_connections": assert result["items"][0]["title"] == "Sales"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_rejected_requests_preserve_provider_message_without_secrets(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Key rejected " + TOKEN}, status)
    result = await node({"operation": "list_connections"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Key rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"connections": [None]}, {"error": "rejected"}])
async def test_connection_evidence_refuses_malformed_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError): await node({"operation": "list_connections"}).execute({})


@pytest.mark.asyncio
async def test_redacts_nested_secret_echo(monkeypatch):
    transport(monkeypatch, {"row": {"echo": TOKEN}})
    result = await node({"operation": "get_row", "connection_id": "db-1", "table_name": "users", "primary_key": {"id": 42}}).execute({})
    assert result["row"] == {"echo": "[redacted]"}


@pytest.mark.parametrize("changes", [{"primary_key": {}}, {"primary_key": {"tableName": "evil"}}, {"connection_id": "../other"}])
def test_invalid_selection_fails_before_request(changes):
    with pytest.raises(ValidationError):
        native.GetRow.model_validate({"connection_id": "db-1", "table_name": "users", "primary_key": {"id": 42}, **changes})


def test_manual_credential_default_and_secret_validation():
    assert native.RocketadminAPIKeyCredential(api_key=TOKEN).credential_type == "rocketadmin_api_key"
    for value in ["https://example.test/key", "<token>", "bad\r\nheader"]:
        with pytest.raises(ValueError): native.RocketadminAPIKeyCredential(api_key=value)
