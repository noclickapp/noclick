"""Auth0's published reference response bodies, exercised through real HTTPX serialization.

Each fixture records the source URL beside its unmodified documented body:
https://auth0.com/docs/api/management/v2/users/get-users
https://auth0.com/docs/api/management/v2/users/get-users-by-id
https://auth0.com/docs/api/management/v2/users/post-users
https://auth0.com/docs/api/management/v2/users/patch-users-by-id
https://auth0.com/docs/api/management/v2/users/delete-users-by-id
https://auth0.com/docs/api/management/v2/users/get-user-roles
https://auth0.com/docs/api/management/v2/users/post-user-roles
https://auth0.com/docs/api/management/v2/users/delete-user-roles
https://auth0.com/docs/api/management/v2/roles/get-roles
https://auth0.com/docs/api/management/v2/roles/post-roles
https://auth0.com/docs/api/management/v2/roles/patch-roles-by-id
https://auth0.com/docs/api/management/v2/roles/delete-roles-by-id
https://auth0.com/docs/api/management/v2/organizations/get-organizations
https://auth0.com/docs/api/management/v2/organizations/get-organizations-by-id
https://auth0.com/docs/api/management/v2/organizations/post-organizations
https://auth0.com/docs/api/management/v2/organizations/get-organization-members
https://auth0.com/docs/api/management/v2/organizations/post-members
https://auth0.com/docs/api/management/v2/organizations/delete-members
https://auth0.com/docs/api/management/v2/logs/get-logs
https://auth0.com/docs/api/management/v2/logs/get-logs-by-id
"""
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes.auth0_node import Auth0Node, Auth0NodeConfig, Auth0TokenCredential

FIXTURES = json.loads((Path(__file__).parent / "fixtures/auth0/responses.json").read_text())
CREDENTIAL = {"credential_type": "auth0_token", "tenant_domain": "example.us.auth0.com", "access_token": "auth0-test-token"}
COLLECTIONS = {
    "list_users": "users", "list_roles": "roles", "list_user_roles": "roles",
    "list_organizations": "organizations", "list_organization_members": "members", "list_logs": "logs",
}


def node(config, credential=CREDENTIAL):
    return Auth0Node(
        node_id="auth0-test", node_type="automation-auth0", node_data={},
        config=Auth0NodeConfig.model_validate({"config": config, "credentials": credential}),
        sio=Mock(), sid="test", workflow_id="test", user_id="test",
    )


async def run(monkeypatch, config, body, status=200, *, transport_error=None):
    requests = []

    def transport(request):
        requests.append(request)
        if transport_error:
            raise transport_error("Auth0 request timed out", request=request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    client = httpx.AsyncClient
    monkeypatch.setattr("nodes.auth0_node.httpx.AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(transport), **kwargs))
    return await node(config).execute({}), requests


@pytest.mark.parametrize("operation", FIXTURES)
async def test_documented_response_and_request(operation, monkeypatch):
    fixture = FIXTURES[operation]
    result, requests = await run(monkeypatch, fixture["config"], fixture["body"], fixture["status"])
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["timing_ms"]["api_request"] >= 0
    request, = requests
    assert request.method == fixture["method"]
    assert request.url.host == "example.us.auth0.com"
    path = fixture["path"]
    for key in ("user_id", "role_id", "organization_id", "log_id"):
        if key in fixture["config"]:
            path = path.replace("{id}", quote(fixture["config"][key], safe=""))
    assert request.url.raw_path.split(b"?")[0].decode() == "/api/v2" + path
    assert request.headers["Authorization"] == "Bearer auth0-test-token"
    assert request.headers["Content-Type"] == "application/json"
    if operation.startswith("list_"):
        assert request.url.params["page"] == "0"
        assert request.url.params["per_page"] == "3"
        assert request.url.params["include_totals"] == "true"
        assert not request.content
        assert all(key not in request.url.params for key in ("operation", "user_id", "organization_id"))
        if operation == "list_logs":
            assert request.url.params["sort"] == "date:-1"
        if operation == "list_users":
            assert request.url.params["search_engine"] == "v3"
    elif fixture["method"] == "GET" or operation in ("delete_user", "delete_role"):
        assert not request.content
        assert not request.url.query
    else:
        expected = {k: v for k, v in fixture["config"].items() if k not in ("operation", "user_id", "role_id", "organization_id")}
        assert json.loads(request.content) == expected
        assert not request.url.query
    if isinstance(fixture["body"], list):
        assert result["data"] == {COLLECTIONS[operation]: fixture["body"], "count": len(fixture["body"])}
    else:
        assert result["data"] == (fixture["body"] or {})


@pytest.mark.parametrize("operation,key", COLLECTIONS.items())
async def test_paginated_list_preserves_totals(operation, key, monkeypatch):
    # Auth0's include_totals response variant retains its pagination envelope.
    payload = {key: FIXTURES[operation]["body"], "start": 0, "limit": 3, "length": 1, "total": 7}
    result, _ = await run(monkeypatch, FIXTURES[operation]["config"], payload)
    assert result["data"] == payload


async def test_update_false_and_metadata_survive_without_path_id_in_body(monkeypatch):
    config = {"operation": "update_user", "user_id": "auth0|59c13f5ed6e34e41877c0810", "blocked": False, "app_metadata": {"plan": "paid"}}
    _, requests = await run(monkeypatch, config, FIXTURES["update_user"]["body"])
    assert json.loads(requests[0].content) == {"blocked": False, "app_metadata": {"plan": "paid"}}


async def test_id_cannot_inject_query_or_path(monkeypatch):
    _, requests = await run(monkeypatch, {"operation": "get_user", "user_id": "auth0|id/roles?fields=password#frag"}, {})
    assert requests[0].url.raw_path == b"/api/v2/users/auth0%7Cid%2Froles%3Ffields%3Dpassword%23frag"
    assert not requests[0].url.query


@pytest.mark.parametrize("code", [401, 403, 404, 429, 503])
async def test_provider_error_is_preserved(code, monkeypatch):
    error = {"statusCode": code, "error": "Forbidden", "message": "Insufficient scope, expected any of: read:users"}
    result, _ = await run(monkeypatch, {"operation": "list_users"}, error, code)
    assert result["status"] == "error"
    assert result["error"] == error
    assert result["status_code"] == code


async def test_transport_error_is_reported(monkeypatch):
    result, _ = await run(monkeypatch, {"operation": "list_users"}, None, transport_error=httpx.ReadTimeout)
    assert result["status"] == "error"
    assert result["error"] == "Auth0 request timed out"


@pytest.mark.parametrize("config", [{"operation": "update_user", "user_id": "auth0|abc"}, {"operation": "update_role", "role_id": "rol_abc"}])
async def test_empty_updates_make_no_request(config, monkeypatch):
    with pytest.raises(ValueError, match="at least one field"):
        await node(config).execute({})


async def test_missing_credentials():
    with pytest.raises(ValueError, match="Connect an Auth0"):
        await node({"operation": "list_users"}, None).execute({})


@pytest.mark.parametrize("tenant", ["http://example.auth0.com", "example.auth0.com.evil.test", "https://127.0.0.1", "example.auth0.com:443", "example.auth0.com/api/v2", "https://user:pass@example.auth0.com", "https://example.auth0.com?x=y"])
def test_tenant_rejects_unsafe_origin(tenant):
    with pytest.raises((ValidationError, ValueError)):
        Auth0TokenCredential(tenant_domain=tenant, access_token="test-token")


@pytest.mark.parametrize("value", ["EXAMPLE.US.AUTH0.COM", "https://example.us.auth0.com/"])
def test_tenant_normalizes_dashboard_domain(value):
    assert Auth0TokenCredential(tenant_domain=value, access_token="test-token").tenant_domain == "example.us.auth0.com"


def test_evidence_is_read_only_and_needs_only_credential():
    evidence = Auth0Node.connection_evidence
    assert evidence.operation == "list_users"
    assert evidence.operation_arguments == {"per_page": 3}
    node({"operation": evidence.operation, **evidence.operation_arguments})
