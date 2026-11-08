"""Offline CoinGecko contract examples and native execution regressions.

Response bodies are copied without changes from CoinGecko's published Demo
OpenAPI v3.0.0, pinned by the external conformance catalog. No live key is used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import coingecko_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-coingecko-secret-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/coingecko/demo_examples.json").read_text())
CONFIGS = {
    "get_prices": {"ids": "bitcoin,ethereum"},
    "get_token_prices": {"id": "ethereum", "contract_addresses": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"},
    "get_coin": {"id": "bitcoin"},
    "get_coin_history": {"id": "bitcoin", "date": "30-12-2025"},
    "get_market_chart": {"id": "bitcoin"},
    "get_ohlc": {"id": "bitcoin"},
    "get_exchange": {"id": "binance"},
    "search": {"query": "Ethereum + café"},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="coingecko-fixture", node_type="automation-coingecko",
        node_data={"config": {"operation": operation, **CONFIGS.get(operation, {}), **config},
                   "credentials": {"credential_type": native.FAMILY, "api_key": TOKEN}})


def transport(monkeypatch, body=None, *, status=200, mime="application/json", failure=False):
    requests = []

    def respond(request):
        requests.append(request)
        if failure:
            raise httpx.ConnectError("unreachable " + TOKEN, request=request)
        return httpx.Response(status, json=body, headers={"content-type": mime})

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_every_native_operation_uses_exact_route_and_accepts_published_example(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = transport(monkeypatch, example["body"])
    output = await node(operation).run({})
    assert output["status"] == "success" and output["data"] == example["body"]
    assert output["identity_verified"] is False
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET" and req.url.host == "api.coingecko.com"
    route = example["path"].replace("{id}", CONFIGS.get(operation, {}).get("id", ""))
    assert req.url.path == "/api/v3" + route
    assert req.headers["x-cg-demo-api-key"] == TOKEN
    assert TOKEN not in str(req.url) and TOKEN not in str(output)
    assert "operation" not in req.url.params and "id" not in req.url.params


@pytest.mark.asyncio
async def test_price_flags_currency_lists_and_single_page_are_explicit(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["get_prices"]["body"])
    await node("get_prices", vs_currencies="usd,eur", include_24hr_change=True).run({})
    assert dict(requests[0].url.params) == {"ids": "bitcoin,ethereum", "vs_currencies": "usd,eur",
        "include_market_cap": "false", "include_24hr_vol": "false", "include_24hr_change": "true", "include_last_updated_at": "false"}
    requests = transport(monkeypatch, EXAMPLES["list_exchanges"]["body"])
    result = await node("list_exchanges", page=3, per_page=2).run({})
    assert dict(requests[0].url.params) == {"page": "3", "per_page": "2"}
    assert result["pagination"] == "single_page" and result["page"] == 3
    assert "has_more" not in result and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_error_status_and_provider_message_redact_secret(monkeypatch, status):
    requests = transport(monkeypatch, {"status": {"error_message": "Rejected " + TOKEN}}, status=status)
    result = await node("check_connection").run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Rejected [redacted]" and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,mime", [({}, "application/json"), ({"error": "bad"}, "application/json"),
    ({"status": {"error_message": "bad"}}, "application/json"), ([], "application/json"),
    ({"gecko_says": "ok"}, "text/html")])
async def test_connection_rejects_unexpected_shapes_and_error_envelopes(monkeypatch, body, mime):
    transport(monkeypatch, body, mime=mime)
    assert (await node("check_connection").run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_network_error_is_not_success_and_response_secrets_are_redacted(monkeypatch):
    transport(monkeypatch, failure=True)
    result = await node("check_connection").run({})
    assert result["status"] == "error" and TOKEN not in str(result)
    transport(monkeypatch, {"gecko_says": TOKEN})
    result = await node("check_connection").run({})
    assert result["data"] == {"gecko_says": "[redacted]"}


@pytest.mark.parametrize("operation,changes", [
    ("get_coin", {"id": "../ping"}), ("get_exchange", {"id": "https://evil.test"}),
    ("get_coin_history", {"date": "31-02-2025"}), ("get_coin_history", {"date": "2025-12-30"}),
    ("get_ohlc", {"days": "2"}), ("get_market_chart", {"days": "max"}),
    ("list_coin_markets", {"per_page": 251}), ("list_exchanges", {"page": 0}),
    ("search", {"query": ""}), ("get_prices", {"extra_params": {"x_cg_demo_api_key": "other"}}),
])
def test_invalid_routes_dates_paging_and_undeclared_parameters_fail(operation, changes):
    with pytest.raises(ValueError):
        node(operation, **changes)


@pytest.mark.parametrize("value", ["", "https://api.coingecko.com", "Bearer key", "bad\r\nkey", "{{ secret }}"])
def test_secret_shape_rejects_urls_headers_and_placeholders(value):
    with pytest.raises(ValidationError):
        native.CoinGeckoAPIKeyCredential(api_key=value)
