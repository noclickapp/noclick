"""An agent's Message is required unless a trigger feeds the agent.

The field used to carry ``min_length=1``, enforced when the config model parsed
at node construction — but a trigger-wired agent's turn is the delivered
EVENT, composed in ``AgentNode.execute`` AFTER that parse, so every such agent
with a blank Message died on its first delivery (two live WhatsApp/Gmail
inboxes silently dropped mail that way, 2026-08-03). The rule now lives where
both halves are known: ``workflow_ops.agent_message_error`` for the build-time
surfaces (canvas, builder done-gate, MCP validate_workflow) and the composed
turn in ``execute`` for the run.
"""

from types import SimpleNamespace

import pytest

from coder.workflow.workflow_ops import (
    AGENT_MESSAGE_REQUIRED_ERROR,
    agent_message_error,
    agent_trigger_fed,
)
from nodes.agent_node import AgentNode
from nodes.core.base import ConfigValidationError

FIRED = {'_triggerPayload': {'a': 1}}


class TestParse:
    @pytest.mark.parametrize("model", ["openrouter/openai/gpt-4o-mini", "claude-code", "codex"])
    def test_an_empty_message_parses_on_every_harness(self, model):
        parsed = AgentNode.parse_config({"config": {"model": model, "message": ""}})
        assert parsed.config.message == ""


class TestBuildTimeRule:
    def test_message_required_unless_trigger_fed(self):
        assert agent_message_error({"message": ""}, trigger_fed=False) == AGENT_MESSAGE_REQUIRED_ERROR
        assert agent_message_error({"message": "   "}, trigger_fed=False) == AGENT_MESSAGE_REQUIRED_ERROR
        assert agent_message_error({}, trigger_fed=True) is None
        assert agent_message_error({"message": "Reply helpfully."}, trigger_fed=False) is None

    def test_trigger_fed_reads_the_stored_graph_shapes(self):
        nodes = [
            {"id": "cron", "type": "trigger-cron", "config": {}},
            {"id": "slack", "type": "automation-slack", "config": {"operation": "on_channel_message"}},
            {"id": "sheet", "type": "automation-google-sheets", "data": {"operation": "read_sheet_data"}},
            {"id": "agent", "type": "agent", "config": {}},
        ]
        assert agent_trigger_fed("agent", nodes, [{"source": "cron", "target": "agent"}])
        assert agent_trigger_fed("agent", nodes, [{"source": "slack", "target": "agent", "targetHandle": "left"}])
        # A trigger op on the tools handle is a provider, not a feed; an action op is neither.
        assert not agent_trigger_fed("agent", nodes, [{"source": "slack", "target": "agent", "targetHandle": "bottom"}])
        assert not agent_trigger_fed("agent", nodes, [{"source": "sheet", "target": "agent"}])
        assert not agent_trigger_fed("agent", nodes, [])

    def test_trigger_fed_reads_the_builder_graph_state_shape(self):
        nodes = [
            SimpleNamespace(id="cron", type="trigger-cron", operation="cron"),
            SimpleNamespace(id="agent", type="agent", operation=None),
        ]
        fed = [SimpleNamespace(source_id="cron", target_id="agent", target_handle=None)]
        tools = [SimpleNamespace(source_id="cron", target_id="agent", target_handle="bottom")]
        assert agent_trigger_fed("agent", nodes, fed)
        assert not agent_trigger_fed("agent", nodes, tools)


class _Reached(Exception):
    """Raised from the first post-check step to prove execute passed the rule."""


def _agent(message: str, monkeypatch, *, nodes=None, edges=None) -> AgentNode:
    data = {"config": {"model": "openrouter/openai/gpt-4o-mini", "message": message}}
    agent = AgentNode(node_id="agent_1", node_type="agent", node_data=data,
                      config=AgentNode.parse_config(data), sio=None, sid=None, workflow_id="wf_1")
    if nodes is not None:
        agent._workflow_nodes, agent._workflow_edges = nodes, edges

    async def _no_emit(*a, **k):
        return None

    async def _reached(*a, **k):
        raise _Reached()

    monkeypatch.setattr("nodes.agent_node.send_event", _no_emit)
    monkeypatch.setattr(agent, "_resolve_model_env_overrides", _reached)
    return agent


class TestRunTimeRule:
    @pytest.mark.asyncio
    async def test_nothing_to_send_is_a_config_error(self, monkeypatch):
        agent = _agent("", monkeypatch)
        with pytest.raises(ConfigValidationError, match="Message is empty"):
            await agent.execute({})

    @pytest.mark.asyncio
    async def test_a_delivered_event_is_the_turn(self, monkeypatch):
        nodes = [{"id": "wh1", "type": "trigger-webhook", "config": {**FIRED, "label": "Hook"}},
                 {"id": "agent_1", "type": "agent", "config": {}}]
        agent = _agent("", monkeypatch, nodes=nodes, edges=[{"source": "wh1", "target": "agent_1"}])
        with pytest.raises(_Reached):
            await agent.execute({"wh1": {"type": "webhook-trigger", "payload": {"a": 1}}})
        assert "--- Event from Hook ---" in agent.config.config.message

    @pytest.mark.asyncio
    async def test_a_manual_run_of_a_trigger_wired_agent_names_the_missing_event(self, monkeypatch):
        nodes = [{"id": "wh1", "type": "trigger-webhook", "config": {"label": "Hook"}},
                 {"id": "agent_1", "type": "agent", "config": {}}]
        agent = _agent("", monkeypatch, nodes=nodes, edges=[{"source": "wh1", "target": "agent_1"}])
        with pytest.raises(ConfigValidationError, match="No trigger event reached this run"):
            await agent.execute({"wh1": {"type": "webhook-trigger", "payload": {}}})
