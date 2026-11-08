"""Softr native factory and HTTP regressions; all keys and responses are fake."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import softr_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-softr-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="softr-test", node_type="automation-softr", node_data={
        "config": config,
        "credentials": credential or {"credential_type": "softr_api_key", "api_key": TOKEN},
    })


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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", native.ROUTES.items())
async def test_every_operation_makes_one_exact_contract_request(monkeypatch, operation, route):
    method, path = route
    config = {"operation": operation}
    for name, value in {"database_id": "db_1", "table_id": "tb_1", "record_id": "rec_1", "field_id": "fld_1"}.items():
        if "{" + name + "}" in path:
            config[name] = value
            path = path.replace("{" + name + "}", value)
    if operation == "create_database":
        config["workspace_id"] = "ws_1"
    if operation in {"create_database", "update_database", "create_table", "update_table", "add_table_field", "update_table_field"}:
        config["name"] = "Contacts"
    if operation == "add_table_field":
        config["field_type"] = "SINGLE_LINE_TEXT"
    if operation in {"create_record", "update_record"}:
        config["fields_json"] = '{"fld_email":"ada@example.com","fld_active":false,"fld_count":0,"fld_clear":null}'
    listing = operation.startswith("list_") or operation == "search_records"
    body = {"data": [{"id": "fixture"}] if listing else {"id": "fixture"}, "metadata": {"offset": 0, "limit": 10, "total": 25}}
    requests = transport(monkeypatch, 204 if method == "DELETE" else 200, body)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split("?")[0] == native.BASE_URL + path
    assert request.headers["Softr-Api-Key"] == TOKEN
    assert "Authorization" not in request.headers
    assert TOKEN not in str(result)
    if operation in {"create_record", "update_record"}:
        assert json.loads(request.content) == {"fields": json.loads(config["fields_json"])}
        assert dict(request.url.params) == {"fieldNames": "false"}
    if operation in {"delete_database", "delete_table"}:
        assert dict(request.url.params) == {"force": "false"}
    if method == "DELETE":
        assert result == {"status": "success", "deleted": True, "http_status": 204}
        assert request.content == b""
    if operation in {"list_records", "search_records"}:
        assert result["metadata"] == body["metadata"]


@pytest.mark.asyncio
async def test_search_filters_sorting_and_explicit_paging(monkeypatch):
    requests = transport(monkeypatch, body={"data": [], "metadata": {"offset": 20, "limit": 5, "total": 20}})
    await node({"operation": "search_records", "database_id": "db_1", "table_id": "tb_1", "offset": 20, "limit": 5,
        "field_names": True, "condition_json": '{"operator":"IS","leftSide":"fld_status","rightSide":"Active"}',
        "sorting_json": '[{"sortingField":"fld_name","sortType":"ASC"}]'}).execute({})
    assert dict(requests[0].url.params) == {"fieldNames": "true"}
    assert json.loads(requests[0].content) == {"paging": {"offset": 20, "limit": 5},
        "filter": {"condition": {"operator": "IS", "leftSide": "fld_status", "rightSide": "Active"}},
        "sorting": [{"sortingField": "fld_name", "sortType": "ASC"}]}


@pytest.mark.asyncio
async def test_list_record_view_and_page_are_preserved(monkeypatch):
    requests = transport(monkeypatch, body={"data": [], "metadata": {"offset": 50, "limit": 25, "total": 50}})
    await node({"operation": "list_records", "database_id": "db_1", "table_id": "tb_1", "view_id": "vw_1",
        "offset": 50, "limit": 25, "field_names": True}).execute({})
    assert dict(requests[0].url.params) == {"viewId": "vw_1", "fieldNames": "true", "offset": "50", "limit": "25"}


@pytest.mark.asyncio
async def test_write_aliases_and_field_options(monkeypatch):
    requests = transport(monkeypatch, body={"data": {"id": "db_1"}})
    await node({"operation": "create_database", "workspace_id": "ws_1", "name": "CRM", "description": "Customers"}).execute({})
    assert json.loads(requests[0].content) == {"workspaceId": "ws_1", "name": "CRM", "description": "Customers"}
    await node({"operation": "add_table_field", "database_id": "db_1", "table_id": "tb_1", "name": "Status",
        "field_type": "SELECT", "options_json": '{"choices":["Active","Inactive"]}'}).execute({})
    assert json.loads(requests[1].content) == {"name": "Status", "type": "SELECT", "options": {"choices": ["Active", "Inactive"]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
async def test_errors_report_provider_message_and_redact_key_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, status, {"message": "Invalid API key. " + TOKEN})
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await node({"operation": "list_databases"}).execute({})
    assert "Invalid API key." in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": {}}, {"data": [], "errorCode": "DENIED"}, []])
async def test_malformed_and_error_envelopes_do_not_prove_connection(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node({"operation": "list_databases"}).execute({})


@pytest.mark.asyncio
async def test_empty_account_and_evidence_need_no_extra_configuration(monkeypatch):
    transport(monkeypatch, body={"data": []})
    assert (await node({"operation": native.SoftrNode.connection_evidence.operation}).execute({}))["data"] == []


@pytest.mark.parametrize("identifier", ["../other", "x/y", "x?key=y", "https://evil.test", ""])
def test_path_injection_rejected(identifier):
    assert not native.SoftrNode.validate_config({"config": {"operation": "get_database", "database_id": identifier}})["valid"]


@pytest.mark.parametrize("text", ['[]', 'null', 'NaN', '{"x":Infinity}', '{"x":1e999}', '{bad'])
def test_record_json_requires_finite_object(text):
    with pytest.raises(ValidationError):
        native.CreateRecord(database_id="db_1", table_id="tb_1", fields_json=text)


@pytest.mark.parametrize("token", ["https://evil.test/token", "Bearer key", "key\nheader", "<token>"])
def test_invalid_key_rejected(token):
    with pytest.raises(ValidationError):
        native.SoftrAPIKey(api_key=token)


@pytest.mark.parametrize("text", ['["not-an-object"]', '[{"sortType":{}}]', '[{"sortingField":3}]', '[{"sortType":"ascending"}]'])
def test_sorting_rejects_non_contract_shapes(text):
    with pytest.raises(ValidationError):
        native.SearchRecords(database_id="db_1", table_id="tb_1", sorting_json=text)
