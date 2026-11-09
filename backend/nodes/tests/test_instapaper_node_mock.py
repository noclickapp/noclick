"""Real factory and transport tests; fixtures from Instapaper's bookmark reference.

https://www.instapaper.com/developers/v2/reference/bookmarks
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import instapaper_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "instapaper"
BOOKMARK = json.loads((FIXTURES / "bookmark.json").read_text())
PARSED = json.loads((FIXTURES / "parsed.json").read_text())
TOKEN = "synthetic-instapaper-access-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credentials):
    return NodeFactory.create_node(node_id="instapaper-test", node_type="automation-instapaper",
        node_data={"config": config, "credentials": {"credential_type": "instapaper_access_token",
            "access_token": TOKEN, **credentials}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_bookmarks", "section": "archive", "limit": 50}, "GET", "/bookmarks", {"bookmarks": [BOOKMARK], "total": 214}, None),
    ({"operation": "create_bookmark", "url": "https://example.com/article", "tags": [{"name": "Recipes"}]}, "POST", "/bookmarks", BOOKMARK,
        {"url": "https://example.com/article", "tags": [{"name": "Recipes"}], "archived": False, "canonicalize": True}),
    ({"operation": "update_bookmark", "bookmark_id": 12345, "progress": {"percentage": 0.42, "timestamp": 1755000000}}, "POST", "/bookmarks/12345", BOOKMARK,
        {"progress": {"percentage": 0.42, "timestamp": 1755000000}}),
    ({"operation": "delete_bookmark", "bookmark_id": 12345}, "DELETE", "/bookmarks/12345", None, None),
    ({"operation": "move_bookmark", "bookmark_id": 12345, "section": "archive"}, "POST", "/bookmarks/12345/move", BOOKMARK, {"section": "archive"}),
    ({"operation": "like_bookmark", "bookmark_id": 12345}, "POST", "/bookmarks/12345/like", BOOKMARK, None),
    ({"operation": "unlike_bookmark", "bookmark_id": 12345}, "DELETE", "/bookmarks/12345/like", BOOKMARK, None),
    ({"operation": "update_bookmark_tags", "bookmark_id": 12345, "add_tags": [{"name": "Recipes"}], "remove_tags": [{"id": 7}]}, "POST", "/bookmarks/12345/tags",
        {"tags": BOOKMARK["tags"], "created_tags": []}, {"add_tags": [{"name": "Recipes"}], "remove_tags": [{"id": 7}]}),
    ({"operation": "get_bookmark_content", "bookmark_id": 12345, "use_cache": "0", "force": "1"}, "GET", "/bookmarks/12345/parse", PARSED, None),
    ({"operation": "parse_bookmark_content", "bookmark_id": 12345, "content": "<p>Article</p>", "use_cache": False}, "POST", "/bookmarks/12345/parse", PARSED,
        {"content": "<p>Article</p>", "use_cache": False, "force": False}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,payload", CASES)
async def test_instapaper_published_operations(monkeypatch, config, method, path, body, payload):
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "www.instapaper.com"
    assert request.url.path == "/api/2" + path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    if payload is not None:
        assert json.loads(request.content) == payload
    else:
        assert not request.content
    if config["operation"] == "get_bookmark_content":
        assert dict(request.url.params) == {"use_cache": "0", "force": "1"}
        assert result["content"] == PARSED["content"]
    if config["operation"] == "list_bookmarks":
        assert dict(request.url.params) == {"section": "archive", "limit": "50", "offset": "0"}
        assert result["next_offset"] == 1
    if config["operation"] == "delete_bookmark":
        assert result["deleted"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("count,deleted,expected", [(1, [12346, 12347], 13), (0, [12346, 12347], None), (0, [], None)])
async def test_instapaper_sync_counts_deleted_ids(monkeypatch, count, deleted, expected):
    transport(monkeypatch, {"bookmarks": [BOOKMARK] * count, "deleted_ids": deleted, "total": 42})
    result = await node({"operation": "list_bookmarks", "since": 1755000000, "offset": 10, "limit": 3}).execute({})
    assert result["next_offset"] == expected
    assert result["deleted_ids"] == deleted


@pytest.mark.asyncio
async def test_instapaper_empty_account_evidence_and_folder_filter(monkeypatch):
    requests = transport(monkeypatch, {"bookmarks": [], "total": 0})
    result = await node({"operation": "list_bookmarks", "folder_id": 99}).execute({})
    assert result["bookmarks"] == [] and result["next_offset"] is None
    assert requests[0].url.params["section"] == "folder"
    assert native.InstapaperNode.connection_evidence.operation == "list_bookmarks"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_bookmark_content", "parse_bookmark_content"])
async def test_instapaper_parser_key_placement(monkeypatch, operation):
    requests = transport(monkeypatch, PARSED)
    result = await node({"operation": operation, "bookmark_id": 12345}, instaparser_api_key="parser-secret").execute({})
    request = requests[0]
    params = dict(request.url.params) if request.method == "GET" else json.loads(request.content)
    assert params["instaparser_api_key"] == "parser-secret"
    assert "parser-secret" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 429, 500])
async def test_instapaper_errors_verbatim_redacted_and_no_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"code": status, "message": "Authentication failed " + TOKEN}}, status)
    result = await node({"operation": "list_bookmarks"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Authentication failed [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"error": {"code": 401, "message": "Authentication failed"}}, {}, {"bookmarks": []}])
async def test_instapaper_malformed_success_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_bookmarks"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "create_bookmark"},
    {"operation": "create_bookmark", "private_source": "Acme Reader"},
    {"operation": "create_bookmark", "url": "not a url"},
    {"operation": "list_bookmarks", "folder_id": 99, "tag": "Recipes"},
    {"operation": "list_bookmarks", "section": "folder"},
    {"operation": "list_bookmarks", "section": "tag"},
    {"operation": "list_bookmarks", "limit": 501},
    {"operation": "move_bookmark", "bookmark_id": 12345, "section": "../../other"},
    {"operation": "update_bookmark_tags", "bookmark_id": 12345},
    {"operation": "update_bookmark", "bookmark_id": 12345, "progress": {"percentage": 1.1, "timestamp": 1755000000}},
])
def test_instapaper_invalid_inputs(config):
    with pytest.raises(ValidationError):
        native.InstapaperFullConfig.model_validate({"config": config})


def test_instapaper_manual_credential_and_private_content():
    credential = native.InstapaperTokenCredential(access_token=TOKEN)
    assert credential.credential_type == "instapaper_access_token"
    assert native.CreateBookmark(private_source="Acme Reader", content="<p>Private</p>").url is None
    with pytest.raises(ValidationError):
        native.InstapaperTokenCredential(access_token="Bearer " + TOKEN)
