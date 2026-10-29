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

    async def tell(owner_id, workflow_id, version):
        calls.append((owner_id, workflow_id, version))

    with patch("coder.workflow.graph_service.tell", side_effect=tell):
        yield calls


@pytest.fixture
def reconciled():
    """Each reconcile the service ran, as (user, old graph, new graph)."""
    calls = []

    async def reconcile(pool, workflow_id, user_id, old, new, *, version=None):
        calls.append((user_id, old, new))
        return version

    with patch("utils.workflow_reconcile.reconcile_graph_change", side_effect=reconcile):
        yield calls


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

    async def test_two_authors_taking_turns_each_keep_their_one_version(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        other = Author(OWNER, key_id="key-2")
        for name in ("A", "B", "C"):
            await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": f"Log {name}"}])
            await _apply(db, workflow_id, [{"op": "update_step", "id": "agent", "settings": {"message": name}}],
                         author=other)
        # Each keeps the number its first write gave it, and orders by its latest.
        assert [(v["history_version"], v["version"], v["author_key_id"]) for v in await _versions(db, workflow_id)] \
            == [(1, 1, None), (2, 6, None), (3, 7, "key-2")]
        # Each is what it was when its author's turn ended: the newest, open, is the workflow as it stands.
        six = await graph_service.version(db.pool, Author(OWNER), workflow_id, 2)
        assert _labels(six["graph"])["log"] == "Log C" and six["changes"] == ["renamed 'Log' to 'Log A'",
                                                                              "renamed 'Log A' to 'Log B'",
                                                                              "renamed 'Log B' to 'Log C'"]
        seven = await graph_service.version(db.pool, Author(OWNER), workflow_id, 3)
        assert next(n for n in seven["graph"]["nodes"] if n["id"] == "agent")["config"]["message"] == "C"

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
        restored = await graph_service.restore(db.pool, Author(OWNER), workflow_id, 2)
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
        restored = await graph_service.restore(db.pool, Author(OWNER), workflow_id, 2)
        assert (restored.version, restored.summary) == (4, "restored version 2")
        assert _labels((await _graph(db, workflow_id))["workflow"])["log"] == "Record"
        # Undone: the version before the restore comes back, as a version of its own.
        await graph_service.restore(db.pool, Author(OWNER), workflow_id, 3)
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
        restored = await graph_service.restore(db.pool, Author(OWNER), workflow_id, 2)
        assert restored.version == 4
        row = await db.fetchrow("SELECT name, description, settings, workflow FROM workflows WHERE id = $1::uuid",
                                workflow_id)
        # The workflow's own fields come back with its graph; NoClick's own setting stays as NoClick left it.
        assert (row["name"], row["description"]) == ("Flow", "")
        assert row["settings"] == {"variable_definitions": [{"name": "a", "value": "1"}], "kept_by_noclick": "later"}
        assert _labels(row["workflow"])["log"] == "Record"
        # A restore that would change nothing writes nothing.
        same = await graph_service.restore(db.pool, Author(OWNER), workflow_id, 4)
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
        await graph_service.restore(db.pool, Author(OWNER), workflow_id, 1)
        claimed = await db.fetchrow("SELECT node_id, local_part, is_active FROM email_reservations "
                                    "WHERE workflow_id = $1::uuid", workflow_id)
        assert (claimed["node_id"], claimed["local_part"], claimed["is_active"]) == ("inbox", local, True)
        # Taken meanwhile by another workflow's step, the restore is refused and nothing of it lands.
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "inbox"}])
        other = await _workflow(db)
        await EmailReservationManager.reserve(db.pool, OWNER, other, "theirs", local)
        with pytest.raises(GraphError) as taken:
            await graph_service.restore(db.pool, Author(OWNER), workflow_id, 1)
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

    async def test_one_workflows_reconciles_run_one_at_a_time(self, db, told, registry):
        import asyncio

        from utils.webhook_manager import WebhookManager
        from utils.workflow_reconcile import reconcile_graph_change

        workflow_id = await _workflow(db)
        running, overlapped = [], []

        async def slow(*args, **kwargs):
            overlapped.append(bool(running))
            running.append(1)
            await asyncio.sleep(0.2)
            running.pop()

        renamed = copy.deepcopy(GRAPH)
        renamed["nodes"][0]["config"]["label"] = "Renamed"
        with patch.object(WebhookManager, "handle_registration_fields_change", side_effect=slow):
            await asyncio.gather(*(reconcile_graph_change(db.pool, workflow_id, OWNER, GRAPH, renamed)
                                   for _ in range(2)))
        assert len(overlapped) >= 2 and not any(overlapped)

    async def test_a_new_trigger_is_provisioned_and_the_version_handed_back_has_its_webhook(
            self, db, told, registry):
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "add_step", "type": "trigger-webhook", "id": "hook2"}],
                              include_graph=True)
        assert registry["provisioned"] == ["hook2"]
        row = await _graph(db, workflow_id)
        hook = next(n for n in row["workflow"]["nodes"] if n["id"] == "hook2")
        assert hook["config"]["webhook_url"] == "https://hooks.example/hook2"
        # The webhook's fields are NoClick's mirror: they move the graph's version, not its history, and the
        # version handed back (and the one notice) is the one they left.
        assert (edited.version, edited.history_version, row["graph_version"]) == (3, 2, 3)
        assert next(n for n in edited.definition["graph"]["nodes"] if n["id"] == "hook2")["config"]["webhook_url"]
        assert [v["version"] for v in await _versions(db, workflow_id)] == [1, 2]
        assert told == [(OWNER, workflow_id, 3)]
        # So the caller edits on from it.
        again = await _apply(db, workflow_id, [{"op": "update_step", "id": "hook2", "name": "Orders"}],
                             if_version=edited.version)
        assert again.version == 4 and _labels((await _graph(db, workflow_id))["workflow"])["hook2"] == "Orders"

    async def test_another_writers_change_in_between_keeps_the_writes_own_version(self, db, told, registry):
        from utils.webhook_manager import WebhookManager

        workflow_id = await _workflow(db)

        async def provision(pool, *, node_id, workflow_id, **kwargs):
            await db.execute("""UPDATE workflows SET workflow = workflow || '{"theirs": true}'::jsonb """
                             "WHERE id = $1::uuid", workflow_id)
            return {"webhook_url": f"https://hooks.example/{node_id}"}

        with patch.object(WebhookManager, "provision_node_webhook", side_effect=provision):
            edited = await _apply(db, workflow_id, [{"op": "add_step", "type": "trigger-webhook", "id": "hook2"}])
        assert (edited.version, (await _graph(db, workflow_id))["graph_version"]) == (2, 4)
        # The change it never saw refuses an edit from its version.
        with pytest.raises(GraphError) as stale:
            await _apply(db, workflow_id, [{"op": "remove_step", "id": "hook2"}], if_version=edited.version)
        assert stale.value.details["version"] == 4

    async def test_a_step_a_restore_brings_back_registers_again(self, db, told, registry):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "hook"}])
        await graph_service.restore(db.pool, Author(OWNER), workflow_id, 1)
        assert registry["registered"] == [["hook"]]


class TestTheCanvasSave:
    @pytest.fixture
    def reconciled(self):
        calls = []

        async def reconcile(pool, workflow_id, user_id, old, new, **kwargs):
            calls.append((user_id, old, new))

        with patch("wss.handlers.workflow_handler.reconcile_graph_change", side_effect=reconcile):
            yield calls

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

    async def test_a_session_is_one_version_moves_are_none_and_each_save_is_reconciled(self, db, reconciled):
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
        assert len(reconciled) == 3
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

    async def test_a_stale_save_records_nothing(self, db, reconciled):
        workflow_id = await _workflow(db)
        handler, sio = self._handler(db)
        await self._save(handler, workflow_id, {"nodes": [], "edges": []}, version=7)
        assert sio.emit.await_args.args[1]["data"]["conflict"] is True
        assert await _versions(db, workflow_id) == [] and reconciled == []
