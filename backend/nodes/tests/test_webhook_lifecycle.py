"""
Tests for the webhook lifecycle choke points (utils.webhook_manager).

The webhooks ROW is the system of record for trigger registration state:

- ``deregister_node_webhooks`` — provider teardown + row DEACTIVATION (never
  deletion): trash, node delete, and (with manage_rows=False) the permanent-
  delete teardown. On success the row's secret/external_webhook_id are NULLed;
  on failure they're preserved as the record of a possibly-live endpoint. The
  ``registered_operation`` marker survives (or is stamped for legacy rows).
- ``register_node_webhooks`` — restore/undo re-registration: acts ONLY on
  inactive rows carrying the marker whose current operation still requires a
  webhook; activates the row via ``persist_registration_state`` and patches
  the node config blob via the atomic CTE.
- ``get_or_create_webhook`` — auto-activates only simple (marker-less) rows.

Provider API calls and DB interactions are mocked; these tests verify the
plumbing — correct methods called in correct order with correct args/SQL.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.webhook_manager import WebhookManager

WORKFLOW_ID = str(uuid.uuid4())
NODE_ID = "stripe-trigger-1"
WEBHOOK_ID = str(uuid.uuid4())
WEBHOOK_URL = f"https://{WEBHOOK_ID}.hooks.example.test"
SIGNING_SECRET = "whsec_test_secret"
ENDPOINT_ID = "we_test_endpoint"
OWNER_ID = str(uuid.uuid4())
CREDENTIAL_ID = str(uuid.uuid4())
OPERATION = "on_payment_intent_succeeded"

STRIPE_NODE_CONFIG = {
    "operation": OPERATION,
    "webhook_id": WEBHOOK_ID,
    "webhook_url": WEBHOOK_URL,
    "external_webhook_id": ENDPOINT_ID,
    "signing_secret": SIGNING_SECRET,
    "trigger_registered": True,
    "credentialIds": {"stripe_api_key": CREDENTIAL_ID},
}

STRIPE_CREDENTIAL = {"credential_type": "stripe_api_key", "api_key": "sk_test_xxx"}


def _node(config=None):
    return {
        "id": NODE_ID,
        "type": "automation-stripe",
        "config": dict(STRIPE_NODE_CONFIG if config is None else config),
    }


def _wf_row(nodes):
    return {"owner_id": uuid.UUID(OWNER_ID), "workflow": {"nodes": nodes}}


def _pool(fetchrow=None, fetch=None, execute="UPDATE 1"):
    """Minimal fake asyncpg pool; rows are plain dicts (support [] and dict())."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetch = AsyncMock(return_value=fetch if fetch is not None else [])
    conn.execute = AsyncMock(return_value=execute)
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool, conn


def _fake_stripe_node(register=None, unregister=None):
    from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

    class FakeStripeNode(ExternalWebhookTriggerMixin):
        pass

    FakeStripeNode._register_external_webhook = register or AsyncMock()
    FakeStripeNode._unregister_external_webhook = unregister or AsyncMock()
    return FakeStripeNode


def _deactivations(conn):
    return [c for c in conn.execute.await_args_list if "is_active = false" in c.args[0]]


# ─── trash (soft delete): rows deregistered but preserved ─────────────────────

@pytest.mark.asyncio
async def test_soft_delete_preserves_webhook_db_record():
    """cleanup_workflow_operational_resources routes through the deregistration
    choke point (rows deactivated + preserved) and never hard-deletes rows."""
    pool, _ = _pool()
    dereg = AsyncMock(return_value={"deregistered": 2, "failed": 0})
    delete_wf = AsyncMock(return_value=2)

    with (
        patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", dereg),
        patch("utils.webhook_manager.WebhookManager.delete_webhooks_for_workflow", delete_wf),
        patch("utils.cron_scheduler_client.delete_schedules_for_workflow",
              AsyncMock(return_value={"deleted": 0})),
    ):
        from utils.workflow_resource_manager import cleanup_workflow_operational_resources
        results = await cleanup_workflow_operational_resources(pool=pool, workflow_id=WORKFLOW_ID)

    dereg.assert_awaited_once_with(pool, WORKFLOW_ID, on_trash=True)
    # Default manage_rows=True: the choke point deactivates (preserves) rows.
    assert "manage_rows" not in dereg.await_args.kwargs
    delete_wf.assert_not_awaited()
    assert results["webhooks"] == {"deregistered": 2, "failed": 0, "preserved": True}


@pytest.mark.asyncio
async def test_trash_preserves_inbound_email_reservation():
    """on_trash=True skips classes with preserve_registration_on_trash — the
    inbound-email address reservation must survive trash → restore (someone
    else could claim the address while trashed). Plain node deletion still
    releases it."""
    from nodes.inbound_email_trigger_node import InboundEmailTriggerNode

    assert InboundEmailTriggerNode.preserve_registration_on_trash is True
    email_node = {
        "id": "email-1", "type": "trigger-email",
        "config": {"trigger_registered": True},
    }
    cleanup = AsyncMock()

    with patch.object(InboundEmailTriggerNode, "cleanup_external_webhook", cleanup):
        pool, _ = _pool(fetchrow=_wf_row([email_node]), fetch=[])
        res = await WebhookManager.deregister_node_webhooks(
            pool, WORKFLOW_ID, on_trash=True
        )
        cleanup.assert_not_awaited()
        assert res == {"deregistered": 0, "failed": 0}

        pool, _ = _pool(fetchrow=_wf_row([email_node]), fetch=[])
        res = await WebhookManager.deregister_node_webhooks(pool, WORKFLOW_ID)
        cleanup.assert_awaited_once()
        assert res["deregistered"] == 1


# ─── permanent delete: teardown (manage_rows=False) then hard delete ──────────

@pytest.mark.asyncio
async def test_permanent_delete_unregisters_then_deletes():
    """cleanup_workflow_resources must tear down provider-side registrations
    (manage_rows=False — no per-node deactivation UPDATEs) BEFORE
    delete_webhooks_for_workflow hard-deletes the rows."""
    pool, _ = _pool(execute="DELETE 0")
    call_order = []

    async def _dereg(*a, **kw):
        call_order.append(("deregister", kw.get("manage_rows")))
        return {"deregistered": 1, "failed": 0}

    async def _delete_wf(*a, **kw):
        call_order.append(("delete", None))
        return 1

    with (
        patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", _dereg),
        patch("utils.webhook_manager.WebhookManager.delete_webhooks_for_workflow", _delete_wf),
        patch("utils.cron_scheduler_client.delete_schedules_for_workflow",
              AsyncMock(return_value={"deleted": 0})),
        patch("utils.cas.gc.rollup_workflow_totals", AsyncMock()),
        patch("utils.workflow_resource_manager._cleanup_workflow_volumes", AsyncMock(return_value=0)),
    ):
        from utils.workflow_resource_manager import cleanup_workflow_resources
        await cleanup_workflow_resources(pool=pool, workflow_id=WORKFLOW_ID)

    assert ("deregister", False) in call_order, (
        "Teardown must run with manage_rows=False — rows are hard-deleted wholesale below"
    )
    names = [n for n, _ in call_order]
    assert names.index("deregister") < names.index("delete"), (
        "Provider must be deregistered before DB records are deleted"
    )


# ─── deregister: success clears registration, marker survives/is stamped ──────

@pytest.mark.asyncio
async def test_deregister_success_clears_row_and_stamps_marker():
    """Successful teardown deactivates the row, NULLs secret/external id, and
    stamps the registered_operation marker (COALESCE) for legacy rows."""
    pool, conn = _pool(
        fetchrow=_wf_row([_node()]),
        # Legacy row: registered provider-side (external id) but pre-marker.
        fetch=[{"node_id": NODE_ID, "external_webhook_id": ENDPOINT_ID,
                "registered_operation": None, "registered_credential_id": None}],
    )
    unregister = AsyncMock()
    node_cls = _fake_stripe_node(unregister=unregister)

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.credential_loader.load_credential", AsyncMock(return_value=STRIPE_CREDENTIAL)),
    ):
        results = await WebhookManager.deregister_node_webhooks(pool, WORKFLOW_ID)

    assert results == {"deregistered": 1, "failed": 0}
    unregister.assert_awaited_once()
    assert unregister.await_args.kwargs["credential"] == STRIPE_CREDENTIAL

    deactivations = _deactivations(conn)
    assert len(deactivations) == 1, "row must be deactivated exactly once"
    sql = deactivations[0].args[0]
    assert "secret = NULL" in sql and "external_webhook_id = NULL" in sql, (
        "confirmed teardown must clear the dead registration values"
    )
    assert "registered_operation = COALESCE(registered_operation, $3)" in sql
    assert deactivations[0].args[3] == OPERATION, (
        "legacy (pre-marker) registered rows must get the marker stamped for restore"
    )


@pytest.mark.asyncio
async def test_deregister_failure_keeps_registration_record():
    """A raising provider hook counts as failed; the row is deactivated WITHOUT
    clearing secret/external_webhook_id (possibly-live endpoint record)."""
    pool, conn = _pool(
        fetchrow=_wf_row([_node()]),
        fetch=[{"node_id": NODE_ID, "external_webhook_id": ENDPOINT_ID,
                "registered_operation": OPERATION, "registered_credential_id": None}],
    )
    unregister = AsyncMock(side_effect=Exception("stripe 500"))
    node_cls = _fake_stripe_node(unregister=unregister)

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.credential_loader.load_credential", AsyncMock(return_value=STRIPE_CREDENTIAL)),
    ):
        results = await WebhookManager.deregister_node_webhooks(pool, WORKFLOW_ID)

    assert results == {"deregistered": 0, "failed": 1}
    unregister.assert_awaited_once()

    deactivations = _deactivations(conn)
    assert len(deactivations) == 1
    sql = deactivations[0].args[0]
    assert "secret = NULL" not in sql and "external_webhook_id = NULL" not in sql, (
        "failed teardown must preserve the registration record on the row"
    )


@pytest.mark.asyncio
async def test_deregister_registered_node_without_credential_counts_failed():
    """A registered mixin node whose credential no longer resolves must count
    as FAILED without calling the provider hook (a silent no-op must not erase
    the endpoint record)."""
    pool, conn = _pool(
        fetchrow=_wf_row([_node()]),
        fetch=[{"node_id": NODE_ID, "external_webhook_id": ENDPOINT_ID,
                "registered_operation": OPERATION, "registered_credential_id": None}],
    )
    unregister = AsyncMock()
    node_cls = _fake_stripe_node(unregister=unregister)

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.credential_loader.load_credential", AsyncMock(return_value=None)),
    ):
        results = await WebhookManager.deregister_node_webhooks(pool, WORKFLOW_ID)

    assert results == {"deregistered": 0, "failed": 1}
    unregister.assert_not_awaited()
    deactivations = _deactivations(conn)
    assert len(deactivations) == 1
    assert "secret = NULL" not in deactivations[0].args[0]


@pytest.mark.asyncio
async def test_deregister_manage_rows_false_skips_row_updates():
    """manage_rows=False is teardown-only (permanent-delete path): no per-node
    deactivation UPDATEs are issued."""
    pool, conn = _pool(
        fetchrow=_wf_row([_node()]),
        fetch=[{"node_id": NODE_ID, "external_webhook_id": ENDPOINT_ID,
                "registered_operation": OPERATION, "registered_credential_id": None}],
    )
    unregister = AsyncMock()
    node_cls = _fake_stripe_node(unregister=unregister)

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.credential_loader.load_credential", AsyncMock(return_value=STRIPE_CREDENTIAL)),
    ):
        results = await WebhookManager.deregister_node_webhooks(
            pool, WORKFLOW_ID, manage_rows=False
        )

    assert results == {"deregistered": 1, "failed": 0}
    unregister.assert_awaited_once()
    conn.execute.assert_not_awaited()


# ─── register→trash race: row external_webhook_id beats the config blob ───────

@pytest.mark.asyncio
async def test_deregister_falls_back_to_row_external_id():
    """When the node config blob never got external_webhook_id autosaved (the
    register-then-trash race), deregistration must use the id persisted on the
    webhooks row, and then clear it."""
    # Blob config carries the credential but NOT external_webhook_id.
    config_no_ext = {
        "operation": OPERATION,
        "credentialIds": {"stripe_api_key": CREDENTIAL_ID},
    }
    pool, conn = _pool(
        fetchrow=_wf_row([_node(config_no_ext)]),
        # The webhooks row holds the provider id (persisted synchronously at register).
        fetch=[{"node_id": NODE_ID, "external_webhook_id": ENDPOINT_ID,
                "registered_operation": OPERATION, "registered_credential_id": None}],
    )
    unregister = AsyncMock()
    node_cls = _fake_stripe_node(unregister=unregister)

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.credential_loader.load_credential", AsyncMock(return_value=STRIPE_CREDENTIAL)),
    ):
        results = await WebhookManager.deregister_node_webhooks(pool, WORKFLOW_ID)

    assert results == {"deregistered": 1, "failed": 0}
    # Deregister used the row's external_webhook_id even though the blob lacked it.
    assert unregister.await_args.kwargs["config"]["external_webhook_id"] == ENDPOINT_ID
    # Deactivation clears the provider id (and secret) on the row.
    deactivations = _deactivations(conn)
    assert len(deactivations) == 1
    assert "external_webhook_id = NULL" in deactivations[0].args[0], (
        "deactivation must clear external_webhook_id on the row"
    )


# ─── register_node_webhooks: re-registers and patches node config ─────────────

@pytest.mark.asyncio
async def test_register_node_webhooks_re_registers_and_patches_config():
    """On restore, register_node_webhooks calls the node's
    _register_external_webhook, activates the row via persist_registration_state,
    and merges the fresh values into the node config blob via the atomic CTE."""
    pool, conn = _pool(
        fetchrow=_wf_row([_node()]),
        fetch=[{"node_id": NODE_ID, "id": uuid.UUID(WEBHOOK_ID),
                "is_active": False, "registered_operation": OPERATION}],
    )
    register = AsyncMock(return_value={
        "external_webhook_id": "we_new_endpoint",
        "signing_secret": "whsec_new_secret",
    })
    node_cls = _fake_stripe_node(register=register)
    node_cls._resolve_trigger_credential = AsyncMock(return_value=STRIPE_CREDENTIAL)
    get_or_create = AsyncMock(return_value={
        "webhook_id": WEBHOOK_ID, "webhook_url": WEBHOOK_URL,
        "relay_connected": True, "is_production": True,
        "is_active": False, "secret_set": False, "external_webhook_id": None,
        "registered_operation": OPERATION, "registered_credential_id": None,
    })

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
              MagicMock(return_value=True)),
        patch("utils.webhook_manager.WebhookManager.get_or_create_webhook", get_or_create),
    ):
        count = await WebhookManager.register_node_webhooks(pool, WORKFLOW_ID, OWNER_ID)

    assert count == 1
    node_cls._resolve_trigger_credential.assert_awaited_once_with(
        pool, OWNER_ID, {"stripe_api_key": CREDENTIAL_ID}
    )
    assert get_or_create.await_args.kwargs["background_relay"] is True
    register.assert_awaited_once_with(
        webhook_url=WEBHOOK_URL,
        credential=STRIPE_CREDENTIAL,
        config=_node()["config"],
        node_id=NODE_ID,
    )

    # Row activated with the fresh registration values (persist_registration_state).
    persists = [c for c in conn.execute.await_args_list if "is_active = true" in c.args[0]]
    assert len(persists) == 1, "persist_registration_state must activate the row"
    p = persists[0].args
    assert p[1] == "whsec_new_secret"
    assert p[2] == "we_new_endpoint"
    assert p[3] == OPERATION
    assert p[4] == CREDENTIAL_ID
    # p[5] = registered_fingerprint — computed from op + credential + declared
    # fields at register time; p[6] = the row id.
    assert isinstance(p[5], str) and len(p[5]) == 16
    assert p[6] == uuid.UUID(WEBHOOK_ID)

    # Node config patched atomically into the workflow blob via the CTE.
    patches = [c for c in conn.execute.await_args_list if "jsonb_set" in c.args[0]]
    assert len(patches) == 1, "Node config must be patched in workflow JSON via jsonb_set"
    assert patches[0].args[1] == uuid.UUID(WORKFLOW_ID)
    assert patches[0].args[2] == NODE_ID
    payload = json.loads(patches[0].args[3])
    assert payload["trigger_registered"] is True
    assert payload["trigger_error"] is None
    assert payload["webhook_id"] == WEBHOOK_ID
    assert payload["webhook_url"] == WEBHOOK_URL
    assert payload["external_webhook_id"] == "we_new_endpoint"
    assert payload["signing_secret"] == "whsec_new_secret"


@pytest.mark.asyncio
async def test_register_node_webhooks_skips_no_credential():
    """Nodes without a resolvable credential are skipped with the row left
    inactive (no activation UPDATE, no provider call)."""
    config_no_cred = {**STRIPE_NODE_CONFIG, "credentialIds": {}}
    pool, conn = _pool(
        fetchrow=_wf_row([_node(config_no_cred)]),
        fetch=[{"node_id": NODE_ID, "id": uuid.UUID(WEBHOOK_ID),
                "is_active": False, "registered_operation": OPERATION}],
    )
    register = AsyncMock()
    # Real mixin _resolve_trigger_credential: empty credentialIds → None.
    node_cls = _fake_stripe_node(register=register)
    get_or_create = AsyncMock()

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
              MagicMock(return_value=True)),
        patch("utils.webhook_manager.WebhookManager.get_or_create_webhook", get_or_create),
    ):
        count = await WebhookManager.register_node_webhooks(pool, WORKFLOW_ID, OWNER_ID)

    assert count == 0
    register.assert_not_awaited()
    get_or_create.assert_not_awaited()
    conn.execute.assert_not_awaited()  # row stays inactive


@pytest.mark.parametrize(
    "row,op_requires",
    [
        # Already live — nothing to restore.
        ({"node_id": NODE_ID, "id": uuid.UUID(WEBHOOK_ID),
          "is_active": True, "registered_operation": OPERATION}, True),
        # Never registered (no marker) — a restored action node must not grow an endpoint.
        ({"node_id": NODE_ID, "id": uuid.UUID(WEBHOOK_ID),
          "is_active": False, "registered_operation": None}, True),
        # Marker present but the CURRENT operation no longer requires a webhook.
        ({"node_id": NODE_ID, "id": uuid.UUID(WEBHOOK_ID),
          "is_active": False, "registered_operation": OPERATION}, False),
    ],
    ids=["active-row", "unmarked-row", "op-no-longer-webhook"],
)
@pytest.mark.asyncio
async def test_register_node_webhooks_only_inactive_marker_rows(row, op_requires):
    """register_node_webhooks acts ONLY on inactive rows carrying the
    registered_operation marker whose current op still requires a webhook."""
    pool, conn = _pool(fetchrow=_wf_row([_node()]), fetch=[row])
    register = AsyncMock()
    node_cls = _fake_stripe_node(register=register)
    node_cls._resolve_trigger_credential = AsyncMock(return_value=STRIPE_CREDENTIAL)
    get_or_create = AsyncMock()

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
              MagicMock(return_value=op_requires)),
        patch("utils.webhook_manager.WebhookManager.get_or_create_webhook", get_or_create),
    ):
        count = await WebhookManager.register_node_webhooks(pool, WORKFLOW_ID, OWNER_ID)

    assert count == 0
    register.assert_not_awaited()
    get_or_create.assert_not_awaited()
    conn.execute.assert_not_awaited()


# ─── UUID preserved: re-registration reuses the existing row ──────────────────

@pytest.mark.asyncio
async def test_restore_reuses_existing_webhook_uuid():
    """register_node_webhooks goes through get_or_create_webhook (which reuses
    the existing row UUID) and hands the provider the preserved URL."""
    pool, _ = _pool(
        fetchrow=_wf_row([_node()]),
        fetch=[{"node_id": NODE_ID, "id": uuid.UUID(WEBHOOK_ID),
                "is_active": False, "registered_operation": OPERATION}],
    )
    register = AsyncMock(return_value={
        "external_webhook_id": "we_restored",
        "signing_secret": "whsec_restored",
    })
    node_cls = _fake_stripe_node(register=register)
    node_cls._resolve_trigger_credential = AsyncMock(return_value=STRIPE_CREDENTIAL)
    get_or_create = AsyncMock(return_value={
        "webhook_id": WEBHOOK_ID,  # existing UUID preserved
        "webhook_url": WEBHOOK_URL,
        "relay_connected": True, "is_production": True,
        "is_active": False, "secret_set": False, "external_webhook_id": None,
        "registered_operation": OPERATION, "registered_credential_id": None,
    })

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
              MagicMock(return_value=True)),
        patch("utils.webhook_manager.WebhookManager.get_or_create_webhook", get_or_create),
    ):
        count = await WebhookManager.register_node_webhooks(pool, WORKFLOW_ID, OWNER_ID)

    assert count == 1
    get_or_create.assert_awaited_once()
    assert get_or_create.await_args.kwargs["node_id"] == NODE_ID
    assert register.await_args.kwargs["webhook_url"] == WEBHOOK_URL, (
        "Provider re-registration must use the preserved webhook URL"
    )


@pytest.mark.asyncio
async def test_restore_nodes_resources_invokes_reregistration():
    """restore_nodes_resources routes provider re-registration through the
    register_node_webhooks choke point and surfaces the count."""
    pool, _ = _pool()
    nodes = [_node()]
    rereg = AsyncMock(return_value=1)

    with patch("utils.webhook_manager.WebhookManager.register_node_webhooks", rereg):
        from utils.workflow_resource_manager import restore_nodes_resources
        results = await restore_nodes_resources(pool, OWNER_ID, WORKFLOW_ID, nodes)

    rereg.assert_awaited_once_with(pool, WORKFLOW_ID, OWNER_ID, nodes=nodes, node_ids=None)
    assert results["reregistered"] == 1


# ─── persist_registration_state: stringify + raise-on-zero-rows ───────────────

@pytest.mark.asyncio
async def test_persist_registration_state_stringifies_int_external_id():
    """GitHub/Shopify return int webhook ids; the TEXT column bind must be the
    string form (no asyncpg DataError), and the UPDATE must activate the row."""
    pool, conn = _pool()

    await WebhookManager.persist_registration_state(
        pool, WEBHOOK_ID,
        signing_secret=SIGNING_SECRET,
        external_webhook_id=987654321,
        registered_operation=OPERATION,
        registered_credential_id=CREDENTIAL_ID,
    )

    args = conn.execute.await_args.args
    assert "is_active = true" in args[0]
    assert args[1] == SIGNING_SECRET
    assert args[2] == "987654321" and isinstance(args[2], str)
    assert args[3] == OPERATION
    assert args[4] == CREDENTIAL_ID
    # args[5] = registered_fingerprint (None when the caller doesn't supply
    # one), args[6] = the row id.
    assert args[5] is None
    assert args[6] == uuid.UUID(WEBHOOK_ID)


@pytest.mark.asyncio
async def test_persist_registration_state_raises_on_zero_rows():
    """A 0-row UPDATE (row vanished) must raise — the row is what verification
    and deregistration read, so silent degradation is a real failure."""
    pool, _ = _pool(execute="UPDATE 0")

    with pytest.raises(RuntimeError):
        await WebhookManager.persist_registration_state(
            pool, WEBHOOK_ID,
            signing_secret=SIGNING_SECRET,
            external_webhook_id=ENDPOINT_ID,
            registered_operation=OPERATION,
            registered_credential_id=CREDENTIAL_ID,
        )


# ─── get_or_create_webhook: marker-gated auto-activation ──────────────────────

@pytest.mark.asyncio
async def test_get_or_create_auto_activates_simple_inactive_row():
    """A simple inactive row (no registered_operation marker — plain
    webhook/cron/alarm) re-activates on touch."""
    row = {"id": uuid.UUID(WEBHOOK_ID), "is_active": False, "secret_set": False,
           "external_webhook_id": None, "registered_operation": None,
           "registered_credential_id": None}
    pool, conn = _pool(fetchrow=row)

    with patch(
        "utils.webhook_tunnel.get_webhook_url",
        MagicMock(return_value=WEBHOOK_URL),
    ):
        result = await WebhookManager.get_or_create_webhook(
            pool, OWNER_ID, uuid.UUID(WORKFLOW_ID), NODE_ID
        )

    assert result["webhook_id"] == WEBHOOK_ID
    assert result["is_active"] is True
    assert "reactivated" not in result  # old key is gone from the contract
    activations = [c for c in conn.execute.await_args_list if "is_active = true" in c.args[0]]
    assert len(activations) == 1


@pytest.mark.asyncio
async def test_get_or_create_does_not_auto_activate_marker_row():
    """An inactive row carrying the registered_operation marker stays INACTIVE
    until a successful registration activates it (persist_registration_state)."""
    row = {"id": uuid.UUID(WEBHOOK_ID), "is_active": False, "secret_set": True,
           "external_webhook_id": ENDPOINT_ID, "registered_operation": OPERATION,
           "registered_credential_id": CREDENTIAL_ID}
    pool, conn = _pool(fetchrow=row)

    with patch(
        "utils.webhook_tunnel.get_webhook_url",
        MagicMock(return_value=WEBHOOK_URL),
    ):
        result = await WebhookManager.get_or_create_webhook(
            pool, OWNER_ID, uuid.UUID(WORKFLOW_ID), NODE_ID
        )

    assert result["is_active"] is False
    assert result["registered_operation"] == OPERATION
    assert result["registered_credential_id"] == CREDENTIAL_ID
    assert result["external_webhook_id"] == ENDPOINT_ID
    assert result["secret_set"] is True
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_deregister_resolves_rows_registered_credential_for_teardown():
    """After a credential swap the node config carries only the NEW credential,
    but provider teardown may need the ORIGINAL registrant's auth. The row
    remembers it (registered_credential_id) and deregister resolves it FIRST —
    this replaced handle_credential_change's old-credential plumbing, which
    raced the debounced mirror."""
    OLD_CRED, NEW_CRED = str(uuid.uuid4()), str(uuid.uuid4())
    node = _node({**STRIPE_NODE_CONFIG, "credentialIds": {"stripe_api_key": NEW_CRED}})
    pool, conn = _pool(
        fetchrow=_wf_row([node]),
        fetch=[{"node_id": NODE_ID, "external_webhook_id": ENDPOINT_ID,
                "registered_operation": OPERATION,
                "registered_credential_id": OLD_CRED}],
    )
    unregister = AsyncMock()
    node_cls = _fake_stripe_node(unregister=unregister)
    resolved = []

    async def fake_resolve(pool_, credential_id, **kw):
        resolved.append(credential_id)
        return {"api_key": f"key-{credential_id[:8]}"}

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-stripe": node_cls}),
        patch("utils.webhook_manager._resolve_node_credential", fake_resolve),
    ):
        results = await WebhookManager.deregister_node_webhooks(
            pool, WORKFLOW_ID, [NODE_ID]
        )

    assert results["deregistered"] == 1
    # The row's registrant credential is resolved FIRST, ahead of the config's
    # current (new) credential — teardown can auth as the original registrant.
    assert resolved[0] == OLD_CRED
    assert NEW_CRED in resolved
