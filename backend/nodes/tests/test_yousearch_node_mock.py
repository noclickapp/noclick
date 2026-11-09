"""Native factory tests using published You.com examples and synthetic errors.

Fixtures copied from https://you.com/docs/api-reference/search/v1-search.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import yousearch_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

KEY = "synthetic-yousearch-key"
FIXTURE = Path(__file__).parent / "fixtures/yousearch/highlights.json"


def node(config=None):
    return NodeFactory.create_node(node_id="search-test", node_type="automation-yousearch",
        node_data={"config": config or {"operation": "search_web", "query": "You.com"},
            "credentials": {"credential_type": "yousearch_api_key", "api_key": KEY}})


def transport(monkeypatch, response):
    requests = []
    def handler(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    real_client = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


def test_discovery_and_manual_credential():
    assert NODE_REGISTRY["automation-yousearch"] is native.YousearchNode
    credential = native.YousearchAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.api_key == KEY and credential.credential_type == "yousearch_api_key"
    assert native.YousearchNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
async def test_documented_highlights_response_and_exact_request(monkeypatch):
    documented = json.loads(FIXTURE.read_text())
    requests = transport(monkeypatch, documented)
    result = await node({"operation": "search_web",
        "query": "what is the difference between JWT and session authentication",
        "extraction_mode": "highlights", "total_max_tokens": 2048, "count": 10}).execute({})
    assert result == {"status": "success", "data": documented}
    request = requests[0]
    assert request.method == "POST" and str(request.url) == "https://ydc-index.io/v1/search"
    assert request.headers["X-API-Key"] == KEY and "authorization" not in request.headers
    body = json.loads(request.content)
    assert body["extraction"] == {"extraction_mode": "highlights", "highlights": {"total_max_tokens": 2048}}
    assert "operation" not in body and "total_max_tokens" not in body
    assert "snippets" not in result["data"]["results"]["web"][0]


@pytest.mark.asyncio
async def test_full_page_filters_pagination_and_knowledge(monkeypatch):
    payload = {"results": {"web": [{"contents": {"markdown": "# You", "html": "<h1>You</h1>"}}],
        "knowledge": [{"type": "future-kind", "title": "Future", "attribution": [{"name": "Provider"}]}]}}
    requests = transport(monkeypatch, payload)
    config = {"operation": "search_web", "query": "AI news", "count": 20, "offset": 2,
        "country": "IN", "language": "EN", "freshness": "week", "safesearch": "strict",
        "exclude_domains": "example.com, spam.test", "boost_domains": "you.com", "knowledge": "core",
        "strict_operators": True, "extraction_mode": "full_page", "extraction_source": "cache",
        "extraction_formats": "both", "crawl_timeout": 30}
    assert (await node(config).execute({}))["data"] == payload
    body = json.loads(requests[0].content)
    assert body["exclude_domains"] == ["example.com", "spam.test"]
    assert body["boost_domains"] == ["you.com"]
    assert body["extraction"] == {"extraction_mode": "full_page", "extraction_source": "cache",
        "full_page": {"extraction_formats": ["markdown", "html"]}}
    assert body["offset"] == 2 and body["count"] == 20 and body["crawl_timeout"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"results": {}}, {"results": {"web": []}}, {"metadata": {"query": "test"}}])
async def test_optional_response_fields_and_empty_results(monkeypatch, payload):
    transport(monkeypatch, payload)
    assert await node().execute({}) == {"status": "success", "data": payload}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,message", [(401, {"detail": "Invalid API key"}, "Invalid API key"),
    (402, {"error": "credits", "message": "Upgrade required", "upgrade_url": "https://you.com/platform"}, "Upgrade required"),
    (403, {"detail": "Forbidden"}, "Forbidden"), (422, {"error": "Bad parameters"}, "Bad parameters"),
    (500, {"detail": "Internal error"}, "Internal error"), (429, {"message": "Rate limit"}, "Rate limit"),
    (401, {"detail": KEY}, "[redacted]")])
async def test_provider_errors(monkeypatch, status, payload, message):
    transport(monkeypatch, lambda r: httpx.Response(status, json=payload))
    assert await node().execute({}) == {"status": "error", "status_code": status, "error": message}


@pytest.mark.asyncio
async def test_redirect_is_not_followed(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(302, headers={"location": "https://elsewhere.test"}, text="redirect"))
    assert (await node().execute({}))["status"] == "error"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_network_failure(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("Timed out", request=request)
    transport(monkeypatch, fail)
    assert (await node().execute({}))["status"] == "error"


@pytest.mark.parametrize("changes", [
    {"count": 0}, {"count": 101}, {"offset": 10}, {"country": "ZZ"}, {"language": "XX"},
    {"include_domains": "a.test", "exclude_domains": "b.test"},
    {"include_domains": "a.test", "boost_domains": "b.test"},
    {"extraction_mode": "highlights", "count": 51},
    {"extraction_mode": "highlights", "extraction_source": "blend"},
    {"extraction_mode": "highlights", "crawl_timeout": 10},
    {"extraction_mode": "highlights", "extraction_formats": "html"},
    {"total_max_tokens": 1024}, {"total_max_tokens": 8193, "extraction_mode": "highlights"},
    {"freshness": "yesterday"}, {"freshness": "2026-02-30to2026-03-01"},
    {"freshness": "2026-11-09to2026-11-01"}, {"include_domains": "a.test,,b.test"},
    {"boost_domains": ",".join(["a.test"] * 501)},
])
def test_invalid_parameters(changes):
    with pytest.raises(ValidationError):
        native.YousearchSearchConfig(query="test", **changes)


def test_snippets_default_and_domain_allowlist():
    body = native.YousearchSearchConfig(query="test", include_domains="you.com, docs.you.com").request_body()
    assert body["include_domains"] == ["you.com", "docs.you.com"]
    assert not {"extraction", "crawl_timeout", "livecrawl", "livecrawl_formats"} & body.keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["snippets", "knowledge", "full_page"])
async def test_other_published_response_variants(monkeypatch, kind):
    payload = json.loads(FIXTURE.with_name(kind + ".json").read_text())
    transport(monkeypatch, payload)
    assert (await node().execute({}))["data"] == payload


@pytest.mark.parametrize("value", ["https://you.com/platform", "<api-key>", "has space", "curly‘quote"])
def test_bad_keys_are_rejected_without_exposing_input(value):
    with pytest.raises(ValidationError) as error:
        native.YousearchAPIKeyCredential(api_key=value)
    assert value not in str(error.value)
