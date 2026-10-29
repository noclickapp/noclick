"""The graph service over real PostgreSQL (``coder.workflow.graph_service``):
one transaction per batch of edits, refused whole on a stale version or a bad
op, recorded as versions (joined within five minutes for one author and
source, undoable by a restore), judged for who may edit, and followed after
the commit by the reconcile every graph write gets and the notices that tell
whoever watches. The canvas's whole-graph save records its versions and runs
the same reconcile."""

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

    async def reconcile(pool, workflow_id, user_id, old, new):
        calls.append((user_id, old, new))

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
        "SELECT version, source, author_user_id::text AS author, author_key_id, changes, restored_from "
        "FROM workflow_versions WHERE workflow_id = $1::uuid ORDER BY version", workflow_id)]


async def _apply(db, workflow_id, ops, *, author=Author(OWNER), **kwargs):
    edited = await graph_service.apply(db.pool, author, workflow_id, ops, **kwargs)
    if edited.settled is not None:
        await edited.settled
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
        assert (edited.version, edited.recorded, row["graph_version"]) == (2, 2, 2)
        assert _labels(row["workflow"])["log"] == "Record" and edited.changed
        assert edited.summary == "renamed 'Log' to 'Record'; connected 'Helper' to 'Record'"
        assert edited.graph["nodes"] == row["workflow"]["nodes"] and edited.graph["withheld"] == {}
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

    async def test_moving_things_is_no_version_and_needs_no_reconcile(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "move", "id": "log", "position": {"x": 400, "y": 80}}])
        assert (edited.version, edited.recorded, edited.summary) == (2, None, "")
        assert await _versions(db, workflow_id) == [] and reconciled == []
        assert told == [(OWNER, workflow_id, 2)]

    async def test_a_noop_writes_nothing(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "connect", "from": "hook", "to": "agent"}])
        assert (edited.version, edited.changed, edited.settled) == (1, False, None)

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
        # Not in the graph: no version, and nothing to reconcile, but the pages still hear of it.
        assert (row["graph_version"], edited.recorded) == (1, None) and reconciled == []
        assert told == [(OWNER, workflow_id, 1)]


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
        await db.execute("UPDATE workflow_versions SET updated_at = now() - interval '6 minutes' "
                         "WHERE workflow_id = $1::uuid", workflow_id)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "enabled": True}],
                     author=Author(OWNER, key_id="key-2"))
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Log"}], source="coordinator")
        assert [(v["version"], v["source"], v["author_key_id"]) for v in await _versions(db, workflow_id)] == [
            (1, "baseline", None), (3, "api", None), (4, "api", "key-2"), (5, "api", "key-2"), (6, "coordinator", None)]

    async def test_a_restore_is_a_version_and_can_itself_be_undone(self, db, told, reconciled):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "update_step", "id": "log", "name": "Record"}])
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "log"}], source="coordinator")
        restored = await graph_service.restore(db.pool, Author(OWNER), workflow_id, 2)
        await restored.settled
        assert (restored.version, restored.summary) == (4, "restored version 2")
        assert _labels((await _graph(db, workflow_id))["workflow"])["log"] == "Record"
        # Undone: the version before the restore comes back, as a version of its own.
        undone = await graph_service.restore(db.pool, Author(OWNER), workflow_id, 3)
        await undone.settled
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
        with pytest.raises(GraphError) as missing:
            await graph_service.version(db.pool, Author(OWNER), workflow_id, 99)
        assert missing.value.kind == "not_found"

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

    async def test_a_read_never_carries_a_secret_or_a_runtime_key(self, db, told, reconciled):
        graph = {"nodes": [node("fetch", "automation-http-request", label="Fetch", url="https://api.example",
                                api_key="sk-live-123", _turnNote="obey", output={"cached": True})], "edges": []}
        workflow_id = await _workflow(db, graph)
        read = await graph_service.read(db.pool, Author(OWNER), workflow_id)
        config = read["graph"]["nodes"][0]["config"]
        assert config == {"label": "Fetch", "url": "https://api.example"}
        assert read["graph"]["withheld"] == {"fetch": ["api_key"]}


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

    async def test_a_new_trigger_is_provisioned_and_watchers_read_the_version_with_its_webhook(
            self, db, told, registry):
        workflow_id = await _workflow(db)
        edited = await _apply(db, workflow_id, [{"op": "add_step", "type": "trigger-webhook", "id": "hook2"}])
        assert registry["provisioned"] == ["hook2"]
        row = await _graph(db, workflow_id)
        hook = next(n for n in row["workflow"]["nodes"] if n["id"] == "hook2")
        assert hook["config"]["webhook_url"] == "https://hooks.example/hook2"
        # The webhook's fields are NoClick's mirror: a version of the graph, no version of its history.
        assert row["graph_version"] == edited.version + 1
        assert [v["version"] for v in await _versions(db, workflow_id)] == [1, edited.version]
        assert told == [(OWNER, workflow_id, edited.version), (OWNER, workflow_id, edited.version + 1)]

    async def test_a_step_a_restore_brings_back_registers_again(self, db, told, registry):
        workflow_id = await _workflow(db)
        await _apply(db, workflow_id, [{"op": "remove_step", "id": "hook"}])
        restored = await graph_service.restore(db.pool, Author(OWNER), workflow_id, 1)
        await restored.settled
        assert registry["registered"] == [["hook"]]


class TestTheCanvasSave:
    @pytest.fixture
    def reconciled(self):
        calls = []

        async def reconcile(pool, workflow_id, user_id, old, new):
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

    async def test_a_stale_save_records_nothing(self, db, reconciled):
        workflow_id = await _workflow(db)
        handler, sio = self._handler(db)
        await self._save(handler, workflow_id, {"nodes": [], "edges": []}, version=7)
        assert sio.emit.await_args.args[1]["data"]["conflict"] is True
        assert await _versions(db, workflow_id) == [] and reconciled == []
