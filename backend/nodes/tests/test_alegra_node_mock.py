"""Exercise Alegra at the HTTP boundary using its published response examples.

The tests cover sales request bodies, pagination, credential failures, and the
subscription lifecycle with verbatim provider event payloads.
"""
import base64
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import alegra_node as a

FIXTURES = Path(__file__).parent / "fixtures" / "alegra"
SALES = json.loads((FIXTURES / "sales.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())
AUTH = {"email": "api@example.com", "api_token": "test-api-token"}


def config(name):
    values = {"operation": name}
    if name.startswith(("get_", "update_", "delete_")):
        values["id"] = "123"
    if name.startswith(("create_", "update_")):
        values["date"] = "2015-11-15"
        if name.endswith("payment"):
            values.update(bank_account_id="1", invoices_json='[{"id":"6","amount":150}]', payment_method="cash")
        else:
            values.update(client_id="2", items_json='[{"id":"1","price":120,"quantity":5}]')
            if not name.endswith("credit_note"):
                values["due_date"] = "2015-12-15"
    return values


@pytest.fixture
def wire(monkeypatch):
    seen, replies = [], []
    native = httpx.AsyncClient
    def transport(request):
        seen.append(request)
        assert request.url.host == "api.alegra.com"
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"api@example.com:test-api-token").decode()
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    monkeypatch.setattr(a.httpx, "AsyncClient", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(transport)))
    return seen, replies


def node(values):
    model = a.AlegraNode.parse_config({"config": values, "credentials": AUTH})
    return a.AlegraNode(node_id="alegra", node_type="automation-alegra", node_data={"config": values}, config=model, sio=Mock())


@pytest.mark.asyncio
@pytest.mark.parametrize("name", SALES)
async def test_sales_documented_response_and_request(name, wire):
    seen, replies = wire
    case = SALES[name]
    replies.append((200, case["body"]))
    result = await node(config(name)).execute({})
    assert result["status"] == "success"
    request = seen[0]
    assert request.method == case["method"]
    assert request.url.path == "/api/v1" + case["path"].replace("{id}", "123")
    if name.startswith("list_"):
        assert dict(request.url.params) == {"start": "0", "limit": "30", "order_direction": "ASC"}
        assert isinstance(result["data"], list)
    elif name.startswith(("create_", "update_")):
        body = json.loads(request.content)
        assert body["date"] == "2015-11-15"
        if name.endswith("payment"):
            assert body["bankAccount"] == {"id": "1"}
            assert body["invoices"] == [{"id": "6", "amount": 150}]
            assert body["paymentMethod"] == "cash"
        else:
            assert body["client"] == {"id": "2"}
            assert body["items"] == [{"id": "1", "price": 120, "quantity": 5}]
            assert "items_json" not in body
            assert ("dueDate" in body) == (not name.endswith("credit_note"))


@pytest.mark.asyncio
async def test_offset_continuation(wire):
    _, replies = wire
    replies.append((200, [{"id": "1"}]))
    assert (await node({"operation": "list_invoices", "start": 5, "limit": 1}).execute({}))["next_start"] == 6
    replies.append((200, []))
    assert (await node({"operation": "list_invoices", "start": 6, "limit": 1}).execute({}))["next_start"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_errors_preserve_provider_text_and_redact_secrets(status, wire):
    _, replies = wire
    replies.append((status, {"error": "Rejected test-api-token"}))
    with pytest.raises(ValueError, match=f"Alegra API error {status}: Rejected \\[redacted\\]"):
        await node({"operation": "list_invoices"}).execute({})


@pytest.mark.parametrize("bad", ["https://example.com/token", "<token>", "a b", "Basic abc", "a:b"])
def test_bad_credentials(bad):
    with pytest.raises(ValidationError):
        a.AlegraAPITokenCredential(email="api@example.com", api_token=bad)


def test_typed_inputs_reject_bad_lines_and_path_injection():
    for name, changes in [("get_invoice", {"id": "../payments"}), ("create_invoice", {"items_json": "{}"}),
                          ("create_invoice", {"items_json": '[{"id":"1","price":-1,"quantity":1}]'}),
                          ("list_invoices", {"limit": 31})]:
        with pytest.raises(ValueError):
            node({**config(name), **changes})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", a.EVENTS)
async def test_webhook_lifecycle_and_documented_event(operation, wire):
    seen, replies = wire
    subject, kind = a.EVENTS[operation]
    replies.append((201, {"subscription": {"id": "sub-1", "event": subject}}))
    state = await a.AlegraNode._register_external_webhook(webhook_url="https://hook.hooks.example.test/test", credential=AUTH, config={"operation": operation}, node_id="alegra")
    assert json.loads(seen[0].content) == {"event": subject, "url": "hook.hooks.example.test/test"}
    assert state == {"external_webhook_id": "sub-1"}
    payload = EVENTS[subject]["body"]
    assert a.AlegraNode.verify_webhook_signature(json.dumps(payload).encode(), {}, {}) is True
    assert a.AlegraNode.handle_webhook_handshake(b"{}", {}) == {"ok": True}
    assert a.AlegraNode.handle_webhook_handshake(b"", {}) == {"ok": True}
    assert a.AlegraNode.handle_webhook_handshake(json.dumps(payload).encode(), {}) is None
    out = a.AlegraNode.resolve_trigger_payload(payload, {"operation": operation})
    event = a.AlegraNode.resolve_agent_event(out)
    assert payload["message"][kind]["id"] in event["text"]
    assert "Alegra" in event["text"]
    assert not a.AlegraNode.filter_trigger_payload({"subject": "other", "message": {}}, {"operation": operation})
    replies.append((204, None))
    await a.AlegraNode._unregister_external_webhook(credential=AUTH, config=state, node_id="alegra")
    assert seen[-1].method == "DELETE"
    assert seen[-1].url.path == "/api/v1/webhooks/subscriptions/sub-1"
    manual = node({"operation": operation})
    result = await manual.execute({"subject": subject})
    assert result["status"] == "no_event"
    assert manual.trigger_produced_no_event(result)


@pytest.mark.asyncio
async def test_partial_update_preserves_omitted_fields(wire):
    seen, replies = wire
    replies.append((200, {"id": "123", "observations": "Updated"}))
    await node({"operation": "update_invoice", "id": "123", "observations": "Updated"}).execute({})
    assert json.loads(seen[0].content) == {"observations": "Updated"}
    with pytest.raises(ValueError):
        node({"operation": "update_invoice", "id": "123"})
