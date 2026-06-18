"""
Live, in-depth integration tests for the Stripe node.

Exercises real end-to-end flows against the Stripe API in TEST MODE across every
major product area, plus node mechanics (form/bracket encoding, pagination,
idempotency, expand, error types, dynamic dropdowns). Requires a test-mode secret
key in ``STRIPE_API_KEY`` (``sk_test_…``); skipped otherwise so CI stays green.

Uses Stripe's shared test payment methods (``pm_card_visa``,
``pm_card_chargeDeclined``). All created resources are cleaned up (deleted where
the API allows, archived otherwise).

Run: STRIPE_API_KEY=sk_test_xxx pytest nodes/tests/test_stripe_node.py
"""

import os
import time
import uuid

import pytest

from nodes.stripe_node import StripeNode, StripeNodeConfig

API_KEY = os.environ.get("STRIPE_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not API_KEY.startswith(("sk_test_", "rk_test_")),
    reason="STRIPE_API_KEY (test-mode sk_test_/rk_test_) not set; skipping live Stripe integration tests",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _node(op_dict, version=None):
    cred = {"credential_type": "stripe_api_key", "api_key": API_KEY}
    if version:
        cred["stripe_version"] = version
    cfg = StripeNodeConfig.model_validate({"config": op_dict, "credentials": cred})
    return StripeNode(
        node_id="test-node",
        node_type="automation-stripe",
        node_data={},
        config=cfg,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


async def _run(op_dict, version=None):
    return await _node(op_dict, version).execute({})


async def _ok(op_dict, version=None):
    r = await _run(op_dict, version)
    assert r["status"] == "success", f"{op_dict.get('operation')} failed: {r.get('error')}"
    return r["data"]


async def _delete(endpoint, rid):
    """Best-effort cleanup via the generic DELETE passthrough."""
    try:
        await _run({"operation": "custom_request", "http_method": "DELETE", "path": f"/{endpoint}/{rid}"})
    except Exception:
        pass


def _uniq(prefix):
    return f"{prefix}-{int(time.time() * 1000)}"


# --------------------------------------------------------------------------- #
# Core payments — real charge + refund with test cards
# --------------------------------------------------------------------------- #


async def test_retrieve_balance():
    data = await _ok({"operation": "retrieve_balance"})
    assert data["object"] == "balance"
    assert "available" in data


async def test_payment_intent_succeeds_and_refunds():
    customer = await _ok({"operation": "create_customer", "email": f"{_uniq('pay')}@example.com"})
    cid = customer["id"]
    try:
        pi = await _ok({
            "operation": "create_payment_intent",
            "amount": 1500, "currency": "usd", "customer": cid,
            "payment_method": "pm_card_visa", "confirm": True,
            "extra_params": {"off_session": True, "payment_method_types": ["card"]},
        })
        assert pi["status"] == "succeeded"

        refund = await _ok({"operation": "create_refund", "payment_intent": pi["id"]})
        assert refund["status"] == "succeeded"
        assert refund["amount"] == 1500

        charges = await _ok({"operation": "list_charges", "limit": 5, "extra_params": {"customer": cid}})
        assert charges["object"] == "list"
        assert any(c["id"] == pi["latest_charge"] for c in charges["data"])
    finally:
        await _delete("customers", cid)


async def test_declined_card_returns_card_error():
    customer = await _ok({"operation": "create_customer", "email": f"{_uniq('decl')}@example.com"})
    cid = customer["id"]
    try:
        r = await _run({
            "operation": "create_payment_intent",
            "amount": 1500, "currency": "usd", "customer": cid,
            "payment_method": "pm_card_chargeDeclined", "confirm": True,
            "extra_params": {"off_session": True, "payment_method_types": ["card"]},
        })
        assert r["status"] == "error"
        assert r["status_code"] == 402
        assert r["error_code"] == "card_declined"
    finally:
        await _delete("customers", cid)


# --------------------------------------------------------------------------- #
# Billing — product → recurring price → subscription lifecycle
# --------------------------------------------------------------------------- #


async def test_subscription_lifecycle():
    customer = await _ok({"operation": "create_customer", "email": f"{_uniq('sub')}@example.com"})
    cid = customer["id"]
    product = await _ok({"operation": "create_product", "name": _uniq("Plan")})
    pid = product["id"]
    try:
        attached = await _ok({"operation": "attach_payment_method", "payment_method_id": "pm_card_visa", "customer": cid})
        await _ok({
            "operation": "update_customer", "customer_id": cid,
            "extra_params": {"invoice_settings": {"default_payment_method": attached["id"]}},
        })
        price = await _ok({
            "operation": "create_price", "product": pid, "unit_amount": 999, "currency": "usd",
            "recurring": {"interval": "month"},
        })
        sub = await _ok({"operation": "create_subscription", "customer": cid, "items": [{"price": price["id"]}]})
        assert sub["status"] in ("active", "trialing")

        retrieved = await _ok({"operation": "retrieve_subscription", "subscription_id": sub["id"]})
        assert retrieved["id"] == sub["id"]

        updated = await _ok({
            "operation": "update_subscription", "subscription_id": sub["id"],
            "metadata": {"plan_tier": "gold"},
        })
        assert updated["metadata"]["plan_tier"] == "gold"

        items = await _ok({"operation": "list_subscription_items", "subscription": sub["id"]})
        assert len(items["data"]) == 1

        cancelled = await _ok({"operation": "cancel_subscription", "subscription_id": sub["id"]})
        assert cancelled["status"] == "canceled"
    finally:
        await _delete("customers", cid)
        await _run({"operation": "update_product", "product_id": pid, "active": False})


# --------------------------------------------------------------------------- #
# Invoicing — item → invoice → finalize → void
# --------------------------------------------------------------------------- #


async def test_invoice_lifecycle():
    customer = await _ok({"operation": "create_customer", "email": f"{_uniq('inv')}@example.com"})
    cid = customer["id"]
    try:
        await _ok({"operation": "create_invoice_item", "customer": cid, "amount": 700, "currency": "usd"})
        invoice = await _ok({
            "operation": "create_invoice", "customer": cid,
            "collection_method": "send_invoice",
            # Newer API versions (2026-05-27.dahlia) don't auto-pull pending items.
            "extra_params": {"days_until_due": 30, "pending_invoice_items_behavior": "include"},
        })
        assert invoice["status"] == "draft"

        finalized = await _ok({"operation": "finalize_invoice", "invoice_id": invoice["id"]})
        assert finalized["status"] == "open"
        assert finalized["amount_due"] == 700

        voided = await _ok({"operation": "void_invoice", "invoice_id": invoice["id"]})
        assert voided["status"] == "void"
    finally:
        await _delete("customers", cid)


# --------------------------------------------------------------------------- #
# Checkout + Payment Links (nested array params)
# --------------------------------------------------------------------------- #


async def test_checkout_session_lifecycle():
    product = await _ok({"operation": "create_product", "name": _uniq("Checkout")})
    pid = product["id"]
    price = await _ok({"operation": "create_price", "product": pid, "unit_amount": 2000, "currency": "usd"})
    try:
        session = await _ok({
            "operation": "create_checkout_session", "mode": "payment",
            "success_url": "https://example.com/success",
            "line_items": [{"price": price["id"], "quantity": 2}],
        })
        assert session["object"] == "checkout.session"

        retrieved = await _ok({"operation": "retrieve_checkout_session", "session_id": session["id"]})
        assert retrieved["id"] == session["id"]

        line_items = await _ok({"operation": "list_checkout_line_items", "session_id": session["id"]})
        assert line_items["data"][0]["quantity"] == 2

        expired = await _ok({"operation": "expire_checkout_session", "session_id": session["id"]})
        assert expired["status"] == "expired"
    finally:
        await _run({"operation": "update_price", "price_id": price["id"], "active": False})
        await _run({"operation": "update_product", "product_id": pid, "active": False})


async def test_payment_link_lifecycle():
    product = await _ok({"operation": "create_product", "name": _uniq("Link")})
    pid = product["id"]
    price = await _ok({"operation": "create_price", "product": pid, "unit_amount": 500, "currency": "usd"})
    try:
        link = await _ok({"operation": "create_payment_link", "line_items": [{"price": price["id"], "quantity": 1}]})
        assert link["url"].startswith("https://")

        items = await _ok({"operation": "list_payment_link_line_items", "payment_link_id": link["id"]})
        assert items["data"][0]["quantity"] == 1

        deactivated = await _ok({"operation": "update_payment_link", "payment_link_id": link["id"], "active": False})
        assert deactivated["active"] is False
    finally:
        await _run({"operation": "update_price", "price_id": price["id"], "active": False})
        await _run({"operation": "update_product", "product_id": pid, "active": False})


# --------------------------------------------------------------------------- #
# Coupons + Promotion Codes
# --------------------------------------------------------------------------- #


async def test_coupon_and_promotion_code():
    # Pin a Stripe version: 2026-05-27.dahlia changed the promotion_codes shape
    # (rejects the top-level `coupon` param). This also exercises the node's
    # stripe_version pinning feature.
    VERSION = "2024-06-20"
    coupon = await _ok({"operation": "create_coupon", "duration": "once", "percent_off": 25.0, "name": _uniq("25off")})
    try:
        code = _uniq("SAVE").upper().replace("-", "")
        promo = await _ok(
            {"operation": "create_promotion_code", "coupon": coupon["id"], "code": code},
            version=VERSION,
        )
        assert promo["coupon"]["id"] == coupon["id"]

        promos = await _ok({"operation": "list_promotion_codes", "coupon": coupon["id"]}, version=VERSION)
        assert any(p["id"] == promo["id"] for p in promos["data"])
    finally:
        await _delete("coupons", coupon["id"])


# --------------------------------------------------------------------------- #
# Tax rates, Webhook endpoints, Events
# --------------------------------------------------------------------------- #


async def test_tax_rate_create_and_list():
    rate = await _ok({
        "operation": "create_tax_rate", "display_name": "VAT", "percentage": 20.0, "inclusive": False,
    })
    assert rate["percentage"] == 20.0
    listed = await _ok({"operation": "list_tax_rates", "limit": 5})
    assert listed["object"] == "list"
    # tax rates can't be deleted; archive it
    await _run({"operation": "update_tax_rate", "tax_rate_id": rate["id"], "active": False})


async def test_webhook_endpoint_lifecycle():
    created = await _ok({
        "operation": "create_webhook_endpoint",
        "url": f"https://example.com/{_uniq('hook')}",
        "enabled_events": ["payment_intent.succeeded", "invoice.paid"],
    })
    wid = created["id"]
    try:
        assert set(created["enabled_events"]) == {"payment_intent.succeeded", "invoice.paid"}
        retrieved = await _ok({"operation": "retrieve_webhook_endpoint", "webhook_endpoint_id": wid})
        assert retrieved["id"] == wid
        updated = await _ok({"operation": "update_webhook_endpoint", "webhook_endpoint_id": wid, "extra_params": {"description": "updated"}})
        assert updated["description"] == "updated"
    finally:
        await _delete("webhook_endpoints", wid)


async def test_list_events():
    events = await _ok({"operation": "list_events", "limit": 3})
    assert events["object"] == "list"


# --------------------------------------------------------------------------- #
# Trigger — live webhook registration + Stripe-Signature verification
# --------------------------------------------------------------------------- #


async def test_webhook_registration_and_signature():
    import hashlib
    import hmac

    from nodes.stripe_node import register_stripe_webhook, unregister_stripe_webhook

    endpoint_id, secret = await register_stripe_webhook(
        API_KEY, f"https://example.com/{_uniq('hook')}", ["payment_intent.succeeded", "invoice.paid"]
    )
    try:
        assert endpoint_id.startswith("we_")
        assert secret.startswith("whsec_")  # real signing secret from Stripe

        # A signature computed with the real secret must verify; tampering must fail.
        body = b'{"id":"evt_1","type":"payment_intent.succeeded"}'
        ts = int(time.time())
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        header = f"t={ts},v1={sig}"
        assert StripeNode.verify_webhook_signature(body, {"stripe-signature": header}, {"signing_secret": secret}) is True
        assert StripeNode.verify_webhook_signature(body + b"x", {"stripe-signature": header}, {"signing_secret": secret}) is False
    finally:
        await unregister_stripe_webhook(API_KEY, endpoint_id)


async def test_trigger_external_webhook_register_unregister():
    # The hooks the trigger system actually calls (ExternalWebhookTriggerMixin).
    cred = {"api_key": API_KEY}
    extra = await StripeNode._register_external_webhook(
        webhook_url=f"https://example.com/{_uniq('hook')}",
        credential=cred,
        config={"event_types": "invoice.paid, charge.refunded"},
        node_id="trigger-node",
    )
    assert extra["external_webhook_id"].startswith("we_")
    assert extra["signing_secret"].startswith("whsec_")
    await StripeNode._unregister_external_webhook(
        credential=cred, config={"external_webhook_id": extra["external_webhook_id"]}, node_id="trigger-node"
    )


# --------------------------------------------------------------------------- #
# Specialized suites — Test Clocks & Radar (custom-suite typed ops)
# --------------------------------------------------------------------------- #


async def test_test_clock_lifecycle():
    clock = await _ok({"operation": "create_test_clock", "extra_params": {"frozen_time": 1750000000}})
    cid = clock["id"]
    try:
        assert clock["status"] in ("ready", "advancing")
        advanced = await _ok({"operation": "advance_test_clock", "test_clock_id": cid, "extra_params": {"frozen_time": 1750100000}})
        assert advanced["status"] in ("advancing", "ready")
    finally:
        await _delete("test_helpers/test_clocks", cid)


async def test_radar_value_list_lifecycle():
    vl = await _ok({
        "operation": "create_value_list",
        "extra_params": {"alias": _uniq("blk").replace("-", "_"), "name": _uniq("Blocklist"), "item_type": "card_fingerprint"},
    })
    vid = vl["id"]
    try:
        assert vl["object"] == "radar.value_list"
        listed = await _ok({"operation": "list_value_lists", "limit": 5})
        assert any(v["id"] == vid for v in listed["data"])
    finally:
        await _delete("radar/value_lists", vid)


# --------------------------------------------------------------------------- #
# Node mechanics — pagination, idempotency, expand, errors, dynamic options
# --------------------------------------------------------------------------- #


async def test_pagination_cursor():
    ids = []
    for i in range(3):
        c = await _ok({"operation": "create_customer", "email": f"{_uniq('pg')}-{i}@example.com", "metadata": {"pgtest": "1"}})
        ids.append(c["id"])
    try:
        page1 = await _run({"operation": "list_customers", "limit": 2})
        assert page1["has_more"] is True
        assert page1["last_id"]
        page2 = await _ok({"operation": "list_customers", "limit": 2, "starting_after": page1["last_id"]})
        assert page2["object"] == "list"
        # last_id is the cursor of the final item on page 1
        page1_ids = {c["id"] for c in page1["data"]["data"]}
        assert page1["last_id"] in page1_ids
        # page 2 doesn't repeat page 1's items
        page2_ids = {c["id"] for c in page2["data"]}
        assert page1_ids.isdisjoint(page2_ids)
    finally:
        for cid in ids:
            await _delete("customers", cid)


async def test_idempotency_key_dedupes():
    key = str(uuid.uuid4())
    email = f"{_uniq('idem')}@example.com"
    a = await _ok({"operation": "custom_request", "http_method": "POST", "path": "/customers", "params": {"email": email}, "idempotency_key": key})
    b = await _ok({"operation": "custom_request", "http_method": "POST", "path": "/customers", "params": {"email": email}, "idempotency_key": key})
    try:
        assert a["id"] == b["id"]  # same key → Stripe replays the original object
    finally:
        await _delete("customers", a["id"])


async def test_expand_returns_nested_object():
    customer = await _ok({"operation": "create_customer", "email": f"{_uniq('exp')}@example.com"})
    cid = customer["id"]
    try:
        pi = await _ok({
            "operation": "create_payment_intent", "amount": 1000, "currency": "usd", "customer": cid,
            "payment_method": "pm_card_visa", "confirm": True,
            "extra_params": {"off_session": True, "payment_method_types": ["card"]},
        })
        expanded = await _ok({
            "operation": "retrieve_payment_intent", "payment_intent_id": pi["id"],
            "extra_params": {"expand": ["customer"]},
        })
        assert isinstance(expanded["customer"], dict)  # expanded, not just an id string
        assert expanded["customer"]["id"] == cid
    finally:
        await _delete("customers", cid)


async def test_metadata_and_nested_params_roundtrip():
    customer = await _ok({
        "operation": "create_customer", "email": f"{_uniq('meta')}@example.com",
        "metadata": {"order_id": "6735", "tier": "pro"},
        "extra_params": {"shipping": {"name": "Jane", "address": {"line1": "1 St", "city": "NYC", "country": "US", "postal_code": "10001"}}},
    })
    cid = customer["id"]
    try:
        assert customer["metadata"] == {"order_id": "6735", "tier": "pro"}
        assert customer["shipping"]["address"]["city"] == "NYC"
    finally:
        await _delete("customers", cid)


async def test_invalid_id_returns_error():
    r = await _run({"operation": "retrieve_customer", "customer_id": "cus_does_not_exist_123"})
    assert r["status"] == "error"
    assert r["status_code"] in (400, 404)
    assert "timing_ms" in r


async def test_missing_required_field_raises():
    node = _node({"operation": "retrieve_customer", "customer_id": "cus_x"})
    node.config.config.customer_id = ""
    with pytest.raises(ValueError):
        await node.execute({})


async def test_search_customers():
    email = f"{_uniq('srch')}@example.com"
    customer = await _ok({"operation": "create_customer", "email": email})
    cid = customer["id"]
    try:
        # Search is eventually consistent; just assert the call succeeds and shape is right.
        r = await _ok({"operation": "search_customers", "query": f"email:'{email}'"})
        assert r["object"] == "search_result"
    finally:
        await _delete("customers", cid)


async def test_custom_request_reaches_arbitrary_endpoint():
    r = await _ok({"operation": "custom_request", "http_method": "GET", "path": "/payment_methods", "params": {"type": "card", "limit": 1}})
    assert r["object"] == "list"


async def test_dynamic_options_loader():
    customer = await _ok({"operation": "create_customer", "email": f"{_uniq('dyn')}@example.com"})
    cid = customer["id"]
    try:
        result = await StripeNode.load_field_options("customer", {"api_key": API_KEY})
        assert "options" in result
        assert any(o["value"] == cid for o in result["options"])
        assert all("label" in o and "value" in o for o in result["options"])
    finally:
        await _delete("customers", cid)


async def test_timing_info_present():
    data = await _run({"operation": "list_products", "limit": 1})
    assert data["status"] == "success"
    assert data["timing_ms"]["api_request"] > 0
    assert data["timing_ms"]["total"] > 0
