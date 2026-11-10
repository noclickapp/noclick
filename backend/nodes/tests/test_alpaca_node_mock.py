"""Offline wire-contract and trading outcome regressions for Alpaca."""
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from nodes import alpaca_node as native
from nodes.core.registry import NodeFactory

ID = "5680c4bc-9ac1-4a12-a44c-df427ba53032"
KEY = "alpaca-test-key-id"
SECRET = "alpaca-test-secret"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, environment="paper"):
    return NodeFactory.create_node(node_id="alpaca-test", node_type="automation-alpaca", node_data={
        "config": config, "credentials": {"credential_type": "alpaca_api_key", "api_key": KEY, "api_secret": SECRET, "environment": environment}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Independent wire expectations, not derived from the node's routing table.
CASES = [
    ({"operation": "get_account"}, "GET", "/v2/account", None),
    ({"operation": "get_account_config"}, "GET", "/v2/account/configurations", None),
    ({"operation": "update_account_config", "suspend_trade": False}, "PATCH", "/v2/account/configurations", {"suspend_trade": False}),
    ({"operation": "get_portfolio_history"}, "GET", "/v2/account/portfolio/history", None),
    ({"operation": "list_activities", "page_size": 1, "page_token": "activity-123"}, "GET", "/v2/account/activities", None),
    ({"operation": "list_assets", "asset_class": "us_equity"}, "GET", "/v2/assets", None),
    ({"operation": "get_asset", "symbol_or_asset_id": "AAPL"}, "GET", "/v2/assets/AAPL", None),
    ({"operation": "get_calendar"}, "GET", "/v2/calendar", None),
    ({"operation": "get_clock"}, "GET", "/v2/clock", None),
    ({"operation": "list_orders", "limit": 1, "nested": False}, "GET", "/v2/orders", None),
    ({"operation": "create_order", "symbol": "AAPL", "side": "buy", "type": "limit", "time_in_force": "gtc", "qty": "2", "limit_price": "150"}, "POST", "/v2/orders", {"symbol": "AAPL", "side": "buy", "type": "limit", "time_in_force": "gtc", "qty": "2", "limit_price": "150", "extended_hours": False}),
    ({"operation": "get_order", "order_id": ID}, "GET", "/v2/orders/" + ID, None),
    ({"operation": "replace_order", "order_id": ID, "qty": "4", "limit_price": "155", "time_in_force": "gtc"}, "PATCH", "/v2/orders/" + ID, {"qty": "4", "limit_price": "155", "time_in_force": "gtc"}),
    ({"operation": "cancel_order", "order_id": ID}, "DELETE", "/v2/orders/" + ID, None),
    ({"operation": "get_order_by_client_id", "client_order_id": "my-order +1"}, "GET", "/v2/orders:by_client_order_id", None),
    ({"operation": "list_positions"}, "GET", "/v2/positions", None),
    ({"operation": "get_position", "symbol_or_asset_id": "AAPL"}, "GET", "/v2/positions/AAPL", None),
    ({"operation": "close_position", "symbol_or_asset_id": "AAPL", "qty": "0.25"}, "DELETE", "/v2/positions/AAPL", None),
    ({"operation": "list_watchlists"}, "GET", "/v2/watchlists", None),
    ({"operation": "create_watchlist", "name": "Tech Stocks", "symbols": ["AAPL", "TSLA"]}, "POST", "/v2/watchlists", {"name": "Tech Stocks", "symbols": ["AAPL", "TSLA"]}),
    ({"operation": "get_watchlist", "watchlist_id": ID}, "GET", "/v2/watchlists/" + ID, None),
    ({"operation": "update_watchlist", "watchlist_id": ID, "symbols": []}, "PUT", "/v2/watchlists/" + ID, {"symbols": []}),
    ({"operation": "add_watchlist_asset", "watchlist_id": ID, "symbol": "AAPL"}, "POST", "/v2/watchlists/" + ID, {"symbol": "AAPL"}),
    ({"operation": "remove_watchlist_asset", "watchlist_id": ID, "symbol": "AAPL"}, "DELETE", "/v2/watchlists/" + ID + "/AAPL", None),
    ({"operation": "delete_watchlist", "watchlist_id": ID}, "DELETE", "/v2/watchlists/" + ID, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_all_operations_wire_contract(monkeypatch, config, method, path, body):
    operation = config["operation"]
    rows = operation.startswith("list_") or operation == "get_calendar"
    payload = [{"id": "activity-123", "symbol": "AAPL"}] if rows else {"id": ID, "status": "accepted"}
    status = 204 if operation in {"cancel_order", "delete_watchlist"} else 200
    requests = transport(monkeypatch, lambda request: httpx.Response(status, **({"json": payload} if status != 204 else {})))
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    assert request.url.host == "paper-api.alpaca.markets"
    assert request.headers["APCA-API-KEY-ID"] == KEY
    assert request.headers["APCA-API-SECRET-KEY"] == SECRET
    assert result["http_status"] == status
    assert json.loads(request.content) == body if body is not None else request.content == b""
    assert KEY not in str(result) and SECRET not in str(result)
    if method != "GET":
        assert result["request_accepted"] is True
    if operation in {"create_order", "replace_order", "close_position", "cancel_order"}:
        assert result["execution_verified"] is False
    if operation == "list_orders":
        assert result["limit_reached"] is True
        assert dict(request.url.params) == {"status": "open", "limit": "1", "direction": "desc", "nested": "false"}
    if operation == "list_activities":
        assert result["next_page_token"] == "activity-123"
        assert request.url.params["page_token"] == "activity-123"
    if operation == "get_order_by_client_id":
        assert request.url.params["client_order_id"] == "my-order +1"
    if operation == "close_position":
        assert dict(request.url.params) == {"qty": "0.25"}


@pytest.mark.asyncio
async def test_live_host_documented_account_and_evidence(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/alpaca/account.json").read_text())
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=fixture["body"]))
    result = await node({"operation": "get_account"}, environment="live").execute({})
    assert requests[0].url.host == "api.alpaca.markets"
    assert result["data"]["account_number"] == fixture["body"]["account_number"]
    assert native.AlpacaNode.connection_evidence.identity_operation == "get_account"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 422, 429, 500])
async def test_errors_redact_secrets_and_never_retry(monkeypatch, code):
    requests = transport(monkeypatch, lambda r: httpx.Response(code, json={"message": "denied " + SECRET + " " + KEY}, headers={"Location": "https://example.com"}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_watchlist", "name": "Tech Stocks"}).execute({})
    assert str(code) in str(exc.value) and SECRET not in str(exc.value) and KEY not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_write_unknown_no_retry(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="outcome is unknown"):
        await node({"operation": "cancel_order", "order_id": ID}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("changes", [
    {"qty": None}, {"notional": "20"}, {"qty": "NaN"}, {"qty": "-1"},
    {"type": "limit"}, {"type": "stop"}, {"type": "trailing_stop"},
    {"extended_hours": True}, {"type": "market", "limit_price": "1"},
    {"time_in_force": "gtc", "qty": "0.5"},
])
def test_reject_invalid_order_before_network(changes):
    with pytest.raises(ValidationError):
        TypeAdapter(native.AlpacaConfig).validate_python({"operation": "create_order", "symbol": "AAPL", "side": "buy", "qty": "2", **changes})


@pytest.mark.parametrize("config", [
    {"operation": "update_account_config"},
    {"operation": "replace_order", "order_id": ID},
    {"operation": "replace_order", "order_id": ID, "qty": "0.5"},
    {"operation": "update_watchlist", "watchlist_id": ID},
    {"operation": "close_position", "symbol_or_asset_id": "AAPL", "qty": "1", "percentage": 50},
    {"operation": "list_orders", "before_order_id": ID, "after_order_id": ID},
    {"operation": "list_orders", "before_order_id": ID, "after": "2026-01-01"},
    {"operation": "get_watchlist", "watchlist_id": "../account"},
    {"operation": "get_asset", "symbol_or_asset_id": "https://evil.example"},
])
def test_reject_invalid_paths_mutations_and_cursors(config):
    with pytest.raises(ValidationError):
        TypeAdapter(native.AlpacaConfig).validate_python(config)


@pytest.mark.parametrize("value", ["https://example.com/key", "<token>", "key\nsecret", "Bearer mytoken"])
def test_credentials_reject_placeholders_urls_headers(value):
    with pytest.raises(ValidationError):
        native.AlpacaAPIKeyCredential(api_key=value, api_secret=SECRET)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], "oops"])
async def test_bad_object_response_fails_closed(monkeypatch, payload):
    transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="unexpected|invalid"):
        await node({"operation": "get_account"}).execute({})


@pytest.fixture
def poll_examples():
    return json.loads((Path(__file__).parent / "fixtures/alpaca/poll_examples.json").read_text())


def poll_state(monkeypatch):
    state = {}
    async def update(self, mutator, *, skip_result):
        replacement, result = mutator(state)
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    monkeypatch.setattr(native.AlpacaNode, "_update_node_state", update)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example", [("on_new_order", "order"), ("on_new_activity", "fill"), ("on_new_activity", "dividend")])
async def test_poll_baseline_new_item_dedup_and_agent(monkeypatch, poll_examples, operation, example):
    poll_state(monkeypatch)
    record = poll_examples[example]
    records = []
    requests = transport(monkeypatch, lambda request: httpx.Response(200, json=records))
    instance = node({"operation": operation})
    assert (await instance.execute({}))["data"] == []
    records.append(record)
    output = await instance.execute({})
    assert output["data"] == [record]
    assert output["new_item_count"] == 1
    event = native.AlpacaNode.resolve_agent_event(output)
    assert record["id"] in event["text"]
    assert record["symbol"] in event["text"]
    assert (await instance.execute({}))["data"] == []
    assert native.AlpacaNode.resolve_agent_event(await instance.execute({})) is None
    if operation == "on_new_order":
        assert dict(requests[0].url.params) == {"status": "all", "direction": "desc", "limit": "500", "nested": "false"}
    else:
        assert dict(requests[0].url.params) == {"direction": "desc", "page_size": "100"}


@pytest.mark.asyncio
async def test_poll_existing_history_is_baselined_and_repointed(monkeypatch, poll_examples):
    state = poll_state(monkeypatch)
    transport(monkeypatch, lambda r: httpx.Response(200, json=[poll_examples["fill"]]))
    assert (await node({"operation": "on_new_activity", "activity_types": "FILL"}).execute({}))["data"] == []
    assert state["seen_ids"] == [poll_examples["fill"]["id"]]
    prior_scope = state["scope"]
    assert (await node({"operation": "on_new_activity", "activity_types": "FILL,DIV"}).execute({}))["data"] == []
    assert state["scope"] != prior_scope


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example,size,cursor", [("on_new_order", "order", 500, "before_order_id"), ("on_new_activity", "fill", 100, "page_token")])
async def test_poll_paginates_before_baseline(monkeypatch, poll_examples, operation, example, size, cursor):
    state = poll_state(monkeypatch)
    records = [{**poll_examples[example], "id": str(UUID(int=i + 1))} for i in range(size)]
    def reply(request):
        return httpx.Response(200, json=[] if cursor in request.url.params else records)
    requests = transport(monkeypatch, reply)
    output = await node({"operation": operation}).execute({})
    assert output["data"] == []
    assert len(state["seen_ids"]) == size
    assert requests[1].url.params[cursor] == records[-1]["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["repeat", "http", "missing"])
async def test_poll_failure_never_writes_partial_baseline(monkeypatch, poll_examples, failure):
    state = poll_state(monkeypatch)
    records = [{**poll_examples["fill"], "id": str(i)} for i in range(100)]
    def reply(request):
        if "page_token" not in request.url.params:
            return httpx.Response(200, json=records)
        if failure == "http":
            return httpx.Response(429, json={"message": "rate limited"})
        return httpx.Response(200, json=[records[0] if failure == "repeat" else {}])
    transport(monkeypatch, reply)
    with pytest.raises(ValueError):
        await node({"operation": "on_new_activity"}).execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_poll_filters_and_live_environment(monkeypatch, poll_examples):
    poll_state(monkeypatch)
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=[]))
    await node({"operation": "on_new_order", "symbols": "AAPL,TSLA", "side": "buy"}, "live").execute({})
    assert requests[0].url.host == "api.alpaca.markets"
    assert requests[0].url.params["symbols"] == "AAPL,TSLA"
    assert requests[0].url.params["side"] == "buy"
    await node({"operation": "on_new_activity", "activity_types": "FILL,DIV", "after": "2022-02-02T18:55:09Z"}).execute({})
    assert requests[1].url.params["activity_types"] == "FILL,DIV"
    assert requests[1].url.params["after"] == "2022-02-02T18:55:09+00:00"


@pytest.mark.asyncio
async def test_poll_page_bound_does_not_write_baseline(monkeypatch, poll_examples):
    state = poll_state(monkeypatch)
    page = 0
    def reply(request):
        nonlocal page
        records = [{**poll_examples["fill"], "id": str(page * 100 + i)} for i in range(100)]
        page += 1
        return httpx.Response(200, json=records)
    transport(monkeypatch, reply)
    with pytest.raises(ValueError, match="page bound"):
        await node({"operation": "on_new_activity"}).execute({})
    assert state == {}
