"""JumpCloud request boundaries, regional auth, pagination and rejection tests."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError
from nodes import jumpcloud_node as native
from nodes.core.registry import NodeFactory

TOKEN = "jumpcloud-test-secret"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="jumpcloud-test", node_type="automation-jumpcloud", node_data={
        "config": config, "credentials": {"credential_type": "jumpcloud_api_key", "api_key": TOKEN, **credential}})


def transport(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("region,host", [("us", "console.jumpcloud.com"), ("eu", "console.eu.jumpcloud.com"), ("in", "console.in.jumpcloud.com")])
async def test_organization_evidence_uses_documented_region(monkeypatch, region, host):
    body = {"results": [{"_id": "org1", "displayName": "Acme"}], "totalCount": 1}
    calls = transport(monkeypatch, body)
    result = await node({"operation": "list_organizations"}, region=region).execute({})
    assert result["items"] == body["results"]
    assert result["has_more"] is False
    assert native.JumpcloudNode.connection_evidence.operation == "list_organizations"
    assert len(calls) == 1
    assert calls[0].url.host == host
    assert calls[0].url.path == "/api/organizations"
    assert calls[0].headers["x-api-key"] == TOKEN
    assert "Authorization" not in calls[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,fields,expected", [
    ("create_user", "/api/systemusers", {"username": "jsmith", "email": "jsmith@example.com", "firstname": "John"}, {"username": "jsmith", "email": "jsmith@example.com", "firstname": "John"}),
    ("update_user", "/api/systemusers/user1", {"user_id": "user1", "department": "Engineering"}, {"department": "Engineering"}),
    ("update_system", "/api/systems/device1", {"system_id": "device1", "displayName": "Laptop"}, {"displayName": "Laptop"}),
    ("create_user_group", "/api/v2/usergroups", {"name": "Engineering"}, {"name": "Engineering"}),
    ("create_system_group", "/api/v2/systemgroups", {"name": "Laptops", "description": "Managed devices"}, {"name": "Laptops", "description": "Managed devices"}),
])
async def test_writes_send_only_declared_fields(monkeypatch, operation, path, fields, expected):
    calls = transport(monkeypatch, {"id": "created"}, 201 if operation.startswith("create_") and "group" in operation else 200)
    result = await node({"operation": operation, **fields}, organization_id="org1").execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == ("PUT" if operation.startswith("update_") else "POST")
    assert request.url.path == path
    assert request.headers["x-org-id"] == "org1"
    assert json.loads(request.content) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,member_type", [("user", "user"), ("system", "system")])
@pytest.mark.parametrize("action", ["add", "remove"])
async def test_membership_uses_graph_operation_and_accepts_empty_ack(monkeypatch, kind, member_type, action):
    calls = transport(monkeypatch, None, 204)
    result = await node({"operation": f"manage_{kind}_group_membership", "group_id": "g1", "member_id": "m1", "op": action}).execute({})
    assert result["acknowledged"] is True
    assert len(calls) == 1
    assert calls[0].url.path == f"/api/v2/{kind}groups/g1/members"
    assert json.loads(calls[0].content) == {"op": action, "type": member_type, "id": "m1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("delete_user", "/api/systemusers/u1"), ("delete_system", "/api/systems/u1"), ("delete_user_group", "/api/v2/usergroups/u1"), ("delete_system_group", "/api/v2/systemgroups/u1")])
async def test_delete_maps_to_single_provider_operation(monkeypatch, operation, path):
    calls = transport(monkeypatch, {"id": "u1"})
    key = "group_id" if "group" in operation else "system_id" if "system" in operation else "user_id"
    assert (await node({"operation": operation, key: "u1"}).execute({}))["status"] == "success"
    assert len(calls) == 1 and calls[0].method == "DELETE"
    assert calls[0].url.path == path


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("list_users", {"results": [{"_id": "u"}], "totalCount": 4}), ("list_user_groups", [{"id": "g"}])])
async def test_v1_envelopes_and_v2_arrays_page_explicitly(monkeypatch, operation, body):
    calls = transport(monkeypatch, body)
    result = await node({"operation": operation, "limit": 1, "skip": 1}).execute({})
    assert result["next_skip"] == 2 and result["has_more"]
    assert len(calls) == 1 and dict(calls[0].url.params) == {"limit": "1", "skip": "1"}


@pytest.mark.asyncio
async def test_rejected_key_preserves_provider_text_and_redacts_secret(monkeypatch):
    transport(monkeypatch, {"message": "Unauthorized " + TOKEN}, 401)
    result = await node({"operation": "list_users"}).execute({})
    assert result["status"] == "error" and result["status_code"] == 401
    assert "Unauthorized" in result["error"] and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_malformed_success_is_not_evidence(monkeypatch):
    transport(monkeypatch, {"results": "wrong"})
    with pytest.raises(ValueError, match="collection"):
        await node({"operation": "list_organizations"}).execute({})


@pytest.mark.asyncio
async def test_empty_update_refused_before_network(monkeypatch):
    calls = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_user", "user_id": "u1"}).execute({})
    assert not calls


@pytest.mark.parametrize("value", ["../escape", "a/b", "a?b", "https://evil.example", "a#b"])
def test_path_injection_refused(value):
    with pytest.raises(ValidationError):
        native.GetUser(user_id=value)


@pytest.mark.parametrize("value", ["https://example.com", "<token>", "Bearer key", "key\nheader"])
def test_bad_manual_key_refused(value):
    with pytest.raises(ValidationError):
        native.JumpcloudAPIKeyCredential(api_key=value)


def test_displayname_is_only_in_documented_create_body():
    assert native.CreateUser(username="jsmith", email="jsmith@example.com", displayname="John").displayname == "John"
    with pytest.raises(ValidationError):
        native.UpdateUser(user_id="u1", displayname="John")
