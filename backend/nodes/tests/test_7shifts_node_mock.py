"""Replay 7shifts' verbatim saved Postman responses; no live credentials or invented response schemas."""
import importlib
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.registry import NodeFactory

native = importlib.import_module("nodes.7shifts_node")
FIXTURE = json.loads((Path(__file__).parent / "fixtures/7shifts/collection_examples.json").read_text())
OPERATIONS = FIXTURE["operations"]
TOKEN = "test-7shifts-access-value-42"
GUID = "1310bfe1-cb3f-4f24-98a2-fde2bc504108"
CASES = [(op, index) for op, item in OPERATIONS.items() for index in range(len(item["responses"]))]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="seven-shifts-test", node_type="automation-7shifts", node_data={
        "config": config, "credentials": {"credential_type": "7shifts_access_token", "access_token": TOKEN, **credential}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,index", CASES)
async def test_published_postman_request_and_every_saved_response(monkeypatch, operation, index):
    item = OPERATIONS[operation]
    saved = item["responses"][index]
    requests = transport(monkeypatch, httpx.Response(saved["code"], content=saved.get("body", "").encode(),
        headers={h["key"]: h["value"] for h in saved.get("header", [])}))
    result = await node(item["config"], company_guid=GUID).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == item["request"]["method"]
    path = "/" + "/".join(item["request"]["url"]["path"])
    for variable in item["request"]["url"].get("variable", []):
        key = {"id": "company_id", "identifier": "user_id"}.get(variable["key"], variable["key"])
        path = path.replace(":" + variable["key"], str(item["config"][key]))
    assert request.url.path == path
    assert request.url.host == "api.7shifts.com"
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["x-api-version"] == "2024-04-01"
    assert request.headers["x-company-guid"] == GUID
    assert result["http_status"] == saved["code"]
    assert result["status"] == ("success" if 200 <= saved["code"] < 300 else "error")
    assert TOKEN not in json.dumps(result)
    if saved["code"] == 204:
        assert result["deleted"] is True
    elif saved["code"] < 300:
        body = json.loads(saved["body"])
        expected = body if operation in {"get_company", "get_time_off", "create_time_off", "update_time_off"} else body["data"]
        assert result["data"] == native._redact(expected, TOKEN)
        if "meta" in body and operation != "get_company":
            assert result["meta"] == body["meta"]


@pytest.mark.asyncio
async def test_personal_token_connection_read_omits_partner_header_and_removes_api_key(monkeypatch):
    saved = OPERATIONS["list_companies"]["responses"][0]
    requests = transport(monkeypatch, httpx.Response(200, content=saved["body"], headers={"content-type": "application/json"}))
    result = await node({"operation": "list_companies"}).execute({})
    assert "x-company-guid" not in requests[0].headers
    assert result["data"] and "api_key" not in json.dumps(result)
    assert native.SevenShiftsNode.connection_evidence.operation == "list_companies"
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_filters_are_encoded_and_paging_is_explicit(monkeypatch):
    saved = OPERATIONS["list_shifts"]["responses"][0]
    requests = transport(monkeypatch, httpx.Response(200, content=saved["body"], headers={"content-type": "application/json"}))
    result = await node({"operation": "list_shifts", "company_id": 1234, "start_gte": "2022-07-07T04:30:00+05:30", "open": False, "cursor": "next+/=", "limit": 50}).execute({})
    assert dict(requests[0].url.params) == {"start[gte]": "2022-07-06T23:00:00Z", "open": "false", "cursor": "next+/=", "limit": "50"}
    assert result["next_cursor"] == "<string>" and result["has_more"] is True
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_time_off_query_uses_underscores_and_company_scope(monkeypatch):
    saved = OPERATIONS["list_time_off"]["responses"][0]
    requests = transport(monkeypatch, httpx.Response(200, content=saved["body"], headers={"content-type": "application/json"}))
    await node({"operation": "list_time_off", "company_id": 8655, "to_date_gte": "2020-01-01"}).execute({})
    assert dict(requests[0].url.params) == {"company_id": "8655", "to_date_gte": "2020-01-01", "limit": "100"}


@pytest.mark.asyncio
async def test_create_user_sends_only_selected_fields_and_does_not_invite_by_default(monkeypatch):
    saved = OPERATIONS["create_user"]["responses"][0]
    requests = transport(monkeypatch, httpx.Response(201, content=saved["body"], headers={"content-type": "application/json"}))
    config = {"operation": "create_user", "company_id": 1234, "first_name": "Jason", "last_name": "Bourne", "location_ids": [4569], "department_ids": [7890]}
    await node(config).execute({})
    assert json.loads(requests[0].content) == {"first_name": "Jason", "last_name": "Bourne", "location_ids": [4569], "department_ids": [7890], "type": "employee", "invite_user": False}
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update_user", "update_time_punch", "update_time_off"])
async def test_empty_updates_refused_before_network(monkeypatch, operation):
    requests = transport(monkeypatch, httpx.Response(500))
    config = {key: value for key, value in OPERATIONS[operation]["config"].items() if key in {"operation", "company_id", "user_id", "time_punch_id", "time_off_id"}}
    with pytest.raises(ValueError, match="at least one field"):
        await node(config).execute({})
    assert not requests


@pytest.mark.parametrize("changes", [
    {"access_token": "Bearer some-token"}, {"access_token": "https://example.test/token"},
    {"access_token": "abc\r\nInjected: true"}, {"company_guid": "https://example.test/"},
])
def test_invalid_credentials_are_refused(changes):
    with pytest.raises(ValidationError):
        native.SevenShiftsAccessTokenCredential.model_validate({"access_token": TOKEN, **changes})


@pytest.mark.parametrize("config", [
    {"operation": "get_shift", "company_id": 0, "shift_id": 1},
    {"operation": "get_shift", "company_id": 1, "shift_id": "../users"},
    {"operation": "list_users", "company_id": 1, "location_id": 1, "role_id": 1},
    {"operation": "create_shift", "company_id": 1, "location_id": 1, "start": "2022-07-07T05:00:00Z", "end": "2022-07-06T23:00:00Z"},
    {"operation": "create_time_punch", "company_id": 1, "location_id": 1, "user_id": 1, "clocked_in": "2022-07-06T23:00:00"},
    {"operation": "list_shifts", "company_id": 1, "limit": 0},
    {"operation": "list_locations", "company_id": 1, "modified_since": "2022-02-30"},
])
def test_invalid_config_fails_before_request(config):
    assert not native.SevenShiftsNode.validate_config({"config": config})["valid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://example.test/"}),
    httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}),
    httpx.Response(200, json={"data": "unexpected"}),
    httpx.Response(200, text="{", headers={"content-type": "application/json"}),
])
async def test_redirects_and_invalid_response_shapes_fail(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_companies"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_unsaved_credential_evidence_runs_the_native_account_read(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    saved = OPERATIONS["list_companies"]["responses"][0]
    requests = transport(monkeypatch, httpx.Response(200, content=saved["body"], headers={"content-type": "application/json"}))
    evidence = await collect_evidence(node_type="automation-7shifts", user_id="seven-shifts-fixture", credential_data={
        "credential_type": "7shifts_access_token", "access_token": TOKEN})
    assert evidence.reachable is True and evidence.samples
    assert evidence.samples[0].label == "string"
    assert len(requests) == 1 and requests[0].url.path == "/v2/companies"
    assert "x-company-guid" not in requests[0].headers
