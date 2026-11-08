"""Replay the provider's exact saved examples through the native node factory.

Transport fault tests deliberately corrupt an example or its transport metadata;
these are rejection tests, never provider witnesses or conformance evidence.
"""
import base64
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import razorpay_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/razorpay/collection_examples.json").read_text())["operations"]
CREDENTIAL = {"credential_type": "razorpay_api_key", "key_id": "rzp_test_fixture42", "key_secret": "fixture-secret-42"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def config(operation):
    raw = EXAMPLES[operation]["request"].get("body", {}).get("raw")
    value = json.loads(raw) if raw else {}
    if operation == "create_subscription":
        value.pop("addons")
        value["customer_notify"] = bool(value["customer_notify"])
    if operation == "create_payment_link":
        value.pop("callback_url")
        value.pop("callback_method")
    return {"operation": operation, **value}


def node(cfg, credential=None):
    return NodeFactory.create_node(node_id="razorpay-fixture", node_type="automation-razorpay",
        node_data={"config": cfg, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, *, operation="list_customers", example=0, status=None, body=None, content_type=None, error=None):
    saved = EXAMPLES[operation]["responses"][example]
    requests = []
    def respond(request):
        requests.append(request)
        if error:
            raise error("Injected transport failure", request=request)
        return httpx.Response(status or saved["code"], content=saved["body"] if body is None else body,
            headers={"Content-Type": content_type or next(h["value"] for h in saved["header"] if h["key"].lower() == "content-type")})
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example", [(op, i) for op, entry in EXAMPLES.items() for i in range(len(entry["responses"]))])
async def test_razorpay_saved_collection_examples_and_exact_requests(monkeypatch, operation, example):
    requests = transport(monkeypatch, operation=operation, example=example)
    n = node(config(operation))
    emitted = []
    async def emit(output):
        emitted.append(output)
    n.emit = emit
    result = await n.execute({})
    assert result["status"] == "success" and emitted == [result]
    method, path, _ = native.ROUTES[operation]
    assert len(requests) == 1 and requests[0].method == method
    assert str(requests[0].url).split("?")[0] == native.BASE_URL + path
    basic = base64.b64encode((CREDENTIAL["key_id"] + ":" + CREDENTIAL["key_secret"]).encode()).decode()
    assert requests[0].headers["authorization"] == "Basic " + basic
    assert all(s not in str(result) for s in (CREDENTIAL["key_id"], CREDENTIAL["key_secret"], basic))
    saved_body = json.loads(EXAMPLES[operation]["responses"][example]["body"])
    if method == "POST":
        assert result["item"] == saved_body
        assert result["write_acknowledged"] and result["readback_verified"] is False
        sent = json.loads(requests[0].content)
        expected = config(operation)
        expected.pop("operation")
        # Defaults are intentional and can suppress provider notification defaults.
        assert all(sent[k] == v for k, v in expected.items())
        assert not requests[0].url.query
    else:
        assert result["items"] == saved_body.get("items", saved_body.get("payment_links"))
        assert result["complete"] is False and result["page_only"] is True
        assert dict(requests[0].url.params) == ({"count": "10"} if operation in {"list_customers", "list_orders", "list_refunds"} else {})
        assert not requests[0].content


@pytest.mark.asyncio
async def test_razorpay_notifications_default_off_and_nested_body(monkeypatch):
    requests = transport(monkeypatch, operation="create_payment_link")
    assert (await node({"operation": "create_payment_link", "amount": 1000, "description": "Payment"}).execute({}))["status"] == "success"
    sent = json.loads(requests[0].content)
    assert sent["notify"] == {"sms": False, "email": False}
    assert sent["reminder_enable"] is False and sent["accept_partial"] is False
    requests = transport(monkeypatch, operation="create_subscription")
    await node({"operation": "create_subscription", "plan_id": "plan_00000000000001", "total_count": 6}).execute({})
    assert json.loads(requests[0].content)["customer_notify"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 301, 302, 401, 403, 404, 429, 500])
async def test_razorpay_transport_faults_never_report_success_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, operation="create_order", status=status)
    result = await node(config("create_order")).execute({})
    assert len(requests) == 1 and result["status"] == "error" and result["http_status"] == status
    assert "item" not in result
    if status == 500:
        assert result["write_outcome"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
async def test_razorpay_ambiguous_write_is_not_retried(monkeypatch, error):
    requests = transport(monkeypatch, operation="create_order", error=error)
    result = await node(config("create_order")).execute({})
    assert len(requests) == 1 and result["status"] == "error" and result["write_outcome"] == "unknown"


@pytest.mark.asyncio
async def test_razorpay_malformed_and_foreign_examples_are_rejected(monkeypatch):
    customer = json.loads(EXAMPLES["list_customers"]["responses"][0]["body"])
    malformed = deepcopy(customer)
    malformed["count"] += 1
    for body in (malformed, json.loads(EXAMPLES["list_orders"]["responses"][0]["body"]), json.loads(EXAMPLES["create_customer"]["responses"][0]["body"])):
        transport(monkeypatch, body=json.dumps(body))
        result = await node({"operation": "list_customers"}).execute({})
        assert result["status"] == "error" and "items" not in result
    transport(monkeypatch, content_type="text/html")
    assert (await node({"operation": "list_customers"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_razorpay_secret_echo_in_published_shape_is_redacted(monkeypatch):
    body = json.loads(EXAMPLES["list_customers"]["responses"][0]["body"])
    body["items"][0]["name"] = CREDENTIAL["key_secret"]
    transport(monkeypatch, body=json.dumps(body))
    result = await node({"operation": "list_customers"}).execute({})
    assert result["items"][0]["name"] == "[redacted]" and CREDENTIAL["key_secret"] not in str(result)


@pytest.mark.parametrize("cfg", [
    {"operation": "list_customers", "count": 101},
    {"operation": "create_order", "amount": True},
    {"operation": "create_order", "amount": 0},
    {"operation": "create_plan", "period": "daily", "interval": 1, "item": {"amount": 100, "name": "Plan"}},
    {"operation": "create_subscription", "plan_id": "../other", "total_count": 1},
    {"operation": "create_payment_link", "amount": 1000, "description": "Payment", "notify": {"sms": True}},
    {"operation": "create_payment_link", "amount": 1000, "description": "Payment", "first_min_partial_amount": 100},
    {"operation": "list_payments", "api_url": "https://example.com"},
])
def test_razorpay_config_guards(cfg):
    with pytest.raises(ValueError):
        native.RazorpayNode.parse_config({"config": cfg, "credentials": CREDENTIAL})


@pytest.mark.parametrize("value", ["https://example.com/key", "<token>", "key:secret", "key secret", "key\nsecret", "clé"])
def test_razorpay_credentials_reject_paste_errors_without_exposing_values(value):
    with pytest.raises(ValidationError):
        native.RazorpayAPIKeyCredential.model_validate({**CREDENTIAL, "key_secret": value})


def test_razorpay_credential_family_evidence_and_paste_cleanup():
    assert native.RazorpayAPIKeyCredential.model_validate({**CREDENTIAL, "key_secret": " fixture-secret-42 \n"}).key_secret == CREDENTIAL["key_secret"]
    with pytest.raises(ValueError):
        native.RazorpayNode.parse_config({"config": {"operation": "list_customers"}, "credentials": {**CREDENTIAL, "credential_type": "foreign_api_key"}})
    assert native.RazorpayNode.connection_evidence.operation == "list_customers"
    assert native.RazorpayNode.connection_evidence.proves == "account"
    assert len(native.ROUTES) == 15
