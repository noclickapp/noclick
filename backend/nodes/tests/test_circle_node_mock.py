"""Circle wire requests against 24 provider examples and one synthetic empty tag page."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import circle_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / "fixtures/circle/responses.json").read_text())["responses"]
TOKEN = "synthetic-circle-secret"
CREDENTIAL = {"credential_type": "circle_api_token", "api_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="circle-test", node_type="automation-circle",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def client(monkeypatch, body, status=200, headers=None, raw=None):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers=headers) if raw is None else httpx.Response(status, content=raw, headers=headers)
    def make(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", make)
    return calls


# Expected routes and wire data are independent of the implementation's route table.
CASES = [
    ("get_community", {}, "GET", "/community", {}),
    ("list_members", {"status": "all", "member_tag_ids": [1, 2], "page": 2}, "GET", "/community_members", {"status": "all", "member_tag_ids": "1,2", "page": 2, "per_page": 20}),
    ("get_member", {"id": 2}, "GET", "/community_members/2", {}),
    ("search_member", {"email": "member@example.com"}, "GET", "/community_members/search", {"email": "member@example.com"}),
    ("create_member", {"email": "member@example.com", "name": "Member", "space_ids": [1], "member_tag_ids": [2], "skip_invitation": True}, "POST", "/community_members", {"email": "member@example.com", "name": "Member", "space_ids": [1], "member_tag_ids": [2], "skip_invitation": True}),
    ("update_member", {"id": 2, "headline": "New headline", "is_flagged": False, "community_member_profile_fields": {"bio": "Writer"}}, "PUT", "/community_members/2", {"headline": "New headline", "is_flagged": False, "community_member_profile_fields": {"bio": "Writer"}}),
    ("deactivate_member", {"id": 2}, "DELETE", "/community_members/2", {}),
    ("list_spaces", {"sort": "alphabetical", "per_page": 100}, "GET", "/spaces", {"sort": "alphabetical", "page": 1, "per_page": 100}),
    ("get_space", {"id": 1}, "GET", "/spaces/1", {}),
    ("list_space_members", {"space_id": 1}, "GET", "/space_members", {"space_id": 1, "page": 1, "per_page": 20, "status": "active"}),
    ("add_space_member", {"space_id": 1, "email": "member@example.com"}, "POST", "/space_members", {"space_id": 1, "email": "member@example.com"}),
    ("remove_space_member", {"space_id": 1, "email": "member@example.com"}, "DELETE", "/space_members", {"space_id": 1, "email": "member@example.com"}),
    ("list_posts", {"space_id": 1, "status": "draft", "search_text": "Welcome", "sort": "latest"}, "GET", "/posts", {"space_id": 1, "status": "draft", "search_text": "Welcome", "sort": "latest", "page": 1, "per_page": 20}),
    ("get_post", {"id": 2}, "GET", "/posts/2", {}),
    ("create_post", {"space_id": 123, "name": "Welcome", "text": "Welcome to the community!"}, "POST", "/posts", {"space_id": 123, "name": "Welcome", "status": "published", "skip_notifications": False, "tiptap_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Welcome to the community!"}]}]}}}),
    ("update_post", {"id": 2, "name": "Welcome", "topics": [], "is_pinned": False}, "PUT", "/posts/2", {"name": "Welcome", "topics": [], "is_pinned": False}),
    ("delete_post", {"id": 2}, "DELETE", "/posts/2", {}),
    ("list_comments", {"post_id": 1, "search_text": "comment"}, "GET", "/comments", {"post_id": 1, "search_text": "comment", "page": 1, "per_page": 20}),
    ("get_comment", {"id": 2}, "GET", "/comments/2", {}),
    ("create_comment", {"post_id": 1, "body": "<p>Hello</p>", "parent_comment_id": 2}, "POST", "/comments", {"post_id": 1, "body": "<p>Hello</p>", "parent_comment_id": 2, "skip_notifications": True}),
    ("delete_comment", {"id": 2}, "DELETE", "/comments/2", {}),
    ("list_member_tags", {"is_public": False, "name": "Tag", "sort": "newest"}, "GET", "/member_tags", {"is_public": False, "name": "Tag", "sort": "newest", "page": 1, "per_page": 20}),
    ("create_member_tag", {"name": "Created Tag Name", "color": "#0ce806"}, "POST", "/member_tags", {"name": "Created Tag Name", "color": "#0ce806", "display_format": "label", "is_public": True}),
    ("tag_member", {"member_tag_id": 1, "user_email": "member@example.com"}, "POST", "/tagged_members", {"member_tag_id": 1, "user_email": "member@example.com"}),
    ("untag_member", {"member_tag_id": 1, "user_email": "member@example.com"}, "DELETE", "/tagged_members", {"member_tag_id": 1, "user_email": "member@example.com"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,wire", CASES, ids=[x[0] for x in CASES])
async def test_circle_operations(monkeypatch, operation, config, method, path, wire):
    fixture = FIXTURES[operation]
    calls = client(monkeypatch, fixture["body"], fixture["status"])
    result = await node({"operation": operation, **config}).execute({})
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == "/api/admin/v2" + path
    assert request.url.host == "app.circle.so" and request.url.scheme == "https"
    assert request.headers["Authorization"] == "Token " + TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    if method in {"GET", "DELETE"}:
        assert not request.content
        assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in wire.items()}
    else:
        assert not request.url.params
        assert json.loads(request.content) == wire
    if operation == "get_community":
        assert result["name"] == "My Community" and result["id"] == 1
    else:
        assert result["data"] == fixture["body"]
    assert result["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_circle_errors_not_success_or_retried(monkeypatch, status):
    calls = client(monkeypatch, {"success": False, "message": "Rejected " + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_community"}).execute({})
    assert TOKEN not in str(error.value) and len(calls) == 1
    if status != 301:
        assert "Rejected [redacted]" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"success": False, "message": "Invalid token"}, {"error": "Invalid token"}, {"id": 1, "name": ""}])
async def test_circle_connection_requires_identity(monkeypatch, body):
    client(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_community"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("content,content_type", [(b'<html>login</html>', 'text/html'), (b'not json', 'application/json')])
async def test_circle_invalid_response(monkeypatch, content, content_type):
    client(monkeypatch, None, raw=content, headers={"Content-Type": content_type})
    with pytest.raises(ValueError):
        await node({"operation": "list_members"}).execute({})


@pytest.mark.asyncio
async def test_circle_preserves_pagination(monkeypatch):
    body = {"records": [{"id": 1}], "page": 2, "per_page": 1, "has_next_page": True, "count": 5, "page_count": 1}
    calls = client(monkeypatch, body)
    result = await node({"operation": "list_members", "page": 2, "per_page": 1}).execute({})
    assert result["data"] == body and len(calls) == 1


@pytest.mark.asyncio
async def test_circle_multiline_text_and_secret_redaction(monkeypatch):
    calls = client(monkeypatch, {"post": {"name": TOKEN}})
    result = await node({"operation": "update_post", "id": 2, "text": "First\n\nLast"}).execute({})
    paragraphs = json.loads(calls[0].content)["tiptap_body"]["body"]["content"]
    assert len(paragraphs) == 3 and paragraphs[1] == {"type": "paragraph", "content": []}
    assert paragraphs[2]["content"][0]["text"] == "Last"
    assert result["data"]["post"]["name"] == "[redacted]"


@pytest.mark.parametrize("config", [
    {"operation": "get_member", "id": "../community"},
    {"operation": "get_member", "id": 0},
    {"operation": "list_members", "per_page": 101},
    {"operation": "list_members", "page": 0},
    {"operation": "update_member", "id": 2},
    {"operation": "update_post", "id": 2},
    {"operation": "create_member_tag", "name": "Tag", "display_format": "icon"},
    {"operation": "create_member", "email": "invalid"},
])
def test_circle_invalid_inputs(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize("token", ["https://example.com", "Token abc", "abc\r\nHost: evil", "<token>"])
def test_circle_invalid_secrets(token):
    with pytest.raises(ValidationError):
        native.CircleAPITokenCredential(api_token=token)


def test_circle_manual_credential_default_and_family():
    assert native.CircleAPITokenCredential(api_token=TOKEN).credential_type == "circle_api_token"
    with pytest.raises(ValueError, match="Circle API token"):
        node({"operation": "get_community"}, {"credential_type": "other", "api_token": TOKEN})
