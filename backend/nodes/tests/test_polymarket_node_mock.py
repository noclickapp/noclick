"""Native CLOB requests, HMAC bytes, account evidence and failure behavior."""
import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from nodes import polymarket_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "polymarket_api_key", "api_key": "synthetic-key-42", "api_secret": "c3ludGhldGljLXNlY3JldA==",
    "api_passphrase": "synthetic-passphrase-42", "wallet_address": "0x1234567890123456789012345678901234567890"}


def node(config):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-polymarket", node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    monkeypatch.setattr(native.time, "time", lambda: 1700000000)
    return requests


@pytest.mark.asyncio
async def test_account_evidence_and_cursor_sign_only_path(monkeypatch):
    requests = transport(monkeypatch, {"data": [{"id": "order-123"}], "next_cursor": "MQ==", "count": 1, "limit": 100})
    result = await node({"operation": "list_orders", "market": "condition", "next_cursor": "MA=="}).execute({})
    request = requests[0]
    assert result["data"] == [{"id": "order-123"}] and result["has_more"] and result["next_cursor"] == "MQ=="
    assert dict(request.url.params) == {"market": "condition", "next_cursor": "MA=="}
    expected = base64.urlsafe_b64encode(hmac.new(b"synthetic-secret", b"1700000000GET/data/orders", hashlib.sha256).digest()).decode()
    assert request.headers["POLY_SIGNATURE"] == expected
    assert request.headers["POLY_ADDRESS"] == CREDENTIAL["wallet_address"]
    assert request.headers["POLY_API_KEY"] == CREDENTIAL["api_key"]
    assert request.headers["POLY_PASSPHRASE"] == CREDENTIAL["api_passphrase"]
    assert native.PolymarketNode.connection_evidence.operation == "list_orders"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,body", [
    ({"operation": "cancel_order", "order_id": "hash-one"}, "/order", {"orderID": "hash-one"}),
    ({"operation": "cancel_orders", "order_ids": ["hash-one", "hash-two"]}, "/orders", ["hash-one", "hash-two"]),
    ({"operation": "cancel_market_orders", "market": "condition", "asset_id": "123"}, "/cancel-market-orders", {"market": "condition", "asset_id": "123"}),
    ({"operation": "cancel_all_orders"}, "/cancel-all", None),
])
async def test_cancellation_serialization_and_partial_result(monkeypatch, config, path, body):
    partial = {"canceled": ["hash-one"], "not_canceled": {"hash-two": "Order already matched"}}
    requests = transport(monkeypatch, partial)
    result = await node(config).execute({})
    request = requests[0]
    assert request.method == "DELETE" and request.url.path == path
    serialized = json.dumps(body, separators=(",", ":")) if body is not None else ""
    assert request.content.decode() == serialized
    expected = base64.urlsafe_b64encode(hmac.new(b"synthetic-secret", ("1700000000DELETE" + path + serialized).encode(), hashlib.sha256).digest()).decode()
    assert request.headers["POLY_SIGNATURE"] == expected
    assert result["data"] == partial  # Never report that every cancellation succeeded.


@pytest.mark.asyncio
async def test_notification_required_signature_type_and_delete_query(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({"operation": "list_notifications", "signature_type": 3}).execute({})
    assert dict(requests[0].url.params) == {"signature_type": "3"}
    requests = transport(monkeypatch, "OK")
    result = await node({"operation": "mark_notifications_read", "ids": "1,2,3"}).execute({})
    assert result["data"] == "OK" and requests[0].method == "DELETE"
    assert dict(requests[0].url.params) == {"ids": "1,2,3"} and not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,reply", [
    ({"operation": "get_price", "token_id": "123", "side": "SELL"}, "/price", {"price": 0.45}),
    ({"operation": "get_order_book", "token_id": "123"}, "/book", {"bids": [], "asks": []}),
    ({"operation": "get_price_history", "market": "123"}, "/prices-history", {"history": []}),
])
async def test_public_reads_do_not_send_credentials(monkeypatch, config, path, reply):
    requests = transport(monkeypatch, reply)
    result = await node(config).execute({})
    assert result["data"] == reply and requests[0].url.path == path
    assert not any(k.lower().startswith("poly_") for k in requests[0].headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_failures_redact_secrets_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "rejected " + CREDENTIAL["api_key"]}, status)
    result = await node({"operation": "list_orders"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert CREDENTIAL["api_key"] not in str(result) and len(requests) == 1


def test_credential_manual_fields_and_operation_catalog():
    credential = native.PolymarketAPIKeyCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert credential.credential_type == "polymarket_api_key"
    fixture = json.loads((Path(__file__).parent / "fixtures/polymarket/routes.json").read_text())
    assert {k: [v[0], v[1]] for k, v in native.ROUTES.items()} == fixture
    assert len(fixture) == 20
