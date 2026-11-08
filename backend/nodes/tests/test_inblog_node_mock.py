"""Inblog request/response regressions using synthetic JSON:API resources."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import inblog_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY

TOKEN = "inblog-local-test-key-9d35"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="inblog-test", node_type="automation-inblog",
        node_data={"config": config, "credentials": {"credential_type": "inblog_api_key", "api_key": TOKEN}})


def mock(monkeypatch, status=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert request.url.host == "inblog.ai"
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def test_inblog_discovered_and_operation_count():
    assert NODE_REGISTRY["automation-inblog"] is native.InblogNode
    assert len(native.ROUTES) == 24


@pytest.mark.asyncio
async def test_inblog_filters_paging_preserves_jsonapi(monkeypatch):
    payload = {"jsonapi": {"version": "1.0"}, "data": [], "meta": {"total": 23}, "links": {"next": "https://inblog.ai/api/v1/posts?page=3"}}
    requests = mock(monkeypatch, body=payload)
    result = await node({"operation": "list_posts", "page": 2, "limit": 10, "slug": "my-post", "published": False}).execute({})
    assert dict(requests[0].url.params) == {"page": "2", "limit": "10", "filter[slug]": "my-post", "filter[published]": "false", "sort": "created_at", "order": "desc"}
    assert result["links"] == payload["links"] and result["meta"] == payload["meta"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_inblog_create_draft_jsonapi_envelope(monkeypatch):
    requests = mock(monkeypatch, status=201, body={"data": {"type": "posts", "id": "123"}})
    result = await node({"operation": "create_post", "title": "Building a Blog with Next.js", "slug": "building-blog-with-nextjs", "content_html": "<p>Hello</p>"}).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/api/v1/posts"
    assert requests[0].headers["content-type"] == "application/vnd.api+json"
    assert json.loads(requests[0].content) == {"jsonapi": {"version": "1.0"}, "data": {"type": "posts", "attributes": {"title": "Building a Blog with Next.js", "slug": "building-blog-with-nextjs", "content_html": "<p>Hello</p>", "published": False}}}
    assert result["http_status"] == 201


@pytest.mark.asyncio
async def test_inblog_partial_update_omits_unset_fields(monkeypatch):
    requests = mock(monkeypatch, body={"data": {"type": "posts", "id": "123"}})
    await node({"operation": "update_post", "post_id": 123, "description": "Updated post description."}).execute({})
    assert requests[0].method == "PATCH" and requests[0].url.path == "/api/v1/posts/123"
    assert json.loads(requests[0].content)["data"]["attributes"] == {"description": "Updated post description."}


@pytest.mark.asyncio
async def test_inblog_redirect_id_and_publish_action(monkeypatch):
    requests = mock(monkeypatch, body={"data": {"type": "redirects", "id": "r-1"}})
    await node({"operation": "update_redirect", "redirect_id": "r-1", "redirect_type": 308}).execute({})
    assert json.loads(requests[0].content)["data"] == {"type": "redirects", "id": "r-1", "attributes": {"redirect_type": 308}}
    requests = mock(monkeypatch, body={"data": {"type": "posts", "id": "123"}})
    await node({"operation": "publish_post", "post_id": 123, "action": "unpublish"}).execute({})
    assert requests[0].url.path == "/api/v1/posts/123/publish"
    assert json.loads(requests[0].content)["data"] == {"type": "publish_action", "attributes": {"action": "unpublish"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field,path", [("delete_post", "post_id", "posts/123"), ("delete_tag", "tag_id", "tags/123"), ("delete_redirect", "redirect_id", "redirects/123")])
async def test_inblog_empty_delete_response(monkeypatch, operation, field, path):
    requests = mock(monkeypatch, status=204)
    result = await node({"operation": operation, field: "123" if field == "redirect_id" else 123}).execute({})
    assert requests[0].method == "DELETE" and requests[0].url.path == "/api/v1/" + path
    assert result["deleted"] is True and not requests[0].content


@pytest.mark.asyncio
async def test_inblog_account_evidence_uses_connected_blog(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/inblog/me.json").read_text())
    requests = mock(monkeypatch, body=fixture)
    result = await node({"operation": "get_me"}).execute({})
    assert requests[0].url.path == "/api/v1/me"
    assert result["subdomain"] == "myblog" and result["blog_id"] == 123
    assert result["data"] == fixture["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_inblog_errors_do_not_report_success_or_echo_secret(monkeypatch, status):
    requests = mock(monkeypatch, status=status, body={"errors": [{"detail": "Rejected " + TOKEN}]})
    with pytest.raises(ValueError) as err:
        await node({"operation": "get_me"}).execute({})
    assert str(status) in str(err.value) and TOKEN not in str(err.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"errors": [{"detail": "bad"}]}, {"data": [], "errors": []}])
async def test_inblog_invalid_envelopes_fail(monkeypatch, body):
    mock(monkeypatch, body=body)
    with pytest.raises(ValueError, match="JSON:API"):
        await node({"operation": "list_tags"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "create_tag", "name": "React", "slug": "has spaces"},
    {"operation": "list_forms", "limit": 101},
    {"operation": "get_post", "post_id": -1},
    {"operation": "get_author", "author_id": "not-a-uuid"},
    {"operation": "publish_post", "post_id": 123, "action": "schedule"},
    {"operation": "update_post", "post_id": 123},
    {"operation": "update_redirect", "redirect_id": "r-1"},
    {"operation": "update_tag", "tag_id": 123},
])
def test_inblog_invalid_config_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_inblog_credential_normalizes_and_rejects_header():
    assert native.InblogAPIKeyCredential(api_key="  " + TOKEN + "  ").api_key == TOKEN
    with pytest.raises(ValueError):
        native.InblogAPIKeyCredential(api_key="Bearer " + TOKEN)
