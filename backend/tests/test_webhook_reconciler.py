"""Level-triggered webhook registration reconciler (utils.webhook_manager.
reconcile_node) — the convergence matrix that replaced per-surface old-vs-new
transition plumbing (which raced the debounced config mirror and orphaned one
provider hook per rapid operation flip, 2026-07-19).

The conformance harness drives reconcile through the mutation sequences that
historically produced duplicates (rapid operation flips, credential swaps,
op-to-action changes, deletes) against a stateful fake world and asserts the
invariant the architecture promises: AT MOST ONE live registration, always
matching the node's current saved config.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.webhook_manager import WebhookManager, registration_fingerprint

pytestmark = pytest.mark.asyncio

OWNER = str(uuid.uuid4())
WF = str(uuid.uuid4())
NODE = "trigger-1"


class _FakeTrigger:
    """Mixin-shaped node class with a declarative fingerprint field."""

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"repository": (config or {}).get("repository")}

    @classmethod
    def webhook_registration_stale(cls, config, webhook_data):
        # Mirror-style staleness (PostHog's registered_event_name pattern):
        # stale iff a mirror exists and disagrees with the config field.
        mirror = (config or {}).get("registered_repository")
        return mirror is not None and mirror != (config or {}).get("repository")


class World:
    """Observed state: the webhooks row + the provider's live registrations."""

    def __init__(self):
        self.row = None
        self.provider = {}          # ext_id -> {"op", "cred"}
        self.next_ext = 100
        self.nodes = []

    def set_node(self, operation, credential="cred-1", repository="o/r", requires=True, **extra):
        self.nodes = [{
            "id": NODE, "type": "automation-fake",
            "config": {
                "operation": operation, "repository": repository,
                "credentialIds": {"fake_key": credential} if credential else {},
                **extra,
            },
        }]
        self.requires = requires

    def delete_node(self):
        self.nodes = []

    async def deregister(self, pool, workflow_id, node_ids=None, **kw):
        # Mirrors the choke point's contract: provider teardown via row
        # context, then deactivate preserving the marker.
        if self.row and self.row["external_webhook_id"]:
            self.provider.pop(self.row["external_webhook_id"], None)
        if self.row:
            self.row = {
                **self.row, "is_active": False,
                "external_webhook_id": None, "registered_fingerprint": None,
            }
        return {"deregistered": 1, "failed": 0}

    async def register_single(self, pool, *, wf_uuid, user_id, node_class,
                              node_type, node_id, node_config, credential,
                              credential_id, current_op):
        ext = f"ext-{self.next_ext}"
        self.next_ext += 1
        self.provider[ext] = {"op": current_op, "cred": credential_id}
        self.row = {
            "id": uuid.uuid4(), "is_active": True,
            "external_webhook_id": ext,
            "registered_operation": current_op,
            "registered_credential_id": credential_id,
            "registered_fingerprint": registration_fingerprint(
                node_class, current_op, credential_id, node_config
            ),
        }
        return True


@pytest.fixture
def world():
    return World()


def _pool_for(world):
    pool = MagicMock()
    conn = AsyncMock()

    async def fetchrow(sql, *args):
        if "FROM webhooks" in sql:
            return world.row
        return None

    async def execute(sql, *args):
        # Fingerprint stamps mutate the observed row: the adoption stamp
        # (WHERE id) and the fields-change hook's historical stamp (WHERE
        # ... registered_fingerprint IS NULL).
        if "UPDATE webhooks SET registered_fingerprint" in sql and world.row:
            if "registered_fingerprint IS NULL" in sql:
                if world.row["is_active"] and world.row["registered_fingerprint"] is None:
                    world.row = {**world.row, "registered_fingerprint": args[0]}
            else:
                world.row = {**world.row, "registered_fingerprint": args[0]}
        return "UPDATE 1"

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.execute = AsyncMock(side_effect=execute)
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool


async def _reconcile(world):
    async def load_owner_nodes(pool, wf_uuid, include_nodes=True):
        return OWNER, list(world.nodes)

    with (
        patch("utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes),
        patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks",
              AsyncMock(side_effect=world.deregister)),
        patch("utils.webhook_manager.WebhookManager._register_single_node",
              AsyncMock(side_effect=world.register_single)),
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-fake": _FakeTrigger}),
        patch("nodes.core.webhook_trigger.ExternalWebhookTriggerMixin", object),
        patch.object(_FakeTrigger, "_resolve_trigger_credential",
                     AsyncMock(return_value={"api_key": "x"}), create=True),
        patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
              staticmethod(lambda nt, op: getattr(world, "requires", True) and op is not None
                           and op.startswith("on_"))),
        patch("utils.redis_client.get_shared_redis", lambda: None),
    ):
        return await WebhookManager.reconcile_node(_pool_for(world), WF, NODE)


def _assert_invariant(world):
    assert len(world.provider) <= 1, f"duplicate live registrations: {world.provider}"
    if world.row and world.row["is_active"]:
        [(ext, spec)] = world.provider.items()
        assert world.row["external_webhook_id"] == ext
        cfg = world.nodes[0]["config"]
        assert spec["op"] == cfg["operation"]


# ─── the conformance matrix ──────────────────────────────────────────────────


async def test_initial_registration_and_idempotence(world):
    world.set_node("on_issue_closed")
    assert (await _reconcile(world))["state"] == "registered"
    _assert_invariant(world)
    # Reconcile again: fingerprint matches → pure no-op, no provider churn.
    ext_before = world.row["external_webhook_id"]
    assert (await _reconcile(world))["state"] == "live"
    assert world.row["external_webhook_id"] == ext_before


async def test_rapid_operation_flips_converge_to_one(world):
    """The 2026-07-19 duplicate-hooks sequence."""
    for op in ("on_issue_comment", "on_release_published", "on_issue_closed"):
        world.set_node(op)
        await _reconcile(world)
        _assert_invariant(world)
    assert list(world.provider.values())[0]["op"] == "on_issue_closed"


async def test_credential_swap_reregisters_under_new_credential(world):
    world.set_node("on_issue_closed", credential="cred-1")
    await _reconcile(world)
    world.set_node("on_issue_closed", credential="cred-2")
    assert (await _reconcile(world))["state"] == "registered"
    _assert_invariant(world)
    assert list(world.provider.values())[0]["cred"] == "cred-2"


async def test_fingerprint_field_change_reregisters(world):
    world.set_node("on_issue_closed", repository="o/r")
    await _reconcile(world)
    world.set_node("on_issue_closed", repository="o/other")
    assert (await _reconcile(world))["state"] == "registered"
    _assert_invariant(world)


async def test_switch_to_action_operation_deregisters(world):
    world.set_node("on_issue_closed")
    await _reconcile(world)
    world.set_node("create_issue")  # not a trigger op
    assert (await _reconcile(world))["state"] == "deregistered"
    assert world.provider == {}
    assert world.row["is_active"] is False


async def test_node_deletion_deregisters(world):
    world.set_node("on_issue_closed")
    await _reconcile(world)
    world.delete_node()
    assert (await _reconcile(world))["state"] == "deregistered"
    assert world.provider == {}


async def test_never_registered_action_node_is_untouched(world):
    world.set_node("create_issue")
    assert (await _reconcile(world))["state"] == "noop"
    assert world.provider == {} and world.row is None


async def test_missing_credential_leaves_unregistered(world):
    world.set_node("on_issue_closed")
    with patch.object(_FakeTrigger, "_resolve_trigger_credential",
                      AsyncMock(return_value=None), create=True):
        async def load_owner_nodes(pool, wf_uuid, include_nodes=True):
            return OWNER, list(world.nodes)

        with (
            patch("utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes),
            patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks",
                  AsyncMock(side_effect=world.deregister)),
            patch("utils.webhook_manager.WebhookManager._register_single_node",
                  AsyncMock(side_effect=world.register_single)),
            patch("nodes.core.registry.NODE_REGISTRY", {"automation-fake": _FakeTrigger}),
            patch("nodes.core.webhook_trigger.ExternalWebhookTriggerMixin", object),
            patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
                  staticmethod(lambda nt, op: op is not None and op.startswith("on_"))),
            patch("utils.redis_client.get_shared_redis", lambda: None),
        ):
            result = await WebhookManager.reconcile_node(_pool_for(world), WF, NODE)
    assert result["state"] == "unregistered"
    assert world.provider == {}


async def test_pre_migration_row_is_adopted_not_rotated(world):
    """A NULL-fingerprint row whose op+credential match must be stamped, not
    torn down — the first nightly resync would otherwise churn every
    pre-existing trigger's provider registration."""
    world.set_node("on_issue_closed", credential="cred-1")
    world.provider["ext-legacy"] = {"op": "on_issue_closed", "cred": "cred-1"}
    world.row = {
        "id": uuid.uuid4(), "is_active": True,
        "external_webhook_id": "ext-legacy",
        "registered_operation": "on_issue_closed",
        "registered_credential_id": "cred-1",
        "registered_fingerprint": None,
    }
    result = await _reconcile(world)
    assert result["state"] == "live" and result.get("adopted") is True
    # Provider untouched — same endpoint still live.
    assert list(world.provider) == ["ext-legacy"]


async def test_pre_migration_row_with_stale_mirror_rotates_not_adopts(world):
    """A NULL-fingerprint row whose NODE-DECLARED staleness signal fires (a
    registration mirror disagreeing with config, PostHog's registered_event_name
    pattern) must be rotated at adoption time — stamping it would bless drift
    that predates the fingerprint era, permanently (the nightly resync then
    reads it as live forever)."""
    world.set_node("on_issue_closed", credential="cred-1",
                   registered_repository="o/old")
    world.provider["ext-legacy"] = {"op": "on_issue_closed", "cred": "cred-1"}
    world.row = {
        "id": uuid.uuid4(), "is_active": True,
        "external_webhook_id": "ext-legacy",
        "registered_operation": "on_issue_closed",
        "registered_credential_id": "cred-1",
        "registered_fingerprint": None,
    }
    result = await _reconcile(world)
    assert result["state"] == "registered" and not result.get("adopted")
    assert "ext-legacy" not in world.provider
    _assert_invariant(world)


# ─── fingerprint semantics ───────────────────────────────────────────────────


def test_fingerprint_sensitivity_and_stability():
    fp = lambda **kw: registration_fingerprint(
        _FakeTrigger, kw.get("op", "on_x"), kw.get("cred", "c1"),
        {"repository": kw.get("repo", "o/r")},
    )
    assert fp() == fp()                          # stable
    assert fp(op="on_y") != fp()                 # operation-sensitive
    assert fp(cred="c2") != fp()                 # credential-sensitive
    assert fp(repo="o/z") != fp()                # declared-field-sensitive
    # Classes without declared fields ignore config entirely.
    class Bare: ...
    assert registration_fingerprint(Bare, "on_x", "c1", {"a": 1}) == \
        registration_fingerprint(Bare, "on_x", "c1", {"b": 2})


# ─── registry-wide conformance: every mixin node declares its fields ─────────


def test_every_trigger_node_declares_registration_relevant_fields():
    """Self-enforcement for the declarative contract: any config field a
    node's ``_register_external_webhook`` reads (directly or via a helper
    taking config) MUST appear in ``registration_fingerprint_fields`` — an
    undeclared field means edits to it silently never re-register (PostHog's
    event_name was exactly this before the reconciler). A new trigger node
    (or a new config read in an existing hook) fails here until declared."""
    import ast
    import inspect
    import re

    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

    # Lifecycle/plumbing fields that never affect WHAT gets registered.
    IGNORE = {
        "operation", "signing_secret", "external_webhook_id", "webhook_id",
        "webhook_url", "trigger_registered", "trigger_error", "credentialIds",
    }
    GET_RE = re.compile(
        r"""(?:config|cfg)(?:\s+or\s+\{\})?\)?\s*\.get\(\s*["']([a-zA-Z_]+)["']"""
    )
    HELPER_RE = re.compile(r"(?:cls\.)?(_[a-z_]+)\(\(?(?:config|cfg)")

    failures = []
    for node_type, node_class in NODE_REGISTRY.items():
        if not (isinstance(node_class, type)
                and issubclass(node_class, ExternalWebhookTriggerMixin)):
            continue
        hook = node_class.__dict__.get("_register_external_webhook")
        if hook is None:
            continue
        try:
            src = inspect.getsource(hook.__func__ if hasattr(hook, "__func__") else hook)
        except (OSError, TypeError):
            continue
        reads = set(GET_RE.findall(src)) - IGNORE
        # Helpers that take config: include the fields THEY read.
        for helper_name in HELPER_RE.findall(src):
            helper = getattr(node_class, helper_name, None)
            if helper is None:
                continue
            try:
                hsrc = inspect.getsource(
                    helper.__func__ if hasattr(helper, "__func__") else helper
                )
            except (OSError, TypeError):
                continue
            reads |= set(re.findall(r"""\.get\(\s*["']([a-zA-Z_]+)["']""", hsrc)) - IGNORE
        if not reads:
            continue
        declared = set(node_class.registration_fingerprint_fields(
            {f: f"probe-{f}" for f in reads}
        ).keys())
        missing = reads - declared
        if missing:
            failures.append(f"{node_type}: reads {sorted(missing)} but doesn't declare them")

    assert not failures, (
        "Trigger nodes read registration-relevant config fields without "
        "declaring them in registration_fingerprint_fields — edits to these "
        "fields will silently never re-register:\n" + "\n".join(failures)
    )


async def test_credential_removed_after_live_tears_down_then_waits(world):
    """Registered → credential removed: the stale registration is torn down
    (fingerprint mismatch fires the teardown BEFORE credential resolution),
    then registration waits (unregistered) until a credential returns — at
    which point the next reconcile converges to live again."""
    world.set_node("on_issue_closed", credential="cred-1")
    await _reconcile(world)
    assert len(world.provider) == 1

    world.set_node("on_issue_closed", credential=None)
    with patch.object(_FakeTrigger, "_resolve_trigger_credential",
                      AsyncMock(return_value=None), create=True):
        async def load_owner_nodes(pool, wf_uuid, include_nodes=True):
            return OWNER, list(world.nodes)

        with (
            patch("utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes),
            patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks",
                  AsyncMock(side_effect=world.deregister)),
            patch("utils.webhook_manager.WebhookManager._register_single_node",
                  AsyncMock(side_effect=world.register_single)),
            patch("nodes.core.registry.NODE_REGISTRY", {"automation-fake": _FakeTrigger}),
            patch("nodes.core.webhook_trigger.ExternalWebhookTriggerMixin", object),
            patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
                  staticmethod(lambda nt, op: op is not None and op.startswith("on_"))),
            patch("utils.redis_client.get_shared_redis", lambda: None),
        ):
            result = await WebhookManager.reconcile_node(_pool_for(world), WF, NODE)
    assert result["state"] == "unregistered"
    assert world.provider == {}, "stale registration must be torn down, not left live"

    # Credential returns → next reconcile converges back to live.
    world.set_node("on_issue_closed", credential="cred-2")
    assert (await _reconcile(world))["state"] == "registered"
    _assert_invariant(world)


async def _fields_change(world, old_cfg, new_cfg):
    """Drive handle_registration_fields_change with the REAL reconcile against
    the world (same patch stack as _reconcile)."""
    async def load_owner_nodes(pool, wf_uuid, include_nodes=True):
        return OWNER, list(world.nodes)

    with (
        patch("utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes),
        patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks",
              AsyncMock(side_effect=world.deregister)),
        patch("utils.webhook_manager.WebhookManager._register_single_node",
              AsyncMock(side_effect=world.register_single)),
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-fake": _FakeTrigger}),
        patch("nodes.core.webhook_trigger.ExternalWebhookTriggerMixin", object),
        patch.object(_FakeTrigger, "_resolve_trigger_credential",
                     AsyncMock(return_value={"api_key": "x"}), create=True),
        patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
              staticmethod(lambda nt, op: op is not None and op.startswith("on_"))),
        patch("utils.redis_client.get_shared_redis", lambda: None),
    ):
        return await WebhookManager.handle_registration_fields_change(
            _pool_for(world), "automation-fake", WF, NODE, old_cfg, new_cfg,
            user_id="u-1",
        )


async def test_fields_edit_on_pre_migration_row_rotates_not_adopts(world):
    """The 2026-07-20 'panel reopen still required' bug: the FIRST fields-only
    edit of a pre-fingerprint (NULL) row hit reconcile's adoption branch
    (op+credential match) — the row got stamped with the NEW config's
    fingerprint while the provider stayed registered on the OLD field value.
    The hook must stamp the OLD config's fingerprint first so the reconcile
    sees the drift and rotates the provider endpoint."""
    old_cfg = {"operation": "on_issue_closed", "repository": "o/r",
               "credentialIds": {"fake_key": "cred-1"}}
    new_cfg = {**old_cfg, "repository": "o/other"}
    world.set_node("on_issue_closed", repository="o/other")
    world.provider["ext-legacy"] = {"op": "on_issue_closed", "cred": "cred-1"}
    world.row = {
        "id": uuid.uuid4(), "is_active": True,
        "external_webhook_id": "ext-legacy",
        "registered_operation": "on_issue_closed",
        "registered_credential_id": "cred-1",
        "registered_fingerprint": None,
    }
    acted = await _fields_change(world, old_cfg, new_cfg)
    assert acted is True
    # Rotated, not adopted: the legacy endpoint (built from the old field
    # value) is gone and the live registration matches the current config.
    assert "ext-legacy" not in world.provider
    _assert_invariant(world)
    assert world.row["registered_fingerprint"] == registration_fingerprint(
        _FakeTrigger, "on_issue_closed", "cred-1", new_cfg
    )


async def test_fields_edit_on_stamped_row_still_rotates(world):
    """Post-migration rows (fingerprint already stamped) rotate through the
    normal mismatch path — the historical stamp is a no-op on them."""
    world.set_node("on_issue_closed", repository="o/r")
    await _reconcile(world)
    old_cfg = dict(world.nodes[0]["config"])
    new_cfg = {**old_cfg, "repository": "o/other"}
    world.set_node("on_issue_closed", repository="o/other")
    acted = await _fields_change(world, old_cfg, new_cfg)
    assert acted is True
    _assert_invariant(world)


# ─── registration-fields change hook (the PostHog event_name class) ──────────


class _FieldsTrigger:
    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_name": (config or {}).get("event_name")}


async def test_fields_change_hook_reconciles_on_declared_field_edit():
    """Editing a registration-relevant field with the SAME op/credentials must
    reconcile — before this hook, PostHog's provider registration silently
    stayed on the old event_name until a config-panel reopen (2026-07-20:
    registered_event_name=auth_button_clicked while config said
    user_signed_up)."""
    from utils.webhook_manager import WebhookManager

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-fake": _FieldsTrigger}),
        patch("nodes.core.webhook_trigger.ExternalWebhookTriggerMixin", object),
        patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
              staticmethod(lambda nt, op: op == "on_custom_event")),
        patch("utils.webhook_manager.WebhookManager.reconcile_node",
              AsyncMock(return_value={"state": "registered"})) as mock_rec,
    ):
        acted = await WebhookManager.handle_registration_fields_change(
            MagicMock(), "automation-fake", WF, NODE,
            {"operation": "on_custom_event", "event_name": "auth_button_clicked"},
            {"operation": "on_custom_event", "event_name": "user_signed_up"},
            user_id="u-1",
        )
    assert acted is True
    assert mock_rec.await_count == 1


async def test_fields_change_hook_noops_when_fields_unchanged():
    from utils.webhook_manager import WebhookManager

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-fake": _FieldsTrigger}),
        patch("nodes.core.webhook_trigger.ExternalWebhookTriggerMixin", object),
        patch("utils.webhook_manager.WebhookManager.reconcile_node",
              AsyncMock()) as mock_rec,
    ):
        acted = await WebhookManager.handle_registration_fields_change(
            MagicMock(), "automation-fake", WF, NODE,
            {"operation": "on_custom_event", "event_name": "same", "unrelated": 1},
            {"operation": "on_custom_event", "event_name": "same", "unrelated": 2},
            user_id="u-1",
        )
    assert acted is False
    mock_rec.assert_not_awaited()


async def test_fields_change_hook_ignores_non_trigger_ops_and_unknown_types():
    from utils.webhook_manager import WebhookManager

    with (
        patch("nodes.core.registry.NODE_REGISTRY", {"automation-fake": _FieldsTrigger}),
        patch("nodes.core.webhook_trigger.ExternalWebhookTriggerMixin", object),
        patch("utils.webhook_manager.WebhookManager.operation_requires_webhook",
              staticmethod(lambda nt, op: False)),
        patch("utils.webhook_manager.WebhookManager.reconcile_node",
              AsyncMock()) as mock_rec,
    ):
        acted = await WebhookManager.handle_registration_fields_change(
            MagicMock(), "automation-fake", WF, NODE,
            {"operation": "capture_event", "event_name": "a"},
            {"operation": "capture_event", "event_name": "b"},
        )
        assert acted is False
        acted = await WebhookManager.handle_registration_fields_change(
            MagicMock(), "not-registered", WF, NODE,
            {"event_name": "a"}, {"event_name": "b"},
        )
        assert acted is False
    mock_rec.assert_not_awaited()
