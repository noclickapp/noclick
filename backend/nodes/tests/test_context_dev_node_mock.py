"""Exercise Context.dev request serialization and response semantics without an account.

The documented usage fixture proves the connection read handles real provider JSON.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import context_dev_node as native
from nodes.core.registry import NodeFactory

TOKEN = "ctxt_secret_fixture_42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="context-test", node_type="automation-context-dev",
        node_data={"config": config, "credentials": credentials or {"api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_account_usage_documented_response_and_auth(monkeypatch):
    data = json.loads((Path(__file__).parent / "fixtures/context-dev/usage.json").read_text())
    requests = transport(monkeypatch, data)
    result = await node({"operation": "get_usage"}).execute({})
    assert result["status"] == "success" and result["data"] == data
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.context.dev/v1/org/usage"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", [
    ({"operation": "scrape_web", "url": "https://stripe.com"}, "POST", "/web/scrape", {"url": "https://stripe.com", "formats": {"markdown": True}, "maxAgeMs": 259200000}),
    ({"operation": "search_web", "query": "pricing", "freshness": "last_week"}, "POST", "/web/search", {"query": "pricing", "numResults": 10, "freshness": "last_week"}),
    ({"operation": "crawl_website", "url": "https://stripe.com"}, "POST", "/web/crawl", {"url": "https://stripe.com", "maxPages": 10, "maxDepth": 1, "useMainContentOnly": True}),
    ({"operation": "answer_research", "task": "Find pricing", "json_format": {"price": 0}}, "POST", "/web/answers", {"task": "Find pricing", "mode": "fast", "json_format": {"price": 0}}),
    ({"operation": "search_news", "query": "chip exports", "cursor": "opaque-next"}, "POST", "/news/search", {"searchBy": {"type": "natural_language", "query": "chip exports"}, "limit": 10, "cursor": "opaque-next"}),
    ({"operation": "retrieve_brand", "domain": "stripe.com"}, "POST", "/brand/retrieve", {"type": "by_domain", "domain": "stripe.com"}),
    ({"operation": "enrich_person", "email": "person@company.com"}, "POST", "/people/enrich", {"email": "person@company.com"}),
    ({"operation": "create_monitor", "name": "Pricing", "url": "https://acme.com/pricing", "instructions": "Report pricing changes"}, "POST", "/monitors", {"name": "Pricing", "target": {"type": "page", "url": "https://acme.com/pricing", "instructions": "Report pricing changes"}, "schedule": {"type": "interval", "frequency": 1, "unit": "days"}}),
    ({"operation": "update_monitor", "monitor_id": "mon_123", "status": "paused"}, "PATCH", "/monitors/mon_123", {"status": "paused"}),
    ({"operation": "delete_monitor", "monitor_id": "mon_123"}, "DELETE", "/monitors/mon_123", None),
    ({"operation": "run_monitor", "monitor_id": "mon_123"}, "POST", "/monitors/mon_123/run", None),
])
async def test_write_and_research_wire_contract(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, {"request_id": "fixture"})
    await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/v1" + path
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,params", [
    ({"operation": "map_urls", "domain": "stripe.com"}, "/web/urls", {"domain": "stripe.com", "maxLinks": "1000", "includeSubdomains": "false"}),
    ({"operation": "search_brands", "query": "stripe"}, "/brand/search", {"query": "stripe"}),
    ({"operation": "get_usage_history", "group_by": "path"}, "/org/usage/history", {"interval": "day", "group_by": "path"}),
    ({"operation": "list_monitors", "q": "pricing", "cursor": "abc+/="}, "/monitors", {"q": "pricing", "limit": "25", "cursor": "abc+/="}),
    ({"operation": "get_monitor", "monitor_id": "mon_123"}, "/monitors/mon_123", {}),
    ({"operation": "list_monitor_runs", "monitor_id": "mon_123", "status": "completed"}, "/monitors/mon_123/runs", {"limit": "25", "status": "completed"}),
    ({"operation": "get_monitor_run", "monitor_id": "mon_123", "run_id": "run_123"}, "/monitors/mon_123/runs/run_123", {}),
    ({"operation": "list_monitor_changes", "monitor_id": "mon_123", "tag": "pricing"}, "/monitors/mon_123/changes", {"limit": "25", "tag": "pricing"}),
])
async def test_get_queries_and_explicit_pagination(monkeypatch, config, path, params):
    data = {"data": [], "next_cursor": "https://evil.example/next", "has_more": True}
    requests = transport(monkeypatch, data)
    result = await node(config).execute({})
    assert len(requests) == 1
    assert requests[0].method == "GET" and requests[0].url.path == "/v1" + path
    assert dict(requests[0].url.params) == params
    assert result["data"] == data


@pytest.mark.asyncio
async def test_queue_acknowledgement_preserves_status_without_polling(monkeypatch):
    requests = transport(monkeypatch, {"run_id": "run_123", "status": "queued"}, 202)
    result = await node({"operation": "run_monitor", "monitor_id": "mon_123"}).execute({})
    assert result["http_status"] == 202 and result["data"]["status"] == "queued"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409, 429, 500])
async def test_provider_errors_and_secret_redaction(monkeypatch, status):
    transport(monkeypatch, {"error": {"message": "Key rejected " + TOKEN}}, status)
    result = await node({"operation": "get_usage"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Key rejected" in str(result) and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_nested_secret_not_exposed(monkeypatch):
    transport(monkeypatch, {"data": [{"value": TOKEN}], TOKEN: "echo"})
    assert TOKEN not in str(await node({"operation": "get_usage"}).execute({}))


@pytest.mark.parametrize("config", [
    {"operation": "get_monitor", "monitor_id": "../usage"},
    {"operation": "get_monitor_run", "monitor_id": "mon_123", "run_id": "run?x=1"},
    {"operation": "create_monitor", "name": "Pricing", "url": "https://example.com", "frequency_days": 366},
    {"operation": "update_monitor", "monitor_id": "mon_123"},
    {"operation": "search_web", "query": "pricing", "num_results": 101},
    {"operation": "scrape_web", "url": "file:///etc/passwd"},
    {"operation": "get_usage_history", "from_time": "2026-10-01T00:00:00Z", "to_time": "2026-09-01T00:00:00Z"},
])
def test_invalid_inputs_fail_before_network(config):
    assert native.ContextDevNode.validate_config({"config": config})["valid"] is False


def test_manual_key_has_default_type_and_rejects_headers():
    assert native.ContextDevAPIKeyCredential(api_key=TOKEN).credential_type == "context_dev_api_key"
    with pytest.raises(ValidationError):
        native.ContextDevAPIKeyCredential(api_key="Bearer " + TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", ["scrape-markdown.json", "scrape-partial.json"])
async def test_documented_scrape_response_metadata_and_partial_outputs(monkeypatch, fixture):
    # Official examples include sourceUrl/finalUrl even though ScrapeMetadata omits them.
    data = json.loads((Path(__file__).parent / "fixtures/context-dev" / fixture).read_text())
    requests = transport(monkeypatch, data)
    result = await node({"operation": "scrape_web", "url": "https://example.com"}).execute({})
    assert len(requests) == 1 and result["data"] == data
    assert result["data"]["metadata"]["sourceUrl"].startswith("https://example.com")
    assert result["data"]["metadata"]["finalUrl"] == "https://example.com/"
    assert result["data"]["markdown"]["success"] is True
    if fixture == "scrape-partial.json":
        assert any(isinstance(v, dict) and v.get("success") is False for v in result["data"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reachable", [(401, False), (403, False), (500, None)])
async def test_connection_evidence_distinguishes_rejection_from_provider_failure(monkeypatch, status, reachable):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence

    transport(monkeypatch, {"message": "The request could not be completed"}, status)
    async def run(**kwargs):
        return await node({"operation": kwargs["operation"]}, kwargs["credential_data"]).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run)
    result = await collect_evidence(node_type="automation-context-dev", user_id="fixture-user",
        credential_data={"api_key": TOKEN})
    assert result.reachable is reachable
    if reachable is False:
        assert "The request could not be completed" in result.error
