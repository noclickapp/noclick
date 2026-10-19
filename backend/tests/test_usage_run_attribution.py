"""What a charge is for: the node and run it was recorded in, and the chat with
NoClick (billing/usage_tracker.py `running`).

These pin: a node's charges carry its node and its run, whatever the node calls
(the executor wraps every node in it); the run's ids yield to an event's own,
as the running workflow does, so a writer that names its node keeps it; they
end with the block, so the next node's charges aren't the last one's; and work
replayed later from a taken attribution (a job's charge on a later poll) puts
them back where they yield."""

import asyncio

import pytest

from billing.usage_tracker import (
    CURRENT_WORKFLOW_ID,
    attributed,
    running,
    split_running,
    usage_attribution,
)
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler, _charged_as_node

pytestmark = pytest.mark.asyncio


async def test_a_nodes_charges_carry_its_node_and_its_run():
    # The executor runs every node through it.
    assert WorkflowExecutionHandler._execute_node.__wrapped__

    @_charged_as_node
    async def execute(self, node, node_outputs, sid, user_id, workflow_id, conversation_id=None,
                      workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
        await asyncio.sleep(0)
        # A charge spawned inside the node keeps what it was spawned with.
        return await asyncio.create_task(asyncio.to_thread(usage_attribution))

    assert await execute(None, {"id": "agent-1"}, {}, "sid", "user", "wf-1", execution_id="run-1") == {
        "node_id": "agent-1", "execution_id": "run-1"}
    # Positional too, as the strategies call it.
    assert (await execute(None, {"id": "tool-2"}, {}, "sid", "user", "wf-1", None, None, None, None, "run-2"))[
        "execution_id"] == "run-2"
    assert usage_attribution() == {}  # gone once the node is done


async def test_the_run_yields_to_what_a_charge_names_itself_and_ends_with_its_block():
    CURRENT_WORKFLOW_ID.set("wf-1")
    with running(node_id="agent-1", execution_id="run-1"):
        attribution = usage_attribution()
        assert attribution == {"node_id": "agent-1", "execution_id": "run-1", "workflow_id": "wf-1"}
        # The tracker merges the event's own keys over these (cloud/billing/usage_tracker.py _stamp_attribution).
        assert {**attribution, **{"node_id": "send-email"}}["node_id"] == "send-email"
        with running(node_id="tool-2"):
            assert usage_attribution()["node_id"] == "tool-2"
        assert usage_attribution()["node_id"] == "agent-1"
    assert usage_attribution() == {"workflow_id": "wf-1"}


async def test_async_with_marks_a_turn():
    async def turn():
        async with running(surface="coordinator"):
            return usage_attribution()

    assert await turn() == {"surface": "coordinator"}
    assert usage_attribution() == {}


async def test_a_replayed_attribution_puts_the_run_back_where_it_yields():
    with running(node_id="agent-1", execution_id="run-1"):
        taken = usage_attribution()
    assert split_running({**taken, "platform_api": {"key_id": "k"}}) == (
        {"platform_api": {"key_id": "k"}}, {"node_id": "agent-1", "execution_id": "run-1"})
    with attributed({**taken, "platform_api": {"key_id": "k"}}):
        again = usage_attribution()
    assert again == {"platform_api": {"key_id": "k"}, "node_id": "agent-1", "execution_id": "run-1"}
    assert usage_attribution() == {}
