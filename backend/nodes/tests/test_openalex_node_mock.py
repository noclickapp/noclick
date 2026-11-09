"""Factory-level wire, paging, error and credential regressions; synthetic keys."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import openalex_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-openalex-key-42"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/openalex/responses.json").read_text())
ENTITIES = {"works": "work", "authors": "author", "sources": "source", "institutions": "institution", "topics": "topic", "keywords": "keyword", "publishers": "publisher", "funders": "funder", "domains": "domain", "fields": "field", "subfields": "subfield"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="openalex-test", node_type="automation-openalex",
        node_data={"config": config, "credentials": {"credential_type": "openalex_api_key", "api_key": KEY}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("plural,singular", ENTITIES.items())
@pytest.mark.parametrize("detail", [False, True])
async def test_all_entity_operations_one_fixed_authenticated_request(monkeypatch, plural, singular, detail):
    body = FIXTURE["singleton" if detail else "list"]
    requests = transport(monkeypatch, body)
    config = {"operation": "get_" + singular, "id": "123"} if detail else {"operation": "list_" + plural}
    n = node(config)
    n.emit = AsyncMock()
    result = await n.execute({})
    assert result["status"] == "success"
    request, = requests
    assert request.method == "GET" and request.url.host == "api.openalex.org"
    assert request.url.path == "/" + plural + ("/123" if detail else "")
    assert dict(request.url.params) == {"api_key": KEY, **({} if detail else {"per_page": "25"})}
    assert "authorization" not in request.headers
    n.emit.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_filters_grouping_select_cursor_and_external_identifier(monkeypatch):
    requests = transport(monkeypatch, FIXTURE["list"])
    cfg = {"operation": "list_works", "search": "machine learning", "filter": "publication_year:2024", "sort": "cited_by_count:desc", "group_by": "publication_year", "select": "id,display_name", "cursor": "*", "per_page": 100}
    result = await node(cfg).execute({})
    assert dict(requests[0].url.params) == {k: str(v) for k, v in cfg.items() if k != "operation"} | {"api_key": KEY}
    assert result["meta"]["next_cursor"] == "opaque-next" and result["group_by"] == []
    requests = transport(monkeypatch, FIXTURE["singleton"])
    await node({"operation": "get_work", "id": "https://doi.org/10.7717/peerj.4375"}).execute({})
    assert b"https%3A%2F%2Fdoi.org%2F10.7717%2Fpeerj.4375" in requests[0].url.raw_path
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_autocomplete_encodes_user_query_and_empty_last_page(monkeypatch):
    requests = transport(monkeypatch, {"results": [], "meta": {"count": 0}})
    result = await node({"operation": "autocomplete", "entity_type": "authors", "q": "Smith & Jones"}).execute({})
    assert result["results"] == [] and requests[0].url.path == "/autocomplete/authors"
    assert requests[0].url.params["q"] == "Smith & Jones"
    transport(monkeypatch, {"results": [], "meta": {"next_cursor": None}})
    assert (await node({"operation": "list_works", "cursor": "last"}).execute({}))["meta"]["next_cursor"] is None


@pytest.mark.asyncio
async def test_usage_probe_removes_key_from_response_and_emitted_output(monkeypatch):
    requests = transport(monkeypatch, {"api_key": KEY, "rate_limit": {"daily_remaining_usd": 0.99, "nested": [KEY]}})
    result = await node({"operation": "get_rate_limit"}).execute({})
    assert result["rate_limit"]["daily_remaining_usd"] == 0.99
    assert KEY not in str(result) and "api_key" not in result
    assert requests[0].url.path == "/rate-limit" and dict(requests[0].url.params) == {"api_key": KEY}
    evidence = native.OpenAlexNode.connection_evidence
    assert evidence.operation == "get_rate_limit" and evidence.proves == "reachability"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_failures_preserve_provider_message_without_secret(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Rejected " + KEY}, status)
    result = await node({"operation": "get_rate_limit"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("config,body", [({"operation": "list_works"}, {}), ({"operation": "get_rate_limit"}, {}), ({"operation": "get_work", "id": "W1"}, []), ({"operation": "list_authors"}, {"error": "Invalid"})])
async def test_unexpected_response_never_reports_success(monkeypatch, config, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node(config).execute({})


def test_manual_credential_default_and_pagination_validation():
    credential = native.OpenAlexAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == "openalex_api_key"
    for config in [{"operation": "list_works", "page": 1, "cursor": "*"}, {"operation": "list_works", "per_page": 101}, {"operation": "list_works", "page": 401}, {"operation": "get_work", "id": ".."}, {"operation": "create_work"}]:
        with pytest.raises(ValueError):
            native.OpenAlexNode.parse_config({"config": config})
