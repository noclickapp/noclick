"""Figma OAuth and REST request contracts for every exposed operation."""

import json
from unittest.mock import Mock

import httpx
import pytest
import respx

from nodes.figma_node import (
    AddReaction, CreateComment, CreateDevResource, CreateWebhook, DeleteComment,
    DeleteDevResource, DeleteReaction, DeleteWebhook, FigmaNode, FigmaNodeConfig,
    FigmaOAuthCredential, FigmaPATCredential, GetCurrentUser, GetFile, GetFileMetadata, GetFileNodes,
    GetImageFills, GetWebhook, ListComments, ListDevResources,
    ListFileComponentSets, ListFileComponents, ListFileStyles, ListReactions,
    ListVersions, ListWebhooks, RenderImages, UpdateDevResource, UpdateWebhook,
)
from nodes.oauth.figma_oauth import OAUTH_PROVIDER, refresh_access_token
from nodes.scopes.figma import FIGMA_OPERATION_SCOPES, FIGMA_SCOPES


def make_node(operation):
    credential = FigmaOAuthCredential(
        access_token="access", refresh_token="refresh", expires_at="2099-01-01T00:00:00Z")
    return FigmaNode(
        node_id="figma-test", node_type="automation-figma", node_data={},
        config=FigmaNodeConfig(config=operation, credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
async def test_oauth_code_exchange_and_reusable_refresh(monkeypatch):
    monkeypatch.setenv("FIGMA_CLIENT_ID", "client")
    monkeypatch.setenv("FIGMA_CLIENT_SECRET", "secret")
    monkeypatch.delenv("FIGMA_REDIRECT_URI", raising=False)
    with respx.mock(assert_all_called=True) as router:
        token = router.post("https://api.figma.com/v1/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "first", "refresh_token": "reusable", "expires_in": 3600}))
        router.get("https://api.figma.com/v1/me").mock(
            return_value=httpx.Response(200, json={"id": "123", "handle": "Figma User"}))
        refresh_route = router.post("https://api.figma.com/v1/oauth/refresh").mock(
            return_value=httpx.Response(200, json={"access_token": "second", "expires_in": 3600}))
        first, name = await OAUTH_PROVIDER.exchange(
            "code", "https://www.noclick.com/api/auth/oauth/figma/callback", "v" * 43)
        second = await refresh_access_token(first.refresh_token)
    assert name == "Figma User"
    assert second.refresh_token == "reusable"
    assert second.access_token == "second"
    assert token.calls[0].request.headers["Authorization"].startswith("Basic ")
    assert refresh_route.calls[0].request.headers["Authorization"].startswith("Basic ")
    exchange = dict(httpx.QueryParams(token.calls[0].request.content.decode()))
    refresh = dict(httpx.QueryParams(refresh_route.calls[0].request.content.decode()))
    assert exchange == {"grant_type": "authorization_code", "code": "code",
                        "redirect_uri": "https://www.noclick.com/api/auth/oauth/figma/callback",
                        "code_verifier": "v" * 43}
    assert refresh == {"refresh_token": "reusable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,body,query", [
    (GetCurrentUser(), "GET", "/v1/me", None, {}),
    (GetFile(file_key="file/1", depth=2), "GET", "/v1/files/file%2F1", None, {"depth": "2"}),
    (GetFileMetadata(file_key="f"), "GET", "/v1/files/f/meta", None, {}),
    (GetFileNodes(file_key="f", node_ids="1:2,1:3"), "GET", "/v1/files/f/nodes", None, {"ids": "1:2,1:3"}),
    (RenderImages(file_key="f", node_ids="1:2"), "GET", "/v1/images/f", None, {"ids": "1:2", "format": "png"}),
    (GetImageFills(file_key="f"), "GET", "/v1/files/f/images", None, {}),
    (ListVersions(file_key="f"), "GET", "/v1/files/f/versions", None, {}),
    (ListComments(file_key="f"), "GET", "/v1/files/f/comments", None, {"as_md": "false"}),
    (CreateComment(file_key="f", message="New comment"), "POST", "/v1/files/f/comments", {"message": "New comment"}, {}),
    (CreateComment(file_key="f", message="Review this", comment_id="c"), "POST", "/v1/files/f/comments", {"message": "Review this", "comment_id": "c"}, {}),
    (DeleteComment(file_key="f", comment_id="c/1"), "DELETE", "/v1/files/f/comments/c%2F1", None, {}),
    (ListReactions(file_key="f", comment_id="c", cursor="next"), "GET", "/v1/files/f/comments/c/reactions", None, {"cursor": "next"}),
    (AddReaction(file_key="f", comment_id="c", emoji=":heart:"), "POST", "/v1/files/f/comments/c/reactions", {"emoji": ":heart:"}, {}),
    (DeleteReaction(file_key="f", comment_id="c", emoji=":heart:"), "DELETE", "/v1/files/f/comments/c/reactions", None, {"emoji": ":heart:"}),
    (ListFileComponents(file_key="f"), "GET", "/v1/files/f/components", None, {}),
    (ListFileComponentSets(file_key="f"), "GET", "/v1/files/f/component_sets", None, {}),
    (ListFileStyles(file_key="f"), "GET", "/v1/files/f/styles", None, {}),
    (ListDevResources(file_key="f", node_ids="1:2"), "GET", "/v1/files/f/dev_resources", None, {"node_ids": "1:2"}),
    (CreateDevResource(file_key="f", node_id="1:2", name="Issue", url="https://example.com"), "POST", "/v1/dev_resources",
     {"dev_resources": [{"file_key": "f", "node_id": "1:2", "name": "Issue", "url": "https://example.com"}]}, {}),
    (UpdateDevResource(resource_id="r", name="Updated"), "PUT", "/v1/dev_resources", {"dev_resources": [{"id": "r", "name": "Updated"}]}, {}),
    (DeleteDevResource(file_key="f", resource_id="r"), "DELETE", "/v1/files/f/dev_resources/r", None, {}),
    (ListWebhooks(context="file", context_id="f"), "GET", "/v2/webhooks", None, {"context": "file", "context_id": "f"}),
    (GetWebhook(webhook_id="w"), "GET", "/v2/webhooks/w", None, {}),
    (CreateWebhook(event_type="FILE_UPDATE", context="file", context_id="f", endpoint="https://example.com/hook", passcode="pass"),
     "POST", "/v2/webhooks", {"event_type": "FILE_UPDATE", "context": "file", "context_id": "f", "endpoint": "https://example.com/hook", "passcode": "pass"}, {}),
    (UpdateWebhook(webhook_id="w", status="PAUSED"), "PUT", "/v2/webhooks/w", {"status": "PAUSED"}, {}),
    (DeleteWebhook(webhook_id="w"), "DELETE", "/v2/webhooks/w", None, {}),
])
async def test_operation_request(operation, method, path, body, query, monkeypatch):
    node = make_node(operation)

    async def no_refresh(_):
        return "access"

    monkeypatch.setattr(node, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        response = httpx.Response(204) if method == "DELETE" else httpx.Response(200, json={"id": "result"})
        route = router.request(method, "https://api.figma.com" + path).mock(return_value=response)
        result = await node.execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer access"
    if body is not None:
        assert json.loads(request.content) == body
    for key, value in query.items():
        assert request.url.params[key] == value
    if isinstance(operation, ListDevResources) and operation.node_ids is None:
        assert "node_ids" not in request.url.params
    assert result["status"] == "success"
    assert result["operation"] == operation.operation


@pytest.mark.asyncio
async def test_dev_resource_batch_errors_and_api_errors():
    with respx.mock(assert_all_called=True) as router:
        router.post("https://api.figma.com/v1/dev_resources").mock(
            return_value=httpx.Response(200, json={"errors": [{"error": "File inaccessible"}]}))
        node = make_node(CreateDevResource(file_key="f", node_id="n", name="Issue", url="https://example.com"))

        async def no_refresh(_):
            return "access"

        node._token = no_refresh
        with pytest.raises(ValueError, match="File inaccessible"):
            await node.execute({})
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.figma.com/v1/me").mock(
            return_value=httpx.Response(403, json={"message": "Missing scope"}))
        with pytest.raises(ValueError, match="403: Missing scope"):
            await FigmaNode._request("access", "GET", "/v1/me")


def test_all_operations_have_documented_scopes():
    schema = FigmaNodeConfig.model_json_schema()
    operations = {
        prop["properties"]["operation"]["const"] for name, prop in schema["$defs"].items()
        if isinstance(prop, dict) and isinstance(prop.get("properties"), dict)
        and isinstance(prop["properties"].get("operation"), dict)
        and "const" in prop["properties"]["operation"]
    }
    assert len(operations) == 26
    assert operations == set(FIGMA_OPERATION_SCOPES)
    assert set(FIGMA_SCOPES.declared_scopes()) == set(FIGMA_OPERATION_SCOPES.values())


@pytest.mark.asyncio
async def test_personal_token_uses_figma_header():
    credential = FigmaPATCredential(access_token="personal")
    node = FigmaNode(
        node_id="figma-pat", node_type="automation-figma", node_data={},
        config=FigmaNodeConfig(config=GetCurrentUser(), credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://api.figma.com/v1/me").mock(
            return_value=httpx.Response(200, json={"id": "user"}))
        result = await node.execute({})
    assert route.calls[0].request.headers["X-Figma-Token"] == "personal"
    assert "Authorization" not in route.calls[0].request.headers
    assert result["data"]["id"] == "user"


@pytest.mark.parametrize("model,fields", [
    (CreateWebhook, {"context": "file", "context_id": "f", "endpoint": "https://example.com/hook", "passcode": "pass"}),
    (UpdateWebhook, {"webhook_id": "w"}),
])
def test_webhook_rejects_unknown_event(model, fields):
    with pytest.raises(ValueError, match="event_type"):
        model(event_type="invalid", **fields)


@pytest.mark.asyncio
async def test_refreshed_token_is_adopted(monkeypatch):
    node = make_node(GetCurrentUser())

    async def fresh(**kwargs):
        kwargs["credential"].update(access_token="new", refresh_token="refresh-new", expires_at="2099-02-01T00:00:00Z")
        return "new"

    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", fresh)
    assert await node._token(node.config.credentials) == "new"
    assert node.config.credentials.access_token == "new"
    assert node.config.credentials.refresh_token == "refresh-new"
