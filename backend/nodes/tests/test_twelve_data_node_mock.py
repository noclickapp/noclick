"""Exercise Twelve Data through the real node factory with intercepted HTTP.

Published fixtures cover account evidence and data preservation; transport and
error tests ensure a pasted secret cannot escape in workflow output.
"""
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from nodes import twelve_data_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-twelve-data-key"
PUBLISHED = json.loads((Path(__file__).parent / "fixtures/twelve-data/published.json").read_text())
CASES = [
    ("get_api_usage", "/api_usage", {}),
    ("search_symbols", "/symbol_search", {"symbol": "AAPL"}),
    ("list_stocks", "/stocks", {}),
    ("list_forex_pairs", "/forex_pairs", {}),
    ("list_cryptocurrencies", "/cryptocurrencies", {}),
    ("get_price", "/price", {"symbol": "AAPL"}),
    ("get_quote", "/quote", {"symbol": "AAPL"}),
    ("get_time_series", "/time_series", {"symbol": "AAPL", "interval": "1min"}),
    ("get_exchange_rate", "/exchange_rate", {"symbol": "EUR/USD"}),
    ("convert_currency", "/currency_conversion", {"symbol": "EUR/USD", "amount": 100}),
    ("get_profile", "/profile", {"symbol": "AAPL"}),
    ("get_statistics", "/statistics", {"symbol": "AAPL"}),
    ("get_income_statement", "/income_statement", {"symbol": "AAPL"}),
    ("get_balance_sheet", "/balance_sheet", {"symbol": "AAPL"}),
    ("get_cash_flow", "/cash_flow", {"symbol": "AAPL"}),
    ("list_dividends", "/dividends", {"symbol": "AAPL"}),
    ("list_splits", "/splits", {"symbol": "AAPL"}),
    ("list_earnings", "/earnings", {"symbol": "AAPL"}),
    ("get_rsi", "/rsi", {"symbol": "AAPL", "interval": "1min"}),
    ("get_sma", "/sma", {"symbol": "AAPL", "interval": "1min"}),
    ("get_macd", "/macd", {"symbol": "AAPL", "interval": "1min"}),
    ("batch_time_series", "/batch", {"symbols": "AAPL,MSFT,EUR/USD", "interval": "1min", "outputsize": 2}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="twelve-data-fixture", node_type="automation-twelve-data",
        node_data={"config": config, "credentials": {"credential_type": "twelve_data_api_key", "api_key": TOKEN}})


def transport(monkeypatch, payload, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,config", CASES, ids=["twelve-data-" + c[0] for c in CASES])
async def test_twelve_data_routes_auth_and_preserved_json(monkeypatch, operation, path, config):
    payload = PUBLISHED[("POST" if path == "/batch" else "GET") + " " + path]["body"]
    calls = transport(monkeypatch, payload)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success" and result["success"] is True
    assert result["data"] == payload
    assert len(calls) == 1
    request = calls[0]
    assert request.url.host == "api.twelvedata.com" and request.url.path == path
    assert request.headers["Authorization"] == "apikey " + TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    assert request.method == ("POST" if path == "/batch" else "GET")
    if path == "/batch":
        body = json.loads(request.content)
        for i, symbol in enumerate(config["symbols"].split(","), 1):
            url = urlsplit(body[f"req_{i}"]["url"])
            assert not url.netloc and url.path == "/time_series"
            assert parse_qs(url.query) == {"symbol": [symbol], "interval": ["1min"], "outputsize": ["2"], "apikey": [TOKEN]}
        assert request.headers["Content-Type"] == "application/json"
        assert result["complete"] is True
    else:
        params = dict(request.url.params)
        for key, value in config.items():
            assert float(params[key]) == value if isinstance(value, (int, float)) else params[key] == value
        assert "operation" not in params
    if operation == "get_api_usage":
        assert result["items"][0]["name"] == "4003 requests used of 20000/minute"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(200, 401), (401, 401), (403, 403), (429, 429), (500, 500), (302, 302)])
async def test_twelve_data_provider_errors_and_redaction(monkeypatch, status, code):
    calls = transport(monkeypatch, {"code": code, "status": "error", "message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "get_price", "symbol": "AAPL"}).execute({})
    assert result["success"] is False and result["status"] == "error"
    assert result["status_code"] == code
    assert result["error"] == "Rejected [redacted]" and len(calls) == 1
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}, {"current_usage": -1, "plan_limit": 200, "timestamp": "2025-05-07"}])
async def test_twelve_data_malformed_evidence_never_succeeds(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "get_api_usage"}).execute({})


@pytest.mark.asyncio
async def test_twelve_data_partial_batch_reports_failure_and_missing_results(monkeypatch):
    payload = copy.deepcopy(PUBLISHED["POST /batch"]["body"])
    payload["data"].pop("req_3")
    payload["data"]["req_2"] = {"status": "error", "response": {"code": 429, "status": "error"}}
    transport(monkeypatch, payload)
    result = await node({"operation": "batch_time_series", "symbols": "AAPL,MSFT,EUR/USD", "interval": "1min"}).execute({})
    assert result["status"] == "partial" and result["success"] is False and result["complete"] is False
    assert result["data"] == payload


@pytest.mark.asyncio
async def test_twelve_data_timeouts_hide_secret_urls(monkeypatch):
    def client(**kwargs):
        raise httpx.ConnectError("private " + TOKEN)
    monkeypatch.setattr(native, "guarded_async_client", client)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_api_usage"}).execute({})
    assert TOKEN not in str(exc.value)


def test_twelve_data_manual_credential_and_bounded_inputs():
    credential = native.TwelveDataAPIKeyCredential(api_key=" " + TOKEN + "\n")
    assert credential.credential_type == "twelve_data_api_key" and credential.api_key == TOKEN
    for value in ["https://example.com/key", "apikey somekey", "<token>", ""]:
        with pytest.raises(ValueError):
            native.TwelveDataAPIKeyCredential(api_key=value)
    for config in [
        {"operation": "get_price"},
        {"operation": "get_time_series", "symbol": "AAPL", "interval": "0.99min"},
        {"operation": "get_price", "symbol": "AAPL,MSFT"},
        {"operation": "batch_time_series", "symbols": "AAPL,AAPL", "interval": "1min"},
        {"operation": "get_rsi", "symbol": "AAPL", "interval": "1min", "outputsize": 5001},
        {"operation": "convert_currency", "symbol": "EUR/USD", "amount": -1},
    ]:
        with pytest.raises(ValueError):
            native.TwelveDataNode.parse_config({"config": config})
