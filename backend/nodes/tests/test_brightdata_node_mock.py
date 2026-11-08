"""Bright Data request boundaries, documented replies and manual credentials."""
import json
from pathlib import Path
import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import brightdata_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-brightdata-key-42"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/brightdata/requests.json").read_text())


def node(config):
    return NodeFactory.create_node(node_id="brightdata-test", node_type="automation-brightdata",
        node_data={"config": config, "credentials": {"credential_type": "brightdata_api_key", "api_key": TOKEN}})


def transport(monkeypatch, reply):
    calls = []
    def respond(request):
        calls.append(request)
        return reply(request)
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURE, ids=lambda case: case["config"]["operation"])
async def test_each_operation_matches_provider_route_and_parameters(monkeypatch, case):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=case["response"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.host == "api.brightdata.com"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if "body" in case:
        assert json.loads(request.content) == case["body"]
    else:
        assert request.content == b""
    if case["config"]["operation"] != "get_scrape_input":
        assert result["data"] == case["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
async def test_provider_rejection_is_not_success_and_never_retried(monkeypatch, code):
    calls = transport(monkeypatch, lambda request: httpx.Response(code, text="Invalid API key " + TOKEN,
        headers={"Location": "https://other.example/"}))
    result = await node({"operation": "rerun_scrape", "snapshot_id": "s_m4x7enmven8djfqak"}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert TOKEN not in str(result) and "Invalid API key" in result["error"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_paid_collection_timeout_is_not_retried(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("provider timeout", request=request)
    calls = transport(monkeypatch, fail)
    result = await node({"operation": "trigger_scrape", "dataset_id": "gd_l1vikfnt1wgvvqz95w",
        "inputs": '[{"url":"https://il.linkedin.com/company/bright-data"}]'}).execute({})
    assert result["status"] == "error" and len(calls) == 1
    assert "check the provider" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["csv", "ndjson", "jsonl"])
async def test_file_downloads_use_binary_output(monkeypatch, fmt):
    transport(monkeypatch, lambda request: httpx.Response(200, content=b"documented,data\n1,2"))
    result = await node({"operation": "download_scrape_snapshot", "snapshot_id": "s_m4x7enmven8djfqak", "format": fmt}).execute({})
    assert isinstance(result["file"], BinaryOutput)
    assert result["file"].data == b"documented,data\n1,2"
    assert result["file"].filename.endswith("." + fmt)


@pytest.mark.asyncio
async def test_async_serp_headers_and_text_acknowledgment(monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, text="OK", headers={"x-response-id":"r_123"}))
    result = await node({"operation":"search_serp", "zone":"serp_api1", "url":"https://www.google.com/search?q=pizza", "asynchronous":True}).execute({})
    assert calls[0].url.params["async"] == "true"
    assert result["response_id"] == "r_123" and result["data"] == "OK"


def test_manual_credential_and_schema_contract():
    cred = native.BrightdataAPIKeyCredential(api_key=TOKEN)
    assert cred.credential_type == "brightdata_api_key"
    schema = native.BrightdataNode.get_config_schema()
    assert len(schema["$defs"]) >= 20
    for config in [
        {"operation":"get_scrape_progress", "snapshot_id":"../escape"},
        {"operation":"get_scrape_progress"},
        {"operation":"list_scrape_snapshots", "dataset_id":"gd_1", "limit":5001},
        {"operation":"trigger_scrape", "dataset_id":"gd_1", "inputs":"{}"},
        {"operation":"search_serp", "zone":"serp_api1", "url":"file:///etc/passwd"},
    ]:
        with pytest.raises(ConfigValidationError):
            native.BrightdataNode.parse_config({"config":config,"credentials":cred.model_dump()})
