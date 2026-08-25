"""
End-to-end test of the Stripe trigger's webhook-delivery path.

Drives the REAL webhook handler (`utils.webhook_routes.handle_webhook_payload`)
with a real Stripe-signed event, exercising the actual integration:
  node lookup by webhook_id → Stripe `verify_webhook_signature` (reads the
  `Stripe-Signature` header) → `filter_trigger_payload` → `_triggerPayload`
  injection → workflow-execution dispatch.

Also pins the row-driven registration lifecycle: the ``webhooks`` row is the
system of record (``registered_operation``/``registered_credential_id`` drive
the already_registered guard; ``deregister_node_webhooks`` /
``register_node_webhooks`` are the lifecycle choke points).

Only the DB layer and the final, generic workflow execution are stubbed —
everything Stripe-specific runs for real. No network or DB required.

Run: pytest nodes/tests/test_stripe_trigger_e2e.py
"""

import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from nodes.tests.conftest import TEST_WEBHOOK_URL, find_sql_calls, make_pool, webhook_row_state
from utils import webhook_routes

WEBHOOK_ID = str(uuid.uuid4())
SIGNING_SECRET = "whsec_e2e_test_secret"


def _stripe_event(event_type="payment_intent.succeeded"):
    return json.dumps({
        "id": "evt_e2e_1",
        "object": "event",
        "type": event_type,
        "data": {"object": {"id": "pi_e2e_1", "amount": 2000, "currency": "usd"}},
    })


def _signed_headers(body: str, secret: str = SIGNING_SECRET, ts: int = None):
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body.encode(), hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


def _workflow_config(event_types="payment_intent.succeeded, invoice.paid"):
    return {
        "nodes": [
            {
                "id": "stripe-trigger",
                "type": "automation-stripe",
                "config": {
                    "operation": "on_event",
                    "webhook_id": WEBHOOK_ID,
                    "signing_secret": SIGNING_SECRET,
                    "event_types": event_types,
                },
            },
            {"id": "downstream", "type": "automation-log", "config": {}},
        ],
        "edges": [{"source": "stripe-trigger", "target": "downstream"}],
    }


@pytest.fixture
def harness(deliver_webhook):
    """Stub the DB lookup + the generic execution + stats; everything Stripe runs for real."""
    config = {
        "is_active": True,
        "user_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "node_id": "stripe-trigger",
        "secret": None,  # Stripe's secret lives on the node, not the webhook record
        "workflow_config": _workflow_config(),
    }
    return config, deliver_webhook(config)


async def test_valid_stripe_event_fires_workflow(harness):
    """Real Stripe-signed event for an allowed type → workflow execution dispatched
    with the event injected as the trigger node's _triggerPayload."""
    _config, exec_mock = harness
    body = _stripe_event("payment_intent.succeeded")

    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _signed_headers(body), {}, method="POST"
    )

    assert result is True
    exec_mock.assert_awaited_once()
    kwargs = exec_mock.await_args.kwargs
    assert kwargs["start_node_id"] == "stripe-trigger"
    # The Stripe event was injected onto the trigger node for the workflow run.
    trigger = next(n for n in kwargs["nodes"] if n["id"] == "stripe-trigger")
    injected = trigger["config"]["_triggerPayload"]
    assert injected["type"] == "payment_intent.succeeded"
    assert injected["data"]["object"]["id"] == "pi_e2e_1"


async def test_tampered_signature_is_rejected(harness):
    """A tampered body (signature no longer valid) → 401, workflow NOT executed."""
    _config, exec_mock = harness
    body = _stripe_event("payment_intent.succeeded")
    headers = _signed_headers(body)
    tampered_body = body.replace("2000", "999999")  # body changed after signing

    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, tampered_body, headers, {}, method="POST", return_response=True
    )

    assert result.get("status") == 401
    exec_mock.assert_not_awaited()


async def test_wrong_secret_is_rejected(harness):
    """A signature made with the wrong secret → 401, workflow NOT executed."""
    _config, exec_mock = harness
    body = _stripe_event("payment_intent.succeeded")
    bad_headers = _signed_headers(body, secret="whsec_attacker")

    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, bad_headers, {}, method="POST", return_response=True
    )

    assert result.get("status") == 401
    exec_mock.assert_not_awaited()


async def test_unsubscribed_event_type_is_filtered(harness):
    """A correctly-signed event whose type isn't in the allowlist → not executed."""
    config, exec_mock = harness
    config["workflow_config"] = _workflow_config(event_types="payment_intent.succeeded")

    body = _stripe_event("charge.refunded")  # signed correctly, but not subscribed
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _signed_headers(body), {}, method="POST"
    )

    assert result is True  # acked
    exec_mock.assert_not_awaited()  # but no workflow run


def _decomposed_config(operation):
    cfg = _workflow_config()
    cfg["nodes"][0]["config"] = {
        "operation": operation, "webhook_id": WEBHOOK_ID, "signing_secret": SIGNING_SECRET,
    }
    return cfg


async def test_decomposed_trigger_fires_only_for_its_event(harness):
    """A per-event trigger op (on_invoice_paid) fires for invoice.paid but ignores others."""
    config, exec_mock = harness
    config["workflow_config"] = _decomposed_config("on_invoice_paid")

    # matching event → fires
    body = json.dumps({"id": "evt_2", "type": "invoice.paid", "data": {"object": {"id": "in_1"}}})
    assert await webhook_routes.handle_webhook_payload(WEBHOOK_ID, body, _signed_headers(body), {}, method="POST") is True
    exec_mock.assert_awaited_once()

    # different event (correctly signed) → filtered out
    exec_mock.reset_mock()
    body2 = json.dumps({"id": "evt_3", "type": "charge.succeeded", "data": {"object": {"id": "ch_1"}}})
    assert await webhook_routes.handle_webhook_payload(WEBHOOK_ID, body2, _signed_headers(body2), {}, method="POST") is True
    exec_mock.assert_not_awaited()


async def test_empty_allowlist_fires_for_any_event(harness):
    """Empty event_types → fire for any signed event."""
    config, exec_mock = harness
    config["workflow_config"] = _workflow_config(event_types="")

    body = _stripe_event("customer.subscription.updated")
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _signed_headers(body), {}, method="POST"
    )

    assert result is True
    exec_mock.assert_awaited_once()


async def test_signing_secret_fallback_from_webhooks_table(deliver_webhook):
    """Race-condition fallback: signing_secret absent from node config but present
    in webhooks.secret → event still verifies and workflow fires.

    This covers the window between load_field_value returning signing_secret to the
    frontend and the 2-second autosave landing in workflows.workflow."""
    config = {
        "is_active": True,
        "user_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "node_id": "stripe-trigger",
        # signing_secret stored in webhooks table (atomically by load_field_value)
        "secret": SIGNING_SECRET,
        "workflow_config": {
            "nodes": [
                {
                    "id": "stripe-trigger",
                    "type": "automation-stripe",
                    "config": {
                        "operation": "on_event",
                        "webhook_id": WEBHOOK_ID,
                        # signing_secret intentionally absent — autosave hasn't fired yet
                        "event_types": "payment_intent.succeeded",
                    },
                },
                {"id": "downstream", "type": "automation-log", "config": {}},
            ],
            "edges": [{"source": "stripe-trigger", "target": "downstream"}],
        },
    }
    exec_mock = deliver_webhook(config)

    body = _stripe_event("payment_intent.succeeded")
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _signed_headers(body), {}, method="POST"
    )

    assert result is True, "Should succeed via webhooks.secret fallback"
    exec_mock.assert_awaited_once()


async def test_no_signing_secret_anywhere_rejects(deliver_webhook):
    """No signing_secret in node config AND no webhooks.secret → 401."""
    config = {
        "is_active": True,
        "user_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "node_id": "stripe-trigger",
        "secret": None,  # nothing in webhooks table either
        "workflow_config": {
            "nodes": [
                {
                    "id": "stripe-trigger",
                    "type": "automation-stripe",
                    "config": {
                        "operation": "on_event",
                        "webhook_id": WEBHOOK_ID,
                        # no signing_secret anywhere
                        "event_types": "",
                    },
                },
            ],
            "edges": [],
        },
    }
    exec_mock = deliver_webhook(config)

    body = _stripe_event("payment_intent.succeeded")
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _signed_headers(body), {}, method="POST", return_response=True
    )

    assert result.get("status") == 401
    exec_mock.assert_not_awaited()


# ─── load_field_value: row-driven registration guard ─────────────────────────


async def test_operation_change_triggers_reregistration():
    """Switching from one Stripe trigger operation to another must NOT be
    blocked by the already_registered guard. The guard is ROW-driven: the
    row's ``registered_operation`` records the OLD op, so a different current
    operation forces a fresh `_register_external_webhook` call (dropping the
    stale endpoint first) and the row UPDATE records the NEW registration."""
    from nodes.stripe_node import StripeNode

    cred_id = str(uuid.uuid4())
    # register_stripe_webhook returns (endpoint_id, signing_secret)
    register_mock = AsyncMock(return_value=("we_new", "whsec_new"))
    stale_drop_mock = AsyncMock()
    pool, conn = make_pool()

    ctx = {
        "operation": "on_invoice_paid",
        "trigger_registered": True,
        "signing_secret": "whsec_old",
        "external_webhook_id": "we_old",
        "webhook_url": TEST_WEBHOOK_URL,
    }
    row = webhook_row_state(
        is_active=True,
        secret_set=True,
        external_webhook_id="we_old",
        registered_operation="on_payment_intent_succeeded",  # row recorded the OLD op
        registered_credential_id=cred_id,
    )

    with patch("nodes.stripe_node.register_stripe_webhook", register_mock), \
         patch("nodes.stripe_node.unregister_stripe_webhook", stale_drop_mock), \
         patch.object(StripeNode, "_resolve_trigger_credential", AsyncMock(return_value={"api_key": "sk_test_x"})), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook", AsyncMock(return_value=row)):
        result = await StripeNode.load_field_value(
            field_name="webhook_url",
            user_id=str(uuid.uuid4()),
            workflow_id=uuid.uuid4(),
            node_id="stripe-1",
            pool=pool,
            context=ctx,
            credential_ids={"stripe_api_key": cred_id},
        )

    vals = result["values"]
    assert vals["trigger_registered"] is True
    assert vals["signing_secret"] == "whsec_new", "Should have re-registered with new secret"
    assert vals["external_webhook_id"] == "we_new"
    register_mock.assert_awaited_once()
    # The old operation's stale endpoint is dropped before creating the new one.
    assert "we_old" in str(stale_drop_mock.await_args)
    # The webhooks row (system of record) now carries the NEW registration.
    persists = find_sql_calls(conn, "is_active = true")
    assert len(persists) == 1
    _, secret, ext_id, reg_op, reg_cred, _fp, _ = persists[0].args
    assert (secret, ext_id, reg_op, reg_cred) == ("whsec_new", "we_new", "on_invoice_paid", cred_id)


async def test_credential_change_triggers_reregistration():
    """Changing the credential must invalidate the row-driven guard
    (row.registered_credential_id != the picked credential id) and force
    re-registration so the new API key owns the Stripe webhook endpoint."""
    from nodes.stripe_node import StripeNode

    new_cred_id = str(uuid.uuid4())
    register_mock = AsyncMock(return_value=("we_new_cred", "whsec_new_cred"))
    pool, conn = make_pool()

    ctx = {
        "operation": "on_payment_intent_succeeded",
        "trigger_registered": True,
        "signing_secret": "whsec_old",
        "external_webhook_id": "we_old",
        "webhook_url": TEST_WEBHOOK_URL,
    }
    row = webhook_row_state(
        is_active=True,
        secret_set=True,
        external_webhook_id="we_old",
        registered_operation="on_payment_intent_succeeded",  # same op...
        registered_credential_id=str(uuid.uuid4()),          # ...but OLD credential
    )

    with patch("nodes.stripe_node.register_stripe_webhook", register_mock), \
         patch("nodes.stripe_node.unregister_stripe_webhook", AsyncMock()), \
         patch.object(StripeNode, "_resolve_trigger_credential", AsyncMock(return_value={"api_key": "sk_test_new"})), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook", AsyncMock(return_value=row)):
        result = await StripeNode.load_field_value(
            field_name="webhook_url",
            user_id=str(uuid.uuid4()),
            workflow_id=uuid.uuid4(),
            node_id="stripe-1",
            pool=pool,
            context=ctx,
            credential_ids={"stripe_api_key": new_cred_id},
        )

    vals = result["values"]
    assert vals["trigger_registered"] is True
    assert vals["signing_secret"] == "whsec_new_cred"
    register_mock.assert_awaited_once()
    # The row records the NEW credential as the registration owner.
    persists = find_sql_calls(conn, "is_active = true")
    assert len(persists) == 1
    _, secret, ext_id, reg_op, reg_cred, _fp, _ = persists[0].args
    assert (secret, ext_id, reg_cred) == ("whsec_new_cred", "we_new_cred", new_cred_id)
    assert reg_op == "on_payment_intent_succeeded"


async def test_persist_failure_surfaces_as_trigger_error():
    """Provider registration succeeded but the row UPDATE hit 0 rows: the row
    is the system of record, so this is a REAL failure — trigger_registered
    False + trigger_error (never a silent warning) — with the provider ids
    still merged into values so the retry's stale-endpoint drop can find (and
    replace) the endpoint instead of orphaning it."""
    from nodes.stripe_node import StripeNode

    pool, _conn = make_pool(execute="UPDATE 0")  # persist_registration_state hits 0 rows
    ctx = {"operation": "on_invoice_paid", "webhook_url": TEST_WEBHOOK_URL}

    with patch("nodes.stripe_node.register_stripe_webhook",
               AsyncMock(return_value=("we_new", "whsec_new"))), \
         patch.object(StripeNode, "_resolve_trigger_credential",
                      AsyncMock(return_value={"api_key": "sk_test_x"})), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook",
               AsyncMock(return_value=webhook_row_state())):
        result = await StripeNode.load_field_value(
            field_name="webhook_url",
            user_id=str(uuid.uuid4()),
            workflow_id=uuid.uuid4(),
            node_id="stripe-1",
            pool=pool,
            context=ctx,
            credential_ids={"stripe_api_key": str(uuid.uuid4())},
        )

    vals = result["values"]
    assert vals["trigger_registered"] is False
    assert "vanished" in vals["trigger_error"]
    # Provider ids still surface so the retry can drop the stale endpoint.
    assert vals["external_webhook_id"] == "we_new"
    assert vals["signing_secret"] == "whsec_new"


# ─── deregister_node_webhooks: THE deregistration choke point ────────────────


async def test_webhook_cleanup_on_node_delete():
    """Deleting a registered node → `deregister_node_webhooks` calls
    _unregister_external_webhook with the stored endpoint id (removing it from
    the Stripe dashboard) and DEACTIVATES the row — clearing secret/external
    id on confirmed teardown, stamping the re-register marker, never deleting
    the row (the URL/UUID must survive an undo)."""
    wf_id = str(uuid.uuid4())
    node_id = "stripe-trigger"
    external_id = "we_existing"
    cred_id = str(uuid.uuid4())

    workflow_json = {
        "nodes": [
            {
                "id": node_id,
                "type": "automation-stripe",
                "config": {
                    "operation": "on_payment_intent_succeeded",
                    "external_webhook_id": external_id,
                    "credentialIds": {"stripe_api_key": cred_id},
                },
            }
        ],
        "edges": [],
    }
    pool, conn = make_pool(
        fetchrow={"owner_id": uuid.uuid4(), "workflow": workflow_json},
        fetch=[{"node_id": node_id, "external_webhook_id": external_id,
                "registered_operation": "on_payment_intent_succeeded", "registered_credential_id": None}],
    )
    unregister_mock = AsyncMock()

    with patch("nodes.stripe_node.unregister_stripe_webhook", unregister_mock), \
         patch("utils.credential_loader.load_credential", AsyncMock(return_value={"api_key": "sk_test_x"})):
        from utils.webhook_manager import WebhookManager
        result = await WebhookManager.deregister_node_webhooks(pool, wf_id, [node_id])

    assert result == {"deregistered": 1, "failed": 0}
    # unregister_stripe_webhook called with the stored endpoint id
    unregister_mock.assert_awaited_once()
    assert unregister_mock.await_args.args[1] == external_id
    # Row: deactivated with registration cleared (teardown confirmed) and the
    # marker stamped so restore knows to re-register — never hard-deleted.
    deacts = find_sql_calls(conn, "is_active = false")
    assert len(deacts) == 1
    sql = deacts[0].args[0]
    assert "secret = NULL" in sql and "external_webhook_id = NULL" in sql
    assert deacts[0].args[3] == "on_payment_intent_succeeded"  # mark_operation
    assert not find_sql_calls(conn, "DELETE FROM webhooks")


async def test_webhook_cleanup_on_workflow_delete():
    """Permanent workflow delete (`manage_rows=False`) tears down every
    registered node's provider endpoint — teardown only, no row updates (the
    caller hard-deletes the rows wholesale right after)."""
    wf_id = str(uuid.uuid4())
    cred_id = str(uuid.uuid4())

    workflow_json = {
        "nodes": [
            {
                "id": "stripe-1",
                "type": "automation-stripe",
                "config": {
                    "operation": "on_invoice_paid",
                    "external_webhook_id": "we_invoice",
                    "credentialIds": {"stripe_api_key": cred_id},
                },
            },
            {
                "id": "log-1",
                "type": "automation-log",  # not in NODE_REGISTRY → skipped
                "config": {},
            },
        ],
        "edges": [],
    }
    pool, conn = make_pool(
        fetchrow={"owner_id": uuid.uuid4(), "workflow": workflow_json},
        fetch=[{"node_id": "stripe-1", "external_webhook_id": "we_invoice",
                "registered_operation": "on_invoice_paid", "registered_credential_id": None}],
    )
    unregister_mock = AsyncMock()

    with patch("nodes.stripe_node.unregister_stripe_webhook", unregister_mock), \
         patch("utils.credential_loader.load_credential", AsyncMock(return_value={"api_key": "sk_test_x"})):
        from utils.webhook_manager import WebhookManager
        result = await WebhookManager.deregister_node_webhooks(pool, wf_id, manage_rows=False)

    # Only the Stripe trigger node is a registered node class — torn down once.
    assert result == {"deregistered": 1, "failed": 0}
    unregister_mock.assert_awaited_once()
    assert unregister_mock.await_args.args[1] == "we_invoice"
    # manage_rows=False: teardown only, rows untouched.
    assert not find_sql_calls(conn, "is_active = false")


async def test_webhook_cleanup_skips_nodes_without_external_id():
    """A node that was NEVER registered (no row marker, no config external id,
    no trigger_registered) still gets cleanup_external_webhook dispatched —
    the choke point dispatches for every registered node class — but Stripe's
    hook no-ops internally (no endpoint id), so no provider API call is made
    and the node counts as successfully deregistered."""
    from nodes.stripe_node import StripeNode

    wf_id = str(uuid.uuid4())
    workflow_json = {
        "nodes": [
            {
                "id": "stripe-1",
                "type": "automation-stripe",
                # never registered: no external_webhook_id, no credential
                "config": {"operation": "on_payment_intent_succeeded"},
            },
        ],
        "edges": [],
    }
    pool, conn = make_pool(
        fetchrow={"owner_id": uuid.uuid4(), "workflow": workflow_json},
        fetch=[],  # no webhooks row either
    )

    unregister_mock = AsyncMock()
    cleanup_spy = AsyncMock(side_effect=StripeNode.cleanup_external_webhook)

    with patch("nodes.stripe_node.unregister_stripe_webhook", unregister_mock), \
         patch.object(StripeNode, "cleanup_external_webhook", cleanup_spy):
        from utils.webhook_manager import WebhookManager
        result = await WebhookManager.deregister_node_webhooks(pool, wf_id)

    # The hook IS dispatched (once, with no credential)...
    cleanup_spy.assert_awaited_once()
    assert cleanup_spy.await_args.args[4] is None
    # ...but no provider API call is made, and nothing counts as failed.
    unregister_mock.assert_not_awaited()
    assert result == {"deregistered": 1, "failed": 0}
    # No row existed, so nothing to deactivate.
    assert not find_sql_calls(conn, "is_active = false")


async def test_registered_node_without_credential_counts_failed():
    """Silent no-op is failure: a REGISTERED Stripe node (row carries
    external_webhook_id + registered_operation) whose credential no longer
    resolves cannot tear down — the provider hook would silently no-op. It
    must count as failed WITHOUT calling the hook, and the row is deactivated
    WITHOUT clearing external_webhook_id (preserving the record of the
    possibly-live provider endpoint for a later re-register to drop)."""
    from nodes.stripe_node import StripeNode

    wf_id = str(uuid.uuid4())
    node_id = "stripe-trigger"
    workflow_json = {
        "nodes": [
            {
                "id": node_id,
                "type": "automation-stripe",
                "config": {
                    "operation": "on_event",
                    "credentialIds": {"stripe_api_key": str(uuid.uuid4())},
                },
            },
        ],
        "edges": [],
    }
    pool, conn = make_pool(
        fetchrow={"owner_id": uuid.uuid4(), "workflow": workflow_json},
        fetch=[{"node_id": node_id, "external_webhook_id": "we_live",
                "registered_operation": "on_event", "registered_credential_id": None}],
    )
    cleanup_spy = AsyncMock()

    with patch.object(StripeNode, "cleanup_external_webhook", cleanup_spy), \
         patch("utils.credential_loader.load_credential", AsyncMock(return_value=None)):
        from utils.webhook_manager import WebhookManager
        result = await WebhookManager.deregister_node_webhooks(pool, wf_id, [node_id])

    assert result == {"deregistered": 0, "failed": 1}
    cleanup_spy.assert_not_awaited()  # a credential-less teardown would silently no-op
    deacts = find_sql_calls(conn, "is_active = false")
    assert len(deacts) == 1
    sql = deacts[0].args[0]
    assert "external_webhook_id = NULL" not in sql and "secret = NULL" not in sql
    assert deacts[0].args[3] == "on_event"  # marker stamped for restore


async def test_resource_manager_calls_external_unregister_on_node_delete():
    """cleanup_nodes_resources (canvas delete path) must route through the
    `deregister_node_webhooks` choke point with the pre-delete node dicts
    (``old_nodes`` → ``node_overrides`` — the canvas save already removed them
    from the live blob) and the requesting user (collaborator credentials).
    The webhooks rows are preserved (deactivated inside the choke point), so
    an undo reuses the same webhook URL — never hard-deleted here."""
    wf_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    node_id = "stripe-trigger"
    old_node = {"id": node_id, "type": "automation-stripe",
                "config": {"operation": "on_event", "external_webhook_id": "we_x"}}

    dereg_mock = AsyncMock(return_value={"deregistered": 1, "failed": 0})
    pool, conn = make_pool()

    with patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", dereg_mock), \
         patch("utils.cron_scheduler_client.delete_schedules_for_nodes", AsyncMock(return_value={})), \
         patch("utils.workflow_resource_manager._cleanup_filesystem_volumes", AsyncMock(return_value=None)):
        from utils.workflow_resource_manager import cleanup_nodes_resources
        results = await cleanup_nodes_resources(
            pool, wf_id, [node_id], old_nodes=[old_node], requesting_user_id=user_id
        )

    dereg_mock.assert_awaited_once_with(
        pool, wf_id, [node_id], node_overrides=[old_node], requesting_user_id=user_id
    )
    assert results["webhooks"] == {"deregistered": 1, "failed": 0, "preserved": True}
    # Nothing on the node-delete path hard-deletes webhooks rows.
    assert not find_sql_calls(conn, "DELETE FROM webhooks")


# ─── handle_credential_change: the swap race ─────────────────────────────────


async def test_credential_swap_after_panel_reregister_preserves_new_registration():
    """Swap-race regression: the config panel already re-registered under the
    NEW credential (row endpoint id moved past old_config's) by the time the
    debounced save's handle_credential_change runs. The reconcile is a
    fingerprint no-op — the fresh registration is left alone — but the OLD
    credential's provider endpoint must STILL be dropped (providers without
    replace-stale/sweep idempotency would otherwise leak it)."""
    wf_id = str(uuid.uuid4())
    node_id = "stripe-trigger"
    user_id = str(uuid.uuid4())
    old_cid, new_cid = str(uuid.uuid4()), str(uuid.uuid4())

    old_config = {
        "operation": "on_event",
        "external_webhook_id": "we_old",
        "credentialIds": {"stripe_api_key": old_cid},
    }
    new_config = {"operation": "on_event", "credentialIds": {"stripe_api_key": new_cid}}

    # The row moved on: the panel's re-register minted we_new.
    pool, conn = make_pool(fetchrow={"external_webhook_id": "we_new"})
    unregister_mock = AsyncMock()

    with patch("nodes.stripe_node.unregister_stripe_webhook", unregister_mock), \
         patch("utils.credentials.get_credential", AsyncMock(return_value={"api_key": "sk_old"})), \
         patch("utils.webhook_manager.WebhookManager.reconcile_node",
               AsyncMock(return_value={"state": "live"})) as mock_rec:
        from utils.webhook_manager import WebhookManager
        cleanups = await WebhookManager.handle_credential_change(
            pool,
            node_type="automation-stripe",
            workflow_id=wf_id,
            node_id=node_id,
            old_config=old_config,
            new_config=new_config,
            user_id=user_id,
        )

    assert cleanups == 1
    # OLD endpoint torn down with the OLD credential.
    unregister_mock.assert_awaited_once()
    assert unregister_mock.await_args.args[0] == "sk_old"
    assert unregister_mock.await_args.args[1] == "we_old"
    # The fresh registration is untouched: the reconcile no-opped and no row
    # deactivation ran.
    mock_rec.assert_awaited_once()
    assert not find_sql_calls(conn, "is_active = false")

async def test_restore_skips_action_nodes():
    """`register_node_webhooks` must never register an operation that doesn't
    require a webhook: a restored Stripe create_customer node grows no
    endpoint — neither via a marker-less inactive row (never registered) nor
    via a stale marker left from a former trigger operation."""
    from nodes.stripe_node import StripeNode

    wf_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    workflow_json = {
        "nodes": [
            {
                "id": "stripe-1",
                "type": "automation-stripe",
                "config": {
                    "operation": "create_customer",  # action, not a trigger
                    "credentialIds": {"stripe_api_key": str(uuid.uuid4())},
                },
            },
        ],
        "edges": [],
    }
    register_mock = AsyncMock()

    for row in (
        {"node_id": "stripe-1", "id": uuid.uuid4(), "is_active": False,
         "registered_operation": None, "registered_credential_id": None},        # never registered
        {"node_id": "stripe-1", "id": uuid.uuid4(), "is_active": False,
         "registered_operation": "on_event", "registered_credential_id": None},  # marker, but op is now an action
    ):
        pool, conn = make_pool(
            fetchrow={"owner_id": uuid.uuid4(), "workflow": workflow_json},
            fetch=[row],
        )
        with patch.object(StripeNode, "_register_external_webhook", register_mock), \
             patch.object(StripeNode, "_resolve_trigger_credential",
                          AsyncMock(return_value={"api_key": "sk_test_x"})):
            from utils.webhook_manager import WebhookManager
            count = await WebhookManager.register_node_webhooks(pool, wf_id, user_id)

        assert count == 0
        register_mock.assert_not_awaited()
        assert not find_sql_calls(conn, "is_active = true")  # no row activation
