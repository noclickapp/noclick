"""Exercise Hive polling against its published open ConnectionResponse shape.

The contract leaves resource properties open; poll identity must preserve them
without depending on an undocumented ID or timestamp property.
"""
import copy

import pytest

from nodes import hive_node as hive
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory
from nodes.tests.test_hive_node_mock import AUTH, transport  # noqa: F401

OPERATIONS = ["on_new_or_updated_action", "on_new_or_updated_project"]


def make_node(operation, **extra):
    node = NodeFactory.create_node(node_id="hive-poll", node_type="automation-hive",
        node_data={"config": {"operation": operation, "workspace_id": "w1", **extra}, "credentials": AUTH})
    state = {}

    async def update(mutator, **kwargs):
        changed, result = mutator(copy.deepcopy(state))
        if changed is not None:
            state.clear()
            state.update(changed)
        return result

    node._update_node_state = update
    return node, state


def page(*items, cursor=None):
    # edges/node/pageInfo and these pagination fields are the published schema:
    # https://developers.hive.com/reference/get_workspaces_workspaceid_actions-1
    return {"edges": [{"node": item} for item in items],
            "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_baseline_creation_edit_and_unchanged_poll(transport, operation):
    requests, replies = transport
    node, state = make_node(operation)
    # The provider allows arbitrary resource fields. Use an opaque field rather
    # than teaching the trigger a guessed resource-specific payload contract.
    original, changed, created = {"opaque": "one"}, {"opaque": "two"}, {"opaque": "three"}
    for items, expected in [([original], []), ([original], []), ([changed], [changed]),
                            ([changed, created], [created]), ([changed, created], [])]:
        replies.append((200, page(*items)))
        output = await node.execute({})
        assert output["status"] == "success"
        assert output["items"] == expected
        assert output["new_or_updated_count"] == len(expected)
        assert node.should_propagate_output(output, {"operation": operation}) == bool(expected)
        event = node.resolve_agent_event(output)
        if expected:
            assert "workspace w1" in event["text"] and expected[0]["opaque"] in event["text"]
        else:
            assert event is None
    assert state["seen_ids"]
    assert all(dict(r.url.params) == {"first": "200", "sortBy": "modifiedAt desc"} for r in requests)
    resource = "actions" if operation.endswith("action") else "projects"
    assert all(r.url.path == f"/api/v2/workspaces/w1/{resource}" for r in requests)


@pytest.mark.asyncio
async def test_cursor_pages_and_project_scope(transport):
    requests, replies = transport
    node, state = make_node(OPERATIONS[0], project_id="p1")
    replies.extend([(200, page({}, cursor="opaque+/=")), (200, page({"opaque": "second"}))])
    assert (await node.execute({}))["new_or_updated_count"] == 0
    assert len(state["seen_ids"]) == 2
    assert requests[0].url.params["projectId"] == "p1"
    assert requests[1].url.params["after"] == "opaque+/="


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [(403, {"message": "Forbidden"}), (200, {"edges": [None], "pageInfo": {}}),
                                  (200, {"edges": [], "pageInfo": {"hasNextPage": True}})])
async def test_failed_poll_keeps_baseline(transport, reply):
    _, replies = transport
    node, state = make_node(OPERATIONS[0])
    replies.append(reply)
    assert (await node.execute({}))["status"] == "error"
    assert state == {}


@pytest.mark.asyncio
async def test_repeated_cursor_and_oversized_scope_fail_without_state_write(transport):
    _, replies = transport
    node, state = make_node(OPERATIONS[0])
    replies.extend([(200, page({}, cursor="repeated"))] * 2)
    assert (await node.execute({}))["status"] == "error"
    assert state == {}
    replies.extend((200, page({}, cursor=str(i))) for i in range(10))
    output = await node.execute({})
    assert "scope exceeds" in output["error"]
    assert state == {}


def test_poll_scope_uses_only_declared_fields():
    config = {"operation": OPERATIONS[0], "workspace_id": "w1", "project_id": "p1"}
    scope = poll_scope(hive.HiveNode, config)
    assert scope
    assert scope == poll_scope(hive.HiveNode, {**config, "schedule": {"frequency": "minutes", "interval": 10}})
    assert scope != poll_scope(hive.HiveNode, {**config, "project_id": "p2"})
    assert scope != poll_scope(hive.HiveNode, {**config, "workspace_id": "w2"})
