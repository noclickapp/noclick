"""Bold native factory, wire contracts and webhook lifecycle regressions.

Fixtures use the provider's pinned schema examples; transport is offline and
no Bold account or live customer is changed.
"""
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import bold_commerce_node as native
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "bold_commerce_token", "api_token": "synthetic-test-token", "shop_identifier": "123456"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/bold_commerce/documented.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="bold-fixture", node_type="automation-bold-commerce", node_data={"config": config, "credentials": AUTH})


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    client = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.boldcommerce.com"
        assert request.headers["Authorization"] == "Bearer synthetic-test-token"
        assert request.headers["Bold-API-Version-Date"] == "2022-05-01"
        return replies.pop(0)
    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body", [
    ("get_shop", {}, "GET", "/shop", None),
    ("get_customer", {"customer_id": 12}, "GET", "/customers/12", None),
    ("update_customer", {"customer_id": 12, "first_name": "Jane", "last_name": "Doe", "email": "jane.doe@example.com", "phone": "12045551234", "notes": "Loyal customer"}, "PUT", "/customers/12", {"customer": {"first_name": "Jane", "last_name": "Doe", "email": "jane.doe@example.com", "phone": "12045551234", "notes": "Loyal customer"}}),
    ("list_customer_addresses", {"customer_id": 12}, "GET", "/customers/12/addresses", None),
    ("list_customer_subscriptions", {"customer_id": 12}, "GET", "/customers/12/subscriptions", None),
    ("get_subscription", {"subscription_id": 1}, "GET", "/subscriptions/1", None),
    ("update_discount_code", {"subscription_id": 1, "discount_code": "HOLIDAY10"}, "PUT", "/subscriptions/1/discount_code", {"discount_code": "HOLIDAY10"}),
    ("remove_discount_code", {"subscription_id": 1}, "DELETE", "/subscriptions/1/discount_code", None),
    ("update_next_order_datetime", {"subscription_id": 1, "nextDate": "2020-01-20T18:00:00Z"}, "PUT", "/subscriptions/1/next_order_datetime", {"nextDate": "2020-01-20T18:00:00Z", "includeFutureOrders": False}),
    ("skip_order", {"subscription_id": 1, "date": "2020-01-20T18:00:00Z"}, "PUT", "/subscriptions/1/skip", {"date": "2020-01-20T18:00:00Z"}),
    ("recover_order", {"subscription_id": 1, "date": "2020-01-20T18:00:00Z"}, "PUT", "/subscriptions/1/recover", {"date": "2020-01-20T18:00:00Z"}),
    ("cancel_subscription", {"subscription_id": 1}, "POST", "/subscriptions/1/cancel", None),
    ("pause_subscription", {"subscription_id": 1}, "POST", "/subscriptions/1/pause", None),
    ("reactivate_subscription", {"subscription_id": 1}, "POST", "/subscriptions/1/activate", None),
    ("get_order", {"subscription_id": 1, "order_id": 2}, "GET", "/subscriptions/1/orders/2", None),
    ("list_future_orders", {"subscription_id": 1}, "GET", "/subscriptions/1/future_orders", None),
    ("list_payment_methods", {"subscription_id": 1}, "GET", "/subscriptions/1/payment_methods", None),
    ("list_subscription_groups", {}, "GET", "/subscription_groups", None),
    ("get_subscription_group", {"group_id": 1}, "GET", "/subscription_groups/1", None),
])
async def test_native_dispatch(wire, operation, arguments, method, path, body):
    requests, replies = wire
    response = FIXTURE["shop"] if operation == "get_shop" else {"subscription": FIXTURE["subscription"]}
    replies.append(httpx.Response(200, json=response))
    result = await node({"operation": operation, **arguments}).execute({})
    assert result["status"] == "success" and result["data"] == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/subscriptions/v1/shops/123456" + path
    assert (json.loads(request.content) if request.content else None) == body
    assert not request.url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,query", [
    ("list_customers", {"page": 2, "limit": 10, "search": "Jane", "status": "active"}, {"page": "2", "limit": "10", "search": "Jane", "status": "active"}),
    ("list_subscriptions", {"limit": 5, "cursor": "next-cursor", "subscription_status": "paused", "expand": "customer"}, {"limit": "5", "cursor": "next-cursor", "subscription_status": "paused", "expand": "customer"}),
    ("list_orders", {"subscription_id": 1, "page": 2, "limit": 10}, {"page": "2", "limit": "10"}),
])
async def test_pagination_and_filters(wire, operation, config, query):
    requests, replies = wire
    response = {"pagination": {"limit": 10, "count": 0}, "subscriptions": [], "cursor": "next"}
    replies.append(httpx.Response(200, json=response))
    result = await node({"operation": operation, **config}).execute({})
    assert result["data"] == response
    assert dict(requests[0].url.params) == query


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_rejections_propagate_without_retry(wire, status):
    requests, replies = wire
    replies.append(httpx.Response(status, json={"message": "Unauthenticated"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "get_shop"}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("field,value", [("shop_identifier", "https://evil.test"), ("shop_identifier", "../shop"), ("shop_identifier", "x?token=y"), ("api_token", "Bearer abc")])
def test_invalid_credential_context(field, value):
    with pytest.raises(ValidationError):
        native.BoldCommerceTokenCredential.model_validate({**AUTH, field: value})


def test_manual_credential_tag_default():
    credential = native.BoldCommerceTokenCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"})
    assert credential.credential_type == "bold_commerce_token"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event", [(k, event) for k, events in native.TRIGGER_EVENTS.items() for event in events])
async def test_registration_and_unregistration(wire, operation, event):
    requests, replies = wire
    replies.extend([httpx.Response(200, json=FIXTURE["topics"]), httpx.Response(200, json={"webhook_subscription": {"id": 17}}), httpx.Response(200)])
    config = {"operation": operation, "event_type": event}
    result = await native.BoldCommerceNode._register_external_webhook(webhook_url="https://fixture.hooks.example.test", credential=AUTH, config=config, node_id="fixture")
    body = json.loads(requests[1].content)["webhook_subscription"]
    assert body["webhook_topic_id"] == next(t["id"] for t in FIXTURE["topics"]["webhook_topics"] if t["topic_name"] == event)
    assert body["shared_secret"] == result["signing_secret"]
    assert body["callback_url"] == "https://fixture.hooks.example.test"
    await native.BoldCommerceNode._unregister_external_webhook(credential=AUTH, config={**config, **result}, node_id="fixture")
    assert requests[2].method == "DELETE" and requests[2].url.path.endswith("/webhooks/subscriptions/17")


@pytest.mark.parametrize("operation,event", [(k, event) for k, events in native.TRIGGER_EVENTS.items() for event in events])
def test_provider_shaped_delivery_and_human_agent_event(operation, event):
    kind = "customer" if event in native.CUSTOMER_EVENTS else "order" if event in native.ORDER_EVENTS else "subscription"
    payload = dict(FIXTURE[kind])
    config = {"operation": operation, "event_type": event, "signing_secret": "fixture-shared-secret"}
    body = json.dumps(payload).encode()
    signature = hmac.new(config["signing_secret"].encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-Bold-Signature": signature, "Event-Identifier": event}
    assert native.BoldCommerceNode.verify_webhook_signature(body, headers, config)
    assert not native.BoldCommerceNode.verify_webhook_signature(body + b" ", headers, config)
    assert not native.BoldCommerceNode.verify_webhook_signature(body, {}, config)
    assert not native.BoldCommerceNode.verify_webhook_signature(body, {"x-bold-signature": "é"}, config)
    payload["_webhook"] = {"headers": headers}
    assert native.BoldCommerceNode.filter_trigger_payload(payload, config)
    assert not native.BoldCommerceNode.filter_trigger_payload(payload, {**config, "event_type": "wrong_event"})
    output = native.BoldCommerceNode.resolve_trigger_payload(payload, config)
    event_output = native.BoldCommerceNode.resolve_agent_event(output)
    assert str(payload["id"]) in event_output["text"]
    assert event in event_output["text"] or event == "subscription_order_created"
    assert "fixture-shared-secret" not in event_output["text"]
    if kind == "customer": assert "Jane" in event_output["text"] and "jane.doe@example.com" in event_output["text"]
    if kind == "subscription": assert str(payload["customer_id"]) in event_output["text"]


@pytest.mark.asyncio
async def test_connect_evidence_names_the_shop_with_one_read(wire):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = wire
    replies.append(httpx.Response(200, json=FIXTURE["shop"]))
    evidence = await collect_evidence(
        node_type="automation-bold-commerce", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH,
    )
    assert evidence.reachable is True
    assert evidence.account_label == FIXTURE["shop"]["shop"]["shop_domain"]
    assert len(requests) == 1 and requests[0].url.path.endswith("/shop")


@pytest.mark.asyncio
async def test_connect_rejection_keeps_the_provider_message(wire):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = wire
    replies.append(httpx.Response(401, json={"message": "Unauthenticated."}))
    evidence = await collect_evidence(
        node_type="automation-bold-commerce", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH,
    )
    assert evidence.reachable is False
    assert "Unauthenticated." in evidence.error
    assert AUTH["api_token"] not in evidence.error
    assert len(requests) == 1
