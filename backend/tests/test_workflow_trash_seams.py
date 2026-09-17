"""Trash and restore are one owner-scoped seam each, shared by the socket
handler, MCP and the coordinator: trash tears down schedules and webhooks
before soft-deleting, restore re-registers them after un-deleting."""

from unittest.mock import AsyncMock

import pytest

from tests.mocks.mock_asyncpg import MockNativePool
from wss.handlers import workflow_handler as wh

USER = "11111111-1111-1111-1111-111111111111"
WORKFLOW = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def seams(monkeypatch):
    cleanup = AsyncMock(return_value={})
    restore_resources = AsyncMock()
    spawned = []
    monkeypatch.setattr(wh, "cleanup_workflow_operational_resources", cleanup)
    monkeypatch.setattr(wh, "restore_nodes_resources", restore_resources)
    monkeypatch.setattr(wh, "spawn", lambda coro, **kw: spawned.append(coro) or coro.close())
    monkeypatch.setattr(wh.WorkflowRepo, "workflow_exists_for_owner", AsyncMock(return_value=True))
    monkeypatch.setattr(wh.WorkflowRepo, "soft_delete_workflow", AsyncMock())
    monkeypatch.setattr(wh.WorkflowRepo, "restore_workflow", AsyncMock(return_value="UPDATE 1"))
    return cleanup, restore_resources, spawned


async def test_trash_tears_down_then_soft_deletes_for_the_owner_only(seams):
    cleanup, _, _ = seams
    out = await wh.trash_workflow_as_owner(MockNativePool(), WORKFLOW, USER)
    assert out == {"success": True, "workflow_id": WORKFLOW, "message": "Workflow moved to trash"}
    cleanup.assert_awaited_once()
    assert wh.WorkflowRepo.soft_delete_workflow.await_args.args[2] == USER

    wh.WorkflowRepo.workflow_exists_for_owner.return_value = False
    assert (await wh.trash_workflow_as_owner(MockNativePool(), WORKFLOW, USER))["success"] is False
    assert cleanup.await_count == 1  # nothing torn down for a workflow the user does not own
    assert (await wh.trash_workflow_as_owner(MockNativePool(), "not-a-uuid", USER))["error"] == "Workflow not found"


async def test_restore_undeletes_then_re_registers_in_the_background(seams, monkeypatch):
    _, restore_resources, spawned = seams
    pool = MockNativePool({"SELECT workflow FROM workflows": {"workflow": {"nodes": [{"id": "n1"}], "edges": []}}})
    out = await wh.restore_workflow_as_owner(pool, WORKFLOW, USER)
    assert out["success"] is True and out["workflow_id"] == WORKFLOW
    assert len(spawned) == 1 and restore_resources.call_args.kwargs["nodes"] == [{"id": "n1"}]

    wh.WorkflowRepo.restore_workflow.return_value = "UPDATE 0"
    assert (await wh.restore_workflow_as_owner(pool, WORKFLOW, USER))["error"] == "Workflow not found in trash"
    assert len(spawned) == 1
