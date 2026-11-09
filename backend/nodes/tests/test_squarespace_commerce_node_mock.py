"""Wire-level checks through the same factory used by connection evidence/tools."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import squarespace_commerce_node as sc
from nodes.core.run_op import run_node_operation
import utils.ssrf as ssrf

TOKEN = "fixture-squarespace-private-key"
AUTH = {"credential_type": sc.CREDENTIAL_TYPE, "api_key": TOKEN}
NODE = "automation-squarespace-commerce"


@pytest.fixture
def transport(monkeypatch):
    seen, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        seen.append(request)
        assert request.url.host == "api.squarespace.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.headers["User-Agent"] == "NoClick Squarespace Commerce Integration"
        assert TOKEN not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, content=b"" if code == 204 else json.dumps(body).encode(), headers={"Content-Type": "application/json"})

    native = ssrf.guarded_async_client
    monkeypatch.setattr(sc, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return seen, replies


async def run(operation, args=None, auth=AUTH):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=args or {}, credential_data=deepcopy(auth), user_id="11111111-1111-4111-8111-111111111111")


CASES = [
    ("get_website", {}, "GET", "/1.0/authorization/website", {"id": "site1", "title": "Fixture Store"}),
    ("list_products", {}, "GET", "/v2/commerce/products", {"products": [], "pagination": {"hasNextPage": False}}),
    ("get_products", {"product_ids": ["p1", "p2"]}, "GET", "/v2/commerce/products/p1,p2", {"products": [{"id": "p2"}, {"id": "p1"}]}),
    ("delete_product", {"product_id": "p1"}, "DELETE", "/v2/commerce/products/p1", None),
    ("list_inventory", {}, "GET", "/1.0/commerce/inventory", {"inventory": [], "pagination": {"hasNextPage": False}}),
    ("get_inventory", {"variant_ids": ["v1"]}, "GET", "/1.0/commerce/inventory/v1", {"inventory": [{"variantId": "v1", "quantity": 2}]}),
    ("adjust_inventory", {"variant_id": "v1", "quantity": 5, "idempotency_key": "stock-change-001"}, "POST", "/1.0/commerce/inventory/adjustments", None),
    ("list_orders", {}, "GET", "/1.0/commerce/orders", {"result": [], "pagination": {"hasNextPage": False}}),
    ("get_order", {"order_id": "o1"}, "GET", "/1.0/commerce/orders/o1", {"id": "o1"}),
    ("fulfill_order", {"order_id": "o1", "shipments": [{"carrierName": "UPS", "service": "Ground", "shipDate": "2024-08-25T15:00:00Z", "trackingNumber": "TRACK1"}]}, "POST", "/1.0/commerce/orders/o1/fulfillments", None),
    ("list_store_pages", {}, "GET", "/1.0/commerce/store_pages", {"storePages": [], "pagination": {"hasNextPage": False}}),
    ("list_transactions", {}, "GET", "/1.0/commerce/transactions", {"documents": [], "pagination": {"hasNextPage": False}}),
    ("get_transactions", {"transaction_ids": ["t1"]}, "GET", "/1.0/commerce/transactions/t1", {"documents": [{"id": "t1"}]}),
    ("list_profiles", {}, "GET", "/1.0/profiles", {"profiles": [], "pagination": {"hasNextPage": False}}),
    ("get_profiles", {"profile_ids": ["c1"]}, "GET", "/1.0/profiles/c1", {"profiles": [{"id": "c1"}]}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path,payload", CASES)
async def test_one_published_request_per_operation(transport, operation, args, method, path, payload):
    seen, replies = transport
    replies.append((204 if payload is None else 200, payload))
    result = await run(operation, args)
    assert result["success"] is True
    assert len(seen) == 1 and not replies
    assert seen[0].method == method and seen[0].url.path == path
    if payload is not None:
        assert result["data"] == payload
    else:
        assert result["acknowledged"] is True and result["readback_verified"] is False
    if operation == "adjust_inventory":
        assert seen[0].headers["Idempotency-Key"] == "stock-change-001"
        assert json.loads(seen[0].content) == {"setFiniteOperations": [{"variantId": "v1", "quantity": 5}]}
    if operation == "fulfill_order":
        body = json.loads(seen[0].content)
        assert body == {"shipments": args["shipments"], "shouldSendNotification": False}
        assert not seen[0].url.params


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,key,value", [("increment", "incrementOperations", {"variantId": "v1", "quantity": 2}), ("decrement", "decrementOperations", {"variantId": "v1", "quantity": 2}), ("set_unlimited", "setUnlimitedOperations", "v1")])
async def test_stock_modes_and_idempotency(transport, mode, key, value):
    seen, replies = transport
    replies.append((204, None))
    await run("adjust_inventory", {"variant_id": "v1", "quantity": 0 if mode == "set_unlimited" else 2, "adjustment": mode, "idempotency_key": "same-logical-change"})
    assert json.loads(seen[0].content) == {key: [value]}


@pytest.mark.asyncio
async def test_queries_and_explicit_cursor_do_not_follow_response_urls(transport):
    seen, replies = transport
    payload = {"result": [], "pagination": {"hasNextPage": True, "nextPageCursor": "opaque+/=", "nextPageUrl": "https://attacker.example/steal"}}
    replies.append((200, payload))
    result = await run("list_orders", {"modified_after": "2024-01-01T00:00:00Z", "modified_before": "2024-02-01T00:00:00Z", "fulfillment_status": "PENDING", "payment_states": "PAID,AUTHORIZED", "customer_id": "c1"})
    assert dict(seen[0].url.params) == {"modifiedAfter": "2024-01-01T00:00:00Z", "modifiedBefore": "2024-02-01T00:00:00Z", "fulfillmentStatus": "PENDING", "paymentStates": "PAID,AUTHORIZED", "customerId": "c1"}
    assert result["data"] == payload and len(seen) == 1
    replies.append((200, {"result": []}))
    await run("list_orders", {"cursor": result["data"]["pagination"]["nextPageCursor"]})
    assert dict(seen[1].url.params) == {"cursor": "opaque+/="}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [
    ("get_order", {"order_id": "../secret"}),
    ("get_products", {"product_ids": ["https://evil.test"]}),
    ("get_inventory", {"variant_ids": []}),
    ("list_orders", {"cursor": "c1", "fulfillment_status": "PAID"}),
    ("list_profiles", {"cursor": "c1", "email": "a@example.test"}),
    ("list_products", {"modified_after": "2024-01-01T00:00:00Z"}),
    ("list_orders", {"modified_after": "yesterday", "modified_before": "today"}),
    ("adjust_inventory", {"variant_id": "v1", "quantity": -1, "idempotency_key": "key1"}),
    ("adjust_inventory", {"variant_id": "v1", "quantity": 3}),
    ("adjust_inventory", {"variant_id": "v1", "quantity": 4, "adjustment": "set_unlimited", "idempotency_key": "key1"}),
])
async def test_invalid_arguments_before_http(transport, operation, args):
    with pytest.raises(ValueError):
        await run(operation, args)
    assert not transport[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_provider_rejections_are_errors_without_retries_or_secret(transport, status):
    seen, replies = transport
    replies.append((status, {"message": "Provider rejection " + TOKEN}))
    result = await run("delete_product", {"product_id": "p1"})
    assert result["success"] is False and result["http_status"] == status
    assert result["message"] == {"message": "Provider rejection [redacted]"}
    assert len(seen) == 1


@pytest.mark.parametrize("key", ["https://example.test", "<token>", "Bearer secret", "bad\nkey", "secret\u2014key"])
def test_bad_manual_keys_rejected(key):
    with pytest.raises(ValueError):
        sc.SquarespaceCommerceAPIKey(api_key=key)


def test_manual_credential_default_and_shaping():
    credential = sc.SquarespaceCommerceAPIKey(api_key="  " + TOKEN + "\n")
    assert credential.credential_type == sc.CREDENTIAL_TYPE and credential.api_key == TOKEN


@pytest.mark.asyncio
async def test_unsaved_key_connection_evidence_names_the_site(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, {"id": "site1", "title": "Fixture Store"}))
    evidence = await collect_evidence(node_type=NODE, credential_data=AUTH, user_id="11111111-1111-4111-8111-111111111111")
    assert evidence.reachable is True and evidence.account_label == "Fixture Store"
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_uncertain_write_is_not_retried(monkeypatch):
    client = AsyncMock()
    client.request.side_effect = httpx.ReadTimeout("contains " + TOKEN)
    client.__aenter__.return_value = client
    monkeypatch.setattr(sc, "guarded_async_client", lambda **kwargs: client)
    result = await run("adjust_inventory", {"variant_id": "v1", "idempotency_key": "stock1"})
    assert result["success"] is False and result["write_outcome"] == "unknown"
    assert TOKEN not in str(result) and client.request.await_count == 1
