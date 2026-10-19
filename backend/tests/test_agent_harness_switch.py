"""An AI write that moves an agent to another harness leaves nothing of the old one.

Replays the 2026-10-17 coordinator edit: asked to switch a scaffolded agent from
OpenCode to Claude Code, the builder set ``model: claude-code`` and stopped. The
node kept its "OpenCode" label (an "OpenCode" title over a claude-code chip),
``opencode_model`` and ``credentialIds.agent_opencode``, and the workflow kept
its scaffold name "OpenCode + Confluence and Monday.com".
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import coder.workflow.option_registries.resolver as resolver
from coder.workflow.agentic.commands import execute_field_ops
from coder.workflow.graph_state import GraphState, NodeState
from coder.workflow.workflow_ops import (
    AGENT_HARNESS_NAMES,
    preserve_existing_credentials,
    rename_workflow_for_harness_switches,
    switch_agent_harness,
)
from coder.workflow.workflow_xml import parse_xml
from nodes.agent.config._cli_models_loader import harness_default_model
from nodes.agent.config.providers import HARNESS_MODEL_FIELDS, WRAPPER_ID_BY_MODEL_TYPE

NODE = "agent-1"
WORKFLOW_NAME = "OpenCode + Confluence and Monday.com"

# The agent as the /agents scaffold saved it, with its key and env vars attached.
SCAFFOLD_AGENT = {
    "label": "OpenCode",
    "model": "opencode",
    "opencode_model": "opencode/big-pickle",
    "message": "Keep Confluence and Monday.com in step",
    "credentialIds": {"agent_opencode": "cred-opencode", "agent_env": "cred-env"},
}


@pytest.fixture(autouse=True)
def _no_live_registry(monkeypatch):
    # No live model registry: a write keeps the value it was given.
    monkeypatch.setattr(resolver, "get_registry", lambda name: None)


def _switched(old, **write):
    config = {**old, **write}
    return config, switch_agent_harness(
        "agent", old, config, label=config.get("label", ""), keep_label="label" in write,
    )


class TestSwitchAgentHarness:
    def test_the_prod_switch_leaves_nothing_of_opencode(self):
        config, switch = _switched(SCAFFOLD_AGENT, model="claude-code")
        assert switch is not None
        assert (switch.old, switch.new) == ("opencode", "claude_code")
        assert "opencode_model" not in config
        assert config["credentialIds"] == {"agent_env": "cred-env"}
        assert switch.dropped_fields == ("opencode_model",)
        assert switch.unlinked_credentials == ("agent_opencode",)
        assert switch.label == "Claude Code"

    def test_the_old_credential_map_is_not_mutated(self):
        old = {**SCAFFOLD_AGENT, "credentialIds": dict(SCAFFOLD_AGENT["credentialIds"])}
        config = {**old, "model": "claude-code"}
        switch_agent_harness("agent", old, config, label="OpenCode")
        assert old["credentialIds"] == SCAFFOLD_AGENT["credentialIds"]

    @pytest.mark.parametrize("old_type", sorted(WRAPPER_ID_BY_MODEL_TYPE))
    @pytest.mark.parametrize("new_type", sorted(WRAPPER_ID_BY_MODEL_TYPE))
    def test_every_harness_pair_drops_only_the_old_harness_fields(self, old_type, new_type):
        if old_type == new_type:
            return
        old_model, new_model = WRAPPER_ID_BY_MODEL_TYPE[old_type], WRAPPER_ID_BY_MODEL_TYPE[new_type]
        old = {"model": old_model, HARNESS_MODEL_FIELDS[old_model]: "some/model", "message": "hi"}
        config = {**old, "model": new_model, HARNESS_MODEL_FIELDS[new_model]: "other/model"}
        switch = switch_agent_harness("agent", old, config, label="Helper")
        assert switch is not None and (switch.old, switch.new) == (old_type, new_type)
        assert HARNESS_MODEL_FIELDS[old_model] not in config
        assert config[HARNESS_MODEL_FIELDS[new_model]] == "other/model"
        assert config["message"] == "hi"
        assert switch.label is None

    def test_openclaw_drops_its_timeout_too(self):
        old = {"model": "openclaw", "openclaw_model": "openrouter/x", "timeout_seconds": 300}
        config, switch = _switched(old, model="hermes")
        assert "timeout_seconds" not in config and "openclaw_model" not in config
        assert set(switch.dropped_fields) == {"openclaw_model", "timeout_seconds"}

    @pytest.mark.parametrize("label", ["OpenCode", "opencode", " OpenCode agent ", "OpenCode Agent"])
    def test_a_label_named_after_the_old_harness_follows_it(self, label):
        _, switch = _switched({**SCAFFOLD_AGENT, "label": label}, model="claude-code")
        assert switch.label == "Claude Code"

    @pytest.mark.parametrize("label", ["Support Bot", "OpenCode helper", "My OpenCode", ""])
    def test_a_label_the_user_wrote_stays(self, label):
        _, switch = _switched({**SCAFFOLD_AGENT, "label": label}, model="claude-code")
        assert switch.label is None

    def test_a_label_set_in_the_same_write_stays(self):
        config, switch = _switched(SCAFFOLD_AGENT, model="claude-code", label="OpenCode")
        assert switch.label is None

    @pytest.mark.parametrize("old_type", sorted(WRAPPER_ID_BY_MODEL_TYPE))
    def test_every_harness_is_named(self, old_type):
        assert AGENT_HARNESS_NAMES.get(old_type), f"{old_type} has no display name"

    def test_every_alias_of_a_harness_is_recognised(self):
        old = {"model": "hermes", "hermes_agent_model": "openrouter/x"}
        for alias in AGENT_HARNESS_NAMES["hermes_agent"]:
            _, switch = _switched({**old, "label": alias}, model="codex")
            assert switch.label == AGENT_HARNESS_NAMES["codex"][0]

    def test_moving_to_noclicks_own_runtime_names_it_like_a_new_agent(self):
        config, switch = _switched(SCAFFOLD_AGENT, model="openrouter/~openai/gpt-luna-latest")
        assert (switch.old, switch.new) == ("opencode", "llm")
        assert switch.label == "AI Agent"
        assert "opencode_model" not in config

    def test_a_key_both_harnesses_read_stays_linked(self):
        old = {
            "model": "opencode", "opencode_model": "anthropic/claude-sonnet-4-5",
            "credentialIds": {"agent_anthropic": "cred-a"},
        }
        config, switch = _switched(old, model="claude-code")
        assert config["credentialIds"] == {"agent_anthropic": "cred-a"}
        assert switch.unlinked_credentials == ()

    def test_a_refused_claude_plan_stays_linked_to_name_the_fix(self):
        old = {"model": "claude-code", "credentialIds": {"agent_claude_code_oauth": "plan"}}
        config, switch = _switched(old, model="anthropic/claude-sonnet-4-5")
        assert config["credentialIds"] == {"agent_claude_code_oauth": "plan"}
        assert switch.unlinked_credentials == ()

    def test_a_claude_plan_is_unlinked_from_a_harness_that_never_reads_it(self):
        old = {"model": "claude-code", "credentialIds": {"agent_claude_code_oauth": "plan"}}
        config, switch = _switched(old, model="codex")
        assert config["credentialIds"] == {}
        assert switch.unlinked_credentials == ("agent_claude_code_oauth",)

    def test_a_chatgpt_plan_does_not_follow_codex_to_the_sdk_agent(self):
        old = {"model": "codex", "credentialIds": {"agent_codex_oauth": "plan"}}
        config, _ = _switched(old, model="openai/gpt-5")
        assert config["credentialIds"] == {}

    @pytest.mark.parametrize("write", [
        {"model": "opencode"},                                 # the same harness again
        {"opencode_model": "opencode/glm-5"},                  # its own model, the same provider
        {"model": "{{ $vars.harness }}"},                      # can't be judged
        {"opencode_model": "{{ $vars.model }}"},               # nor can a templated sub-model
    ])
    def test_no_switch_changes_nothing(self, write):
        config, switch = _switched(SCAFFOLD_AGENT, **write)
        assert switch is None
        assert config["credentialIds"] == SCAFFOLD_AGENT["credentialIds"]
        assert config["label"] == "OpenCode"
        assert "opencode_model" in config

    def test_a_submodel_of_another_provider_unlinks_the_old_key_and_nothing_else(self):
        config, switch = _switched(SCAFFOLD_AGENT, opencode_model="anthropic/claude-sonnet-4-5")
        assert config["credentialIds"] == {"agent_env": "cred-env"}
        assert switch is not None and not switch.moved
        assert (switch.old, switch.new) == ("opencode", "opencode")
        assert switch.unlinked_credentials == ("agent_opencode",)
        assert switch.dropped_fields == () and switch.label is None
        assert config["label"] == "OpenCode" and config["opencode_model"] == "anthropic/claude-sonnet-4-5"
        assert "agent_opencode" in switch.summary(NODE) and "moved" not in switch.summary(NODE)

    def test_an_sdk_model_of_another_provider_unlinks_the_old_key(self):
        old = {"model": "anthropic/claude-sonnet-4.5", "credentialIds": {"agent_anthropic": "cred-a", "agent_env": "e"}}
        config, switch = _switched(old, model="openai/gpt-5")
        assert config["credentialIds"] == {"agent_env": "e"}
        assert switch.unlinked_credentials == ("agent_anthropic",) and not switch.moved

    def test_a_model_of_the_same_provider_keeps_its_key(self):
        old = {"model": "anthropic/claude-sonnet-4.5", "credentialIds": {"agent_anthropic": "cred-a"}}
        config, switch = _switched(old, model="anthropic/claude-opus-4.1")
        assert switch is None
        assert config["credentialIds"] == {"agent_anthropic": "cred-a"}

    def test_a_key_every_model_reads_stays_across_providers(self):
        old = {"model": "anthropic/claude-sonnet-4.5", "credentialIds": {"agent_api_key": "k"}}
        config, switch = _switched(old, model="openai/gpt-5")
        assert switch is None and config["credentialIds"] == {"agent_api_key": "k"}

    def test_media_model_switches_inside_the_sdk_harness_are_not_harness_moves(self):
        old = {"model": "openrouter/~openai/gpt-luna-latest", "label": "AI Agent"}
        _, switch = _switched(old, model="google/veo-3.1-fast")
        assert switch is None

    def test_other_node_types_are_untouched(self):
        old = {"model": "opencode", "opencode_model": "x"}
        config = {**old, "model": "claude-code"}
        assert switch_agent_harness("automation-slack", old, config, label="OpenCode") is None
        assert config["opencode_model"] == "x"


class TestWorkflowName:
    def test_the_scaffold_name_follows_the_agent(self):
        assert rename_workflow_for_harness_switches(
            WORKFLOW_NAME, [("opencode", "claude_code")],
        ) == "Claude Code + Confluence and Monday.com"

    @pytest.mark.parametrize("name", [
        "Confluence sync", "My OpenCode helper", "OpenCode agent (3 tools)", "OpenCode + ", "",
    ])
    def test_any_other_name_stays(self, name):
        assert rename_workflow_for_harness_switches(name, [("opencode", "claude_code")]) is None

    def test_switches_apply_in_order(self):
        assert rename_workflow_for_harness_switches(
            "Codex + Slack", [("codex", "opencode"), ("opencode", "hermes_agent")],
        ) == "Hermes + Slack"
        assert rename_workflow_for_harness_switches(
            "Codex + Slack", [("codex", "opencode"), ("opencode", "codex")],
        ) is None

    def test_a_name_naming_another_harness_stays(self):
        assert rename_workflow_for_harness_switches(
            "Codex + Slack", [("opencode", "claude_code")],
        ) is None


class TestPreserveExistingCredentials:
    """The builder's whole-blob persist carries stored credentialIds forward, so
    a slot the switch unlinked must not come back from the stored row."""

    def test_a_switch_unlinked_slot_is_not_carried_back(self):
        incoming = [{"id": NODE, "type": "agent", "config": {
            **SCAFFOLD_AGENT, "model": "claude-code", "credentialIds": {"agent_env": "cred-env"},
        }}]
        stored = [{"id": NODE, "type": "agent", "config": dict(SCAFFOLD_AGENT)}]
        preserve_existing_credentials(incoming, stored)
        assert incoming[0]["config"]["credentialIds"] == {"agent_env": "cred-env"}

    def test_a_slot_a_provider_change_unlinked_is_not_carried_back(self):
        incoming = [{"id": NODE, "type": "agent", "config": {
            **SCAFFOLD_AGENT, "opencode_model": "anthropic/claude-sonnet-4-5", "credentialIds": {"agent_env": "cred-env"},
        }}]
        stored = [{"id": NODE, "type": "agent", "config": dict(SCAFFOLD_AGENT)}]
        preserve_existing_credentials(incoming, stored)
        assert incoming[0]["config"]["credentialIds"] == {"agent_env": "cred-env"}

    def test_without_a_switch_stored_slots_still_survive(self):
        incoming = [{"id": NODE, "type": "agent", "config": {**SCAFFOLD_AGENT, "credentialIds": {}}}]
        stored = [{"id": NODE, "type": "agent", "config": dict(SCAFFOLD_AGENT)}]
        preserve_existing_credentials(incoming, stored)
        assert incoming[0]["config"]["credentialIds"] == SCAFFOLD_AGENT["credentialIds"]


def _builder_state(**overrides):
    config = {k: v for k, v in {**SCAFFOLD_AGENT, **overrides}.items() if k != "label"}
    state = GraphState()
    state.nodes[NODE] = NodeState(
        id=NODE, type="agent", label=overrides.get("label", SCAFFOLD_AGENT["label"]),
        goal="Sync the boards", operation="default", config=config,
    )
    return state


class TestBuilderWrite:
    def test_the_coordinator_edit_moves_the_whole_node(self):
        state = _builder_state()
        results = execute_field_ops(
            parse_xml(f'<field name="model" node="{NODE}" value="claude-code"/>'), state,
        )
        node = state.nodes[NODE]
        assert node.config["model"] == "claude-code"
        assert "opencode_model" not in node.config
        assert node.config["credentialIds"] == {"agent_env": "cred-env"}
        assert node.label == "Claude Code"
        assert state.harness_switches == [("opencode", "claude_code")]
        note = next(r for r in results if "OpenCode to Claude Code" in r)
        assert "opencode_model" in note and "agent_opencode" in note and "'Claude Code'" in note

    def test_a_label_written_in_the_same_batch_wins(self):
        state = _builder_state()
        execute_field_ops(parse_xml(
            f'<field name="model" node="{NODE}" value="claude-code"/>'
            f'<field name="label" node="{NODE}" value="Board Sync"/>'
        ), state)
        node = state.nodes[NODE]
        assert node.config["label"] == "Board Sync"
        assert node.label == "OpenCode"  # the config copy is what persists and renders

    def test_a_label_the_brain_wrote_earlier_is_renamed_where_it_lives(self):
        state = _builder_state()
        state.nodes[NODE].config["label"] = "OpenCode"
        execute_field_ops(parse_xml(f'<field name="model" node="{NODE}" value="claude-code"/>'), state)
        node = state.nodes[NODE]
        assert node.config["label"] == "Claude Code" and node.label == "Claude Code"

    def test_a_submodel_change_is_not_a_switch(self):
        state = _builder_state()
        execute_field_ops(
            parse_xml(f'<field name="opencode_model" node="{NODE}" value="opencode/glm-5"/>'), state,
        )
        assert state.harness_switches == []
        assert state.nodes[NODE].config["credentialIds"] == SCAFFOLD_AGENT["credentialIds"]

    def test_a_submodel_of_another_provider_drops_the_old_key_and_says_so(self):
        state = _builder_state()
        results = execute_field_ops(
            parse_xml(f'<field name="opencode_model" node="{NODE}" value="anthropic/claude-sonnet-4-5"/>'), state,
        )
        node = state.nodes[NODE]
        assert node.config["credentialIds"] == {"agent_env": "cred-env"}
        assert node.label == "OpenCode" and node.config["opencode_model"] == "anthropic/claude-sonnet-4-5"
        assert state.harness_switches == []  # the workflow keeps its name
        assert any("unlinked agent_opencode" in r for r in results)

    def test_an_sdk_model_of_another_provider_drops_the_old_key(self):
        state = GraphState()
        state.nodes[NODE] = NodeState(
            id=NODE, type="agent", label="Helper", goal="Help", operation="default",
            config={"model": "anthropic/claude-sonnet-4.5", "message": "hi",
                    "credentialIds": {"agent_anthropic": "cred-a", "agent_env": "cred-env"}},
        )
        execute_field_ops(parse_xml(f'<field name="model" node="{NODE}" value="openai/gpt-5"/>'), state)
        assert state.nodes[NODE].config["credentialIds"] == {"agent_env": "cred-env"}
        assert state.harness_switches == []


async def _builder_turn(reply, state):
    """One builder turn whose brain answers ``reply``; returns (builder, events)."""
    from coder.workflow.agentic.brain import BrainResponse
    from coder.workflow.agentic.builder import EXEC_RESULT_MARKER, AgenticBuilder
    from coder.workflow.agentic.config import AgenticBuilderConfig
    from coder.workflow.schema import BuilderInput

    class Brain:
        async def step(self, messages, *, turn, generation_id, workflow_id=None):
            yield reply
            yield BrainResponse(text=reply)

    builder = AgenticBuilder(config=AgenticBuilderConfig(max_turns=1), generation_id="switch", brain=Brain())
    await builder.generate(BuilderInput(prompt="switch the agent to Claude Code"))
    builder.graph_state.nodes[NODE] = state.nodes[NODE]
    builder.messages.append({"role": "user", "content": f"{EXEC_RESULT_MARKER}\nAdded {NODE}"})
    events = [e async for e in builder.run_one_turn()]
    return builder, events


class TestBuilderEvents:
    """An open canvas merges node_updated into its node (null deletes a key), so
    the event must name what the switch removed and the new label."""

    @pytest.mark.asyncio
    async def test_node_updated_carries_the_removals_and_the_label(self):
        _, events = await _builder_turn(
            f'<field name="model" node="{NODE}" value="claude-code"/>', _builder_state(),
        )
        update = [e.data for e in events if e.type == "node_updated" and e.data.get("nodeId") == NODE][-1]
        assert update["config"]["model"] == "claude-code"
        assert "opencode_model" in update["config"] and update["config"]["opencode_model"] is None
        # Read the way the canvas does (useCanvasWorkflowEdit): top level, else in config.
        assert update.get("credentialIds", update["config"].get("credentialIds")) == {"agent_env": "cred-env"}
        assert update["label"] == "Claude Code"

    @pytest.mark.asyncio
    async def test_the_canvas_bridge_keeps_them(self):
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        _, events = await _builder_turn(
            f'<field name="model" node="{NODE}" value="claude-code"/>', _builder_state(),
        )
        update = [e for e in events if e.type == "node_updated" and e.data.get("nodeId") == NODE][-1]
        bridged = WorkflowBuilderHandler._to_mcp_event(update)["data"]["config"]
        assert bridged["opencode_model"] is None
        assert bridged["label"] == "Claude Code"
        assert bridged["credentialIds"] == {"agent_env": "cred-env"}


def _persisting_handler(stored_workflow, name):
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    handler = WorkflowBuilderHandler(MagicMock())
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"workflow": stored_workflow, "name": name})
    pool = MagicMock(acquire=MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False),
    )))
    handler.get_pool = AsyncMock(return_value=pool)
    save = AsyncMock(return_value={"id": "wf"})
    return handler, save


class TestBuilderPersist:
    @pytest.mark.asyncio
    async def test_the_persist_renames_the_workflow_and_keeps_the_slot_unlinked(self, monkeypatch):
        stored = {"nodes": [{"id": NODE, "type": "agent", "config": dict(SCAFFOLD_AGENT)}], "edges": []}
        handler, save = _persisting_handler(stored, WORKFLOW_NAME)
        monkeypatch.setattr(
            "wss.handlers.workflow_builder_handler.WorkflowRepo",
            lambda _pool: MagicMock(update_workflow_dynamic=save),
        )
        state = _builder_state()
        execute_field_ops(parse_xml(f'<field name="model" node="{NODE}" value="claude-code"/>'), state)

        await handler._persist_builder_graph_for(str(uuid.uuid4()), SimpleNamespace(graph_state=state), "owner-1")

        kwargs = save.await_args.kwargs
        assert kwargs["name"] == "Claude Code + Confluence and Monday.com"
        written = kwargs["workflow_data"]["nodes"][0]["config"]
        assert written["credentialIds"] == {"agent_env": "cred-env"}
        assert written["label"] == "Claude Code"
        assert "opencode_model" not in written
        assert state.harness_switches == []

    @pytest.mark.asyncio
    async def test_a_workflow_without_a_switch_keeps_its_name(self, monkeypatch):
        stored = {"nodes": [{"id": NODE, "type": "agent", "config": dict(SCAFFOLD_AGENT)}], "edges": []}
        handler, save = _persisting_handler(stored, WORKFLOW_NAME)
        monkeypatch.setattr(
            "wss.handlers.workflow_builder_handler.WorkflowRepo",
            lambda _pool: MagicMock(update_workflow_dynamic=save),
        )
        await handler._persist_builder_graph_for(
            str(uuid.uuid4()), SimpleNamespace(graph_state=_builder_state()), "owner-1",
        )
        assert save.await_args.kwargs["name"] is None


def _mcp_server(workflow_data, name):
    from mcp_server import NoClickMCPServer

    with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
        srv = NoClickMCPServer(MagicMock())
    srv._emit_builder_event = AsyncMock()

    async def load(user_id, workflow_id, meta_out=None):
        if meta_out is not None:
            meta_out["name"] = name
        return workflow_data, None

    srv._load_workflow = load
    srv._save_workflow = AsyncMock(return_value=None)
    return srv


async def _mcp_update(srv, xml):
    from mcp_server import _user_id_var

    token = _user_id_var.set("user-1")
    try:
        return await srv._process_update_workflow(
            workflow_id="wf-1", updates_xml=xml, include_operations=False, include_configs=False,
        )
    finally:
        _user_id_var.reset(token)


def _mcp_workflow(**overrides):
    return {"nodes": [{
        "id": NODE, "type": "agent", "position": {"x": 0, "y": 0},
        "data": {"config": {**SCAFFOLD_AGENT, **overrides}},
    }], "edges": []}


class TestMcpWrite:
    @pytest.mark.asyncio
    async def test_update_config_moves_the_whole_node_and_the_workflow_name(self):
        workflow = _mcp_workflow()
        srv = _mcp_server(workflow, WORKFLOW_NAME)
        result = await _mcp_update(srv, f'<update_config id="{NODE}" model="claude-code" />')

        cfg = workflow["nodes"][0]["data"]["config"]
        assert cfg["model"] == "claude-code"
        assert "opencode_model" not in cfg
        assert cfg["credentialIds"] == {"agent_env": "cred-env"}
        assert cfg["label"] == "Claude Code"

        log = next(op for op in result["operations"] if op["action"] == "update_config")
        assert log["harness_switch"]["from"] == "opencode" and log["harness_switch"]["to"] == "claude_code"
        assert log["harness_switch"]["unlinked_credentials"] == ["agent_opencode"]

        assert srv._save_workflow.await_args.kwargs["name"] == "Claude Code + Confluence and Monday.com"
        assert result["workflow_renamed"] == {
            "from": WORKFLOW_NAME, "to": "Claude Code + Confluence and Monday.com",
        }

        emitted = [c.args[3] for c in srv._emit_builder_event.await_args_list if c.args[2] == "node_updated"]
        assert emitted[-1]["config"]["opencode_model"] is None
        assert emitted[-1]["config"]["label"] == "Claude Code"

    @pytest.mark.asyncio
    async def test_a_label_set_in_the_same_update_wins(self):
        workflow = _mcp_workflow()
        srv = _mcp_server(workflow, WORKFLOW_NAME)
        await _mcp_update(srv, f'<update_config id="{NODE}" model="claude-code" label="Board Sync" />')
        assert workflow["nodes"][0]["data"]["config"]["label"] == "Board Sync"

    @pytest.mark.asyncio
    async def test_an_update_without_a_switch_keeps_everything(self):
        workflow = _mcp_workflow()
        srv = _mcp_server(workflow, WORKFLOW_NAME)
        result = await _mcp_update(srv, f'<update_config id="{NODE}" message="Sync hourly" />')
        cfg = workflow["nodes"][0]["data"]["config"]
        assert cfg["opencode_model"] == "opencode/big-pickle"
        assert cfg["credentialIds"] == SCAFFOLD_AGENT["credentialIds"]
        assert cfg["label"] == "OpenCode"
        assert srv._save_workflow.await_args.kwargs.get("name") is None
        assert "workflow_renamed" not in result

    @pytest.mark.asyncio
    async def test_a_submodel_of_another_provider_unlinks_the_old_key_and_keeps_the_name(self):
        workflow = _mcp_workflow()
        srv = _mcp_server(workflow, WORKFLOW_NAME)
        result = await _mcp_update(srv, f'<update_config id="{NODE}" opencode_model="anthropic/claude-sonnet-4-5" />')
        cfg = workflow["nodes"][0]["data"]["config"]
        assert cfg["credentialIds"] == {"agent_env": "cred-env"}
        assert cfg["label"] == "OpenCode"
        log = next(op for op in result["operations"] if op["action"] == "update_config")
        assert log["harness_switch"]["from"] == log["harness_switch"]["to"] == "opencode"
        assert log["harness_switch"]["unlinked_credentials"] == ["agent_opencode"]
        assert srv._save_workflow.await_args.kwargs.get("name") is None
        assert "workflow_renamed" not in result
