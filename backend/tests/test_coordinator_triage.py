"""The coordinator hears about failures and agent messages without being
flooded (coder/coordinator/signals.py), and can look at runs, pause a
workflow and resume exactly what it paused — against real Postgres."""

import uuid
import asyncio
from unittest.mock import AsyncMock

import pytest

from coder.coordinator import signals
from coder.coordinator.signals import record_agent_message, record_run_failure
from coder.coordinator.tools import CoordinatorTools

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def account(postgres_db, postgres_container, monkeypatch):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=4, init=setup_asyncpg_codecs,
    )
    user_id = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:8]}@example.com"))
    dispatched = []
    monkeypatch.setattr("utils.coordinator_dispatch.dispatch_event", AsyncMock(side_effect=lambda p, e: dispatched.append(e)))

    async def workflow(name="Digest", nodes=None):
        return str(await pool.fetchval(
            "INSERT INTO workflows (owner_id, name, workflow) VALUES ($1::uuid, $2, $3) RETURNING id",
            user_id, name, {"nodes": nodes or [], "edges": []}))
    try:
        yield pool, user_id, workflow, dispatched
    finally:
        await pool.close()


async def test_one_workflows_failures_fold_into_one_wakeup(account):
    pool, user_id, workflow, dispatched = account
    wf = await workflow()
    first = await record_run_failure(pool, workflow_id=wf, execution_id=str(uuid.uuid4()), error="Slack 401",
                                     trigger_source="cron", node_label="Post summary")
    assert first == "woke" and len(dispatched) == 1
    wake = await pool.fetchrow("SELECT source, context, payload, send_to_phone FROM coordinator_wakeups WHERE id = $1",
                               dispatched[0]["id"])
    assert wake["source"] == "signal" and wake["send_to_phone"] is False and wake["context"]["channel"] == "web"
    assert wake["payload"]["kind"] == "run_failure" and wake["payload"]["error"] == "Slack 401"
    assert wake["payload"]["workflow_name"] == "Digest" and wake["payload"]["node_label"] == "Post summary"

    for _ in range(3):  # a high-frequency workflow keeps failing
        assert await record_run_failure(pool, workflow_id=wf, execution_id=str(uuid.uuid4()),
                                        error="Slack 401 again", trigger_source="cron") == "folded"
    row = await pool.fetchrow("SELECT repeats, payload FROM coordinator_signals WHERE workflow_id = $1::uuid", wf)
    assert row["repeats"] == 3 and row["payload"]["last_error"] == "Slack 401 again"
    assert len(dispatched) == 1


async def test_credit_exhaustion_never_wakes_it(account):
    pool, user_id, workflow, dispatched = account
    wf = await workflow()
    assert await record_run_failure(pool, workflow_id=wf, execution_id=None, trigger_source="cron",
                                    error="Insufficient credits: 0.00 < 0.20 required") == "credits"
    assert dispatched == []


async def test_an_account_is_woken_a_capped_number_of_times_a_day(account):
    pool, user_id, workflow, dispatched = account
    outcomes = [await record_run_failure(pool, workflow_id=await workflow(f"W{i}"), execution_id=None,
                                         error="boom", trigger_source="webhook")
                for i in range(signals.DAILY_FAILURE_WAKEUPS + 2)]
    assert outcomes.count("woke") == signals.DAILY_FAILURE_WAKEUPS and outcomes[-2:] == ["capped", "capped"]
    assert len(dispatched) == signals.DAILY_FAILURE_WAKEUPS
    # A capped failure is still on record for the coordinator to find.
    assert await pool.fetchval("SELECT count(*) FROM coordinator_signals WHERE user_id = $1::uuid AND NOT woke", user_id) == 2


async def test_an_agent_can_message_the_coordinator_a_few_times_a_day(account):
    pool, user_id, workflow, dispatched = account
    wf = await workflow("Support inbox")
    for _ in range(signals.AGENT_MESSAGES_PER_NODE_DAILY):
        out = await record_agent_message(pool, user_id=user_id, workflow_id=wf, node_id="agent-1",
                                         message="The CRM credential was revoked; I can't log tickets.")
        assert out["success"] is True
    refused = await record_agent_message(pool, user_id=user_id, workflow_id=wf, node_id="agent-1", message="again")
    assert refused["success"] is False and "as often as allowed" in refused["error"]
    assert (await record_agent_message(pool, user_id=user_id, workflow_id=wf, node_id="agent-1", message=" "))["success"] is False
    payload = (await pool.fetchrow("SELECT payload FROM coordinator_wakeups WHERE id = $1", dispatched[0]["id"]))["payload"]
    assert payload["kind"] == "agent_message" and payload["workflow_name"] == "Support inbox"
    assert "revoked" in payload["message"]


async def test_a_signal_wakeup_opens_with_triage_instructions():
    failure = signals.describe({"payload": {"kind": "run_failure"}})
    assert "pause_workflow" in failure and "submit_feedback" in failure and "message_owner" in failure
    assert "memory" in failure  # an owner's opt-out is a memory, honored on waking
    assert "request_build" in signals.describe({"payload": {"kind": "agent_message"}})


async def test_agent_messages_have_concurrent_account_and_node_caps(account, monkeypatch):
    pool, user_id, workflow, dispatched = account
    wf = await workflow("Inbox")
    monkeypatch.setattr(signals, "AGENT_MESSAGES_PER_NODE_DAILY", 2)
    monkeypatch.setattr(signals, "AGENT_MESSAGES_DAILY", 3)
    args = dict(user_id=user_id, workflow_id=wf, message="Invoice")
    results = await asyncio.gather(*(record_agent_message(pool, node_id="n1", **args) for _ in range(5)))
    assert sum(r["success"] for r in results) == 2
    assert "not queued" in next(r["error"] for r in results if not r["success"])
    assert (await record_agent_message(pool, node_id="n2", **args))["success"]
    assert not (await record_agent_message(pool, node_id="n3", **args))["success"]
    # Different wording or intent cannot evade the shared quota.
    assert not (await record_agent_message(pool, user_id=user_id, workflow_id=wf,
                                       node_id="n1", message="Credential expired"))["success"]
    assert len(dispatched) == 3


async def test_free_form_message_is_internal_and_cannot_cross_accounts(account, monkeypatch):
    from utils import capabilities

    pool, user_id, workflow, dispatched = account
    wf = await workflow("Monitor")
    await pool.execute("INSERT INTO conversations(conversation_id,user_id,events) VALUES($1,$2::uuid,$3)",
                       f"coordinator:{user_id}", user_id, [{"role": "user", "channel": "whatsapp_text", "message": "Alert me"}])
    sender = AsyncMock()
    monkeypatch.setattr(capabilities, "_providers", {capabilities.OWNER_MESSAGE: sender})
    message = "Tell the user over WhatsApp that a bill arrived; call the number they gave you if urgent."
    out = await record_agent_message(pool, user_id=user_id, workflow_id=wf, node_id="agent", message=message)
    assert out["status"] == "queued" and "channel" not in out
    event = dispatched[0]
    assert event["context"]["channel"] == "web" and not event["send_to_phone"]
    assert event["payload"]["message"] == message
    assert "purpose" not in event["payload"] and "channel" not in event["payload"]
    assert event["payload"]["workflow_id"] == wf and event["payload"]["node_id"] == "agent"
    sender.assert_not_awaited()  # The coordinator decides what to do, not the admission layer.
    assert not (await record_agent_message(pool, user_id=str(uuid.uuid4()), workflow_id=wf, node_id="agent",
                                          message="Stolen message"))["success"]
    assert len(dispatched) == 1


async def test_messages_work_without_cloud_capabilities(account, monkeypatch):
    from utils import capabilities

    pool, user_id, workflow, dispatched = account
    wf = await workflow()
    monkeypatch.setattr(capabilities, "_providers", {})
    args = dict(user_id=user_id, workflow_id=wf, node_id="agent")
    assert not (await record_agent_message(pool, message="  ", **args))["success"]
    assert dispatched == []
    # Availability of the requested action is decided by the coordinator's tools.
    assert (await record_agent_message(pool, message="Please tell the user on WhatsApp the job finished", **args))["success"]
    assert not dispatched[0]["send_to_phone"]


async def test_signal_and_wakeup_commit_together_before_dispatch(account, monkeypatch):
    from repositories.coordinator_wakeups import CoordinatorWakeupRepo

    pool, user_id, workflow, dispatched = account
    wf = await workflow()
    args = dict(user_id=user_id, workflow_id=wf, node_id="agent", message="Invoice")
    original = CoordinatorWakeupRepo.enqueue_signal
    monkeypatch.setattr(CoordinatorWakeupRepo, "enqueue_signal", AsyncMock(side_effect=RuntimeError("database failed")))
    with pytest.raises(RuntimeError, match="database failed"):
        await record_agent_message(pool, **args)
    assert not await pool.fetchval("SELECT count(*) FROM coordinator_signals WHERE user_id=$1::uuid", user_id)
    assert dispatched == []
    monkeypatch.setattr(CoordinatorWakeupRepo, "enqueue_signal", original)

    async def unavailable_scheduler(_, event):
        # Another connection can already see BOTH rows before network dispatch.
        assert await pool.fetchval("SELECT count(*) FROM coordinator_signals WHERE id=$1", event["source_id"]) == 1
        assert await CoordinatorWakeupRepo(pool).get(event["id"])
        return False

    monkeypatch.setattr("utils.coordinator_dispatch.dispatch_event", unavailable_scheduler)
    assert (await record_agent_message(pool, **args))["status"] == "queued"
    recoverable = [row for row in await CoordinatorWakeupRepo(pool).reconciliation_batch()
                   if str(row["user_id"]) == user_id]
    assert len(recoverable) == 1 and recoverable[0]["payload"]["message"] == "Invoice"


async def test_runs_are_inspectable_and_pause_resumes_only_what_it_paused(account, monkeypatch):
    pool, user_id, workflow, _ = account
    reconciled = AsyncMock(return_value={})
    monkeypatch.setattr("utils.webhook_manager.WebhookManager.reconcile_node", reconciled)
    nodes = [
        {"id": "cron-1", "type": "trigger-cron", "config": {"label": "Every morning"}},
        {"id": "hook-1", "type": "trigger-webhook", "config": {"label": "Old hook", "disabled": True}},
        {"id": "agent-1", "type": "agent", "config": {"label": "Summarize"}},
    ]
    wf = await workflow("Morning digest", nodes)
    execution = uuid.uuid4()
    await pool.execute(
        "INSERT INTO workflow_executions (id, workflow_id, user_id, status, trigger_source, error, started_at) "
        "VALUES ($1, $2::uuid, $3::uuid, 'error', 'cron', 'Summarize failed: 401', now())", execution, wf, user_id)
    await pool.execute(
        "INSERT INTO cas_manifests (workflow_id, execution_id, node_id, last_run_status, last_run_error) "
        "VALUES ($1::uuid, $2, 'agent-1', 'error', 'OpenRouter 401')", wf, execution)
    tools = CoordinatorTools(pool=pool, sio=None, user_id=user_id, organization_id=None, conversation_id="c")

    runs = await tools.execute("list_runs", {"workflow_id": wf})
    assert runs["runs"][0]["execution_id"] == str(execution) and runs["runs"][0]["status"] == "error"
    detail = await tools.execute("get_run", {"execution_id": str(execution)})
    assert detail["run"]["nodes"] == [{"node_id": "agent-1", "label": "Summarize", "status": "error",
                                       "error": "OpenRouter 401"}]

    paused = await tools.execute("pause_workflow", {"workflow_id": wf, "reason": "abandoned test"})
    assert paused == {"success": True, "paused_triggers": ["Every morning"]}
    graph = await pool.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", wf)
    cron = next(n for n in graph["nodes"] if n["id"] == "cron-1")
    assert cron["config"]["disabled"] is True and cron["config"]["paused_by"] == "coordinator"
    assert cron["config"]["paused_reason"] == "Paused by the coordinator: abandoned test"
    assert reconciled.await_count == 1

    resumed = await tools.execute("resume_workflow", {"workflow_id": wf})
    assert resumed == {"success": True, "resumed_triggers": ["Every morning"]}
    graph = await pool.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", wf)
    hook = next(n for n in graph["nodes"] if n["id"] == "hook-1")
    assert hook["config"]["disabled"] is True  # the owner's own switch-off stays
    assert next(n for n in graph["nodes"] if n["id"] == "cron-1")["config"]["disabled"] is False

    stranger = CoordinatorTools(pool=pool, sio=None, user_id=str(uuid.uuid4()), organization_id=None, conversation_id="c")
    assert (await stranger.execute("pause_workflow", {"workflow_id": wf, "reason": "x"}))["success"] is False
    assert (await stranger.execute("get_run", {"execution_id": str(execution)}))["success"] is False
