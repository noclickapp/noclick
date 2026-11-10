"""Request contract and stateful news detection against Owler's published schemas."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential
from nodes.owler_node import OwlerNode, OwlerAPIKeyCredential

FIXTURE = json.loads((Path(__file__).parent / "fixtures/owler/schema_payloads.json").read_text())
CREDENTIAL = {"credential_type": "owler_api_key", "api_key": "test-owler-api-key"}


def node(config):
    return NodeFactory.create_node(node_id="owler-test", node_type="automation-owler",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize("operation,fields,path,params", [
    ("get_company_by_id", {"company_id": "100486"}, "/v1/companypremium/id/100486", {}),
    ("get_company_by_website", {"website": "owler.com"}, "/v1/companypremium/url/owler.com", {}),
    ("get_competitors_by_id", {"company_id": "100486"}, "/v1/company/competitorpremium/id/100486", {"pagination_id": "*"}),
    ("get_competitors_by_website", {"website": "owler.com", "pagination_id": "cursor-2"}, "/v1/company/competitorpremium/url/owler.com", {"pagination_id": "cursor-2"}),
    ("get_feeds_by_id", {"company_id": "100486, 100487", "category": "FUNDING", "limit": 50}, "/v1/feed", {"company_id": "100486,100487", "category": "FUNDING", "limit": "50"}),
    ("get_funding_news", {"company_id": "100486"}, "/v1/feed", {"company_id": "100486", "category": "FUNDING", "limit": "10"}),
    ("get_acquisition_news", {"company_id": "100486"}, "/v1/feed", {"company_id": "100486", "category": "ACQUISITION", "limit": "10"}),
    ("get_people_news", {"company_id": "100486"}, "/v1/feed", {"company_id": "100486", "category": "PEOPLE", "limit": "10"}),
    ("get_press_releases", {"company_id": "100486"}, "/v1/feed", {"company_id": "100486", "category": "PRESS", "limit": "10"}),
    ("get_feeds_by_website", {"domain": "owler.com", "pagination_id": "next"}, "/v1/feed/url", {"domain": "owler.com", "limit": "10", "pagination_id": "next"}),
])
@pytest.mark.asyncio
async def test_owler_request_and_response(monkeypatch, operation, fields, path, params):
    body = FIXTURE["feedresults" if path.startswith("/v1/feed") else "competitors" if "competitors" in operation else "companyPremium"]
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "apiv2.owler.com"
        assert request.url.path == path
        assert dict(request.url.params) == {"format": "json", **params}
        assert request.headers["x-api-key"] == CREDENTIAL["api_key"]
        assert "authorization" not in request.headers
        assert not request.content
        return httpx.Response(200, json=body)
    transport(monkeypatch, handler)
    assert await node({"operation": operation, **fields}).execute({}) == body
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_owler_rejection(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(403, text="Authentication Failed"))
    with pytest.raises(ValueError, match="403: Authentication Failed"):
        await node({"operation": "get_company_by_id", "company_id": "100486"}).execute({})


@pytest.mark.parametrize("operation,fields,path,query", [
    ("on_new_feed_by_id", {"company_id": "100486", "category": "NEWS"}, "/v1/feed", {"company_id": "100486", "category": "NEWS"}),
    ("on_new_feed_by_website", {"domain": "owler.com"}, "/v1/feed/url", {"domain": "owler.com"}),
])
@pytest.mark.asyncio
async def test_owler_poll_baseline_dedup_and_repoint(monkeypatch, operation, fields, path, query):
    body = copy.deepcopy(FIXTURE["feedresults"])
    def handler(request):
        assert request.url.path == path
        assert dict(request.url.params) == {"format": "json", "limit": "100", **query}
        return httpx.Response(200, json=body)
    transport(monkeypatch, handler)
    instance = node({"operation": operation, **fields})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(copy.deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    instance._update_node_state = update
    assert (await instance.execute({}))["new_feed_count"] == 0
    body["feed"][0]["id"] = "news-2"
    result = await instance.execute({})
    assert result["new_feed_count"] == 1
    event = OwlerNode.resolve_agent_event(result)
    assert "news-2" in event["text"]
    assert body["feed"][0]["title"] in event["text"]
    assert body["feed"][0]["company"]["name"] in event["text"]
    assert body["feed"][0]["source_url"] in event["text"]
    assert instance.trigger_emitted_event(result)
    result = await instance.execute({})
    assert result["new_feed_count"] == 0
    assert instance.trigger_produced_no_event(result)
    assert OwlerNode.resolve_agent_event(result) is None
    state["scope"] = "previous-scope"
    body["feed"][0]["id"] = "news-3"
    assert (await instance.execute({}))["new_feed_count"] == 0


def test_owler_manual_credential_and_bounds():
    shaped, errors, resolved = shape_credential("owler_api_key", {"api_key": "working-owler-api-key"})
    assert not errors
    assert resolved is not None
    assert OwlerAPIKeyCredential.model_validate(shaped).credential_type == "owler_api_key"
    for config in [
        {"operation": "get_feeds_by_id", "company_id": ","},
        {"operation": "get_feeds_by_id", "company_id": ",".join(str(i) for i in range(11))},
        {"operation": "get_feeds_by_website", "domain": "owler.com", "limit": 101},
        {"operation": "on_new_feed_by_id", "company_id": "100486", "category": "invented"},
    ]:
        assert not OwlerNode.validate_config({"config": config})["valid"]
