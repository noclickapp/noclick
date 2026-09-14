"""Empty push triggers stop their branch in the real concurrent executor.

Node runs replace provider/agent I/O; graph scheduling, _execute_node and the
WhatsApp no-event predicate remain real. Independent branches still execute.
"""
from unittest.mock import AsyncMock
import pytest
from nodes.whatsapp_node import (
    WhatsAppNode,
    WhatsAppNodeConfig,
    WhatsAppReceiveMessageConfig,
)
from nodes.agent_node import AgentNode
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler


@pytest.mark.parametrize("mode", ["empty", "incoming", "rehearsal"])
async def test_no_event_never_spends_agent_turn_and_preserves_independent_branch(
    monkeypatch, mode
):
    handler = WorkflowExecutionHandler(AsyncMock())
    monkeypatch.setattr(handler, "_resolve_credentials", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "wss.handlers.workflow_execution_handler.track_node_schema", AsyncMock()
    )
    trigger = WhatsAppNode(
        node_id="in",
        node_type="automation-whatsapp",
        node_data={},
        config=WhatsAppNodeConfig(config=WhatsAppReceiveMessageConfig()),
        sio=None,
        sid=None,
        workflow_id="wf",
    )
    event = {"message": "Normal site update", "from": "monitored-group@g.us"}
    trigger.run = AsyncMock(
        return_value={"status": "no_event", "message": "Waiting for incoming message"}
        if mode == "empty"
        else event
    )
    agent = AgentNode(
        node_id="brain",
        node_type="agent",
        node_data={},
        config=None,
        sio=None,
        sid=None,
        workflow_id="wf",
    )
    agent.run = AsyncMock(return_value={"status": "processed"})
    other = AgentNode(
        node_id="other",
        node_type="agent",
        node_data={},
        config=None,
        sio=None,
        sid=None,
        workflow_id="wf",
    )
    other.run = AsyncMock(return_value={"status": "independent"})
    instances = {"in": trigger, "brain": agent, "other": other}
    monkeypatch.setattr(
        "wss.handlers.workflow_execution_handler.NodeFactory.create_node",
        lambda nid, *args, **kwargs: instances[nid],
    )
    nodes = [
        {
            "id": "in",
            "type": "automation-whatsapp",
            "config": {
                "operation": "receive_message",
                **({"mockedOutput": event} if mode == "rehearsal" else {}),
            },
        },
        {"id": "brain", "type": "agent", "config": {}},
        {"id": "other", "type": "agent", "config": {}},
    ]
    _, error, outputs = await handler._execute_nodes_concurrent(
        nodes, [{"source": "in", "target": "brain"}], "sid", "user", "wf"
    )
    assert error is None
    assert other.run.await_count == 1
    assert agent.run.await_count == (0 if mode == "empty" else 1)
    assert "_halt_downstream" not in outputs["in"]
