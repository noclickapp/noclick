"""Requests, documented payloads, signatures and registration lifecycle."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.mycashflow_node import MyCashflowNode, MyCashflowNodeConfig, MyCashflowCredential

CRED = {"credential_type": "mycashflow_api_key", "store_name": "example", "email": "api@example.com", "api_key": "test-secret"}

@pytest.mark.asyncio
async def test_write_routes_and_body(monkeypatch):
    request = AsyncMock(return_value={"data": {"balance": 12}})
    monkeypatch.setattr(MyCashflowNode, "_request", request)
    node = MyCashflowNode(node_id="test", node_type="automation-mycashflow", node_data={},
        config=MyCashflowNodeConfig(config={"operation": "adjust_stock", "productCode": "AE/123", "balance_change": -4}, credentials=CRED))
    result = await node.execute({})
    assert result["data"]["balance"] == 12
    assert request.call_args.args[1:] == ("POST", "/v1/stock/AE%2F123/update-balance")
    assert request.call_args.kwargs["body"] == {"balance_change": -4}

@pytest.mark.asyncio
async def test_registration_and_cleanup(monkeypatch):
    request = AsyncMock(return_value={"data": {"uuid": "083c584d-ae65-11ec-aef4-0242ac130002"}})
    monkeypatch.setattr(MyCashflowNode, "_request", request)
    state = await MyCashflowNode._register_external_webhook(webhook_url="https://example.com", credential=CRED,
        config={"operation": "on_event", "event_type": "order.created"}, node_id="test")
    assert state["signing_secret"] == CRED["api_key"]
    assert request.call_args.kwargs["body"] == {"url": "https://example.com", "topic": "order.created"}
    await MyCashflowNode._unregister_external_webhook(credential=CRED, config=state, node_id="test")
    assert request.call_args.args[1:] == ("DELETE", "/v1/webhooks/083c584d-ae65-11ec-aef4-0242ac130002")

@pytest.mark.parametrize("topic", ["order.created", "order.archived", "order.unarchived", "campaign.created", "campaign.updated", "order.comment.created", "marketing.newsletter.updated"])
def test_documented_order_payload(topic):
    # Property examples from the published callback schemas: id, meta.webhook_topic.
    payload = json.loads((Path(__file__).parent / "fixtures/mycashflow" / (topic.replace(".", "_") + ".json")).read_text())
    body = json.dumps(payload).encode()
    signature = base64.b64encode(hmac.new(b"test-secret", body, hashlib.sha256).digest()).decode()
    config = {"event_type": topic, "signing_secret": "test-secret"}
    assert MyCashflowNode.verify_webhook_signature(body, {"X-MCF-Webhook-Signature": signature}, config)
    assert not MyCashflowNode.verify_webhook_signature(body+b" ", {"X-MCF-Webhook-Signature": signature}, config)
    assert not MyCashflowNode.verify_webhook_signature(body, {}, config)
    assert MyCashflowNode.filter_trigger_payload(payload, config)
    assert not MyCashflowNode.filter_trigger_payload(payload, {"event_type": "other"})
    result = MyCashflowNode.resolve_agent_event(MyCashflowNode.resolve_trigger_payload(payload, config))
    assert topic in result["text"] and str(payload["data"].get("id", payload["data"].get("order_id"))) in result["text"]

@pytest.mark.parametrize("host", ["example.com", "https://example.mycashflow.fi", "a/b", "evil@host", "-bad"])
def test_store_host_is_bounded(host):
    with pytest.raises(ValueError):
        MyCashflowCredential.model_validate({**CRED, "store_name": host})

@pytest.mark.asyncio
async def test_basic_auth_and_default_domain(monkeypatch):
    def respond(request):
        assert str(request.url) == "https://example.mycashflow.fi/api/v1/products?page=2"
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"api@example.com:test-secret").decode()
        return httpx.Response(200, json={"data": [], "meta": {"item_count": 0}})
    monkeypatch.setattr("nodes.mycashflow_node.guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kw))
    assert await MyCashflowNode._request(CRED, "GET", "/v1/products", params={"page": 2}) == {"data": [], "meta": {"item_count": 0}}
