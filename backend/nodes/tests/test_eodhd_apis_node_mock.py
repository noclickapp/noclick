"""Fixed EODHD routes, native connect, query serialization and provider examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import eodhd_apis_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-eodhd-token-42"
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/eodhd-apis/published_examples.json").read_text()
)
CASES = [
    ({"operation": "get_user"}, "/user", {"fmt": "json"}),
    (
        {
            "operation": "get_eod_prices",
            "ticker": "AAPL.US",
            "from_date": "2024-01-01",
            "to_date": "2024-02-01",
            "period": "w",
        },
        "/eod/AAPL.US",
        {"fmt": "json", "from": "2024-01-01", "to": "2024-02-01", "period": "w"},
    ),
    (
        {
            "operation": "get_live_prices",
            "ticker": "AAPL.US",
            "symbols": "MSFT.US,TSLA.US",
        },
        "/real-time/AAPL.US",
        {"fmt": "json", "s": "MSFT.US,TSLA.US"},
    ),
    (
        {
            "operation": "get_intraday_prices",
            "ticker": "AAPL.US",
            "interval": "5m",
            "from_timestamp": 1627896900,
            "to_timestamp": 1630575300,
        },
        "/intraday/AAPL.US",
        {"fmt": "json", "interval": "5m", "from": "1627896900", "to": "1630575300"},
    ),
    (
        {
            "operation": "get_fundamentals",
            "ticker": "AAPL.US",
            "filter": "General",
            "historical": 0,
            "no_cache": 1,
        },
        "/fundamentals/AAPL.US",
        {"filter": "General", "historical": "0", "no_cache": "1"},
    ),
    (
        {
            "operation": "search_symbols",
            "query": "Apple Inc",
            "security_type": "stock",
            "exchange": "US",
            "limit": 10,
        },
        "/search/Apple Inc",
        {"fmt": "json", "type": "stock", "exchange": "US", "limit": "10"},
    ),
    ({"operation": "list_exchanges"}, "/exchanges-list", {"fmt": "json"}),
    (
        {
            "operation": "list_exchange_symbols",
            "exchange": "US",
            "delisted": 0,
            "security_type": "etf",
        },
        "/exchange-symbol-list/US",
        {"fmt": "json", "delisted": "0", "type": "etf"},
    ),
    (
        {"operation": "get_exchange_details", "exchange": "US", "format_version": 1},
        "/exchange-details/US",
        {"fmt": "json", "format_version": "1"},
    ),
    (
        {"operation": "get_news", "symbols": "AAPL.US", "limit": 50, "offset": 50},
        "/news",
        {"fmt": "json", "s": "AAPL.US", "limit": "50", "offset": "50"},
    ),
    (
        {"operation": "get_sentiment", "symbols": "AAPL.US"},
        "/sentiments",
        {"fmt": "json", "s": "AAPL.US"},
    ),
    (
        {"operation": "get_dividends", "ticker": "AAPL.US"},
        "/div/AAPL.US",
        {"fmt": "json"},
    ),
    (
        {"operation": "get_splits", "ticker": "AAPL.US"},
        "/splits/AAPL.US",
        {"fmt": "json"},
    ),
    (
        {"operation": "get_earnings_calendar", "symbols": "AAPL.US"},
        "/calendar/earnings",
        {"fmt": "json", "symbols": "AAPL.US"},
    ),
    ({"operation": "get_ipo_calendar"}, "/calendar/ipos", {"fmt": "json"}),
    ({"operation": "get_splits_calendar"}, "/calendar/splits", {"fmt": "json"}),
    (
        {
            "operation": "get_dividends_calendar",
            "symbol": "AAPL.US",
            "date_from": "2024-01-01",
            "limit": 100,
            "offset": 100,
        },
        "/calendar/dividends",
        {
            "fmt": "json",
            "filter[symbol]": "AAPL.US",
            "filter[date_from]": "2024-01-01",
            "page[limit]": "100",
            "page[offset]": "100",
        },
    ),
    (
        {
            "operation": "get_technical_indicator",
            "ticker": "AAPL.US",
            "function_name": "sma",
            "period": 50,
        },
        "/technical/AAPL.US",
        {"fmt": "json", "function": "sma", "period": "50"},
    ),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(
        node_id="eodhd-fixture",
        node_type="automation-eodhd-apis",
        node_data={
            "config": config,
            "credentials": credentials
            or {"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN},
        },
    )


def transport(monkeypatch, reply):
    calls = []

    def respond(request):
        calls.append(request)
        return reply(request)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,query", CASES)
async def test_eodhd_apis_native_routes_and_query(monkeypatch, config, path, query):
    calls = transport(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"name": "Test account"} if path == "/user" else []
        ),
    )
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert (
        request.method == "GET"
        and request.url.host == "eodhd.com"
        and request.url.path == "/api" + path
    )
    assert dict(request.url.params) == {"api_token": TOKEN, **query}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("path,body", EXAMPLES.items())
async def test_eodhd_apis_published_examples_pass_through(monkeypatch, path, body):
    operation = next(op for op, route in native.ROUTES.items() if route[0] == path)
    config = next(cfg for cfg, _, _ in CASES if cfg["operation"] == operation)
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_eodhd_apis_rejections_never_retry_or_leak_token(monkeypatch, status):
    calls = transport(
        monkeypatch, lambda req: httpx.Response(status, text="Rejected " + TOKEN)
    )
    result = await node({"operation": "get_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert len(calls) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>login</html>"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"error": "Invalid key"}),
        httpx.Response(
            200, content="broken", headers={"content-type": "application/json"}
        ),
    ],
)
async def test_eodhd_apis_error_envelopes_and_bad_json(monkeypatch, response):
    transport(monkeypatch, lambda req: response)
    assert (await node({"operation": "get_user"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_eodhd_apis_user_identity_omits_unpublished_secrets(monkeypatch):
    transport(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            json={
                "name": "Subscriber",
                "email": "subscriber@example.test",
                "apiToken": TOKEN,
                "inviteToken": "private",
            },
        ),
    )
    result = await node({"operation": "get_user"}).execute({})
    assert result["data"] == {"name": "Subscriber", "email": "subscriber@example.test"}
    assert native.EodhdApisNode.connection_evidence.identity_operation == "get_user"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ticker", ["..", "AAPL.US/../../user", "https://other.test", "x\\y"]
)
async def test_eodhd_apis_no_path_escape(monkeypatch, ticker):
    calls = transport(monkeypatch, lambda req: httpx.Response(200, json=[]))
    with pytest.raises(ValueError):
        await node({"operation": "get_eod_prices", "ticker": ticker}).execute({})
    assert calls == []


def test_eodhd_apis_manual_connect_defaults_and_required_fields():
    credential = native.EodhdApisAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == native.CREDENTIAL_TYPE
    assert native.EodhdApisAPITokenCredential.model_json_schema()["required"] == [
        "api_token"
    ]
    with pytest.raises(ValidationError):
        native.EodhdApisAPITokenCredential(api_token="https://eodhd.com/key")
    with pytest.raises(ValidationError):
        native.EodhdGetNewsConfig(limit=1001)
    with pytest.raises(ValidationError):
        native.EodhdGetEodPricesConfig(
            ticker="AAPL.US", from_date="2024-02-01", to_date="2024-01-01"
        )
