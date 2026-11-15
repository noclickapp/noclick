"""What a chat turn says reaches the agent as written.

A turn's text (a chat message, a shared-link visitor's line, a platform or
coordinator message, an email reply) arrives as a config override on the
agent. ``{{ }}`` in it is text, never a reference resolved against the run's
node outputs, while the references the node's saved config carries still
resolve. Runtime keys (a delivered event, a harness's reply, an error report)
are data the same way.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nodes.agent_node import AgentNode
from utils.runtime_keys import LITERAL_KEYS, literal_config_keys
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler, apply_config_overrides

STORED = {"report": {"result": {"secret": "stored-value"}}, "form": {"name": "Ada"}}
TEXT = "What do {{ $('report').result.secret }} and {{report.result.secret}} mean?"


async def agent_turn_config(node, outputs=STORED):
    """The config the agent node is built with when ``node`` executes against ``outputs``."""
    seen = {}

    async def execute(self, inputs):
        seen.update(self.node_data["config"])
        return {"response": "ok"}

    with patch.object(AgentNode, "execute", execute):
        await WorkflowExecutionHandler(sio=AsyncMock())._execute_node(
            node, dict(outputs), sid="", user_id="u1", workflow_id="wf1",
            workflow_nodes=[node], workflow_edges=[],
        )
    return seen


def _agent(**config):
    return {"id": "agent", "type": "agent", "config": {"message": "Greet {{ $('form').name }}", **config}}


@pytest.mark.asyncio
async def test_a_turns_message_reaches_the_agent_as_written():
    nodes = [_agent()]
    apply_config_overrides(nodes, {"agent": {"message": TEXT, "conversation_key": "k1", "mockedOutput": None}})
    config = await agent_turn_config(nodes[0])
    assert config["message"] == TEXT
    assert config["conversation_key"] == "k1"


@pytest.mark.asyncio
async def test_a_turn_quoting_a_failed_expression_does_not_fail_the_run():
    """A turn that quotes an expression naming a node with no data in the run
    used to fail the agent with that expression's own error."""
    text = "The run failed: Expression {{ $('api_report').result.report }} failed"
    nodes = [_agent()]
    apply_config_overrides(nodes, {"agent": {"message": text}})
    assert (await agent_turn_config(nodes[0]))["message"] == text


@pytest.mark.asyncio
async def test_saved_references_still_resolve():
    saved = _agent(system_prompt="Help {{ $('form').name }}, also known as {{form.name}}")
    assert (await agent_turn_config(saved))["message"] == "Greet Ada"

    nodes = [_agent(system_prompt=saved["config"]["system_prompt"])]
    apply_config_overrides(nodes, {"agent": {"message": TEXT}})
    config = await agent_turn_config(nodes[0])
    assert config["system_prompt"] == "Help Ada, also known as Ada"
    assert config["message"] == TEXT


def test_only_a_chat_turns_keys_on_an_agent_are_marked():
    """Other overrides are config like the saved graph's: an agent's
    system_prompt or another node's field may carry a reference."""
    nodes = [_agent(), {"id": "http", "type": "automation-http", "config": {}}]
    apply_config_overrides(nodes, {
        "agent": {"message": TEXT, "model": "m", "system_prompt": "{{form.name}}", "mockedOutput": None},
        "http": {"message": "{{form.name}}"},
    })
    assert nodes[0]["config"][LITERAL_KEYS] == ["message", "model"]
    assert LITERAL_KEYS not in nodes[1]["config"]
    assert literal_config_keys(nodes[0]["config"]) == {"message", "model", LITERAL_KEYS}


@pytest.mark.asyncio
async def test_runtime_keys_are_data():
    """A delivered event or a harness's reply quoting ``{{ }}`` reaches the node as delivered."""
    delivered = {"response": TEXT}
    config = await agent_turn_config(_agent(_agent_turn_output=delivered))
    assert config["_agent_turn_output"] == delivered


@pytest.mark.asyncio
async def test_a_phone_turns_words_reach_the_agent_as_written():
    """A call's turn sets the agent's message itself (``execute_agent_turn``),
    through the same seam."""
    handler = WorkflowExecutionHandler(sio=None)
    executed = AsyncMock(return_value=(1, None, {}, None))
    with patch.object(handler, "_fetch_workflow", AsyncMock(return_value=([_agent()], [], None, {}, {}))), \
         patch.object(handler, "_preload_excluded_node_outputs", AsyncMock(return_value={})), \
         patch.object(handler, "_execute_nodes_concurrent", executed), \
         patch.object(handler, "get_pool", AsyncMock()), \
         patch("utils.execution_relay.create_execution_relay", MagicMock(return_value=MagicMock(close=AsyncMock()))):
        await handler.execute_agent_turn(
            workflow_id="wf1", agent_node_id="agent", user_id="u1", message=TEXT,
            conversation_key="+1555", execution_id="e1",
        )
    [agent] = executed.await_args.args[0]
    assert agent["config"]["message"] == TEXT
    assert literal_config_keys(agent["config"]) >= {"message", "conversation_key", "_memoryReadonly"}
