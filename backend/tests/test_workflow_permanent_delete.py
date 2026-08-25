import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repositories.workflow import WorkflowRepo
from wss.handlers.workflow_handler import WorkflowHandler
from wss.receiver.client_events import WorkflowPermanentDeleteRequest


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_permanent_delete_refuses_while_execution_remains_active():
    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    sio.emit = AsyncMock()
    conn = MagicMock()
    pool = MagicMock()
    pool.acquire.side_effect = lambda: _Acquire(conn)
    handler = WorkflowHandler(sio=sio)
    handler.get_pool = AsyncMock(return_value=pool)
    request = WorkflowPermanentDeleteRequest(
        request_id="delete-1",
        workflow_id="00000000-0000-4000-8000-000000000001",
    )

    with patch(
        "repositories.workflow.WorkflowRepo.workflow_in_trash_for_owner",
        new=AsyncMock(return_value=True),
    ), patch(
        "utils.execution_stop.stop_running_workflow_executions",
        new=AsyncMock(return_value=["exec-1"]),
    ) as stop_runs, patch(
        "wss.handlers.workflow_handler.cleanup_workflow_resources",
        new=AsyncMock(),
    ) as cleanup, patch(
        "repositories.workflow.WorkflowRepo.hard_delete_workflow",
        new=AsyncMock(),
    ) as hard_delete:
        await handler.permanent_delete_workflow("sid-1", request)

    stop_runs.assert_awaited_once_with(
        pool,
        request.workflow_id,
        "user-1",
    )
    cleanup.assert_not_awaited()
    hard_delete.assert_not_awaited()
    response = sio.emit.await_args.args[1]
    assert "active execution" in response["error"]


@pytest.mark.asyncio
async def test_repo_hard_delete_is_guarded_by_running_execution(postgres_db):
    user_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    await postgres_db.execute(
        "INSERT INTO auth.users (id, email) VALUES ($1, $2)",
        user_id,
        f"delete-{user_id}@example.com",
    )
    await postgres_db.execute(
        "INSERT INTO workflows (id, owner_id, name, deleted_at) "
        "VALUES ($1, $2, 'delete-race', NOW())",
        workflow_id,
        user_id,
    )
    await postgres_db.execute(
        "INSERT INTO workflow_executions (id, workflow_id, user_id, status) "
        "VALUES ($1, $2, $3, 'running')",
        execution_id,
        workflow_id,
        user_id,
    )
    repo = WorkflowRepo(MagicMock())

    assert await repo.list_running_execution_ids(postgres_db, workflow_id) == [
        str(execution_id)
    ]
    assert (
        await repo.hard_delete_workflow(
            postgres_db,
            workflow_id,
            user_id,
        )
        is False
    )
    assert (
        await postgres_db.fetchval(
            "SELECT count(*) FROM workflows WHERE id = $1",
            workflow_id,
        )
        == 1
    )

    await postgres_db.execute(
        "UPDATE workflow_executions SET status = 'error', finished_at = NOW() "
        "WHERE id = $1",
        execution_id,
    )
    assert (
        await repo.hard_delete_workflow(
            postgres_db,
            workflow_id,
            user_id,
        )
        is True
    )
    assert (
        await postgres_db.fetchval(
            "SELECT count(*) FROM workflows WHERE id = $1",
            workflow_id,
        )
        == 0
    )
