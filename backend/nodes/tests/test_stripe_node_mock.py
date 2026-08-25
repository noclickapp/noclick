"""
Offline mock tests for the Stripe node.

These run with NO Stripe credentials. ``httpx.AsyncClient`` is mocked so we can
assert, for EVERY operation, that the node builds the right request: correct HTTP
method + path, ``Authorization: Bearer`` header, form/bracket encoding,
``Idempotency-Key`` on writes, ``Stripe-Account`` passthrough, error handling,
custom-request routing, and Stripe webhook signature verification.

Run: pytest nodes/tests/test_stripe_node_mock.py
"""

import hashlib
import hmac
import time
import typing
from typing import Any, Dict, List, Optional

import pytest

import nodes.stripe_node as sn
from nodes.stripe_node import (
    StripeConfig,
    StripeNode,
    StripeNodeConfig,
    _OPERATIONS,
    _PATH_FIELDS,
    _to_form,
)

API_BASE = sn.STRIPE_API_BASE
API_KEY = "sk_test_123"


def _form_body() -> dict:
    """Parse the last request's urlencoded form body (sent via content=)."""
    from urllib.parse import parse_qsl

    content = CapturingClient.last.get("content")
    return dict(parse_qsl(content)) if content else {}


# --------------------------------------------------------------------------- #
# Mock httpx
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {"object": "thing", "id": "obj_123"}
        self.content = b'{"ok":1}'
        self.text = "fake error body"

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class CapturingClient:
    """Stand-in for httpx.AsyncClient that records the last request()."""

    last: Dict[str, Any] = {}
    next_response: Optional[FakeResponse] = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def request(self, method, url, headers=None, params=None, data=None, json=None, content=None, timeout=None):
        CapturingClient.last = {
            "method": method,
            "url": url,
            "headers": headers or {},
            "params": params,
            "data": data,
            "json": json,
            "content": content,
        }
        return CapturingClient.next_response or FakeResponse()

    async def get(self, url, headers=None, params=None, timeout=None):
        CapturingClient.last = {"method": "GET", "url": url, "headers": headers or {}, "params": params}
        return CapturingClient.next_response or FakeResponse(json_data={"data": [], "has_more": False})


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    CapturingClient.last = {}
    CapturingClient.next_response = None
    monkeypatch.setattr(sn.httpx, "AsyncClient", CapturingClient)
    yield


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_node(op_dict, credentials=None):
    cred = credentials or {"credential_type": "stripe_api_key", "api_key": API_KEY}
    node_config = StripeNodeConfig.model_validate({"config": op_dict, "credentials": cred})
    return StripeNode(
        node_id="test-node",
        node_type="automation-stripe",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


def _fake_value(annotation):
    """Produce a minimal valid value for a field annotation."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Literal:
        return args[0]
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        return _fake_value(non_none[0])
    if origin in (list, List):
        elem = args[0] if args else str
        elem_origin = typing.get_origin(elem)
        if elem_origin in (dict, Dict) or elem is dict:
            return [{"price": "price_1", "quantity": 1}]
        if elem is str:
            return ["item_evt"]
        return [_fake_value(elem)]
    if origin in (dict, Dict):
        return {"k": "v"}
    if annotation is int:
        return 1
    if annotation is float:
        return 1.5
    if annotation is bool:
        return True
    return "x"


def _union_members():
    union = typing.get_args(StripeConfig)[0]  # Annotated -> Union
    return list(typing.get_args(union))


def _op_of(member):
    return typing.get_args(member.model_fields["operation"].annotation)[0]


def _build_op_dict(member):
    d: Dict[str, Any] = {}
    for name, field in member.model_fields.items():
        if name == "operation":
            continue
        if field.is_required():
            d[name] = _fake_value(field.annotation)
    d["operation"] = _op_of(member)
    return d


# All routed operations (exclude the two special ops handled separately).
_ROUTED_MEMBERS = [
    m for m in _union_members() if _op_of(m) in _OPERATIONS
]


# --------------------------------------------------------------------------- #
# Coverage: every routed operation dispatches to the right method + path
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("member", _ROUTED_MEMBERS, ids=lambda m: _op_of(m))
async def test_operation_dispatch(member):
    op = _op_of(member)
    method, path_template = _OPERATIONS[op]
    op_dict = _build_op_dict(member)

    # Expected path: substitute path placeholders with the same fake values used.
    from urllib.parse import quote

    expected_path = path_template
    for field in _PATH_FIELDS[op]:
        expected_path = expected_path.replace("{" + field + "}", quote(str(op_dict[field]), safe=""))

    node = _make_node(op_dict)
    result = await node.execute({})

    assert result["status"] == "success", f"{op}: {result}"
    assert result["action"] == op
    captured = CapturingClient.last
    assert captured["method"] == method, f"{op}: method"
    assert captured["url"] == f"{API_BASE}{expected_path}", f"{op}: url"
    assert captured["headers"]["Authorization"] == f"Bearer {API_KEY}"
    if method in ("POST", "DELETE"):
        assert "Idempotency-Key" in captured["headers"], f"{op}: idempotency"
        # Body is a urlencoded form string, or None when the op has no body params.
        assert captured["content"] is None or isinstance(captured["content"], str)
    else:
        assert captured["content"] is None


def test_all_operations_have_configs():
    """Routing table and union stay in lockstep (no orphan operations)."""
    union_ops = {_op_of(m) for m in _union_members()}
    special = {"custom_request"} | sn._TRIGGER_OPERATIONS  # trigger ops are not routed
    assert set(_OPERATIONS) - union_ops == set()
    assert union_ops - set(_OPERATIONS) - special == set()
    # every decomposed trigger op maps to a Stripe event type, none collide with routed ops
    assert not (set(sn._TRIGGER_OPERATIONS) & set(_OPERATIONS))


# --------------------------------------------------------------------------- #
# Form / bracket encoding
# --------------------------------------------------------------------------- #


def test_to_form_bracket_notation():
    pairs = dict(
        _to_form(
            {
                "metadata": {"order_id": "6735"},
                "items": [{"price": "price_1", "quantity": 2}],
                "expand": ["customer"],
                "active": True,
                "skip_me": None,
            }
        )
    )
    assert pairs["metadata[order_id]"] == "6735"
    assert pairs["items[0][price]"] == "price_1"
    assert pairs["items[0][quantity]"] == "2"
    assert pairs["expand[0]"] == "customer"
    assert pairs["active"] == "true"  # booleans lower-cased for Stripe
    assert "skip_me" not in pairs


async def test_post_body_is_form_encoded():
    node = _make_node(
        {
            "operation": "create_customer",
            "email": "a@b.com",
            "metadata": {"plan": "pro"},
        }
    )
    await node.execute({})
    data = _form_body()
    assert data["email"] == "a@b.com"
    assert data["metadata[plan]"] == "pro"
    assert CapturingClient.last["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


async def test_extra_params_merged():
    node = _make_node(
        {
            "operation": "create_payment_intent",
            "amount": 2000,
            "currency": "usd",
            "extra_params": {"automatic_payment_methods": {"enabled": True}},
        }
    )
    await node.execute({})
    data = _form_body()
    assert data["amount"] == "2000"
    assert data["automatic_payment_methods[enabled]"] == "true"


# --------------------------------------------------------------------------- #
# Auth variants
# --------------------------------------------------------------------------- #


async def test_oauth_credential_uses_access_token():
    node = _make_node(
        {"operation": "retrieve_balance"},
        credentials={
            "credential_type": "stripe_oauth",
            "access_token": "sk_oauth_xyz",
            "stripe_user_id": "acct_1",
        },
    )
    await node.execute({})
    assert CapturingClient.last["headers"]["Authorization"] == "Bearer sk_oauth_xyz"


async def test_stripe_version_header_from_credential():
    node = _make_node(
        {"operation": "list_customers"},
        credentials={"credential_type": "stripe_api_key", "api_key": API_KEY, "stripe_version": "2024-06-20"},
    )
    await node.execute({})
    assert CapturingClient.last["headers"]["Stripe-Version"] == "2024-06-20"


async def test_stripe_version_header_from_custom_request():
    node = _make_node(
        {"operation": "custom_request", "http_method": "GET", "path": "/charges", "stripe_version": "2025-01-01"}
    )
    await node.execute({})
    assert CapturingClient.last["headers"]["Stripe-Version"] == "2025-01-01"


async def test_no_stripe_version_header_by_default():
    node = _make_node({"operation": "list_customers"})
    await node.execute({})
    assert "Stripe-Version" not in CapturingClient.last["headers"]


async def test_stripe_account_header_passthrough():
    node = _make_node(
        {"operation": "list_customers"},
        credentials={
            "credential_type": "stripe_api_key",
            "api_key": API_KEY,
            "stripe_account": "acct_connected_1",
        },
    )
    await node.execute({})
    assert CapturingClient.last["headers"]["Stripe-Account"] == "acct_connected_1"


async def test_missing_required_path_field_raises():
    # retrieve_customer needs customer_id; omit it.
    node = _make_node({"operation": "retrieve_customer", "customer_id": "cus_1"})
    # Tamper: blank the id to hit the guard.
    node.config.config.customer_id = ""
    with pytest.raises(ValueError):
        await node.execute({})


# --------------------------------------------------------------------------- #
# Custom request
# --------------------------------------------------------------------------- #


async def test_custom_request_strips_v1_prefix_and_routes_post():
    node = _make_node(
        {
            "operation": "custom_request",
            "http_method": "POST",
            "path": "/v1/issuing/cards",
            "params": {"type": "virtual"},
            "stripe_account": "acct_x",
        }
    )
    result = await node.execute({})
    assert result["action"] == "custom_request"
    assert CapturingClient.last["method"] == "POST"
    assert CapturingClient.last["url"] == f"{API_BASE}/issuing/cards"
    assert CapturingClient.last["headers"]["Stripe-Account"] == "acct_x"
    assert _form_body()["type"] == "virtual"


async def test_custom_request_v2_uses_json_and_host():
    node = _make_node(
        {
            "operation": "custom_request",
            "http_method": "POST",
            "path": "/v2/billing/meter_events",
            "params": {"event_name": "ai_tokens", "payload": {"value": "10"}},
        }
    )
    result = await node.execute({})
    assert result["status"] == "success"
    # v2 hits the bare host (no /v1) and sends JSON, not form pairs.
    assert CapturingClient.last["url"] == "https://api.stripe.com/v2/billing/meter_events"
    assert CapturingClient.last["data"] is None
    assert CapturingClient.last["json"]["event_name"] == "ai_tokens"


async def test_custom_request_get_uses_query():
    node = _make_node(
        {"operation": "custom_request", "http_method": "GET", "path": "charges", "params": {"limit": 3}}
    )
    await node.execute({})
    assert CapturingClient.last["method"] == "GET"
    assert CapturingClient.last["url"] == f"{API_BASE}/charges"
    assert dict(CapturingClient.last["params"])["limit"] == "3"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


async def test_error_response_shape():
    CapturingClient.next_response = FakeResponse(
        status_code=402,
        json_data={"error": {"message": "Your card was declined.", "code": "card_declined", "type": "card_error"}},
    )
    node = _make_node({"operation": "retrieve_charge", "charge_id": "ch_1"})
    result = await node.execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 402
    assert result["error"] == "Your card was declined."
    assert result["error_code"] == "card_declined"
    assert result["error_type"] == "card_error"


async def test_list_surfaces_pagination():
    CapturingClient.next_response = FakeResponse(
        json_data={"object": "list", "has_more": True, "data": [{"id": "cus_a"}, {"id": "cus_b"}]}
    )
    node = _make_node({"operation": "list_customers"})
    result = await node.execute({})
    assert result["has_more"] is True
    assert result["last_id"] == "cus_b"


# --------------------------------------------------------------------------- #
# Trigger
# --------------------------------------------------------------------------- #


def _stripe_signature(secret: str, body: bytes, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + body
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={v1}"


def test_verify_webhook_signature_valid_and_tampered():
    secret = "whsec_test"
    body = b'{"id":"evt_1","type":"payment_intent.succeeded"}'
    ts = int(time.time())
    header = _stripe_signature(secret, body, ts)
    cfg = {"signing_secret": secret}

    assert StripeNode.verify_webhook_signature(body, {"stripe-signature": header}, cfg) is True
    # Tampered body
    assert StripeNode.verify_webhook_signature(body + b"x", {"stripe-signature": header}, cfg) is False
    # Missing secret
    assert StripeNode.verify_webhook_signature(body, {"stripe-signature": header}, {}) is False
    # Missing header
    assert StripeNode.verify_webhook_signature(body, {}, cfg) is False


def test_filter_trigger_payload_allowlist():
    cfg = {"event_types": "payment_intent.succeeded, invoice.paid"}
    assert StripeNode.filter_trigger_payload({"type": "invoice.paid"}, cfg) is True
    assert StripeNode.filter_trigger_payload({"type": "charge.refunded"}, cfg) is False
    # Empty allowlist => all events pass (generic "On Custom Event")
    assert StripeNode.filter_trigger_payload({"type": "anything"}, {"operation": "on_event"}) is True


def test_decomposed_triggers_exist_and_map_to_events():
    # ~55 per-event trigger ops, each mapping to exactly one Stripe event type.
    assert len(sn._TRIGGER_EVENTS) >= 50
    assert sn._TRIGGER_EVENTS["on_invoice_paid"] == "invoice.paid"
    assert sn._TRIGGER_EVENTS["on_customer_subscription_deleted"] == "customer.subscription.deleted"
    assert sn._TRIGGER_EVENTS["on_payment_intent_succeeded"] == "payment_intent.succeeded"


def test_decomposed_trigger_filters_to_its_event():
    cfg = {"operation": "on_invoice_paid"}
    assert StripeNode.filter_trigger_payload({"type": "invoice.paid"}, cfg) is True
    assert StripeNode.filter_trigger_payload({"type": "invoice.created"}, cfg) is False
    assert StripeNode.filter_trigger_payload({"type": "payment_intent.succeeded"}, cfg) is False


async def test_decomposed_trigger_registers_its_single_event(monkeypatch):
    captured = {}

    async def fake_register(token, url, events, stripe_account=None):
        captured.update(token=token, url=url, events=events)
        return ("we_1", "whsec_1")

    monkeypatch.setattr(sn, "register_stripe_webhook", fake_register)
    extra = await StripeNode._register_external_webhook(
        webhook_url="https://e.com/h", credential={"api_key": API_KEY},
        config={"operation": "on_payment_intent_succeeded"}, node_id="n1",
    )
    assert captured["events"] == ["payment_intent.succeeded"]  # not ["*"]
    assert extra["signing_secret"] == "whsec_1"


def test_decomposed_trigger_ops_are_marked_triggers_in_schema():
    schema = StripeNode.get_config_schema()
    defs = schema["$defs"]
    cfg = defs["StripeOnInvoicePaidConfig"]
    assert cfg["properties"]["operation"].get("x-is-trigger") is True
    assert cfg.get("x-requires-webhook") is True


def test_resolve_agent_event_surfaces_object():
    out = {"type": "invoice.paid", "data": {"object": {"id": "in_1", "amount_paid": 500}}}
    resolved = StripeNode.resolve_agent_event(out)
    assert "invoice.paid" in resolved["text"]
    assert "in_1" in resolved["text"]
    assert resolved["conversation_key"] is None


async def test_register_stripe_webhook_uses_content_encoding(monkeypatch):
    """The trigger's webhook-registration helper must send a urlencoded body via
    content= (not httpx data=, which can break on an AsyncClient)."""
    captured = {}

    class _Resp:
        status_code = 200
        content = b"{}"

        def json(self):
            return {"id": "we_123", "secret": "whsec_abc"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, content=None, data=None):
            captured.update(url=url, headers=headers or {}, content=content, data=data)
            return _Resp()

    monkeypatch.setattr(sn.httpx, "AsyncClient", _Client)
    eid, secret = await sn.register_stripe_webhook("sk_test_x", "https://e.com/h", ["a.b", "c.d"])

    assert eid == "we_123" and secret == "whsec_abc"
    assert captured["data"] is None
    assert isinstance(captured["content"], str)
    assert "enabled_events" in captured["content"]
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert captured["url"].endswith("/webhook_endpoints")


async def test_trigger_manual_run_outputs_description():
    node = _make_node({"operation": "on_event", "event_types": "invoice.paid"})
    result = await node.execute({})
    assert result["action"] == "on_event"
    assert result["event_types"] == "invoice.paid"
