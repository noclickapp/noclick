"""The ``TRIGGER_DELIVERY`` seam: a product that provides it takes a fired
trigger's delivery in place of a run of the workflow, on every path a trigger
fires through (the per-node route, its relay twin, the app-event fan-out),
and answers its sender; a node it doesn't claim runs exactly as before."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI

from utils import capabilities, webhook_routes
from utils.capabilities import TRIGGER_DELIVERY

WORKFLOW = str(uuid.uuid4())
WEBHOOK = str(uuid.uuid4())


def _config(node_id: str) -> dict:
    node = {"id": node_id, "type": "trigger-webhook", "config": {"webhook_id": WEBHOOK}}
    return {"id": WEBHOOK, "user_id": str(uuid.uuid4()), "workflow_id": WORKFLOW, "node_id": node_id,
            "secret": None, "is_active": True, "workflow_config": {"nodes": [node], "edges": []}}


@pytest.fixture
def seam(monkeypatch):
    """A product claiming the node called ``taken``; the workflow runner and
    the stats write stand in for the engine's own."""
    taken = []

    async def deliver(*, workflow_id, node, payload):
        if node["id"] != "taken":
            return None
        taken.append({"workflow_id": workflow_id, "node_id": node["id"], "payload": payload})
        return 202, {"status": "taken"}

    run = AsyncMock(return_value=None)
    monkeypatch.setitem(capabilities._providers, TRIGGER_DELIVERY, deliver)
    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", run)
    monkeypatch.setattr(webhook_routes, "update_webhook_stats", lambda *_: None)
    return taken, run


def _route(monkeypatch, node_id: str) -> httpx.AsyncClient:
    monkeypatch.setattr(webhook_routes, "get_webhook_config", AsyncMock(return_value=_config(node_id)))
    app = FastAPI()
    app.include_router(webhook_routes.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_the_route_hands_a_claimed_delivery_over_and_answers_with_its_reply(seam, monkeypatch):
    taken, run = seam
    async with _route(monkeypatch, "taken") as client:
        response = await client.post(f"/webhook/{WEBHOOK}", json={"order": 7})
    assert response.status_code == 202 and response.json() == {"status": "taken"}
    [delivery] = taken
    assert delivery["workflow_id"] == WORKFLOW and delivery["payload"]["order"] == 7
    assert delivery["payload"]["_webhook"]["method"] == "POST"
    run.assert_not_awaited()


async def test_the_route_runs_a_workflow_the_seam_doesnt_claim(seam, monkeypatch):
    taken, run = seam
    async with _route(monkeypatch, "trigger_1") as client:
        response = await client.post(f"/webhook/{WEBHOOK}", json={"order": 7})
    assert response.status_code == 200 and response.json()["message"] == "Webhook received and workflow triggered"
    assert taken == [] and run.await_count == 1


async def test_without_a_provider_the_workflow_runs(seam, monkeypatch):
    taken, run = seam
    monkeypatch.delitem(capabilities._providers, TRIGGER_DELIVERY)
    async with _route(monkeypatch, "taken") as client:
        assert (await client.post(f"/webhook/{WEBHOOK}", json={})).status_code == 200
    assert taken == [] and run.await_count == 1


async def test_the_relay_twin_hands_it_over_as_a_relay_reply(seam, monkeypatch):
    taken, run = seam
    monkeypatch.setattr(webhook_routes, "get_webhook_config", AsyncMock(return_value=_config("taken")))
    reply = await webhook_routes.handle_webhook_payload(WEBHOOK, json.dumps({"n": 1}), {}, {}, return_response=True)
    assert reply["status"] == 202 and json.loads(reply["body"]) == {"status": "taken"}
    assert await webhook_routes.handle_webhook_payload(WEBHOOK, "{}", {}, {}) is True
    assert len(taken) == 2
    run.assert_not_awaited()


@pytest.mark.parametrize("node_id, status, fired, ran", [
    ("taken", 202, True, False),
    ("taken", 410, False, False),
    ("trigger_1", None, True, True),
])
async def test_the_app_event_fanout_hands_it_over(seam, monkeypatch, node_id, status, fired, ran):
    taken, _ = seam
    if status == 410:
        async def gone(*, workflow_id, node, payload):
            return 410, {"error": {"type": "gone"}}

        monkeypatch.setitem(capabilities._providers, TRIGGER_DELIVERY, gone)
    sub = {"provider": "hubspot", "workflow_id": uuid.UUID(WORKFLOW), "node_id": node_id, "user_id": uuid.uuid4()}
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"workflow": {"nodes": [{"id": node_id, "config": {}}], "edges": []}})
    tasks = MagicMock()
    with patch("utils.webhook_routes.get_native_pool", return_value=pool):
        assert await webhook_routes._fire_subscription(tasks, sub, {"event": {"id": 1}}, None) is fired
    assert tasks.add_task.called is ran
    assert [t["payload"] for t in taken] == ([{"event": {"id": 1}}] if status == 202 else [])
