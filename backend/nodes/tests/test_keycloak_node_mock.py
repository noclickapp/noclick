"""Keycloak wire and polling checks. All accounts, tokens and rows are synthetic.

The independent request expectations follow the published Admin REST contract.
Conformance separately checks the pinned provider document and schema witnesses.
"""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import keycloak_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope
from utils import ssrf

TOKEN = "synthetic-keycloak-token-42"
AUTH = {"credential_type": "keycloak_token", "instance_url": "https://sso.example.com", "realm": "example", "access_token": TOKEN}
USER = {"id": "user-1", "username": "alice", "createdTimestamp": 1700000000000, "enabled": True}
ROLE = {"id": "role-1", "name": "member"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    def send(request):
        requests.append(request)
        assert request.url.host == "sso.example.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        return replies.pop(0)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(**kwargs, transport=httpx.MockTransport(send))
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, replies


def node(operation, config=None, auth=None):
    return NodeFactory.create_node(node_id="keycloak-test", node_type="automation-keycloak", node_data={
        "config": {"operation": operation, **(config or {})}, "credentials": AUTH if auth is None else auth})


CASES = [
    ("list_realms", {}, "GET", "", None, 200, True),
    ("get_realm", {}, "GET", "/example", None, 200, False),
    ("list_users", {}, "GET", "/example/users", None, 200, True),
    ("get_user", {"user_id": "user-1"}, "GET", "/example/users/user-1", None, 200, False),
    ("create_user", {"username": "alice", "first_name": "Alice", "enabled": False}, "POST", "/example/users", {"username": "alice", "firstName": "Alice", "enabled": False}, 201, False),
    ("update_user", {"user_id": "user-1", "email_verified": False, "attributes": {}}, "PUT", "/example/users/user-1", {"emailVerified": False, "attributes": {}}, 204, False),
    ("delete_user", {"user_id": "user-1"}, "DELETE", "/example/users/user-1", None, 204, False),
    ("list_user_groups", {"user_id": "user-1"}, "GET", "/example/users/user-1/groups", None, 200, True),
    ("add_user_to_group", {"user_id": "user-1", "group_id": "group-1"}, "PUT", "/example/users/user-1/groups/group-1", None, 204, False),
    ("remove_user_from_group", {"user_id": "user-1", "group_id": "group-1"}, "DELETE", "/example/users/user-1/groups/group-1", None, 204, False),
    ("list_user_realm_roles", {"user_id": "user-1"}, "GET", "/example/users/user-1/role-mappings/realm", None, 200, True),
    ("add_user_realm_roles", {"user_id": "user-1", "roles": [ROLE]}, "POST", "/example/users/user-1/role-mappings/realm", [ROLE], 204, False),
    ("remove_user_realm_roles", {"user_id": "user-1", "roles": [ROLE]}, "DELETE", "/example/users/user-1/role-mappings/realm", [ROLE], 204, False),
    ("list_groups", {}, "GET", "/example/groups", None, 200, True),
    ("get_group", {"group_id": "group-1"}, "GET", "/example/groups/group-1", None, 200, False),
    ("create_group", {"name": "Engineering"}, "POST", "/example/groups", {"name": "Engineering"}, 201, False),
    ("update_group", {"group_id": "group-1", "name": "Support", "attributes": {}}, "PUT", "/example/groups/group-1", {"name": "Support", "attributes": {}}, 204, False),
    ("delete_group", {"group_id": "group-1"}, "DELETE", "/example/groups/group-1", None, 204, False),
    ("list_clients", {}, "GET", "/example/clients", None, 200, True),
    ("get_client", {"client_uuid": "client-1"}, "GET", "/example/clients/client-1", None, 200, False),
    ("list_realm_roles", {}, "GET", "/example/roles", None, 200, True),
    ("list_user_sessions", {"user_id": "user-1"}, "GET", "/example/users/user-1/sessions", None, 200, True),
    ("logout_user", {"user_id": "user-1"}, "POST", "/example/users/user-1/logout", None, 204, False),
    ("list_events", {}, "GET", "/example/events", None, 200, True),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body,code,is_list", CASES)
async def test_keycloak_one_contract_operation(transport, operation, config, method, path, body, code, is_list):
    requests, replies = transport
    data = [USER] if is_list else USER
    replies.append(httpx.Response(code, json=data) if code == 200 else httpx.Response(code))
    result = await node(operation, config).execute({})
    assert result["status"] == "success" and result["http_status"] == code
    assert len(requests) == 1 and not replies
    assert requests[0].method == method and requests[0].url.path == "/admin/realms" + path
    assert (json.loads(requests[0].content) if requests[0].content else None) == body
    if code in {201, 204}:
        assert result["acknowledged"] is True and "data" not in result


@pytest.mark.asyncio
async def test_keycloak_query_names_repeated_types_and_page(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json=[USER]))
    result = await node("list_users", {"created_after": "2026-01-01", "first": 3, "max": 1, "enabled": False, "exact": True}).execute({})
    assert dict(requests[0].url.params) == {"createdAfter": "2026-01-01", "first": "3", "max": "1", "enabled": "false", "exact": "true"}
    assert result["next_offset"] == 4 and result["has_more"] is True
    replies.append(httpx.Response(200, json=[]))
    await node("list_events", {"date_from": "1700000000000", "date_to": "2026-01-01", "type": ["LOGIN", "REGISTER"]}).execute({})
    assert requests[1].url.params.get_list("type") == ["LOGIN", "REGISTER"]
    assert requests[1].url.params["dateFrom"] == "1700000000000"
    replies.append(httpx.Response(200, json=[]))
    await node("list_clients", {"client_id": "my-app"}).execute({})
    assert requests[2].url.params["clientId"] == "my-app"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [302, 401, 403, 429, 500])
async def test_keycloak_rejection_no_redirect_or_retry(transport, code):
    requests, replies = transport
    replies.append(httpx.Response(code, json={"error": "denied " + TOKEN}, headers={"Location": "https://other.example/"}))
    with pytest.raises(ValueError, match=f"Keycloak API {code}") as exc:
        await node("create_user", {"username": "alice"}).execute({})
    assert TOKEN not in str(exc.value) and "denied" in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_keycloak_invalid_shape_and_response_redaction(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"id": "client-1", "secret": "client-secret", "registrationAccessToken": "reg-secret", "name": TOKEN}))
    result = await node("get_client", {"client_uuid": "client-1"}).execute({})
    assert result["data"] == {"id": "client-1", "name": "[redacted]"}
    replies.append(httpx.Response(200, text="not JSON", headers={"Content-Type": "text/html"}))
    with pytest.raises(ValueError, match="bounded JSON"):
        await node("get_realm").execute({})
    replies.append(httpx.Response(200, json={"items": []}))
    with pytest.raises(ValueError, match="response shape"):
        await node("list_users").execute({})


@pytest.mark.parametrize("key,value", [("instance_url", "http://sso.example.com"), ("instance_url", "https://sso.example.com/auth"), ("instance_url", "https://user:pass@sso.example.com"), ("realm", "../master"), ("realm", "x%2fy"), ("access_token", "Bearer token"), ("access_token", "token\r\nX: header")])
def test_keycloak_refuses_ambiguous_destination_or_token(key, value):
    with pytest.raises(ValidationError):
        native.KeycloakTokenCredential.model_validate({**AUTH, key: value})


def test_keycloak_manual_shape_and_required_write_fields():
    assert native.KeycloakTokenCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"}).credential_type == "keycloak_token"
    with pytest.raises(ValueError):
        node("get_user", {"user_id": "../elsewhere"}).config
    with pytest.raises(ValueError):
        node("update_user", {"user_id": "user-1"}).config
    with pytest.raises(ValueError):
        node("get_realm", auth={**AUTH, "credential_type": "other"}).config


@pytest.mark.asyncio
async def test_keycloak_poll_baseline_new_user_and_repoint(transport):
    requests, replies = transport
    n = node("on_new_user", {"created_after": "2026-01-01"})
    state = {}
    async def update(mutator, **kwargs):
        new, result = mutator(dict(state))
        if new is not None:
            state.clear(); state.update(new)
        return result
    n._update_node_state = update
    replies.append(httpx.Response(200, json=[USER]))
    assert (await n.execute({}))["users"] == []
    assert n.trigger_produced_no_event({})
    bob = {**USER, "id": "user-2", "username": "bob"}
    replies.append(httpx.Response(200, json=[USER, bob]))
    output = await n.execute({})
    assert output["users"] == [bob] and n.trigger_emitted_event(output)
    event = native.KeycloakNode.resolve_agent_event(output)
    assert "bob" in event["text"] and "user-2" in event["text"] and "example" in event["text"]
    replies.append(httpx.Response(200, json=[USER, bob]))
    assert (await n.execute({}))["new_user_count"] == 0
    assert all(r.url.params["createdAfter"] == "2026-01-01" for r in requests)
    a = {"operation": "on_new_user", "created_after": "2026-01-01"}
    assert poll_scope(native.KeycloakNode, a) == poll_scope(native.KeycloakNode, {**a, "label": "cosmetic"})
    assert poll_scope(native.KeycloakNode, a) != poll_scope(native.KeycloakNode, {**a, "created_after": "2026-02-01"})
    n2 = node("on_new_user", {"created_after": "2026-02-01"}); n2._update_node_state = update
    replies.append(httpx.Response(200, json=[bob]))
    assert (await n2.execute({}))["new_user_count"] == 0


@pytest.mark.asyncio
async def test_keycloak_poll_paginates_before_dedup_and_refuses_overflow(monkeypatch):
    n = node("on_new_user")
    batches = [[{**USER, "id": str(i)} for i in range(100)], [{**USER, "id": "last"}]]
    request = AsyncMock(side_effect=[{"data": batch} for batch in batches])
    monkeypatch.setattr(n, "_request", request)
    seen = AsyncMock(side_effect=lambda rows, key: rows)
    monkeypatch.setattr(n, "_filter_unseen", seen)
    assert (await n.execute({}))["new_user_count"] == 101
    assert request.call_args_list[1].kwargs["params"]["first"] == 100
    seen.assert_awaited_once()
    monkeypatch.setattr(n, "_request", AsyncMock(return_value={"data": batches[0]}))
    seen.reset_mock()
    with pytest.raises(ValueError, match="5,000"):
        await n.execute({})
    seen.assert_not_awaited()


@pytest.mark.parametrize("field", ["user_id", "group_id"])
def test_keycloak_membership_validates_both_resource_ids(field):
    config = {"user_id": "user-1", "group_id": "group-1", field: "../escape"}
    with pytest.raises(ValueError):
        node("add_user_to_group", config).config


@pytest.mark.asyncio
async def test_keycloak_transport_failure_does_not_retry(monkeypatch):
    request = AsyncMock(side_effect=httpx.ConnectError("network unavailable"))
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        request = None
    Client.request = request
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: Client())
    result = await node("create_user", {"username": "alice"}).execute({})
    assert result["status"] == "error" and "unknown" in result["error"]
    request.assert_awaited_once()
