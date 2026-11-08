"""Fixer contract examples through the real node factory; no live credentials."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import fixer_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-fixer-access-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/fixer/responses.json").read_text())
CASES = [
    ({"operation": "list_currencies"}, "/symbols", {}),
    ({"operation": "get_latest_rates", "base": "eur", "symbols": "usd, gbp"}, "/latest", {"base": "EUR", "symbols": "USD,GBP"}),
    ({"operation": "get_latest_quotes"}, "/latest", {"spread": "1"}),
    ({"operation": "get_historical_rates", "date": "2013-12-24"}, "/{date}", {}),
    ({"operation": "get_historical_quotes", "date": "2026-10-01"}, "/{date}", {"spread": "1"}),
    ({"operation": "convert_currency", "from_currency": "GBP", "to_currency": "JPY", "amount": 25}, "/convert", {"from": "GBP", "to": "JPY", "amount": "25.0"}),
    ({"operation": "convert_historical_currency", "from_currency": "GBP", "to_currency": "JPY", "amount": 25, "date": "2018-02-22"}, "/convert", {"from": "GBP", "to": "JPY", "amount": "25.0", "date": "2018-02-22"}),
    ({"operation": "get_time_series", "start_date": "2012-05-01", "end_date": "2012-05-03"}, "/timeseries", {"start_date": "2012-05-01", "end_date": "2012-05-03"}),
    ({"operation": "get_time_series_quotes", "start_date": "2026-10-01", "end_date": "2026-10-03"}, "/timeseries", {"start_date": "2026-10-01", "end_date": "2026-10-03", "spread": "1"}),
    ({"operation": "get_fluctuations", "start_date": "2015-12-01", "end_date": "2015-12-24"}, "/fluctuation", {"start_date": "2015-12-01", "end_date": "2015-12-24"}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="fixer-fixture", node_type="automation-fixer", node_data={
        "config": config, "credentials": {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN},
    })


def transport(monkeypatch, body=None, *, status=200, raw=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if raw is None else httpx.Response(status, content=raw)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,params", CASES)
async def test_each_action_makes_one_documented_get(monkeypatch, config, path, params):
    requests = transport(monkeypatch, EXAMPLES[path])
    output = await node(config).execute({})
    assert output["status"] == "success"
    assert output["data"] == EXAMPLES[path]
    assert TOKEN not in str(output)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.host == "data.fixer.io"
    assert request.url.scheme == "https"
    assert request.url.path == "/api" + ("/" + config["date"] if path == "/{date}" else path)
    assert dict(request.url.params) == {"access_key": TOKEN, **params}
    assert "authorization" not in request.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path", [(CASES[2][0], "/latest"), (CASES[4][0], "/{date}"), (CASES[8][0], "/timeseries")])
async def test_quotes_accept_optional_bid_ask_and_numeric_fallback(monkeypatch, config, path):
    body = copy.deepcopy(EXAMPLES[path])
    quote = {"rate": 1.0856, "bid": 1.0854, "ask": 1.0858, "spread": 0.0004}
    rates = {"USD": quote, "GBP": {"rate": 0.88}, "JPY": 132.36}
    body["rates"] = {"2026-10-01": rates} if path == "/timeseries" else rates
    transport(monkeypatch, body)
    assert (await node(config).execute({}))["data"]["rates"] == body["rates"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 403, 429, 500])
async def test_provider_error_envelope_never_becomes_evidence(monkeypatch, status):
    message = "You have not supplied a valid API Access Key."
    requests = transport(monkeypatch, {"success": False, "error": {"code": 101, "type": "invalid_access_key", "info": message}}, status=status)
    result = await node({"operation": "list_currencies"}).execute({})
    assert result == {"operation": "list_currencies", "status": "error", "http_status": status, "error": message}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_provider_echo_of_secret_is_redacted(monkeypatch):
    transport(monkeypatch, {"success": False, "error": {"info": "Rejected " + TOKEN}})
    result = await node({"operation": "list_currencies"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"success": True}, {"success": True, "rates": {"USD": True}}, {"success": True, "rates": {"USD": {"bid": 1.2}}}])
async def test_malformed_rates_fail_honestly(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "get_latest_rates"}).execute({})
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [204, 302, 401, 429, 503])
async def test_http_errors_and_redirects_are_not_followed(monkeypatch, status):
    requests = transport(monkeypatch, EXAMPLES["/symbols"], status=status)
    assert (await node({"operation": "list_currencies"}).execute({}))["status"] == "error"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_invalid_json_and_transport_failure_hide_request_key(monkeypatch):
    transport(monkeypatch, raw=b"<html>not JSON</html>")
    assert (await node({"operation": "list_currencies"}).execute({}))["status"] == "error"
    def client(**kwargs):
        raise httpx.ConnectError("Failed " + TOKEN)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node({"operation": "list_currencies"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize("config", [
    {"operation": "get_historical_rates", "date": "../symbols"},
    {"operation": "get_historical_rates", "date": "2026-02-30"},
    {"operation": "get_latest_rates", "base": "EUR&access_key=other"},
    {"operation": "get_latest_rates", "symbols": "USD,,EUR"},
    {"operation": "get_time_series", "start_date": "2026-10-03", "end_date": "2026-10-01"},
    {"operation": "convert_currency", "from_currency": "EUR", "to_currency": "GBP", "amount": float("inf")},
    {"operation": "convert_historical_currency", "from_currency": "EUR", "to_currency": "GBP", "amount": 25},
])
def test_bad_inputs_are_rejected_before_http(config):
    with pytest.raises(ValueError):
        native.FixerNode.parse_config({"config": config})


def test_manual_credential_default_and_evidence():
    cred = native.FixerAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert cred.credential_type == native.CREDENTIAL_TYPE and cred.api_key == TOKEN
    assert native.FixerNode.connection_evidence.proves == "reachability"
    for value in ("https://fixer.io/dashboard", "<token>", "key with spaces"):
        with pytest.raises(ValidationError):
            native.FixerAPIKeyCredential(api_key=value)
