"""Contract checks against the documented Microsoft Graph OneNote routes.

These are local HTTP tests; live OAuth and FlowCanvas QA are separate gates.
"""

from unittest.mock import AsyncMock
from copy import deepcopy
import json

import httpx
import pytest

from nodes.microsoft_onenote_node import (
    CONFIG_MODELS,
    OPERATIONS,
    OneNoteNode,
    OneNoteNodeConfig,
    OneNoteOAuthCredential,
    OneNoteOnNewPageConfig,
    OneNoteOnNewOrUpdatedPageConfig,
)


CREDENTIAL = OneNoteOAuthCredential(
    access_token="test-access-token",
    refresh_token="test-refresh-token",
    expires_at="2099-01-01T00:00:00Z",
    email="qa@example.com",
)
VALUES = {
    "notebook_id": "notebook/one",
    "section_id": "section/one",
    "section_group_id": "group/one",
    "page_id": "page/one",
    "display_name": "QA notes",
    "title": "QA <Summary>",
    "body_html": "<p>OneNote QA</p>",
    "content_html": "<p>More QA</p>",
    "target_id": "generated-123",
    "top": 10,
}


def make_node(slug: str) -> OneNoteNode:
    fields = {key: VALUES[key] for key in OPERATIONS[slug].fields}
    config = CONFIG_MODELS[slug](**fields)
    return OneNoteNode(
        node_id="onenote-qa",
        node_type="automation-microsoft-onenote",
        node_data={},
        config=OneNoteNodeConfig(config=config, credentials=CREDENTIAL),
        sio=None,
        sid=None,
        workflow_id="workflow-qa",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", list(OPERATIONS))
async def test_every_operation_uses_its_graph_route_and_bearer(monkeypatch, slug):
    from nodes.core import oauth_refresh
    from nodes import microsoft_onenote_node as onenote_node

    monkeypatch.setattr(
        oauth_refresh,
        "ensure_fresh_oauth_token",
        AsyncMock(return_value="test-access-token"),
    )
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method in ("DELETE", "PATCH"):
            return httpx.Response(204, request=request)
        if slug.startswith("list_"):
            return httpx.Response(
                200,
                json={"value": [{"id": "item-1", "displayName": "QA"}]},
                request=request,
            )
        if slug == "get_page_content":
            return httpx.Response(
                200, text="<html><body>QA</body></html>", request=request
            )
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json={"id": "item-1"},
            request=request,
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        onenote_node.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(respond)),
    )
    result = await make_node(slug).execute({})

    assert len(requests) == 1
    request = requests[0]
    spec = OPERATIONS[slug]
    expected_path = spec.path
    for key in ("notebook_id", "section_id", "section_group_id", "page_id"):
        expected_path = expected_path.replace(
            "{" + key + "}", VALUES[key].replace("/", "%2F")
        )
    assert request.method == spec.method
    assert request.url.host == "graph.microsoft.com"
    assert (
        request.url.raw_path.decode().split("?")[0]
        == "/v1.0/me/onenote" + expected_path
    )
    assert request.headers["Authorization"] == "Bearer test-access-token"
    assert result["status"] == "success"
    if slug.startswith("list_"):
        assert result["items"][0]["id"] == "item-1"
        assert result["count"] == 1
    if slug == "get_page_content":
        assert "<body>QA</body>" in result["html"]


@pytest.mark.asyncio
async def test_create_page_escapes_title_and_sends_html(monkeypatch):
    from nodes.core import oauth_refresh
    from nodes import microsoft_onenote_node as onenote_node

    monkeypatch.setattr(
        oauth_refresh,
        "ensure_fresh_oauth_token",
        AsyncMock(return_value="test-access-token"),
    )
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "new-page"}, request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        onenote_node.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(respond)),
    )
    result = await make_node("create_page").execute({})
    assert result["data"]["id"] == "new-page"
    assert seen[0].headers["Content-Type"] == "text/html"
    assert b"<title>QA &lt;Summary&gt;</title>" in seen[0].content
    assert b"<p>OneNote QA</p>" in seen[0].content


@pytest.mark.asyncio
async def test_graph_error_surfaces_message_without_token(monkeypatch):
    from nodes.core import oauth_refresh
    from nodes import microsoft_onenote_node as onenote_node

    monkeypatch.setattr(
        oauth_refresh,
        "ensure_fresh_oauth_token",
        AsyncMock(return_value="test-access-token"),
    )
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        onenote_node.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    403,
                    json={"error": {"message": "Insufficient privileges"}},
                    request=request,
                )
            )
        ),
    )
    with pytest.raises(ValueError, match="Insufficient privileges") as exc:
        await make_node("list_notebooks").execute({})
    assert "test-access-token" not in str(exc.value)


def test_schema_and_scope_cover_every_operation():
    schema = OneNoteNode.get_config_schema()
    assert len(OPERATIONS) == 19
    assert set(OPERATIONS) | {"on_new_page", "on_new_or_updated_page"} == OneNoteNode.scope_registry.keys_declared
    credential = schema["$defs"]["OneNoteOAuthCredential"]
    assert credential["x-oauth-provider"] == "microsoft"
    assert "https://graph.microsoft.com/Notes.ReadWrite" in credential["x-oauth-scopes"]


def test_existing_microsoft_connect_flow_creates_the_declared_credential_type():
    from wss.handlers.oauth.microsoft_oauth_handler import MicrosoftOAuthHandler

    handler = object.__new__(MicrosoftOAuthHandler)
    credential_schema = OneNoteNode.get_config_schema()["$defs"]["OneNoteOAuthCredential"]
    created_type = handler._get_credential_type_from_name(
        credential_schema["title"], credential_schema["x-oauth-scopes"]
    )
    assert created_type == CREDENTIAL.credential_type


@pytest.mark.asyncio
async def test_freshen_credential_uses_staging_microsoft_refresh(monkeypatch):
    from nodes.core import oauth_refresh
    from nodes.oauth.microsoft_oauth import refresh_access_token

    freshen = AsyncMock(return_value={"access_token": "fresh"})
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", freshen)
    data = CREDENTIAL.model_dump()
    result = await OneNoteNode.freshen_credential(
        data, pool="pool", user_id="user", credential_id="credential"
    )
    assert result == {"access_token": "fresh"}
    freshen.assert_awaited_once_with(
        data, pool="pool", user_id="user", credential_id="credential",
        refresh=refresh_access_token, provider="microsoft",
    )


# Unmodified resource JSON from Microsoft's page resource documentation:
# https://learn.microsoft.com/en-us/graph/api/resources/page?view=graph-rest-1.0
PAGE = json.loads('''{
  "content": "stream",
  "contentUrl": "string",
  "createdByAppId": "string",
  "createdDateTime": "String (timestamp)",
  "id": "string (identifier)",
  "lastModifiedDateTime": "String (timestamp)",
  "level": 1024,
  "links": {
    "@odata.type": "microsoft.graph.pageLinks"
  },
  "order": 1024,
  "self": "string",
  "title": "string"
}''')


def poll_node(operation="on_new_page", section_id=None):
    model = (OneNoteOnNewPageConfig if operation == "on_new_page"
             else OneNoteOnNewOrUpdatedPageConfig)
    return OneNoteNode(
        node_id="onenote-poll", node_type="automation-microsoft-onenote", node_data={},
        config=OneNoteNodeConfig(config=model(section_id=section_id), credentials=CREDENTIAL),
        sio=None, sid=None, workflow_id="workflow-qa",
    )


def poll_state(node):
    state = {}

    async def update(mutator, **kwargs):
        changed, result = mutator(deepcopy(state))
        if changed is not None:
            state.clear()
            state.update(changed)
        return result

    node._update_node_state = update
    return state


def mock_poll(monkeypatch, respond):
    from nodes.core import oauth_refresh
    from nodes import microsoft_onenote_node as module

    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", AsyncMock(return_value="token"))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(respond)))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_page", "on_new_or_updated_page"])
async def test_poll_baselines_and_detects_new_pages_and_revisions(monkeypatch, operation):
    pages = [deepcopy(PAGE)]
    mock_poll(monkeypatch, lambda request: httpx.Response(200, json={"value": pages}, request=request))
    node = poll_node(operation)
    state = poll_state(node)
    assert (await node.execute({}))["pages"] == []
    assert node.trigger_produced_no_event({})
    assert (await node.execute({}))["pages"] == []
    # A later revision uses the timestamp from Microsoft's List Pages response.
    pages[0]["lastModifiedDateTime"] = "2016-10-19T10:37:00Z"
    result = await node.execute({})
    assert result["count"] == (1 if operation == "on_new_or_updated_page" else 0)
    if result["count"]:
        assert node.trigger_emitted_event(result)
        event = node.resolve_agent_event(result)
        assert PAGE["id"] in event["text"]
        assert PAGE["title"] in event["text"]
        assert PAGE["contentUrl"] in event["text"]
    assert (await node.execute({}))["pages"] == []
    # Vary the documented resource's identifier to simulate a newly created page.
    pages.append({**PAGE, "id": "second-page"})
    result = await node.execute({})
    assert [p["id"] for p in result["pages"]] == ["second-page"]
    assert node.should_propagate_output(result, {"operation": operation})
    assert not node.should_propagate_output({"pages": []}, {"operation": operation})
    assert node.resolve_agent_event({"operation": operation, "pages": []}) is None
    assert "seen_ids" in state


@pytest.mark.asyncio
async def test_poll_paginates_within_selected_section_before_recording_state(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer token"
        assert request.url.raw_path.decode().split("?")[0].endswith("/sections/section%2Fone/pages")
        if len(requests) == 1:
            assert request.url.params["$orderby"] == "lastModifiedDateTime desc"
            assert request.url.params["$skip"] == "0"
            return httpx.Response(200, json={"value": [
                {**PAGE, "id": f"page-{i}"} for i in range(100)
            ]}, request=request)
        assert request.url.params["$skip"] == "100"
        assert request.url.params["$orderby"] == "lastModifiedDateTime desc"
        return httpx.Response(200, json={"value": [{**PAGE, "id": "second-page"}]}, request=request)

    mock_poll(monkeypatch, respond)
    node = poll_node(section_id="section/one")
    state = poll_state(node)
    await node.execute({})
    assert len(requests) == 2
    assert len(state["seen_ids"]) == 101


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"value": [{"title": "missing ID"}]},
    {"value": [{"id": "missing timestamp"}]},
    {"error": {"message": "bad response"}},
])
async def test_poll_errors_never_commit_partial_state(monkeypatch, body):
    mock_poll(monkeypatch, lambda request: httpx.Response(200, json=body, request=request))
    node = poll_node("on_new_or_updated_page")
    state = poll_state(node)
    with pytest.raises(ValueError):
        await node.execute({})
    assert state == {}


def test_poll_scope_tracks_only_declared_resource_fields():
    from nodes.core.poll_trigger import poll_scope

    config = {"operation": "on_new_page", "section_id": "a"}
    scope = poll_scope(OneNoteNode, config)
    assert scope
    assert scope == poll_scope(OneNoteNode, {**config, "label": "cosmetic", "webhook_id": "changed"})
    assert scope != poll_scope(OneNoteNode, {**config, "section_id": "b"})
    assert scope != poll_scope(OneNoteNode, {**config, "operation": "on_new_or_updated_page"})
