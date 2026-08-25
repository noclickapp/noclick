"""Public node-drafter registry, events, validation, and autofill tests."""

import asyncio
from types import SimpleNamespace

import pytest

import coder.workflow.node_drafter as nd
from coder.workflow.node_drafter import SinglePassNodeDrafter, create_node_drafter


@pytest.fixture(autouse=True)
def fresh_registry():
    """Restore whatever was registered, without naming it.

    Nothing re-registers lazily any more — registration happens once, at
    start-up — so a cleared registry stays cleared and every later test in the
    session silently gets a different drafter. Putting the previous factory back
    rather than importing the hosted one also keeps this fixture free of a
    private import, which would condemn the whole file at export instead of the
    one test that needs it."""
    previous = nd._factory
    nd.clear()
    yield
    nd.clear()
    if previous is not None:
        nd.register_node_drafter(previous)




def _drafter(model_reply, node_type="automation-slack", operation=None):
    d = SinglePassNodeDrafter(config=None)
    node = SimpleNamespace(type=node_type, operation=operation, config={},
                           goal="post a message", label="Slack")
    d.graph_state = SimpleNamespace(nodes={"n1": node})
    d.user_prompt = "notify the team"

    async def fake_call(prompt, hint):
        fake_call.prompts.append((prompt, hint))
        return model_reply
    fake_call.prompts = []
    d._call_model = fake_call
    return d, node, fake_call


async def _collect(agen):
    return [e async for e in agen]


@pytest.mark.asyncio
async def test_drafts_operation_and_config():
    d, node, _ = _drafter({"operation": "send_message_to_channel",
                           "config": {"channel": "#general", "text": "hi"}})
    events = await _collect(d.draft_nodes({"n1"}))
    types = [e.type for e in events]
    assert types == ["node_processing_start", "node_operation_selected", "node_updated"]
    assert node.operation == "send_message_to_channel"
    assert node.config["channel"] == "#general"


@pytest.mark.asyncio
async def test_hallucinated_operation_is_refused():
    """A made-up operation must not be written onto the node — the brain (or
    the user) resolves it instead of the canvas showing an invalid node."""
    d, node, _ = _drafter({"operation": "definitely_not_an_operation", "config": {"x": 1}})
    events = await _collect(d.draft_nodes({"n1"}))
    assert [e.type for e in events] == ["node_processing_start", "node_updated"]
    assert node.operation is None
    assert node.config == {}


@pytest.mark.asyncio
async def test_invalid_config_is_dropped_not_written():
    """Configs go through the same validator the canvas and hosted path use."""
    d, node, _ = _drafter({"operation": "send_message_to_channel",
                           "config": {"channel": {"not": "a string"}, "text": "hi"}})
    await _collect(d.draft_nodes({"n1"}))
    assert node.operation == "send_message_to_channel"      # selection still stands
    assert "channel" not in node.config          # rejected draft not persisted


@pytest.mark.asyncio
async def test_autofill_modes():
    # operation-only leaves config untouched
    d, node, _ = _drafter({"operation": "send_message_to_channel", "config": {"text": "x"}})
    await _collect(d.autofill_node("n1", mode="operation"))
    assert node.operation == "send_message_to_channel" and node.config == {}

    # single_field restricts to the requested field
    d, node, calls = _drafter(
        {"operation": "send_message_to_channel", "config": {"text": "hello", "channel": "#c"}},
        operation="send_message_to_channel",
    )
    await _collect(d.autofill_node("n1", mode="single_field", target_field="text"))
    assert "text" in calls.prompts[0][1]           # the model was told which field
    assert set(node.config) <= {"text", "operation"}


@pytest.mark.asyncio
async def test_nodes_without_operations_pass_through():
    d, node, _ = _drafter({}, node_type="sticky-note")
    events = await _collect(d.draft_nodes({"n1"}))
    assert [e.type for e in events] == ["node_processing_start", "node_updated"]
