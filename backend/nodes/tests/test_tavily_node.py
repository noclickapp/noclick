"""Mock contract tests for each Tavily REST operation."""

import json
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.tavily_node import (
    TavilyApiKeyCredential,
    TavilyCrawlConfig,
    TavilyCreateResearchConfig,
    TavilyExtractConfig,
    TavilyGetLogsConfig,
    TavilyGetOrgUsageConfig,
    TavilyGetResearchConfig,
    TavilyGetUsageConfig,
    TavilyMapConfig,
    TavilyNode,
    TavilyNodeConfig,
    TavilySearchConfig,
    TavilySubmitFeedbackConfig,
)


def _node(operation, credentials=None):
    return TavilyNode(
        node_id="tavily-test",
        node_type="automation-tavily",
        node_data={},
        config=TavilyNodeConfig(
            config=operation,
            credentials=credentials or TavilyApiKeyCredential(api_key="tvly-test-secret"),
        ),
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


async def _run(operation, payload=None, status_code=200):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(status_code, json=payload or {"ok": True})

    client = httpx.AsyncClient
    with patch("nodes.tavily_node.httpx.AsyncClient", side_effect=lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs)):
        result = await _node(operation).execute({})
    assert len(seen) == 1
    assert seen[0].headers["Authorization"] == "Bearer tvly-test-secret"
    assert "api_request" in result["timing_ms"]
    return result, seen[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,method,path,expected",
    [
        (TavilySearchConfig(query="current news", include_domains="example.com, news.example.com", include_image_descriptions=True), "POST", "/search", {"query": "current news", "include_domains": ["example.com", "news.example.com"], "include_image_descriptions": True}),
        (TavilyExtractConfig(urls="https://a.example\nhttps://b.example", timeout=45), "POST", "/extract", {"urls": ["https://a.example", "https://b.example"], "timeout": 45}),
        (TavilyCrawlConfig(url="https://example.com", select_paths="/docs/.*\n/api/.*"), "POST", "/crawl", {"url": "https://example.com", "select_paths": ["/docs/.*", "/api/.*"]}),
        (TavilyMapConfig(url="https://example.com"), "POST", "/map", {"url": "https://example.com"}),
        (TavilyCreateResearchConfig(input="Compare two databases", output_schema='{"properties":{"summary":{"type":"string","description":"Summary"}}}', files='[{"name":"brief.md","data":"YWJj","type":"base64"}]'), "POST", "/research", {"input": "Compare two databases", "stream": False, "output_schema": {"properties": {"summary": {"type": "string", "description": "Summary"}}}, "files": [{"name": "brief.md", "data": "YWJj", "type": "base64"}]}),
        (TavilyGetResearchConfig(request_id="req-1"), "GET", "/research/req-1", None),
        (TavilyGetUsageConfig(), "GET", "/usage", None),
        (TavilySubmitFeedbackConfig(request_id="req-1", used_urls="https://a.example\nhttps://b.example", used_citations="Quote one\nQuote two"), "POST", "/feedback", {"request_id": "req-1", "used_urls": ["https://a.example", "https://b.example"], "used_citations": ["Quote one", "Quote two"]}),
        (TavilyGetLogsConfig(endpoints="search,extract"), "POST", "/logs", {"endpoints": ["search", "extract"]}),
        (TavilyGetOrgUsageConfig(organization_name="NoClick"), "POST", "/org-usage", {"organization_name": "NoClick"}),
    ],
)
async def test_operation_route_and_payload(operation, method, path, expected):
    result, request = await _run(operation, {"results": [{"url": "https://example.com"}]})
    assert result["status"] == "success"
    assert result["action"] == operation.operation
    assert result["data"]["results"][0]["url"] == "https://example.com"
    assert request.method == method
    assert request.url.path == path
    if expected:
        body = json.loads(request.content)
        for key, value in expected.items():
            assert body[key] == value
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_provider_error_preserves_status_and_message():
    result, _ = await _run(TavilySearchConfig(query="news"), {"detail": "quota exhausted"}, 429)
    assert result["status"] == "error"
    assert result["status_code"] == 429
    assert result["error"] == "quota exhausted"


@pytest.mark.asyncio
async def test_usage_project_header_and_research_id_encoding():
    _, usage = await _run(TavilyGetUsageConfig(project_id="project-123"))
    assert usage.headers["X-Project-ID"] == "project-123"
    _, research = await _run(TavilyGetResearchConfig(request_id="a/b"))
    assert research.url.raw_path == b"/research/a%2Fb?include_usage=true"


@pytest.mark.asyncio
async def test_missing_credentials_fail_before_request():
    node = _node(TavilyGetUsageConfig())
    node.config.credentials = None
    with pytest.raises(ValueError, match="Connect a Tavily API key"):
        await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,message", [
    (TavilyExtractConfig(urls="\n"), "At least one URL"),
    (TavilyCreateResearchConfig(input="Research", output_schema="{bad"), "valid JSON"),
    (TavilyCreateResearchConfig(input="Research", files="[]{}"), "valid JSON"),
    (TavilyCreateResearchConfig(input="Research", files="{}"), "JSON list"),
    (TavilySubmitFeedbackConfig(), "request ID or session ID"),
])
async def test_invalid_request_is_rejected_before_network(operation, message):
    with pytest.raises(ValueError, match=message):
        await _node(operation).execute({})


def test_connection_evidence_probes_read_only_account_usage():
    assert TavilyNode.connection_evidence.identity_operation == "get_usage"
    assert TavilyNode.connection_evidence.proves == "reachability"
