"""Exercise MyCase's poll lifecycle against its published response schemas.

Schema files are pinned verbatim from MyCase's Stoplight project; record values
below are test data, not captured API deliveries or conformance witnesses.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import mycase_node as module
from nodes.core.poll_trigger import poll_scope
from nodes.tests.test_mycase_node_mock import node, transport

RESOURCES = ("client", "lead", "case", "task")
SCHEMAS = json.loads((Path(__file__).parent / "fixtures/mycase/poll_response_schemas.json").read_text())


def record(noun, identifier=123, updated="2022-03-17T21:00:00Z"):
    data = {"id": identifier, "updated_at": updated}
    if noun in {"client", "lead"}:
        data.update(first_name="John", last_name="Doe", email="john@example.com")
    else:
        data.update(name="Smith matter", description="Review the matter")
    assert set(data) <= set(SCHEMAS[noun]["schema"]["properties"])
    return data


def stateful(monkeypatch, instance):
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("noun", RESOURCES)
async def test_mycase_poll_baselines_emits_updates_and_new_records(monkeypatch, noun):
    rows = [record(noun)]
    config = {"operation": "on_new_or_updated_" + noun, "updated_after": "2022-03-17T21:00:00Z"}
    instance = node(config)
    state = stateful(monkeypatch, instance)
    def request(req):
        assert req.url.path == "/v1/" + module.POLL_RESOURCES[config["operation"]]
        assert dict(req.url.params) == {"page_size": "1000", "filter[updated_after]": "2022-03-17T21:00:00+00:00"}
        return httpx.Response(200, json=rows)
    transport(monkeypatch, request)
    result = await instance.execute({})
    assert result["data"] == []
    assert instance.trigger_produced_no_event(result)
    assert module.MyCaseNode.resolve_agent_event(result) is None
    rows[:] = [record(noun, updated="2022-03-18T21:00:00Z"), record(noun, identifier=456)]
    result = await instance.execute({})
    assert result["data"] == rows
    assert instance.trigger_emitted_event(result)
    event = module.MyCaseNode.resolve_agent_event(result)
    assert "123" in event["text"] and "456" in event["text"]
    assert "John Doe" in event["text"] if noun in {"client", "lead"} else "Smith matter" in event["text"]
    assert (await instance.execute({}))["data"] == []
    assert state["scope"] == poll_scope(module.MyCaseNode, config)
    assert poll_scope(module.MyCaseNode, {**config, "label": "Renamed"}) == state["scope"]
    assert poll_scope(module.MyCaseNode, {**config, "updated_after": "2022-03-18T21:00:00Z"}) != state["scope"]


@pytest.mark.asyncio
async def test_mycase_poll_follows_pages_before_dedup(monkeypatch):
    instance = node({"operation": "on_new_or_updated_case"})
    state = stateful(monkeypatch, instance)
    state["seen_ids"] = []
    def request(req):
        if "page_token" not in req.url.params:
            return httpx.Response(200, json=[record("case")], headers={"Link": '<https://external-integrations.mycase.com/v1/cases?page_token=next>; rel="next"'})
        assert req.url.params["page_token"] == "next"
        return httpx.Response(200, json=[record("case", identifier=456)])
    transport(monkeypatch, request)
    result = await instance.execute({})
    assert result["changed_count"] == 2
    assert len(state["seen_ids"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "shape", "missing_timestamp", "unsafe_link", "cycle"])
async def test_mycase_failed_poll_does_not_advance_state(monkeypatch, failure):
    instance = node({"operation": "on_new_or_updated_case"})
    state = stateful(monkeypatch, instance)
    state["seen_ids"] = []
    def request(req):
        if failure == "http":
            return httpx.Response(503, json={"message": "unavailable"})
        if failure == "shape":
            return httpx.Response(200, json={"data": []})
        if failure == "missing_timestamp":
            return httpx.Response(200, json=[{"id": 123}])
        url = "https://evil.example/v1/cases?page_token=next" if failure == "unsafe_link" else "https://external-integrations.mycase.com/v1/cases?page_token=next"
        return httpx.Response(200, json=[record("case")], headers={"Link": f'<{url}>; rel="next"'})
    transport(monkeypatch, request)
    assert (await instance.execute({}))["status"] == "error"
    assert state == {"seen_ids": []}
