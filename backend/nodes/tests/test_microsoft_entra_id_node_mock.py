"""Exercise directory requests, documented response shapes and failure handling.

Transport mocks keep OAuth tokens and mutations off the network.
"""
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.microsoft_entra_id_node import (
    CONFIG_MODELS, OPERATIONS, EntraNodeConfig, EntraOAuthCredential, MicrosoftEntraIdNode,
)

CREDENTIAL = {
    "credential_type": "microsoft_oauth", "access_token": "test-access-token",
    "refresh_token": "test-refresh-token", "expires_at": "2099-01-01T00:00:00Z",
    "email": "admin@contoso.com",
}
VALUES = {
    "user_id": "adelev@contoso.com", "group_id": "00000000-0000-0000-0000-000000000001",
    "member_id": "00000000-0000-0000-0000-000000000002",
    "display_name": "Adele Vance", "mail_nickname": "adelev",
    "user_principal_name": "adelev@contoso.com", "password": "Test-Password-123!",
    "display_name_update": "Updated Name", "description_update": "Updated description",
}


def node(operation, **values):
    spec = OPERATIONS[operation]
    data = {key: VALUES[key] for key in spec.fields if key in VALUES}
    data.update(values)
    return MicrosoftEntraIdNode(node_id="entra-test", node_type="automation-microsoft-entra-id",
        node_data={}, config=EntraNodeConfig(config=CONFIG_MODELS[operation](**data),
            credentials=EntraOAuthCredential(**CREDENTIAL)), sio=None, sid=None, workflow_id="qa")


@pytest.fixture
def transport(monkeypatch):
    from nodes.core import oauth_refresh
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", AsyncMock(return_value="test-access-token"))
    requests = []
    real = httpx.AsyncClient

    def install(respond):
        def handle(request):
            requests.append(request)
            return respond(request)
        def client(**kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
            return real(transport=httpx.MockTransport(handle))
        monkeypatch.setattr("nodes.microsoft_entra_id_node.httpx.AsyncClient", client)
        return requests
    return install


ROUTES = {
    "get_me": ("GET", "/me"),
    "list_users": ("GET", "/users"), "get_user": ("GET", "/users/adelev%40contoso.com"),
    "create_user": ("POST", "/users"), "update_user": ("PATCH", "/users/adelev%40contoso.com"),
    "delete_user": ("DELETE", "/users/adelev%40contoso.com"),
    "list_groups": ("GET", "/groups"), "get_group": ("GET", "/groups/" + VALUES["group_id"]),
    "create_group": ("POST", "/groups"), "update_group": ("PATCH", "/groups/" + VALUES["group_id"]),
    "delete_group": ("DELETE", "/groups/" + VALUES["group_id"]),
    "list_group_members": ("GET", "/groups/" + VALUES["group_id"] + "/members"),
    "add_group_user": ("POST", "/groups/" + VALUES["group_id"] + "/members/$ref"),
    "remove_group_member": ("DELETE", "/groups/" + VALUES["group_id"] + "/members/" + VALUES["member_id"] + "/$ref"),
    "list_user_memberships": ("GET", "/users/adelev%40contoso.com/memberOf"),
    "list_applications": ("GET", "/applications"),
    "list_service_principals": ("GET", "/servicePrincipals"),
    "list_organizations": ("GET", "/organization"), "list_subscribed_skus": ("GET", "/subscribedSkus"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ROUTES)
async def test_directory_routes_and_auth(transport, operation):
    import json
    method, path = ROUTES[operation]
    def respond(req):
        if method in {"DELETE", "PATCH"} or operation == "add_group_user":
            return httpx.Response(204)
        data = {"value": [{"id": "id", "displayName": "Adele Vance"}]} if OPERATIONS[operation].collection else {"id": "id", "displayName": "Adele Vance"}
        return httpx.Response(201 if method == "POST" else 200, json=data)
    requests = transport(respond)
    out = await node(operation).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    assert req.url.host == "graph.microsoft.com"
    assert req.url.raw_path.decode().split("?")[0] == "/v1.0" + path
    assert req.headers["Authorization"] == "Bearer test-access-token"
    assert out["status"] == "success"
    if operation == "create_user":
        body = json.loads(req.content)
        assert body["passwordProfile"] == {"forceChangePasswordNextSignIn": True, "password": VALUES["password"]}
        assert body["userPrincipalName"] == VALUES["user_principal_name"]
        assert body["accountEnabled"] is True
        assert "password" not in str(out)
    if operation == "create_group":
        assert json.loads(req.content) == {"displayName": "Adele Vance", "mailNickname": "adelev", "mailEnabled": False, "securityEnabled": True, "groupTypes": []}
    if operation == "add_group_user":
        assert json.loads(req.content) == {"@odata.id": "https://graph.microsoft.com/v1.0/users/adelev%40contoso.com"}


@pytest.mark.asyncio
async def test_update_sends_false_and_only_chosen_properties(transport):
    import json
    requests = transport(lambda req: httpx.Response(204))
    await node("update_user", display_name_update=None, account_enabled_update=False).execute({})
    assert json.loads(requests[0].content) == {"accountEnabled": False}


@pytest.mark.parametrize("operation", ["update_user", "update_group"])
def test_empty_update_is_rejected(operation):
    with pytest.raises(ValidationError, match="Supply"):
        CONFIG_MODELS[operation](**{"user_id" if operation == "update_user" else "group_id": "id"})


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://evil.example/v1.0/users", "https://graph.microsoft.com.evil.example/v1.0/users",
    "https://user@graph.microsoft.com/v1.0/users", "https://graph.microsoft.com:444/v1.0/users",
    "https://graph.microsoft.com/v1.0/groups", "http://graph.microsoft.com/v1.0/users",
    "https://graph.microsoft.com/v1.0/users#fragment",
])
async def test_continuation_cannot_retarget_request(transport, url):
    requests = transport(lambda req: pytest.fail("unexpected request"))
    with pytest.raises(ValueError, match="Next page link"):
        await node("list_users", next_link=url).execute({})
    assert requests == []


@pytest.mark.asyncio
async def test_continuation_is_preserved(transport):
    url = "https://graph.microsoft.com/v1.0/users?$skiptoken=opaque%2Btoken"
    requests = transport(lambda req: httpx.Response(200, json={"value": [], "@odata.nextLink": url}))
    out = await node("list_users", next_link=url).execute({})
    assert str(requests[0].url) == url
    assert out == {"status": "success", "operation": "list_users", "items": [], "count": 0, "next_link": url}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500])
async def test_provider_failures_are_not_success(transport, status):
    transport(lambda req: httpx.Response(status, json={"error": {"code": "Denied", "message": "Provider rejection"}}))
    with pytest.raises(ValueError, match="Provider rejection"):
        await node("get_me").execute({})


@pytest.mark.asyncio
async def test_bad_collection_is_not_empty_success(transport):
    transport(lambda req: httpx.Response(200, json={"unexpected": []}))
    with pytest.raises(ValueError, match="value collection"):
        await node("list_users").execute({})


def test_scopes_cover_every_operation_and_use_shared_signin():
    from nodes.scopes.microsoft_entra_id import ENTRA_SCOPES
    assert set(ENTRA_SCOPES._requirements) == set(OPERATIONS)
    schema = EntraOAuthCredential.model_json_schema()
    assert schema["x-oauth-provider"] == "microsoft"
    assert set(schema["x-oauth-scopes"]) == set(ENTRA_SCOPES.declared_scopes())
    assert MicrosoftEntraIdNode.connection_evidence.operation == "get_me"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,key", [
    ("get_me", "GET /me"), ("list_users", "GET /users"),
    ("get_user", "GET /users/{user-id}"), ("create_user", "POST /users"),
    ("list_groups", "GET /groups"), ("get_group", "GET /groups/{group-id}"),
    ("create_group", "POST /groups"), ("list_group_members", "GET /groups/{group-id}/members"),
    ("list_user_memberships", "GET /users/{user-id}/memberOf"),
    ("list_applications", "GET /applications"), ("list_service_principals", "GET /servicePrincipals"),
    ("list_organizations", "GET /organization"), ("list_subscribed_skus", "GET /subscribedSkus"),
])
async def test_parses_published_graph_examples(transport, operation, key):
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures/microsoft-entra-id/documented_responses.json").read_text())[key]
    transport(lambda req: httpx.Response(201 if operation.startswith("create_") else 200, json=fixture["body"]))
    out = await node(operation).execute({})
    if OPERATIONS[operation].collection:
        assert out["items"] == fixture["body"]["value"]
    else:
        assert out["data"] == fixture["body"]
