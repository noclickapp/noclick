"""The nightly trigger resync, over real PostgreSQL with each provider faked at its edge.

A pass used to visit the same oldest workflows every night, so most were never
checked. It now walks a lap of all of them by a durable cursor. And since a healed
trigger can start firing on its owner's money after months of silence, it only
reports until a person has read that report and turned it on: the report comes from
the reconciler's own decisions, writing nothing and calling no provider.
"""
import asyncio
import json
import socket
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from nodes.slack_node import SlackNode
from nodes.stripe_node import StripeNode
from repositories import trigger_resync
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils import cron_scheduler_client, webhook_manager
from utils.encryption import get_encryption
from utils.webhook_manager import WebhookManager, registration_fingerprint

pytestmark = pytest.mark.asyncio

NODE = "trigger"
CRON = "trigger-cron"
STRIPE = "automation-stripe"
SLACK = "automation-slack"
HOURLY = {"schedules": [{"frequency": "hours", "interval": 1}]}
LABEL = "Quarterly invoices for Acme"


@pytest_asyncio.fixture
async def db(real_database):  # noqa: F811
    """The resync's state starts empty, as it does on a fresh install, and leaves no switch on for the next test."""
    await real_database.execute("DELETE FROM trigger_resync_state")
    yield real_database
    await real_database.execute("DELETE FROM trigger_resync_state")


async def _owner(db) -> str:
    owner = str(uuid.uuid4())
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2)", owner, f"{owner}@example.test")
    return owner


async def _workflow(db, owner, nodes, *, edited_days_ago: int = 0) -> str:
    workflow_id = str(uuid.uuid4())
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1, $2, $3, $4::jsonb)",
                     workflow_id, owner, LABEL, {"nodes": nodes, "edges": []})
    if edited_days_ago:
        # The trigger keeps updated_at on a write that changes no content, so age it with the trigger off.
        await db.execute("ALTER TABLE workflows DISABLE TRIGGER update_workflows_updated_at")
        await db.execute("UPDATE workflows SET updated_at = $2 WHERE id = $1", workflow_id,
                         datetime.now(timezone.utc) - timedelta(days=edited_days_ago, hours=1))
        await db.execute("ALTER TABLE workflows ENABLE TRIGGER update_workflows_updated_at")
    return workflow_id


async def _cron_workflows(db, count: int) -> list[str]:
    owner = await _owner(db)
    return [await _workflow(db, owner, [_step(CRON, HOURLY)]) for _ in range(count)]


def _step(node_type, config, node_id=NODE):
    return {"id": node_id, "type": node_type, "config": {"label": LABEL, **config}}


async def _credential(db, owner, kind) -> str:
    return str(await db.fetchval(
        "INSERT INTO credentials (owner_id, credential_type, name, credential) "
        "VALUES ($1, $2, 'Work account', $3) RETURNING id",
        owner, kind, get_encryption().encrypt_credential({"api_key": "sk_test_secret", "access_token": "xoxb-secret"})))


async def _row(db, workflow_id, *, operation, fingerprint=None, active=True, node_id=NODE):
    await db.execute(
        "INSERT INTO webhooks (user_id, workflow_id, node_id, is_active, registered_operation, registered_fingerprint) "
        "SELECT owner_id, id, $2, $3, $4, $5 FROM workflows WHERE id = $1",
        workflow_id, node_id, active, operation, fingerprint)


async def _subscription(db, workflow_id, *, credential_id, event="app_mention", node_id=NODE):
    await db.execute(
        "INSERT INTO webhook_subscriptions (provider, tenant_id, event_type, user_id, workflow_id, node_id, credential_id) "
        "SELECT 'slack', 'T1', $2, owner_id, id, $3, $4 FROM workflows WHERE id = $1",
        workflow_id, event, node_id, credential_id)


async def _everything(db) -> dict:
    """Every row a resync could touch, whole: an unchanged copy means nothing was written."""
    return {
        table: [r["row"] for r in await db.fetch(
            f"SELECT to_jsonb(t)::text AS row FROM {table} t ORDER BY 1")]
        for table in ("workflows", "webhooks", "webhook_subscriptions", "credentials", "trigger_resync_state",
                      "workflow_reconcile_jobs", "workflow_versions")
    }


async def _pass_visits(db, *, limit, budget_s=600.0):
    """One pass that acts, its reconcile faked: the workflows it reached, and its stats."""
    visited = []

    async def visit(pool, workflow_id, node_id, **kwargs):
        visited.append(workflow_id)
        return {"state": "live"}

    with patch.object(WebhookManager, "reconcile_node", visit):
        stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=limit, budget_s=budget_s)
    return visited, stats


# ── The rotation ─────────────────────────────────────────────────────────────


async def test_a_lap_reaches_every_workflow_and_starts_again(db):
    seeded = set(await _cron_workflows(db, 7))
    await trigger_resync.set_registers(db.pool, True)

    laps = [[]]
    for _ in range(100):
        visited, stats = await _pass_visits(db, limit=3)
        assert len(visited) <= 3
        laps[-1] += visited
        if stats["lap_finished"]:
            if len(laps) == 2:
                break
            laps.append([])
    else:
        pytest.fail("no lap ever finished")

    assert seeded <= set(laps[0]), "a lap must reach every workflow"
    assert len(laps[0]) == len(set(laps[0])), "a lap visits each workflow once"
    assert laps[1] == laps[0], "the next lap goes round again in the same order"
    state = await trigger_resync.read_state(db.pool)
    assert state.lap_finished_at is not None and state.after_workflow_id is None


async def test_a_visit_that_edits_a_workflow_doesnt_keep_the_rest_from_their_turn(db):
    """The order the old sweep went by moved with every write, and its cut-off always fell on the same workflows."""
    seeded = set(await _cron_workflows(db, 5))
    await trigger_resync.set_registers(db.pool, True)
    reached = set()

    async def visit_and_write(pool, workflow_id, node_id, **kwargs):
        reached.add(workflow_id)
        await db.execute("UPDATE workflows SET name = name || '!' WHERE id = $1", workflow_id)
        return {"state": "live"}

    with patch.object(WebhookManager, "reconcile_node", visit_and_write):
        for _ in range(100):
            stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=2)
            if stats["lap_finished"]:
                break
    assert seeded <= reached


async def test_a_pass_out_of_time_picks_up_where_it_stopped(db):
    await _cron_workflows(db, 5)
    await trigger_resync.set_registers(db.pool, True)
    clock = iter(range(1000))

    with patch.object(webhook_manager, "monotonic", lambda: next(clock)):
        # The deadline is taken at 0, the first workflow is judged at 1, the second at 2, so 2 seconds is one visit.
        first, stats = await _pass_visits(db, limit=100, budget_s=2)
    assert len(first) == 1 and stats["stopped"] == "out of time" and not stats["lap_finished"]

    rest, stats = await _pass_visits(db, limit=10_000)
    assert stats["lap_finished"]
    all_ids = [str(r["id"]) for r in await trigger_resync.candidates(db.pool, WebhookManager._registerable_types())]
    assert first + rest == all_ids, "nothing is skipped and nothing is visited twice"


async def test_a_pass_with_no_time_left_starts_nothing_and_loses_nothing(db):
    await _cron_workflows(db, 2)
    await trigger_resync.set_registers(db.pool, True)
    visited, stats = await _pass_visits(db, limit=10, budget_s=-1)
    assert visited == [] and stats["stopped"] == "out of time"
    assert (await trigger_resync.read_state(db.pool)).after_workflow_id is None


async def test_a_pass_killed_inside_a_workflow_goes_on_past_it_and_the_next_lap_reaches_it(db):
    """Retrying it first would let one workflow that kills the pass stop the rotation for good."""
    await _cron_workflows(db, 4)
    await trigger_resync.set_registers(db.pool, True)
    all_ids = [str(r["id"]) for r in await trigger_resync.candidates(db.pool, WebhookManager._registerable_types())]
    victim = all_ids[1]
    visited = []

    async def killed_at_victim(pool, workflow_id, node_id, **kwargs):
        visited.append(workflow_id)
        if workflow_id == victim and visited.count(victim) == 1:
            raise asyncio.CancelledError()
        return {"state": "live"}

    with patch.object(WebhookManager, "reconcile_node", killed_at_victim):
        with pytest.raises(asyncio.CancelledError):
            await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
        assert (await trigger_resync.read_state(db.pool)).after_workflow_id == uuid.UUID(victim)

        stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
        assert stats["lap_finished"]
        assert visited == all_ids, "the next pass starts right after it"

        await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
    assert visited.count(victim) == 2, "the next lap reaches it"


async def test_a_step_that_hangs_is_counted_and_the_pass_goes_on(db):
    seeded = await _cron_workflows(db, 3)
    await trigger_resync.set_registers(db.pool, True)
    visited = []

    async def hangs_on_one(pool, workflow_id, node_id, **kwargs):
        visited.append(workflow_id)
        if workflow_id == seeded[0]:
            await asyncio.sleep(60)
        return {"state": "live"}

    with patch.object(WebhookManager, "reconcile_node", hangs_on_one), \
            patch.object(webhook_manager, "RESYNC_NODE_TIMEOUT_S", 0.05):
        stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
    assert stats["failed"] == 1 and stats["lap_finished"]
    assert set(seeded) <= set(visited)


async def test_a_step_that_fails_doesnt_stop_the_pass(db):
    seeded = await _cron_workflows(db, 3)
    await trigger_resync.set_registers(db.pool, True)
    visited = []

    async def fails_on_one(pool, workflow_id, node_id, **kwargs):
        visited.append(workflow_id)
        if workflow_id == seeded[0]:
            raise RuntimeError("provider down")
        return {"state": "live"}

    with patch.object(WebhookManager, "reconcile_node", fails_on_one):
        stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
    assert stats["failed"] == 1 and set(seeded) <= set(visited)


async def test_turning_it_off_stops_a_pass_at_its_next_workflow(db):
    await _cron_workflows(db, 4)
    await trigger_resync.set_registers(db.pool, True)
    visited = []

    async def turned_off_during_the_first(pool, workflow_id, node_id, **kwargs):
        visited.append(workflow_id)
        await trigger_resync.set_registers(db.pool, False)
        return {"state": "live"}

    with patch.object(WebhookManager, "reconcile_node", turned_off_during_the_first):
        stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
    assert len(visited) == 1 and stats["stopped"]


async def test_of_two_passes_at_once_the_one_that_finds_the_lap_moved_stops(db):
    await _cron_workflows(db, 4)
    await trigger_resync.set_registers(db.pool, True)
    visited = []

    async def another_pass_moves_the_lap(pool, workflow_id, node_id, **kwargs):
        visited.append(workflow_id)
        moved = await db.execute("UPDATE trigger_resync_state SET after_workflow_id = $1", uuid.uuid4())
        assert moved == "UPDATE 1"
        return {"state": "live"}

    with patch.object(WebhookManager, "reconcile_node", another_pass_moves_the_lap):
        stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
    assert len(visited) == 1 and stats["stopped"]


# ── The switch and the dry run ───────────────────────────────────────────────


class Provider:
    """Each provider's edge, and everything else a dry run must never reach."""

    def __init__(self):
        self.registered = []
        self.deregistered = []
        self.scheduled = []
        self.unscheduled = []

    def fakes(self):
        provider = self

        async def register_external(cls=None, *, webhook_url, credential, config, node_id):
            provider.registered.append(node_id)
            return {"external_webhook_id": f"we-{uuid.uuid4().hex[:6]}", "signing_secret": "whsec"}

        async def unregister_external(cls=None, *, credential, config, node_id):
            provider.deregistered.append(node_id)

        async def register_and_describe(cls=None, pool=None, *, user_id, workflow_id, node_id, operation,
                                        credential_id, credential, config):
            provider.registered.append(node_id)
            await _subscription(pool, workflow_id, credential_id=credential_id, node_id=node_id)
            return {"trigger_registered": True, "trigger_error": None}

        async def resolve_slack(cls=None, pool=None, user_id=None, credential_ids=None):
            from utils.credential_loader import load_credential

            credential_id = next(iter((credential_ids or {}).values()), None)
            return credential_id, await load_credential(pool, user_id, credential_id)

        async def register_schedules(**kwargs):
            provider.scheduled.append(kwargs["node_id"])
            return {"schedule_ids": ["s1"], "schedule_id": "s1", "next_run": "2026-11-06T00:00:00Z", "is_active": True}

        async def delete_schedules(workflow_id, node_ids, **kwargs):
            provider.unscheduled += list(node_ids)

        async def no_next_run(*args, **kwargs):
            raise AssertionError("a sweep doesn't read the scheduler for a converged step")

        return [
            patch.object(StripeNode, "_register_external_webhook", classmethod(register_external)),
            patch.object(StripeNode, "_unregister_external_webhook", classmethod(unregister_external)),
            patch.object(SlackNode, "register_and_describe", classmethod(register_and_describe)),
            patch.object(SlackNode, "_resolve_trigger_credential", classmethod(resolve_slack)),
            patch.object(cron_scheduler_client, "register_node_schedules", register_schedules),
            patch.object(cron_scheduler_client, "delete_schedules_for_nodes", delete_schedules),
            patch.object(cron_scheduler_client, "get_schedule", no_next_run),
            patch.object(cron_scheduler_client, "is_cron_scheduler_enabled", lambda: True),
            patch("utils.webhook_delivery.get_webhook_url", lambda webhook_id: f"https://hooks.example.test/{webhook_id}"),
        ]


@pytest.fixture
def provider():
    world = Provider()
    fakes = world.fakes()
    for fake in fakes:
        fake.start()
    yield world
    for fake in reversed(fakes):
        fake.stop()


@pytest.fixture
def nothing_leaves(monkeypatch):
    """A dry run reaching anything but its database fails here: a hostname looked up, Redis, a decrypt, a refresh."""
    real = socket.getaddrinfo

    def only_local(host, *args, **kwargs):
        if host not in ("localhost", "127.0.0.1", "::1", None) and host != _db_host():
            raise AssertionError(f"a dry run looked up {host}")
        return real(host, *args, **kwargs)

    def _db_host():
        import os
        from urllib.parse import urlparse

        return urlparse(os.environ.get("POSTGRES_POOLER_URL", "")).hostname

    def refuse(*args, **kwargs):
        raise AssertionError("a dry run reached this")

    monkeypatch.setattr(socket, "getaddrinfo", only_local)
    monkeypatch.setattr("utils.redis_client.get_shared_redis", refuse)
    monkeypatch.setattr(type(get_encryption()), "decrypt_credential", refuse)
    monkeypatch.setattr(StripeNode, "freshen_credential", classmethod(refuse))
    monkeypatch.setattr(SlackNode, "freshen_credential", classmethod(refuse))
    for name in ("_register_single_node", "deregister_node_webhooks", "get_or_create_webhook",
                 "_provision_node_webhook", "persist_registration_state", "merge_node_config_patch",
                 "deactivate_webhook"):
        monkeypatch.setattr(WebhookManager, name, refuse)


async def _a_bit_of_everything(db):
    """A workflow per thing the resync could do to it, and what it would come to."""
    owner = await _owner(db)
    stripe = await _credential(db, owner, "stripe_api")
    slack = await _credential(db, owner, "slack_bot")
    on_stripe = _step(STRIPE, {"operation": "on_event", "credentialIds": {"stripe_api": stripe}})
    on_slack = _step(SLACK, {"operation": "on_app_mention", "credentialIds": {"slack_bot": slack}})
    wf = {
        "cron": await _workflow(db, owner, [_step(CRON, HOURLY)], edited_days_ago=200),
        "stripe": await _workflow(db, owner, [on_stripe], edited_days_ago=40),
        "slack": await _workflow(db, owner, [on_slack], edited_days_ago=3),
        "stale_stripe": await _workflow(db, owner, [on_stripe]),
        "gone": await _workflow(db, owner, [_step(CRON, HOURLY, node_id="something_else")]),
    }
    await _row(db, wf["stale_stripe"], operation="on_event", fingerprint="an-older-fingerprint")
    await _row(db, wf["gone"], operation="on_event", fingerprint="f", node_id="removed_step")
    return wf, owner, stripe, slack


async def test_off_is_the_default_and_a_pass_only_reports(db, provider, nothing_leaves):
    wf, *_ = await _a_bit_of_everything(db)
    before = await _everything(db)

    summary = await WebhookManager.resync_trigger_registrations(db.pool)

    assert summary["registers"] is False and summary["complete"] is True
    assert summary["states"]["would_register"] >= 3
    assert await _everything(db) == before, "off, a pass writes nothing, the lap included"
    assert provider.registered == provider.deregistered == provider.scheduled == provider.unscheduled == []
    # It stays a summary: the list is for a person to ask for.
    assert not set(wf.values()) & set(json.dumps(summary).replace('"', " ").split())


async def test_the_dry_run_writes_nothing_calls_no_provider_and_shows_no_customer_content(db, provider, nothing_leaves):
    wf, _, stripe, slack = await _a_bit_of_everything(db)
    before = await _everything(db)

    plan = await WebhookManager.plan_trigger_resync(db.pool)

    assert await _everything(db) == before
    assert provider.registered == provider.deregistered == provider.scheduled == provider.unscheduled == []

    new = {e["workflow_id"]: e for e in plan["listed"]["would_register"]}
    assert {wf["cron"], wf["stripe"], wf["slack"], wf["gone"]} <= set(new)
    assert (new[wf["cron"]]["type"], new[wf["cron"]]["operation"], new[wf["cron"]]["edited_days_ago"]) == (CRON, None, 200)
    assert (new[wf["stripe"]]["type"], new[wf["stripe"]]["operation"], new[wf["stripe"]]["edited_days_ago"]) == (
        STRIPE, "on_event", 40)
    assert (new[wf["slack"]]["type"], new[wf["slack"]]["operation"], new[wf["slack"]]["edited_days_ago"]) == (
        SLACK, "on_app_mention", 3)
    assert wf["stale_stripe"] in {e["workflow_id"] for e in plan["listed"]["would_reregister"]}
    assert wf["gone"] in {e["workflow_id"] for e in plan["listed"]["would_deregister"]}

    counts = {(c["type"], c["operation"]): c["count"] for c in plan["counts"]["would_register"]}
    assert counts[(STRIPE, "on_event")] >= 1 and counts[(SLACK, "on_app_mention")] >= 1 and counts[(CRON, None)] >= 2

    # Only what was asked for leaves: no name, label, step id, credential or owner.
    shown = json.dumps(plan)
    for private in (LABEL, "removed_step", "something_else", stripe, slack, "secret", "@example.test"):
        assert private not in shown
    assert {key for entries in plan["listed"].values() for e in entries for key in e} == {
        "workflow_id", "edited_days_ago", "type", "operation"}


async def test_an_operation_nobody_defined_is_never_shown(db, provider, nothing_leaves):
    owner = await _owner(db)
    workflow_id = await _workflow(db, owner, [_step(STRIPE, {"operation": "Dear Sam, invoice attached"})])
    await _row(db, workflow_id, operation="on_event", fingerprint="f")

    plan = await WebhookManager.plan_trigger_resync(db.pool)

    assert "Dear Sam" not in json.dumps(plan)
    [entry] = [e for e in plan["listed"]["would_deregister"] if e["workflow_id"] == workflow_id]
    assert entry["operation"] == "(unknown)"


async def test_a_credential_id_that_was_never_saved_is_no_credential(db, provider, nothing_leaves):
    owner = await _owner(db)
    workflow_id = await _workflow(db, owner, [
        _step(STRIPE, {"operation": "on_event", "credentialIds": {"stripe_api": "your-stripe-account"}})])

    result = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, plan_only=True)

    assert result["state"] == "unregistered"


async def test_a_plan_out_of_time_says_so(db, provider, nothing_leaves):
    await _cron_workflows(db, 1)
    plan = await WebhookManager.plan_trigger_resync(db.pool, budget_s=-1)
    assert plan["complete"] is False and plan["checked"] == 0


async def test_turning_it_on_registers_what_the_dry_run_listed(db, provider):
    wf, *_ = await _a_bit_of_everything(db)
    plan = await WebhookManager.plan_trigger_resync(db.pool)
    listed = {e["workflow_id"] for e in plan["listed"]["would_register"]}
    assert (await WebhookManager.resync_trigger_registrations(db.pool))["registers"] is False
    assert provider.registered == provider.scheduled == []

    await trigger_resync.set_registers(db.pool, True)
    stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)

    assert stats["registers"] is True and stats["lap_finished"] and stats["converged"] >= 5
    for key in ("cron", "stripe"):
        row = await db.fetchrow("SELECT is_active, registered_fingerprint FROM webhooks "
                                "WHERE workflow_id = $1 AND node_id = $2", wf[key], NODE)
        assert row["is_active"] and row["registered_fingerprint"]
    assert await db.fetchval("SELECT count(*) FROM webhook_subscriptions WHERE workflow_id = $1", wf["slack"]) == 1
    assert provider.scheduled and NODE in provider.registered
    assert "removed_step" in provider.unscheduled

    after = await WebhookManager.plan_trigger_resync(db.pool)
    assert not listed & {e["workflow_id"] for e in after["listed"].get("would_register", [])}, (
        "what it registered reads as live afterwards")

    await trigger_resync.set_registers(db.pool, False)
    registered = list(provider.registered)
    await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
    assert provider.registered == registered, "off again, it only reports"


async def test_a_sweep_leaves_a_converged_schedule_alone(db, provider):
    """Its next_run mirror would be a write to the workflow, which reads as an edit of it every lap."""
    [workflow_id] = await _cron_workflows(db, 1)
    await trigger_resync.set_registers(db.pool, True)
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, refresh_next_run=False))["state"] == "registered"
    before = await db.fetchrow("SELECT updated_at, graph_version FROM workflows WHERE id = $1", workflow_id)

    await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)  # get_schedule raises if it's read

    assert await db.fetchrow("SELECT updated_at, graph_version FROM workflows WHERE id = $1", workflow_id) == before


# ── What a dry run says is what a real reconcile then does ───────────────────


async def _never_registered(db, owner, node_type, config, **_):
    return await _workflow(db, owner, [_step(node_type, config)])


async def _stale(db, owner, node_type, config, operation, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, config)])
    await _row(db, workflow_id, operation=operation or "__schedule__", fingerprint="an-older-fingerprint")
    return workflow_id


async def _torn_down_row(db, owner, node_type, config, operation, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, config)])
    await _row(db, workflow_id, operation=operation or "__schedule__", fingerprint="an-older-fingerprint", active=False)
    return workflow_id


async def _live_stripe(db, owner, node_type, config, operation, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, config)])
    await _row(db, workflow_id, operation=operation,
               fingerprint=registration_fingerprint(StripeNode, operation, config["credentialIds"]["stripe_api"], config))
    return workflow_id


async def _adoptable(db, owner, node_type, config, operation, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, config)])
    await _row(db, workflow_id, operation=operation, fingerprint=None)
    await db.execute("UPDATE webhooks SET registered_credential_id = $2 WHERE workflow_id = $1",
                     workflow_id, config["credentialIds"]["stripe_api"])
    return workflow_id


async def _moved_off_its_trigger(db, owner, node_type, config, operation, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, {**config, "operation": "create_customer"})])
    await _row(db, workflow_id, operation=operation, fingerprint="f")
    return workflow_id


async def _step_removed(db, owner, node_type, config, operation, **_):
    workflow_id = await _workflow(db, owner, [])
    await _row(db, workflow_id, operation=operation, fingerprint="f")
    return workflow_id


async def _unfinished_setup(db, owner, node_type, config, **_):
    """A trigger whose next step has no account: it can't activate."""
    workflow_id = str(uuid.uuid4())
    graph = {
        "nodes": [_step(node_type, config),
                  _step(STRIPE, {"operation": "create_customer"}, node_id="next")],
        "edges": [{"id": "e", "source": NODE, "target": "next"}],
    }
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1, $2, $3, $4::jsonb)",
                     workflow_id, owner, LABEL, graph)
    return workflow_id


async def _stale_unfinished_setup(db, owner, node_type, config, operation, **_):
    workflow_id = await _unfinished_setup(db, owner, node_type, config)
    await _row(db, workflow_id, operation=operation or "__schedule__", fingerprint="an-older-fingerprint")
    return workflow_id


async def _slack_rows(db, owner, node_type, config, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, config)])
    await _subscription(db, workflow_id, credential_id=config["credentialIds"]["slack_bot"])
    return workflow_id


async def _slack_moved_off(db, owner, node_type, config, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, {**config, "operation": "send_message"})])
    await _subscription(db, workflow_id, credential_id=config["credentialIds"]["slack_bot"])
    return workflow_id


async def _slack_other_event(db, owner, node_type, config, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, config)])
    await _subscription(db, workflow_id, credential_id=config["credentialIds"]["slack_bot"], event="reaction_added")
    return workflow_id


async def _slack_credential_gone(db, owner, node_type, config, **_):
    gone = str(uuid.uuid4())
    workflow_id = await _workflow(db, owner, [_step(node_type, {**config, "credentialIds": {"slack_bot": gone}})])
    return workflow_id


async def _revoked_credential(db, owner, node_type, config, operation, **_):
    await db.execute("UPDATE credentials SET revoked_at = now() WHERE id = $1", config["credentialIds"]["stripe_api"])
    return await _workflow(db, owner, [_step(node_type, config)])


async def _no_credential(db, owner, node_type, config, **_):
    return await _workflow(db, owner, [_step(node_type, {"operation": config["operation"]})])


async def _cron_disabled_with_a_schedule(db, owner, node_type, config, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, {**config, "disabled": True})])
    await _row(db, workflow_id, operation="__schedule__", fingerprint="sched:f")
    return workflow_id


async def _cron_disabled_never_scheduled(db, owner, node_type, config, **_):
    return await _workflow(db, owner, [_step(node_type, {**config, "disabled": True})])


async def _cron_live(db, owner, node_type, config, **_):
    workflow_id = await _workflow(db, owner, [_step(node_type, config)])
    await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, refresh_next_run=False)
    return workflow_id


ON_EVENT = {"operation": "on_event"}
MENTION = {"operation": "on_app_mention"}
SCENARIOS = [
    # build, node type, config, what the dry run says, what the reconcile then does
    (_never_registered, CRON, HOURLY, "would_register", "registered"),
    (_stale, CRON, HOURLY, "would_reregister", "registered"),
    (_torn_down_row, CRON, HOURLY, "would_register", "registered"),
    (_cron_live, CRON, HOURLY, "live", "live"),
    (_cron_disabled_with_a_schedule, CRON, HOURLY, "would_deregister", "deregistered"),
    (_cron_disabled_never_scheduled, CRON, HOURLY, "noop", "noop"),
    (_step_removed, STRIPE, ON_EVENT, "would_deregister", "deregistered"),
    (_unfinished_setup, CRON, HOURLY, "refused", "raises"),
    (_stale_unfinished_setup, CRON, HOURLY, "would_deregister", "raises"),
    (_never_registered, STRIPE, ON_EVENT, "would_register", "registered"),
    (_stale, STRIPE, ON_EVENT, "would_reregister", "registered"),
    (_torn_down_row, STRIPE, ON_EVENT, "would_register", "registered"),
    (_live_stripe, STRIPE, ON_EVENT, "live", "live"),
    (_adoptable, STRIPE, ON_EVENT, "would_adopt", "live"),
    (_moved_off_its_trigger, STRIPE, ON_EVENT, "would_deregister", "deregistered"),
    (_no_credential, STRIPE, ON_EVENT, "unregistered", "unregistered"),
    (_revoked_credential, STRIPE, ON_EVENT, "unregistered", "unregistered"),
    (_unfinished_setup, STRIPE, ON_EVENT, "refused", "raises"),
    (_stale_unfinished_setup, STRIPE, ON_EVENT, "would_deregister", "raises"),
    (_never_registered, SLACK, MENTION, "would_register", "registered"),
    (_slack_rows, SLACK, MENTION, "live", "live"),
    (_slack_moved_off, SLACK, MENTION, "would_deregister", "deregistered"),
    (_slack_other_event, SLACK, MENTION, "would_reregister", "registered"),
    (_slack_credential_gone, SLACK, MENTION, "unregistered", "unregistered"),
    (_no_credential, SLACK, MENTION, "unregistered", "unregistered"),
]


@pytest.mark.parametrize("build,node_type,config,says,does", SCENARIOS,
                         ids=[f"{s[0].__name__}-{s[1]}" for s in SCENARIOS])
async def test_the_dry_run_says_what_the_reconcile_then_does(db, provider, build, node_type, config, says, does):
    from utils.workflow_readiness import WorkflowNotReadyError

    owner = await _owner(db)
    config = dict(config)
    if node_type == STRIPE:
        config["credentialIds"] = {"stripe_api": await _credential(db, owner, "stripe_api")}
    elif node_type == SLACK:
        config["credentialIds"] = {"slack_bot": await _credential(db, owner, "slack_bot")}
    workflow_id = await build(db, owner, node_type, config, operation=config.get("operation"))
    provider.__init__()
    before = await _everything(db)

    planned = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, plan_only=True)

    assert planned["state"] == says
    assert await _everything(db) == before
    assert provider.registered == provider.deregistered == provider.scheduled == provider.unscheduled == []

    if does == "raises":
        with pytest.raises(WorkflowNotReadyError):
            await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, refresh_next_run=False)
    else:
        done = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, refresh_next_run=False)
        assert done["state"] == does
        assert bool(done.get("adopted")) == (says == "would_adopt")
    acted = bool(provider.registered or provider.scheduled)
    assert acted == (says in ("would_register", "would_reregister"))
    tore_down = bool(provider.deregistered or provider.unscheduled)
    if says == "would_deregister" and node_type != SLACK:
        assert tore_down


# ── Nothing is torn down on a signal that says nothing ───────────────────────


@pytest.mark.parametrize("plan_only", [True, False], ids=["dry run", "reconcile"])
async def test_a_webhook_on_a_node_that_also_polls_isnt_taken_for_a_schedule(db, provider, plan_only):
    """Such a node goes to the schedule family's arm whatever its operation, which saw no schedule and deactivated
    the webhook's row: the trigger went deaf, with its endpoint still registered at the provider."""
    owner = await _owner(db)
    workflow_id = await _workflow(db, owner, [_step("automation-cloudflare", {"operation": "cloudflare_alert"})])
    await _row(db, workflow_id, operation="cloudflare_alert", fingerprint="f")

    result = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, plan_only=plan_only)

    assert result["state"] == "noop"
    assert await db.fetchval("SELECT is_active FROM webhooks WHERE workflow_id = $1", workflow_id) is True
    assert provider.unscheduled == provider.deregistered == []


@pytest.mark.parametrize("blob", [{}, {"edges": []}, {"nodes": "not a list"}], ids=str)
async def test_a_workflow_with_no_list_of_steps_loses_nothing(db, provider, blob):
    owner = await _owner(db)
    workflow_id = str(uuid.uuid4())
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1, $2, 'x', $3::jsonb)",
                     workflow_id, owner, blob)
    row_step = f"step-{workflow_id}"
    await _row(db, workflow_id, operation="on_event", fingerprint="f", node_id=row_step)

    plan = await WebhookManager.plan_trigger_resync(db.pool)
    assert plan["no_graph"] >= 1

    await trigger_resync.set_registers(db.pool, True)
    stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)

    assert stats["no_graph"] >= 1
    assert await db.fetchval("SELECT is_active FROM webhooks WHERE workflow_id = $1", workflow_id) is True
    assert row_step not in provider.deregistered + provider.unscheduled


async def test_a_workflow_it_cant_read_loses_nothing(db, provider):
    owner = await _owner(db)
    workflow_id = await _workflow(db, owner, [_step(CRON, HOURLY)])
    await _row(db, workflow_id, operation="__schedule__", fingerprint="sched:f")
    await trigger_resync.set_registers(db.pool, True)

    with patch.object(webhook_manager, "_load_workflow_owner_and_nodes", AsyncMock(side_effect=OSError("db blip"))):
        stats = await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
        plan = await WebhookManager.plan_trigger_resync(db.pool)

    assert stats["failed"] >= 1 and plan["states"]["failed"] >= 1
    assert plan["listed"]["failed"][0]["error"] == "OSError"
    assert await db.fetchval("SELECT is_active FROM webhooks WHERE workflow_id = $1", workflow_id) is True
    assert provider.deregistered == provider.unscheduled == provider.registered == provider.scheduled == []


async def test_a_credential_it_cant_reach_keeps_a_subscription_live(db, provider):
    """Fan-out doesn't need the credential, so an app-event trigger's rows outlive its credential's trouble."""
    owner = await _owner(db)
    credential_id = await _credential(db, owner, "slack_bot")
    workflow_id = await _workflow(db, owner, [
        _step(SLACK, {"operation": "on_app_mention", "credentialIds": {"slack_bot": credential_id}})])
    await _subscription(db, workflow_id, credential_id=credential_id, event="reaction_added")
    await db.execute("UPDATE credentials SET revoked_at = now() WHERE id = $1", credential_id)
    await trigger_resync.set_registers(db.pool, True)

    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, plan_only=True))["state"] == "unregistered"
    await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)

    assert await db.fetchval("SELECT count(*) FROM webhook_subscriptions WHERE workflow_id = $1", workflow_id) == 1


async def test_a_scheduler_not_configured_here_tears_nothing_down_and_says_it_cant_judge(db, provider):
    owner = await _owner(db)
    never = await _workflow(db, owner, [_step(CRON, HOURLY)])
    unrunnable = await _workflow(db, owner, [_step(CRON, {"schedules": []})])
    await _row(db, unrunnable, operation="__schedule__", fingerprint="sched:f")

    with patch.object(cron_scheduler_client, "is_cron_scheduler_enabled", lambda: False):
        plan = await WebhookManager.plan_trigger_resync(db.pool)
        assert {never, unrunnable} <= {e["workflow_id"] for e in plan["listed"]["cannot_judge"]}
        result = await WebhookManager.reconcile_node(db.pool, unrunnable, NODE, refresh_next_run=False)

    assert result["state"] == "noop"
    assert await db.fetchval("SELECT is_active FROM webhooks WHERE workflow_id = $1", unrunnable) is True
    assert provider.unscheduled == []


# ── The table ────────────────────────────────────────────────────────────────


async def test_the_state_is_backend_only(db):
    assert await db.fetchval(
        "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.trigger_resync_state'::regclass") is True
    assert await db.fetchval(
        "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = 'trigger_resync_state'") == 0
    for role in ("anon", "authenticated"):
        assert await db.fetchval(
            "SELECT has_table_privilege($1, 'public.trigger_resync_state', 'SELECT')", role) is False


async def test_there_is_one_state_row(db):
    await trigger_resync.set_registers(db.pool, True)
    await trigger_resync.set_registers(db.pool, False)
    await trigger_resync.set_registers(db.pool, True)
    assert await db.fetchval("SELECT count(*) FROM trigger_resync_state") == 1
    state = await trigger_resync.read_state(db.pool)
    assert state.registers is True and state.registers_set_at is not None
