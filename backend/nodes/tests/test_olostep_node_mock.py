"""Exercise Olostep through the real node factory with an isolated HTTP transport.

Requests cover each operation, pagination and documented response envelopes.
No live provider account or billable request is used.
"""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import olostep_node as native
from nodes.core.registry import NodeFactory

TOKEN = "test-olostep-secret-42"
CASES = [
    ({"operation": "create_scrape", "url_to_scrape": "https://example.com", "formats": ["markdown"]}, "POST", "/v1/scrapes"),
    ({"operation": "get_scrape", "scrape_id": "scrape_abc"}, "GET", "/v1/scrapes/scrape_abc"),
    ({"operation": "list_recent_batches", "limit": 10}, "GET", "/v1/batches/recent"),
    ({"operation": "create_batch", "items": [{"url": "https://example.com", "custom_id": "product-1"}]}, "POST", "/v1/batches"),
    ({"operation": "get_batch", "batch_id": "batch_abc"}, "GET", "/v1/batches/batch_abc"),
    ({"operation": "update_batch_metadata", "batch_id": "batch_abc", "metadata": {"status": "reviewed"}}, "PATCH", "/v1/batches/batch_abc"),
    ({"operation": "list_batch_items", "batch_id": "batch_abc", "cursor": 20, "limit": 10}, "GET", "/v1/batches/batch_abc/items"),
    ({"operation": "create_crawl", "start_url": "https://example.com", "max_pages": 10}, "POST", "/v1/crawls"),
    ({"operation": "get_crawl", "crawl_id": "crawl_abc"}, "GET", "/v1/crawls/crawl_abc"),
    ({"operation": "list_crawl_pages", "crawl_id": "crawl_abc", "formats": ["html", "markdown"], "cursor": 4}, "GET", "/v1/crawls/crawl_abc/pages"),
    ({"operation": "create_map", "url": "https://example.com", "cursor": "next-page"}, "POST", "/v1/maps"),
    ({"operation": "get_map", "map_id": "map_abc"}, "GET", "/v1/maps/map_abc"),
    ({"operation": "create_answer", "task": "Find the company's founders", "json_format": {"founders": ["name"]}}, "POST", "/v1/answers"),
    ({"operation": "get_answer", "answer_id": "answer_abc"}, "GET", "/v1/answers/answer_abc"),
    ({"operation": "create_search", "query": "Olostep API", "limit": 5, "scrape_options": {"formats": ["markdown"]}}, "POST", "/v1/searches"),
    ({"operation": "get_search", "search_id": "search_abc"}, "GET", "/v1/searches/search_abc"),
    ({"operation": "create_schedule", "method": "POST", "endpoint": "v1/scrapes", "payload": {"url_to_scrape": "https://example.com"}, "text": "every 3 minutes"}, "POST", "/v1/schedules"),
    ({"operation": "list_schedules", "include_deleted": "true"}, "GET", "/v1/schedules"),
    ({"operation": "get_schedule", "schedule_id": "schedule_abc"}, "GET", "/v1/schedules/schedule_abc"),
    ({"operation": "delete_schedule", "schedule_id": "schedule_abc"}, "DELETE", "/v1/schedules/schedule_abc"),
    ({"operation": "get_credit_info"}, "GET", "/user/credits/info"),
]


def node(config):
    return NodeFactory.create_node(node_id="olostep-test", node_type="automation-olostep", node_data={
        "config": config, "credentials": {"credential_type": "olostep_api_key", "api_key": TOKEN}})


def mock_http(monkeypatch, response):
    requests = []
    def handle(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES, ids=[v[0]["operation"] for v in CASES])
async def test_all_operations_fixed_contract_routes(monkeypatch, config, method, path):
    payload = {"id": "job_abc", "status": "in_progress", "cursor": 42, "items": []}
    requests = mock_http(monkeypatch, payload)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": payload}
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.olostep.com" and request.url.scheme == "https"
    assert request.method == method and request.url.path == path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if method in {"POST", "PATCH"}:
        body = json.loads(request.content)
        assert "operation" not in body
        assert not any(k.endswith("_id") for k in body)
        assert body == {k: v for k, v in config.items() if k != "operation" and not k.endswith("_id")}
    else:
        assert not request.content
    if config["operation"] == "list_crawl_pages":
        assert request.url.params.get_list("formats") == ["html", "markdown"]
        assert request.url.params["cursor"] == "4"


@pytest.mark.asyncio
async def test_documented_credit_response_and_secret_redaction(monkeypatch):
    payload = json.loads((Path(__file__).parent / "fixtures/olostep/credits.json").read_text())
    mock_http(monkeypatch, payload)
    assert (await node({"operation": "get_credit_info"}).execute({}))["data"]["credits"] == 12500
    mock_http(monkeypatch, {"result": {"text_content": TOKEN}})
    assert TOKEN not in str(await node({"operation": "get_scrape", "scrape_id": "scrape_abc"}).execute({}))


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"detail": "Your API key is invalid"}), (200, {"object": "error", "error": {"message": TOKEN}}), (429, {"error": "rate_limited"})])
async def test_error_envelopes_are_never_success(monkeypatch, status, body):
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=body))
    result = await node({"operation": "get_credit_info"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_transport_failure_never_retries_write(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("uncertain write")
    requests = mock_http(monkeypatch, fail)
    with pytest.raises(ValueError, match="inspect the dashboard"):
        await node(CASES[0][0]).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_invalid_response_not_accepted(monkeypatch):
    mock_http(monkeypatch, [])
    with pytest.raises(ValueError, match="JSON object"):
        await node({"operation": "get_credit_info"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_scrape", "scrape_id": "../credits"},
    {"operation": "get_schedule", "schedule_id": "bad"},
    {"operation": "create_batch", "items": [{"url": "https://example.com"}]},
    {"operation": "create_search", "query": "hello", "limit": 26},
    {"operation": "create_schedule", "method": "POST", "endpoint": "v1/scrapes"},
])
def test_invalid_contract_inputs(config):
    with pytest.raises(ValueError):
        native.OlostepNode.parse_config({"config": config})


@pytest.mark.parametrize("key", ["Bearer token", "https://example.com/key", "<token>", "a\nb"])
def test_bad_keys(key):
    with pytest.raises(ValidationError):
        native.OlostepAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
async def test_nested_body_alias_and_metadata_coercion(monkeypatch):
    requests = mock_http(monkeypatch, {"id": "scrape_abc"})
    await node({"operation": "create_scrape", "url_to_scrape": "https://example.com", "llm_extract": {"schema": {"type": "object", "properties": {"title": {"type": "string"}}}}}).execute({})
    assert json.loads(requests[0].content)["llm_extract"] == {"schema": {"type": "object", "properties": {"title": {"type": "string"}}}}
    requests = mock_http(monkeypatch, {"id": "batch_abc"})
    await node({"operation": "create_batch", "items": [{"url": "https://example.com", "custom_id": "product/123", "metadata": {"priority": 1, "processed": False}}]}).execute({})
    assert json.loads(requests[0].content)["items"][0]["metadata"] == {"priority": "1", "processed": "false"}


@pytest.mark.parametrize("metadata", [{"bad[key]": "value"}, {"key": "x" * 501}, {"key": {"nested": "value"}}])
def test_metadata_limits(metadata):
    with pytest.raises(ValueError):
        native.OlostepNode.parse_config({"config": {"operation": "update_batch_metadata", "batch_id": "batch_abc", "metadata": metadata}})
