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




def _drafter(*model_replies, node_type="automation-slack", operation=None):
    """Each model call answers the next reply; the last one repeats."""
    d = SinglePassNodeDrafter(config=None)
    node = SimpleNamespace(type=node_type, operation=operation, config={},
                           goal="post a message", label="Slack")
    d.graph_state = SimpleNamespace(nodes={"n1": node})
    d.user_prompt = "notify the team"

    async def fake_call(prompt, hint, correction=None):
        fake_call.prompts.append((prompt, hint))
        fake_call.corrections.append(correction)
        return dict(model_replies[min(len(fake_call.prompts), len(model_replies)) - 1])
    fake_call.prompts = []
    fake_call.corrections = []
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


_DAYS = {"operation": "default", "config": {"schedules": [{"frequency": "days", "hour": 8, "minute": 0}]}}
_DAY = {"operation": "default", "config": {"schedules": [{"frequency": "day", "hour": 8, "minute": 0}]}}


@pytest.mark.asyncio
async def test_drafter_sees_the_schedule_fields_it_fills():
    d, _, calls = _drafter(_DAY, node_type="trigger-cron")
    await _collect(d.draft_nodes({"n1"}))
    assert 'name="frequency" type="enum" values="seconds|minutes|hours|day|week|weeks|month"' in calls.prompts[0][0]


@pytest.mark.asyncio
async def test_rejected_draft_gets_one_corrective_try():
    """"Every morning" drafted as "days": the validator's words go back once, and the fix is written."""
    d, node, calls = _drafter(_DAYS, _DAY, node_type="trigger-cron")
    await _collect(d.draft_nodes({"n1"}))
    assert len(calls.prompts) == 2
    rejected, error = calls.corrections[1]
    assert rejected == _DAYS and "'day'" in error and "frequency" in error
    assert node.config["schedules"] == _DAY["config"]["schedules"]


@pytest.mark.asyncio
async def test_draft_still_invalid_is_kept_for_the_builders_checks():
    """Dropped, the trigger kept its hourly default and nothing said so: kept, the
    validator the builder's done check runs names what is wrong."""
    from coder.workflow.operation_catalog import validate_node_config

    d, node, calls = _drafter(_DAYS, node_type="trigger-cron")
    await _collect(d.draft_nodes({"n1"}))
    assert len(calls.prompts) == 2                       # one corrective try, no more
    assert node.config["schedules"] == _DAYS["config"]["schedules"]
    assert "Input should be 'seconds', 'minutes', 'hours', 'day'" in validate_node_config(
        "trigger-cron", "default", node.config)


@pytest.mark.asyncio
async def test_a_lone_schedule_object_is_put_in_its_list():
    d, node, calls = _drafter(
        {"operation": "default", "config": {"schedules": {"frequency": "day", "hour": 8, "minute": 0}}},
        node_type="trigger-cron",
    )
    await _collect(d.draft_nodes({"n1"}))
    assert len(calls.prompts) == 1
    assert node.config["schedules"] == [{"frequency": "day", "hour": 8, "minute": 0}]


@pytest.mark.asyncio
async def test_wrong_typed_values_are_never_kept():
    d, node, calls = _drafter(
        {"operation": "default", "config": {"schedules": "every day at 8", "timezone": "Europe/London"}},
        node_type="trigger-cron",
    )
    await _collect(d.draft_nodes({"n1"}))
    assert len(calls.prompts) == 2
    assert "schedules" not in node.config and node.config["timezone"] == "Europe/London"


@pytest.mark.asyncio
async def test_invalid_autofill_is_dropped_not_written():
    """An on-demand autofill leaves the node as it was rather than writing an invalid value."""
    d, node, calls = _drafter({"operation": "send_message_to_channel",
                               "config": {"channel": {"not": "a string"}, "text": "hi"}},
                              operation="send_message_to_channel")
    await _collect(d.autofill_node("n1", mode="fields"))
    assert len(calls.prompts) == 1
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
