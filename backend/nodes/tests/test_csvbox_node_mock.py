"""Exercise Csvbox through the registry against provider-documented request shapes.

Transport-only mocks leave parsing, credentials, routing and serialization real.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import csvbox_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/csvbox/contract_cases.json").read_text())["cases"]
KEY = "csvbox-fixture-key-abc123"
SECRET = "csvbox-fixture-secret-def456"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="csvbox-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": credentials or {
            "credential_type": "csvbox_api_key", "api_key": KEY, "secret_api_key": SECRET}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_documented_actions_have_one_exact_request(monkeypatch, case):
    operation = case["config"]["operation"]
    body = {"sheet_license_key": "a1b2c3d4", "title": "Customer Import"}
    reply = {"data": [body], "meta": {"current_page": 1, "last_page": 3}, "links": {"next": "https://api.csvbox.io/1.1/sheet?page=2"}} if operation == "list_sheets" else body if operation == "get_sheet" else {"status": "Sheet Created Successfully" if operation == "create_sheet" else "Sheet Updated Successfully", "data": body}
    requests = transport(monkeypatch, lambda request: httpx.Response(201 if operation == "create_sheet" else 200, json=reply))
    result = await node(case["config"]).run({})
    assert result["status"] == "success" and result["data"] == (reply["data"] if operation != "get_sheet" else body)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "api.csvbox.io"
    assert request.headers["x-csvbox-api-key"] == KEY and request.headers["x-csvbox-secret-api-key"] == SECRET
    assert request.headers["Accept"] == "application/json" and request.headers["Content-Type"] == "application/json"
    if case["body"] is None:
        assert request.content == b""
        assert dict(request.url.params) == ({"page": "1", "per_page": "20"} if operation == "list_sheets" else {})
    else:
        assert not request.url.query
        assert json.loads(request.content) == case["body"]
    assert KEY not in str(result) and SECRET not in str(result)


@pytest.mark.asyncio
async def test_patch_preserves_omitted_script_fields_and_alias(monkeypatch):
    requests = transport(monkeypatch, {"status": "Sheet Partially Updated Successfully", "data": {"sheet_license_key": "a1b2c3d4"}})
    for items in [[{"function_name": "check_email", "active": False}], [{"function_name": "old_one", "_delete": True}], []]:
        result = await node({"operation": "merge_validation_functions", "sheet_license_key": "a1b2c3d4", "validation_functions": items}).execute({})
        assert result["status"] == "success"
        assert json.loads(requests[-1].content) == {"validation_functions": items}
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_nullable_steps_false_values_and_empty_arrays_survive(monkeypatch):
    requests = transport(monkeypatch, {"data": {}, "status": "Sheet Partially Updated Successfully"})
    fields = {"steps": {"file_upload": {"page_limit": None, "accept_raw_value": False}}, "webhooks": []}
    result = await node({"operation": "patch_sheet", "sheet_license_key": "123", "title": None, "data_transforms": "", **fields}).execute({})
    assert result["status"] == "success" and json.loads(requests[0].content) == fields


@pytest.mark.asyncio
async def test_pagination_is_explicit_and_never_follows_response_urls(monkeypatch):
    body = {"data": [], "meta": {"current_page": 2, "last_page": 2}, "links": {"next": "https://untrusted.example/page"}}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_sheets", "page": 2, "per_page": 100}).execute({})
    assert len(requests) == 1 and dict(requests[0].url.params) == {"page": "2", "per_page": "100"}
    assert result["data"] == [] and result["meta"] == body["meta"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 301, 302, 400, 401, 403, 404, 422, 429, 500])
async def test_failures_are_not_success_and_credentials_are_redacted(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"message": f"Rejected {KEY} {SECRET}"}, headers={"Location": "https://untrusted.example"}))
    result = await node({"operation": "list_sheets"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert KEY not in str(result) and SECRET not in str(result) and len(requests) == 1
    if status != 204:
        assert result["error"] == "Rejected [redacted] [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>unexpected</html>"), httpx.Response(200, json={"errors": {"title": ["Invalid"]}})])
async def test_unexpected_json_and_error_envelopes_fail(monkeypatch, response):
    transport(monkeypatch, lambda r: response)
    assert (await node({"operation": "list_sheets"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_network_errors_do_not_echo_headers(monkeypatch):
    def failed(request):
        raise httpx.ConnectError(f"unavailable {KEY} {SECRET}")
    requests = transport(monkeypatch, failed)
    result = await node({"operation": "list_sheets"}).execute({})
    assert result["status"] == "error" and len(requests) == 1
    assert KEY not in str(result) and SECRET not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [
    {"operation": "patch_sheet", "sheet_license_key": "123"},
    {"operation": "create_sheet", "title": "Customer Import", "virtual_columns": [{"column_name": "full_name"}]},
    {"operation": "update_sheet", "sheet_license_key": "123", "virtual_columns": [{"column_name": "full_name", "_delete": True}]},
    {"operation": "merge_virtual_columns", "sheet_license_key": "123", "virtual_columns": [{"column_name": "full_name", "js_code": " "}]},
])
async def test_invalid_script_mutations_fail_before_sending(monkeypatch, config):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node(config).execute({})
    assert requests == []


@pytest.mark.parametrize("config", [
    {"operation": "get_sheet", "sheet_license_key": "../123"},
    {"operation": "get_sheet", "sheet_license_key": "123?x=1"},
    {"operation": "list_sheets", "page": 0},
    {"operation": "list_sheets", "per_page": 101},
    {"operation": "list_sheets", "page": True},
    {"operation": "create_sheet"},
    {"operation": "delete_sheet", "sheet_license_key": "123"},
    {"operation": "patch_sheet", "sheet_license_key": "123", "display": {"theme": "Dark"}},
    {"operation": "set_security_settings", "sheet_license_key": "123", "security_settings": {"region": "other"}},
])
def test_invalid_config_cannot_reach_transport(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_pair_defaults_and_secret_validation():
    shaped = native.CsvboxAPIKeyCredential(api_key=" " + KEY + "\n", secret_api_key=SECRET)
    assert shaped.credential_type == "csvbox_api_key" and shaped.api_key == KEY
    for values in [{"api_key": KEY}, {"api_key": "https://app.csvbox.io", "secret_api_key": SECRET}, {"api_key": KEY, "secret_api_key": "bad\nkey"}]:
        with pytest.raises(ValidationError):
            native.CsvboxAPIKeyCredential.model_validate(values)
