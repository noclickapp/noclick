"""Exercise the real node factory with isolated HTTP and provider-shaped payloads."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import uniswap_api_node as native
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

TOKEN = "synthetic-uniswap-api-key"
ADDRESS = "0xC9bebBA9f481b12cE6f3EA54c4B182c9636ec421"
HASH = "0x" + "a" * 64
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/uniswap-api/request_examples.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    instance = NodeFactory.create_node(
        node_id="uniswap-test",
        node_type="automation-uniswap-api",
        node_data={
            "config": config,
            "credentials": {"credential_type": "uniswap_api_key", "api_key": TOKEN},
        },
    )
    instance.emit = AsyncMock()
    return instance


def transport(monkeypatch, body, status=200):
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["check_approval", "check_permissions", "get_quote", "create_swap"]
)
async def test_provider_examples_preserve_body_and_optional_headers(
    monkeypatch, operation
):
    config = (
        {**EXAMPLES[operation]["config"], "x_permit2_disabled": False}
        if operation in {"check_approval", "get_quote", "create_swap"}
        else EXAMPLES[operation]["config"]
    )
    reply = {
        "requestId": "fixture-request",
        "quote": {"amount": "2516"},
        "permitData": None,
    }
    requests = transport(monkeypatch, reply)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": reply}
    req = requests[0]
    assert (
        req.method == "POST" and req.url.path == "/v1" + native.OPERATIONS[operation][1]
    )
    assert (
        req.headers["x-api-key"] == TOKEN
        and req.url.host == "trade-api.gateway.uniswap.org"
    )
    assert not req.url.query
    expected = {
        k: v for k, v in config.items() if k != "operation" and not k.startswith("x_")
    }
    assert json.loads(req.content) == expected
    if "x_permit2_disabled" in config:
        assert req.headers["x-permit2-disabled"] == "false"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,query",
    [
        (
            {"operation": "get_orders", "cursor": "next+page/=", "orderIds": "one,two"},
            {"cursor": "next+page/=", "orderIds": "one,two"},
        ),
        (
            {"operation": "get_swaps", "txHashes": [HASH, HASH], "chainId": 1},
            {"txHashes": HASH + "," + HASH, "chainId": "1"},
        ),
        (
            {
                "operation": "get_swappable_tokens",
                "tokenIn": ADDRESS,
                "tokenInChainId": 1,
            },
            {"tokenIn": ADDRESS, "tokenInChainId": "1"},
        ),
        ({"operation": "get_supported_chains"}, {}),
        (
            {"operation": "get_tokens", "chainId": 1, "limit": 10, "sort": "tvl"},
            {"chainId": "1", "limit": "10", "sort": "tvl"},
        ),
    ],
)
async def test_read_queries_do_not_send_body_or_lose_pagination(
    monkeypatch, config, query
):
    reply = {"requestId": "fixture-request", "cursor": "next+page/=", "items": []}
    requests = transport(monkeypatch, reply)
    assert (await node(config).execute({}))["data"] == reply
    req = requests[0]
    assert req.method == "GET" and dict(req.url.params) == query and not req.content
    assert req.url.path == "/v1" + native.OPERATIONS[config["operation"]][1]


@pytest.mark.asyncio
async def test_signed_order_is_submitted_exactly_once(monkeypatch):
    # Quote is an opaque provider-returned object and must survive unchanged.
    quote = {"orderInfo": {"swapper": ADDRESS, "nonce": "3"}, "encodedOrder": "0x1234"}
    config = {
        "operation": "create_order",
        "signature": "0x1234",
        "quote": quote,
        "routing": "DUTCH_V2",
    }
    requests = transport(monkeypatch, {"orderId": "submitted-order"}, 201)
    assert (await node(config).execute({}))["data"]["orderId"] == "submitted-order"
    assert len(requests) == 1 and requests[0].url.path == "/v1/order"
    assert json.loads(requests[0].content) == {
        k: v for k, v in config.items() if k != "operation"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_rejections_do_not_retry_or_echo_key(monkeypatch, status):
    requests = transport(
        monkeypatch, {"errorCode": "InvalidKey", "detail": TOKEN}, status
    )
    result = await node({"operation": "get_supported_chains"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert (
        "InvalidKey" in result["error"]
        and TOKEN not in str(result)
        and len(requests) == 1
    )


def test_manual_credential_default_and_required_fields():
    credential = native.UniswapAPIKeyCredential(api_key=" " + TOKEN + " ")
    assert (
        credential.credential_type == "uniswap_api_key" and credential.api_key == TOKEN
    )
    assert native.UniswapAPINode.connection_evidence.proves == "reachability"
    for bad in ["https://example.com/key", "key\nheader: injected"]:
        with pytest.raises(ValueError):
            native.UniswapAPIKeyCredential(api_key=bad)
    for bad in [
        {"operation": "get_swaps"},
        {"operation": "get_swaps", "txHashes": ["bad"]},
        {"operation": "get_tokens", "limit": 1001},
        {"operation": "check_approval", "walletAddress": "../bad"},
        {"operation": "get_quote", "walletExecutionContext": {}},
    ]:
        with pytest.raises(ConfigValidationError):
            node(bad)


@pytest.mark.asyncio
async def test_documented_quote_response_and_numeric_slippage(monkeypatch):
    reply = json.loads(
        (Path(__file__).parent / "fixtures/uniswap-api/quote_response.json").read_text()
    )
    config = dict(EXAMPLES["get_quote"]["config"])
    config.pop("autoSlippage")
    config["slippageTolerance"] = 1.25
    requests = transport(monkeypatch, reply)
    instance = node(config)
    result = await instance.execute({})
    assert result["data"] == reply and result["data"]["permitTransaction"] is None
    assert json.loads(requests[0].content)["slippageTolerance"] == 1.25
    instance.emit.assert_awaited_once_with(result)
