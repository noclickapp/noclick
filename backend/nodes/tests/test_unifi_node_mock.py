"""Native-factory wire tests using published Site Manager response examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import unifi_node as api
from nodes.core.registry import NodeFactory
from nodes.core.binary_output import BinaryOutput

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/unifi/contract_examples.json").read_text())["operations"]
AUTH = {"credential_type": "unifi_api_key", "api_key": "synthetic-unifi-fixture-key"}

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.ui.com"
        assert request.headers["X-API-Key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        return replies.pop(0)
    monkeypatch.setattr(api, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(send), **kw))
    monkeypatch.setattr(api.UnifiNode, "emit", AsyncMock())
    return requests, replies

async def run(operation, config=None):
    node = NodeFactory.create_node(node_id="unifi-test", node_type="automation-unifi",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": AUTH})
    return await node.execute({})

@pytest.mark.parametrize("operation", EXAMPLES)
@pytest.mark.asyncio
async def test_published_responses_and_routes(transport, operation):
    requests, replies = transport
    example = EXAMPLES[operation]
    replies.append(httpx.Response(200, json=example["body"]))
    result = await run(operation, example["config"])
    assert result["status"] == "success" and result["data"] == example["body"]
    assert len(requests) == 1
    request = requests[0]
    route = example["route"].replace("{id}", "host-1" if "host" in operation or operation.startswith("connector") else "config-1").replace("{type}", example["config"].get("type", "5m")).replace("*path", "network/integration/v1/sites")
    assert request.method == example["method"] and request.url.path == route
    if operation == "list_devices":
        assert request.url.params.get_list("hostIds[]") == ["host-1", "host-2"]
        assert request.url.params["nextToken"] == "opaque"
        assert request.url.params["pageSize"] == "10"
        assert request.url.params["time"] == "2026-06-15T07:21:27Z"
    if operation == "get_isp_metrics":
        assert dict(request.url.params) == {"duration": "24h"}
    if operation == "query_isp_metrics":
        assert json.loads(request.content) == {"sites": [{"hostId": "host-1", "siteId": "site-1", "beginTimestamp": "2024-06-30T13:35:00Z", "endTimestamp": "2024-06-30T15:35:00Z"}]}
    if "body" in example["config"]:
        assert json.loads(request.content) == example["config"]["body"]

@pytest.mark.asyncio
async def test_pagination_is_one_page_and_preserves_token(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"data": [], "nextToken": "next-page"}))
    result = await run("list_hosts", {"next_token": "prior-page", "page_size": "10"})
    assert result["data"]["nextToken"] == "next-page" and len(requests) == 1
    assert dict(requests[0].url.params) == {"nextToken": "prior-page", "pageSize": "10"}

@pytest.mark.asyncio
async def test_provider_rejection_and_no_retry(transport):
    requests, replies = transport
    replies.append(httpx.Response(401, json={"message": "unauthorized"}))
    result = await run("list_hosts")
    assert result["success"] is False and result["message"] == "unauthorized"
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_connector_binary_and_empty_response(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, content=b"binary", headers={"Content-Type": "application/octet-stream"}))
    result = await run("connector_get", {"id": "host-1", "path": "protect/integration/v1/meta/info"})
    assert isinstance(result["data"], BinaryOutput)
    replies.append(httpx.Response(204))
    result = await run("connector_delete", {"id": "host-1", "path": "network/integration/v1/sites"})
    assert result["data"] is None

@pytest.mark.parametrize("path", ["https://example.test", "//example.test", "network/../admin", "network/integration/v1/%2e%2e", "network/integration/v1/sites?key=x", "/proxy/network/integration/v1/sites"])
def test_unsafe_connector_path(path):
    with pytest.raises(ValidationError):
        api.UnifiConnectorGetConfig(id="host-1", path=path)

@pytest.mark.parametrize("config", [{"duration": "7d"}, {"duration": "24h", "begin_timestamp": "2024-06-30T13:35:00Z"}, {"begin_timestamp": "yesterday"}, {"begin_timestamp": "2024-06-30T15:35:00Z", "end_timestamp": "2024-06-30T13:35:00Z"}])
def test_invalid_metric_windows(config):
    with pytest.raises(ValidationError):
        api.UnifiGetISPMetricsConfig(**config)

def test_manual_credential_default_and_secret_validation():
    assert api.UnifiAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == "unifi_api_key"
    with pytest.raises(ValidationError):
        api.UnifiAPIKeyCredential(api_key="https://unifi.ui.com")

@pytest.mark.asyncio
async def test_manual_json_configuration(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"data": []}))
    await run("connector_post", {"id": "host-1", "path": "network/integration/v1/sites", "body": '{"name":"Example"}'})
    assert json.loads(requests[0].content) == {"name": "Example"}
    parsed = api.UnifiQueryISPMetricsConfig(sites='[{"host_id":"host-1","site_id":"site-1"}]')
    assert parsed.sites[0].site_id == "site-1"
