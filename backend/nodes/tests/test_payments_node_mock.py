"""Contract-shaped requests and scheduled payment detection, without live writes."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import payments_node as api

KEY = {"credential_type": "payments_api_key", "api_key": "fixture-service-key-123"}
PAYMENT_ID = "hu20sqlact5260q2nanm0q8u93"
AGREEMENT_ID = "cgc1ocvh0pt9fqs0ma67r42l58"


def node(operation, **fields):
    config = {"config": {"operation": operation, **fields}, "credentials": deepcopy(KEY)}
    return api.PaymentsNode("fixture", "automation-payments", config, config=api.PaymentsNode.parse_config(config))


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    native = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        assert request.url.host == "publicapi.payments.service.gov.uk"
        assert request.headers["Authorization"] == "Bearer " + KEY["api_key"]
        code, body = replies.pop(0)
        return httpx.Response(code, json=body) if body is not None else httpx.Response(code)
    monkeypatch.setattr(api.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(respond)))
    return calls, replies


CASES = [
    ("search_payments", {"reference": "12345", "state": "success"}, "GET", "/v1/payments", None),
    ("create_payment", {"amount": 12000, "description": "New passport application", "reference": "12345", "return_url": "https://service-name.gov.uk/transactions/12345", "delayed_capture": False, "idempotency_key": "passport-12345"}, "POST", "/v1/payments", {"amount": 12000, "description": "New passport application", "reference": "12345", "return_url": "https://service-name.gov.uk/transactions/12345", "delayed_capture": False}),
    ("get_payment", {"payment_id": PAYMENT_ID}, "GET", f"/v1/payments/{PAYMENT_ID}", None),
    ("cancel_payment", {"payment_id": PAYMENT_ID}, "POST", f"/v1/payments/{PAYMENT_ID}/cancel", None),
    ("capture_payment", {"payment_id": PAYMENT_ID}, "POST", f"/v1/payments/{PAYMENT_ID}/capture", None),
    ("get_payment_events", {"payment_id": PAYMENT_ID}, "GET", f"/v1/payments/{PAYMENT_ID}/events", None),
    ("list_payment_refunds", {"payment_id": PAYMENT_ID}, "GET", f"/v1/payments/{PAYMENT_ID}/refunds", None),
    ("create_refund", {"payment_id": PAYMENT_ID, "amount": 150000, "refund_amount_available": 200000}, "POST", f"/v1/payments/{PAYMENT_ID}/refunds", {"amount": 150000, "refund_amount_available": 200000}),
    ("get_refund", {"payment_id": PAYMENT_ID, "refund_id": "act4c33qeqwk1bl41hl2un3f8y"}, "GET", f"/v1/payments/{PAYMENT_ID}/refunds/act4c33qeqwk1bl41hl2un3f8y", None),
    ("search_refunds", {"from_date": "2015-08-13T12:35:00Z"}, "GET", "/v1/refunds", None),
    ("search_agreements", {"status": "active"}, "GET", "/v1/agreements", None),
    ("create_agreement", {"reference": "CT-22-23-0001", "description": "Dorset Council 2022/23 council tax subscription.", "user_identifier": "user-3fb81107-76b7-4910"}, "POST", "/v1/agreements", {"reference": "CT-22-23-0001", "description": "Dorset Council 2022/23 council tax subscription.", "user_identifier": "user-3fb81107-76b7-4910"}),
    ("get_agreement", {"agreement_id": AGREEMENT_ID}, "GET", f"/v1/agreements/{AGREEMENT_ID}", None),
    ("cancel_agreement", {"agreement_id": AGREEMENT_ID}, "POST", f"/v1/agreements/{AGREEMENT_ID}/cancel", None),
    ("search_disputes", {"status": "won", "page": 2, "display_size": 50}, "GET", "/v1/disputes", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,body", CASES)
async def test_request_contract(transport, operation, fields, method, path, body):
    calls, replies = transport
    empty = operation in {"cancel_payment", "capture_payment", "cancel_agreement"}
    replies.append((204 if empty else 200, None if empty else {"payment_id": PAYMENT_ID}))
    result = await node(operation, **fields).execute({})
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert (json.loads(request.content) if request.content else None) == body
    if "idempotency_key" in fields:
        assert request.headers["Idempotency-Key"] == fields["idempotency_key"]
    for key in api.OPERATIONS[operation]["query"]:
        if key in fields:
            assert request.url.params[key] == str(fields[key])
    assert KEY["api_key"] not in str(request.url) and KEY["api_key"] not in str(result)


@pytest.mark.asyncio
async def test_rejection_is_not_retried_and_redacts_key(transport):
    calls, replies = transport
    replies.append((401, {"description": "Unauthorised " + KEY["api_key"]}))
    with pytest.raises(ValueError, match="HTTP 401") as exc:
        await node("search_payments").execute({})
    assert KEY["api_key"] not in str(exc.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_poll_paginates_then_baselines_and_emits_new_payments(transport):
    calls, replies = transport
    instance = node("on_new_payment", from_date="2015-08-13T12:35:00Z")
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(state)
        if replacement is not None:
            state = replacement
        return result
    instance._update_node_state = update
    first_page = [{"payment_id": str(i), "reference": "12345"} for i in range(500)]
    replies.extend([(200, {"results": first_page}), (200, {"results": []})])
    assert (await instance.execute({}))["new_payment_count"] == 0
    assert calls[1].url.params["page"] == "2"
    replies.append((200, {"results": [first_page[0], {"payment_id": PAYMENT_ID, "reference": "12345", "description": "New passport application"}]}))
    output = await instance.execute({})
    assert output["new_payment_count"] == 1
    event = api.PaymentsNode.resolve_agent_event(output)
    assert PAYMENT_ID in event["text"] and "New passport application" in event["text"]
    replies.append((200, {"results": [{"payment_id": PAYMENT_ID}]}))
    assert (await instance.execute({}))["new_payment_count"] == 0
    assert not instance.should_propagate_output({"new_payment_count": 0}, {"operation": "on_new_payment"})


@pytest.mark.asyncio
async def test_invalid_poll_response_does_not_consume_state(transport):
    _, replies = transport
    replies.append((200, {"results": [{"reference": "missing id"}]}))
    instance = node("on_new_payment")
    instance._filter_unseen = AsyncMock()
    with pytest.raises(ValueError, match="payment IDs"):
        await instance.execute({})
    instance._filter_unseen.assert_not_called()


def test_manual_key_default_and_invalid_fields():
    assert api.PaymentsAPIKeyCredential(api_key=KEY["api_key"]).credential_type == "payments_api_key"
    for key in ["Bearer abc", "https://example.org/key", "<token>"]:
        with pytest.raises(ValidationError):
            api.PaymentsAPIKeyCredential(api_key=key)
    for fields in [{"payment_id": "../bad"}, {"payment_id": "abc/def"}]:
        with pytest.raises(ValueError):
            node("get_payment", **fields)
    with pytest.raises(ValueError):
        node("search_payments", display_size=501)


@pytest.mark.asyncio
async def test_documented_payment_response_and_poll_event(transport):
    _, replies = transport
    documented = json.loads((Path(__file__).parent / "fixtures/payments/created_payment.json").read_text())["body"]
    replies.append((201, documented))
    output = await node("create_payment", amount=14500, description="Pay your council tax", reference="12345", return_url="https://your.service.gov.uk/completed").execute({})
    assert output == documented
    assert output["_links"]["next_url"]["href"].startswith("https://www.payments.service.gov.uk/")
    replies.append((200, {"results": [documented]}))
    instance = node("on_new_payment")
    async def update(mutator, **kwargs):
        return mutator({"seen_ids": []})[1]
    instance._update_node_state = update
    output = await instance.execute({})
    assert output["new_payment_count"] == 1
    assert documented["payment_id"] in instance.resolve_agent_event(output)["text"]
