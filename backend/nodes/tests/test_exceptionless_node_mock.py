"""Exercise the registered node against an offline HTTP transport."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import exceptionless_node as native
from nodes.core.registry import NodeFactory

ID = "0123456789abcdef01234567"
TOKEN = "synthetic-exceptionless-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **fields):
    return NodeFactory.create_node(node_id="exceptionless-test", node_type="automation-exceptionless",
        node_data={"config": {"operation": operation, **fields},
                   "credentials": {"credential_type": "exceptionless_user_token", "api_token": TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("get_current_user", {}, "GET", "/users/me", 200, {"id": ID, "full_name": "Test User"}),
    ("list_organizations", {}, "GET", "/organizations", 200, [{"id": ID, "name": "Test Org"}]),
    ("get_organization", {"organization_id": ID}, "GET", "/organizations/" + ID, 200, {"id": ID}),
    ("list_projects", {}, "GET", "/projects", 200, [{"id": ID}]),
    ("get_project", {"project_id": ID}, "GET", "/projects/" + ID, 200, {"id": ID}),
    ("create_project", {"organization_id": ID, "name": "Production"}, "POST", "/projects", 201, {"id": ID}),
    ("update_project", {"project_id": ID, "name": "Renamed"}, "PATCH", "/projects/" + ID, 200, {"id": ID}),
    ("list_stacks", {}, "GET", "/stacks", 200, [{"id": ID}]),
    ("get_stack", {"stack_id": ID}, "GET", "/stacks/" + ID, 200, {"id": ID}),
    ("list_project_stacks", {"project_id": ID}, "GET", "/projects/" + ID + "/stacks", 200, [{"id": ID}]),
    ("mark_stacks_fixed", {"stack_ids": ID, "version": "v1.2"}, "POST", "/stacks/" + ID + "/mark-fixed", 200, None),
    ("snooze_stacks", {"stack_ids": ID, "snooze_until_utc": "2030-01-01T00:00:00Z"}, "POST", "/stacks/" + ID + "/mark-snoozed", 200, None),
    ("mark_stacks_critical", {"stack_ids": ID}, "POST", "/stacks/" + ID + "/mark-critical", 200, None),
    ("unmark_stacks_critical", {"stack_ids": ID}, "DELETE", "/stacks/" + ID + "/mark-critical", 204, None),
    ("add_stack_link", {"stack_id": ID, "link": "https://example.com/issue/42"}, "POST", "/stacks/" + ID + "/add-link", 200, None),
    ("remove_stack_link", {"stack_id": ID, "link": "https://example.com/issue/42"}, "POST", "/stacks/" + ID + "/remove-link", 204, None),
    ("list_events", {}, "GET", "/events", 200, [{"id": ID, "message": "Failed job"}]),
    ("get_event", {"event_id": ID}, "GET", "/events/" + ID, 200, {"id": ID}),
    ("count_events", {}, "GET", "/events/count", 200, {"total": 74}),
    ("list_stack_events", {"stack_id": ID}, "GET", "/stacks/" + ID + "/events", 200, [{"id": ID}]),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,status,body", CASES)
async def test_all_operations_exact_contract(monkeypatch, operation, fields, method, path, status, body):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, **({"json": body} if body is not None else {})))
    result = await node(operation, **fields).execute({})
    assert result["status"] == "success" and result["http_status"] == status
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split("?")[0] == native.BASE_URL + path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert "access_token" not in request.url.params
    if body is None:
        assert result["acknowledged"] is True
    else:
        assert result["items" if isinstance(body, list) else "data"] == body
    expected_query = {"page": "1", "limit": "10"} if operation.startswith("list_") and operation != "list_organizations" else {}
    if operation == "mark_stacks_fixed": expected_query = {"version": "v1.2"}
    if operation == "snooze_stacks": expected_query = {"snoozeUntilUtc": fields["snooze_until_utc"]}
    assert dict(request.url.params) == expected_query
    expected_body = None
    if operation == "create_project": expected_body = {"organization_id": ID, "name": "Production", "delete_bot_data_enabled": False}
    if operation == "update_project": expected_body = {"name": "Renamed"}
    if operation in {"add_stack_link", "remove_stack_link"}: expected_body = {"value": fields["link"]}
    assert (json.loads(request.content) if request.content else None) == expected_body


@pytest.mark.asyncio
async def test_filters_and_pagination_preserve_user_query(monkeypatch):
    requests = transport(monkeypatch, lambda request: httpx.Response(200, json=[]))
    result = await node("list_events", filter='type:error AND message:"a+b"', sort="-date", time="last 7 days", page=3, limit=50).execute({})
    assert result["items"] == [] and result["page"] == 3 and result["limit"] == 50
    assert dict(requests[0].url.params) == {"filter": 'type:error AND message:"a+b"', "sort": "-date", "time": "last 7 days", "page": "3", "limit": "50"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_errors_keep_provider_reason_and_redact_secret(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, json={"message": "Token rejected " + TOKEN}, headers={"Location": "https://example.com/"}))
    result = await node("list_organizations").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Token rejected" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "denied"}, "not a list", ["bad resource"]])
async def test_bad_list_is_not_success(monkeypatch, body):
    transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node("list_projects").execute({})


@pytest.mark.parametrize("fields", [{"project_id": "../users"}, {"project_id": ID, "extra": True}])
def test_bad_path_and_unknown_fields_are_rejected(fields):
    with pytest.raises((ValidationError, ValueError)):
        node("get_project", **fields)


def test_manual_credential_default_and_schema():
    credential = native.ExceptionlessUserTokenCredential(api_token=TOKEN)
    assert credential.credential_type == "exceptionless_user_token"
    assert native.ExceptionlessNode.connection_evidence.operation == "list_organizations"
    assert len(native.ROUTES) == 20
    with pytest.raises(ValidationError):
        native.ExceptionlessUserTokenCredential(api_token="Bearer " + TOKEN)
