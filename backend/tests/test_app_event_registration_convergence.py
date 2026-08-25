"""App-event trigger registration convergence (Slack/HubSpot/Discord).

The third registration family — app-level fan-out subscriptions in
``webhook_subscriptions`` — must be covered by EVERY lifecycle surface the
other families already have: headless provisioning (builder/MCP), the
level-triggered reconciler (operation/credential change, restores), and the
graph-driven nightly sweep. The 2026-07-30 incident: a builder-built Slack
agent shipped with no subscription row, and the first mentions were silently
dropped until a config-panel open happened to register it.

Drives the REAL SlackNode registration core against a stateful fake
subscription table; only the DB/credential edges are patched.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.slack_node import SlackNode
from utils.webhook_manager import WebhookManager

pytestmark = pytest.mark.asyncio

OWNER = str(uuid.uuid4())
NEW_OWNER = str(uuid.uuid4())
WF = str(uuid.uuid4())
NODE = "slack-trigger"
CRED = "cred-1"


class SubWorld:
    """Observed state: the webhook_subscriptions table for one workflow."""

    def __init__(self):
        self.rows = []
        self.owner = OWNER
        self.nodes = []

    def set_node(self, operation, credential=CRED, node_type="automation-slack"):
        self.nodes = [{
            "id": NODE, "type": node_type,
            "config": {
                "operation": operation,
                "credentialIds": {"slack_oauth": credential} if credential else {},
            },
        }]

    def seed_rows(self, event_types, credential_id=CRED, user_id=OWNER,
                  tenant_id="T123"):
        self.rows = [{
            "provider": "slack", "tenant_id": tenant_id, "event_type": et,
            "user_id": user_id, "workflow_id": WF, "node_id": NODE,
            "credential_id": credential_id, "verification_key": None,
        } for et in event_types]

    async def get(self, pool, workflow_id, node_id):
        return [dict(r) for r in self.rows
                if r["workflow_id"] == str(workflow_id) and r["node_id"] == node_id]

    async def save(self, pool, *, provider, tenant_id, user_id, workflow_id,
                   node_id, credential_id, event_types, verification_key=None):
        self.rows = [r for r in self.rows
                     if not (r["workflow_id"] == workflow_id and r["node_id"] == node_id)]
        for et in event_types:
            self.rows.append({
                "provider": provider, "tenant_id": tenant_id, "event_type": et,
                "user_id": user_id, "workflow_id": workflow_id, "node_id": node_id,
                "credential_id": credential_id, "verification_key": verification_key,
            })

    async def delete(self, pool, workflow_id, node_id):
        self.rows = [r for r in self.rows
                     if not (r["workflow_id"] == str(workflow_id) and r["node_id"] == node_id)]


@pytest.fixture
def world():
    return SubWorld()


def _fake_pool():
    """Pool for the external-family fallthrough (webhooks-row fetch on the
    removed-node path) — no rows, no webhooks table state."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool


async def _reconcile(world, resolve=("cred-1", {"team_id": "T123"})):
    async def load_owner_nodes(pool, wf_uuid, include_nodes=True):
        return world.owner, list(world.nodes)

    with (
        patch("utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes),
        patch("nodes.core.webhook_subscriptions.get_node_subscriptions",
              AsyncMock(side_effect=world.get)),
        patch("nodes.core.webhook_subscriptions.save_subscriptions",
              AsyncMock(side_effect=world.save)),
        patch("nodes.core.webhook_subscriptions.delete_subscriptions",
              AsyncMock(side_effect=world.delete)),
        patch.object(SlackNode, "_resolve_trigger_credential",
                     AsyncMock(return_value=resolve)) as resolver,
        patch("utils.redis_client.get_shared_redis", lambda: None),
    ):
        result = await WebhookManager.reconcile_node(_fake_pool(), WF, NODE)
        result["_credential_loads"] = resolver.await_count
    return result


# ─── the convergence matrix ──────────────────────────────────────────────────


async def test_never_registered_trigger_registers(world):
    """The 2026-07-30 gap: desired state exists in the graph, no rows — any
    reconcile surface (sweep, restore, op-change hook) must register."""
    world.set_node("on_app_mention")
    assert (await _reconcile(world))["state"] == "registered"
    assert {r["event_type"] for r in world.rows} == {"app_mention"}
    assert all(r["user_id"] == OWNER for r in world.rows)
    assert all(r["tenant_id"] == "T123" for r in world.rows)


async def test_matching_rows_are_live_without_credential_load(world):
    """Sweep fast path: one SELECT, no credential resolution, no writes."""
    world.set_node("on_app_mention")
    world.seed_rows(["app_mention"])
    result = await _reconcile(world)
    assert result["state"] == "live"
    assert result["_credential_loads"] == 0


async def test_operation_change_converges_event_type(world):
    """Headless op change (MCP/builder) must not leave the row on the old
    event type — the trigger would fire on the wrong Slack event."""
    world.set_node("on_channel_message")
    world.seed_rows(["app_mention"])
    assert (await _reconcile(world))["state"] == "registered"
    assert {r["event_type"] for r in world.rows} == {"message"}


async def test_trigger_to_action_op_tears_down(world):
    world.set_node("send_message")
    world.seed_rows(["app_mention"])
    assert (await _reconcile(world))["state"] == "deregistered"
    assert world.rows == []


async def test_removed_node_orphan_rows_cleaned(world):
    """Node left the saved graph: rows must not fan out to it forever."""
    world.nodes = []
    world.seed_rows(["app_mention"])
    assert (await _reconcile(world))["state"] == "deregistered"
    assert world.rows == []


async def test_unresolvable_credential_keeps_rows(world):
    """Never delete on a non-definitive signal: a credential that fails to
    load (provider blip, revoked) must not tear down a live registration —
    fan-out doesn't need the credential."""
    world.set_node("on_app_mention")
    world.seed_rows(["app_mention"], user_id=NEW_OWNER)  # force convergence path
    result = await _reconcile(world, resolve=(CRED, None))
    assert result["state"] == "unregistered"
    assert {r["event_type"] for r in world.rows} == {"app_mention"}


async def test_detached_credential_keeps_live_rows(world):
    world.set_node("on_app_mention", credential=None)
    world.seed_rows(["app_mention"])
    result = await _reconcile(world)
    assert result["state"] == "unregistered"
    assert {r["event_type"] for r in world.rows} == {"app_mention"}


async def test_ownership_transfer_restamps_fire_identity(world):
    """Rows fire (and bill) as their stamped user — after a transfer the
    reconciler must restamp to the new owner."""
    world.set_node("on_app_mention")
    world.seed_rows(["app_mention"], user_id=OWNER)
    world.owner = NEW_OWNER
    assert (await _reconcile(world))["state"] == "registered"
    assert all(r["user_id"] == NEW_OWNER for r in world.rows)


async def test_reconcile_is_idempotent(world):
    world.set_node("on_app_mention")
    assert (await _reconcile(world))["state"] == "registered"
    rows_after_first = [dict(r) for r in world.rows]
    assert (await _reconcile(world))["state"] == "live"
    assert world.rows == rows_after_first


# ─── headless provisioning (builder / MCP) ───────────────────────────────────


def test_gate_recognizes_every_app_event_trigger_op():
    """node_webhook_field_for is the candidate pre-filter for BOTH headless
    write paths (builder step 3d, MCP auto-provision) — an op it misses ships
    dead. Every app-event trigger op must resolve to subscription_status."""
    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.webhook_subscriptions import AppEventTriggerMixin

    checked = 0
    for node_type, node_class in NODE_REGISTRY.items():
        if not (isinstance(node_class, type)
                and issubclass(node_class, AppEventTriggerMixin)):
            continue
        for op in node_class._trigger_event_map:
            checked += 1
            assert WebhookManager.node_webhook_field_for(node_type, op) == \
                "subscription_status", f"{node_type}:{op} invisible to provisioning"
    assert checked > 0


async def test_provision_node_webhook_registers_headlessly(world):
    """The panel-equivalent load must register a Slack trigger with no UI
    visit — exactly what the builder-built workflow was missing."""
    with (
        patch("utils.credential_loader.load_credential",
              AsyncMock(return_value={"team_id": "T123", "access_token": "t"})),
        patch("utils.webhook_manager._load_workflow_owner_and_nodes",
              AsyncMock(return_value=(OWNER, []))),
        patch("nodes.core.webhook_subscriptions.get_node_subscriptions",
              AsyncMock(side_effect=world.get)),
        patch("nodes.core.webhook_subscriptions.save_subscriptions",
              AsyncMock(side_effect=world.save)),
    ):
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id="collab-session-user",
            workflow_id=WF,
            node_id=NODE,
            node_type="automation-slack",
            operation="on_app_mention",
            config={"operation": "on_app_mention",
                    "credentialIds": {"slack_oauth": CRED}},
        )
    assert updates["trigger_registered"] is True
    assert {r["event_type"] for r in world.rows} == {"app_mention"}
    # Stamped with the OWNER (fire/billing identity), not the session user.
    assert all(r["user_id"] == OWNER for r in world.rows)


async def test_provision_folds_operation_into_loader_context(world):
    """Builder GraphState holds operation OUTSIDE node.config — the seam must
    fold the parameter in, or the mixin registers against operation=None
    ('Unknown trigger operation: None', 2026-07-30 builder follow-up)."""
    with (
        patch("utils.credential_loader.load_credential",
              AsyncMock(return_value={"team_id": "T123", "access_token": "t"})),
        patch("utils.webhook_manager._load_workflow_owner_and_nodes",
              AsyncMock(return_value=(OWNER, []))),
        patch("nodes.core.webhook_subscriptions.get_node_subscriptions",
              AsyncMock(side_effect=world.get)),
        patch("nodes.core.webhook_subscriptions.save_subscriptions",
              AsyncMock(side_effect=world.save)),
    ):
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id=OWNER,
            workflow_id=WF,
            node_id=NODE,
            node_type="automation-slack",
            operation="on_app_mention",
            config={"credentialIds": {"slack_oauth": CRED}},  # no operation key
        )
    assert updates["trigger_registered"] is True, str(updates)
    assert {r["event_type"] for r in world.rows} == {"app_mention"}


def test_snapshot_trigger_status_line():
    """The brain's workflow snapshot must carry the registration model for
    app-event triggers — status, auto-registration, and the fact there is no
    webhook URL (the interface agent invented webhook-URL mental models and
    manual registration steps without it)."""
    from coder.workflow.operation_catalog import trigger_status_line

    registered = trigger_status_line(
        "automation-slack", "on_app_mention",
        {"trigger_registered": True,
         "subscription_status": "Active — listening across all channels"},
    )
    assert "no webhook URL" in registered and "Active" in registered

    failed = trigger_status_line(
        "automation-slack", "on_app_mention",
        {"trigger_registered": False, "trigger_error": "Not registered: boom"},
    )
    assert "NOT registered" in failed and "automatically" in failed

    pending = trigger_status_line("automation-slack", "on_app_mention", {})
    assert "registers automatically" in pending

    assert trigger_status_line("automation-slack", "send_message", {}) is None


# ─── restore choke point ─────────────────────────────────────────────────────


async def test_register_node_webhooks_reconciles_app_event_nodes(world):
    """Trash/checkpoint restore and canvas-undo route here; app-event nodes
    (whose teardown hard-deletes rows, leaving no inactive-row marker) must
    re-register via the reconciler."""
    world.set_node("on_app_mention")

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    async def load_owner_nodes(p, wf_uuid, include_nodes=True):
        return OWNER, list(world.nodes)

    with (
        patch("utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes),
        patch.object(WebhookManager, "reconcile_node",
                     AsyncMock(return_value={"state": "registered"})) as rec,
    ):
        count = await WebhookManager.register_node_webhooks(
            pool, WF, OWNER, node_ids=[NODE]
        )
    assert count == 1
    rec.assert_awaited_once_with(pool, WF, NODE)


# ─── graph-driven sweep ──────────────────────────────────────────────────────


async def _run_sweep(world, sub_node_ids=(), webhook_node_ids=()):
    wf_uuid = uuid.UUID(WF)
    conn = AsyncMock()

    async def fetch(sql, *args):
        if "WITH candidates" in sql:
            return [{"id": wf_uuid}]
        if "FROM webhooks" in sql:
            return [{"node_id": n} for n in webhook_node_ids]
        if "FROM webhook_subscriptions" in sql:
            return [{"node_id": n} for n in sub_node_ids]
        raise AssertionError(f"unexpected sweep SQL: {sql}")

    conn.fetch = AsyncMock(side_effect=fetch)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    async def load_owner_nodes(p, wf, include_nodes=True):
        return world.owner, list(world.nodes)

    with (
        patch("utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes),
        patch.object(WebhookManager, "reconcile_node",
                     AsyncMock(return_value={"state": "registered"})) as rec,
    ):
        stats = await WebhookManager.resync_trigger_registrations(pool)
    return stats, rec


async def test_sweep_heals_never_registered_graph_trigger(world):
    """The structural fix: the sweep walks GRAPHS, so a registration that
    never happened (headless surface missed provisioning) is healed — the
    old row-driven sweep could never see it."""
    world.set_node("on_app_mention")
    stats, rec = await _run_sweep(world)
    assert stats["checked"] == 1 and stats["converged"] == 1
    assert rec.await_args.args[1:] == (WF, NODE)


async def test_sweep_cleans_orphaned_subscription_rows(world):
    world.nodes = []
    stats, rec = await _run_sweep(world, sub_node_ids=[NODE])
    assert stats["checked"] == 1
    assert rec.await_args.args[1:] == (WF, NODE)


async def test_sweep_unions_graph_row_and_subscription_candidates(world):
    world.set_node("on_app_mention")
    stats, rec = await _run_sweep(
        world, sub_node_ids=["ghost-sub"], webhook_node_ids=["ghost-row"]
    )
    assert stats["checked"] == 3
    assert {c.args[2] for c in rec.await_args_list} == {NODE, "ghost-sub", "ghost-row"}


# ─── registry-wide enforcement ───────────────────────────────────────────────

# Trigger operations that genuinely need NO registration of any kind — the
# node manages its subscription at run time against user-owned infrastructure.
# Adding an entry here requires the same scrutiny as a new registration
# family: if events must reach NoClick over the public internet, it does NOT
# belong on this list.
REGISTRATION_FREE_TRIGGER_OPS = {
    ("automation-redis", "subscribe_to_channels"),
    ("automation-redis", "subscribe_to_channel_patterns"),
}


def test_every_trigger_operation_has_a_registration_strategy():
    """A trigger family invisible to the provisioning gate ships dead from
    every headless write path (the 2026-07-30 Slack incident class). Every
    operation the trigger predicate flags must resolve to a registration
    marker — or be explicitly declared registration-free above."""
    from nodes.agent.node_op_tools import _trigger_operations
    from nodes.core.registry import NODE_REGISTRY

    missing = []
    for node_type in sorted(NODE_REGISTRY):
        for op in sorted(_trigger_operations(node_type)):
            if (node_type, op) in REGISTRATION_FREE_TRIGGER_OPS:
                continue
            if not WebhookManager.node_webhook_field_for(node_type, op):
                missing.append((node_type, op))
    assert not missing, (
        "Trigger operations with NO registration strategy — headless builds "
        f"ship them dead: {missing}. Register a marker field (webhook widget, "
        "webhook_url/subscription_status ui:loadValue) or, only if events "
        "truly need no registration, add to REGISTRATION_FREE_TRIGGER_OPS."
    )
