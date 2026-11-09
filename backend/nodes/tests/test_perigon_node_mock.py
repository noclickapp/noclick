"""Factory HTTP contracts using publisher examples from https://perigon.io/openapi.json (1.0.0)."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import perigon_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-perigon-key-42"
RESPONSES = json.loads((Path(__file__).parent / "fixtures/perigon/responses.json").read_text())
CASES = [
    ("search_articles", {}, "GET", "/v1/articles/all", None),
    ("search_stories", {}, "GET", "/v1/stories/all", None),
    ("search_sources", {}, "GET", "/v1/sources/all", None),
    ("search_companies", {}, "GET", "/v1/companies/all", None),
    ("search_people", {}, "GET", "/v1/people/all", None),
    ("search_journalists", {}, "GET", "/v1/journalists/all", None),
    ("search_topics", {}, "GET", "/v1/topics/all", None),
    ("get_limits", {}, "GET", "/v1/limits", None),
    ("list_source_groups", {}, "GET", "/v1/api/sourceGroups", None),
    ("create_source_group", {"name": "tier-1-tech", "domains": ["reuters.com"]}, "POST", "/v1/api/sourceGroups", {"name": "tier-1-tech", "domains": ["reuters.com"]}),
    ("resolve_source_groups", {"name": ["tier-1-tech"]}, "GET", "/v1/api/sourceGroups/resolve", None),
    ("get_source_group", {"id": 17}, "GET", "/v1/api/sourceGroups/17", None),
    ("update_source_group", {"id": 17, "displayName": "Tier 1 Tech"}, "PATCH", "/v1/api/sourceGroups/17", {"displayName": "Tier 1 Tech"}),
    ("delete_source_group", {"id": 17}, "DELETE", "/v1/api/sourceGroups/17", None),
    ("list_watchlists", {}, "GET", "/v1/api/watchlists", None),
    ("create_watchlist", {"name": "ai-executives", "people": [{"name": "Sam Altman", "wikidataId": "Q7411063"}], "companies": []}, "POST", "/v1/api/watchlists", {"name": "ai-executives", "people": [{"name": "Sam Altman", "wikidataId": "Q7411063"}], "companies": []}),
    ("resolve_watchlists", {"name": ["ai-executives"]}, "GET", "/v1/api/watchlists/resolve", None),
    ("get_watchlist", {"id": 42}, "GET", "/v1/api/watchlists/42", None),
    ("update_watchlist", {"id": 42, "companies": [], "visible": False}, "PATCH", "/v1/api/watchlists/42", {"companies": [], "visible": False}),
    ("delete_watchlist", {"id": 42}, "DELETE", "/v1/api/watchlists/42", None),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="perigon-test", node_type="automation-perigon", node_data={
        "config": config, "credentials": {"credential_type": "perigon_api_key", "api_key": TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", CASES)
async def test_publisher_examples_through_factory(monkeypatch, operation, config, method, path, body):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=RESPONSES[operation]))
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success" and TOKEN not in str(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.perigon.io" and request.url.scheme == "https"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"sortBy": "id", "sortOrder": "asc", "page": "0", "size": "10"}
    if operation == "get_limits":
        assert result["organizationName"] == "Acme Research" and not request.url.query


@pytest.mark.asyncio
async def test_query_arrays_dates_and_pagination(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=RESPONSES["search_articles"]))
    await node({"operation": "search_articles", "q": "AI + chips", "source": ["reuters.com", "apnews.com"], "from": "2025-08-01T00:00:00Z", "page": 3, "size": 25}).execute({})
    params = requests[0].url.params
    assert params.get_list("source") == ["reuters.com", "apnews.com"]
    assert params["from"] == "2025-08-01T00:00:00Z" and params["q"] == "AI + chips"
    assert params["page"] == "3" and params["size"] == "25"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_error_rejection_wording_and_no_secret_echo(monkeypatch, status):
    transport(monkeypatch, lambda _: httpx.Response(status, json={"message": "Invalid API key. " + TOKEN}))
    result = await node({"operation": "get_limits"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Invalid API key. [redacted]"}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"data": None}, {"data": [], "message": "Failure"}])
async def test_incomplete_limits_never_prove_connection(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "get_limits"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "create_source_group", "name": "x", "domains": []},
    {"operation": "get_watchlist", "id": "../other"},
    {"operation": "list_watchlists", "size": 101},
    {"operation": "create_watchlist", "name": "x"},
    {"operation": "search_articles", "page": -1},
])
def test_invalid_config_rejected(config):
    assert not native.PerigonNode.validate_config({"config": config})["valid"]


def test_manual_credential_has_default_tag_and_rejects_header_injection():
    assert native.PerigonApiKeyCredential(api_key=TOKEN).credential_type == "perigon_api_key"
    for bad in ["", "Bearer abc", "abc\r\nx-test: yes"]:
        with pytest.raises(ValidationError):
            native.PerigonApiKeyCredential(api_key=bad)
