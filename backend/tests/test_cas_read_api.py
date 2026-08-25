"""Handler tests for the CAS read API: list_executions (extended),
get_execution_detail, get_node_output. Real DB + R2 fake; responses captured
off the mocked sio.emit (send_event → sio.emit('response', data, to=sid))."""

import uuid
from unittest.mock import AsyncMock

import pytest

from tests.fixtures.cas_fixtures import cas_pool, make_workflow, make_execution, TEST_USER_ID  # noqa: F401
from tests.mocks.mock_r2 import FakeR2, patch_r2
from utils.cas import store
from wss.handlers.workflow_handler import WorkflowHandler
from wss.receiver.client_events import (
    WorkflowExecutionDetailRequest,
    WorkflowNodeOutputRequest,
    WorkflowExecutionListRequest,
)

GRAPH = {"nodes": [{"id": "n1"}], "edges": []}


def _handler(pool, user_id=TEST_USER_ID):
    h = WorkflowHandler(sio=AsyncMock())
    h.sio.get_session = AsyncMock(return_value={"user_id": str(user_id)})
    h.get_pool = AsyncMock(return_value=pool)
    return h


def _last_response(handler):
    for call in reversed(handler.sio.emit.call_args_list):
        if call.args and call.args[0] == "response":
            return call.args[1]
    return None


@pytest.mark.asyncio
class TestCasReadApi:
    async def test_list_executions_includes_trigger_and_has_graph(self, cas_pool):
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        with patch_r2(FakeR2()):
            await store.persist_graph_snapshot(cas_pool, workflow_id=wid, execution_id=eid, graph=GRAPH)
        await cas_pool.execute("UPDATE workflow_executions SET trigger_source='cron' WHERE id=$1", eid)

        handler = _handler(cas_pool)
        await handler.list_executions("sid", WorkflowExecutionListRequest(
            request_id="r1", workflow_id=str(wid)))
        data = _last_response(handler)["data"]
        row = next(e for e in data["executions"] if e["id"] == str(eid))
        assert row["trigger_source"] == "cron"
        assert row["has_graph"] is True

    async def test_get_execution_detail(self, cas_pool):
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        with patch_r2(FakeR2()):
            await store.persist_graph_snapshot(cas_pool, workflow_id=wid, execution_id=eid, graph=GRAPH)
            await store.persist_node_result(cas_pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output={"big": list(range(2000))},
                                            status="completed", threshold=16)
            await store.persist_node_result(cas_pool, workflow_id=wid, execution_id=eid,
                                            node_id="n2", status="skipped")
            handler = _handler(cas_pool)
            await handler.get_execution_detail("sid", WorkflowExecutionDetailRequest(
                request_id="r2", workflow_id=str(wid), execution_id=str(eid)))
        data = _last_response(handler)["data"]
        assert data["graph"] == GRAPH
        results = {r["node_id"]: r for r in data["node_results"]}
        assert results["n1"]["last_run_status"] == "completed" and results["n1"]["has_output"] is True
        assert results["n2"]["last_run_status"] == "skipped" and results["n2"]["has_output"] is False

    async def test_get_node_output(self, cas_pool):
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        output = {"big": list(range(2000))}
        with patch_r2(FakeR2()):
            await store.persist_node_result(cas_pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=output, status="completed", threshold=16)
            handler = _handler(cas_pool)
            await handler.get_node_output("sid", WorkflowNodeOutputRequest(
                request_id="r3", workflow_id=str(wid), execution_id=str(eid), node_id="n1"))
        data = _last_response(handler)["data"]
        assert data["node_id"] == "n1"
        assert data["output"] == output

    async def test_detail_access_denied_for_non_sharer(self, cas_pool):
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        handler = _handler(cas_pool, user_id=uuid.uuid4())  # not the owner
        await handler.get_execution_detail("sid", WorkflowExecutionDetailRequest(
            request_id="r4", workflow_id=str(wid), execution_id=str(eid)))
        assert _last_response(handler).get("error")
