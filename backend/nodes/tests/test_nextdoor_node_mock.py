"""Exercise the actual Nextdoor node factory at the HTTP boundary."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import nextdoor_node as nd
from nodes.core.registry import NodeFactory
from nodes.oauth.nextdoor_oauth import OAUTH_PROVIDER

AUTH = {"credential_type": "nextdoor_oauth", "access_token": "nextdoor-fixture-token"}

CASES = [
    ("get_account", {}, "GET", "/me/", None),
    ("list_profiles", {}, "GET", "/me/profiles", None),
    ("list_posts", {}, "GET", "/post/", None),
    ("create_post", {"body_text": "Hello neighbours", "secure_profile_id": "business-1"}, "POST", "/post/create/", {"body_text": "Hello neighbours", "secure_profile_id": "business-1"}),
    ("create_listing", {"body_text": "Free chair", "fsf": {"title": "Chair", "description": "Wooden chair", "price": "0", "category": "Furniture", "image_attachments": ["https://example.com/chair.png"]}}, "POST", "/post/fsf/", None),
    ("set_listing_sold", {"classified_id": "listing-1", "sold": False}, "PUT", "/post/fsf/", {"classified_id": "listing-1", "sold": False}),
    ("create_comment", {"id": "post-1", "body_text": "Thanks", "parent_comment_id": "comment-1"}, "POST", "/comment/", {"id": "post-1", "body_text": "Thanks", "parent_comment_id": "comment-1"}),
    ("edit_comment", {"id": "comment-1", "body_text": "Updated"}, "PUT", "/comment/", {"id": "comment-1", "body_text": "Updated"}),
    ("delete_comment", {"id": "comment-1", "secure_profile_id": "business-1"}, "DELETE", "/comment/", None),
    ("edit_post", {"id": "post-1", "body_text": "Updated"}, "PUT", "/post/", {"id": "post-1", "body_text": "Updated"}),
    ("delete_post", {"id": "post-1"}, "DELETE", "/post/", None),
    ("list_agency_boundaries", {"after": "cursor-2", "show_geometries": False}, "GET", "/agency/boundary/", None),
    ("set_commenting", {"id": "post-1", "comment_status": False}, "POST", "/post/toggle_commenting/", {"id": "post-1", "comment_status": False}),
]


def node(operation, arguments=None, credential=None):
    return NodeFactory.create_node(node_id="nextdoor-test", node_type="automation-nextdoor", node_data={
        "config": {"operation": operation, **(arguments or {})}, "credentials": credential or AUTH})


@pytest.fixture
def wire(monkeypatch):
    calls, replies = [], []
    native = httpx.AsyncClient

    async def send(request):
        calls.append(request)
        assert request.url.host == "nextdoor.com"
        assert request.headers["authorization"] == "Bearer nextdoor-fixture-token"
        assert "nextdoor-fixture-token" not in str(request.url)
        status, payload = replies.pop(0) if replies else (200, {"result": "success"})
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(nd.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return calls, replies


@pytest.mark.parametrize("operation,arguments,method,path,body", CASES)
@pytest.mark.asyncio
async def test_every_operation_wire(wire, operation, arguments, method, path, body):
    calls, _ = wire
    result = await node(operation, arguments).execute({})
    assert result == {"status": "success", "operation": operation, "data": {"result": "success"}}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == "/external/api/partner/v1" + path
    if body is not None:
        assert json.loads(request.content) == body
    if operation == "create_listing":
        assert json.loads(request.content) == arguments
    if operation.startswith("delete_"):
        assert request.url.params["id"] == arguments["id"] and not request.content
    if operation == "list_agency_boundaries":
        assert dict(request.url.params) == {"show_geometries": "false", "enable_pagination": "true", "after": "cursor-2"}


@pytest.mark.asyncio
async def test_documented_account_and_array_responses(wire):
    _, replies = wire
    fixture = json.loads((Path(__file__).parent / "fixtures/nextdoor/responses.json").read_text())
    for operation, body in fixture.items():
        replies.append((200, body))
        assert (await node(operation).execute({}))["data"] == body


@pytest.mark.parametrize("status,body", [(401, {"message": "Token rejected"}), (403, {"message": "Insufficient scope"}), (429, {"message": "Rate limited"}), (302, {})])
@pytest.mark.asyncio
async def test_http_failures_are_not_success(wire, status, body):
    _, replies = wire
    replies.append((status, body))
    with pytest.raises(ValueError, match=f"Nextdoor HTTP {status}"):
        await node("get_account").execute({})


@pytest.mark.asyncio
async def test_provider_error_envelope(wire):
    _, replies = wire
    replies.append((200, {"error": "not authorized"}))
    with pytest.raises(ValueError, match="error response"):
        await node("get_account").execute({})


@pytest.mark.asyncio
async def test_redacts_error_token(wire):
    _, replies = wire
    replies.append((401, {"message": AUTH["access_token"]}))
    with pytest.raises(ValueError) as exc:
        await node("get_account").execute({})
    assert AUTH["access_token"] not in str(exc.value)


@pytest.mark.asyncio
async def test_refresh_uses_shared_seam(monkeypatch, wire):
    from nodes.core import oauth_refresh
    refresh = AsyncMock(return_value=AUTH["access_token"])
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", refresh)
    await node("get_account").execute({})
    assert refresh.await_args.kwargs["provider"] == "nextdoor"
    assert refresh.await_args.kwargs["credential"]["refresh_token"] == AUTH["access_token"]


@pytest.mark.asyncio
async def test_oauth_documented_access_token_refresh(monkeypatch):
    from nodes.core.oauth_provider import OAuthProviderSpec
    from nodes.core.oauth_provider import OAuthTokens
    original = AsyncMock(return_value=(OAuthTokens(access_token="successor", expires_at="2099-01-01T00:00:00Z"), None))
    monkeypatch.setattr(OAuthProviderSpec, "_tokens", original)
    result = await OAUTH_PROVIDER.refresh("current-access-token")
    assert original.await_args.args[0] == {"grant_type": "refresh_token", "refresh_token": "current-access-token"}
    assert result.refresh_token == result.access_token == "successor"


def test_scope_and_oauth_contract():
    assert set(nd.ROUTES) | {"on_new_post", "on_new_comment"} == set(nd.NEXTDOOR_SCOPES)
    assert nd.NEXTDOOR_SCOPES.require("create_comment").scopes == ("comment:write",)
    assert OAUTH_PROVIDER.token_auth == "basic"
    assert OAUTH_PROVIDER.identity_url == nd.BASE + "/me/"
    assert set(OAUTH_PROVIDER.token_params["scope"].split()) == set(OAUTH_PROVIDER.scopes)
    assert nd.NextdoorOAuthCredential(access_token="token").credential_type == "nextdoor_oauth"


def test_oauth_token_request_requires_basic_and_form_client_id(monkeypatch):
    monkeypatch.setenv("NEXTDOOR_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("NEXTDOOR_CLIENT_SECRET", "fixture-secret")
    request = OAUTH_PROVIDER.token_request({"grant_type": "authorization_code", "code": "fixture-code", "redirect_uri": "https://app.example.com/callback"})
    assert request["url"] == "https://auth.nextdoor.com/v2/token"
    assert isinstance(request["auth"], httpx.BasicAuth)
    assert request["data"]["client_id"] == "fixture-client"
    assert "client_secret" not in request["data"]
    assert request["data"]["code"] == "fixture-code"


@pytest.mark.asyncio
async def test_documented_string_responses_are_preserved(wire):
    _, replies = wire
    examples = json.loads((Path(__file__).parent / "fixtures/nextdoor/string-responses.json").read_text())
    for example in examples:
        replies.append((200, example["body"]))
        result = await node(example["operation"], example["arguments"]).execute({})
        assert result["data"] == example["body"]


@pytest.mark.parametrize("operation", ["on_new_post", "on_new_comment"])
@pytest.mark.asyncio
async def test_poll_baseline_new_items_and_duplicate_delivery(wire, operation):
    import copy
    from nodes.core.poll_trigger import poll_scope
    calls, replies = wire
    body = json.loads((Path(__file__).parent / "fixtures/nextdoor/posts.json").read_text())
    trigger = node(operation, {"secure_profile_id": "mysecureprofileid"})
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    trigger._update_node_state = update
    replies.append((200, body))
    baseline = await trigger.execute({})
    assert baseline["new_item_count"] == 0
    assert trigger.trigger_produced_no_event(baseline)
    assert nd.NextdoorNode.resolve_agent_event(baseline) is None
    assert dict(calls[-1].url.params) == {"secure_profile_id": "mysecureprofileid"}
    assert state["scope"] == poll_scope(nd.NextdoorNode, {"operation": operation, "secure_profile_id": "mysecureprofileid"})

    changed = copy.deepcopy(body)
    if operation == "on_new_post":
        fresh = copy.deepcopy(body["posts"][0])
        fresh["id"] = "new-post"
        changed["posts"].append(fresh)
    else:
        fresh = copy.deepcopy(body["posts"][0]["comments"][0])
        fresh["id"] = 2
        fresh["parent_comment_id"] = 1
        fresh["author_id"] = None
        changed["posts"][0]["comments"].append(fresh)
    replies.append((200, changed))
    result = await trigger.execute({})
    assert result["new_item_count"] == 1
    assert trigger.trigger_emitted_event(result)
    assert nd.NextdoorNode.should_propagate_output(result, {"operation": operation})
    event = nd.NextdoorNode.resolve_agent_event(result)
    assert ("new-post" if operation == "on_new_post" else "Comment 2") in event["text"]
    assert ("post_body" if operation == "on_new_post" else "comment_body") in event["text"]
    assert "post_url" in event["text"]
    if operation == "on_new_comment":
        assert "post_id" in event["text"] and "parent comment 1" in event["text"]
    replies.append((200, changed))
    assert (await trigger.execute({}))["new_item_count"] == 0

    trigger.config.config.secure_profile_id = "another-profile"
    replies.append((200, changed))
    assert (await trigger.execute({}))["new_item_count"] == 0
    assert dict(calls[-1].url.params) == {"secure_profile_id": "another-profile"}


@pytest.mark.parametrize("body", [{}, {"posts": None}, {"posts": [{"id": "post", "comments": None}]}])
@pytest.mark.asyncio
async def test_poll_rejects_invalid_feed_without_changing_state(wire, body):
    _, replies = wire
    replies.append((200, body))
    trigger = node("on_new_comment")
    trigger._filter_unseen = AsyncMock()
    with pytest.raises(ValueError, match="array"):
        await trigger.execute({})
    trigger._filter_unseen.assert_not_awaited()


def test_poll_scope_ignores_canvas_metadata():
    from nodes.core.poll_trigger import poll_scope
    config = {"operation": "on_new_post", "secure_profile_id": "mysecureprofileid"}
    assert poll_scope(nd.NextdoorNode, config) == poll_scope(nd.NextdoorNode, {**config, "label": "Renamed", "goal": "Watch posts"})
    assert poll_scope(nd.NextdoorNode, config) != poll_scope(nd.NextdoorNode, {**config, "secure_profile_id": "other"})
