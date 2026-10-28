"""The Table step (``automation-table``): rows in the automation's own tables,
against real Postgres, on the store this instance registers (hosted: each
automation's own database, here on the database Worker's fake; the open
edition: Postgres) and on the engine's own Postgres store.

What it writes is the same table the Table block, Resources and the SDK read
(``utils.dataset_store`` on the same ``dataset`` resource); a name it doesn't
hold yet is made by the first Add, once however many Adds race for it; it
reaches only its own automation's tables; the seam's limits hold; and an agent
wired to it gets ``table__*`` tools that do the same.
"""

import asyncio
import json
import uuid

import pytest

from nodes.agent.node_op_tools import build_node_op_tools, node_supports_op_tools
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import needs_credential_hint, run_node_lookup, run_node_op_tool
from repositories.datasets import PostgresDatasets
from repositories.resources import ResourceRepo
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils import dataset_store
from utils.dataset_store import MAX_PAGE_ROWS, MAX_ROW_BYTES, DatasetError

pytestmark = pytest.mark.asyncio

TYPE = "automation-table"


@pytest.fixture(params=["registered", "postgres"])
def store(request, monkeypatch):
    if request.param == "postgres":
        monkeypatch.setattr(dataset_store, "_factory", PostgresDatasets)
    return request.param


async def _workflow(db, name="Leads finder"):
    owner = str(uuid.uuid4())
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2)", owner, f"{owner}@example.com")
    workflow = await db.fetchval("INSERT INTO workflows (owner_id, name) VALUES ($1, $2) RETURNING id", owner, name)
    return str(workflow), owner


async def _run(workflow, owner, operation, **config):
    node = NodeFactory.create_node(node_id="table", node_type=TYPE,
                                   node_data={"config": {"operation": operation, **config}},
                                   workflow_id=workflow, user_id=owner)
    return await node.run({})


async def _tables(db, workflow):
    return await ResourceRepo(db.pool).workflow_datasets(workflow)


async def _data(db, table):
    rows, _ = await dataset_store.read_rows(db.pool, table, limit=MAX_PAGE_ROWS)
    return [r["data"] for r in rows]


class TestAdd:
    async def test_the_first_add_makes_the_table_the_block_and_resources_read(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        first = await _run(workflow, owner, "add_rows", table="Results",
                           rows=[{"title": "Ada", "score": 3}, {"title": "Grace", "score": 5}])
        assert first["created"] is True and first["added"] == 2 and first["table"] == "Results"
        again = await _run(workflow, owner, "add_rows", table="results", rows={"title": "Linus", "score": 1})
        assert again["created"] is False and again["table_id"] == first["table_id"] and again["added"] == 1

        [table] = await _tables(real_database, workflow)
        assert str(table["id"]) == first["table_id"] and table["name"] == "Results"
        assert str(table["owner_id"]) == owner and table["resource_type"] == "dataset"
        assert table["metadata"]["row_count"] == 3
        assert await _data(real_database, table) == [
            {"title": "Ada", "score": 3}, {"title": "Grace", "score": 5}, {"title": "Linus", "score": 1}]

    async def test_rows_written_as_json_text_and_an_upstream_list_whole(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        await _run(workflow, owner, "add_rows", table="Log", rows='[{"a": 1}, {"a": 2}]')
        await _run(workflow, owner, "add_rows", table="Log", rows='{"a": 3}')
        await _run(workflow, owner, "add_rows", table="Log", rows=[])
        [table] = await _tables(real_database, workflow)
        assert await _data(real_database, table) == [{"a": 1}, {"a": 2}, {"a": 3}]

    async def test_adds_racing_for_a_new_name_make_one_table(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        await asyncio.gather(*(_run(workflow, owner, "add_rows", table="Burst", rows=[{"i": i}]) for i in range(6)))
        [table] = await _tables(real_database, workflow)
        assert sorted(r["i"] for r in await _data(real_database, table)) == list(range(6))

    async def test_the_limits_hold_and_a_refused_add_makes_no_table(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        with pytest.raises(DatasetError, match="at most"):
            await _run(workflow, owner, "add_rows", table="Big", rows=[{"blob": "x" * MAX_ROW_BYTES}])
        assert await _tables(real_database, workflow) == []
        with pytest.raises(ConfigValidationError, match="rows.1"):
            await _run(workflow, owner, "add_rows", table="Big", rows=[{"ok": 1}, "just text"])
        with pytest.raises(ConfigValidationError, match="JSON"):
            await _run(workflow, owner, "add_rows", table="Big", rows="<_quickjs.Object object>")
        with pytest.raises(ConfigValidationError):
            await _run(workflow, owner, "read_rows", table="Big", limit=MAX_PAGE_ROWS + 1)

    async def test_a_step_reaches_only_its_own_automations_tables(self, real_database, store):
        mine, owner = await _workflow(real_database)
        theirs, other = await _workflow(real_database, "Someone else's")
        await _run(theirs, other, "add_rows", table="Results", rows=[{"secret": 1}])
        read = await _run(mine, owner, "read_rows", table="Results")
        assert read["rows"] == [] and read["total"] == 0 and read["table_id"] is None
        await _run(mine, owner, "add_rows", table="Results", rows=[{"mine": 1}])
        [their_table] = await _tables(real_database, theirs)
        assert await _data(real_database, their_table) == [{"secret": 1}]


class TestRead:
    async def test_pages_of_every_row_in_order(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        await _run(workflow, owner, "add_rows", table="T", rows=[{"n": i} for i in range(5)])
        page = await _run(workflow, owner, "read_rows", table="T", limit=2, offset=1)
        assert [r["data"]["n"] for r in page["rows"]] == [1, 2]
        assert page["total"] == 5 and page["has_more"] is True
        assert all(r["id"] and isinstance(r["created_at"], str) for r in page["rows"])
        last = await _run(workflow, owner, "read_rows", table="T", limit=2, offset=4)
        assert [r["data"]["n"] for r in last["rows"]] == [4] and last["has_more"] is False

    async def test_a_match_on_a_column(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        await _run(workflow, owner, "add_rows", table="T", rows=[
            {"email": "a@x.com", "n": 1, "vip": True}, {"email": "b@x.com", "n": 2, "vip": False},
            {"email": "a@x.com", "n": 3, "vip": True}, {"email": None, "n": 4}, {"n": 5}])
        found = await _run(workflow, owner, "read_rows", table="T", match_column="email", match_value="a@x.com")
        assert [r["data"]["n"] for r in found["rows"]] == [1, 3] and found["total"] == 2
        assert [r["data"]["n"] for r in (await _run(workflow, owner, "read_rows", table="T", match_column="n",
                                                   match_value="2"))["rows"]] == [2]
        # A template resolving to a number or true/false reaches the step as its text.
        assert (await _run(workflow, owner, "read_rows", table="T", match_column="vip", match_value=True))["total"] == 2
        paged = await _run(workflow, owner, "read_rows", table="T", match_column="email", match_value="a@x.com",
                           limit=1, offset=1)
        assert [r["data"]["n"] for r in paged["rows"]] == [3] and paged["total"] == 2 and not paged["has_more"]
        with pytest.raises(ConfigValidationError, match="both a column and the value"):
            await _run(workflow, owner, "read_rows", table="T", match_column="email")


class TestUpdate:
    async def test_by_id_sets_the_columns_given_and_keeps_the_rest(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        await _run(workflow, owner, "add_rows", table="T", rows=[{"name": "Ada", "status": "new"}, {"name": "Bo"}])
        [first, _] = (await _run(workflow, owner, "read_rows", table="T"))["rows"]
        done = await _run(workflow, owner, "update_rows", table="T", row_id=first["id"],
                          values='{"status": "done", "at": 1}')
        assert done["updated"] == 1
        [table] = await _tables(real_database, workflow)
        assert await _data(real_database, table) == [{"name": "Ada", "status": "done", "at": 1}, {"name": "Bo"}]
        with pytest.raises(ValueError, match="has no row"):
            await _run(workflow, owner, "update_rows", table="T", row_id=str(uuid.uuid4()), values={"x": 1})

    async def test_by_match_sets_every_matching_row(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        await _run(workflow, owner, "add_rows", table="T", rows=[
            {"order": "7", "state": "open"}, {"order": 8, "state": "open"}, {"order": 7, "state": "open"}])
        assert (await _run(workflow, owner, "update_rows", table="T", match_column="order", match_value="7",
                           values={"state": "shipped"}))["updated"] == 2
        [table] = await _tables(real_database, workflow)
        assert [r["state"] for r in await _data(real_database, table)] == ["shipped", "open", "shipped"]
        missing = await _run(workflow, owner, "update_rows", table="Not made", match_column="order", match_value="7",
                             values={"state": "x"})
        assert missing["updated"] == 0

    async def test_the_rows_are_named_once(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        for config in ({}, {"row_id": "r", "match_column": "a", "match_value": "b"}):
            with pytest.raises(ConfigValidationError, match="Row ID or by Match column"):
                await _run(workflow, owner, "update_rows", table="T", values={"x": 1}, **config)
        with pytest.raises(ConfigValidationError, match="at least one column"):
            await _run(workflow, owner, "update_rows", table="T", row_id="r", values={})


class TestDelete:
    async def test_by_id_and_by_match(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        await _run(workflow, owner, "add_rows", table="T", rows=[{"k": "a"}, {"k": "b"}, {"k": "a"}, {"k": "c"}])
        [first, *_] = (await _run(workflow, owner, "read_rows", table="T"))["rows"]
        assert (await _run(workflow, owner, "delete_rows", table="T", row_id=first["id"]))["deleted"] == 1
        assert (await _run(workflow, owner, "delete_rows", table="T", match_column="k", match_value="a"))["deleted"] == 1
        [table] = await _tables(real_database, workflow)
        assert await _data(real_database, table) == [{"k": "b"}, {"k": "c"}]
        fresh = await ResourceRepo(real_database.pool).get_resource(str(table["id"]))
        assert fresh["metadata"]["row_count"] == 2
        with pytest.raises(ValueError, match="has no row"):
            await _run(workflow, owner, "delete_rows", table="T", row_id=first["id"])


class TestPicker:
    async def test_lists_this_automations_tables_by_name_once_the_server_names_it(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        other, other_owner = await _workflow(real_database, "Other")
        await _run(workflow, owner, "add_rows", table="Leads", rows=[{"a": 1}])
        await _run(workflow, owner, "add_rows", table="Orders", rows=[{"a": 1}])
        await _run(other, other_owner, "add_rows", table="Private", rows=[{"a": 1}])
        repo = ResourceRepo(real_database.pool)
        dup = await repo.create_resource(owner_id=owner, organization_id=None, workflow_id=workflow, node_id=None,
                                         resource_type="dataset", name="leads", mime_type=None, size_bytes=0,
                                         storage_ref=None, metadata={})
        await dataset_store.create_dataset(real_database.pool, dup)

        load = NODE_REGISTRY[TYPE].load_field_options
        listed = await load("table", {}, {"_workflow_id": workflow})
        assert [o["value"] for o in listed["options"]] == ["Leads", "Orders"]
        assert (await load("table", {}, {"_workflow_id": workflow}, search="ord"))["options"] == [
            {"value": "Orders", "label": "Orders"}]
        assert (await load("table", {}, {}))["options"] == []

        # The agent's lookup tool names its own automation; a caller's own _workflow_id never counts.
        via_agent = await run_node_lookup(node_type=TYPE, field_name="table", user_id=owner, workflow_id=workflow,
                                          context={"_workflow_id": other})
        assert [o["value"] for o in via_agent["options"]] == ["Leads", "Orders"]
        forged = await run_node_lookup(node_type=TYPE, field_name="table", user_id=owner,
                                       context={"_workflow_id": other})
        assert forged["options"] == []


    async def test_the_canvas_picker_names_the_open_workflow_only_to_who_may_see_it(self, real_database, store):
        from unittest.mock import AsyncMock, MagicMock

        from wss.handlers.workflow_handler import WorkflowHandler
        from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest

        workflow, owner = await _workflow(real_database)
        _, stranger = await _workflow(real_database, "Stranger's")
        await _run(workflow, owner, "add_rows", table="Leads", rows=[{"a": 1}])

        async def picker(user, **request):
            sio = MagicMock()
            sio.get_session = AsyncMock(return_value={"user_id": user})
            sio.emit = AsyncMock()
            handler = WorkflowHandler(sio=sio)
            handler.get_pool = AsyncMock(return_value=real_database.pool)
            await handler.load_node_options("sid", WorkflowNodeLoadOptionsRequest(
                request_id="r", node_type=TYPE, field_name="table", **request))
            [response] = [c.args[1]["data"] for c in sio.emit.call_args_list if c.args[0] == "response"]
            assert response["success"] is True
            return [o["value"] for o in response["options"]]

        assert await picker(owner, workflow_id=workflow) == ["Leads"]
        assert await picker(stranger, workflow_id=workflow) == []
        assert await picker(stranger, context={"_workflow_id": workflow}) == []


class TestAgentTools:
    async def test_an_agent_wired_to_the_step_adds_and_reads_rows(self, real_database, store):
        assert node_supports_op_tools(TYPE)
        workflow, owner = await _workflow(real_database)
        params, configs = build_node_op_tools(TYPE, ["add_rows", "read_rows", "update_rows", "delete_rows"],
                                              node_id="table-1")
        names = {p["function"]["name"] for p in params}
        assert {"table__add_rows", "table__read_rows", "table__update_rows", "table__delete_rows",
                "table__lookup_options"} <= names
        add = next(p for p in params if p["function"]["name"] == "table__add_rows")["function"]["parameters"]
        assert add["properties"]["rows"]["type"] == "array" and set(add["required"]) == {"table", "rows"}

        async def call(tool, **arguments):
            return await run_node_op_tool(configs[tool], arguments, user_id=owner, workflow_id=workflow)

        assert (await call("table__add_rows", table="Seen", rows=[{"url": "https://a"}]))["created"] is True
        await call("table__update_rows", table="Seen", match_column="url", match_value="https://a",
                   values={"checked": True})
        read = await call("table__read_rows", table="Seen")
        assert [r["data"] for r in read["rows"]] == [{"url": "https://a", "checked": True}]
        listed = await call("table__lookup_options", field="table")
        assert [o["value"] for o in listed["options"]] == ["Seen"]

        [table] = await _tables(real_database, workflow)
        assert await _data(real_database, table) == [{"url": "https://a", "checked": True}]

    async def test_its_errors_reach_the_agent_as_they_are(self, real_database, store):
        workflow, owner = await _workflow(real_database)
        _, configs = build_node_op_tools(TYPE, ["update_rows"], node_id="table-1")
        assert not needs_credential_hint(TYPE, "update_rows")
        with pytest.raises(ValueError) as refused:
            await run_node_op_tool(configs["table__update_rows"], {"table": "T", "row_id": "nope", "values": {"a": 1}},
                                   user_id=owner, workflow_id=workflow)
        assert "has no row nope" in str(refused.value) and "credential" not in str(refused.value)


async def test_what_a_step_returns_is_declared_for_the_builders_reference_check(real_database, store):
    """The builder judges `$('save').rows` before the step ever ran, from the shape each operation returns."""
    from coder.workflow.workflow_ops import find_unknown_output_references

    workflow, owner = await _workflow(real_database)
    cls = NODE_REGISTRY[TYPE]
    for operation, config in (("add_rows", {"rows": [{"a": 1}]}), ("read_rows", {}),
                              ("update_rows", {"match_column": "a", "match_value": "1", "values": {"b": 2}}),
                              ("delete_rows", {"match_column": "a", "match_value": "1"})):
        output = await _run(workflow, owner, operation, table="T", **config)
        assert sorted(output) == sorted(cls.declared_output_keys({"operation": operation}))
    known = {"read": cls.declared_output_keys({"operation": "read_rows"})}
    assert find_unknown_output_references({"text": "{{ $('read').rows }}"}, known) == []
    assert find_unknown_output_references({"text": "{{ $('read').items }}"}, known)


async def test_its_tables_are_named_not_picked_from_an_account():
    """The builder names a table (a new one is made on its first Add): its picker is never an account input."""
    from coder.workflow.workflow_schema import is_account_dynamic_field

    schema = NODE_REGISTRY[TYPE].get_config_schema()
    for member in ("TableAddRowsConfig", "TableReadRowsConfig", "TableUpdateRowsConfig", "TableDeleteRowsConfig"):
        table = schema["$defs"][member]["properties"]["table"]
        assert table["x-dynamic-options"]["auto_select_sole_option"] is True
        assert not is_account_dynamic_field(table)
    assert json.loads(json.dumps(schema))  # what the frontend renders from


class TestBuilderAndMcp:
    """What the builder's and MCP's DSLs write is what the step runs."""

    def _state(self, operation="add_rows", **config):
        from coder.workflow.graph_state import GraphState, NodeState

        state = GraphState()
        state.nodes["save"] = NodeState(id="save", type=TYPE, label="Save results", goal="save each result",
                                        operation=operation, config=config)
        return state

    async def test_a_builder_write_runs_as_written(self, real_database, store):
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.operation_catalog import validate_node_config
        from coder.workflow.workflow_xml import parse_xml
        from utils.expression_evaluator import evaluate_expressions

        state = self._state()
        results = execute_field_ops(parse_xml(
            """<field name="table" node="save" value="Results" />"""
            """<field name="rows" node="save" value="{{ $('extract').items }}" />"""), state)
        assert not [r for r in results if "ERROR" in r or "REJECTED" in r], results
        assert validate_node_config(TYPE, "add_rows", state.nodes["save"].config) is None

        execute_field_ops(parse_xml(
            """<field name="rows" node="save" value='[{"title": "{{ $(\\'fetch\\').title }}", "n": 1}]' />"""), state)
        written = state.nodes["save"].config
        assert written["rows"] == [{"title": "{{ $('fetch').title }}", "n": 1}]
        assert validate_node_config(TYPE, "add_rows", written) is None

        workflow, owner = await _workflow(real_database)
        for config in ({**written, "rows": "{{ $('extract').items }}"}, written):
            resolved = await evaluate_expressions(
                {**config, "operation": "add_rows"},
                {"extract": {"items": [{"title": "Ada", "n": 0}]}, "fetch": {"title": 'Say "hi"'}})
            await _run(workflow, owner, **resolved)
        [table] = await _tables(real_database, workflow)
        assert await _data(real_database, table) == [{"title": "Ada", "n": 0}, {"title": 'Say "hi"', "n": 1}]

    async def test_an_mcp_write_lands_valid(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from mcp_server import NoClickMCPServer, _user_id_var

        workflow = {"nodes": [{"id": "save", "type": TYPE, "position": {"x": 0, "y": 0},
                               "data": {"config": {"operation": "update_rows"}}}], "edges": []}
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(MagicMock())
        srv._emit_builder_event = AsyncMock()
        srv._load_workflow = AsyncMock(return_value=(workflow, None))
        srv._save_workflow = AsyncMock(return_value=None)
        token = _user_id_var.set("user-1")
        try:
            result = await srv._process_update_workflow(
                workflow_id="wf-1", include_operations=False, include_configs=False,
                updates_xml="""<update_config id="save" table="Leads" match_column="email" """
                            """match_value="{{ $('trigger').email }}" values='{"status": "contacted"}' />""")
        finally:
            _user_id_var.reset(token)
        assert not result["errors"] and result["operations"][0]["config_valid"] is True
        assert workflow["nodes"][0]["data"]["config"]["values"] == {"status": "contacted"}
