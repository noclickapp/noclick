"""The graph service over real PostgreSQL (``coder.workflow.graph_service``):
one transaction per batch of edits, refused whole on a stale version or a bad
op, recorded as versions of the whole definition (joined within five minutes
for one author and source, undoable by a restore), judged for who may edit,
never reading out a secret nor losing one a write didn't send back, and
followed after the commit by the reconcile every graph write gets and one
notice to whoever watches, at the version the reconcile left. The canvas's
save records its versions and runs the same reconcile."""

import copy
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coder.workflow import graph_service
from coder.workflow.graph_service import Author, GraphError
from tests.fixtures.real_db_fixture import real_database  # noqa: F401

pytestmark = pytest.mark.asyncio

OWNER = "00000000-0000-4000-8000-00000000a001"
OTHER = "00000000-0000-4000-8000-00000000a002"
EDITOR = "00000000-0000-4000-8000-00000000a003"
VIEWER = "00000000-0000-4000-8000-00000000a004"


def node(node_id, kind, **config):
    return {"id": node_id, "type": kind, "position": {"x": 0, "y": 0}, "config": config}


GRAPH = {
    "nodes": [node("hook", "trigger-webhook", label="Hook", webhook_url="https://hooks.example/1"),
              node("agent", "agent", label="Helper", model="openrouter/~openai/gpt-luna-latest", message="Sum up."),
              node("log", "log", label="Log", message="done")],
    "edges": [{"id": "hook-agent", "source": "hook", "target": "agent"}],
}


@pytest.fixture
async def db(real_database):
    for user in (OWNER, OTHER, EDITOR, VIEWER):
        await real_database.execute("INSERT INTO auth.users (id, email) VALUES ($1::uuid, $2) ON CONFLICT (id) "
                                    "DO NOTHING", user, f"{user[-4:]}@graph.example")
    return real_database


@pytest.fixture(autouse=True)
def _receives_mail(monkeypatch):
    """An installation whose inboxes get addresses (every edition: the open one's needs a domain set)."""
    monkeypatch.setattr("utils.email_reservation_manager.get_inbound_email_domain", lambda: "graph.example")


@pytest.fixture
def told():
    """The notices (the owner's pages, the canvases' room), as (owner, workflow, version)."""
    calls = []

    async def tell(owner_id, workflow_id, version, canvas=(), *, base):
        calls.append((owner_id, workflow_id, version))

    with patch("coder.workflow.graph_service.tell", side_effect=tell):
        yield calls


@pytest.fixture
def reconciled():
    """Each reconcile job's work the workflow's worker ran, as (user, the steps it touched as they were, as the
    write left them)."""
    calls = []

    async def reconcile(pool, workflow_id, user_id, old, new, deleted):
        calls.append((user_id, old, new))

    with patch("utils.workflow_reconcile._reconcile", side_effect=reconcile):
        yield calls


@pytest.fixture
def room():
    """What the workflow's room on the relay carried (every canvas open on it hears it); no owner's frame."""
    heard = []

    class Room:
        def __init__(self, workflow_id, execution_id, user_id, **kwargs):
            pass

        def start(self):
            return None

        async def send_event(self, event):
            heard.append(event)

        async def close(self):
            return None

    with patch("utils.execution_relay.create_execution_relay", Room), \
            patch("utils.capabilities.capability", lambda name: None):
        yield heard


async def _workflow(db, graph=GRAPH, *, owner=OWNER, settings=None) -> str:
    return str(await db.fetchval(
        "INSERT INTO workflows (owner_id, name, workflow, settings) VALUES ($1::uuid, 'Flow', $2, $3) RETURNING id",
        owner, copy.deepcopy(graph), settings or {}))


async def _graph(db, workflow_id):
    return await db.fetchrow("SELECT workflow, graph_version, name FROM workflows WHERE id = $1::uuid", workflow_id)


async def _versions(db, workflow_id):
    return [dict(r) for r in await db.fetch(
        "SELECT history_version, version, source, author_user_id::text AS author, author_key_id, changes, restored_from "
        "FROM workflow_versions WHERE workflow_id = $1::uuid ORDER BY version", workflow_id)]


async def _apply(db, workflow_id, ops, *, author=Author(OWNER), **kwargs):
    """An edit, and its notices (sent off the answer's path)."""
    from utils.async_helpers import drain_spawned_tasks

    edited = await graph_service.apply(db.pool, author, workflow_id, ops, **kwargs)
    await drain_spawned_tasks(timeout=5)
    return edited


async def _restore(db, workflow_id, number, *, author=Author(OWNER), **kwargs):
    """A restore, and what runs after it (its notices, its reconcile job)."""
    from utils.async_helpers import drain_spawned_tasks

    restored = await graph_service.restore(db.pool, author, workflow_id, number, **kwargs)
    await drain_spawned_tasks(timeout=5)
    return restored


async def _job_status(db, job_id):
    return await db.fetchval("SELECT status FROM workflow_reconcile_jobs WHERE id = $1", job_id)


async def _share(db, workflow_id, user, permission):
    await db.execute("INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, "
                     "permission, shared_by) VALUES ('workflow', $1::uuid, 'user', $2::uuid, $3, $4::uuid)",
                     workflow_id, user, permission, OWNER)


async def _credential(db, owner, kind) -> str:
    return str(await db.fetchval("INSERT INTO credentials (owner_id, name, credential_type, credential) "
                                 "VALUES ($1::uuid, 'test', $2, 'x') RETURNING id", owner, kind))


def _labels(graph):
    return {n["id"]: (n.get("config") or {}).get("label") for n in graph["nodes"]}


class TestWrites:
    async def test_an_edit_lands_as_one_version_and_answers_its_number(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"},
                                                {"op": "connect", "from": "agent", "to": "log"}],
                              include_graph=True)
        row = await _graph(db, workflow_id)
        assert (edited.version, edited.history_version, row["graph_version"]) == (2, 2, 2)
        assert _labels(row["workflow"])["log"] == "Record" and edited.changed
        assert edited.summary == "renamed 'Log' to 'Record'; connected 'Helper' to 'Record'"
        graph = edited.definition["graph"]
        assert graph["nodes"] == row["workflow"]["nodes"] and graph["withheld"] == {}
        assert (edited.definition["name"], edited.definition["settings"]) == ("Flow", {})
        # The graph it had before is its first version, so this edit can be undone.
        assert [(v["version"], v["source"], v["author"]) for v in await _versions(db, workflow_id)] == [
            (1, "baseline", None), (2, "api", OWNER)]
        assert told == [(OWNER, workflow_id, 2)]
        [(user, old, new)] = reconciled
        assert user == OWNER and _labels(old)["log"] == "Log" and _labels(new)["log"] == "Record"

    async def test_every_canvas_open_on_it_is_sent_what_changed_then_the_version(self, db, reconciled, room):
        """Whoever's canvas it is (a collaborator's too): the workflow's room carries the change as the builder's
        events, then one notice of the version."""
        heard = room
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"},
                                       {"op": "remove_step", "id": "hook"}])
        assert heard[-1] == {"type": "workflow:graph_changed", "workflow_id": workflow_id, "base_version": 1,
                             "version": 2}
        # Written changes: a canvas takes them as the server's state, its base for a conflict's merge.
        assert all(e["committed"] is True for e in heard[:-1])
        assert [(e["type"], e["event_type"], e["data"]) for e in heard[:-1]] == [
            ("mcp:builder_event", "node_removed", {"nodeId": "hook", "removedEdgeIds": ["hook-agent"]}),
            ("mcp:builder_event", "node_updated", {"nodeId": "log", "config": {"label": "Record"}})]

    async def test_the_room_never_carries_a_secret_or_an_outsize_setting(self, db, reconciled, room):
        """A step's secrets, and a setting too big to send, stay out of the room: the canvas fetches that step
        through its own authorized read (``refetch``)."""
        import json

        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "add_step", "type": "automation-http-request", "id": "fetch",
                                        "operation": "send_http_get_request", "settings": {
                                            "url": "https://api.example", "api_key": "sk-live-SECRET",
                                            "headers": [{"key": "Authorization", "value": "Bearer HDR-SECRET"}]}}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "fetch", "settings": {"api_key": "sk-NEW"}},
                                       {"op": "update_step", "id": "log", "settings": {"message": "x" * 200_000}}])
        sent = json.dumps(room)
        assert "SECRET" not in sent and "sk-NEW" not in sent and "x" * 1000 not in sent
        updates = {(e["data"]["nodeId"], json.dumps(e["data"], sort_keys=True))
                   for e in room if e.get("event_type") == "node_updated"}
        added = next(json.loads(d) for n, d in updates if n == "fetch" and "type" in json.loads(d))
        assert added["refetch"] is True and added["config"]["url"] == "https://api.example"
        assert added["config"]["headers"] == [{"key": "Authorization"}] and "api_key" not in added["config"]
        changed = [json.loads(d) for n, d in updates if n == "fetch" and "type" not in json.loads(d)]
        assert changed == [{"nodeId": "fetch", "refetch": True, "config": {}}]
        outsize = [json.loads(d) for n, d in updates if n == "log"]
        assert outsize == [{"nodeId": "log", "refetch": True}]

    async def test_a_stale_version_is_refused_with_the_workflow_as_it_stands(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}], if_version=1)
        with pytest.raises(GraphError) as stale:
            await _apply(db, workflow_id, [{"op": "remove_step", "id": "log"}], if_version=1)
        assert stale.value.kind == "stale" and stale.value.details["version"] == 2
        assert _labels(stale.value.details["graph"])["log"] == "Record"
        row = await _graph(db, workflow_id)
        assert row["graph_version"] == 2 and "log" in _labels(row["workflow"])

    async def test_a_batch_lands_whole_or_not_at_all(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        local = f"orders-{uuid.uuid4().hex[:8]}"
        with pytest.raises(GraphError) as refused:
            await _apply(db, workflow_id, [
                {"op": "add_step", "type": "trigger-email", "id": "inbox", "settings": {"local_part": local}},
                {"op": "update_step", "id": "log", "name": "Record"},
                {"op": "remove_step", "id": "ghost"},
            ])
        assert (refused.value.kind, refused.value.details["op"]) == ("invalid", 2)
        row = await _graph(db, workflow_id)
        assert row["graph_version"] == 1 and row["workflow"] == GRAPH
        assert await _versions(db, workflow_id) == [] and told == [] and reconciled == []
        # The inbox the first op claimed went with the rest of the batch.
        assert await db.fetchval("SELECT count(*) FROM email_reservations WHERE workflow_id = $1::uuid",
                                 workflow_id) == 0

    async def test_a_claimed_inbox_lands_with_its_step(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        local = f"orders-{uuid.uuid4().hex[:8]}"
        await _apply(db, workflow_id, [{"op": "add_step", "type": "trigger-email", "id": "inbox",
                                        "settings": {"local_part": local}}])
        config = next(n for n in (await _graph(db, workflow_id))["workflow"]["nodes"] if n["id"] == "inbox")["config"]
        assert config["local_part"] == local and config["email_address"].startswith(f"{local}@")
        other = await _workflow(db)
        with pytest.raises(GraphError) as taken:
            await _apply(db, other, [{"op": "add_step", "type": "trigger-email", "settings": {"local_part": local}}])
        assert taken.value.kind == "invalid" and "taken" in taken.value.message

    async def test_the_model_list_is_read_before_the_workflow_is_locked(self, db, told, reconciled, monkeypatch):
        """Resolving a model can rebuild the model list with a blocking fetch: that happens off the event loop,
        before the row lock is taken, never under it."""
        import threading

        from coder.workflow.option_registries import MODELS_REGISTRY
        from coder.workflow.option_registries.base import Option

        built = []

        def build():
            built.append(threading.current_thread() is threading.main_thread())
            return [Option(id="openrouter/~openai/gpt-luna-latest", label="Luna")]

        monkeypatch.setattr(MODELS_REGISTRY, "_build", build)
        monkeypatch.setattr(MODELS_REGISTRY, "_has_succeeded", False)
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "agent",
                                        "settings": {"model": "openrouter/~openai/gpt-luna-latest"}}])
        assert built == [False]

    async def test_moving_things_is_no_version_and_needs_no_reconcile(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "move", "id": "log", "position": {"x": 400, "y": 80}}])
        assert (edited.version, edited.history_version, edited.summary) == (2, None, "")
        assert await _versions(db, workflow_id) == [] and reconciled == []
        assert told == [(OWNER, workflow_id, 2)]

    async def test_a_noop_writes_nothing(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "connect", "from": "hook", "to": "agent"}])
        assert (edited.version, edited.changed, edited.history_version) == (1, False, None) and told == []

    async def test_the_workflows_own_fields_are_written_beside_the_graph(self, db, told, reconciled):
        workflow_id = await _workflow(db, settings={"variable_definitions": [{"name": "a", "value": "1"}]})
        edited = await _apply(db, workflow_id, [
            {"op": "update_workflow", "name": "Refunds", "description": "Answers  refund\nmail."},
            {"op": "define_variable", "name": "region", "value": "eu"},
        ])
        row = await db.fetchrow("SELECT name, description, settings, graph_version FROM workflows "
                                "WHERE id = $1::uuid", workflow_id)
        assert (row["name"], row["description"]) == ("Refunds", "Answers refund mail.")
        assert [d["name"] for d in row["settings"]["variable_definitions"]] == ["a", "region"]
        # A version like any write's, with nothing to reconcile: the graph didn't change.
        assert (row["graph_version"], edited.version, edited.history_version) == (2, 2, 2) and reconciled == []
        assert edited.summary == "renamed the workflow to 'Refunds'; changed its description; changed its variables"
        assert told == [(OWNER, workflow_id, 2)]
        # Written again as it is, nothing moves.
        again = await _apply(db, workflow_id, [{"op": "update_workflow", "name": "Refunds"}])
        assert (again.version, again.changed) == (2, False)


class TestVersions:
    async def test_one_author_from_one_source_within_five_minutes_is_one_version(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "agent", "settings": {"message": "Shorter."}}])
        assert [(v["version"], v["source"], v["changes"]) for v in await _versions(db, workflow_id)] == [
            (1, "baseline", []), (3, "api", ["renamed 'Log' to 'Record'", "changed 'Helper' (message)"])]
        # Another key, another source, or the same one after the window: a version of its own.
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "enabled": False}],
                     author=Author(OWNER, key_id="key-2"))
        await db.execute("UPDATE workflow_versions SET created_at = now() - interval '6 minutes' "
                         "WHERE workflow_id = $1::uuid", workflow_id)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "enabled": True}],
                     author=Author(OWNER, key_id="key-2"))
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Log"}], source="coordinator")
        assert [(v["version"], v["source"], v["author_key_id"]) for v in await _versions(db, workflow_id)] == [
            (1, "baseline", None), (3, "api", None), (4, "api", "key-2"), (5, "api", "key-2"), (6, "coordinator", None)]

    async def test_api_writes_taking_turns_each_keep_a_version_of_their_own(self, db, told, reconciled):
        """A edits, B edits, A edits again within five minutes: A's first edit is a version without B's, so either
        can be undone on its own; one author's consecutive writes are still one version."""
        workflow_id = await _workflow(db)
        other = Author(OWNER, key_id="key-2")
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "A1"}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "agent", "settings": {"message": "B"}}],
                     author=other)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "A2"}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "A3"}])
        assert [(v["history_version"], v["version"], v["author_key_id"]) for v in await _versions(db, workflow_id)] \
            == [(1, 1, None), (2, 2, None), (3, 3, "key-2"), (4, 5, None)]
        two = await graph_service.version(db.pool, Author(OWNER), workflow_id, 2)
        assert _labels(two["graph"])["log"] == "A1"
        assert next(n for n in two["graph"]["nodes"] if n["id"] == "agent")["config"]["message"] == "Sum up."
        three = await graph_service.version(db.pool, Author(OWNER), workflow_id, 3)
        assert _labels(three["graph"])["log"] == "A1"
        assert next(n for n in three["graph"]["nodes"] if n["id"] == "agent")["config"]["message"] == "B"

    async def test_a_version_spans_five_minutes_from_its_first_write_however_often_it_is_written(
            self, db, told, reconciled):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "One"}])
        await db.execute("UPDATE workflow_versions SET created_at = now() - interval '6 minutes' "
                         "WHERE workflow_id = $1::uuid AND version = 2", workflow_id)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Two"}])
        assert [v["version"] for v in await _versions(db, workflow_id)] == [1, 2, 3]

    async def test_a_save_writes_the_graph_once_its_version_holding_none_while_it_is_the_newest(
            self, db, told, reconciled):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "One"}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Two"}])
        stored = lambda: db.fetch("SELECT version, graph IS NULL AS open FROM workflow_versions "  # noqa: E731
                                  "WHERE workflow_id = $1::uuid ORDER BY version", workflow_id)
        assert [(r["version"], r["open"]) for r in await stored()] == [(1, False), (3, True)]
        # The next version closes it with the workflow as it was then.
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Three"}], source="coordinator")
        assert [(r["version"], r["open"]) for r in await stored()] == [(1, False), (3, False), (4, True)]
        graph = await db.fetchval("SELECT graph FROM workflow_versions WHERE workflow_id = $1::uuid AND version = 3",
                                  workflow_id)
        assert _labels(graph)["log"] == "Two"
        restored = await _restore(db, workflow_id, 2)
        assert _labels((await _graph(db, workflow_id))["workflow"])["log"] == "Two" and restored.version == 5

    async def test_the_open_editions_scheduler_prunes_old_versions(self, db, told, reconciled):
        from utils.local_cron import maintain_daily

        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}])
        await db.execute("UPDATE workflow_versions SET updated_at = now() - interval '91 days' "
                         "WHERE workflow_id = $1::uuid", workflow_id)
        await maintain_daily(db.pool)
        assert [v["version"] for v in await _versions(db, workflow_id)] == [2]

    async def test_a_restore_is_a_version_and_can_itself_be_undone(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}])
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "log"}], source="coordinator")
        restored = await _restore(db, workflow_id, 2)
        assert (restored.version, restored.summary) == (4, "restored version 2")
        assert _labels((await _graph(db, workflow_id))["workflow"])["log"] == "Record"
        # Undone: the version before the restore comes back, as a version of its own.
        await _restore(db, workflow_id, 3)
        assert "log" not in _labels((await _graph(db, workflow_id))["workflow"])
        assert [(v["version"], v["source"], v["restored_from"]) for v in await _versions(db, workflow_id)] == [
            (1, "baseline", None), (2, "api", None), (3, "coordinator", None), (4, "restore", 2), (5, "restore", 3)]
        # The steps a restore brought back or took away are reconciled like any edit's.
        assert "log" in _labels(reconciled[2][2]) and "log" not in _labels(reconciled[3][2])

    async def test_versions_are_listed_newest_first_and_read_whole(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Log"}], source="coordinator")
        page = await graph_service.versions(db.pool, Author(OWNER), workflow_id, limit=2)
        assert [v["version"] for v in page["data"]] == [3, 2] and page["next_cursor"] == "2"
        rest = await graph_service.versions(db.pool, Author(OWNER), workflow_id, limit=2, before=2)
        assert [(v["version"], v["summary"]) for v in rest["data"]] == [(1, "As it was before its history began.")]
        one = await graph_service.version(db.pool, Author(OWNER), workflow_id, 2)
        assert one["summary"] == "renamed 'Log' to 'Record'" and _labels(one["graph"])["log"] == "Record"
        assert (one["name"], one["description"], one["settings"]) == ("Flow", None, {})
        with pytest.raises(GraphError) as missing:
            await graph_service.version(db.pool, Author(OWNER), workflow_id, 99)
        assert missing.value.kind == "not_found"

    async def test_a_version_is_the_whole_definition_and_a_restore_puts_it_all_back(
            self, db, told, reconciled, monkeypatch):
        monkeypatch.setattr("utils.system_workflows._SERVER_SETTINGS", {"system", "kept_by_noclick"})
        workflow_id = await _workflow(db, settings={"variable_definitions": [{"name": "a", "value": "1"}],
                                                    "kept_by_noclick": "first"})
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}])
        await _apply(db, workflow_id, [{"op": "update_workflow", "name": "Refunds", "description": "Refund mail."},
                                       {"op": "define_variable", "name": "region", "value": "eu"}],
                     source="coordinator")
        await db.execute("""UPDATE workflows SET settings = settings || '{"kept_by_noclick": "later"}'::jsonb """
                         "WHERE id = $1::uuid", workflow_id)
        three = await graph_service.version(db.pool, Author(OWNER), workflow_id, 3)
        assert (three["name"], three["description"]) == ("Refunds", "Refund mail.")
        assert [d["name"] for d in three["settings"]["variable_definitions"]] == ["a", "region"]
        assert "kept_by_noclick" not in three["settings"]
        restored = await _restore(db, workflow_id, 2)
        assert restored.version == 4
        row = await db.fetchrow("SELECT name, description, settings, workflow FROM workflows WHERE id = $1::uuid",
                                workflow_id)
        # The workflow's own fields come back with its graph; NoClick's own setting stays as NoClick left it.
        assert (row["name"], row["description"]) == ("Flow", "")
        assert row["settings"] == {"variable_definitions": [{"name": "a", "value": "1"}], "kept_by_noclick": "later"}
        assert _labels(row["workflow"])["log"] == "Record"
        # A restore that would change nothing writes nothing.
        same = await _restore(db, workflow_id, 4)
        assert (same.version, same.changed) == (4, False)

    async def test_old_versions_go_but_a_workflows_newest_stays(self, db, told, reconciled):
        from repositories import workflow_versions

        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}])
        await db.execute("UPDATE workflow_versions SET updated_at = now() - interval '91 days' "
                         "WHERE workflow_id = $1::uuid", workflow_id)
        await workflow_versions.prune(db.pool)
        assert [v["version"] for v in await _versions(db, workflow_id)] == [2]


class TestWhoMayEdit:
    async def test_a_workflow_noclick_runs_is_read_never_edited(self, db, told, reconciled):
        from utils.system_workflows import refusal

        workflow_id = await _workflow(db, settings={"system": "your NoClick assistant"})
        read = await graph_service.read(db.pool, Author(OWNER), workflow_id)
        assert read["version"] == 1 and "system" not in read["settings"]
        with pytest.raises(GraphError) as refused:
            await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Mine"}])
        assert (refused.value.kind, refused.value.message) == ("forbidden", refusal("your NoClick assistant"))

    async def test_a_viewer_reads_an_editor_edits_and_only_the_owner_changes_settings(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        await _share(db, workflow_id, VIEWER, "view")
        await _share(db, workflow_id, EDITOR, "edit")
        assert (await graph_service.read(db.pool, Author(VIEWER), workflow_id))["version"] == 1
        with pytest.raises(GraphError) as viewer:
            await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "x"}], author=Author(VIEWER))
        assert viewer.value.kind == "forbidden"
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "x"}], author=Author(EDITOR))
        with pytest.raises(GraphError) as settings:
            await _apply(db, workflow_id, [{"op": "define_variable", "name": "x"}], author=Author(EDITOR))
        assert settings.value.kind == "invalid" and "owner" in settings.value.message
        with pytest.raises(GraphError) as stranger:
            await graph_service.read(db.pool, Author(OTHER), workflow_id)
        assert stranger.value.kind == "not_found"

    async def test_a_connection_is_one_the_caller_may_use_and_is_authorized_for_the_owners_runs(
            self, db, told, reconciled):
        workflow_id = await _workflow(db, {"nodes": [node("slack", "automation-slack",
                                                          operation="send_message_to_channel")], "edges": []})
        theirs = await _credential(db, OTHER, "slack_oauth")
        with pytest.raises(GraphError) as refused:
            await _apply(db, workflow_id, [{"op": "set_connection", "id": "slack", "connection": theirs}])
        assert (refused.value.kind, refused.value.details["field"]) == ("invalid", "connection")
        mine = await _credential(db, OWNER, "slack_bot_token")
        await _apply(db, workflow_id, [{"op": "set_connection", "id": "slack", "connection": mine}])
        config = (await _graph(db, workflow_id))["workflow"]["nodes"][0]["config"]
        assert config["credentialIds"] == {"slack_bot_token": mine}
        assert await db.fetchval("SELECT count(*) FROM workflow_authorized_credentials WHERE workflow_id = $1::uuid "
                                 "AND credential_id = $2::uuid", workflow_id, mine) == 1

    async def test_a_caller_acting_for_one_user_adds_no_connection_the_workflow_doesnt_hold(
            self, db, told, reconciled):
        held = await _credential(db, OWNER, "slack_bot_token")
        other = await _credential(db, OWNER, "slack_bot_token")
        workflow_id = await _workflow(db, {"nodes": [
            node("slack", "automation-slack", operation="send_message_to_channel",
                 credentialIds={"slack_bot_token": held}),
            node("slack2", "automation-slack", operation="send_message_to_channel")], "edges": []})
        narrow = Author(OWNER, key_id="user-key", whole_account=False)
        with pytest.raises(GraphError) as refused:
            await _apply(db, workflow_id, [{"op": "set_connection", "id": "slack2", "connection": other}],
                         author=narrow)
        assert (refused.value.kind, refused.value.details["op"], refused.value.details["field"]) == (
            "invalid", 0, "connection")
        assert "whole account" in refused.value.message
        # One the workflow already holds, or none, is theirs to set.
        await _apply(db, workflow_id, [{"op": "set_connection", "id": "slack2", "connection": held},
                                       {"op": "set_connection", "id": "slack", "connection": None,
                                        "slot": "slack_bot_token"}], author=narrow)
        configs = {n["id"]: n["config"] for n in (await _graph(db, workflow_id))["workflow"]["nodes"]}
        assert configs["slack2"]["credentialIds"] == {"slack_bot_token": held}
        assert not configs["slack"].get("credentialIds")

    async def test_a_read_never_carries_a_secret_or_a_runtime_key(self, db, told, reconciled):
        graph = {"nodes": [node("fetch", "automation-http-request", label="Fetch", url="https://api.example",
                                operation="send_http_get_request", api_key="sk-live-123", _turnNote="obey",
                                output={"cached": True}, auth={"user": "me", "password": "hunter2"},
                                headers=[{"key": "Authorization", "value": "Bearer abc", "enabled": True},
                                         {"key": "Accept", "value": "application/json", "enabled": True}],
                                query_params=[{"key": "api_token", "value": "q-1", "enabled": True}])],
                 "edges": [], "variables": {"token": "t-1"}}
        workflow_id = await _workflow(db, graph, settings={"variable_definitions": [
            {"name": "OPENAI_API_KEY", "value": "sk-var"}, {"name": "region", "value": "eu"}]})
        read = await graph_service.read(db.pool, Author(OWNER), workflow_id)
        config = read["graph"]["nodes"][0]["config"]
        assert config == {"label": "Fetch", "url": "https://api.example", "operation": "send_http_get_request",
                          "auth": {"user": "me"},
                          "headers": [{"key": "Authorization", "enabled": True},
                                      {"key": "Accept", "value": "application/json", "enabled": True}],
                          "query_params": [{"key": "api_token", "enabled": True}]}
        assert read["graph"]["withheld"] == {"fetch": ["api_key", "auth.password", "headers[0].value",
                                                       "query_params[0].value"]}
        # A variable's value, which a field bound to {{vars.x}} takes, whatever its name: as the template page.
        assert read["settings"] == {"variable_definitions": [{"name": "OPENAI_API_KEY"}, {"name": "region"}]}
        assert read["settings_withheld"] == ["variable_definitions[0].value", "variable_definitions[1].value"]
        assert "variables" not in read["graph"] and read["graph"]["variables_withheld"] == ["token"]
        # A version reads the same way.
        await _apply(db, workflow_id, [{"op": "update_step", "id": "fetch", "name": "Get"}])
        two = await graph_service.version(db.pool, Author(OWNER), workflow_id, 2)
        assert two["graph"]["withheld"] == read["graph"]["withheld"]
        assert two["settings_withheld"] == read["settings_withheld"]

    async def test_a_write_that_sends_back_what_it_read_keeps_the_secrets_it_never_saw(self, db, told, reconciled):
        graph = {"nodes": [node("fetch", "automation-http-request", label="Fetch", url="https://api.example",
                                operation="send_http_get_request",
                                headers=[{"key": "Authorization", "value": "Bearer abc", "enabled": True},
                                         {"key": "X-Api-Key", "value": "k-1", "enabled": True}])],
                 "edges": []}
        workflow_id = await _workflow(db, graph, settings={"variable_definitions": [
            {"name": "OPENAI_API_KEY", "value": "sk-var"}, {"name": "region", "value": "eu"}]})
        read = await graph_service.read(db.pool, Author(OWNER), workflow_id)
        headers = read["graph"]["nodes"][0]["config"]["headers"]
        # Sent back with one header dropped and one added.
        sent = [headers[0], {"key": "Accept", "value": "text/csv", "enabled": True}]
        await _apply(db, workflow_id, [
            {"op": "update_step", "id": "fetch", "settings": {"headers": sent}},
            {"op": "update_workflow", "settings": read["settings"]},
        ], if_version=read["version"])
        row = await db.fetchrow("SELECT workflow, settings FROM workflows WHERE id = $1::uuid", workflow_id)
        assert row["workflow"]["nodes"][0]["config"]["headers"] == [
            {"key": "Authorization", "value": "Bearer abc", "enabled": True},
            {"key": "Accept", "value": "text/csv", "enabled": True}]
        assert row["settings"]["variable_definitions"] == [{"name": "OPENAI_API_KEY", "value": "sk-var"},
                                                           {"name": "region", "value": "eu"}]
        # A withheld value a write does send replaces it.
        await _apply(db, workflow_id, [{"op": "update_step", "id": "fetch", "settings": {
            "headers": [{"key": "authorization", "value": "Bearer new", "enabled": True}]}}])
        assert (await _graph(db, workflow_id))["workflow"]["nodes"][0]["config"]["headers"] == [
            {"key": "authorization", "value": "Bearer new", "enabled": True}]


    async def test_a_secret_in_a_list_comes_back_only_to_the_item_it_belongs_to(self, db, told, reconciled):
        """An item matched by a name it keeps (a row's key, an item's id) takes its secret back; one with no such
        name never takes another's by its place in the list (a removed item's key landing in the next one)."""
        graph = {"nodes": [node("fetch", "automation-http-request", label="Fetch", url="https://api.example",
                                operation="send_http_get_request",
                                accounts=[{"id": "a", "api_key": "k-a"}, {"id": "b", "api_key": "k-b"}],
                                mirrors=[{"label": "x", "api_key": "k-x"}, {"label": "y", "api_key": "k-y"}])],
                 "edges": []}
        workflow_id = await _workflow(db, graph)
        read = await graph_service.read(db.pool, Author(OWNER), workflow_id)
        config = read["graph"]["nodes"][0]["config"]
        assert config["accounts"] == [{"id": "a"}, {"id": "b"}] and config["mirrors"] == [{"label": "x"},
                                                                                       {"label": "y"}]
        await _apply(db, workflow_id, [{"op": "update_step", "id": "fetch", "settings": {
            "accounts": [{"id": "b"}], "mirrors": [{"label": "y"}]}}], if_version=read["version"])
        stored = (await _graph(db, workflow_id))["workflow"]["nodes"][0]["config"]
        assert stored["accounts"] == [{"id": "b", "api_key": "k-b"}]
        assert stored["mirrors"] == [{"label": "y"}]

    async def test_a_yes_or_no_named_like_a_secret_is_shown_and_kept(self, db, told, reconciled):
        """A flag holds no secret, whatever it's called: a form's field marked ``secret: true`` (a password field)
        is read as it is, and a write sending its fields back keeps it a password field."""
        fields = [{"name": "email", "type": "string", "label": "Email"},
                  {"name": "pin", "type": "string", "label": "PIN", "secret": True}]
        workflow_id = await _workflow(db, {"nodes": [node("form", "trigger-form-input", label="Form",
                                                          fields=fields, secret=False)], "edges": []})
        read = await graph_service.read(db.pool, Author(OWNER), workflow_id)
        assert read["graph"]["nodes"][0]["config"]["fields"] == fields and read["graph"]["withheld"] == {}
        assert read["graph"]["nodes"][0]["config"]["secret"] is False
        sent = [{**field, "label": field["label"].upper()} for field in read["graph"]["nodes"][0]["config"]["fields"]]
        await _apply(db, workflow_id, [{"op": "update_step", "id": "form", "settings": {"fields": sent}}],
                     if_version=read["version"])
        assert (await _graph(db, workflow_id))["workflow"]["nodes"][0]["config"]["fields"][1]["secret"] is True


class TestReconcileThroughTheService:
    """What an edit sets in motion outside the graph, through the real reconcile with the registration
    chokepoints stood in for: each family's change hook, removed steps' teardown, new triggers' provisioning and
    steps a restore brings back."""

    @pytest.fixture
    def registry(self):
        calls = {"reconciled": [], "cleaned": [], "provisioned": [], "registered": []}

        async def reconcile_node(pool, workflow_id, node_id, **kwargs):
            calls["reconciled"].append(node_id)
            return {"state": "registered"}

        async def cleanup(*, pool, workflow_id, node_ids, background, old_nodes, requesting_user_id):
            calls["cleaned"].append(([n["id"] for n in old_nodes], node_ids))

        async def provision(pool, *, node_id, **kwargs):
            calls["provisioned"].append(node_id)
            return {"webhook_url": f"https://hooks.example/{node_id}"}

        async def register(pool, workflow_id, user_id, node_ids=None):
            calls["registered"].append(list(node_ids))

        from utils.webhook_manager import WebhookManager

        with patch.object(WebhookManager, "reconcile_node", side_effect=reconcile_node), \
                patch("utils.workflow_resource_manager.cleanup_nodes_resources", side_effect=cleanup), \
                patch.object(WebhookManager, "provision_node_webhook", side_effect=provision), \
                patch.object(WebhookManager, "register_node_webhooks", side_effect=register):
            yield calls

    async def test_each_registration_family_reconciles_its_change(self, db, told, registry):
        a, b = await _credential(db, OWNER, "linear_oauth"), await _credential(db, OWNER, "linear_oauth")
        workflow_id = await _workflow(db, {"nodes": [
            node("issues", "automation-linear", operation="on_issue_created", webhook_url="https://h/1",
                 credentialIds={"linear_oauth": a}),
            node("cron", "trigger-cron", schedule={"frequency": "daily", "time": "08:00"}, webhook_url="https://h/2"),
            node("chat", "automation-slack", operation="on_channel_message", webhook_url="https://h/3"),
        ], "edges": []})
        await _apply(db, workflow_id, [
            {"op": "set_connection", "id": "issues", "connection": b},
            {"op": "update_step", "id": "cron", "settings": {"schedule": {"frequency": "daily", "time": "09:00"}}},
            {"op": "update_step", "id": "chat", "operation": "on_app_mention"},
        ])
        assert sorted(registry["reconciled"]) == ["chat", "cron", "issues"]

    async def test_a_removed_step_is_torn_down_and_gives_back_its_inbox(self, db, told, registry):
        from utils.email_reservation_manager import EmailReservationManager

        workflow_id = await _workflow(db, {"nodes": [node("inbox", "trigger-email", label="Inbox")], "edges": []})
        await EmailReservationManager.reserve(db.pool, OWNER, workflow_id, "inbox", f"in-{uuid.uuid4().hex[:8]}")
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "inbox"}])
        assert registry["cleaned"] == [(["inbox"], ["inbox"])]
        assert await db.fetchval("SELECT count(*) FROM email_reservations WHERE workflow_id = $1::uuid",
                                 workflow_id) == 0

    async def test_a_restore_that_brings_an_inbox_back_claims_its_address_again(self, db, told, registry):
        from utils.email_reservation_manager import EmailReservationManager

        local = f"in-{uuid.uuid4().hex[:8]}"
        workflow_id = await _workflow(db, {"nodes": [node("inbox", "trigger-email", label="Inbox", local_part=local)],
                                           "edges": []})
        await EmailReservationManager.reserve(db.pool, OWNER, workflow_id, "inbox", local)
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "inbox"}])
        await _restore(db, workflow_id, 1)
        claimed = await db.fetchrow("SELECT node_id, local_part, is_active FROM email_reservations "
                                    "WHERE workflow_id = $1::uuid", workflow_id)
        assert (claimed["node_id"], claimed["local_part"], claimed["is_active"]) == ("inbox", local, True)
        # Taken meanwhile by another workflow's step, the restore is refused and nothing of it lands.
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "inbox"}])
        other = await _workflow(db)
        await EmailReservationManager.reserve(db.pool, OWNER, other, "theirs", local)
        with pytest.raises(GraphError) as taken:
            await _restore(db, workflow_id, 1)
        assert taken.value.kind == "invalid" and local in taken.value.message
        assert "inbox" not in _labels((await _graph(db, workflow_id))["workflow"])

    async def test_a_late_reconcile_leaves_alone_a_step_a_later_write_brought_back(self, db, told, registry):
        """Remove a step, then add it back: the removal's reconcile, run after the re-add landed, tears nothing
        of it down."""
        from utils.workflow_reconcile import reconcile_graph_change

        workflow_id = await _workflow(db)
        without = copy.deepcopy(GRAPH)
        without["nodes"] = [n for n in without["nodes"] if n["id"] != "hook"]
        await reconcile_graph_change(db.pool, workflow_id, OWNER, GRAPH, without)
        assert registry["cleaned"] == []

    async def test_reconciles_hold_no_connection_while_they_work(self, db, told, registry):
        """On a one-connection pool, reconciles of two workflows (and two of one) all finish: none holds a
        connection or a transaction while its work takes its own."""
        import asyncio

        import asyncpg

        from utils.database_pool import setup_asyncpg_codecs
        from utils.workflow_reconcile import reconcile_graph_change

        small = await asyncpg.create_pool(db.url, min_size=1, max_size=1, init=setup_asyncpg_codecs,
                                          statement_cache_size=0)
        try:
            flows = [await _workflow(db), await _workflow(db)]
            after = copy.deepcopy(GRAPH)
            after["nodes"] = [n for n in after["nodes"] if n["id"] != "log"]
            for workflow_id in flows:
                await db.execute("UPDATE workflows SET workflow = $2 WHERE id = $1::uuid", workflow_id, after)

            async def cleanup(*, pool, workflow_id, node_ids, background, old_nodes, requesting_user_id):
                async with pool.acquire() as conn:  # as cleanup_nodes_resources does
                    await conn.fetchval("SELECT 1")

            with patch("utils.workflow_resource_manager.cleanup_nodes_resources", side_effect=cleanup):
                await asyncio.wait_for(asyncio.gather(*(
                    reconcile_graph_change(small, w, OWNER, GRAPH, after) for w in [*flows, flows[0]])), timeout=20)
        finally:
            await small.close()

    async def test_a_job_another_worker_holds_waits_for_it_and_a_dead_ones_resumes_on_the_sweep(
            self, db, told, registry, monkeypatch):
        """A worker elsewhere holds the workflow's lease: the job waits for it rather than running beside it. That
        worker died: once its lease lapses the sweep runs the job."""
        import asyncio

        from utils import workflow_reconcile

        workflow_id = await _workflow(db)
        await db.execute("INSERT INTO workflow_reconcile_leases (workflow_id, holder, expires_at) "
                         "VALUES ($1::uuid, 'elsewhere', now() + interval '1 second')", workflow_id)
        renamed = copy.deepcopy(GRAPH)
        renamed["nodes"][0]["config"]["label"] = "Renamed"
        hooked = []

        async def hook(pool, node_type, workflow_id, node_id, *args, **kwargs):
            hooked.append(node_id)

        monkeypatch.setattr("utils.webhook_manager.WebhookManager.handle_registration_fields_change", hook)
        job = await workflow_reconcile.reconcile_graph_change(db.pool, workflow_id, OWNER, GRAPH, renamed)
        assert hooked == [] and await _job_status(db, job) == "queued"
        await asyncio.sleep(1.2)
        assert await workflow_reconcile.sweep(db.pool) == 1
        assert hooked == ["hook"] and await _job_status(db, job) == "done"
        assert await db.fetchval("SELECT count(*) FROM workflow_reconcile_leases WHERE workflow_id = $1::uuid",
                                 workflow_id) == 0

    async def test_an_edit_answers_before_its_teardown_which_runs_after(self, db, told):
        """Removing a step answers once it's written; the step's teardown (provider round trips) runs after, off
        the answer's path, and the next edit made on the answered version isn't held by it."""
        import asyncio

        from utils.webhook_manager import WebhookManager

        release, cleaned = asyncio.Event(), []

        async def cleanup(*, pool, workflow_id, node_ids, background, old_nodes, requesting_user_id):
            await release.wait()
            cleaned.append(list(node_ids))

        from coder.workflow.option_registries import warm_registries

        await warm_registries()  # the model list an edit resolves against, built once per process: not the edit's
        workflow_id = await _workflow(db)
        with patch("utils.workflow_resource_manager.cleanup_nodes_resources", side_effect=cleanup), \
                patch.object(WebhookManager, "provision_node_webhook", AsyncMock(return_value=None)):
            edited = await asyncio.wait_for(graph_service.apply(
                db.pool, Author(OWNER), workflow_id, [{"op": "remove_step", "id": "log"}]), timeout=5)
            assert edited.version == 2 and cleaned == []
            again = await asyncio.wait_for(graph_service.apply(
                db.pool, Author(OWNER), workflow_id, [{"op": "update_step", "id": "agent", "name": "Next"}],
                if_version=edited.version), timeout=5)
            assert again.version == 3 and cleaned == []
            release.set()
            from utils.async_helpers import drain_spawned_tasks

            await drain_spawned_tasks(timeout=5)
        assert cleaned == [["log"]]
        assert [r["status"] for r in await db.fetch(
            "SELECT status FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid ORDER BY id", workflow_id)] == [
            "done", "done"]

    async def test_overlapping_reconciles_leave_each_step_as_the_graph_has_it(self, db, told, monkeypatch):
        """Two runs of one workflow's work that overlap (a lease that lapsed under a worker): each teardown and
        registration acts on the graph as stored when it acts, so the last word on a step matches the graph,
        whichever order they finish in; a step back while its teardown ran holds its inbox's address again."""
        import asyncio

        from utils.email_reservation_manager import EmailReservationManager
        from utils.webhook_manager import WebhookManager
        from utils.workflow_reconcile import _reconcile

        local = f"in-{uuid.uuid4().hex[:8]}"
        inbox = node("log", "trigger-email", label="Inbox", local_part=local)
        with_inbox = {"nodes": [*[n for n in GRAPH["nodes"] if n["id"] != "log"], inbox], "edges": GRAPH["edges"]}
        without = copy.deepcopy(GRAPH)
        without["nodes"] = [n for n in without["nodes"] if n["id"] != "log"]
        acted = []
        slow = {}

        async def cleanup(*, pool, workflow_id, node_ids, background, old_nodes, requesting_user_id):
            await asyncio.sleep(slow["teardown"])
            acted.append(("teardown", sorted(node_ids)))

        async def register(pool, workflow_id, user_id, node_ids=None):
            await asyncio.sleep(slow["register"])
            acted.append(("register", sorted(node_ids)))

        async def store(workflow_id, graph):
            await db.execute("UPDATE workflows SET workflow = $2 WHERE id = $1::uuid", workflow_id, graph)

        with patch("utils.workflow_resource_manager.cleanup_nodes_resources", side_effect=cleanup), \
                patch.object(WebhookManager, "register_node_webhooks", side_effect=register), \
                patch.object(WebhookManager, "provision_node_webhook", AsyncMock(return_value=None)):
            # A slow teardown of a removed step, overtaken by a write that puts it back: registered at the end,
            # its address claimed again.
            slow.update(teardown=1.0, register=0)
            workflow_id = await _workflow(db, without)
            await EmailReservationManager.reserve(db.pool, OWNER, workflow_id, "log", local)
            first = asyncio.create_task(_reconcile(db.pool, workflow_id, OWNER, with_inbox, without, None))
            await asyncio.sleep(0.1)
            await store(workflow_id, with_inbox)
            await asyncio.gather(first, _reconcile(db.pool, workflow_id, OWNER, without, with_inbox, None))
            assert acted[-1] == ("register", ["log"]), acted
            assert await db.fetchval("SELECT local_part FROM email_reservations WHERE workflow_id = $1::uuid "
                                     "AND node_id = 'log'", workflow_id) == local
            # A slow registration of a step that's back, overtaken by a write that removes it: torn down at the end.
            acted.clear()
            slow.update(teardown=0, register=1.0)
            workflow_id = await _workflow(db)
            first = asyncio.create_task(_reconcile(db.pool, workflow_id, OWNER, without, GRAPH, []))
            await asyncio.sleep(0.1)
            await store(workflow_id, without)
            await asyncio.gather(first, _reconcile(db.pool, workflow_id, OWNER, GRAPH, without, None))
            assert acted[-1] == ("teardown", ["log"]), acted

    async def test_a_job_cut_off_resumes_until_done(self, db, told, registry, monkeypatch):
        """A job whose work runs past ``WORK_S`` is stopped, its lease given back, and retried: its removed step's
        teardown and inbox are finished then, never left half done."""
        import asyncio

        from utils import workflow_reconcile
        from utils.email_reservation_manager import EmailReservationManager

        monkeypatch.setattr(workflow_reconcile, "WORK_S", 0.5)
        local = f"in-{uuid.uuid4().hex[:8]}"
        workflow_id = await _workflow(db, {"nodes": [node("inbox", "trigger-email", label="Inbox", local_part=local)],
                                           "edges": []})
        await EmailReservationManager.reserve(db.pool, OWNER, workflow_id, "inbox", local)
        slow = {"s": 5.0}
        cleaned = []

        async def cleanup(*, pool, workflow_id, node_ids, background, old_nodes, requesting_user_id):
            await asyncio.sleep(slow["s"])
            cleaned.append(list(node_ids))

        with patch("utils.workflow_resource_manager.cleanup_nodes_resources", side_effect=cleanup):
            edited = await _apply(db, workflow_id, [{"op": "remove_step", "id": "inbox"}])
            [job] = await db.fetch("SELECT id, status, attempts, last_error FROM workflow_reconcile_jobs "
                                   "WHERE workflow_id = $1::uuid", workflow_id)
            assert (job["status"], job["attempts"], cleaned) == ("queued", 1, [])
            assert "ran past" in job["last_error"]
            assert await db.fetchval("SELECT count(*) FROM workflow_reconcile_leases WHERE workflow_id = $1::uuid",
                                     workflow_id) == 0
            assert await db.fetchval("SELECT count(*) FROM email_reservations WHERE workflow_id = $1::uuid",
                                     workflow_id) == 1
            # Its retry comes due, and the provider answers in time now.
            slow["s"] = 0
            await db.execute("UPDATE workflow_reconcile_jobs SET retry_at = now() WHERE id = $1", job["id"])
            assert await workflow_reconcile.sweep(db.pool) == 1
        assert cleaned == [["inbox"]] and await _job_status(db, job["id"]) == "done"
        assert await db.fetchval("SELECT count(*) FROM email_reservations WHERE workflow_id = $1::uuid",
                                 workflow_id) == 0
        assert edited.version == 2

    async def test_a_failing_job_holds_only_the_jobs_touching_its_steps(self, db, told, registry, monkeypatch):
        """A job that keeps failing (its trigger's provider down) waits for its retries; a later job touching other
        steps runs at once, and one touching its step waits behind it. The failing trigger shows it."""
        from utils import workflow_reconcile
        from utils.webhook_manager import WebhookManager

        async def broken(pool, node_type, workflow_id, node_id, *args, **kwargs):
            if node_id == "hook":
                raise RuntimeError("the provider is down")

        monkeypatch.setattr(WebhookManager, "handle_registration_fields_change", broken)
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "hook", "name": "Orders"}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "agent", "settings": {"message": "Later."}}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "hook", "name": "Orders again"}])
        jobs = await db.fetch("SELECT status, attempts, last_error FROM workflow_reconcile_jobs "
                              "WHERE workflow_id = $1::uuid ORDER BY id", workflow_id)
        assert [(j["status"], j["attempts"]) for j in jobs] == [("queued", 1), ("done", 0), ("queued", 0)]
        assert "the provider is down" in jobs[0]["last_error"]
        hook = next(n for n in (await _graph(db, workflow_id))["workflow"]["nodes"] if n["id"] == "hook")
        assert hook["config"]["trigger_error"].startswith(workflow_reconcile.UNFINISHED)
        assert "the provider is down" in hook["config"]["trigger_error"]
        # The provider is back and the retry comes due: both run, in order, and the trigger no longer shows it.
        monkeypatch.setattr(WebhookManager, "handle_registration_fields_change", AsyncMock(return_value=None))
        await db.execute("UPDATE workflow_reconcile_jobs SET retry_at = now() WHERE workflow_id = $1::uuid",
                         workflow_id)
        await workflow_reconcile.sweep(db.pool)
        assert [r["status"] for r in await db.fetch(
            "SELECT status FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid ORDER BY id", workflow_id)] == [
            "done", "done", "done"]
        hook = next(n for n in (await _graph(db, workflow_id))["workflow"]["nodes"] if n["id"] == "hook")
        assert hook["config"]["trigger_error"] is None

    async def test_a_job_given_up_on_is_kept_and_retried_daily(self, db, told, registry, monkeypatch):
        import asyncio

        from utils import workflow_reconcile
        from utils.webhook_manager import WebhookManager

        monkeypatch.setattr(workflow_reconcile, "MAX_ATTEMPTS", 2)
        monkeypatch.setattr(workflow_reconcile, "RETRY_S", 0.1)
        monkeypatch.setattr(WebhookManager, "handle_registration_fields_change",
                            AsyncMock(side_effect=RuntimeError("the provider is down")))
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "hook", "name": "Orders"}])
        await asyncio.sleep(0.2)
        await workflow_reconcile.sweep(db.pool)
        job = await db.fetchrow("SELECT id, status, attempts FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid",
                                workflow_id)
        assert (job["status"], job["attempts"]) == ("failed", 2)
        # Never pruned, however old, while it's undone.
        await db.execute("UPDATE workflow_reconcile_jobs SET done_at = now() - interval '90 days' WHERE id = $1",
                         job["id"])
        await workflow_reconcile.prune(db.pool)
        assert await _job_status(db, job["id"]) == "failed"
        # The daily maintenance runs it again: the provider is back.
        monkeypatch.setattr(WebhookManager, "handle_registration_fields_change", AsyncMock(return_value=None))
        assert await workflow_reconcile.retry_given_up(db.pool) == 1
        assert await _job_status(db, job["id"]) == "done"

    async def test_given_up_jobs_are_retried_newest_per_step_and_closed_by_a_newer_success(
            self, db, told, registry, monkeypatch):
        """Each save touching a broken step queues a job that's given up on in time. Each newer one takes over the
        older ones it covers (they're superseded, their work its), so only the newest per step is retried daily, and
        a newer job on those steps that succeeds closes it: none runs after it."""
        from utils import workflow_reconcile
        from utils.webhook_manager import WebhookManager

        monkeypatch.setattr(workflow_reconcile, "MAX_ATTEMPTS", 1)
        monkeypatch.setattr(WebhookManager, "handle_registration_fields_change",
                            AsyncMock(side_effect=RuntimeError("the provider is down")))
        workflow_id = await _workflow(db)
        for name in ("One", "Two", "Three"):
            await _apply(db, workflow_id, [{"op": "update_step", "id": "hook", "name": name}])
        def statuses():
            return db.fetch("SELECT status FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid ORDER BY id",
                            workflow_id)

        assert [r["status"] for r in await statuses()] == ["superseded", "superseded", "failed"]
        # The daily retry runs the newest alone (the provider is still down).
        assert await workflow_reconcile.retry_given_up(db.pool) == 1
        assert [r["status"] for r in await statuses()] == ["superseded", "superseded", "failed"]
        # The provider is back: the next change to hook succeeds, and closes the one given up on.
        monkeypatch.setattr(WebhookManager, "handle_registration_fields_change", AsyncMock(return_value=None))
        await _apply(db, workflow_id, [{"op": "update_step", "id": "hook", "name": "Four"}])
        assert [r["status"] for r in await statuses()] == ["superseded", "superseded", "superseded", "done"]
        assert await workflow_reconcile.retry_given_up(db.pool) == 0

    @pytest.mark.parametrize("taken_over_by", ["the daily retry", "a newer change"])
    async def test_a_job_taking_over_older_ones_does_their_work_from_where_it_began(
            self, db, told, registry, monkeypatch, taken_over_by):
        """A step's operation changed and its job was given up on; a rename of it was too. The job that takes them
        over (the newest, retried daily, or a newer change's) reconciles from where the first change began, so the
        change of operation is still made, and the trigger's error stays until it is."""
        from utils import workflow_reconcile
        from utils.webhook_manager import WebhookManager

        monkeypatch.setattr(workflow_reconcile, "MAX_ATTEMPTS", 1)
        changed, provider = [], {"up": False}

        async def operation_change(pool, node_type, workflow_id, node_id, old_op, new_op, **kwargs):
            if not provider["up"]:
                raise RuntimeError("the provider is down")
            changed.append((node_id, old_op, new_op))

        async def fields_change(pool, node_type, workflow_id, node_id, *args, **kwargs):
            if not provider["up"]:
                raise RuntimeError("the provider is down")

        monkeypatch.setattr(WebhookManager, "handle_operation_change", operation_change)
        monkeypatch.setattr(WebhookManager, "handle_registration_fields_change", fields_change)
        workflow_id = await _workflow(db, {"nodes": [
            node("chat", "automation-slack", label="Chat", operation="on_channel_message")], "edges": []})
        await _apply(db, workflow_id, [{"op": "update_step", "id": "chat", "operation": "on_app_mention"}])
        await _apply(db, workflow_id, [{"op": "update_step", "id": "chat", "name": "Mentions"}])
        # The rename's job took over the first: it's given up on too, the first superseded.
        assert [r["status"] for r in await db.fetch(
            "SELECT status FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid ORDER BY id", workflow_id)] == [
            "superseded", "failed"]
        assert changed == []
        provider["up"] = True
        if taken_over_by == "the daily retry":
            assert await workflow_reconcile.retry_given_up(db.pool) == 1
        else:
            await _apply(db, workflow_id, [{"op": "update_step", "id": "chat", "name": "Mentions only"}])
        assert changed == [("chat", "on_channel_message", "on_app_mention")]
        statuses = [r["status"] for r in await db.fetch(
            "SELECT status FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid ORDER BY id", workflow_id)]
        assert statuses[-1] == "done" and set(statuses[:-1]) == {"superseded"}
        chat = next(n for n in (await _graph(db, workflow_id))["workflow"]["nodes"] if n["id"] == "chat")
        assert not chat["config"].get("trigger_error")

    async def test_another_steps_job_leaves_a_failing_triggers_error_alone(self, db, told, registry):
        """A trigger whose own job couldn't finish registering keeps showing it: another step's job neither
        provisions it nor clears what it shows."""
        from utils import workflow_reconcile
        from utils.webhook_manager import WebhookManager

        provisioned = []

        async def provision(pool, *, node_id, **kwargs):
            provisioned.append(node_id)
            return {"webhook_url": f"https://hooks.example/{node_id}", "trigger_error": None}

        shown = f"{workflow_reconcile.UNFINISHED} the provider is down"
        graph = copy.deepcopy(GRAPH)
        graph["nodes"][0]["config"].update(webhook_url="https://hooks.example/1", trigger_error=shown)
        workflow_id = await _workflow(db, graph)
        # Inside the registry's own stand-in, and gone before it is: a monkeypatch over a fixture's patch outlived
        # both, and every later test in the session provisioned through this stub.
        with patch.object(WebhookManager, "provision_node_webhook", side_effect=provision):
            await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}])
        hook = next(n for n in (await _graph(db, workflow_id))["workflow"]["nodes"] if n["id"] == "hook")
        assert hook["config"]["trigger_error"] == shown and provisioned == []

    async def test_moving_steps_on_the_canvas_queues_nothing(self, db, told, registry):
        from wss.handlers.workflow_handler import WorkflowHandler
        from wss.receiver.client_events import WorkflowUpdateRequest

        workflow_id = await _workflow(db)
        sio = MagicMock()
        sio.get_session = AsyncMock(return_value={"user_id": OWNER})
        sio.emit = AsyncMock()
        handler = WorkflowHandler(sio=sio)
        handler.get_pool = AsyncMock(return_value=db.pool)
        moved = copy.deepcopy(GRAPH)
        moved["nodes"][0]["position"] = {"x": 300, "y": 40}
        moved["nodes"][1].update(width=320, height=180)
        await handler.update_workflow("sid", WorkflowUpdateRequest(
            request_id="r", workflow_id=workflow_id, workflow_data=moved, expected_graph_version=1))
        assert (await _graph(db, workflow_id))["graph_version"] == 2
        assert await db.fetchval("SELECT count(*) FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid",
                                 workflow_id) == 0

    async def test_a_sweep_runs_workflows_side_by_side(self, db, told, monkeypatch):
        """One workflow's slow provider doesn't hold every other workflow's retries."""
        import asyncio
        import time

        from utils import workflow_reconcile

        async def slow(*args, **kwargs):
            await asyncio.sleep(1.0)

        flows = [await _workflow(db) for _ in range(3)]
        renamed = copy.deepcopy(GRAPH)
        renamed["nodes"][0]["config"]["label"] = "Renamed"
        for workflow_id in flows:
            async with db.pool.acquire() as conn:
                await workflow_reconcile.enqueue(conn, workflow_id, OWNER, GRAPH, renamed, from_version=1,
                                                 to_version=2)
        with patch.object(workflow_reconcile, "_reconcile", side_effect=slow):
            started = time.monotonic()
            assert await workflow_reconcile.sweep(db.pool) >= 3
        assert time.monotonic() - started < 2.5

    async def test_one_workflows_jobs_run_one_at_a_time_in_order(self, db, told, registry):
        import asyncio

        from utils.webhook_manager import WebhookManager
        from utils.workflow_reconcile import reconcile_graph_change

        workflow_id = await _workflow(db)
        running, overlapped, order = [], [], []

        async def slow(pool, node_type, workflow_id, node_id, old_config, new_config, **kwargs):
            overlapped.append(bool(running))
            running.append(1)
            await asyncio.sleep(0.2)
            order.append(new_config.get("label"))
            running.pop()

        first, second = copy.deepcopy(GRAPH), copy.deepcopy(GRAPH)
        first["nodes"][0]["config"]["label"] = "First"
        second["nodes"][0]["config"]["label"] = "Second"
        with patch.object(WebhookManager, "handle_registration_fields_change", side_effect=slow):
            await asyncio.gather(reconcile_graph_change(db.pool, workflow_id, OWNER, GRAPH, first),
                                 reconcile_graph_change(db.pool, workflow_id, OWNER, first, second))
            from utils.async_helpers import drain_spawned_tasks

            await drain_spawned_tasks(timeout=5)
        assert order == ["First", "Second"] and not any(overlapped)

    async def test_a_new_trigger_is_provisioned_after_the_answer_and_its_version_edits_on(
            self, db, told, registry):
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "add_step", "type": "trigger-webhook", "id": "hook2"}],
                              include_graph=True)
        assert registry["provisioned"] == ["hook2"]
        row = await _graph(db, workflow_id)
        hook = next(n for n in row["workflow"]["nodes"] if n["id"] == "hook2")
        assert hook["config"]["webhook_url"] == "https://hooks.example/hook2"
        # The edit answered once it was written; the webhook's fields, NoClick's mirror written after, move the
        # graph's version (each recorded as a reconcile's), not its history, and its canvases hear them too.
        assert (edited.version, edited.history_version, row["graph_version"]) == (2, 2, 3)
        assert [v["version"] for v in await _versions(db, workflow_id)] == [1, 2]
        assert told == [(OWNER, workflow_id, 2), (OWNER, workflow_id, 3)]
        assert [r["version"] for r in await db.fetch(
            "SELECT version FROM workflow_reconcile_versions WHERE workflow_id = $1::uuid", workflow_id)] == [3]
        # The caller edits on from the version it was answered.
        again = await _apply(db, workflow_id, [{"op": "update_step", "id": "hook2", "name": "Orders"}],
                             if_version=edited.version)
        assert again.version == 4 and _labels((await _graph(db, workflow_id))["workflow"])["hook2"] == "Orders"

    async def test_another_writers_change_after_the_answer_makes_its_version_stale(self, db, told, registry):
        from utils.webhook_manager import WebhookManager

        workflow_id = await _workflow(db)

        async def provision(pool, *, node_id, workflow_id, **kwargs):
            await db.execute("""UPDATE workflows SET workflow = workflow || '{"theirs": true}'::jsonb """
                             "WHERE id = $1::uuid", workflow_id)
            return {"webhook_url": f"https://hooks.example/{node_id}"}

        with patch.object(WebhookManager, "provision_node_webhook", side_effect=provision):
            edited = await _apply(db, workflow_id, [{"op": "add_step", "type": "trigger-webhook", "id": "hook2"}])
        assert (edited.version, (await _graph(db, workflow_id))["graph_version"]) == (2, 4)
        # The change it never saw (version 3, not a reconcile's) refuses an edit from its version.
        with pytest.raises(GraphError) as stale:
            await _apply(db, workflow_id, [{"op": "remove_step", "id": "hook2"}], if_version=edited.version)
        assert stale.value.details["version"] == 4

    async def test_a_step_a_restore_brings_back_registers_again(self, db, told, registry):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "hook"}])
        await _restore(db, workflow_id, 1)
        assert registry["registered"] == [["hook"]]

    async def test_a_job_run_once_its_workflow_is_in_the_trash_registers_nothing(self, db, told, registry):
        """Trashing a workflow stops its triggers and restoring it registers them again, so a job from before the
        trash, run after it (a retry, a sweep, the daily retry of one given up on), only tears down the steps its
        change removed: a trashed workflow's schedule or provider webhook never comes back on."""
        from utils.workflow_reconcile import reconcile_graph_change

        before = {"nodes": [node("cron", "trigger-cron", schedule={"frequency": "daily", "time": "08:00"},
                                 webhook_url="https://h/2"),
                            node("log", "log", label="Log", message="done")], "edges": []}
        after = {"nodes": [node("cron", "trigger-cron", schedule={"frequency": "daily", "time": "09:00"},
                                webhook_url="https://h/2"),
                           node("hook2", "trigger-webhook", label="Orders")], "edges": []}
        workflow_id = await _workflow(db, after)
        await db.execute("UPDATE workflows SET deleted_at = now() WHERE id = $1::uuid", workflow_id)
        await reconcile_graph_change(db.pool, workflow_id, OWNER, before, after)
        assert (registry["reconciled"], registry["provisioned"], registry["registered"]) == ([], [], [])
        assert registry["cleaned"] == [(["log"], ["log"])]
        assert await db.fetchval("SELECT status FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid",
                                 workflow_id) == "done"
        # Out of the trash, the same change registers as any change does.
        await db.execute("UPDATE workflows SET deleted_at = NULL WHERE id = $1::uuid", workflow_id)
        await reconcile_graph_change(db.pool, workflow_id, OWNER, before, after)
        assert registry["reconciled"] == ["cron"] and registry["provisioned"] == ["hook2"]
        assert registry["registered"] == [["hook2"]]


class TestTheCanvasSave:
    def _handler(self, db, user=OWNER):
        from wss.handlers.workflow_handler import WorkflowHandler

        sio = MagicMock()
        sio.get_session = AsyncMock(return_value={"user_id": user})
        sio.emit = AsyncMock()
        handler = WorkflowHandler(sio=sio)
        handler.get_pool = AsyncMock(return_value=db.pool)
        return handler, sio

    async def _save(self, handler, workflow_id, graph, version=None):
        from wss.receiver.client_events import WorkflowUpdateRequest

        await handler.update_workflow("sid", WorkflowUpdateRequest(
            request_id="r", workflow_id=workflow_id, workflow_data=graph, expected_graph_version=version))

    async def test_a_session_is_one_version_and_moves_are_no_version_nor_reconcile(self, db, reconciled):
        from utils.async_helpers import drain_spawned_tasks

        workflow_id = await _workflow(db)
        handler, sio = self._handler(db)
        renamed = copy.deepcopy(GRAPH)
        renamed["nodes"][2]["config"]["label"] = "Record"
        await self._save(handler, workflow_id, renamed, version=1)
        removed = copy.deepcopy(renamed)
        removed["nodes"] = removed["nodes"][:2]
        await self._save(handler, workflow_id, removed, version=2)
        moved = copy.deepcopy(removed)
        moved["nodes"][0]["position"] = {"x": 300, "y": 0}
        await self._save(handler, workflow_id, moved, version=3)
        await drain_spawned_tasks(timeout=5)
        assert [(v["version"], v["source"], v["author"], v["changes"]) for v in await _versions(db, workflow_id)] == [
            (1, "baseline", None, []), (3, "canvas", OWNER, ["renamed 'Log' to 'Record'", "removed 'Record'"])]
        # The rename and the removal are reconciled; the move sets nothing in motion.
        assert len(reconciled) == 2
        assert "log" in _labels(reconciled[1][1]) and "log" not in _labels(reconciled[1][2])

    async def test_a_change_to_only_the_workflows_fields_joins_the_canvas_version_or_waits(self, db, reconciled):
        from wss.receiver.client_events import WorkflowUpdateRequest

        workflow_id = await _workflow(db)
        handler, sio = self._handler(db)
        # No version of this author's from the canvas yet: the rename moves no version (the canvas's next save
        # mustn't conflict with it), and the next version carries it.
        await handler.update_workflow("sid", WorkflowUpdateRequest(request_id="r", workflow_id=workflow_id,
                                                                   name="First"))
        assert (await _graph(db, workflow_id))["graph_version"] == 1 and await _versions(db, workflow_id) == []
        renamed = copy.deepcopy(GRAPH)
        renamed["nodes"][2]["config"]["label"] = "Record"
        await self._save(handler, workflow_id, renamed, version=1)
        await handler.update_workflow("sid", WorkflowUpdateRequest(
            request_id="r", workflow_id=workflow_id, name="Second", settings={"variable_definitions": []}))
        row = await _graph(db, workflow_id)
        assert (row["graph_version"], row["name"]) == (2, "Second")
        [_, two] = await _versions(db, workflow_id)
        assert two["version"] == 2 and two["changes"] == [
            "renamed 'Log' to 'Record'", "renamed the workflow to 'Second'", "changed its variables"]
        version = await graph_service.version(db.pool, Author(OWNER), workflow_id, 2)
        assert (version["name"], version["settings"]) == ("Second", {"variable_definitions": []})
        assert (await graph_service.version(db.pool, Author(OWNER), workflow_id, 1))["name"] == "First"

    async def test_a_save_tears_down_only_what_it_says_it_deleted(self, db):
        """A save with no version (a closing tab's last flush) whose graph lacks a step it never deleted tears
        nothing down; the steps it names as deleted are, as is one deleted before it was ever saved."""
        from utils.async_helpers import drain_spawned_tasks
        from utils.webhook_manager import WebhookManager
        from wss.receiver.client_events import WorkflowUpdateRequest

        workflow_id = await _workflow(db)
        handler, _ = self._handler(db)
        cleaned = []

        async def cleanup(*, pool, workflow_id, node_ids, background, old_nodes, requesting_user_id):
            cleaned.append((sorted(node_ids), sorted(n["id"] for n in old_nodes or [])))

        stale = copy.deepcopy(GRAPH)
        stale["nodes"] = [n for n in stale["nodes"] if n["id"] != "log"]
        with patch("utils.workflow_resource_manager.cleanup_nodes_resources", side_effect=cleanup), \
                patch.object(WebhookManager, "provision_node_webhook", AsyncMock(return_value=None)):
            await handler.update_workflow("sid", WorkflowUpdateRequest(
                request_id="r", workflow_id=workflow_id, workflow_data=stale))
            await drain_spawned_tasks(timeout=5)
            assert cleaned == []
            deleted = copy.deepcopy(stale)
            deleted["nodes"] = [n for n in deleted["nodes"] if n["id"] != "agent"]
            await handler.update_workflow("sid", WorkflowUpdateRequest(
                request_id="r", workflow_id=workflow_id, workflow_data=deleted, deleted_node_ids=["agent", "draft"]))
            await drain_spawned_tasks(timeout=5)
        assert cleaned == [(["agent", "draft"], ["agent"])]

    async def test_a_canvas_session_is_one_version_whoever_edits_in_it(self, db, told, reconciled):
        """Canvas saves within five minutes of the session's first are one version listing its authors; a write
        from anywhere else closes it and is a version of its own, and the canvas starts another after it."""
        workflow_id = await _workflow(db)
        await db.execute("INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, "
                         "permission, shared_by) VALUES ('workflow', $1::uuid, 'user', $2::uuid, 'edit', $3::uuid)",
                         workflow_id, EDITOR, OWNER)
        mine, _ = self._handler(db)
        theirs, _ = self._handler(db, EDITOR)
        graph = copy.deepcopy(GRAPH)
        for handler, label, version in ((mine, "One", 1), (theirs, "Two", 2), (mine, "Three", 3)):
            graph["nodes"][2]["config"]["label"] = label
            await self._save(handler, workflow_id, copy.deepcopy(graph), version=version)
        rows = await db.fetch("SELECT history_version, version, source, authors::text[] AS authors "
                              "FROM workflow_versions WHERE workflow_id = $1::uuid ORDER BY version", workflow_id)
        assert [(r["history_version"], r["version"], r["source"], r["authors"]) for r in rows] == [
            (1, 1, "baseline", []), (2, 4, "canvas", [OWNER, EDITOR])]
        session = await graph_service.version(db.pool, Author(OWNER), workflow_id, 2)
        assert session["authors"] == [{"user_id": OWNER, "key_id": None}, {"user_id": EDITOR, "key_id": None}]
        await _apply(db, workflow_id, [{"op": "update_step", "id": "agent", "settings": {"message": "Mine."}}],
                     source="coordinator")
        graph = copy.deepcopy((await _graph(db, workflow_id))["workflow"])
        graph["nodes"][2]["config"]["label"] = "Four"
        await self._save(mine, workflow_id, graph, version=5)
        assert [(v["history_version"], v["source"]) for v in await _versions(db, workflow_id)] == [
            (1, "baseline"), (2, "canvas"), (5, "coordinator"), (6, "canvas")]
        # The coordinator's edit is undone on its own: the canvas session before it holds none of it.
        assert next(n for n in session["graph"]["nodes"] if n["id"] == "agent")["config"]["message"] == "Sum up."

    async def test_an_open_canvas_echoing_a_write_leaves_the_version_the_write_answered(self, db, told,
                                                                                         reconciled):
        """The canvas saves what it now shows (the write applied, in its own shape: edges without their style);
        that writes nothing, so the version the write answered stays the one to edit on from."""
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "connect", "from": "agent", "to": "log"}])
        stored = (await _graph(db, workflow_id))["workflow"]
        assert any(e.get("type") for e in stored["edges"])
        echo = {"nodes": stored["nodes"], "edges": [
            {k: e[k] for k in ("id", "source", "target", "sourceHandle", "targetHandle") if k in e}
            for e in stored["edges"]]}
        handler, sio = self._handler(db)
        await self._save(handler, workflow_id, echo, version=edited.version)
        answer = sio.emit.await_args.args[1]["data"]
        assert answer["workflow"]["graph_version"] == edited.version
        assert (await _graph(db, workflow_id))["graph_version"] == edited.version
        again = await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Next"}],
                             if_version=edited.version)
        assert again.version == edited.version + 1

    async def test_an_echo_without_a_setting_a_write_cleared_writes_nothing(self, db, told, reconciled):
        """A write that clears a setting stores it as null (a trigger's mirrors after a reconcile), and the canvas
        that applied it holds no such setting (``node_updated`` sends it as null, which the canvas drops): its
        echo is still the graph as stored. So is one holding a null the store doesn't."""
        cleared = copy.deepcopy(GRAPH)
        cleared["nodes"][0]["config"].update(trigger_error=None, paused_reason=None)
        workflow_id = await _workflow(db, cleared)
        handler, sio = self._handler(db)
        await self._save(handler, workflow_id, copy.deepcopy(GRAPH), version=1)
        nulled = copy.deepcopy(GRAPH)
        nulled["nodes"][2]["config"]["stale_key"] = None
        await self._save(handler, workflow_id, nulled, version=1)
        assert sio.emit.await_args.args[1]["data"]["workflow"]["graph_version"] == 1
        assert (await _graph(db, workflow_id))["graph_version"] == 1 and await _versions(db, workflow_id) == []

    async def test_a_step_held_in_part_keeps_its_settings_as_stored(self, db, told, reconciled):
        """A step the room held part of back, which the canvas hasn't read whole yet, is saved with what the canvas
        does hold of it (it moved), never its settings; one no longer stored isn't written back."""
        from wss.receiver.client_events import WorkflowUpdateRequest

        workflow_id = await _workflow(db)
        handler, sio = self._handler(db)
        shown = copy.deepcopy(GRAPH)
        log = next(n for n in shown["nodes"] if n["id"] == "log")
        log["config"], log["position"] = {}, {"x": 500, "y": 40}
        shown["nodes"].append(node("gone", "log", label="Gone"))
        shown["edges"].append({"id": "log-gone", "source": "log", "target": "gone"})
        await handler.update_workflow("sid", WorkflowUpdateRequest(
            request_id="r", workflow_id=workflow_id, workflow_data=shown, expected_graph_version=1,
            partial_node_ids=["log", "gone"]))
        assert not sio.emit.await_args.args[1].get("error"), sio.emit.await_args.args[1]
        stored = (await _graph(db, workflow_id))["workflow"]
        saved = next(n for n in stored["nodes"] if n["id"] == "log")
        assert saved["config"] == {"label": "Log", "message": "done"} and saved["position"] == {"x": 500, "y": 40}
        assert [n["id"] for n in stored["nodes"]] == ["hook", "agent", "log"]
        assert [e["id"] for e in stored["edges"]] == ["hook-agent"]

    async def test_a_closing_tabs_save_on_an_old_version_writes_only_its_own_changes(self, db, told, reconciled):
        """A tab that missed later writes (its room was down) saves as it closes, on the version it last saw and
        with nothing to rebase on: what it changed lands on the workflow as it stands, and nothing it missed (an
        added step, another's change) is lost."""
        from wss.receiver.client_events import WorkflowCanvasChanges, WorkflowUpdateRequest

        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [
            {"op": "add_step", "type": "log", "id": "tock", "name": "Tock", "settings": {"message": "tock"}},
            {"op": "update_step", "id": "agent", "settings": {"message": "Theirs."}}])
        version = (await _graph(db, workflow_id))["graph_version"]
        mine = copy.deepcopy(GRAPH)
        next(n for n in mine["nodes"] if n["id"] == "log")["config"]["label"] = "Mine"
        mine["nodes"] = [n for n in mine["nodes"] if n["id"] != "hook"]
        mine["edges"] = [{"id": "agent-log", "source": "agent", "target": "log"}]
        handler, sio = self._handler(db)
        await handler.update_workflow("sid", WorkflowUpdateRequest(
            request_id="r", workflow_id=workflow_id, workflow_data=mine, expected_graph_version=1,
            deleted_node_ids=["hook"], changes=WorkflowCanvasChanges(
                steps=["log"], edges_added=["agent-log"], edges_removed=["hook-agent"])))
        assert not sio.emit.await_args.args[1]["data"].get("conflict"), sio.emit.await_args.args[1]
        row = await _graph(db, workflow_id)
        assert row["graph_version"] == version + 1
        labels = _labels(row["workflow"])
        assert labels == {"agent": "Helper", "log": "Mine", "tock": "Tock"}
        agent = next(n for n in row["workflow"]["nodes"] if n["id"] == "agent")
        assert agent["config"]["message"] == "Theirs."
        assert [e["id"] for e in row["workflow"]["edges"]] == ["agent-log"]

    async def test_a_canvas_save_keeps_a_secret_the_canvas_never_had(self, db, told, reconciled):
        graph = {"nodes": [node("fetch", "automation-http-request", url="https://api.example",
                                operation="send_http_get_request", api_key="sk-live-123",
                                headers=[{"key": "Authorization", "value": "Bearer abc"}])], "edges": []}
        workflow_id = await _workflow(db, graph)
        shown = copy.deepcopy(graph)
        shown["nodes"][0]["config"] = {"url": "https://api.example/v2", "operation": "send_http_get_request",
                                       "headers": [{"key": "Authorization"}], "label": "Fetch"}
        handler, sio = self._handler(db)
        await self._save(handler, workflow_id, shown, version=1)
        config = (await _graph(db, workflow_id))["workflow"]["nodes"][0]["config"]
        assert (config["url"], config["api_key"], config["headers"]) == (
            "https://api.example/v2", "sk-live-123", [{"key": "Authorization", "value": "Bearer abc"}])

    async def test_a_stale_save_records_nothing(self, db, reconciled):
        workflow_id = await _workflow(db)
        handler, sio = self._handler(db)
        await self._save(handler, workflow_id, {"nodes": [], "edges": []}, version=7)
        assert sio.emit.await_args.args[1]["data"]["conflict"] is True
        assert await _versions(db, workflow_id) == [] and reconciled == []
