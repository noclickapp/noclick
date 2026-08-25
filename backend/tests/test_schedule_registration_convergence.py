"""Cron-schedule trigger registration convergence (the FOURTH family).

Poll triggers, the cron node, and the bespoke schedule pollers register
Cloudflare cron schedules. Registration must be covered by EVERY lifecycle
surface the other families have: the shared family loader (panel + headless
provisioning), the level-triggered reconciler (operation/credential/config
change, restores), and the graph-driven nightly sweep. The 2026-08-04
incident class: per-surface "which changes matter" candidate lists kept
missing the write that completed a trigger's config, so schedules armed only
when a user happened to open the panel.

Drives the REAL family arm (_reconcile_schedule_node) + node specs against
mocked chokepoints (register_node_schedules internals, WebhookManager row
persistence). The register chokepoint's own idempotency semantics are pinned
in test_cron_scheduler_client.py.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.webhook_manager import WebhookManager

pytestmark = pytest.mark.asyncio

OWNER = str(uuid.uuid4())
WF = str(uuid.uuid4())
NODE = "form-trigger"

COMPLETE_FORMS_CONFIG = {
    "operation": "on_form_response",
    "form_id": "form-abc",
    "schedule": {"interval": "1", "frequency": "minutes"},
    "credentialIds": {"google_forms_oauth": "cred-1"},
}
INCOMPLETE_FORMS_CONFIG = {
    "operation": "on_form_response",
    "schedule": {"interval": "1", "frequency": "minutes"},
}


def _fake_pool(row=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="UPDATE 1")
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool


class World:
    """Records every side effect of a reconcile pass."""

    def __init__(self):
        self.registered = []      # register_node_schedules kwargs
        self.pruned = []          # delete_schedules_for_nodes args
        self.persisted = []       # persist_registration_state kwargs
        self.deactivated = []
        self.patches = []         # merge_node_config_patch payloads
        self.armed = []           # arm spawn names


async def _reconcile(
    node_type,
    config,
    *,
    row=None,
    register_active=True,
    scheduler_enabled=True,
    node_present=True,
):
    world = World()

    async def fake_register(**kwargs):
        world.registered.append(kwargs)
        if not kwargs["cron_expressions"] or not register_active:
            return {"schedule_ids": [], "schedule_id": None,
                    "next_run": None, "is_active": False}
        return {"schedule_ids": ["s1"], "schedule_id": "s1",
                "next_run": "2026-08-05T00:01:00Z", "is_active": True}

    async def fake_prune(wf, node_ids, **kwargs):
        world.pruned.append((wf, tuple(node_ids)))

    async def fake_persist(pool, webhook_id, **kwargs):
        world.persisted.append({"webhook_id": webhook_id, **kwargs})

    async def fake_deactivate(pool, wf, node_id, **kwargs):
        world.deactivated.append((str(wf), node_id))

    async def fake_patch(pool, wf, node_id, patch_payload):
        world.patches.append(patch_payload)

    node = {"id": NODE, "type": node_type, "config": dict(config)} if node_present else None
    nodes = [node] if node else []

    async def load_owner_nodes(pool, wf_uuid, include_nodes=True):
        return OWNER, nodes

    webhook = {
        "webhook_id": "wh-1", "webhook_url": "https://wh-1.hooks.example.test",
        "relay_connected": True, "is_production": True,
    }

    def fake_spawn(coro, name=None):
        world.armed.append(name)
        coro.close()

    with (
        patch("utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes),
        patch("utils.cron_scheduler_client.register_node_schedules", fake_register),
        patch("utils.cron_scheduler_client.delete_schedules_for_nodes", fake_prune),
        patch("utils.cron_scheduler_client.is_cron_scheduler_enabled",
              return_value=scheduler_enabled),
        patch.object(WebhookManager, "get_or_create_webhook",
                     AsyncMock(return_value=webhook)),
        patch.object(WebhookManager, "persist_registration_state", fake_persist),
        patch.object(WebhookManager, "deactivate_webhook", fake_deactivate),
        patch.object(WebhookManager, "merge_node_config_patch", fake_patch),
        patch("utils.async_helpers.spawn", side_effect=fake_spawn),
        patch("utils.redis_client.get_shared_redis", lambda: None),
    ):
        result = await WebhookManager.reconcile_node(_fake_pool(row), WF, NODE)
    return result, world


def _row(fingerprint=None, registered_operation="on_form_response", is_active=True):
    return {
        "id": uuid.uuid4(), "is_active": is_active,
        "registered_operation": registered_operation,
        "registered_fingerprint": fingerprint,
    }


# ─── the convergence matrix ──────────────────────────────────────────────────


async def test_never_registered_trigger_registers_and_arms():
    """The incident class: desired state exists in the graph, no row — any
    reconcile surface must register AND arm the baseline."""
    result, world = await _reconcile("automation-google-forms", COMPLETE_FORMS_CONFIG)
    assert result["state"] == "registered"
    assert world.registered[0]["cron_expressions"] == ["*/1 * * * *"]
    assert world.registered[0]["user_id"] == OWNER  # fires/bills as owner
    assert world.persisted[0]["registered_fingerprint"] == result["fingerprint"]
    assert world.persisted[0]["registered_operation"] == "on_form_response"
    assert world.armed == [f"schedule-arm:{NODE}"]
    assert result["values"]["trigger_registered"] is True
    assert result["values"]["next_run"] == "2026-08-05T00:01:00Z"
    # Mirrors merged into the saved blob so every surface reads fresh state.
    assert world.patches and world.patches[0]["trigger_registered"] is True


async def test_matching_fingerprint_is_live_with_zero_cloudflare_calls():
    first, _ = await _reconcile("automation-google-forms", COMPLETE_FORMS_CONFIG)
    result, world = await _reconcile(
        "automation-google-forms", COMPLETE_FORMS_CONFIG,
        row=_row(fingerprint=first["fingerprint"]),
    )
    assert result["state"] == "live"
    assert world.registered == [] and world.pruned == [] and world.armed == []


async def test_schedule_edit_rotates_and_reregisters():
    first, _ = await _reconcile("automation-google-forms", COMPLETE_FORMS_CONFIG)
    edited = {**COMPLETE_FORMS_CONFIG, "schedule": {"interval": "30", "frequency": "minutes"}}
    result, world = await _reconcile(
        "automation-google-forms", edited, row=_row(fingerprint=first["fingerprint"]),
    )
    assert result["state"] == "registered"
    assert world.registered[0]["cron_expressions"] == ["*/30 * * * *"]
    assert result["fingerprint"] != first["fingerprint"]


async def test_repoint_rotates_fingerprint_and_rearms_baseline():
    """form_id → different form: the poll scope shifts the fingerprint, so
    the reconciler re-registers (same schedule) and re-arms — the arm hook
    establishes a fresh baseline for the new resource."""
    first, _ = await _reconcile("automation-google-forms", COMPLETE_FORMS_CONFIG)
    repointed = {**COMPLETE_FORMS_CONFIG, "form_id": "form-OTHER"}
    result, world = await _reconcile(
        "automation-google-forms", repointed, row=_row(fingerprint=first["fingerprint"]),
    )
    assert result["state"] == "registered"
    assert result["fingerprint"] != first["fingerprint"]
    assert world.armed == [f"schedule-arm:{NODE}"]


async def test_credential_attach_rotates_fingerprint_and_arms():
    """Registration is credential-free but ARMING is not: a credential
    attached after registration must rotate the fingerprint so the reconcile
    re-registers (harmless idempotent upsert) and finally runs the arm hook —
    without this, the baseline never established until the first tick and the
    arm-timing gap reopened one layer deeper."""
    credless = {k: v for k, v in COMPLETE_FORMS_CONFIG.items() if k != "credentialIds"}
    first, world = await _reconcile("automation-google-forms", credless)
    assert first["state"] == "registered"
    # Arm hook still spawns (and fails quietly downstream without a credential).
    result, world = await _reconcile(
        "automation-google-forms", COMPLETE_FORMS_CONFIG,
        row=_row(fingerprint=first["fingerprint"]),
    )
    assert result["state"] == "registered"
    assert result["fingerprint"] != first["fingerprint"]
    assert world.armed == [f"schedule-arm:{NODE}"]


async def test_credential_change_is_a_registration_field():
    """The save-diff hook must see credential changes for family nodes."""
    from nodes.google_forms_node import GoogleFormsNode

    old = GoogleFormsNode.registration_fingerprint_fields(COMPLETE_FORMS_CONFIG)
    new = GoogleFormsNode.registration_fingerprint_fields(
        {**COMPLETE_FORMS_CONFIG, "credentialIds": {"google_forms_oauth": "cred-2"}}
    )
    assert old["credential"] == "cred-1"
    assert new["credential"] == "cred-2"
    assert old != new


async def test_builder_metadata_churn_stays_live():
    """Canvas metadata (goal/label/…) must not shift the fingerprint — the
    scope hashes the PARSED op config (the poll_scope allowlist fix)."""
    first, _ = await _reconcile("automation-google-forms", COMPLETE_FORMS_CONFIG)
    churned = {**COMPLETE_FORMS_CONFIG, "goal": "changed", "label": "Renamed",
               "operationReason": "x", "userFields": ["form_id"]}
    result, world = await _reconcile(
        "automation-google-forms", churned, row=_row(fingerprint=first["fingerprint"]),
    )
    assert result["state"] == "live"
    assert world.registered == []


async def test_incomplete_config_converges_to_no_schedules_with_reason():
    """The validity gate: a config that can't run arms nothing; the reason is
    mirrored so panel/brain see why. A previously-registered row deactivates."""
    result, world = await _reconcile(
        "automation-google-forms", INCOMPLETE_FORMS_CONFIG, row=_row(),
    )
    assert result["state"] == "deregistered"
    assert world.pruned == [(WF, (NODE,))]
    assert world.deactivated == [(WF, NODE)]
    assert "form_id" in (result["values"]["trigger_error"] or "")
    assert result["values"]["trigger_registered"] is False


async def test_operation_change_away_deregisters():
    config = {"operation": "list_forms", "form_id": "form-abc",
              "schedule_id": "s1", "trigger_registered": True}
    result, world = await _reconcile("automation-google-forms", config, row=_row())
    assert result["state"] == "deregistered"
    assert world.pruned == [(WF, (NODE,))]


async def test_never_registered_action_node_is_noop():
    """Sweep economy: an action-op node with no row and no schedule mirrors
    must cost zero Cloudflare calls."""
    result, world = await _reconcile(
        "automation-google-forms", {"operation": "list_forms"},
    )
    assert result["state"] == "noop"
    assert world.pruned == [] and world.registered == []


async def test_scheduler_disabled_never_tears_down():
    """Local dev without the CF scheduler: can't judge — never prune."""
    result, world = await _reconcile(
        "automation-google-forms", COMPLETE_FORMS_CONFIG,
        row=_row(fingerprint="sched:stale"), scheduler_enabled=False,
    )
    assert result["state"] == "noop"
    assert world.pruned == [] and world.registered == []


async def test_legacy_null_fingerprint_row_converges_by_idempotent_upsert():
    """Pre-family rows have no fingerprint: converge via the chokepoint's
    deterministic-id upsert (no rotation hazard) and stamp."""
    result, world = await _reconcile(
        "automation-google-forms", COMPLETE_FORMS_CONFIG,
        row=_row(fingerprint=None, registered_operation=None),
    )
    assert result["state"] == "registered"
    assert world.persisted[0]["registered_fingerprint"] == result["fingerprint"]


async def test_registration_failure_mirrors_error():
    result, world = await _reconcile(
        "automation-google-forms", COMPLETE_FORMS_CONFIG, register_active=False,
    )
    assert result["state"] == "failed"
    assert result["values"]["trigger_registered"] is False
    assert world.armed == []  # never arm an unregistered trigger


async def test_removed_node_prunes_orphan_schedules():
    """Node left the saved graph: schedules must not tick a missing node
    forever (a deactivated row 410s deliveries without ever reaching the
    tick-time orphan cleanup)."""
    result, world = await _reconcile(
        "automation-google-forms", {}, node_present=False,
    )
    assert world.pruned and world.pruned[0] == (WF, (NODE,))


async def test_cron_node_multi_schedule_spec():
    config = {
        "schedules": [
            {"frequency": "minutes", "interval": 5},
            {"frequency": "hours", "interval": 1},
        ],
        "timezone": "UTC",
    }
    result, world = await _reconcile("trigger-cron", config)
    assert result["state"] == "registered"
    assert world.registered[0]["cron_expressions"] == ["*/5 * * * *", "0 */1 * * *"]
    assert result["values"]["schedule_ids"] == ["s1"]


async def test_cron_node_empty_schedules_disables():
    """Explicitly empty schedules list = cron disabled → converge to none."""
    first, _ = await _reconcile("trigger-cron", {"schedules": [{"frequency": "hours", "interval": 1}]})
    result, world = await _reconcile(
        "trigger-cron", {"schedules": [], "schedule_id": "s1"},
        row=_row(fingerprint=first["fingerprint"], registered_operation="__schedule__"),
    )
    assert result["state"] == "deregistered"
    assert world.pruned == [(WF, (NODE,))]


async def test_bespoke_poller_registers_via_family(  ):
    """Gmail — a bespoke poller with no schema webhook marker — must converge
    through the same family arm."""
    config = {"operation": "poll_for_new_emails",
              "schedule": {"frequency": "minutes", "interval": 5}}
    result, world = await _reconcile("automation-gmail", config)
    assert result["state"] == "registered"
    assert world.registered[0]["cron_expressions"] == ["*/5 * * * *"]


# ─── time windows + timezone-aware registration ──────────────────────────────


WINDOWED_CRON_CONFIG = {
    "schedules": [{
        "frequency": "minutes", "interval": 30,
        "windowStart": "09:00", "windowEnd": "18:00",
        "daysOfWeek": [1, 2, 3, 4, 5],
    }],
    "timezone": "America/New_York",
}


async def test_windowed_schedule_registers_local_expressions_with_tz():
    """The customer ask: every 30 min, 9:00 AM–6:00 PM New York, Mon–Fri.
    Compiles to LOCAL-time expressions (the endpoint as its own slot) that the
    scheduler evaluates in the registration's timezone."""
    result, world = await _reconcile("trigger-cron", WINDOWED_CRON_CONFIG)
    assert result["state"] == "registered"
    assert world.registered[0]["cron_expressions"] == [
        "*/30 9-17 * * 1-5", "0 18 * * 1-5",
    ]
    assert world.registered[0]["timezone"] == "America/New_York"


async def test_window_edit_rotates_fingerprint_and_reregisters():
    first, _ = await _reconcile("trigger-cron", WINDOWED_CRON_CONFIG)
    edited = {
        **WINDOWED_CRON_CONFIG,
        "schedules": [{**WINDOWED_CRON_CONFIG["schedules"][0], "windowEnd": "17:00"}],
    }
    result, world = await _reconcile(
        "trigger-cron", edited,
        row=_row(fingerprint=first["fingerprint"], registered_operation="__schedule__"),
    )
    assert result["state"] == "registered"
    assert result["fingerprint"] != first["fingerprint"]
    assert world.registered[0]["cron_expressions"] == [
        "*/30 9-16 * * 1-5", "0 17 * * 1-5",
    ]


async def test_unrunnable_window_converges_to_no_schedules_with_reason():
    """A window on a daily schedule can't run — the node converges to NO
    schedules with the reason mirrored, never a partial registration."""
    config = {
        "schedules": [{"frequency": "day", "hour": 9, "minute": 0,
                       "windowStart": "09:00", "windowEnd": "18:00"}],
        "timezone": "UTC",
        "schedule_id": "stale",
    }
    result, world = await _reconcile("trigger-cron", config)
    assert result["state"] == "deregistered"
    assert world.registered == []
    assert "part-of-day window" in result["values"]["trigger_error"]


async def test_day_schedule_emits_local_time_for_tz_evaluation():
    """Absolute-time schedules are no longer offset-converted here: the
    expression stays local wall-clock and the timezone rides the registration
    — which is what keeps 9:30 New York correct across DST."""
    config = {
        "schedules": [{"frequency": "day", "hour": 9, "minute": 30}],
        "timezone": "America/New_York",
    }
    result, world = await _reconcile("trigger-cron", config)
    assert result["state"] == "registered"
    assert world.registered[0]["cron_expressions"] == ["30 9 * * *"]
    assert world.registered[0]["timezone"] == "America/New_York"


async def test_poll_family_spec_passes_config_timezone():
    """The family default spec forwards a node's timezone config so poll
    windows can be zone-correct too (UTC when the node has no such field)."""
    config = {"operation": "poll_for_new_emails",
              "schedule": {"frequency": "minutes", "interval": 5,
                           "windowStart": "09:00", "windowEnd": "17:00"},
              "timezone": "Asia/Kolkata"}
    result, world = await _reconcile("automation-gmail", config)
    assert result["state"] == "registered"
    assert world.registered[0]["cron_expressions"] == ["*/5 9-16 * * *", "0 17 * * *"]
    assert world.registered[0]["timezone"] == "Asia/Kolkata"


# ─── lifecycle surface routing ───────────────────────────────────────────────


async def test_register_node_webhooks_routes_family_to_reconciler():
    """Trash/checkpoint restore + canvas undo route here; schedule nodes
    re-register via the reconciler (desired state from the graph)."""
    node = {"id": NODE, "type": "automation-google-forms",
            "config": dict(COMPLETE_FORMS_CONFIG)}

    async def load_owner_nodes(p, wf_uuid, include_nodes=True):
        return OWNER, [node]

    pool = _fake_pool()
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


def test_operation_requires_registration_covers_family():
    """Mutation hooks + the sweep gate on this — bespoke pollers carry no
    schema webhook marker and the cron node has no operation, so the family
    check must cover them."""
    assert WebhookManager.operation_requires_registration(
        "automation-gmail", "poll_for_new_emails"
    )
    assert WebhookManager.operation_requires_registration("trigger-cron", None)
    assert WebhookManager.operation_requires_registration(
        "automation-google-forms", "on_form_response"
    )
    assert not WebhookManager.operation_requires_registration(
        "automation-gmail", "send_email_message"
    )


async def test_registration_fields_change_reconciles_schedule_family():
    """The panel-save diff hook: a config edit that changes the schedule or
    the watched resource must reconcile — THIS is what makes plain config
    saves a registration surface (no more per-surface candidate lists)."""
    old = dict(COMPLETE_FORMS_CONFIG)
    new = {**COMPLETE_FORMS_CONFIG, "form_id": "form-OTHER"}
    with patch.object(
        WebhookManager, "reconcile_node",
        AsyncMock(return_value={"state": "registered"}),
    ) as rec:
        acted = await WebhookManager.handle_registration_fields_change(
            _fake_pool(), "automation-google-forms", WF, NODE, old, new,
            user_id=OWNER,
        )
    assert acted is True
    rec.assert_awaited_once()


async def test_registration_fields_change_ignores_cosmetic_edits():
    old = dict(COMPLETE_FORMS_CONFIG)
    new = {**COMPLETE_FORMS_CONFIG, "goal": "different goal", "label": "Renamed"}
    with patch.object(
        WebhookManager, "reconcile_node", AsyncMock()
    ) as rec:
        acted = await WebhookManager.handle_registration_fields_change(
            _fake_pool(), "automation-google-forms", WF, NODE, old, new,
            user_id=OWNER,
        )
    assert acted is False
    rec.assert_not_awaited()


def test_sweep_walks_schedule_family_types():
    """The nightly graph-driven sweep must include family members, so a
    registration that NEVER happened heals within a day."""
    import inspect

    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.schedule_registration import CronScheduleTriggerMixin

    src = inspect.getsource(WebhookManager.resync_trigger_registrations)
    assert "CronScheduleTriggerMixin" in src
    members = [t for t, c in NODE_REGISTRY.items()
               if isinstance(c, type) and issubclass(c, CronScheduleTriggerMixin)]
    assert len(members) >= 16  # 10 poll-mixin + 5 bespoke + trigger-cron




# ─── registry-wide enforcement ───────────────────────────────────────────────


def test_every_poll_trigger_op_is_a_family_member():
    """A schedule-registering trigger op outside the family ships dead from
    every lifecycle surface. Every operation whose config subclasses
    PollTriggerConfigBase — and every declared bespoke schedule op — must
    live on a CronScheduleTriggerMixin class and be recognized by both the
    provisioning pre-filter and the family's own operation check."""
    import typing

    from nodes.core.poll_trigger import PollTriggerConfigBase
    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.schedule_registration import (
        CronScheduleTriggerMixin,
        operation_config_class,
    )

    checked = 0
    problems = []
    for node_type in sorted(NODE_REGISTRY):
        node_class = NODE_REGISTRY[node_type]
        if not isinstance(node_class, type):
            continue
        model = node_class.get_config_model()
        if model is None:
            continue
        config_field = getattr(model, "model_fields", {}).get("config")
        annotation = config_field.annotation if config_field is not None else model
        while typing.get_origin(annotation) is not None and typing.get_origin(
            annotation
        ) is not typing.Union:
            args = typing.get_args(annotation)
            if not args:
                break
            annotation = args[0]
        members = (
            typing.get_args(annotation)
            if typing.get_origin(annotation) is typing.Union
            else (annotation,)
        )
        ops = []
        for member in members:
            if (isinstance(member, type) and issubclass(member, PollTriggerConfigBase)):
                op_field = member.model_fields.get("operation")
                if op_field is not None and isinstance(op_field.default, str):
                    ops.append(op_field.default)
        if issubclass(node_class, CronScheduleTriggerMixin):
            ops.extend(node_class.schedule_trigger_operations)
        for op in ops:
            checked += 1
            if not issubclass(node_class, CronScheduleTriggerMixin):
                problems.append((node_type, op, "not a family member"))
                continue
            if not node_class._is_schedule_operation(op):
                problems.append((node_type, op, "_is_schedule_operation False"))
            if not WebhookManager.node_webhook_field_for(node_type, op):
                problems.append((node_type, op, "invisible to provisioning pre-filter"))
            if operation_config_class(node_class, op) is None and op not in getattr(
                node_class, "schedule_trigger_operations", ()
            ):
                problems.append((node_type, op, "operation class unresolvable"))
    assert checked >= 16, f"suspiciously few schedule trigger ops found: {checked}"
    assert not problems, (
        "Schedule-trigger operations outside the registration family — they "
        f"ship dead from headless surfaces: {problems}"
    )
