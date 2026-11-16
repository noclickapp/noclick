"""A single-step test run resolves references to any node outside its slice.

The canvas's single-step Run sends the step plus its direct parents (with
their canvas outputs as mocks) and the whole graph as the replay graph, but
no start node. A step's `$('X')` may name any node, the trigger two hops up
included, so everything outside the slice is preloaded from its latest stored
output, as a run from a start node does. Real Postgres and the real node
runner; only the socket and the relay are stubbed.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.async_helpers import drain_spawned_tasks
from utils.cas import store as cas_store
from utils.node_outputs import latest_output_meta
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
from wss.receiver.client_events import WorkflowExecuteRequest

OWNER = "00000000-0000-4000-8000-0000000005c1"
DELIVERY = {"body": {"customer": "Ada"}}


def _step(node_id, value, **config):
    return {"id": node_id, "type": "test-dummy", "position": {"x": 0, "y": 0},
            "config": {"stringValue": value, **config}}


# hook → step_a → gate → shape → upload; `shape` reads the trigger two hops up.
GRAPH = [
    {"id": "hook", "type": "trigger-webhook", "position": {"x": 0, "y": 0}, "config": {}},
    _step("step_a", "a"),
    _step("gate", "gate"),
    _step("shape", "{{ $('hook').body.customer }} via {{ $('gate').stringValue }}"),
    _step("upload", "{{ $('shape').stringValue }}"),
]
EDGES = [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(
    [("hook", "step_a"), ("step_a", "gate"), ("gate", "shape"), ("shape", "upload")])]


class _Relay:
    connected, connect_error = True, None

    def start(self):
        return None

    async def listen_for_stop(self, *a, **k):
        return None

    async def close(self):
        return None


async def _workflow(db):
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, 'single-step@example.com') "
                     "ON CONFLICT (id) DO NOTHING", OWNER)
    workflow_id = str(uuid.uuid4())
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Flow', $3)",
                     workflow_id, OWNER, {"nodes": GRAPH, "edges": EDGES})
    return workflow_id


async def _stored(db, workflow_id, outputs):
    """An earlier run that left these nodes' latest stored outputs."""
    execution_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO workflow_executions (id, workflow_id, user_id, status, started_at, finished_at) "
        "VALUES ($1, $2, $3, 'completed', NOW() - INTERVAL '1 hour', NOW() - INTERVAL '1 hour')",
        execution_id, workflow_id, OWNER,
    )
    for node_id, output in outputs.items():
        await cas_store.persist_node_output(
            db.pool, workflow_id=workflow_id, execution_id=execution_id, node_id=node_id, output=output)
    return execution_id


async def _single_step(db, workflow_id, nodes, edges):
    """An editor's single-step Run, as the canvas sends it."""
    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": OWNER})
    handler = WorkflowExecutionHandler(sio=sio)
    handler.get_pool = AsyncMock(return_value=db.pool)
    request = WorkflowExecuteRequest(
        request_id="single-step", workflow_id=workflow_id, nodes=nodes, edges=edges,
        replay_nodes=GRAPH, replay_edges=EDGES,
    )
    with patch("wss.handlers.workflow_execution_handler.send_event", new_callable=AsyncMock), \
            patch("wss.sender.send_event", new_callable=AsyncMock), \
            patch("utils.execution_relay.create_execution_relay", return_value=_Relay()), \
            patch("utils.node_outputs.commit_graph_snapshot", AsyncMock()):
        result = await handler.handle_execute("sid", request)
    await drain_spawned_tasks(timeout=10)  # the fire-and-forget CAS persist
    return result


@pytest.fixture(autouse=True)
def _no_dummy_sleep(monkeypatch):
    monkeypatch.setenv("WORKFLOW_TEST_MODE", "1")


@pytest.mark.asyncio
async def test_a_step_reads_a_node_two_hops_up_from_its_stored_output(real_database):
    workflow_id = await _workflow(real_database)
    delivery_run = await _stored(real_database, workflow_id, {
        "hook": DELIVERY, "gate": {"type": "dummy", "stringValue": "stored gate"}})
    gate = _step("gate", "gate", mockedOutput={"stringValue": "canvas gate"})

    result = await _single_step(real_database, workflow_id, [gate, GRAPH[3]], [EDGES[2]])

    assert result.success, result.error
    # The trigger comes from its stored delivery; the parent's canvas output
    # beats the parent's stored one.
    assert result.node_outputs["shape"]["stringValue"] == "Ada via canvas gate"
    assert set(result.node_statuses) == {"gate", "shape"}
    persisted = {r["node_id"] for r in await real_database.fetch(
        "SELECT node_id FROM cas_manifests WHERE execution_id = $1", uuid.UUID(result.execution_id))}
    assert "shape" in persisted and "hook" not in persisted, "context is never re-persisted"
    assert (await latest_output_meta(real_database.pool, workflow_id, "hook"))["execution_id"] == str(delivery_run)


@pytest.mark.asyncio
async def test_a_parent_that_has_not_run_runs_with_its_own_context(real_database):
    """Run on `upload` while `shape` has no output: `shape` runs for real and
    reads the trigger and its own parent from their stored outputs."""
    workflow_id = await _workflow(real_database)
    await _stored(real_database, workflow_id, {
        "hook": DELIVERY, "gate": {"type": "dummy", "stringValue": "stored gate"}})

    result = await _single_step(real_database, workflow_id, [GRAPH[3], GRAPH[4]], [EDGES[3]])

    assert result.success, result.error
    assert result.node_outputs["upload"]["stringValue"] == "Ada via stored gate"
    assert set(result.node_statuses) == {"shape", "upload"}
