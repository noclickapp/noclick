"""CompanyCam request contracts exercised through the real node factory.

These fixtures are synthetic and never contact a provider account.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import companycam_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-companycam-token-42"
CREDENTIAL = {"credential_type": "companycam_personal_access_token", "access_token": TOKEN}
PROJECT = {"name": "Roof inspection", "street_address_1": "123 Main St", "city": "Lincoln",
           "state": "NE", "postal_code": "68508", "country": "US"}
CASES = [
    ({"operation": "get_current_user"}, "GET", "/users/current", {}, None),
    ({"operation": "get_current_company"}, "GET", "/companies/current", {}, None),
    ({"operation": "list_projects", "after": "cursor-42", "limit": 25, "archived": "false"}, "GET", "/projects", {"limit": "25", "after": "cursor-42", "archived": "false"}, None),
    ({"operation": "get_project", "project_id": "42"}, "GET", "/projects/42", {}, None),
    ({"operation": "create_project", **PROJECT, "customer_id": "5"}, "POST", "/projects", {}, {"project": {**PROJECT, "customer_id": "5"}}),
    ({"operation": "update_project", "project_id": "42", "name": "New roof"}, "PATCH", "/projects/42", {}, {"project": {"name": "New roof"}}),
    ({"operation": "archive_project", "project_id": "42"}, "PATCH", "/projects/42/archive", {}, {}),
    ({"operation": "unarchive_project", "project_id": "42"}, "PATCH", "/projects/42/unarchive", {}, {}),
    ({"operation": "list_project_photos", "project_id": "42"}, "GET", "/projects/42/photos", {"limit": "50"}, None),
    ({"operation": "get_photo", "photo_id": "8"}, "GET", "/photos/8", {}, None),
    ({"operation": "list_project_comments", "project_id": "42"}, "GET", "/projects/42/comments", {}, None),
    ({"operation": "create_project_comment", "project_id": "42", "content": "Inspection complete"}, "POST", "/projects/42/comments", {}, {"comment": {"content": "Inspection complete"}}),
    ({"operation": "list_photo_comments", "photo_id": "8"}, "GET", "/photos/8/comments", {}, None),
    ({"operation": "create_photo_comment", "photo_id": "8", "content": "Replace flashing"}, "POST", "/photos/8/comments", {}, {"comment": {"content": "Replace flashing"}}),
    ({"operation": "list_tags"}, "GET", "/tags", {"limit": "50"}, None),
    ({"operation": "create_tag", "display_value": "Inspection"}, "POST", "/tags", {}, {"tag": {"display_value": "Inspection"}}),
    ({"operation": "list_customers", "q": "Acme"}, "GET", "/customers", {"q": "Acme"}, None),
    ({"operation": "get_customer", "customer_id": "5"}, "GET", "/customers/5", {}, None),
    ({"operation": "create_customer", "name": "Acme", "email": "customer@example.test"}, "POST", "/customers", {}, {"customer": {"name": "Acme", "email": "customer@example.test"}}),
    ({"operation": "list_users", "status": "active", "after": "next"}, "GET", "/users", {"limit": "50", "after": "next", "status": "active"}, None),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=CREDENTIAL):
    return NodeFactory.create_node(node_id="companycam-test", node_type="automation-companycam",
                                   node_data={"config": config, "credentials": credential})


def transport(monkeypatch, response):
    requests = []

    def handler(request):
        requests.append(request)
        return response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_one_request_per_operation(monkeypatch, config, method, path, query, body):
    data = [{"id": "42"}] if config["operation"].startswith("list_") else {"id": "42", "name": "Acme"}
    meta = {"next_cursor": "provider-cursor", "has_more": True}
    requests = transport(monkeypatch, httpx.Response(201 if method == "POST" else 200,
                                                   json={"data": data, "errors": [], "meta": meta}))
    result = await node(config).execute({})
    assert result == {"status": "success", "data": data, "meta": meta}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url.copy_with(query=None)) == native.BASE_URL + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (401, {"errors": [{"code": "token_expired"}]}),
    (403, {"errors": [{"code": "insufficient_scope"}]}),
    (422, {"errors": [{"message": "Invalid project"}]}),
    (429, {"errors": [{"message": "Rate limit exceeded"}]}),
    (200, {"data": {}, "errors": [{"code": "invalid_token"}], "meta": {}}),
])
async def test_provider_errors_are_not_success_and_writes_are_not_retried(monkeypatch, status, body):
    requests = transport(monkeypatch, httpx.Response(status, json=body))
    with pytest.raises(ValueError, match="CompanyCam rejected"):
        await node({"operation": "create_tag", "display_value": "Inspection"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://other.test"}),
    httpx.Response(200, text="<html>Sign in</html>"), httpx.Response(200, json=[]),
    httpx.Response(200, json={"data": [], "errors": [], "meta": {}})])
async def test_unexpected_responses_do_not_prove_connection(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "get_current_company"}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("bad", ["https://app.companycam.com/token", "Bearer token", "key\r\nInjected: value"])
def test_refuses_url_header_and_control_characters(bad):
    with pytest.raises(ValidationError):
        native.CompanycamPersonalAccessToken(access_token=bad)


@pytest.mark.parametrize("bad", ["../users", "42?token=x", "42/other", "-1"])
def test_resource_ids_cannot_change_routes(bad):
    with pytest.raises(ValidationError):
        native.GetProject(project_id=bad)


def test_create_project_requires_the_contract_address_fields():
    with pytest.raises(ValidationError):
        native.CreateProject(name="Missing address")


def test_connection_read_needs_only_the_credential():
    assert native.CompanycamNode.connection_evidence.identity_operation == "get_current_company"
    assert node({"operation": "get_current_company"}).config.config.operation == "get_current_company"
