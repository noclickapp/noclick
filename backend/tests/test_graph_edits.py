"""Typed graph edits (``coder.workflow.graph_edits``) judge a change as the
workflow MCP's and the AI builder's XML writes judge it: each op, applied to a
graph, leaves the steps' config and wiring the XML path leaves for the same
change, and refuses what it refuses with the same words. Positions are layout,
which each writer places its own way, so they aren't compared."""

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import coder.workflow.option_registries.resolver as resolver
from coder.workflow.graph_edits import (
    EditContext, EditRefused, apply_ops, describe_changes, merge_changes, parse_ops, summary,
)
from utils.graph_nodes import graph_edges, graph_nodes, node_config

OWNER = "00000000-0000-4000-8000-00000000ed17"
NODE = "agent-1"
# The agent as the /agents scaffold saved it, with its key and env vars attached.
SCAFFOLD_AGENT = {
    "label": "OpenCode", "model": "opencode", "opencode_model": "opencode/big-pickle",
    "message": "Keep Confluence and Monday.com in step",
    "credentialIds": {"agent_opencode": "cred-opencode", "agent_env": "cred-env"},
}


@pytest.fixture(autouse=True)
def _no_live_registry(monkeypatch):
    monkeypatch.setattr(resolver, "get_registry", lambda name: None)


def node(node_id, kind, **config):
    return {"id": node_id, "type": kind, "position": {"x": 0, "y": 0}, "config": config}


def edge(source, target, **handles):
    return {"id": f"{source}-{target}", "source": source, "target": target, "type": "animated", **handles}


BASE = {
    "nodes": [
        node("hook", "trigger-webhook", label="Hook"),
        node("agent", "agent", label="Helper", model="openrouter/~openai/gpt-luna-latest", message="Summarize it."),
        node("slack", "automation-slack", label="Slack", operation="send_message_to_channel",
             channel="C1", text="hi"),
        node("loop", "iteration", label="Each"),
        node("log", "log", label="Log", message="done"),
        node("tool", "tool", label="Tool"),
        node("note", "stickyNote", content="Read me", color=8),
    ],
    "edges": [edge("hook", "agent")],
}


def _context(**kwargs):
    return EditContext("wf-1", OWNER, kwargs.pop("is_owner", True), **kwargs)


async def through_ops(graph, ops, *, name="Flow", settings=None, **context):
    return await apply_ops(copy.deepcopy(graph), parse_ops(ops), name=name, settings=settings or {},
                           context=_context(**context))


def _mcp_server():
    from mcp_server import NoClickMCPServer

    with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
        srv = NoClickMCPServer(MagicMock())
    srv._emit_builder_event = AsyncMock()
    # No pool: a credential is filed under the key the call names, as with no DB to read its type from.
    srv.get_pool = AsyncMock(return_value=None)
    return srv


async def through_mcp(graph, xml, *, name="Flow"):
    from mcp_server import _user_id_var

    srv = _mcp_server()
    data = copy.deepcopy(graph)
    saved = {}
    srv._load_workflow = AsyncMock(side_effect=lambda user_id, wid, meta_out=None: (
        meta_out.update(name=name) if meta_out is not None else None, (data, None))[1])

    async def save(user_id, workflow_id, workflow_data, expected_updated_at=None, name=None):
        saved.update(graph=copy.deepcopy(workflow_data), name=name)

    srv._save_workflow = save
    token = _user_id_var.set(OWNER)
    try:
        result = await srv._process_update_workflow(workflow_id="wf-1", updates_xml=xml, include_operations=False,
                                                    include_configs=False)
    finally:
        _user_id_var.reset(token)
    return result, saved


def steps(graph):
    """What each step is (its type and config), by id: layout left out."""
    return {n["id"]: {"type": n["type"], "config": node_config(n)} for n in graph_nodes(graph)}


def wiring(graph):
    return {(e.get("source"), e.get("target"), e.get("sourceHandle"), e.get("targetHandle"))
            for e in graph_edges(graph)}


async def assert_same(graph, xml, ops, **context):
    result, saved = await through_mcp(graph, xml)
    assert result["success"], result
    edited = await through_ops(graph, ops, **context)
    assert steps(edited.graph) == steps(saved["graph"])
    assert wiring(edited.graph) == wiring(saved["graph"])
    return edited, result


# ── each op against the MCP's XML write of the same change ─────────────────

@pytest.mark.asyncio
class TestParityWithTheMcpWrite:
    async def test_add_step(self):
        result, saved = await through_mcp(
            BASE, '<add_node type="automation-rss" name="feed" operation="parse_rss_atom_feed" label="News" '
                  'feed_url="https://example.com/rss" />')
        edited = await through_ops(BASE, [{"op": "add_step", "type": "automation-rss", "name": "News",
                                           "operation": "parse_rss_atom_feed",
                                           "settings": {"feed_url": "https://example.com/rss"}}])
        mcp_id, ops_id = result["alias_map"]["feed"], edited.results[0]["id"]
        assert ops_id.startswith("automation-rss-")
        assert steps(edited.graph)[ops_id] == steps(saved["graph"])[mcp_id]
        assert {k: v for k, v in steps(edited.graph).items() if k != ops_id} == \
            {k: v for k, v in steps(saved["graph"]).items() if k != mcp_id}

    async def test_add_step_with_an_id_the_caller_chose(self):
        edited = await through_ops(BASE, [{"op": "add_step", "type": "log", "id": "summary", "name": "Summary",
                                           "settings": {"message": "x"}},
                                          {"op": "connect", "from": "agent", "to": "summary"}])
        assert steps(edited.graph)["summary"]["config"] == {"label": "Summary", "message": "x"}
        assert ("agent", "summary", None, None) in wiring(edited.graph)

    async def test_update_step_settings(self):
        await assert_same(BASE, '<update_config id="slack" text="Hello there" channel="C2" />',
                          [{"op": "update_step", "id": "slack", "settings": {"text": "Hello there", "channel": "C2"}}])

    async def test_update_step_name_operation_and_enabled(self):
        await assert_same(
            BASE, '<update_config id="slack" label="Post it" operation="update_existing_message" />'
                  '<disable_node id="log" />',
            [{"op": "update_step", "id": "slack", "name": "Post it", "operation": "update_existing_message"},
             {"op": "update_step", "id": "log", "enabled": False}])

    async def test_enabling_a_step(self):
        graph = copy.deepcopy(BASE)
        graph["nodes"][4]["config"]["disabled"] = True
        await assert_same(graph, '<enable_node id="log" />', [{"op": "update_step", "id": "log", "enabled": True}])

    async def test_an_agent_moved_to_another_harness_leaves_nothing_of_the_old_one(self):
        graph = {"nodes": [node(NODE, "agent", **SCAFFOLD_AGENT)], "edges": []}
        edited, result = await assert_same(graph, f'<update_config id="{NODE}" model="claude-code" />',
                                           [{"op": "update_step", "id": NODE, "settings": {"model": "claude-code"}}])
        config = node_config(edited.graph["nodes"][0])
        assert config["label"] == "Claude Code" and "opencode_model" not in config
        assert config["credentialIds"] == {"agent_env": "cred-env"}
        assert edited.results[0]["harness_switch"]["unlinked_credentials"] == ["agent_opencode"]

    async def test_a_scaffold_named_workflow_follows_its_agent(self):
        graph = {"nodes": [node(NODE, "agent", **SCAFFOLD_AGENT)], "edges": []}
        edited = await through_ops(graph, [{"op": "update_step", "id": NODE, "settings": {"model": "claude-code"}}],
                                   name="OpenCode + Confluence and Monday.com")
        _, saved = await through_mcp(graph, f'<update_config id="{NODE}" model="claude-code" />',
                                     name="OpenCode + Confluence and Monday.com")
        assert edited.name == saved["name"] == "Claude Code + Confluence and Monday.com"

    async def test_patch_step(self):
        graph = copy.deepcopy(BASE)
        graph["nodes"][1]["config"]["system_prompt"] = "line one\nline two\nline three"
        patch_text = "@@ line one\n-line two\n+line 2"
        await assert_same(graph, f'<patch_config id="agent" field="system_prompt">{patch_text}</patch_config>',
                          [{"op": "patch_step", "id": "agent", "field": "system_prompt", "patch": patch_text}])

    async def test_remove_step_takes_its_edges(self):
        await assert_same(BASE, '<remove_node id="agent" />', [{"op": "remove_step", "id": "agent"}])

    async def test_connect_dataflow(self):
        await assert_same(BASE, '<add_edge from="agent" to="log" />',
                          [{"op": "connect", "from": "agent", "to": "log"}])

    async def test_connect_a_branch_of_a_step_with_several_outputs(self):
        await assert_same(BASE, '<add_edge from="loop" to="log" handle="done" />',
                          [{"op": "connect", "from": "loop", "to": "log", "handle": "done"}])

    async def test_connect_an_integration_as_an_agents_tools(self):
        edited, _ = await assert_same(BASE, '<add_edge from="slack" to="agent" type="tools" />',
                                      [{"op": "connect", "from": "slack", "to": "agent", "kind": "tools"}])
        assert edited.results[0]["kind"] == "tools"
        assert ("slack", "agent", "top", "bottom") in wiring(edited.graph)

    async def test_a_structural_tool_into_an_agent_is_always_tools(self):
        await assert_same(BASE, '<add_edge from="tool" to="agent" />',
                          [{"op": "connect", "from": "tool", "to": "agent"}])

    async def test_disconnect(self):
        await assert_same(BASE, '<remove_edge from="hook" to="agent" />',
                          [{"op": "disconnect", "from": "hook", "to": "agent"}])

    async def test_set_connection(self):
        await assert_same(BASE, '<set_credentials id="slack" slack_oauth="cred-1" />',
                          [{"op": "set_connection", "id": "slack", "connection": "cred-1"}],
                          credential_types={"cred-1": "slack_oauth"})

    async def test_mock_and_unmock(self):
        edited, _ = await assert_same(BASE, '<mock_node id="log" output=\'{"ok": true}\' />',
                                      [{"op": "mock_step", "id": "log", "output": {"ok": True}}])
        mocked = copy.deepcopy(edited.graph)
        await assert_same(mocked, '<unmock_node id="log" />', [{"op": "unmock_step", "id": "log"}])

    async def test_add_note(self):
        result, saved = await through_mcp(BASE, '<add_sticky_note name="n" near="agent" direction="below">'
                                                 'Why it waits</add_sticky_note>')
        edited = await through_ops(BASE, [{"op": "add_note", "content": "Why it waits", "near": ["agent"],
                                           "direction": "below"}])
        mcp_note = steps(saved["graph"])[result["alias_map"]["n"]]
        assert steps(edited.graph)[edited.results[0]["id"]] == mcp_note


def _builder(graph, xml):
    """The AI builder's write of ``xml`` on ``graph``: its graph mutations, then its field writes."""
    from coder.workflow.agentic.commands import execute_field_ops, execute_graph_mutations
    from coder.workflow.graph_state import GraphState
    from coder.workflow.workflow_xml import parse_xml

    state = GraphState.from_dict(copy.deepcopy(graph))
    ops = parse_xml(xml)
    results, _ = execute_graph_mutations([o for o in ops if o.tag != "field"], state)
    results += execute_field_ops([o for o in ops if o.tag == "field"], state)
    written = state.to_workflow_data()
    # The builder's persist writes each node's goal and display content (its label as loaded) beside its label:
    # its own bookkeeping, not the change.
    before = {n["id"]: n["config"] for n in graph["nodes"]}
    for n in written["nodes"]:
        for key in ("goal", "content"):
            if key not in before.get(n["id"], {}):
                n["config"].pop(key, None)
    return written, results


@pytest.mark.asyncio
class TestParityWithTheBuilderWrite:
    async def test_connect_tools_and_dataflow(self):
        written, _ = _builder(BASE, '<add_edge from="slack" to="agent" type="tools" /><add_edge from="agent" '
                                    'to="log" /><add_edge from="tool" to="agent" />')
        edited = await through_ops(BASE, [{"op": "connect", "from": "slack", "to": "agent", "kind": "tools"},
                                          {"op": "connect", "from": "agent", "to": "log"},
                                          {"op": "connect", "from": "tool", "to": "agent"}])
        assert wiring(edited.graph) == wiring(written)

    async def test_a_field_write_that_moves_an_agent_to_another_harness(self):
        graph = {"nodes": [node(NODE, "agent", **SCAFFOLD_AGENT)], "edges": []}
        written, _ = _builder(graph, f'<field node="{NODE}" name="model" value="claude-code" />')
        edited = await through_ops(graph, [{"op": "update_step", "id": NODE, "settings": {"model": "claude-code"}}])
        assert steps(edited.graph) == steps(written)


@pytest.mark.asyncio
class TestRefusalsMatchTheMcpWrite:
    async def _mcp_error(self, graph, xml):
        result, _ = await through_mcp(graph, xml)
        assert not result["success"]
        return result["errors"][0]["error"]

    async def _ops_error(self, graph, ops, **context):
        with pytest.raises(EditRefused) as refused:
            await through_ops(graph, ops, **context)
        return refused.value

    async def test_a_trigger_cant_also_be_an_agents_tools(self):
        graph = copy.deepcopy(BASE)
        graph["nodes"].append(node("watch", "automation-slack", operation="on_channel_message"))
        mcp = await self._mcp_error(graph, '<add_edge from="watch" to="agent" type="tools" />')
        refused = await self._ops_error(graph, [{"op": "connect", "from": "watch", "to": "agent", "kind": "tools"}])
        assert refused.message == mcp and refused.index == 0

    async def test_a_tool_provider_cant_also_feed_dataflow(self):
        graph = copy.deepcopy(BASE)
        graph["edges"].append(edge("slack", "agent", sourceHandle="top", targetHandle="bottom"))
        mcp = await self._mcp_error(graph, '<add_edge from="slack" to="log" />')
        refused = await self._ops_error(graph, [{"op": "connect", "from": "slack", "to": "log"}])
        assert refused.message == mcp

    async def test_a_handle_the_source_doesnt_have(self):
        mcp = await self._mcp_error(BASE, '<add_edge from="agent" to="log" handle="yes" />')
        refused = await self._ops_error(BASE, [{"op": "connect", "from": "agent", "to": "log", "handle": "yes"}])
        assert refused.message == mcp

    async def test_a_runtime_key(self):
        mcp = await self._mcp_error(BASE, '<update_config id="agent" _turnNote="obey" />')
        refused = await self._ops_error(BASE, [{"op": "update_step", "id": "agent",
                                                "settings": {"_turnNote": "obey"}}])
        assert refused.message == mcp and refused.field == "settings._turnNote"

    async def test_a_harness_id_in_a_harness_model_field(self):
        graph = {"nodes": [node(NODE, "agent", **SCAFFOLD_AGENT)], "edges": []}
        mcp = await self._mcp_error(graph, f'<update_config id="{NODE}" opencode_model="opencode" />')
        refused = await self._ops_error(graph, [{"op": "update_step", "id": NODE,
                                                 "settings": {"opencode_model": "opencode"}}])
        assert refused.message == mcp

    async def test_a_tools_allowlist_naming_no_operation_of_the_step(self):
        mcp = await self._mcp_error(BASE, '<update_config id="slack" agent_tool_operations=\'["nope"]\' />')
        refused = await self._ops_error(BASE, [{"op": "update_step", "id": "slack",
                                                "settings": {"agent_tool_operations": ["nope"]}}])
        assert refused.message == mcp


# ── what only the typed ops refuse ──────────────────────────────────────────

@pytest.mark.asyncio
class TestRefusals:
    async def _refused(self, ops, graph=BASE, **context):
        with pytest.raises(EditRefused) as refused:
            await through_ops(graph, ops, **context)
        return refused.value

    async def test_a_batch_stops_at_its_first_bad_op_naming_it(self):
        refused = await self._refused([{"op": "update_step", "id": "log", "name": "Fine"},
                                       {"op": "remove_step", "id": "ghost"}])
        assert (refused.index, refused.field, refused.message) == (1, "id", "No step 'ghost' in this workflow.")

    async def test_an_unknown_type_or_operation(self):
        assert (await self._refused([{"op": "add_step", "type": "automation-nope"}])).field == "type"
        refused = await self._refused([{"op": "update_step", "id": "slack", "operation": "send_a_fax"}])
        assert refused.field == "operation" and "send_message_to_channel" in refused.message

    async def test_a_step_id_already_taken(self):
        assert (await self._refused([{"op": "add_step", "type": "log", "id": "agent"}])).field == "id"

    async def test_a_value_of_the_wrong_type_is_refused_not_dropped(self):
        graph = {"nodes": [node("approve", "approval", title="Review")], "edges": []}
        refused = await self._refused([{"op": "update_step", "id": "approve",
                                        "settings": {"fields": [{"label": "no name key"}]}}], graph=graph)
        assert refused.field == "settings.fields"

    async def test_connections_and_the_operation_have_their_own_ops(self):
        assert "set_connection" in (await self._refused([{"op": "update_step", "id": "slack", "settings": {
            "credentialIds": {"slack_oauth": "x"}}}])).message
        assert (await self._refused([{"op": "update_step", "id": "slack",
                                      "settings": {"operation": "x"}}])).field == "settings.operation"

    @pytest.mark.parametrize("settings", [
        {"credential_id": "cred-x"}, {"credentialId": "cred-x"}, {"credential_ids": {"slack_oauth": "cred-x"}},
        {"credentials": {"id": "cred-x"}}, {"config": {"credentialIds": {"slack_oauth": "cred-x"}}},
    ])
    async def test_a_connection_rides_in_by_no_other_key(self, settings):
        """Each key the run engine reads a connection from (``extract_credential_ids``, and the nested ``config``
        it flattens) is set_connection's alone."""
        for op in ({"op": "update_step", "id": "slack", "settings": copy.deepcopy(settings)},
                   {"op": "add_step", "type": "automation-slack", "operation": "send_message_to_channel",
                    "settings": copy.deepcopy(settings)}):
            refused = await self._refused([op])
            assert refused.field.startswith("settings.") and "set_connection" in refused.message

    async def test_the_canvas_copy_of_settings_isnt_written(self):
        refused = await self._refused([{"op": "update_step", "id": "slack", "settings": {"config": {"text": "x"}}}])
        assert refused.field == "settings.config"

    async def test_a_field_of_the_steps_own_named_like_a_connection_is_its_own(self):
        """A provider's own id (Databricks' Git credential) is the step's field: written, and the step's connection
        map is there so the run engine never reads it as a NoClick connection."""
        graph = {"nodes": [node("db", "automation-databricks", operation="get_git_credential")], "edges": []}
        editor = await through_ops(graph, [{"op": "update_step", "id": "db", "settings": {"credential_id": "42"}}])
        config = node_config(editor.nodes[0])
        assert config["credential_id"] == "42" and config["credentialIds"] == {}
        from utils.credentials import extract_credential_ids
        assert extract_credential_ids(config) == {}

    async def test_a_patch_never_reaches_the_operation_or_the_connections(self):
        for field in ("operation", "credentialIds", "credential_id"):
            refused = await self._refused([{"op": "patch_step", "id": "slack", "field": field,
                                            "patch": "@@ send_message_to_channel\n-send_message_to_channel\n+x"}])
            assert refused.field == "field" and ("set_connection" in refused.message or "operation" in
                                                 refused.message)

    async def test_a_connection_the_caller_cant_use(self):
        refused = await self._refused([{"op": "set_connection", "id": "slack", "connection": "someone-elses"}])
        assert (refused.field, refused.message) == ("connection", "No connection 'someone-elses' that this account "
                                                                  "can use.")

    async def test_a_connection_of_a_type_the_step_doesnt_take(self):
        refused = await self._refused([{"op": "set_connection", "id": "slack", "connection": "cred-gh"}],
                                      credential_types={"cred-gh": "github_pat"})
        assert refused.field == "connection" and "slack_oauth" in refused.message

    async def test_settings_and_variables_are_the_owners(self):
        for op in ({"op": "update_workflow", "settings": {"x": 1}}, {"op": "define_variable", "name": "region"}):
            assert "owner" in (await self._refused([op], is_owner=False)).message

    async def test_noclicks_own_settings_are_never_written(self):
        assert (await self._refused([{"op": "update_workflow", "settings": {"system": "yours"}}])).field == \
            "settings.system"


def test_an_op_that_isnt_one():
    with pytest.raises(EditRefused) as refused:
        parse_ops([{"op": "connect", "from": "a", "to": "b"}, {"op": "teleport", "id": "x"}])
    assert refused.value.index == 1


def test_unknown_fields_are_refused():
    with pytest.raises(EditRefused) as refused:
        parse_ops([{"op": "remove_step", "id": "x", "cascade": True}])
    assert refused.value.index == 0 and "cascade" in refused.value.message


# ── the rest of the batch ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestBatches:
    async def test_ops_apply_in_order_and_later_ones_name_earlier_steps(self):
        edited = await through_ops(BASE, [
            {"op": "add_step", "type": "log", "id": "after", "settings": {"message": "x"}},
            {"op": "connect", "from": "agent", "to": "after"},
            {"op": "update_step", "id": "after", "name": "After"},
        ])
        assert node_config(next(n for n in edited.graph["nodes"] if n["id"] == "after"))["label"] == "After"

    async def test_new_steps_without_a_position_are_laid_out_and_others_stay(self):
        edited = await through_ops(BASE, [{"op": "add_step", "type": "log", "id": "a"},
                                          {"op": "add_step", "type": "log", "id": "b", "position": {"x": 5, "y": 6}}])
        placed = {n["id"]: n["position"] for n in edited.graph["nodes"]}
        assert placed["b"] == {"x": 5, "y": 6} and placed["a"] != {"x": 0, "y": 0}
        assert all(placed[n["id"]] == n["position"] for n in BASE["nodes"] if n["type"] != "stickyNote")

    async def test_each_touched_step_is_judged_on_the_final_graph(self):
        graph = {"nodes": [node("hook", "trigger-webhook"), node("agent", "agent", model="openrouter/x/y")],
                 "edges": []}
        alone = await through_ops(graph, [{"op": "update_step", "id": "agent", "name": "Agent"}])
        assert "Message is empty" in alone.steps["agent"]["validation_error"]
        fed = await through_ops(graph, [{"op": "update_step", "id": "agent", "name": "Agent"},
                                        {"op": "connect", "from": "hook", "to": "agent"}])
        assert "Message is empty" not in (fed.steps["agent"].get("validation_error") or "")

    async def test_a_trigger_wired_in_after_the_message_is_written_takes_its_reference_out(self):
        graph = {"nodes": [node("hook", "trigger-webhook"), node("agent", "agent", model="openrouter/x/y")],
                 "edges": []}
        edited, _ = await assert_same(
            graph, '<add_edge from="hook" to="agent" /><update_config id="agent" message="Answer {{ $(\'hook\').body }}" />',
            [{"op": "update_step", "id": "agent", "settings": {"message": "Answer {{ $('hook').body }}"}},
             {"op": "connect", "from": "hook", "to": "agent"}])
        assert edited.steps["agent"]["stripped_trigger_refs"]["node_ids"] == ["hook"]

    async def test_variables_and_test_runs_land_in_the_settings(self):
        from coder.workflow.workflow_ops import upsert_variable_definitions

        edited = await through_ops(BASE, [
            {"op": "define_variable", "name": "region", "value": "eu", "per_user": True},
            {"op": "add_test_run", "trigger": "hook", "name": "A refund", "body": "I want my money back"},
        ], settings={"variable_definitions": [{"name": "other", "value": "1"}]})
        assert edited.settings["variable_definitions"] == upsert_variable_definitions(
            [{"name": "other", "value": "1"}], [{"name": "region", "value": "eu", "per_user": True}])
        assert edited.results[1]["trigger_type"] == "trigger-webhook"
        assert list(edited.settings["rehearsal_authoring"]["runs"]) == ["trigger-webhook"]

    async def test_a_note_covers_a_stretch_or_sits_near_steps(self):
        edited = await through_ops(BASE, [{"op": "add_note", "content": "x", "after": "hook", "before": "agent"}])
        note = next(n for n in edited.graph["nodes"] if n["id"] == edited.results[0]["id"])
        assert (note["config"]["_anchor_after"], note["config"]["_anchor_before"]) == ("hook", "agent")


def test_what_a_write_changed_reads_as_one_line():
    after = copy.deepcopy(BASE)
    after["nodes"][1]["config"].update(label="Summarizer", message="Shorter.")
    after["nodes"][4]["config"]["disabled"] = True
    after["nodes"].append(node("new", "log", label="New"))
    after["nodes"] = [n for n in after["nodes"] if n["id"] != "tool"]
    after["edges"].append(edge("agent", "new"))
    for n in after["nodes"]:
        n["position"] = {"x": 100, "y": 100}
    changes = describe_changes(BASE, after)
    assert set(changes) == {"added 'New'", "removed 'Tool'", "renamed 'Helper' to 'Summarizer'",
                            "changed 'Summarizer' (message)", "turned off 'Log'", "connected 'Summarizer' to 'New'"}
    moved_only = copy.deepcopy(BASE)
    moved_only["nodes"][0]["position"] = {"x": 9, "y": 9}
    assert describe_changes(BASE, moved_only) == []
    assert summary(merge_changes(["added 'New'"], ["added 'New'", "turned off 'Log'"])) == \
        "added 'New'; turned off 'Log'"


def test_a_triggers_registration_mirrors_arent_a_change_but_an_actions_fields_are():
    graph = {"nodes": [node("cron", "trigger-cron", schedule={"frequency": "daily"}),
                       node("flare", "automation-cloudflare", webhook_url="https://a.example")], "edges": []}
    mirrored = copy.deepcopy(graph)
    mirrored["nodes"][0]["config"].update(next_run="2026-10-30T08:00:00Z", trigger_registered=True)
    assert describe_changes(graph, mirrored) == []
    repointed = copy.deepcopy(graph)
    repointed["nodes"][1]["config"]["webhook_url"] = "https://b.example"
    assert describe_changes(graph, repointed) == ["changed 'automation-cloudflare' (webhook_url)"]


def test_the_ops_are_documented_as_one_schema():
    from coder.workflow.graph_edits import _OPS

    schema = _OPS.json_schema()
    assert len(schema["items"]["oneOf"]) == 15
    assert schema["items"]["discriminator"]["propertyName"] == "op"
