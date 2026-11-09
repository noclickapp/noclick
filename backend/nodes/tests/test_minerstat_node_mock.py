"""Offline request contracts and provider examples from
https://api.minerstat.com/v3/openapi.json (Minerstat Data API 3.0.0).
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import minerstat_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

KEY = "synthetic-minerstat-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/minerstat/responses.json").read_text())
CASES = [
    ({"operation": "list_coins", "algorithm": "scrypt", "verified": False, "limit": 2, "offset": 5},
     "/v3/coins", "/v3/coins", {"algorithm": "scrypt", "verified": "false", "limit": "2", "offset": "5"}),
    ({"operation": "get_coin", "slug": "btc"}, "/v3/coins/btc", "/v3/coins/{slug}", {}),
    ({"operation": "get_coin_history", "slug": "btc", "limit": 2, "offset": 3},
     "/v3/coins/btc/history", "/v3/coins/{slug}/history", {"limit": "2", "offset": "3"}),
    ({"operation": "list_hardware", "type": "ASIC"}, "/v3/hardware", "/v3/hardware", {"limit": "20", "offset": "0", "type": "ASIC"}),
    ({"operation": "get_hardware", "slug": "nvidia-geforce-rtx-4090"},
     "/v3/hardware/nvidia-geforce-rtx-4090", "/v3/hardware/{slug}", {}),
    ({"operation": "list_algorithms"}, "/v3/algorithms", "/v3/algorithms", {"limit": "20", "offset": "0"}),
    ({"operation": "get_algorithm", "slug": "sha-256"}, "/v3/algorithms/sha-256", "/v3/algorithms/{slug}", {}),
    ({"operation": "list_pools"}, "/v3/pools", "/v3/pools", {"limit": "20", "offset": "0"}),
    ({"operation": "get_pool", "slug": "f2pool"}, "/v3/pools/f2pool", "/v3/pools/{slug}", {}),
    ({"operation": "get_profitability", "hardware": "nvidia-geforce-rtx-4090", "electricity": 0.08,
      "quantity": 2, "poolFee": 0.01, "verifiedOnly": True, "window": "24h", "limit": 10},
     "/v3/profitability", "/v3/profitability", {"hardware": "nvidia-geforce-rtx-4090", "electricity": "0.08",
      "quantity": "2", "poolFee": "0.01", "verifiedOnly": "true", "window": "24h", "limit": "10"}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="minerstat-test", node_type="automation-minerstat",
        node_data={"config": config, "credentials": credentials or {"api_key": KEY}})


def mock_http(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,example,params", CASES)
async def test_minerstat_published_examples_and_exact_requests(monkeypatch, config, path, example, params):
    requests = mock_http(monkeypatch, EXAMPLES[example])
    result = await node(config).run({})
    assert result == {"status": "success", "operation": config["operation"], "data": EXAMPLES[example]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.host == "api.minerstat.com" and request.url.scheme == "https"
    assert request.url.path == path and dict(request.url.params) == params
    assert request.headers["X-Api-Key"] == KEY and request.headers["Accept"] == "application/json"
    assert not request.content and KEY not in str(request.url) and KEY not in str(result)


@pytest.mark.asyncio
async def test_minerstat_manual_profitability_preserves_zero_cost_and_false_filter(monkeypatch):
    requests = mock_http(monkeypatch, EXAMPLES["/v3/profitability"])
    await node({"operation": "get_profitability", "hashrate": 1000, "algorithm": "sha-256",
                "power": 0, "electricity": 0, "poolFee": 0, "verifiedOnly": False}).execute({})
    assert dict(requests[0].url.params) == {"hashrate": "1000.0", "algorithm": "sha-256", "power": "0.0",
        "electricity": "0.0", "poolFee": "0.0", "verifiedOnly": "false", "quantity": "1", "limit": "25", "window": "current"}


@pytest.mark.asyncio
async def test_minerstat_empty_plan_capped_page_is_not_identity_proof(monkeypatch):
    body = {"offset": 0, "limit": 20, "count": 0, "results": [], "notice": "Free plan capped at 20 rows"}
    mock_http(monkeypatch, body)
    result = await node({"operation": "list_coins"}).execute({})
    assert result["data"] == body
    assert native.MinerstatNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 402, 403, 429, 500])
async def test_minerstat_provider_errors_no_retry_or_secret_echo(monkeypatch, status):
    requests = mock_http(monkeypatch, lambda _: httpx.Response(status, json={"error": {"message": "Rejected " + KEY}}))
    result = await node({"operation": "list_coins"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"error": {"message": "bad"}}, {}, {"results": {}}, {"results": [1]}])
async def test_minerstat_rejects_malformed_list_envelopes(monkeypatch, body):
    mock_http(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_coins"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("config,body", [
    ({"operation": "get_coin", "slug": "btc"}, {"coin": {"slug": "ltc"}}),
    ({"operation": "get_coin", "slug": "btc"}, {"coin": []}),
    ({"operation": "get_coin_history", "slug": "btc"}, {"coin": "ltc", "results": []}),
])
async def test_minerstat_rejects_crossed_resource_identity(monkeypatch, config, body):
    mock_http(monkeypatch, body)
    with pytest.raises(ValueError):
        await node(config).execute({})


@pytest.mark.asyncio
async def test_minerstat_rejects_html_and_invalid_json(monkeypatch):
    for headers, body in [({"content-type": "text/html"}, b"<html>login</html>"),
                          ({"content-type": "application/json"}, b"not-json")]:
        mock_http(monkeypatch, lambda _, h=headers, b=body: httpx.Response(200, headers=h, content=b))
        with pytest.raises(ValueError):
            await node({"operation": "list_coins"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_coin", "slug": "../btc"}, {"operation": "get_pool", "slug": "a?key=secret"},
    {"operation": "list_coins", "limit": 0}, {"operation": "list_hardware", "type": "gpu"},
    {"operation": "get_coin_history", "slug": "btc", "limit": 101},
    {"operation": "list_algorithms", "offset": -1}, {"operation": "list_pools", "extra": "bad"},
    {"operation": "get_profitability"}, {"operation": "get_profitability", "hashrate": 1000},
    {"operation": "get_profitability", "hardware": "x", "hashrate": 1000},
    {"operation": "get_profitability", "hardware": "x", "electricity": float("nan")},
    {"operation": "get_profitability", "hardware": "x", "poolFee": 0.21},
])
def test_minerstat_rejects_invalid_config_before_http(config):
    assert native.MinerstatNode.validate_config({"config": config, "credentials": {"api_key": KEY}})["valid"] is False


@pytest.mark.parametrize("key", ["", "<token>", "https://example.com/key", "x\ny", "Bearer key"])
def test_minerstat_manual_credential_shaping(key):
    with pytest.raises(ValidationError):
        native.MinerstatAPIKeyCredential(api_key=key)


def test_minerstat_registration_and_manual_default():
    assert NODE_REGISTRY["automation-minerstat"] is native.MinerstatNode
    assert native.MinerstatAPIKeyCredential(api_key="  " + KEY + "  ").model_dump() == {
        "credential_type": "minerstat_api_key", "api_key": KEY}
    assert len(native.ROUTES) == 10
