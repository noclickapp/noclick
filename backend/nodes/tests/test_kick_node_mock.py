"""Kick request serialization, response preservation and credential behavior."""
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from nodes.kick_node import KickNode, KickNodeConfig, KickOAuthCredential
from nodes.oauth.kick_oauth import OAUTH_PROVIDER

REWARD = "01KEWZ2RKYZZFGD154K50Y3F8D"
OTHER = "01KEWZ2YC27070XWMHKFJR6C87"


def node(operation, **fields):
    return KickNode(node_id="kick-test", node_type="automation-kick", node_data={}, user_id="test-user",
        config=KickNodeConfig(config={"operation": operation, **fields},
            credentials=KickOAuthCredential(access_token="test-kick-token")))


@pytest.fixture
def wire():
    seen, responses = [], []
    original = httpx.AsyncClient
    def respond(request):
        seen.append(request)
        return responses.pop(0) if responses else httpx.Response(200, json={"data": [], "message": "OK"})
    with patch("nodes.kick_node.httpx.AsyncClient", side_effect=lambda **kw: original(transport=httpx.MockTransport(respond), **kw)):
        yield seen, responses


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,body", [
    ("get_users", {}, "GET", "/public/v1/users", None),
    ("search_categories", {"q": "Minecraft", "page": 2}, "GET", "/public/v1/categories", None),
    ("get_category", {"category_id": 123}, "GET", "/public/v1/categories/123", None),
    ("get_channels", {"slug": ["alice", "bob"]}, "GET", "/public/v1/channels", None),
    ("update_channel", {"stream_title": "My first stream"}, "PATCH", "/public/v1/channels", {"stream_title": "My first stream"}),
    ("list_rewards", {}, "GET", "/public/v1/channels/rewards", None),
    ("create_reward", {"cost": 100, "title": "Song Request"}, "POST", "/public/v1/channels/rewards",
        {"cost": 100, "title": "Song Request", "background_color": "#00e701", "is_enabled": True, "is_user_input_required": False, "should_redemptions_skip_request_queue": False}),
    ("update_reward", {"id": REWARD, "is_enabled": False}, "PATCH", "/public/v1/channels/rewards/" + REWARD, {"is_enabled": False}),
    ("delete_reward", {"id": REWARD}, "DELETE", "/public/v1/channels/rewards/" + REWARD, None),
    ("list_redemptions", {"status": "pending", "cursor": "bmV4dA=="}, "GET", "/public/v1/channels/rewards/redemptions", None),
    ("accept_redemptions", {"ids": [REWARD, OTHER]}, "POST", "/public/v1/channels/rewards/redemptions/accept", {"ids": [REWARD, OTHER]}),
    ("reject_redemptions", {"ids": [REWARD]}, "POST", "/public/v1/channels/rewards/redemptions/reject", {"ids": [REWARD]}),
    ("send_message", {"type": "user", "broadcaster_user_id": 123, "content": "Pog"}, "POST", "/public/v1/chat", {"type": "user", "broadcaster_user_id": 123, "content": "Pog"}),
    ("delete_message", {"message_id": "828f83bb-e391-4c78-9e91-af35a172840e"}, "DELETE", "/public/v1/chat/828f83bb-e391-4c78-9e91-af35a172840e", None),
    ("list_livestreams", {"category_id": [1, 2], "language_code": ["en", "fr"], "cursor": "next"}, "GET", "/public/v2/livestreams", None),
    ("get_livestream_stats", {}, "GET", "/public/v1/livestreams/stats", None),
    ("list_user_livestreams", {"user_id": [123, 333]}, "GET", "/public/v1/users/livestreams", None),
    ("ban_user", {"broadcaster_user_id": 123, "user_id": 333, "duration": 10}, "POST", "/public/v1/moderation/bans", {"broadcaster_user_id": 123, "user_id": 333, "duration": 10}),
    ("unban_user", {"broadcaster_user_id": 123, "user_id": 333}, "DELETE", "/public/v1/moderation/bans", {"broadcaster_user_id": 123, "user_id": 333}),
    ("get_leaderboard", {"top": 5}, "GET", "/public/v1/kicks/leaderboard", None),
])
async def test_documented_requests(wire, operation, fields, method, path, body):
    seen, _ = wire
    result = await node(operation, **fields).execute({})
    assert result["status"] == "success"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.kick.com"
    assert request.headers["authorization"] == "Bearer test-kick-token"
    assert (json.loads(request.content) if request.content else None) == body
    if operation == "get_users":
        assert not request.url.query  # no IDs returns the authorized user
    if operation == "search_categories":
        assert dict(request.url.params) == {"q": "Minecraft", "page": "2"}
    if operation == "get_channels":
        assert request.url.params.get_list("slug") == ["alice", "bob"]
    if operation == "list_user_livestreams":
        assert request.url.params.get_list("user_id") == ["123", "333"]
    if operation == "list_livestreams":
        assert request.url.params.get_list("category_id") == ["1", "2"]
        assert request.url.params.get_list("language_code") == ["en", "fr"]
        assert request.url.params["cursor"] == "next" and request.url.params["limit"] == "100"
    if operation == "list_redemptions":
        assert dict(request.url.params) == {"status": "pending", "cursor": "bmV4dA=="}
    if operation == "get_leaderboard":
        assert request.url.params["top"] == "5"


@pytest.mark.asyncio
async def test_preserves_documented_identity_and_pagination(wire):
    _, responses = wire
    identity = json.loads((Path(__file__).parent / "fixtures/kick/user.json").read_text())
    responses.append(httpx.Response(200, json=identity))
    result = await node("get_users").execute({})
    assert result["data"][0]["name"] == "John Doe" and result["data"][0]["user_id"] == 123
    responses.append(httpx.Response(200, json={"data": [{"id": REWARD}], "pagination": {"next_cursor": "next-page"}}))
    result = await node("list_redemptions").execute({})
    assert result["pagination"]["next_cursor"] == "next-page"
    assert result["data"] == [{"id": REWARD}]


@pytest.mark.parametrize("operation,fields", [
    ("update_channel", {}), ("update_reward", {"id": REWARD}),
    ("get_channels", {"slug": ["alice"], "broadcaster_user_id": [123]}),
    ("list_redemptions", {"id": [REWARD], "status": "pending"}),
    ("accept_redemptions", {"ids": [REWARD, REWARD]}),
    ("reject_redemptions", {"ids": ["../unsafe"]}),
    ("send_message", {"content": "Pog", "type": "user"}),
    ("create_reward", {"cost": 0, "title": "Song Request"}),
    ("ban_user", {"broadcaster_user_id": 123, "user_id": 333, "duration": 10081}),
    ("get_leaderboard", {"top": 101}),
    ("list_user_livestreams", {"user_id": []}),
    ("get_users", {"unexpected": "must be refused"}),
])
def test_invalid_configs_refused(operation, fields):
    with pytest.raises(ValueError):
        node(operation, **fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Unauthorized"}), (403, {"message": "Forbidden"}), (429, {"message": "Too many requests"}), (500, {"message": "Internal error"}), (302, {})])
async def test_http_failures_are_not_success(wire, status, body):
    seen, responses = wire
    responses.append(httpx.Response(status, json=body))
    with pytest.raises(httpx.HTTPStatusError):
        await node("get_users").execute({})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_empty_delete_response_and_error_envelope(wire):
    _, responses = wire
    responses.append(httpx.Response(204))
    assert (await node("delete_reward", id=REWARD).execute({}))["status"] == "success"
    responses.append(httpx.Response(200, json={"error": "not permitted"}))
    with pytest.raises(ValueError, match="not permitted"):
        await node("get_users").execute({})
    responses.append(httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ValueError):
        await node("get_users").execute({})


@pytest.mark.asyncio
async def test_execute_adopts_refreshed_token(wire, monkeypatch):
    import nodes.kick_node as module
    calls = []
    async def refresh(**kwargs):
        calls.append(kwargs)
        kwargs["credential"].update(access_token="new-token", refresh_token="new-refresh", expires_at="future")
    monkeypatch.setattr(module, "ensure_fresh_oauth_token", refresh)
    instance = node("get_users")
    await instance.execute({})
    assert calls[0]["provider"] == "kick"
    assert wire[0][0].headers["authorization"] == "Bearer new-token"
    assert instance.config.credentials.refresh_token == "new-refresh"


def test_oauth_and_manual_credential_contract():
    cred = KickOAuthCredential(access_token="manual-token")
    assert cred.credential_type == "kick_oauth" and cred.refresh_token is None
    assert OAUTH_PROVIDER.pkce and OAUTH_PROVIDER.token_auth == "body"
    assert OAUTH_PROVIDER.name_field == "data.0.name"
    assert OAUTH_PROVIDER.identity_url == "https://api.kick.com/public/v1/users"
    assert set(KickOAuthCredential.model_json_schema()["x-oauth-scopes"]) == set(KickNode.scope_registry.declared_scopes())
