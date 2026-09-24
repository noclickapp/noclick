"""Completion → real coordinator turn → dynamically chosen next action.

Only the model and transports are doubled. Claims, locks, requests, resets and
outbox writes run against PostgreSQL, including concurrent/restarted workers.
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from coder.coordinator import agent, tasks, wakeups
from coder.workflow import requests
from repositories.coordinator_tasks import CoordinatorTaskRepo
from repositories.coordinator_wakeups import CoordinatorWakeupRepo, coordinator_lock
from tests.fixtures.local_scheduler import local_scheduler  # noqa: F401
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from utils import capabilities
from wss.sender.events import ChatMessageEvent

pytestmark = pytest.mark.asyncio
CONTEXT = {"epoch": "", "depth": 0, "request": "After unpublishing, publish at ttt.",
           "channel": "whatsapp_text", "turn_id": "original-user-turn"}


@pytest.fixture
async def db(builder_request_db, monkeypatch, local_scheduler):
    pool, builds, workflow_id, enqueue = builder_request_db
    repo = CoordinatorWakeupRepo(pool)
    monkeypatch.setattr(agent, "get_native_pool", lambda: pool)
    monkeypatch.setattr(agent, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(wakeups, "get_sio", lambda: object())
    monkeypatch.setattr("utils.feature_gates.require_feature", lambda *a, **kw: None)
    monkeypatch.setattr("wss.handlers.coordinator_handler.plan_allows_turn", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(capabilities, "_providers", {capabilities.INTERFACE_PUBLISH: AsyncMock()})
    # No real provider/billing/transport calls in this regression.
    monkeypatch.setattr(agent, "memory_context", AsyncMock(return_value=""))
    try:
        yield pool, repo, builds, workflow_id, enqueue
    finally:
        await pool.execute("DELETE FROM coordinator_wakeups WHERE user_id=$1::uuid", USER)


async def complete_build(db, *, error=None, cancelled=False, context=None):
    pool, repo, builds, workflow_id, enqueue = db
    request = await enqueue(
        publish={"action": "unpublish", "title": "", "node_id": None, "subdomain": None},
        origin={"source": "coordinator"}, continuation=CONTEXT if context is None else context,
        send_to_phone=True,
    )
    claimed = await builds.claim()
    if cancelled:
        await pool.execute("UPDATE coordinator_jobs SET status='cancelled' WHERE id=$1", request["id"])
    else:
        await builds.finish(claimed["id"], claimed["attempt_id"],
                            result={"publication": {"state": "unpublished"}}, error=error)
    notification = await builds.claim_notification()
    assert notification["phone_state"] is None  # no premature phone send
    await requests.notify_result(pool, notification)
    return request, notification


@pytest.mark.parametrize("original_channel", ["whatsapp_text", "web"])
async def test_completion_wakes_same_coordinator_and_only_then_submits_b(db, monkeypatch, original_channel):
    pool, repo, builds, workflow_id, _ = db
    context = {**CONTEXT, "channel": original_channel}
    request, notification = await complete_build(db, context=context)
    # Repeated delivery of the same completion cannot create a second wake-up.
    await asyncio.gather(*(requests.notify_result(pool, notification) for _ in range(3)))
    assert await builds.claim_notification() is None
    assert len(await builds.list_for_user(USER)) == 1  # B is not pre-queued
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups") == 1
    calls = []

    class ResumedAgent:
        @classmethod
        async def create(cls, **kwargs):
            self = cls()
            self.kwargs = kwargs
            assert kwargs["conversation_id"] == f"coordinator:{USER}"
            assert kwargs["enable_persistence"] is True
            return self

        async def __call__(self, message):
            assert "content_items" not in message
            item = message["input_items"][0]
            assert item["role"] == "developer"
            payload = json.loads(item["content"].split("\n", 1)[1])
            assert payload["original_request"] == CONTEXT["request"]
            assert payload["outcome"]["result"]["publication"]["state"] == "unpublished"
            # This models a decision made AFTER receiving A's result, using the
            # coordinator's normal tool executor and the builder's real queue.
            result = await self.kwargs["custom_tool_executor"]("request_build", {
                "workflow_id": workflow_id, "publish": {"action": "publish", "subdomain": "ttt"},
            })
            assert result["success"]
            calls.append(result["job_id"])
            await self.kwargs["emit_message"](ChatMessageEvent(message="Unpublished; publishing at ttt now.", finished=True))

        async def cleanup(self):
            pass

    monkeypatch.setattr(agent, "Agent", ResumedAgent)
    claims = await asyncio.gather(*(CoordinatorWakeupRepo(pool).claim() for _ in range(3)))
    event = next(c for c in claims if c)
    assert sum(c is not None for c in claims) == 1
    await wakeups.run_wakeup(pool, event)
    assert len(calls) == 1
    followup = (await builds.list_for_user(USER, job_id=calls[0]))[0]
    assert followup["spec"]["publish"]["subdomain"] == "ttt"
    assert followup["continuation"] == {**context, "depth": 1}
    assert followup["send_to_phone"] is True
    # No fabricated user message or duplicate assistant transcript on resume.
    assert not await pool.fetchval("SELECT events FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
    phone = AsyncMock(return_value=("sent", None))
    socket = AsyncMock()
    monkeypatch.setattr(wakeups, "deliver_phone", phone)
    monkeypatch.setattr(wakeups, "emit_notification", socket)
    delivery = await repo.claim_delivery()
    assert await repo.claim_delivery() is None
    await wakeups.deliver_reply(pool, delivery)
    phone.assert_awaited_once()
    assert phone.call_args.args[2] == "Unpublished; publishing at ttt now."
    transcript = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
    assert len(transcript) == 1 and transcript[0]["role"] == "assistant"
    assert transcript[0]["notification"] is True
    assert (await builds.list_for_user(USER, job_id=str(request["id"])))[0]["phone_state"] == "sent"


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_every_terminal_builder_result_wakes_with_actual_outcome(db, status):
    pool, repo, _, _, _ = db
    await complete_build(db, error="URL taken" if status == "failed" else None, cancelled=status == "cancelled")
    event = await repo.claim()
    assert event["payload"]["status"] == status
    assert event["payload"]["error"] == ("URL taken" if status == "failed" else None)


@pytest.mark.parametrize("failed", [False, True])
async def test_agent_reply_uses_same_completion_inbox(db, failed):
    pool, repo, _, workflow_id, _ = db
    tasks_repo = CoordinatorTaskRepo(pool)
    task = await tasks_repo.enqueue(user_id=USER, workflow_id=workflow_id, node_id="agent", agent_name="Researcher",
                                    message="Research this", send_to_phone=True, continuation=CONTEXT)
    await tasks_repo.claim()
    await tasks_repo.finish(str(task["id"]), result={"response": "Found it"}, error="Unavailable" if failed else None)
    await asyncio.gather(tasks.notify_results(pool), tasks.notify_results(pool))
    event = await repo.claim()
    assert event["source"] == "job" and event["source_id"] == task["id"]
    assert event["payload"]["status"] == ("failed" if failed else "completed")
    assert event["send_to_phone"] is True
    assert await repo.claim() is None
    assert await tasks_repo.pending_notifications() == []


async def test_restart_retries_only_unstarted_turn_and_fences_old_attempt(db):
    pool, repo, _, _, _ = db
    await complete_build(db)
    first = await repo.claim()
    await pool.execute("UPDATE coordinator_wakeups SET lease_until=now()-interval '1 second'")
    await repo.reap_stalled()
    next_attempt = await CoordinatorWakeupRepo(pool).claim()
    assert first["id"] == next_attempt["id"] and first["attempt_id"] != next_attempt["attempt_id"]
    assert not await repo.start(first)
    assert not await repo.heartbeat(first)
    await repo.finish(first, "stale")
    assert await repo.start(next_attempt)
    await pool.execute("UPDATE coordinator_wakeups SET lease_until=now()-interval '1 second'")
    await repo.reap_stalled()
    assert await repo.claim() is None  # a tool might already have acted
    delivery = await repo.claim_delivery()
    assert "interrupted" in delivery["response"]
    await pool.execute("UPDATE coordinator_wakeups SET lease_until=now()-interval '1 second'")
    await repo.reap_stalled()
    assert await repo.claim_delivery() is None  # never duplicate an uncertain phone send
    assert await pool.fetchval("SELECT delivery_error FROM coordinator_wakeups")


async def test_shared_lock_serializes_independent_containers_and_releases_on_error(db):
    pool, _, _, _, _ = db
    acquired = asyncio.Event()

    async def second_container():
        async with coordinator_lock(pool, USER):
            acquired.set()

    with pytest.raises(ValueError):
        async with coordinator_lock(pool, USER):
            waiter = asyncio.create_task(second_container())
            await asyncio.sleep(0.05)
            assert not acquired.is_set()
            # An unrelated account is not blocked by this turn.
            other = str(uuid.uuid4())
            await pool.execute("INSERT INTO auth.users(id,email) VALUES($1::uuid, 'lease-test@example.test')", other)
            async with coordinator_lock(pool, other):
                pass
            raise ValueError("turn failed")
    await asyncio.wait_for(waiter, 2)
    assert acquired.is_set()


async def test_reset_invalidates_pending_and_future_completions(db, monkeypatch):
    pool, repo, _, _, _ = db
    await pool.execute("INSERT INTO conversations(conversation_id,user_id) VALUES ($1,$2::uuid)", f"coordinator:{USER}", USER)
    await complete_build(db)
    event = await repo.claim()
    async with coordinator_lock(pool, USER):
        assert await repo.reset(USER)
    assert await repo.epoch(USER) != CONTEXT["epoch"]
    turn = AsyncMock()
    monkeypatch.setattr(agent, "run_coordinator_turn", turn)
    await wakeups.run_wakeup(pool, event)
    # A result arriving after reset also retains its old authorization epoch.
    await complete_build(db)
    await wakeups.run_wakeup(pool, await repo.claim())
    turn.assert_not_awaited()
    assert await repo.claim_delivery() is None


@pytest.mark.parametrize("blocker", ["limit", "plan", "gate"])
async def test_followup_limits_report_result_without_new_actions(db, monkeypatch, blocker):
    pool, repo, _, _, _ = db
    await complete_build(db, context={**CONTEXT, "depth": wakeups.MAX_AUTONOMOUS_TURNS if blocker == "limit" else 0})
    if blocker == "plan":
        monkeypatch.setattr("wss.handlers.coordinator_handler.plan_allows_turn", AsyncMock(return_value=(False, "Daily AI limit reached")))
    elif blocker == "gate":
        def denied(*a, **kw):
            raise ValueError("Feature disabled")
        monkeypatch.setattr("utils.feature_gates.require_feature", denied)
    turn = AsyncMock()
    monkeypatch.setattr(agent, "run_coordinator_turn", turn)
    await wakeups.run_wakeup(pool, await repo.claim())
    turn.assert_not_awaited()
    assert "completed" in (await repo.claim_delivery())["response"]


async def test_wakeup_table_is_private(db):
    pool, _, _, _, _ = db
    assert await pool.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid='coordinator_wakeups'::regclass")
    for role in ("anon", "authenticated"):
        assert not await pool.fetchval("SELECT has_table_privilege($1,'coordinator_wakeups','SELECT')", role)


@pytest.mark.parametrize('link_kind', ['credential_request', 'credential_policy', 'credential_approval'])
async def test_human_link_result_recovers_then_runs_same_thread_and_replies_once(db, monkeypatch, link_kind):
    from repositories.credentials import CredentialsRepo
    from repositories.credential_approvals import CredentialApprovalRepo
    from repositories.local_schedules import LocalScheduleRepo
    from utils import coordinator_dispatch
    pool, repo, _, _, _ = db
    cid = await pool.fetchval("INSERT INTO credentials(owner_id,name,credential_type,credential) "
                              "VALUES($1::uuid,'Mail','google_gmail_oauth','encrypted') RETURNING id", USER)
    policy = CredentialApprovalRepo(pool)
    if link_kind == 'credential_request':
        row = await CredentialsRepo(pool).upsert_credential_request(
            requester_id=USER, target_email='', credential_type='google_gmail_oauth',
            message='Connect mail', continuation=CONTEXT,
        )
        await pool.execute("UPDATE credential_requests SET status='fulfilled',credential_id=$2 WHERE id=$1::uuid", row.id, cid)
        expected = 'fulfilled'
    elif link_kind == 'credential_policy':
        await policy.await_human_review(str(cid), USER, CONTEXT)
        await policy.replace_from_human(str(cid), USER, [], 0)
        expected = 'reviewed'
    else:
        await policy.tighten(str(cid), USER, ['automation-gmail.send_email_message'])
        approval = await policy.admit(credential_id=str(cid), user_id=USER,
            node_type='automation-gmail', operation='send_email_message', arguments={'to': 'recipient@example.test'},
            conversation_id=f'coordinator:{USER}', continuation=CONTEXT)
        await policy.decide_from_human(str(approval['id']), USER, 'approved')
        expected = 'approved'
    # Simulate a process stopping immediately after commit: no route dispatched.
    assert await pool.fetchval('SELECT count(*) FROM local_cron_schedules') == 0
    await coordinator_dispatch.reconcile(pool)
    schedules = await LocalScheduleRepo(pool).list(user_id=USER, target_kind='coordinator_wakeup')
    assert len(schedules) == 1
    event = await repo.get(schedules[0]['payload']['event_id'])
    seen = []

    class ResumedAgent:
        @classmethod
        async def create(cls, **kwargs):
            self = cls()
            self.kwargs = kwargs
            assert kwargs['conversation_id'] == f'coordinator:{USER}'
            assert kwargs['enable_persistence']
            return self

        async def __call__(self, message):
            payload = json.loads(message['input_items'][0]['content'].split('\n', 1)[1])
            assert payload['original_request'] == CONTEXT['request']
            assert payload['outcome']['status'] == expected
            seen.append(payload)
            await self.kwargs['emit_message'](ChatMessageEvent(message='I have the result and can continue.', finished=True))

        async def cleanup(self):
            pass

    monkeypatch.setattr(agent, 'Agent', ResumedAgent)
    phone = AsyncMock(return_value=('sent', None))
    monkeypatch.setattr(wakeups, 'deliver_phone', phone)
    monkeypatch.setattr(wakeups, 'emit_notification', AsyncMock())
    assert await wakeups.process_event(pool, event)
    assert await wakeups.process_event(pool, await repo.get(event['id']))  # Duplicate scheduler delivery.
    assert len(seen) == 1
    phone.assert_awaited_once()
    assert phone.call_args.args[2] == 'I have the result and can continue.'
    assert (await repo.get(event['id']))['status'] == 'done'
    await pool.execute('DELETE FROM credential_requests WHERE requester_id=$1::uuid', USER)
    await pool.execute('DELETE FROM credentials WHERE id=$1', cid)
