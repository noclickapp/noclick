"""Mattermost requests exercised through native discovery, without an account."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import mattermost_node as native
from nodes.core.registry import NodeFactory

A, B, C = "a" * 26, "b" * 26, "c" * 26
TOKEN = "synthetic-mattermost-token"
CREDS = {"credential_type": "mattermost_token", "server_url": "https://chat.example.com", "access_token": TOKEN}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, credentials=None):
    return NodeFactory.create_node(node_id="mattermost-fixture", node_type="automation-mattermost",
        node_data={"config": config, "credentials": CREDS if credentials is None else credentials})

def transport(monkeypatch, body, status=200, **headers):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests

# Expected wire requests are independent of the implementation's route table.
CASES = [
    ("get_current_user", {}, "GET", "/users/me", None, {}, "user"),
    ("get_user", {"user_id": A}, "GET", "/users/" + A, None, {}, "user"),
    ("get_user_by_username", {"username": "casey"}, "GET", "/users/username/casey", None, {}, "user"),
    ("list_my_teams", {}, "GET", "/users/me/teams", None, {}, "teams"),
    ("list_public_channels", {"team_id": A, "page": 2, "per_page": 5}, "GET", "/teams/" + A + "/channels", None, {"page": "2", "per_page": "5"}, "channels"),
    ("list_my_channels", {"team_id": A}, "GET", "/users/me/teams/" + A + "/channels", None, {}, "channels"),
    ("get_channel", {"channel_id": A}, "GET", "/channels/" + A, None, {}, "channel"),
    ("create_channel", {"team_id": A, "name": "ops-team", "display_name": "Ops", "type": "P", "header": "# Hello"}, "POST", "/channels", {"team_id": A, "name": "ops-team", "display_name": "Ops", "type": "P", "header": "# Hello"}, {}, "channel"),
    ("update_channel", {"channel_id": A, "purpose": "Automation"}, "PUT", "/channels/" + A + "/patch", {"purpose": "Automation"}, {}, "channel"),
    ("create_direct_channel", {"first_user_id": A, "second_user_id": B}, "POST", "/channels/direct", [A, B], {}, "channel"),
    ("list_channel_members", {"channel_id": A}, "GET", "/channels/" + A + "/members", None, {"page": "0", "per_page": "60"}, "members"),
    ("add_channel_member", {"channel_id": A, "user_id": B}, "POST", "/channels/" + A + "/members", {"user_id": B}, {}, "member"),
    ("remove_channel_member", {"channel_id": A, "user_id": B}, "DELETE", "/channels/" + A + "/members/" + B, None, {}, "ok"),
    ("list_posts", {"channel_id": A}, "GET", "/channels/" + A + "/posts", None, {"page": "0", "per_page": "60"}, "posts"),
    ("create_post", {"channel_id": A, "message": "Hello **team**", "root_id": B, "file_ids": [C]}, "POST", "/posts", {"channel_id": A, "message": "Hello **team**", "root_id": B, "file_ids": [C]}, {}, "post"),
    ("get_post", {"post_id": A}, "GET", "/posts/" + A, None, {}, "post"),
    ("update_post", {"post_id": A, "message": "Revised"}, "PUT", "/posts/" + A + "/patch", {"message": "Revised"}, {}, "post"),
    ("delete_post", {"post_id": A}, "DELETE", "/posts/" + A, None, {}, "ok"),
    ("get_thread", {"post_id": A, "from_post": B, "direction": "down"}, "GET", "/posts/" + A + "/thread", None, {"perPage": "60", "fromPost": B, "direction": "down"}, "posts"),
    ("search_posts", {"team_id": A, "terms": "in:town-square release"}, "POST", "/teams/" + A + "/posts/search", {"terms": "in:town-square release", "is_or_search": False, "page": 0, "per_page": 60}, {}, "posts"),
    ("add_reaction", {"user_id": A, "post_id": B, "emoji_name": "+1"}, "POST", "/reactions", {"user_id": A, "post_id": B, "emoji_name": "+1"}, {}, "reaction"),
    ("remove_reaction", {"user_id": A, "post_id": B, "emoji_name": "+1"}, "DELETE", "/users/" + A + "/posts/" + B + "/reactions/+1", None, {}, "ok"),
    ("list_reactions", {"post_id": A}, "GET", "/posts/" + A + "/reactions", None, {}, "reactions"),
    ("pin_post", {"post_id": A}, "POST", "/posts/" + A + "/pin", None, {}, "ok"),
    ("unpin_post", {"post_id": A}, "POST", "/posts/" + A + "/unpin", None, {}, "ok"),
]
FIXTURES = json.loads((Path(__file__).parent / "fixtures/mattermost/responses.json").read_text())

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body,params,fixture", CASES, ids=[c[0] for c in CASES])
async def test_mattermost_exact_contract_request(monkeypatch, operation, config, method, path, body, params, fixture):
    requests = transport(monkeypatch, FIXTURES[fixture], 201 if operation in {"create_post", "create_channel", "create_direct_channel", "add_reaction", "add_channel_member"} else 200)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success" and result["data"] == FIXTURES[fixture]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v4" + path
    assert request.url.host == "chat.example.com"
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body

@pytest.mark.asyncio
async def test_mattermost_connection_identity_and_subpath(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["user"])
    result = await node({"operation": "get_current_user"}, {**CREDS, "server_url": " https://Chat.example.com/mattermost/ "}).execute({})
    assert requests[0].url.path == "/mattermost/api/v4/users/me"
    assert result["data"]["username"] == "casey"
    assert native.MattermostNode.connection_evidence.identity_operation == "get_current_user"

@pytest.mark.parametrize("field,value", [
    ("server_url", "http://chat.example.com"), ("server_url", "https://u:p@chat.example.com"),
    ("server_url", "https://chat.example.com/path?token=x"), ("server_url", "https://chat.example.com/#x"),
    ("server_url", "https://chat.example.com/../other"), ("server_url", "https://chat.example.com/api/v4"),
    ("access_token", "Bearer abc"), ("access_token", "<token>"), ("access_token", "https://example.com"),
    ("access_token", "abc\nheader"), ("access_token", "key\u00e9"),
])
def test_mattermost_credential_rejects_unsafe_paste(field, value):
    with pytest.raises(ValidationError):
        native.MattermostTokenCredential.model_validate({**CREDS, field: value})

def test_mattermost_manual_default_and_invalid_configs():
    credential = native.MattermostTokenCredential(server_url=CREDS["server_url"], access_token=" " + TOKEN + "\n")
    assert credential.credential_type == "mattermost_token" and credential.access_token == TOKEN
    for config in [
        {"operation": "get_post", "post_id": "../bad"},
        {"operation": "list_posts", "channel_id": A, "per_page": 201},
        {"operation": "update_channel", "channel_id": A},
    ]:
        with pytest.raises(ValueError):
            node(config)

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_mattermost_rejection_is_not_success_and_never_retries(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Denied " + TOKEN}, status, location="https://other.example.com")
    result = await node({"operation": "create_post", "channel_id": A, "message": "Hi"}).execute({})
    assert len(requests) == 1 and result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Denied [redacted]" and TOKEN not in str(result)
    if status == 500:
        assert result["write_outcome"] == "unknown"

@pytest.mark.asyncio
async def test_mattermost_sensitive_response_and_single_page(monkeypatch):
    transport(monkeypatch, {**FIXTURES["user"], "auth_data": "private", "password": "hidden", "props": {"echo": TOKEN}})
    result = await node({"operation": "get_current_user"}).execute({})
    assert "auth_data" not in result["data"] and "password" not in result["data"] and TOKEN not in str(result)
    transport(monkeypatch, FIXTURES["channels"])
    result = await node({"operation": "list_public_channels", "team_id": A, "per_page": 1}).execute({})
    assert result["single_page"] and result["next_page"] == 1
    transport(monkeypatch, [])
    result = await node({"operation": "list_public_channels", "team_id": A, "page": 1}).execute({})
    assert result["next_page"] is None and result["data"] == []

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, [], {"status": "error"}, {"id": A}])
async def test_mattermost_invalid_identity_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "get_current_user"}).execute({})

@pytest.mark.asyncio
async def test_mattermost_network_failure_hides_url_and_token(monkeypatch):
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout(TOKEN + str(request.url))
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fail), **kw))
    with pytest.raises(ValueError, match="outcome may be unknown") as error:
        await node({"operation": "create_post", "channel_id": A, "message": "Hi"}).execute({})
    assert len(calls) == 1 and TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_mattermost_self_dm_and_documented_lowercase_ok(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["channel"], 201)
    await node({"operation": "create_direct_channel", "first_user_id": A, "second_user_id": A}).execute({})
    assert json.loads(requests[0].content) == [A, A]
    transport(monkeypatch, {"status": "ok"})
    result = await node({"operation": "delete_post", "post_id": A}).execute({})
    assert result["status"] == "success"
