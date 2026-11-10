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


def trade_page():
    """Unchanged provider example, pinned from CLOB OpenAPI 1.0.0."""
    return json.loads((Path(__file__).parent / "fixtures/polymarket/trades.json").read_text())["body"]


def poll_node(**filters):
    return node({"operation": "on_new_trade", "maker_address": CREDENTIAL["wallet_address"], **filters})


def poll_state(monkeypatch, instance, state):
    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)


def paged_transport(monkeypatch, pages):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json=pages.pop(0))
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_trade_poll_baselines_then_emits_documented_trade_once(monkeypatch):
    # Empty pages use the documented envelope and end cursor; the event is the
    # provider's complete example, unchanged. Repeated polls must not re-fire it.
    empty = {"data": [], "next_cursor": "LTE=", "count": 0, "limit": 100}
    instance = poll_node(after="1600000000")
    state = {}
    poll_state(monkeypatch, instance, state)
    requests = paged_transport(monkeypatch, [empty, trade_page(), trade_page()])
    initial = await instance.execute({})
    assert initial["trades"] == [] and instance.trigger_produced_no_event(initial)
    fresh = await instance.execute({})
    assert fresh["trades"] == trade_page()["data"] and fresh["new_trade_count"] == 1
    assert instance.trigger_emitted_event(fresh)
    assert instance.should_propagate_output(fresh, {"operation": "on_new_trade"})
    repeated = await instance.execute({})
    assert repeated["trades"] == [] and instance.trigger_produced_no_event(repeated)
    assert not instance.should_propagate_output(repeated, {"operation": "on_new_trade"})
    assert instance.resolve_agent_event(repeated) is None
    event = instance.resolve_agent_event(fresh)
    for field in ("maker_address", "side", "size", "price", "market", "asset_id", "id", "taker_order_id", "status"):
        assert trade_page()["data"][0][field] in event["text"]
    assert event["conversation_key"] is None
    assert dict(requests[0].url.params) == {"maker_address": CREDENTIAL["wallet_address"], "after": "1600000000"}
    assert all(r.headers.get("POLY_SIGNATURE") and r.url.path == "/data/trades" for r in requests)


@pytest.mark.asyncio
async def test_trade_poll_existing_history_and_changed_scope_baseline(monkeypatch):
    from nodes.core.poll_trigger import poll_scope
    page = trade_page()
    terminal = {"data": [], "next_cursor": "LTE=", "count": 0, "limit": 100}
    instance = poll_node()
    state = {}
    poll_state(monkeypatch, instance, state)
    paged_transport(monkeypatch, [page])
    assert (await instance.execute({}))["trades"] == []
    assert state["seen_ids"] == [page["data"][0]["id"]]
    original_scope = state["scope"]
    instance = poll_node(market=page["data"][0]["market"], asset_id=page["data"][0]["asset_id"])
    assert poll_scope(type(instance), instance.node_data["config"]) != original_scope
    poll_state(monkeypatch, instance, state)
    requests = paged_transport(monkeypatch, [page])
    assert (await instance.execute({}))["trades"] == []
    assert state["scope"] != original_scope
    assert requests[0].url.params["market"] == page["data"][0]["market"]
    assert requests[0].url.params["asset_id"] == page["data"][0]["asset_id"]


@pytest.mark.asyncio
async def test_trade_poll_rejects_repeated_cursor_without_consuming_state(monkeypatch):
    instance = poll_node()
    state = {"seen_ids": []}
    poll_state(monkeypatch, instance, state)
    page = trade_page()
    page["count"] = page["limit"]
    paged_transport(monkeypatch, [page, page])
    with pytest.raises(ValueError, match="repeated.*cursor"):
        await instance.execute({})
    assert state == {"seen_ids": []}


@pytest.mark.asyncio
async def test_trade_poll_error_preserves_state(monkeypatch):
    instance = poll_node()
    state = {"seen_ids": []}
    poll_state(monkeypatch, instance, state)
    transport(monkeypatch, {"error": "rejected " + CREDENTIAL["api_key"]}, 401)
    result = await instance.execute({})
    assert result["status"] == "error" and CREDENTIAL["api_key"] not in str(result)
    assert state == {"seen_ids": []}


def test_trade_trigger_schema_and_schedule():
    from nodes.core.poll_trigger import PollTriggerConfigBase
    config = native.OnNewTrade(maker_address=CREDENTIAL["wallet_address"])
    assert isinstance(config, PollTriggerConfigBase)
    assert config.schedule.frequency == "minutes" and config.schedule.interval == 5
    assert native.OnNewTrade.model_json_schema()["properties"]["operation"]["x-is-trigger"] is True


@pytest.mark.asyncio
async def test_trade_poll_follows_full_pages_before_dedup(monkeypatch):
    # Change only pagination metadata to exercise a full page followed by the
    # provider's unchanged short page; overlapping trades must be emitted once.
    page = trade_page()
    page["count"] = page["limit"]
    instance = poll_node()
    state = {"seen_ids": []}
    poll_state(monkeypatch, instance, state)
    requests = paged_transport(monkeypatch, [page, trade_page()])
    result = await instance.execute({})
    assert result["trades"] == trade_page()["data"] and result["new_trade_count"] == 1
    assert requests[1].url.params["next_cursor"] == "MTAw"
