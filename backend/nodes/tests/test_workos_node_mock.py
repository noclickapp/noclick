"""Exercise WorkOS requests through real node discovery and HTTP serialization."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import workos_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

TOKEN = "synthetic-workos-key-12345"
AUTH = {"credential_type": "workos_api_key", "api_key": TOKEN}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def respond(request):
        requests.append(request)
        assert request.url.host == "api.workos.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, content=payload) if isinstance(payload, bytes) else httpx.Response(code, json=payload)
    client = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(respond)))
    return requests, replies


def node(config, credentials=AUTH):
    return NodeFactory.create_node(node_id="workos-test", node_type="automation-workos",
        node_data={"config": config, "credentials": deepcopy(credentials)})


# Independently stated route expectations catch mismatched methods, paths and ID placement.
CASES = [
    ("list_organizations", {}, "GET", "/organizations"),
    ("get_organization", {"organization_id": "org_123"}, "GET", "/organizations/org_123"),
    ("create_organization", {"name": "Acme"}, "POST", "/organizations"),
    ("update_organization", {"organization_id": "org_123", "name": "Acme"}, "PUT", "/organizations/org_123"),
    ("delete_organization", {"organization_id": "org_123"}, "DELETE", "/organizations/org_123"),
    ("list_users", {}, "GET", "/user_management/users"),
    ("get_user", {"user_id": "user_123"}, "GET", "/user_management/users/user_123"),
    ("create_user", {"email": "marcelina.davis@example.com"}, "POST", "/user_management/users"),
    ("update_user", {"user_id": "user_123", "first_name": "Marcelina"}, "PUT", "/user_management/users/user_123"),
    ("delete_user", {"user_id": "user_123"}, "DELETE", "/user_management/users/user_123"),
    ("list_memberships", {}, "GET", "/user_management/organization_memberships"),
    ("get_membership", {"membership_id": "om_123"}, "GET", "/user_management/organization_memberships/om_123"),
    ("create_membership", {"organization_id": "org_123", "user_id": "user_123", "role_slug": "member"}, "POST", "/user_management/organization_memberships"),
    ("update_membership", {"membership_id": "om_123", "role_slug": "member"}, "PUT", "/user_management/organization_memberships/om_123"),
    ("delete_membership", {"membership_id": "om_123"}, "DELETE", "/user_management/organization_memberships/om_123"),
    ("list_directories", {}, "GET", "/directories"),
    ("get_directory", {"directory_id": "directory_123"}, "GET", "/directories/directory_123"),
    ("list_directory_users", {}, "GET", "/directory_users"),
    ("get_directory_user", {"directory_user_id": "directory_user_123"}, "GET", "/directory_users/directory_user_123"),
    ("list_directory_groups", {}, "GET", "/directory_groups"),
    ("get_directory_group", {"directory_group_id": "directory_group_123"}, "GET", "/directory_groups/directory_group_123"),
    ("list_connections", {}, "GET", "/connections"),
    ("get_connection", {"connection_id": "conn_123"}, "GET", "/connections/conn_123"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path", CASES)
async def test_one_operation_one_documented_request(transport, operation, fields, method, path):
    requests, replies = transport
    payload = {"object": "list", "data": [], "list_metadata": {"before": None, "after": None}} if operation.startswith("list_") else {"id": "result_123", "object": "resource"}
    replies.append((200, b"" if method == "DELETE" else payload))
    result = await node({"operation": operation, **fields}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    if method in {"POST", "PUT"}:
        body = {k: v for k, v in fields.items() if not (k.endswith("_id") and path.endswith('/' + str(v)))}
        assert json.loads(request.content) == body
    elif method == "GET":
        assert dict(request.url.params) == ({"limit": "10"} if operation.startswith("list_") else {})
    else:
        assert not request.content
        assert result["deletion_acknowledged"] and result["absence_verified"] is False


@pytest.mark.asyncio
async def test_filters_cursors_and_metadata_are_preserved(transport):
    requests, replies = transport
    payload = {"object": "list", "data": [{"id": "directory_user_123", "first_name": "Jane"}],
        "list_metadata": {"before": "directory_user_122", "after": "directory_user_124"}}
    replies.append((200, payload))
    result = await node({"operation": "list_directory_users", "directory": "directory_123", "email": "jane+tag@example.com", "after": "directory_user_121", "limit": 25, "order": "asc"}).execute({})
    assert result["data"] == payload["data"] and result["list_metadata"] == payload["list_metadata"]
    assert dict(requests[0].url.params) == {"directory": "directory_123", "email": "jane+tag@example.com", "after": "directory_user_121", "limit": "25", "order": "asc"}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 422, 429, 500])
async def test_provider_errors_are_not_retried_and_do_not_leak_key(transport, code):
    requests, replies = transport
    replies.append((code, {"message": "Rejected " + TOKEN}))
    result = await node({"operation": "create_organization", "name": "Acme"}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert TOKEN not in str(result) and "Rejected" in result["message"] and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"error": "rejected"}, []])
async def test_invalid_success_list_is_rejected(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError):
        await node({"operation": "list_organizations"}).execute({})


@pytest.mark.parametrize("changes", [{"limit": 0}, {"limit": 101}, {"after": "../users"}, {"after": "x", "before": "y"}])
def test_pagination_validation(changes):
    with pytest.raises(ValidationError):
        native.ListOrganizations(**changes)


def test_manual_credential_defaults_and_validation():
    assert native.WorkOSAPIKeyCredential(api_key=TOKEN).credential_type == "workos_api_key"
    assert native.WorkOSAPIKeyCredential(api_key="  " + TOKEN + "  ").api_key == TOKEN
    for value in ["https://example.com", "Bearer " + TOKEN, "x\ny"]:
        with pytest.raises(ValidationError):
            native.WorkOSAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_empty_user_update_never_sends_request(transport):
    requests, _ = transport
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_user", "user_id": "user_123"}).execute({})
    assert not requests


@pytest.mark.asyncio
async def test_provider_membership_status_is_preserved_in_resource(transport):
    _, replies = transport
    payload = {"object": "organization_membership", "id": "om_123", "status": "active", "organization_id": "org_123", "user_id": "user_123"}
    replies.append((200, payload))
    result = await node({"operation": "get_membership", "membership_id": "om_123"}).execute({})
    assert result["status"] == "success" and result["data"] == payload
