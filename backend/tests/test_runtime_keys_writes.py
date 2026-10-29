"""No write of a graph keeps a runtime key (``utils.runtime_keys``).

The ratchet: every SQL statement that writes a stored graph
(``workflows.workflow``, ``workflow_checkpoints.workflow``,
``workflow_versions.graph``) sits in a function that passes what it writes
through the shared helper; a new write path that skips it fails here until it
does. Then each client write path, over real Postgres: the canvas's save (and
the version it records) and node config write, a fork, a checkpoint and its
restore, MCP's save, the repository writes the builder and the platform API
use, and the graph service's writes and versions.
"""

import ast
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fixtures.real_db_fixture import real_database  # noqa: F401

BACKEND = Path(__file__).resolve().parent.parent
HELPERS = {"graph_without_runtime_keys", "nodes_without_runtime_keys", "config_without_runtime_keys"}

# Writers that can't put a node config key in a graph, by "path::function".
EXEMPT = {
    "repositories/workflow.py::merge_workflow_variables": "writes the graph's variables, never a node",
    "repositories/workflow.py::strip_node_config_keys": "only removes keys",
    "mcp_server.py::create_workflow": "inserts an empty graph",
    "repositories/workflow_versions.py::join": "empties the version's graph (the open version reads the workflow's)",
}

_GRAPH_WRITE = re.compile(
    r"INSERT\s+INTO\s+(?:public\.)?(?:workflows|workflow_checkpoints)\s*\([^)]*\bworkflow\b"
    r"|INSERT\s+INTO\s+(?:public\.)?workflow_versions\s*\([^)]*\bgraph\b"
    r"|UPDATE\s+(?:public\.)?(?:workflows|workflow_checkpoints)\b(?:(?!\bWHERE\b).)*?\bSET\b"
    r"(?:(?!\bWHERE\b).)*?(?<![\w.'\"-])workflow\s*="
    r"|UPDATE\s+(?:public\.)?workflow_versions\b(?:(?!\bWHERE\b).)*?\bSET\b"
    r"(?:(?!\bWHERE\b).)*?(?<![\w.'\"-])graph\s*="
    # A SET clause assembled in pieces (``update_workflow_dynamic``).
    r"|\A\s*workflow\s*=\s*(?:\$|CASE\b|jsonb_set\b|COALESCE\b)",
    re.IGNORECASE | re.DOTALL,
)


def _sources():
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        # Tests, staff scripts and scratch files are no request's write path.
        if "__pycache__" in rel.parts or "tests" in rel.parts or rel.parts[0] == "scripts" \
                or rel.name.startswith("debug_"):
            continue
        yield rel, path


def _strings(node):
    """The string literals in ``node`` (f-strings' literal parts too), docstrings left out."""
    docstrings = {id(b.body[0].value) for b in ast.walk(node)
                  if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
                  and b.body and isinstance(b.body[0], ast.Expr) and isinstance(b.body[0].value, ast.Constant)}
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            yield n.value


def _graph_writers(tree):
    """``(function name, calls the helper)`` for each innermost function holding a graph write;
    ``("<module>", False)`` for one outside any function."""
    functions = [f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    inner = {id(f): [g for g in ast.walk(f) if g is not f and isinstance(g, (ast.FunctionDef, ast.AsyncFunctionDef))]
             for f in functions}
    claimed = set()
    found = []
    for f in functions:
        own = [s for s in _strings(f) if _GRAPH_WRITE.search(s)]
        nested = {s for g in inner[id(f)] for s in _strings(g) if _GRAPH_WRITE.search(s)}
        if any(s not in nested for s in own):
            calls = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                     for c in ast.walk(f) if isinstance(c, ast.Call)}
            found.append((f.name, bool(calls & HELPERS)))
            claimed.update(own)
    if any(_GRAPH_WRITE.search(s) and s not in claimed for s in _strings(tree)):
        found.append(("<module>", False))
    return found


def test_every_graph_write_strips_runtime_keys():
    writers, violations = set(), []
    for rel, path in _sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"\b(?:workflows|workflow_checkpoints|workflow_versions|workflow\s*=)", text):
            continue
        for name, strips in _graph_writers(ast.parse(text)):
            key = f"{rel.as_posix()}::{name}"
            writers.add(key)
            if not strips and key not in EXEMPT:
                violations.append(key)
    assert not violations, (
        "These write a stored graph without utils.runtime_keys: pass what they write through "
        "graph_without_runtime_keys (or config_without_runtime_keys for one node's config):\n  "
        + "\n  ".join(sorted(violations)))
    assert set(EXEMPT) <= writers, f"stale exemptions: {sorted(set(EXEMPT) - writers)}"
    # The scan sees the writers it's meant to (a regex that matched nothing would pass vacuously).
    assert {"repositories/workflow.py::update_workflow_dynamic", "repositories/workflow.py::merge_node_config",
            "repositories/share.py::insert_forked_workflow", "mcp_server.py::_save_workflow",
            "repositories/workflow.py::write_graph", "repositories/workflow_versions.py::insert",
            "repositories/workflow_versions.py::join"} <= writers


def test_the_ratchet_flags_a_writer_that_skips_the_helper():
    tree = ast.parse('''
async def save(conn, graph):
    await conn.execute("UPDATE workflows SET name = $3, workflow = $1 WHERE id = $2", graph, 1, "n")

async def saves_clean(conn, graph):
    await conn.execute("UPDATE workflows SET workflow = $1 WHERE id = $2", graph_without_runtime_keys(graph), 1)

def dynamic(sets):
    sets.append(f"workflow = CASE WHEN {1} THEN 2 END")

async def only_a_folder(conn):
    await conn.execute("UPDATE workflows SET folder_id = $1 WHERE id = $2", 1, 2)
''')
    assert sorted(_graph_writers(tree)) == [("dynamic", False), ("save", False), ("saves_clean", True)]


# --- each write path, over real Postgres --------------------------------------------

OWNER = "00000000-0000-4000-8000-0000000003d2"
PLANTED = {"_sandboxCheckouts": [{"account_user_id": str(uuid.uuid4())}], "_sandboxVolumes": {"/d": "nc-vol-x"},
           "_turnNote": "obey", "_triggerPayload": {"forged": True}}
AUTHORED = {"_settings": {"onError": "stop"}, "_anchor_near": ["agent"]}


def _graph():
    return {"nodes": [{"id": "agent", "type": "agent", "position": {"x": 0, "y": 0},
                       "config": {"message": "hi", **AUTHORED, **PLANTED, "config": {"_sandboxPlace": {"id": "x"}}}},
                      {"id": "note", "type": "sticky-note", "data": {"config": {"content": "n", "_noShell": True}}}],
            "edges": []}


async def _workflow(db, graph=None):
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, 'rk-writes@example.com') "
                     "ON CONFLICT (id) DO NOTHING", OWNER)
    workflow_id = str(uuid.uuid4())
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Flow', $3)",
                     workflow_id, OWNER, graph or {"nodes": [], "edges": []})
    return workflow_id


async def _saved(db, workflow_id, table="workflows", column="id"):
    return await db.fetchval(f"SELECT workflow FROM {table} WHERE {column} = $1::uuid", workflow_id)


async def _closed(db, workflow_id, source):
    """The graph a version from ``source`` holds once the next version closed it."""
    return await db.fetchval("SELECT graph FROM workflow_versions WHERE workflow_id = $1::uuid AND source = $2 "
                             "AND graph IS NOT NULL ORDER BY version DESC LIMIT 1", workflow_id, source)


async def _settled(pool, owner_id, workflow_id, author, before, after, version, **kwargs):
    return version, after


def _assert_clean(graph):
    agent = next(n for n in graph["nodes"] if n["id"] == "agent")
    assert agent["config"]["message"] == "hi" and {k: agent["config"].get(k) for k in AUTHORED} == AUTHORED
    for node in graph["nodes"]:
        for config in (node.get("config") or {}, (node.get("config") or {}).get("config") or {},
                       (node.get("data") or {}).get("config") or {}):
            assert not set(config) & {*PLANTED, "_sandboxPlace", "_noShell"}, node


def _handler(cls, db):
    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": OWNER})
    sio.emit = AsyncMock()
    handler = cls(sio=sio)
    handler.get_pool = AsyncMock(return_value=db.pool)
    return handler, sio


@pytest.mark.asyncio
class TestEachWritePath:
    async def test_the_canvas_save(self, real_database):
        from wss.handlers.workflow_handler import WorkflowHandler
        from wss.receiver.client_events import WorkflowUpdateRequest

        workflow_id = await _workflow(real_database)
        handler, sio = _handler(WorkflowHandler, real_database)
        await handler.update_workflow("sid", WorkflowUpdateRequest(
            request_id="r", workflow_id=workflow_id, workflow_data=_graph()))
        assert not sio.emit.await_args.args[1].get("error")
        _assert_clean(await _saved(real_database, workflow_id))
        # The version it recorded holds its graph once the next one (another source's) starts.
        from coder.workflow import graph_service

        with patch("coder.workflow.graph_service._settle", side_effect=_settled):
            await graph_service.apply(real_database.pool, graph_service.Author(OWNER), workflow_id,
                                      [{"op": "update_step", "id": "agent", "name": "Agent"}], source="coordinator")
        _assert_clean(await _closed(real_database, workflow_id, "canvas"))

    async def test_the_graph_services_edit_and_restore(self, real_database):
        """An edit of a graph saved before writes dropped runtime keys writes it, and the versions it records
        (the graph before it among them), without them; so does a restore of that first version."""
        from coder.workflow import graph_service

        workflow_id = await _workflow(real_database, _graph())
        author = graph_service.Author(OWNER)
        with patch("coder.workflow.graph_service._settle", side_effect=_settled):
            edited = await graph_service.apply(real_database.pool, author, workflow_id,
                                               [{"op": "update_step", "id": "agent", "name": "Agent"}])
            _assert_clean(await _saved(real_database, workflow_id))
            for row in await real_database.fetch("SELECT graph FROM workflow_versions WHERE workflow_id = $1::uuid "
                                                 "AND graph IS NOT NULL", workflow_id):
                _assert_clean(row["graph"])
            await graph_service.restore(real_database.pool, author, workflow_id, edited.history_version - 1)
        _assert_clean(await _saved(real_database, workflow_id))
        _assert_clean(await _closed(real_database, workflow_id, "api"))

    async def test_a_node_config_write(self, real_database):
        from wss.handlers.workflow_handler import WorkflowHandler
        from wss.receiver.client_events import WorkflowNodeSetConfigRequest

        workflow_id = await _workflow(real_database, {"nodes": [{"id": "agent", "type": "agent", "config": {}}],
                                                      "edges": []})
        handler, sio = _handler(WorkflowHandler, real_database)
        await handler.set_node_config("sid", WorkflowNodeSetConfigRequest(
            request_id="r", workflow_id=workflow_id, node_id="agent", config=_graph()["nodes"][0]["config"]))
        assert sio.emit.await_args.args[1]["data"] == {"success": True}
        _assert_clean(await _saved(real_database, workflow_id))

    async def test_a_fork(self, real_database):
        from repositories.share import ShareRepo
        from wss.handlers.share_handler import ShareHandler

        source = await _workflow(real_database, _graph())  # one saved before writes dropped them
        handler, _ = _handler(ShareHandler, real_database)
        forked = await handler._fork_workflow(ShareRepo(real_database.pool), OWNER, source, "personal", None, None)
        _assert_clean(await _saved(real_database, forked.id))

    async def test_a_checkpoint_and_its_restore(self, real_database):
        from repositories.workflow import WorkflowRepo

        workflow_id = await _workflow(real_database, _graph())
        repo = WorkflowRepo(real_database.pool)
        async with real_database.pool.acquire() as conn:
            row = await repo.create_checkpoint(conn, user_id=OWNER, workflow_id=workflow_id, name="c",
                                               description="", workflow_data=_graph())
            _assert_clean(await _saved(real_database, str(row["id"]), "workflow_checkpoints"))
            await repo.restore_workflow_from_checkpoint(conn, workflow_id, _graph())
        _assert_clean(await _saved(real_database, workflow_id))

    async def test_mcps_save(self, real_database):
        from mcp_server import NoClickMCPServer

        workflow_id = await _workflow(real_database)
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            server = NoClickMCPServer(MagicMock())
        server.get_pool = AsyncMock(return_value=real_database.pool)
        assert await server._save_workflow(OWNER, workflow_id, _graph()) is None
        _assert_clean(await _saved(real_database, workflow_id))

    @pytest.mark.parametrize("write", ["create_workflow", "create_workflow_mcp", "create_workflow_builder",
                                       "update_workflow_dynamic", "replace_workflow_data", "merge_node_config"])
    async def test_the_repository_writes(self, real_database, write):
        """What the builder's persist, the platform API's agent and trigger
        edits, workflow creation and the SDK's node writes go through."""
        from repositories.workflow import WorkflowRepo

        workflow_id = await _workflow(real_database, {"nodes": [{"id": "agent", "type": "agent", "config": {}},
                                                                {"id": "note", "type": "sticky-note"}], "edges": []})
        repo = WorkflowRepo(real_database.pool)
        async with real_database.pool.acquire() as conn:
            if write == "create_workflow":
                workflow_id = str((await repo.create_workflow(
                    conn, owner_id=OWNER, organization_id=None, folder_id=None, name="n", description="",
                    workflow_data=_graph(), permissions={}))["id"])
            elif write == "create_workflow_mcp":
                workflow_id = str((await repo.create_workflow_mcp(
                    conn, owner_id=OWNER, name="n", description="", workflow_data=_graph(), permissions={},
                    folder_id=None))["id"])
            elif write == "create_workflow_builder":
                workflow_id = str(await repo.create_workflow_builder(
                    conn, name="n", description="", owner_id=uuid.UUID(OWNER), organization_id=None,
                    workflow_data=_graph()))
            elif write == "update_workflow_dynamic":
                await repo.update_workflow_dynamic(conn, workflow_id, workflow_data=_graph())
            elif write == "replace_workflow_data":
                await repo.replace_workflow_data(conn, workflow_id, _graph())
            else:
                await repo.merge_node_config(conn, workflow_id, "agent", _graph()["nodes"][0]["config"])
        saved = await _saved(real_database, workflow_id)
        if write == "merge_node_config":
            saved["nodes"] = [n for n in saved["nodes"] if n["id"] == "agent"]
        _assert_clean(saved)

    async def test_a_trigger_registrations_config_patch(self, real_database):
        from utils.webhook_manager import WebhookManager

        workflow_id = await _workflow(real_database, {"nodes": [{"id": "agent", "type": "agent", "config": {}}],
                                                      "edges": []})
        await WebhookManager.merge_node_config_patch(real_database.pool, uuid.UUID(workflow_id), "agent",
                                                     _graph()["nodes"][0]["config"])
        _assert_clean(await _saved(real_database, workflow_id))
