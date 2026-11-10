"""Offline CoinGecko contract examples and native execution regressions.

Response bodies are copied without changes from CoinGecko's published Demo
OpenAPI v3.0.0, pinned by the external conformance catalog. No live key is used.
"""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import coingecko_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-coingecko-secret-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/coingecko/demo_examples.json").read_text())
TRIGGERS = json.loads((Path(__file__).parent / "fixtures/coingecko/trigger_examples.json").read_text())
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


def poll_state(monkeypatch):
    state = {}

    async def update(self, mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    monkeypatch.setattr(native.CoinGeckoNode, "_update_node_state", update)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,network,path,params", [
    ("on_new_pool", None, "/onchain/networks/new_pools", {"page": "1"}),
    ("on_new_pool", "eth", "/onchain/networks/{network}/new_pools", {"page": "1"}),
    ("on_updated_token", None, "/onchain/tokens/info_recently_updated", {}),
    ("on_updated_token", "eth", "/onchain/tokens/info_recently_updated", {"network": "eth"}),
])
async def test_poll_documented_examples_baseline_dedup_and_agent_event(monkeypatch, operation, network, path, params):
    state = poll_state(monkeypatch)
    body = TRIGGERS[path]["body"]
    requests = transport(monkeypatch, body)
    trigger = node(operation, network=network)
    output = await trigger.run({"another_node": {"untrusted": True}})
    assert output["count"] == 0 and output["data"] == []
    assert trigger.trigger_produced_no_event(output)
    assert native.CoinGeckoNode.resolve_agent_event(output) is None
    assert requests[0].url.path == "/api/v3" + path.replace("{network}", network or "")
    assert dict(requests[0].url.params) == params
    assert requests[0].headers["x-cg-demo-api-key"] == TOKEN
    baseline = deepcopy(state)
    assert (await node(operation, network=network).run({}))["count"] == 0
    assert state == baseline
    # An existing empty baseline exercises delivery of the provider's exact example.
    state["seen_ids"] = []
    trigger = node(operation, network=network)
    output = await trigger.run({})
    assert output["data"] == body["data"] and output["count"] == len(body["data"])
    assert trigger.trigger_emitted_event(output)
    event = native.CoinGeckoNode.resolve_agent_event(output)
    for item in body["data"]:
        assert item["id"] in event["text"]
        assert item["attributes"]["name"] in event["text"]
        assert item["attributes"]["address"] in event["text"]
    assert "another_node" not in event["text"]
    assert (await node(operation, network=network).run({}))["count"] == 0


@pytest.mark.asyncio
async def test_token_update_uses_metadata_version_and_repoint_rebaselines(monkeypatch):
    state = poll_state(monkeypatch)
    body = deepcopy(TRIGGERS["/onchain/tokens/info_recently_updated"]["body"])
    transport(monkeypatch, body)
    await node("on_updated_token").run({})
    item = body["data"][0]
    item["attributes"]["metadata_updated_at"] = "2026-05-29T01:52:27Z"
    transport(monkeypatch, body)
    output = await node("on_updated_token").run({})
    assert output["data"] == [item]
    assert (await node("on_updated_token").run({}))["count"] == 0
    scope = state["scope"]
    assert (await node("on_updated_token", network="eth").run({}))["count"] == 0
    assert state["scope"] != scope


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({"data": {}}, 200), ({"data": [{}]}, 200),
    ({"error": "rate limit"}, 429), ({"data": [{"id": "pool", "attributes": {}}]}, 200)])
async def test_poll_failures_preserve_state(monkeypatch, body, status):
    state = poll_state(monkeypatch)
    state["seen_ids"] = ["earlier"]
    before = deepcopy(state)
    transport(monkeypatch, body, status=status)
    if status == 200:
        with pytest.raises(ValueError, match="poll state was preserved"):
            await node("on_new_pool").run({})
    else:
        assert (await node("on_new_pool").run({}))["status"] == "error"
    assert state == before


@pytest.mark.parametrize("network", ["../eth", "eth/other", "https://bad.test", "eth?x=1"])
def test_poll_network_rejects_path_injection(network):
    with pytest.raises(ValueError):
        node("on_new_pool", network=network)
