"""Contract checks against the documented Microsoft Graph OneNote routes.

These are local HTTP tests; live OAuth and FlowCanvas QA are separate gates.
"""

from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.microsoft_onenote_node import (
    CONFIG_MODELS,
    OPERATIONS,
    OneNoteNode,
    OneNoteNodeConfig,
    OneNoteOAuthCredential,
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
    assert set(OPERATIONS) == OneNoteNode.scope_registry.keys_declared
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
