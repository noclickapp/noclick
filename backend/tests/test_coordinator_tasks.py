"""Coordinator delegation contracts: real SQL claims, ownership, and reply delivery.

The database tests use independent connections so claims race as they do across
serving containers. Runtime tests exercise immediate and delayed agent replies.
"""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from coder.coordinator import tasks
from repositories.coordinator_tasks import CoordinatorTaskRepo
from utils import task_notifications
from utils.access_control import Permission

pytestmark = pytest.mark.asyncio
USER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
async def task_db(postgres_db, postgres_container):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(),
        port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password,
        database=postgres_container.dbname, min_size=1, max_size=5,
        init=setup_asyncpg_codecs,
    )
    workflow_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO workflows(id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Delegate', $3)",
        workflow_id, USER, {"nodes": [], "edges": []},
    )
    repo = CoordinatorTaskRepo(pool)

    async def enqueue(**overrides):
        args = dict(user_id=USER, workflow_id=workflow_id, node_id="agent", agent_name="Researcher",
                    message="Research this", send_to_phone=False)
        args.update(overrides)
        return await repo.enqueue(**args)

    try:
        yield pool, repo, enqueue
    finally:
        await pool.execute("DELETE FROM workflows WHERE id = $1::uuid", workflow_id)
        await pool.execute("DELETE FROM conversations WHERE conversation_id = $1", f"coordinator:{USER}")
        await pool.close()


async def test_concurrent_claims_dispatch_once_and_followups_wait(task_db):
    pool, repo, enqueue = task_db
    first = await enqueue()
    second = await enqueue(parent_job_id=str(first["id"]), message="And summarize it")
    assert first["conversation_key"] == second["conversation_key"]
    claims = await asyncio.gather(*(repo.claim() for _ in range(4)))
    claimed = [c for c in claims if c]
    assert [c["id"] for c in claimed] == [first["id"]]
    assert await repo.claim() is None
    assert await pool.fetchval("SELECT trigger_source FROM workflow_executions WHERE id=$1", claimed[0]["execution_id"]) == "coordinator"
    await repo.wait_for_reply(str(first["id"]))
    assert await repo.claim() is None
    await repo.finish(str(first["id"]), result={"response": "Found it"})
    assert (await repo.claim())["id"] == second["id"]


async def test_followup_ownership_and_pending_cap(task_db):
    _, repo, enqueue = task_db
    first = await enqueue()
    with pytest.raises(ValueError, match="account"):
        await enqueue(parent_job_id=str(first["id"]), user_id=str(uuid.uuid4()))
    with pytest.raises(ValueError, match="agent"):
        await enqueue(parent_job_id=str(first["id"]), node_id="other-agent")
    assert await repo.list_for_user(str(uuid.uuid4()), str(first["id"])) == []
    outcomes = await asyncio.gather(*(enqueue() for _ in range(12)), return_exceptions=True)
    assert sum(isinstance(o, ValueError) for o in outcomes) == 3
    assert len(await repo.list_for_user(USER)) == 10


async def test_callback_races_delivery_ack_and_duplicate_notifications(task_db, monkeypatch):
    pool, repo, enqueue = task_db
    await enqueue()
    claimed = await repo.claim()
    tid = str(claimed["id"])
    monkeypatch.setattr(tasks, "get_native_pool", lambda: pool)
    output = {"response": "The answer", "input_execution_ids": [str(claimed["execution_id"]), "invalid"]}
    args = dict(workflow_id=str(claimed["workflow_id"]), node_id="agent",
                conversation_id=f"ck:{claimed['workflow_id']}:agent:{claimed['conversation_key']}", output=output)
    await tasks.complete_agent_deliveries(**{**args, "node_id": "wrong-agent"})
    assert (await repo.list_for_user(USER, tid))[0]["status"] == "running"
    await tasks.complete_agent_deliveries(**args)
    await tasks.settle_output(repo, tid, {"status": "awaiting_agent_turn"})
    await tasks.complete_agent_deliveries(**{**args, "output": {**output, "response": "duplicate"}})
    row = (await repo.list_for_user(USER, tid))[0]
    assert row["status"] == "completed" and row["result"]["response"] == "The answer"
    send = AsyncMock()
    monkeypatch.setattr(task_notifications, "send_event", send)
    monkeypatch.setattr(tasks, "get_sio", lambda: object())
    await asyncio.gather(tasks.notify_results(pool), tasks.notify_results(pool))
    send.assert_awaited_once()
    assert send.call_args.args[2].notification is True
    assert send.call_args.kwargs["user_id"] == USER
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
    assert len(events) == 1 and events[0]["message"] == "Researcher replied:\n\nThe answer"
    assert events[0]["turn_id"] == f"coordinator-task:{tid}"


async def test_restart_expires_lease_without_resending(task_db):
    pool, repo, enqueue = task_db
    await enqueue()
    claimed = await repo.claim()
    await pool.execute("UPDATE coordinator_jobs SET lease_until=now()-interval '1 second' WHERE id=$1", claimed["id"])
    restarted = CoordinatorTaskRepo(pool)
    await restarted.reap_stalled()
    row = (await restarted.list_for_user(USER))[0]
    assert row["status"] == "failed" and "interrupted" in row["error"]
    assert await restarted.claim() is None
    assert await pool.fetchval("SELECT status FROM workflow_executions WHERE id=$1", claimed["execution_id"]) == "error"


async def test_phone_delivery_failure_keeps_the_durable_reply(task_db, monkeypatch):
    pool, repo, enqueue = task_db
    await enqueue(send_to_phone=True)
    claimed = await repo.claim()
    await tasks.settle_output(repo, str(claimed["id"]), {"response": {"answer": 42}})
    monkeypatch.setattr(tasks, "get_sio", lambda: object())
    monkeypatch.setattr(task_notifications, "send_event", AsyncMock())
    phone = AsyncMock(return_value={"success": False, "error": "WhatsApp window closed"})
    monkeypatch.setattr(task_notifications, "capability", lambda key: phone)
    await tasks.notify_results(pool)
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "completed" and row["notified_at"]
    assert row["delivery_error"] == "WhatsApp window closed"
    assert '"answer": 42' in phone.call_args.args[2]


async def test_dispatch_rechecks_access_and_finalizes_precreated_execution(task_db, monkeypatch):
    pool, repo, enqueue = task_db
    await enqueue()
    claimed = await repo.claim()
    monkeypatch.setattr(tasks, "get_sio", lambda: object())
    monkeypatch.setattr(tasks, "agent_target", AsyncMock(side_effect=ValueError("Edit access revoked")))
    with patch("wss.handlers.workflow_execution_handler.WorkflowExecutionHandler.handle_execute", AsyncMock()) as run:
        await tasks.run_task(pool, claimed)
    run.assert_not_called()
    assert (await repo.list_for_user(USER))[0]["error"] == "Edit access revoked"
    assert await pool.fetchval("SELECT status FROM workflow_executions WHERE id=$1", claimed["execution_id"]) == "error"


async def test_task_table_is_inaccessible_to_browser_roles(task_db):
    pool, _, _ = task_db
    assert await pool.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid='coordinator_jobs'::regclass")
    for role in ("anon", "authenticated"):
        assert not await pool.fetchval("SELECT has_table_privilege($1, 'coordinator_jobs', 'SELECT,INSERT,UPDATE,DELETE')", role)


@pytest.mark.parametrize("permission", [Permission.VIEW, None])
async def test_message_requires_edit_access(permission):
    from tests.mocks.mock_asyncpg import MockNativePool

    with patch.object(tasks, "check_resource_access", AsyncMock(return_value=SimpleNamespace(
        has_access=permission is not None, permission=permission,
    ))), patch("wss.handlers.workflow_execution_handler.WorkflowExecutionHandler._fetch_workflow", AsyncMock()) as fetch:
        with pytest.raises(ValueError, match="edit access"):
            await tasks.request_agent_message(MockNativePool(), None, user_id=USER, workflow_id=str(uuid.uuid4()),
                                              node_id="agent", message="Hello", send_to_phone=False)
        fetch.assert_not_called()


@pytest.mark.parametrize("output,success,error,expected", [
    ({"response": "Done"}, True, None, "completed"),
    ({"status": "awaiting_agent_turn"}, True, None, "waiting"),
    (None, False, "Missing credentials", "failed"),
    ({"response": ""}, True, None, "failed"),
])
async def test_dispatch_uses_saved_delivery_and_conversation(task_db, monkeypatch, output, success, error, expected):
    pool, repo, enqueue = task_db
    await enqueue()
    claimed = await repo.claim()
    monkeypatch.setattr(tasks, "agent_target", AsyncMock(return_value={"id": "agent"}))
    monkeypatch.setattr(tasks, "get_sio", lambda: object())
    run = AsyncMock(return_value=SimpleNamespace(node_outputs={"agent": output}, success=success, error=error))
    with patch("wss.handlers.workflow_execution_handler.WorkflowExecutionHandler.handle_execute", run):
        await tasks.run_task(pool, claimed)
    request = run.call_args.args[1]
    assert request.start_node_id == "agent" and request.trigger_source == "coordinator"
    assert run.call_args.args[2] == str(claimed["execution_id"])
    assert run.call_args.kwargs["caller_user_id"] == USER
    assert request.config_overrides["agent"] == {
        "message": "Research this", "conversation_key": claimed["conversation_key"], "mockedOutput": None,
    }
    assert request.conversation_id.endswith(claimed["conversation_key"])
    assert (await repo.list_for_user(USER))[0]["status"] == expected
