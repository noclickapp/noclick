"""An AI write never puts a CLI harness's own model in an agent's Model.

Replays the 2026-10-16 builder edit. A gone-model refusal told the coordinator to
pick another OpenCode Model, such as 'opencode/big-pickle'; the coordinator asked
the builder to do it. The builder's snapshot hid `opencode_model` and writing it
drew a "not a valid field" warning, so it set the agent's `model` instead. That
moved the agent off the OpenCode harness onto the SDK gateway, where Zen refuses
its free models, and every turn after failed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import coder.workflow.option_registries.resolver as resolver
from coder.workflow.agentic.commands import execute_field_ops
from coder.workflow.graph_state import GraphState, NodeState
from coder.workflow.operation_catalog import validate_node_config
from coder.workflow.workflow_ops import misplaced_agent_model
from coder.workflow.workflow_xml import parse_xml
from nodes.agent.config import harness_model_lists
from nodes.agent.config.providers import HARNESS_MODEL_FIELDS

NODE = "agent_4p3m"

# models.dev's shape: Zen serves a model free when both costs are 0.
CATALOG = {"opencode": {"models": {
    "big-pickle": {"tool_call": True, "cost": {"input": 0, "output": 0}},
    "glm-5": {"tool_call": True, "cost": {"input": 1, "output": 3.2}},
}}}

# The saved agent as it was before the edit (no model_type stored).
PROD_AGENT = {
    "model": "opencode",
    "opencode_model": "opencode/deepseek-v4-flash-free",
    "message": "Respond like a hospital agent and reply directly via WhatsApp",
    "credentialIds": {"agent_opencode": "cred-1"},
}


_SYNC_CATALOG_READ = harness_model_lists._fetch_models_dev_sync


@pytest.fixture(autouse=True)
def _offline_catalogs(monkeypatch):
    monkeypatch.setattr(harness_model_lists, "_fetch_models_dev_sync", lambda: CATALOG)
    # No live model registry: a write keeps the value it was given.
    monkeypatch.setattr(resolver, "get_registry", lambda name: None)


def _state(**overrides):
    state = GraphState()
    state.nodes[NODE] = NodeState(
        id=NODE, type="agent", label="Hospital Agent", goal="Answer WhatsApp messages",
        operation="default", config={**PROD_AGENT, **overrides},
    )
    return state


def _problems(results):
    return [r for r in results if "WARNING" in r or "ERROR" in r or "REJECTED" in r]


class TestBuilderWrite:
    def test_the_prod_edit_is_refused_and_names_the_right_field(self):
        state = _state()
        results = execute_field_ops(
            parse_xml(f'<field name="model" node="{NODE}" value="opencode/big-pickle"/>'), state,
        )
        cfg = state.nodes[NODE].config
        assert cfg["model"] == "opencode"
        assert cfg["opencode_model"] == "opencode/deepseek-v4-flash-free"
        refusal = [r for r in results if r.startswith(f"REJECTED {NODE}.model")]
        assert refusal, results
        assert "OpenCode Model (opencode_model)" in refusal[0]
        assert "'opencode/big-pickle'" in refusal[0]
        assert "NOT saved" in refusal[0]

    @pytest.mark.parametrize("stored_type", [None, "opencode"])
    def test_the_right_edit_lands_without_warnings(self, stored_type):
        state = _state(**({"model_type": stored_type} if stored_type else {}))
        results = execute_field_ops(
            parse_xml(f'<field name="opencode_model" node="{NODE}" value="opencode/big-pickle"/>'), state,
        )
        cfg = state.nodes[NODE].config
        assert cfg["opencode_model"] == "opencode/big-pickle"
        assert cfg["model"] == "opencode"
        assert _problems(results) == []

    def test_a_refused_model_write_keeps_the_stored_discriminator(self):
        state = _state(model_type="opencode")
        execute_field_ops(
            parse_xml(f'<field name="model" node="{NODE}" value="opencode/big-pickle"/>'), state,
        )
        assert state.nodes[NODE].config["model_type"] == "opencode"

    def test_the_snapshot_shows_the_harness_model_field(self):
        assert 'opencode_model="opencode/deepseek-v4-flash-free"' in _state().to_xml()

    def test_a_paid_zen_model_still_sets_model(self):
        state = _state()
        results = execute_field_ops(
            parse_xml(f'<field name="model" node="{NODE}" value="opencode/glm-5"/>'), state,
        )
        assert state.nodes[NODE].config["model"] == "opencode/glm-5"
        assert _problems(results) == []


class TestSavedConfig:
    def test_validation_names_the_fix_for_a_saved_misplaced_model(self):
        err = validate_node_config("agent", "default", {**PROD_AGENT, "model": "opencode/big-pickle"})
        assert err is not None
        assert "OpenCode Model (opencode_model)" in err

    @pytest.mark.parametrize("stored_type", [None, "opencode"])
    def test_a_harness_agent_validates_as_its_own_kind(self, stored_type):
        cfg = {**PROD_AGENT, **({"model_type": stored_type} if stored_type else {})}
        assert validate_node_config("agent", "default", cfg) is None


class TestMisplacedAgentModel:
    @pytest.mark.parametrize("model", [
        "opencode",                                  # the harness itself
        "opencode/glm-5",                            # paid Zen: runs on the SDK gateway
        "openrouter/~openai/gpt-luna-latest",
        "anthropic/claude-sonnet-4-5",
        "opencode/unlisted",                         # unknown: judged at run time
        "{{ $vars.model }}",
    ])
    def test_models_that_can_run_as_model_pass(self, model):
        assert misplaced_agent_model({"model": model}) is None

    def test_an_unreadable_catalog_judges_nothing(self, monkeypatch):
        def unreadable():
            raise RuntimeError("models.dev could not be read")

        monkeypatch.setattr(harness_model_lists, "_fetch_models_dev_sync", unreadable)
        assert misplaced_agent_model({"model": "opencode/big-pickle"}) is None

    @pytest.mark.parametrize("harness,field", sorted(HARNESS_MODEL_FIELDS.items()))
    def test_a_harness_id_in_a_harness_model_field_is_refused(self, harness, field):
        err = misplaced_agent_model({field: harness})
        assert err is not None
        assert "Model (model)" in err and field in err

    @pytest.mark.parametrize("field", sorted(HARNESS_MODEL_FIELDS.values()))
    def test_a_model_id_in_a_harness_model_field_passes(self, field):
        assert misplaced_agent_model({field: "anthropic/claude-sonnet-4-5"}) is None


def _mcp_server(workflow_data):
    from mcp_server import NoClickMCPServer

    with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
        srv = NoClickMCPServer(MagicMock())
    srv._emit_builder_event = AsyncMock()
    srv._load_workflow = AsyncMock(return_value=(workflow_data, None))
    srv._save_workflow = AsyncMock(return_value=None)
    return srv


async def _mcp_update(workflow_data, xml):
    from mcp_server import _user_id_var

    token = _user_id_var.set("user-1")
    try:
        return await _mcp_server(workflow_data)._process_update_workflow(
            workflow_id="wf-1", updates_xml=xml, include_operations=False, include_configs=False,
        )
    finally:
        _user_id_var.reset(token)


def _workflow(**overrides):
    return {"nodes": [{
        "id": NODE, "type": "agent", "position": {"x": 0, "y": 0},
        "data": {"config": {**PROD_AGENT, **overrides}},
    }], "edges": []}


class TestMcpWrite:
    @pytest.mark.asyncio
    async def test_update_config_refuses_the_prod_edit(self):
        workflow = _workflow()
        result = await _mcp_update(workflow, f'<update_config id="{NODE}" model="opencode/big-pickle" />')
        assert workflow["nodes"][0]["data"]["config"]["model"] == "opencode"
        errors = [e["error"] for e in result["errors"] if e["action"] == "update_config"]
        assert errors and "OpenCode Model (opencode_model)" in errors[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stored_type", [None, "opencode"])
    async def test_update_config_lands_the_right_edit(self, stored_type):
        workflow = _workflow(**({"model_type": stored_type} if stored_type else {}))
        result = await _mcp_update(workflow, f'<update_config id="{NODE}" opencode_model="opencode/big-pickle" />')
        cfg = workflow["nodes"][0]["data"]["config"]
        assert cfg["opencode_model"] == "opencode/big-pickle" and cfg["model"] == "opencode"
        assert not result.get("errors")
        log = next(op for op in result["operations"] if op["action"] == "update_config")
        assert log["config_valid"] is True

    @pytest.mark.asyncio
    async def test_add_node_refuses_an_agent_on_a_misplaced_model(self):
        workflow = {"nodes": [], "edges": []}
        result = await _mcp_update(workflow, '<add_node type="agent" name="a" model="opencode/big-pickle" />')
        assert workflow["nodes"] == []
        errors = [e["error"] for e in result["errors"] if e["action"] == "add_node"]
        assert errors and "OpenCode Model (opencode_model)" in errors[0]


@pytest.fixture
def cold_catalog(monkeypatch):
    """models.dev not yet read in this process. Returns the sync reads made: a
    sync read inside a builder turn or an MCP call stalls the whole server's
    event loop for as long as models.dev takes."""
    import utils.opencode_zen as zen

    monkeypatch.setattr(harness_model_lists, "_fetch_models_dev_sync", _SYNC_CATALOG_READ)
    monkeypatch.setattr(zen, "_models_dev_cache", None)
    monkeypatch.setattr(zen, "_failed_at", {})
    sync_reads = []

    async def read(url, timeout):
        return CATALOG

    def read_sync(url):
        sync_reads.append(url)
        return CATALOG

    monkeypatch.setattr(zen, "_get_json", read)
    monkeypatch.setattr(zen, "_get_json_sync", read_sync)
    return sync_reads


async def _builder_turn(reply, **agent):
    """One builder turn whose brain answers ``reply``, on a graph holding the agent."""
    from coder.workflow.agentic.brain import BrainResponse
    from coder.workflow.agentic.builder import EXEC_RESULT_MARKER, AgenticBuilder
    from coder.workflow.agentic.config import AgenticBuilderConfig
    from coder.workflow.schema import BuilderInput

    class Brain:
        async def step(self, messages, *, turn, generation_id, workflow_id=None):
            yield reply
            yield BrainResponse(text=reply)

    builder = AgenticBuilder(config=AgenticBuilderConfig(max_turns=1), generation_id="catalog-read", brain=Brain())
    await builder.generate(BuilderInput(prompt="pick another OpenCode Model"))
    builder.graph_state.nodes[NODE] = _state(**agent).nodes[NODE]
    builder.messages.append({"role": "user", "content": f"{EXEC_RESULT_MARKER}\nAdded {NODE}"})
    async for _ in builder.run_one_turn():
        pass
    return builder


class TestCatalogReadOffTheEventLoop:
    @pytest.mark.asyncio
    async def test_a_builder_turn_reads_models_dev_asynchronously(self, cold_catalog):
        builder = await _builder_turn(f'<field name="model" node="{NODE}" value="opencode/big-pickle"/>')
        assert builder.graph_state.nodes[NODE].config["model"] == "opencode"
        assert any(f"REJECTED {NODE}.model" in (m.get("content") or "") for m in builder.messages)
        assert cold_catalog == []

    @pytest.mark.asyncio
    async def test_the_done_gate_reads_models_dev_asynchronously(self, cold_catalog):
        builder = await _builder_turn("<done/>", model="opencode/big-pickle")
        assert builder.last_turn_result().next_action == "continue"
        assert "OpenCode Model (opencode_model)" in builder.messages[-1]["content"]
        assert cold_catalog == []

    @pytest.mark.asyncio
    async def test_an_mcp_write_reads_models_dev_asynchronously(self, cold_catalog):
        workflow = _workflow()
        result = await _mcp_update(workflow, f'<update_config id="{NODE}" model="opencode/big-pickle" />')
        assert workflow["nodes"][0]["data"]["config"]["model"] == "opencode"
        assert any("OpenCode Model (opencode_model)" in e["error"] for e in result["errors"])
        assert cold_catalog == []

    @pytest.mark.asyncio
    async def test_validating_a_saved_zen_model_reads_models_dev_asynchronously(self, cold_catalog):
        workflow = _workflow(model="opencode/big-pickle")
        result = await _mcp_update(workflow, f'<update_config id="{NODE}" message="Reply in Spanish" />')
        log = next(op for op in result["operations"] if op["action"] == "update_config")
        assert log["config_valid"] is False
        assert cold_catalog == []

    @pytest.mark.asyncio
    async def test_validate_workflow_reads_models_dev_asynchronously(self, cold_catalog):
        from mcp_server import _user_id_var

        srv = _mcp_server({"nodes": [{
            "id": NODE, "type": "agent", "position": {"x": 0, "y": 0},
            "config": {**PROD_AGENT, "model": "opencode/big-pickle"},
        }], "edges": []})
        srv.get_pool = AsyncMock(return_value=None)
        srv._register_tools()
        validate_workflow = (await srv.mcp.get_tool("validate_workflow")).fn
        token = _user_id_var.set("user-1")
        try:
            report = await validate_workflow(workflow_id="wf-1")
        finally:
            _user_id_var.reset(token)
        assert "OpenCode Model (opencode_model)" in str(report)
        assert cold_catalog == []

    @pytest.mark.asyncio
    async def test_the_open_drafter_reads_models_dev_asynchronously(self, cold_catalog):
        from types import SimpleNamespace

        from coder.workflow.node_drafter import SinglePassNodeDrafter

        drafter = SinglePassNodeDrafter(config=None)
        node = SimpleNamespace(node_type="agent", operation=None, config={}, goal="answer", label="Agent")
        drafter.graph_state = SimpleNamespace(nodes={NODE: node})
        drafter.user_prompt = "answer WhatsApp messages"

        async def draft(prompt, hint):
            return {"operation": "default", "config": {"model": "opencode/big-pickle", "message": "Reply"}}

        drafter._call_model = draft
        [_ async for _ in drafter.draft_nodes({NODE})]
        assert "model" not in node.config
        assert cold_catalog == []


_CACHED_CATALOG_READ = harness_model_lists._models_dev_cached


class TestOpenCodeModelPriceReadBeforeKeyJudged:
    """Whether an OpenCode agent needs a key is judged from the price models.dev
    gives its OpenCode Model, so a turn or write naming one reads the catalog
    first: unread, a free model is taken to need a key, and the account's one
    OpenCode key is attached to it."""

    @pytest.fixture(autouse=True)
    def _prices_from_the_catalog_read(self, cold_catalog, monkeypatch):
        monkeypatch.setattr(harness_model_lists, "_models_dev_cached", _CACHED_CATALOG_READ)

    @pytest.mark.asyncio
    async def test_a_builder_turn_on_an_opencode_model(self, cold_catalog):
        from nodes.agent.config.providers import agent_credential_requirement

        builder = await _builder_turn(
            f'<field name="opencode_model" node="{NODE}" value="opencode/big-pickle"/>', credentialIds={},
        )
        config = builder.graph_state.nodes[NODE].config
        assert config["opencode_model"] == "opencode/big-pickle"
        assert agent_credential_requirement(config).required is False
        assert cold_catalog == []

    @pytest.mark.asyncio
    async def test_an_mcp_write_of_an_opencode_model(self, cold_catalog):
        from mcp_server import _user_id_var

        workflow = _workflow(credentialIds={})
        srv = _mcp_server(workflow)
        srv._auto_attach_agent_credential = AsyncMock(return_value={"id": "the-accounts-key"})
        token = _user_id_var.set("user-1")
        try:
            result = await srv._process_update_workflow(
                workflow_id="wf-1", updates_xml=f'<update_config id="{NODE}" opencode_model="opencode/big-pickle" />',
                include_operations=False, include_configs=False,
            )
        finally:
            _user_id_var.reset(token)
        assert not result.get("errors")
        srv._auto_attach_agent_credential.assert_not_awaited()
        assert workflow["nodes"][0]["data"]["config"]["credentialIds"] == {}
        assert cold_catalog == []
