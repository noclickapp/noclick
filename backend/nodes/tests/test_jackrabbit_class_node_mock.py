"""Exercise the registered Jackrabbit Class node at its HTTP boundary.

Fixtures use synthetic account data and check documented route/body spellings,
manual credentials, pagination, and uncertain write outcomes without live calls.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import jackrabbit_class_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

TOKEN = "synthetic-jackrabbit-token"
CASES = json.loads((Path(__file__).parent / "fixtures/jackrabbit_class/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(
        node_id="fixture", node_type="automation-jackrabbit-class",
        node_data={"config": config, "credentials": {"api_token": TOKEN, **credential}})


def transport(monkeypatch, response):
    calls = []
    def handle(request):
        calls.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(CASES))
async def test_contract_routes_query_and_json_bodies(monkeypatch, operation):
    config, method, path, body = CASES[operation]
    reply = {"name": "Fixture Academy"} if operation == "get_organization" else (
        {"data": [{"id": 9}], "totalCount": 26, "page": 1, "pageSize": 25}
        if operation.startswith("list_") and operation != "list_locations" else {"id": 9})
    calls = transport(monkeypatch, httpx.Response(201 if operation.startswith("create_") else 200, json=reply))
    result = await node({"operation": operation, **config}, organization_id=55).execute({})
    assert result["success"] is True and TOKEN not in str(result)
    assert len(calls) == 1
    request = calls[0]
    assert (request.method, request.url.host, request.url.path) == (method, "api.jackrabbitclass.com", path)
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["X-Org-Id"] == "55"
    if body is not None:
        assert json.loads(request.content) == body
        assert request.headers["content-type"] == "application/json"
        assert result["write_outcome"] == "acknowledged"
    else:
        assert not request.content
    if "page" in native.QUERY_FIELDS[operation]:
        assert request.url.params["Page"] == "1" and request.url.params["PageSize"] == "25"
        assert result["next_page"] == 2 and result["total_count"] == 26
    if operation == "list_enrollments":
        assert request.url.params["StudentId"] == "12" and request.url.params["Enrolled"] == "false"
    if operation == "list_attendance":
        assert request.url.params["DidAttend"] == "false"


@pytest.mark.asyncio
async def test_account_evidence_and_organization_token(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(200, json={"name": "Fixture Academy", "email": "office@example.test"}))
    result = await node({"operation": "get_organization"}).execute({})
    assert result["data"]["name"] == "Fixture Academy"
    assert "X-Org-Id" not in calls[0].headers
    assert native.JackrabbitClassNode.connection_evidence.operation == "get_organization"


def test_manual_credential_fills_default_type_and_normalizes_token():
    value, errors, resolved = shape_credential(native.CREDENTIAL_TYPE, {"api_token": "  " + TOKEN + "  "})
    assert not errors
    assert value["api_token"] == TOKEN
    assert resolved[1].model_validate(value).credential_type == native.CREDENTIAL_TYPE


@pytest.mark.parametrize("value", ["https://example.com/key", "<token>", "Bearer abc", "bad\nheader", "非ascii"])
def test_refuse_unsafe_pasted_tokens(value):
    with pytest.raises(ValidationError):
        native.JackrabbitClassAPITokenCredential(api_token=value)


@pytest.mark.parametrize("config", [
    {"operation": "update_family", "family_id": 2},
    {"operation": "update_student", "student_id": 2},
    {"operation": "update_contact", "contact_id": 2},
    {"operation": "update_class", "class_id": 2},
    {"operation": "get_student", "student_id": "../../Options/me"},
    {"operation": "list_students", "page": 0},
    {"operation": "list_students", "page_size": 101},
    {"operation": "list_students", "url": "https://other.test"},
    {"operation": "create_student", "first_name": "Sam"},
    {"operation": "enroll_student", "student_id": 12, "class_id": 77},
    {"operation": "drop_student", "student_id": 12, "class_id": 77, "drop_reason_id": 2},
    {"operation": "enroll_student", "student_id": 12, "class_id": 77, "enroll_type_id": 3, "days": {}},
])
def test_invalid_configs_fail_before_network(config):
    with pytest.raises(ValueError):
        native.JackrabbitClassNode.parse_config({"config": config, "credentials": {"api_token": TOKEN}})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 429, 500])
async def test_failure_status_and_secret_redaction(monkeypatch, status):
    calls = transport(monkeypatch, httpx.Response(status, text="Provider refusal " + TOKEN,
                                               headers={"Location": "https://other.test"}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_organization"}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_empty_patch_response_is_acknowledgement(monkeypatch):
    transport(monkeypatch, httpx.Response(200))
    result = await node({"operation": "update_student", "student_id": 12, "is_active": False}).execute({})
    assert result["data"] is None and result["write_outcome"] == "acknowledged"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(200), httpx.Response(200, text="<html>wrong host</html>"),
    httpx.Response(200, json={}), httpx.Response(200, json={"name": ""})])
async def test_invalid_identity_never_proves_account(monkeypatch, reply):
    transport(monkeypatch, reply)
    with pytest.raises(ValueError):
        await node({"operation": "get_organization"}).execute({})


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_never_retried(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("synthetic", request=request)
    calls = transport(monkeypatch, timeout)
    result = await node({"operation": "create_student", "family_id": 9, "first_name": "Sam"}).execute({})
    assert result["status"] == "unknown" and result["success"] is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_terminal_page_and_filters(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(200, json={"data": [], "totalCount": "25", "page": "2", "pageSize": "25"}))
    result = await node({"operation": "list_students", "page": 2, "is_active": False, "date_last_updated": "2026-11-01"}).execute({})
    assert result["next_page"] is None
    assert dict(calls[0].url.params) == {"Page": "2", "PageSize": "25", "IsActive": "false", "DateLastUpdated": "2026-11-01"}
