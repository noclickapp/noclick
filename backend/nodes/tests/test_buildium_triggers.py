"""Exercise Buildium polling using the provider's published list examples.

State transitions verify that arming is quiet and later changes reach agents.
"""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from nodes import buildium_node as B
from nodes.core.poll_trigger import poll_scope
from nodes.tests.test_buildium_node_mock import AUTH, USER, world

FIXTURES = Path(__file__).parent / "fixtures" / "buildium"


def example(kind):
    return json.loads((FIXTURES / f"{kind}.json").read_text())["body"]


def node(operation, **fields):
    data = {"config": {"operation": operation, **fields}, "credentials": deepcopy(AUTH)}
    instance = B.BuildiumNode(node_type=B.NODE_TYPE, user_id=USER, node_id="poll",
                             node_data=data, config=B.BuildiumNode.parse_config(data))
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        changed, output = mutator(deepcopy(state))
        if changed is not None:
            state = changed
        return output

    instance._update_node_state = update
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,kind,path,order", [
    ("on_new_or_updated_task", "tasks", "/v1/tasks", "LastUpdatedDateTime desc,Id asc"),
    ("on_new_tenant", "tenants", "/v1/leases/tenants", "CreatedDateTime desc,Id asc"),
])
async def test_documented_lists_baseline_new_records_and_agent_turn(world, operation, kind, path, order):
    rows = example(kind)
    world.override = lambda _: httpx.Response(200, json=rows, headers={"X-Total-Count": str(len(rows))})
    instance = node(operation)
    first = await instance.execute({})
    assert first["records"] == [] and instance.trigger_produced_no_event(first)
    assert B.BuildiumNode.resolve_agent_event(first) is None
    # Simulate a subsequent record with the documented shape and timestamp.
    added = deepcopy(rows[0]); added["Id"] = 23; rows.append(added)
    output = await instance.execute({})
    assert [r["id"] for r in output["records"]] == ["23"]
    assert instance.trigger_emitted_event(output)
    event = B.BuildiumNode.resolve_agent_event(output)
    assert "Buildium" in event["text"] and "23" in event["text"] and "string" in event["text"]
    assert "2019-08-24T14:15:22Z" in event["text"]
    assert (await instance.execute({}))["records"] == []
    assert "Email" not in json.dumps(output) and "Description" not in json.dumps(output)
    assert world.calls[-1].url.path == path
    assert world.calls[-1].url.params["orderby"] == order
    assert all(r.method == "GET" for r in world.calls)


@pytest.mark.asyncio
async def test_task_revision_emits_once_and_nullable_last_update_uses_creation(world):
    rows = example("tasks"); rows[0]["LastUpdatedDateTime"] = None
    world.override = lambda _: httpx.Response(200, json=rows, headers={"X-Total-Count": "1"})
    instance = node("on_new_or_updated_task")
    await instance.execute({})
    rows[0]["LastUpdatedDateTime"] = "2022-05-10T15:12:46.2317653Z"
    rows[0]["TaskStatus"] = "Completed"
    output = await instance.execute({})
    assert len(output["records"]) == 1
    assert "Completed" in B.BuildiumNode.resolve_agent_event(output)["text"]
    assert (await instance.execute({}))["event_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,kind,filters", [
    ("on_new_or_updated_task", "tasks", {"entityid": "23", "entitytype": "Rental"}),
    ("on_new_tenant", "tenants", {"propertyids": "23"}),
])
async def test_property_filters_and_declared_scope(world, operation, kind, filters):
    rows = example(kind)
    world.override = lambda _: httpx.Response(200, json=rows, headers={"X-Total-Count": "1"})
    instance = node(operation, property_id="23")
    await instance.execute({})
    for key, value in filters.items():
        assert world.calls[-1].url.params[key] == value
    base = {"operation": operation, "property_id": "23"}
    assert poll_scope(B.BuildiumNode, base) == poll_scope(B.BuildiumNode, {**base, "goal": "New label", "unknown": "ignored"})
    assert poll_scope(B.BuildiumNode, base) != poll_scope(B.BuildiumNode, {**base, "property_id": "24"})


@pytest.mark.asyncio
async def test_paging_finishes_before_state_changes_and_rejects_truncation(world):
    row = example("tasks")[0]
    def respond(request):
        offset = int(request.url.params["offset"])
        rows = [{**deepcopy(row), "Id": i + 1} for i in range(offset, min(offset + 1000, 1001))]
        return httpx.Response(200, json=rows, headers={"X-Total-Count": "1001"})
    world.override = respond
    instance = node("on_new_or_updated_task")
    assert (await instance.execute({}))["event_count"] == 0
    assert [r.url.params["offset"] for r in world.calls] == ["0", "1000"]
    world.override = lambda _: httpx.Response(200, json=[row], headers={"X-Total-Count": "5001"})
    with pytest.raises(ValueError, match="5,000"):
        await instance.execute({})
    world.override = lambda _: httpx.Response(200, json=[row, row], headers={"X-Total-Count": "2"})
    with pytest.raises(RuntimeError, match="duplicate"):
        await instance.execute({})


@pytest.mark.asyncio
async def test_invalid_timestamp_never_records_a_baseline(world):
    rows = example("tasks"); rows[0].pop("CreatedDateTime"); rows[0]["LastUpdatedDateTime"] = None
    world.override = lambda _: httpx.Response(200, json=rows, headers={"X-Total-Count": "1"})
    instance = node("on_new_or_updated_task")
    with pytest.raises(RuntimeError, match="timestamp"):
        await instance.execute({})


def test_schedule_family_and_trigger_metadata():
    for op in B.TRIGGERS:
        parsed = B.BuildiumNode.parse_config({"config": {"operation": op}}).config
        assert isinstance(parsed, B.PollTriggerConfigBase)
        schema = type(parsed).model_json_schema()
        assert schema["x-requires-webhook"] is True
        assert schema["properties"]["operation"]["x-is-trigger"] is True
        assert parsed.schedule.interval == 5
        assert B.BuildiumNode.resolve_trigger_payload({"tick": True}, {"operation": op}) is None
