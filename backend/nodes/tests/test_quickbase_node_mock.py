"""Exercise Quickbase through the native factory with offline HTTP responses.

Fixtures come from the provider contract; wire assertions cover every operation,
manual credential shaping, pagination, partial writes and provider rejection.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import quickbase_node as native
from nodes.core.registry import NodeFactory


TOKEN = "quickbase-fixture-user-token"
AUTH = {"credential_type": "quickbase_user_token", "user_token": TOKEN,
        "realm_hostname": "demo.quickbase.com", "app_id": "bck7gp3q2"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/quickbase/responses.json").read_text())["responses"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="quickbase-fixture", node_type="automation-quickbase",
        node_data={"config": config, "credentials": AUTH if credential is None else credential})


def transport(monkeypatch, payload, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("get_app", {}, "GET", "/apps/bck7gp3q2", {}, None),
    ("create_app", {"name": "Testing App", "assign_token": True}, "POST", "/apps", {}, {"name": "Testing App", "assignToken": True}),
    ("update_app", {"name": "Updated"}, "POST", "/apps/bck7gp3q2", {}, {"name": "Updated"}),
    ("list_app_events", {}, "GET", "/apps/bck7gp3q2/events", {}, None),
    ("list_tables", {}, "GET", "/tables", {"appId": "bck7gp3q2"}, None),
    ("create_table", {"name": "My table", "single_record_name": "record"}, "POST", "/tables", {"appId": "bck7gp3q2"}, {"name": "My table", "singleRecordName": "record"}),
    ("get_table", {"table_id": "btable"}, "GET", "/tables/btable", {"appId": "bck7gp3q2"}, None),
    ("update_table", {"table_id": "btable", "description": "Changed", "plural_record_name": "items"}, "POST", "/tables/btable", {"appId": "bck7gp3q2"}, {"description": "Changed", "pluralRecordName": "items"}),
    ("list_reports", {"table_id": "btable"}, "GET", "/reports", {"tableId": "btable"}, None),
    ("get_report", {"table_id": "btable", "report_id": "1"}, "GET", "/reports/1", {"tableId": "btable"}, None),
    ("run_report", {"table_id": "btable", "report_id": "1"}, "POST", "/reports/1/run", {"tableId": "btable", "skip": "0", "top": "100"}, None),
    ("list_fields", {"table_id": "btable", "include_field_perms": True}, "GET", "/fields", {"tableId": "btable", "includeFieldPerms": "true"}, None),
    ("get_field", {"table_id": "btable", "field_id": 6}, "GET", "/fields/6", {"tableId": "btable", "includeFieldPerms": "false"}, None),
    ("create_field", {"table_id": "btable", "label": "Full Name", "field_type": "text"}, "POST", "/fields", {"tableId": "btable"}, {"label": "Full Name", "fieldType": "text"}),
    ("update_field", {"table_id": "btable", "field_id": 6, "field_help": "Changed"}, "POST", "/fields/6", {"tableId": "btable"}, {"fieldHelp": "Changed"}),
    ("list_field_usage", {"table_id": "btable", "skip": 5}, "GET", "/fields/usage", {"tableId": "btable", "skip": "5", "top": "100"}, None),
    ("run_formula", {"table_id": "btable", "formula": "User()", "record_id": 1}, "POST", "/formula/run", {}, {"from": "btable", "formula": "User()", "rid": 1}),
    ("upsert_records", {"table_id": "btable", "data": [{"3": {"value": 1}, "6": {"value": None}}], "merge_field_id": 3, "fields_to_return": [6]}, "POST", "/records", {}, {"to": "btable", "data": [{"3": {"value": 1}, "6": {"value": None}}], "mergeFieldId": 3, "fieldsToReturn": [6]}),
    ("delete_records", {"table_id": "btable", "where": [1, 2, 3]}, "DELETE", "/records", {}, {"from": "btable", "where": [1, 2, 3]}),
    ("query_records", {"table_id": "btable", "select": [6], "sort_by": [{"fieldId": 6, "order": "ASC"}], "where": "{6.EX.'hello'}"}, "POST", "/records/query", {}, {"from": "btable", "select": [6], "sortBy": [{"fieldId": 6, "order": "ASC"}], "where": "{6.EX.'hello'}", "options": {"skip": 0, "top": 100}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,params,body", CASES)
async def test_quickbase_documented_operations(monkeypatch, operation, config, method, path, params, body):
    requests = transport(monkeypatch, FIXTURE[operation])
    result = await node({"operation": operation, **config}).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).startswith("https://api.quickbase.com/v1/")
    assert request.url.path == "/v1" + path
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers["Authorization"] == "QB-USER-TOKEN " + TOKEN
    assert request.headers["QB-Realm-Hostname"] == "demo.quickbase.com"
    assert TOKEN not in str(result)
    assert result["data"] == FIXTURE[operation]


@pytest.mark.asyncio
async def test_quickbase_connection_and_manual_defaults(monkeypatch):
    credential = native.QuickbaseUserTokenCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"})
    assert credential.credential_type == "quickbase_user_token"
    assert native.QuickbaseNode.connection_evidence.identity_operation == "get_app"
    requests = transport(monkeypatch, FIXTURE["get_app"])
    result = await node({"operation": "get_app", "app_id": "otherapp"}).execute({})
    assert requests[0].url.path == "/v1/apps/otherapp"
    assert result["data"]["name"]


@pytest.mark.asyncio
async def test_quickbase_shared_connection_evidence_names_app_and_rejects_token(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, FIXTURE["get_app"])
    result = await collect_evidence(node_type="automation-quickbase", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert result.reachable is True and result.account_label == FIXTURE["get_app"]["name"]
    assert len(requests) == 1 and requests[0].url.path == "/v1/apps/bck7gp3q2"
    transport(monkeypatch, {"message": "Unauthorized", "description": "Invalid user token"}, 401)
    result = await collect_evidence(node_type="automation-quickbase", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert result.reachable is False


@pytest.mark.parametrize("changes", [
    {"realm_hostname": "https://demo.quickbase.com"},
    {"realm_hostname": "demo.quickbase.com.evil.test"},
    {"realm_hostname": "localhost"},
    {"realm_hostname": "demo.quickbase.com\r\nx: y"},
    {"user_token": "QB-USER-TOKEN something"},
    {"app_id": "../secrets"},
    {"credential_type": "another_provider"},
])
def test_quickbase_rejects_bad_credential(changes):
    with pytest.raises(ValidationError):
        native.QuickbaseUserTokenCredential.model_validate({**AUTH, **changes})


@pytest.mark.asyncio
async def test_quickbase_pagination_keeps_provider_count(monkeypatch):
    payload = {"data": [], "metadata": {"skip": 5, "numRecords": 2, "totalRecords": 10, "numFields": 0}}
    transport(monkeypatch, payload)
    result = await node({"operation": "query_records", "table_id": "btable", "skip": 5, "top": 2}).execute({})
    assert result["next_skip"] == 7
    payload["metadata"]["skip"] = 6
    with pytest.raises(ValueError, match="offset"):
        await node({"operation": "query_records", "table_id": "btable", "skip": 5}).execute({})


@pytest.mark.asyncio
async def test_quickbase_upsert_partial_failure_is_not_success(monkeypatch):
    payload = {"data": [], "metadata": {"lineErrors": {"1": ["Invalid field value"]}, "createdRecordIds": [42]}}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "upsert_records", "table_id": "btable", "data": [{"6": {"value": "hello"}}]}).execute({})
    assert result["status"] == "partial" and not result["success"]
    assert result["data"]["metadata"]["createdRecordIds"] == [42]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_quickbase_json_editor_values_reach_typed_wire(monkeypatch):
    requests = transport(monkeypatch, FIXTURE["upsert_records"])
    await node({"operation": "upsert_records", "table_id": "btable",
                "data": '[{"6":{"value":"This is my text"}}]', "fields_to_return": '[6,7]'}).execute({})
    assert json.loads(requests[0].content) == {"to": "btable", "data": [{"6": {"value": "This is my text"}}], "fieldsToReturn": [6, 7]}
    requests = transport(monkeypatch, FIXTURE["query_records"])
    await node({"operation": "query_records", "table_id": "btable", "select": '[1,2,3]',
                "sort_by": '[{"fieldId":4,"order":"ASC"}]'}).execute({})
    assert json.loads(requests[0].content)["sortBy"] == [{"fieldId": 4, "order": "ASC"}]
    requests = transport(monkeypatch, FIXTURE["delete_records"])
    await node({"operation": "delete_records", "table_id": "btable", "where": '[1,2,3]'}).execute({})
    assert json.loads(requests[0].content)["where"] == [1, 2, 3]
    with pytest.raises(ValidationError):
        native.UpsertRecords(table_id="btable", data='[{"6":{"notValue":1}}]')


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_quickbase_errors_preserve_message_without_retry_or_token(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Token denied", "description": "Do not echo " + TOKEN}, status)
    result = await node({"operation": "get_app"}).execute({})
    assert result["status"] == "error" and not result["success"]
    assert result["message"] == "Token denied" and result["status_code"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_quickbase_html_and_invalid_pagination_are_not_success(monkeypatch):
    transport(monkeypatch, {}, headers={"content-type": "text/html"})
    with pytest.raises(ValueError, match="JSON"):
        await node({"operation": "get_app"}).execute({})
    transport(monkeypatch, {"data": [], "metadata": {}})
    with pytest.raises(ValueError, match="pagination"):
        await node({"operation": "query_records", "table_id": "btable"}).execute({})


@pytest.mark.asyncio
async def test_quickbase_empty_update_rejected_before_http(monkeypatch):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_field", "table_id": "btable", "field_id": 6}).execute({})
    assert not requests
