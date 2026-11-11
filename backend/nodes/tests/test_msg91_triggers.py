"""MSG91 poll triggers replay the provider's documented email and Hello responses.

These regressions exercise baselining, delivery changes, scope changes and agent turns.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nodes.core.poll_trigger import poll_scope
from nodes.tests.test_msg91_node_mock import make_node, transport
from nodes import msg91_node as native

FIXTURES = json.loads((Path(__file__).parent / "fixtures/msg91/trigger_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def state_store(monkeypatch):
    state = {}
    async def update(self, mutator, **kwargs):
        updated, result = mutator(copy.deepcopy(state))
        if updated is not None:
            state.clear()
            state.update(updated)
        return result
    monkeypatch.setattr(native.Msg91Node, "_update_node_state", update)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route,collection,output,config", [
    ("on_email_delivery_update", "GET /api/v5/report/logs/mail", "data", "emails", {}),
    ("on_new_or_updated_ticket", "GET /api/v5/hello/v2/mail-channel/", "chat_channels", "tickets", {"inbox_id": "1234", "ticket_state": "close"}),
])
async def test_msg91_polls_baseline_deduplicate_and_detect_documented_updates(monkeypatch, operation, route, collection, output, config):
    state = state_store(monkeypatch)
    body = copy.deepcopy(FIXTURES[route]["body"])
    requests = transport(monkeypatch, body)
    node = make_node({"operation": operation, **config})
    additional_email = None
    if output == "emails":
        additional_email = body[collection].pop()
        body["metadata"]["total"] = len(body[collection])
    first = await node.execute({})
    assert first[output] == [] and node.trigger_produced_no_event(first)
    assert native.Msg91Node.resolve_agent_event(first) is None
    assert (await node.execute({}))[output] == []
    if output == "emails":
        body[collection].append(additional_email)
        body["metadata"]["total"] = len(body[collection])
        assert (await node.execute({}))[output] == [additional_email]
        row = body[collection][0]
        row["statusUpdatedAt"] = "2026-03-02 16:36:27"  # documented second timestamp
        expected = [row]
        today = datetime.now(timezone.utc).date()
        assert dict(requests[0].url.params) == {"startDate": (today-timedelta(days=2)).isoformat(), "endDate": today.isoformat(), "limit": "1000"}
    else:
        row = body[collection][0]
        row["last_message"]["timetoken"] += 1  # synthetic later clock, same documented field
        expected = [row]
        assert dict(requests[0].url.params) == {"inbox_id": "1234", "type": "close", "start_from": "0", "page_size": "100"}
    changed = await node.execute({})
    assert changed[output] == expected and not node.trigger_produced_no_event(changed)
    event = native.Msg91Node.resolve_agent_event(changed)
    assert "MSG91" in event["text"]
    assert str(row.get("requestId") or row["ticket_id"]) in event["text"]
    assert (await node.execute({}))[output] == []
    assert state["seen_ids"]
    assert all(r.headers["authkey"] for r in requests)


@pytest.mark.asyncio
async def test_msg91_poll_errors_do_not_advance_baseline(monkeypatch):
    state = state_store(monkeypatch)
    body = copy.deepcopy(FIXTURES["GET /api/v5/report/logs/mail"]["body"])
    transport(monkeypatch, body)
    node = make_node({"operation": "on_email_delivery_update"})
    await node.execute({})
    before = copy.deepcopy(state)
    body["metadata"]["total"] = len(body["data"]) + 1
    with pytest.raises(ValueError, match="incomplete"):
        await node.execute({})
    assert state == before
    body["metadata"]["total"] = len(body["data"])
    del body["data"][0]["requestId"]
    with pytest.raises(ValueError, match="missing"):
        await node.execute({})
    assert state == before
    transport(monkeypatch, {"error": "Unauthorized"}, 401)
    with pytest.raises(ValueError):
        await node.execute({})
    assert state == before


def test_msg91_poll_scope_only_declared_fields_and_trigger_metadata():
    config = {"operation": "on_new_or_updated_ticket", "inbox_id": "1234"}
    scope = poll_scope(native.Msg91Node, config)
    assert scope == poll_scope(native.Msg91Node, {**config, "goal": "Updated label"})
    assert scope != poll_scope(native.Msg91Node, {**config, "inbox_id": "1631"})
    assert scope != poll_scope(native.Msg91Node, {**config, "ticket_state": "close"})
    for model in (native.OnEmailDeliveryUpdate, native.OnNewOrUpdatedTicket):
        assert model.model_fields["operation"].json_schema_extra["x-is-trigger"] is True
