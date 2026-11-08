"""Published Fixer examples and exact native-node wire regressions; no live key."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from nodes import fixer_io_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NODE_REGISTRY, NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/fixer-io/contract.json").read_text())
KEY = "synthetic-fixer-key-42"
ROUTES = {
    "list_symbols": "/symbols",
    "get_latest_rates": "/latest",
    "get_latest_spread": "/latest",
    "get_historical_rates": "/{date}",
    "get_historical_spread": "/{date}",
    "convert_currency": "/convert",
    "convert_historical_currency": "/convert",
    "get_time_series": "/timeseries",
    "get_time_series_spread": "/timeseries",
    "get_fluctuation": "/fluctuation",
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="fixer-fixture", node_type="automation-fixer-io",
        node_data={"config": config, "credentials": credential or {
            "credential_type": "fixer_io_api_key", "access_key": KEY}})


def transport(monkeypatch, body, status=200):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ROUTES, ids=lambda operation: "fixer-io:" + operation)
async def test_fixer_io_published_examples_and_exact_requests(monkeypatch, operation):
    config = FIXTURE["inputs"][operation]
    route = ROUTES[operation]
    body = FIXTURE["responses"][route]
    requests = transport(monkeypatch, body)
    result = await node(config).run({})
    assert result == {**body, "operation": operation, "status": "success"}
    assert KEY not in str(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.scheme == "https" and request.url.host == "data.fixer.io"
    assert request.url.path == "/api" + route.replace("{date}", config.get("date", ""))
    expected = {k: str(v) for k, v in config.items() if k in {"base", "symbols", "start_date", "end_date"}}
    if "from_currency" in config:
        expected.update({"from": config["from_currency"], "to": config["to_currency"], "amount": "25.0"})
        if "date" in config:
            expected["date"] = config["date"]
    if operation.endswith("_spread"):
        expected["spread"] = "1"
    assert dict(request.url.params) == {"access_key": KEY, **expected}
    assert not request.content and "authorization" not in request.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_latest_spread", "get_historical_spread", "get_time_series_spread"])
async def test_fixer_io_mixed_spread_quotes_and_unavailable_bid_ask(monkeypatch, operation):
    body = copy.deepcopy(FIXTURE["responses"][ROUTES[operation]])
    quotes = {"USD": {"rate": 1.0856, "bid": 1.0854, "ask": 1.0858, "spread": 0.0004}, "GBP": {"rate": 0.882047}, "JPY": 132.36}
    body["rates"] = {"2026-10-01": quotes} if "time_series" in operation else quotes
    transport(monkeypatch, body)
    result = await node(FIXTURE["inputs"][operation]).run({})
    assert result["rates"] == body["rates"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429])
async def test_fixer_io_provider_errors_and_secret_redaction(monkeypatch, status):
    transport(monkeypatch, {"success": False, "error": {"code": 101,
        "type": "invalid_access_key", "info": "Rejected key " + KEY}}, status)
    with pytest.raises(ValueError, match=r"Rejected key \[redacted\]") as exc:
        await node({"operation": "list_symbols"}).run({})
    assert KEY not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({}, 200), ({"success": True}, 302),
    ({"success": True, "rates": []}, 200), ({"success": True, "rates": {"USD": True}}, 200),
    ({"success": True, "rates": {"USD": {"bid": 1}}}, 200),
    ({"success": True, "rates": {"USD": {"rate": 1, "ask": "bad"}}}, 200)])
async def test_fixer_io_malformed_responses_fail_closed(monkeypatch, body, status):
    requests = transport(monkeypatch, body, status)
    with pytest.raises(ValueError):
        await node({"operation": "get_latest_rates"}).run({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_fixer_io_zero_conversion_and_unfiltered_default_base(monkeypatch):
    body = copy.deepcopy(FIXTURE["responses"]["/convert"])
    body["result"] = 0
    transport(monkeypatch, body)
    assert (await node({"operation": "convert_currency", "from_currency": "GBP", "to_currency": "JPY", "amount": 0}).run({}))["result"] == 0
    requests = transport(monkeypatch, FIXTURE["responses"]["/latest"])
    await node({"operation": "get_latest_rates"}).run({})
    assert dict(requests[0].url.params) == {"access_key": KEY}


@pytest.mark.parametrize("config", [
    {"operation": "get_historical_rates", "date": "../latest"},
    {"operation": "get_historical_rates", "date": "2026-02-30"},
    {"operation": "get_latest_rates", "base": "USD,GBP"},
    {"operation": "get_latest_rates", "symbols": "USD&access_key=other"},
    {"operation": "convert_currency", "from_currency": "GBP", "to_currency": "JPY", "amount": float("inf")},
    {"operation": "get_time_series", "start_date": "2025-01-02", "end_date": "2025-01-01"},
    {"operation": "get_time_series", "start_date": "2024-01-01", "end_date": "2025-01-02"},
    {"operation": "list_symbols", "callback": "unwanted"},
    {"operation": "write_rates"},
])
def test_fixer_io_invalid_config_rejected(config):
    with pytest.raises(ValueError):
        node(config)


def test_fixer_io_registration_manual_connect_and_honest_evidence():
    assert NODE_REGISTRY["automation-fixer-io"] is native.FixerIoNode
    shaped, errors, resolved = shape_credential("fixer_io_api_key", {"access_key": " " + KEY + " "})
    assert errors == {} and shaped["access_key"] == KEY
    assert resolved[0] == "automation-fixer-io"
    assert resolved[1].model_validate(shaped).credential_type == "fixer_io_api_key"
    evidence = native.FixerIoNode.connection_evidence
    assert evidence.operation == "list_symbols" and evidence.proves == "reachability"
    assert len(ROUTES) == 10
