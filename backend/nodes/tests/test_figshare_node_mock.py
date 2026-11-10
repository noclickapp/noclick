"""Figshare transport, documented field examples and poll lifecycle regressions."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import figshare_node as provider
from nodes.core.registry import NodeFactory
from utils import ssrf

TOKEN = "fixture-personal-token"
AUTH = {"credential_type": "figshare_personal_token", "personal_token": TOKEN}
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/figshare/documented_examples.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        calls.append(request)
        assert request.url.host == "api.figshare.com"
        assert request.headers["Authorization"] == "token " + TOKEN
        assert TOKEN not in str(request.url)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(provider, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return calls, responses


def node(operation, **fields):
    return NodeFactory.create_node(node_id="figshare-test", node_type="automation-figshare",
        node_data={"config": {"operation": operation, **fields}, "credentials": deepcopy(AUTH)})


CASES = [
    ("get_account", {}, "GET", "/account", "Account"),
    ("list_public_articles", {}, "GET", "/articles", "Article"),
    ("search_public_articles", {"search_for": "figshare"}, "POST", "/articles/search", "Article"),
    ("get_public_article", {"article_id": 1434614}, "GET", "/articles/1434614", "Article"),
    ("list_article_versions", {"article_id": 1434614}, "GET", "/articles/1434614/versions", None),
    ("list_public_article_files", {"article_id": 1434614}, "GET", "/articles/1434614/files", None),
    ("list_articles", {}, "GET", "/account/articles", "Article"),
    ("get_article", {"article_id": 1434614}, "GET", "/account/articles/1434614", "Article"),
    ("create_article", {"title": "Test article title"}, "POST", "/account/articles", None),
    ("update_article", {"article_id": 1434614, "description": "Test description of article"}, "PUT", "/account/articles/1434614", None),
    ("delete_article", {"article_id": 1434614}, "DELETE", "/account/articles/1434614", None),
    ("publish_article", {"article_id": 1434614}, "POST", "/account/articles/1434614/publish", None),
    ("reserve_article_doi", {"article_id": 1434614}, "POST", "/account/articles/1434614/reserve_doi", None),
    ("list_article_files", {"article_id": 1434614}, "GET", "/account/articles/1434614/files", None),
    ("list_collections", {}, "GET", "/account/collections", "Collection"),
    ("get_collection", {"collection_id": 123}, "GET", "/account/collections/123", "Collection"),
    ("create_collection", {"title": "Test collection title"}, "POST", "/account/collections", None),
    ("update_collection", {"collection_id": 123, "title": "Test collection title"}, "PATCH", "/account/collections/123", None),
    ("delete_collection", {"collection_id": 123}, "DELETE", "/account/collections/123", None),
    ("list_collection_articles", {"collection_id": 123}, "GET", "/account/collections/123/articles", "Article"),
    ("add_collection_articles", {"collection_id": 123, "articles": [2000003, 2000004]}, "POST", "/account/collections/123/articles", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,example", CASES)
async def test_native_transport_routes_and_response_preservation(transport, operation, config, method, path, example):
    calls, replies = transport
    payload = deepcopy(EXAMPLES[example]) if example else {"location": "https://api.figshare.com/v2/account/articles/1434614"}
    if operation.startswith("list_") or operation == "search_public_articles": payload = [payload]
    replies.append((200 if method == "GET" or operation == "search_public_articles" else 201, payload))
    result = await node(operation, **config).execute({})
    assert result["data"] == payload
    assert len(calls) == 1
    assert calls[0].method == method
    assert calls[0].url.path == "/v2" + path
    if operation in ("create_article", "create_collection", "add_collection_articles", "update_article", "update_collection"):
        assert json.loads(calls[0].content) == {k: v for k, v in config.items() if k not in ("article_id", "collection_id")}


@pytest.mark.asyncio
async def test_pagination_filters_and_false_metadata_preserved(transport):
    calls, replies = transport
    replies.extend([(200, []), (205, None)])
    await node("list_public_articles", institution=2000013, modified_since="2017-12-22", page=2, page_size=10).execute({})
    assert dict(calls[0].url.params) == {"page": "2", "page_size": "10", "order": "modified_date", "order_direction": "desc", "institution": "2000013", "modified_since": "2017-12-22"}
    result = await node("update_article", article_id=1434614, is_metadata_record=False, license=0, tags=[]).execute({})
    assert json.loads(calls[1].content) == {"is_metadata_record": False, "license": 0, "tags": []}
    assert result == {"data": {"ok": True}}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 429, 500])
async def test_rejection_is_not_success_and_token_is_redacted(transport, code):
    _, replies = transport
    replies.append((code, {"message": "denied " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node("get_account").execute({})
    assert TOKEN not in str(exc.value)
    assert str(code) in str(exc.value)
    assert "denied" in str(exc.value)


@pytest.mark.parametrize("fields", [{"article_id": "../account"}, {"article_id": 0}, {"article_id": -1}])
def test_article_id_validation(fields):
    with pytest.raises(ValidationError):
        provider.FigshareNodeConfig.model_validate({"config": {"operation": "get_article", **fields}, "credentials": AUTH})


def test_manual_token_has_default_type_and_rejects_header_injection():
    credential = provider.FigsharePersonalTokenCredential(personal_token=TOKEN)
    assert credential.credential_type == AUTH["credential_type"]
    with pytest.raises(ValidationError):
        provider.FigsharePersonalTokenCredential(personal_token="token abc\r\nX-Header: evil")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example", [("on_public_article_updated", "Article"), ("on_new_collection", "Collection")])
async def test_poll_baseline_dedup_new_item_and_article_update(transport, operation, example):
    calls, replies = transport
    current = node(operation)
    state = {}
    async def update(mutator, **kwargs):
        new, result = mutator(deepcopy(state))
        if new is not None: state.clear(); state.update(new)
        return result
    current._update_node_state = update
    row = deepcopy(EXAMPLES[example])
    replies.append((200, [row]))
    assert (await current.execute({}))["count"] == 0
    replies.append((200, [row]))
    assert (await current.execute({}))["count"] == 0
    newer = {**row, "id": row["id"] + 1}
    replies.append((200, [newer, row]))
    output = await current.execute({})
    assert output["items"] == [newer]
    event = provider.FigshareNode.resolve_agent_event(output)
    assert str(newer["id"]) in event["text"] and newer["title"] in event["text"]
    assert dict(calls[-1].url.params) == {"page": "1", "page_size": "1000", "order": "modified_date", "order_direction": "desc"}
    if example == "Article":
        changed = {**row, "modified_date": "2018-05-22T04:04:04Z"}
        replies.append((200, [changed]))
        assert (await current.execute({}))["items"] == [changed]
    assert "scope" in state


@pytest.mark.asyncio
async def test_poll_filters_are_scoped_and_empty_or_bad_lists(transport):
    calls, replies = transport
    current = node("on_public_article_updated", institution=2000013, group=2000013, modified_since="2017-12-22")
    current._filter_unseen = AsyncMock(return_value=[])
    replies.append((200, []))
    assert (await current.execute({}))["count"] == 0
    assert provider.FigshareNode.resolve_agent_event({"items": []}) is None
    assert calls[0].url.params["institution"] == "2000013"
    replies.append((200, {"unexpected": []}))
    with pytest.raises(ValueError, match="array"):
        await current.execute({})


@pytest.mark.asyncio
async def test_search_uses_only_its_declared_pagination_fields(transport):
    calls, replies = transport
    replies.append((200, []))
    await node("search_public_articles", search_for="figshare", limit=10, offset=10).execute({})
    assert not calls[0].url.params
    assert json.loads(calls[0].content) == {"search_for": "figshare", "limit": 10, "offset": 10,
        "order": "modified_date", "order_direction": "desc"}
    assert "page" not in provider.FigshareSearchPublicArticlesConfig.model_fields
    assert "page_size" not in provider.FigshareSearchPublicArticlesConfig.model_fields
