"""Integration tests for the CAS wiring in WorkflowExecutionHandler.

Exercises the real handler's persist routing against a committed pool + the R2
fake: node outputs/status route to the CAS (the sole node-output store), and
set-variable nodes mirror their assignments into workflows.workflow->variables.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.fixtures.cas_fixtures import cas_pool, codec_pool, make_workflow, make_execution, TEST_USER_ID  # noqa: F401
from tests.mocks.mock_r2 import FakeR2, patch_r2
from utils.cas import store
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler


def _handler(pool):
    h = WorkflowExecutionHandler(sio=None)
    h.get_pool = AsyncMock(return_value=pool)
    return h


@pytest.fixture(autouse=True)
def _route_cas_pool_to_testdb(cas_pool):
    """The handler + iteration persist paths resolve their CAS pool via
    get_native_pool() (function-level import from utils.database_pool), which
    in tests is either uninitialized or pointed at the wrong DB. Point it at
    the committed testcontainer pool so the REAL persist path runs against
    the test DB."""
    with patch("utils.database_pool.get_native_pool", return_value=cas_pool):
        yield


@pytest.mark.asyncio
class TestHandlerCasRouting:
    async def test_persist_routes_to_cas(self, cas_pool):
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        handler = _handler(cas_pool)
        handler._execution_node_statuses = {
            str(eid): {"n1": {"status": "completed", "error": None}}}
        node_outputs = {"n1": {"big": list(range(2000))}}
        with patch_r2(FakeR2()):
            await handler._persist_node_outputs(
                str(wid), str(TEST_USER_ID), node_outputs,
                execution_id=str(eid), executable_nodes=[{"id": "n1", "type": "x"}])
            got = await store.read_node_output(cas_pool, execution_id=eid, node_id="n1")
        assert got == node_outputs["n1"]
        async with cas_pool.acquire() as c:
            assert await c.fetchval(
                "SELECT last_run_status FROM cas_manifests WHERE execution_id=$1 AND node_id='n1'", eid) == "completed"

    async def test_cas_status_only_node_no_output(self, cas_pool):
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        handler = _handler(cas_pool)
        # a skipped node: status present, no output
        handler._execution_node_statuses = {
            str(eid): {"n2": {"status": "skipped", "error": None}}}
        with patch_r2(FakeR2()):
            await handler._persist_node_outputs(
                str(wid), str(TEST_USER_ID), {},
                execution_id=str(eid), executable_nodes=[{"id": "n2", "type": "x"}])
        async with cas_pool.acquire() as c:
            row = await c.fetchrow(
                "SELECT manifest, last_run_status FROM cas_manifests "
                "WHERE execution_id=$1 AND node_id='n2'", eid)
        assert row["manifest"] is None          # status-only → SQL NULL manifest
        assert row["last_run_status"] == "skipped"

    async def test_set_variable_mirrors_to_workflow_variables(self, cas_pool, codec_pool):
        """A set-variable node's assignments are mirrored into
        workflows.workflow->variables (the one JSONB write kept post-cutover) so
        {{vars.X}} resolves in later/partial runs."""
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        async with cas_pool.acquire() as c:
            await c.execute(
                "UPDATE workflows SET workflow=$1::jsonb WHERE id=$2",
                json.dumps({"nodes": [], "edges": [], "variables": {"keep": "me"}}), wid)
        handler = _handler(codec_pool)
        handler._execution_node_statuses = {}
        sv_output = {"assignments": [{"variable_name": "row_num", "value": 42}]}
        with patch_r2(FakeR2()):
            await handler._persist_node_outputs(
                str(wid), str(TEST_USER_ID), {"sv": sv_output},
                execution_id=str(eid), executable_nodes=[{"id": "sv", "type": "set-variable"}])
        async with cas_pool.acquire() as c:
            variables = await c.fetchval(
                "SELECT workflow->'variables' FROM workflows WHERE id=$1", wid)
        variables = json.loads(variables) if isinstance(variables, str) else variables
        assert variables == {"keep": "me", "row_num": 42}  # merged, not clobbered

    async def test_set_variable_denied_without_edit_access(self, cas_pool):
        """A runner with NO edit access (not owner, no share row) must NOT be able
        to mutate workflows.workflow->variables via the set-variable mirror. The
        gate in _persist_set_variables (check_resource_access → EDIT/OWNER) drops
        the write; existing variables are left untouched."""
        wid = await make_workflow(cas_pool)  # owner = TEST_USER_ID
        eid = await make_execution(cas_pool, wid)
        async with cas_pool.acquire() as c:
            await c.execute(
                "UPDATE workflows SET workflow=$1::jsonb WHERE id=$2",
                json.dumps({"nodes": [], "edges": [], "variables": {"keep": "me"}}), wid)
        # A different user with no permission row on this workflow.
        intruder = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
        handler = _handler(cas_pool)
        handler._execution_node_statuses = {}
        sv_output = {"assignments": [{"variable_name": "x", "value": 1}]}
        with patch_r2(FakeR2()):
            await handler._persist_node_outputs(
                str(wid), str(intruder), {"sv": sv_output},
                execution_id=str(eid), executable_nodes=[{"id": "sv", "type": "set-variable"}])
        async with cas_pool.acquire() as c:
            variables = await c.fetchval(
                "SELECT workflow->'variables' FROM workflows WHERE id=$1", wid)
        variables = json.loads(variables) if isinstance(variables, str) else variables
        assert variables == {"keep": "me"}  # gate denied → unchanged

    async def test_set_variable_legacy_single_variable_compat(self, cas_pool, codec_pool):
        """Legacy set-variable output shape (flat variable_name/value, no
        'assignments' key) is still mirrored — backward-compat path in
        _persist_set_variables. Owner runs, so the gate allows the write."""
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        async with cas_pool.acquire() as c:
            await c.execute(
                "UPDATE workflows SET workflow=$1::jsonb WHERE id=$2",
                json.dumps({"nodes": [], "edges": [], "variables": {"keep": "me"}}), wid)
        handler = _handler(codec_pool)
        handler._execution_node_statuses = {}
        sv_output = {"variable_name": "legacy", "value": 7}  # no assignments key
        with patch_r2(FakeR2()):
            await handler._persist_node_outputs(
                str(wid), str(TEST_USER_ID), {"sv": sv_output},
                execution_id=str(eid), executable_nodes=[{"id": "sv", "type": "set-variable"}])
        async with cas_pool.acquire() as c:
            variables = await c.fetchval(
                "SELECT workflow->'variables' FROM workflows WHERE id=$1", wid)
        variables = json.loads(variables) if isinstance(variables, str) else variables
        assert variables == {"keep": "me", "legacy": 7}  # legacy single var merged

    async def test_persist_node_outputs_swallows_persist_errors(self, cas_pool):
        """_persist_node_outputs is fire-and-forget: a raise inside the underlying
        persist_outputs must NOT propagate (it's spawned, not awaited by the
        caller). Pin the swallow so a CAS write failure can't crash a run."""
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        handler = _handler(cas_pool)
        handler._execution_node_statuses = {
            str(eid): {"n1": {"status": "completed", "error": None}}}

        async def _boom(*a, **k):
            raise RuntimeError("simulated CAS persist failure")

        with patch_r2(FakeR2()), \
                patch("utils.node_outputs.persist_outputs", _boom):
            # Must return without raising.
            await handler._persist_node_outputs(
                str(wid), str(TEST_USER_ID), {"n1": {"v": 1}},
                execution_id=str(eid), executable_nodes=[{"id": "n1", "type": "x"}])
        # Persist failed, so nothing landed in the CAS.
        async with cas_pool.acquire() as c:
            count = await c.fetchval(
                "SELECT COUNT(*) FROM cas_manifests WHERE execution_id=$1", eid)
        assert count == 0


# Iteration persists are fire-and-forget (utils.async_helpers.spawn) — drain
# them so the CAS rows are committed before we assert.
from tests.utils.task_helpers import drain_spawned_tasks as _drain_spawned_tasks


def _iter_handler(cas_pool):
    """Handler wired for driving the iteration strategy: a real AsyncMock sio (so
    emit_state/emit_output don't NPE on a None sio) + get_pool → cas_pool."""
    sio = AsyncMock()
    sio.emit = AsyncMock()
    h = WorkflowExecutionHandler(sio=sio)
    h.get_pool = AsyncMock(return_value=cas_pool)
    return h


@pytest.mark.asyncio
class TestIterationSubOutputCasWrite:
    """Drives the real IterationExecutionStrategy through _execute_nodes_concurrent
    with a REAL execution_id so the iteration persist branch (iteration_node.py,
    gated on ctx.execution_id and not iteration_failed) actually writes sub-outputs
    to the CAS under composite '<body>#iter:N' keys.

    The branch resolves its CAS pool via get_native_pool() (the one native
    asyncpg pool); the autouse fixture points that at the committed cas_pool, so
    the real persist_run_outputs runs: chunking, manifest, R2 PUT, composite
    keys, and the not-iteration-failed gate all execute against the test DB.
    """

    async def test_iteration_persists_sub_outputs_under_real_execution(self, cas_pool):
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        handler = _iter_handler(cas_pool)

        async def mock_execute_node(node, node_outputs, *args, **kwargs):
            ntype = node.get("type", "")
            if ntype == "iteration":
                return {
                    "items": [{"v": 1}, {"v": 2}],
                    "total": 2,
                    "item": {"v": 1},
                    "index": 0,
                    "isIterationNode": True,
                }
            # body node
            item = node_outputs.get("item", {})
            return {"got": item.get("v")}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 1}}},
            {"id": "body", "type": "body-node", "config": {}},
        ]
        edges = [{"source": "iteration-1", "target": "body", "sourceHandle": "loop"}]

        with patch_r2(FakeR2()):
            nodes_executed, error, _ = await handler._execute_nodes_concurrent(
                nodes, edges, "test-sid", str(TEST_USER_ID), str(wid),
                execution_id=str(eid))
            assert error is None
            await _drain_spawned_tasks()

            # Both iterations persisted under composite keys for the real execution.
            async with cas_pool.acquire() as c:
                iter_ids = await c.fetch(
                    "SELECT node_id FROM cas_manifests "
                    "WHERE execution_id=$1 ORDER BY node_id", eid)
            iter_node_ids = {r["node_id"] for r in iter_ids}
            assert "body#iter:0" in iter_node_ids
            assert "body#iter:1" in iter_node_ids

            # History surfaces both iterations under the body node (prefix match).
            history = await store.read_node_output_history(cas_pool, wid, "body")
            outputs = sorted(h["output"]["got"] for h in history)
            assert outputs == [1, 2]

            # The canvas-hydrate read excludes composite iter keys → no bare 'body'.
            latest = await store.read_latest_node_outputs(cas_pool, wid)
        assert "body" not in latest
        # And there's no bare 'body' manifest either (only the composite keys).
        assert "body" not in iter_node_ids

    async def test_iteration_failed_item_skips_persist(self, cas_pool):
        """The 'not iteration_failed' gate: an iteration whose body raises is NOT
        persisted, while a sibling iteration that succeeds IS. Body raises on
        item 0 (v==1) and succeeds on item 1 (v==2) → no 'body#iter:0' row, a
        'body#iter:1' row."""
        wid = await make_workflow(cas_pool)
        eid = await make_execution(cas_pool, wid)
        handler = _iter_handler(cas_pool)

        async def mock_execute_node(node, node_outputs, *args, **kwargs):
            ntype = node.get("type", "")
            if ntype == "iteration":
                return {
                    "items": [{"v": 1}, {"v": 2}],
                    "total": 2,
                    "item": {"v": 1},
                    "index": 0,
                    "isIterationNode": True,
                }
            item = node_outputs.get("item", {})
            if item.get("v") == 1:
                raise RuntimeError("body blew up on item 0")
            return {"got": item.get("v")}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 1}}},
            {"id": "body", "type": "body-node", "config": {}},
        ]
        edges = [{"source": "iteration-1", "target": "body", "sourceHandle": "loop"}]

        with patch_r2(FakeR2()):
            await handler._execute_nodes_concurrent(
                nodes, edges, "test-sid", str(TEST_USER_ID), str(wid),
                execution_id=str(eid))
            await _drain_spawned_tasks()
            async with cas_pool.acquire() as c:
                rows = await c.fetch(
                    "SELECT node_id FROM cas_manifests WHERE execution_id=$1", eid)
        node_ids = {r["node_id"] for r in rows}
        assert "body#iter:0" not in node_ids  # failed iteration → not persisted
        assert "body#iter:1" in node_ids      # successful sibling → persisted
