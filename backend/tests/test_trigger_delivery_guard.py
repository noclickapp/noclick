"""A per-node trigger delivery that its provider sends again, because it wasn't
answered fast enough, runs once. WAHooks gives up on a delivery after 15s and
retries it four more times under the same event ``id``.

The node names what makes two deliveries the same event
(``WorkflowNode.trigger_event_ids``). Both per-node delivery paths hold those
ids in the shared lease/delivered guard (``utils.app_delivery_guard``) from the
fire budget to the run's dispatch. Redis is fakeredis, which runs the guard's
real Lua.
"""

import asyncio
import copy
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import httpx
import pytest
from fastapi import FastAPI

from nodes.whatsapp_node import WhatsAppNode
from utils import capabilities, webhook_routes
from utils.app_delivery_guard import guard_app_deliveries
from utils.capabilities import TRIGGER_DELIVERY
from wss.handlers.workflow_execution_handler import WorkflowExecutionResult

from tests.fixtures.capabilities import claimed_accounts, deliveries_run_workflows  # noqa: F401  (fixtures)

pytestmark = pytest.mark.usefixtures("claimed_accounts")

CHAT = "12025550101@c.us"
STANZA = "3A1B2C3D4E5F60718293"
MESSAGE_ID = f"false_{CHAT}_{STANZA}"


def delivery(event_id="evt_01test", message_id=MESSAGE_ID, stanza=STANZA, event="message"):
    """A WAHooks delivery: ``id`` names the event, ``payload.id`` the message."""
    return {
        "id": event_id, "event": event, "session": "u_test_s_test",
        "payload": {"id": message_id, "from": CHAT, "fromMe": False, "body": "Is my order ready?",
                    "_data": {"key": {"remoteJid": CHAT, "fromMe": False, "id": stanza}}},
    }


def whatsapp_trigger(webhook_id, **config):
    return _webhook(webhook_id, "automation-whatsapp", {"operation": "receive_message", **config})


def _webhook(webhook_id, node_type, config):
    node_id = f"trigger_{webhook_id[:8]}"
    node = {"id": node_id, "type": node_type, "config": {"webhook_id": webhook_id, **config}}
    return {"id": webhook_id, "user_id": str(uuid.uuid4()), "workflow_id": str(uuid.uuid4()), "node_id": node_id,
            "secret": None, "is_active": True, "workflow_config": {"nodes": [node], "edges": []}}


@pytest.fixture
async def redis(monkeypatch):
    from utils import redis_client

    client = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(redis_client, "_client", client)
    yield client
    await client.aclose()


@pytest.fixture
def webhooks(monkeypatch):
    """The webhook rows in play, by id, each read afresh per delivery as the
    database would; the workflow runner and the stats write stand in for the
    engine's own."""
    rows = {}
    run = AsyncMock(return_value=None)

    async def config_of(webhook_id):
        return copy.deepcopy(rows.get(webhook_id))

    monkeypatch.setattr(webhook_routes, "get_webhook_config", config_of)
    monkeypatch.setattr(webhook_routes, "get_native_pool", MagicMock)
    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", run)
    monkeypatch.setattr(webhook_routes, "update_webhook_stats", lambda *_: None)
    return rows, run


def _runs_of(run, webhook_id):
    return [c for c in run.await_args_list
            if c.kwargs["nodes"][0]["config"]["webhook_id"] == webhook_id]


async def via_relay(webhook_id, body):
    reply = await webhook_routes.handle_webhook_payload(
        webhook_id, json.dumps(body), {}, {}, return_response=True)
    await asyncio.sleep(0)  # the relay acks first and runs the workflow in a spawned task
    return reply["status"], reply["body"]


async def via_route(webhook_id, body):
    app = FastAPI()
    app.include_router(webhook_routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/webhook/{webhook_id}", content=json.dumps(body),
                                     headers={"Content-Type": "application/json"})
    return response.status_code, response.text


BOTH_PATHS = pytest.mark.parametrize("deliver", [via_relay, via_route])


@pytest.fixture
def slow_rehost(monkeypatch):
    """WhatsApp's media rehost, held open until released: what each delivery rehosted."""
    entered, release, rehosted = asyncio.Event(), asyncio.Event(), []

    async def rehost(cls, payload, config, *, pool, workflow_id, node_id):
        rehosted.append(payload["id"])
        entered.set()
        await release.wait()
        return None

    monkeypatch.setattr(WhatsAppNode, "transform_trigger_payload", classmethod(rehost))
    return entered, release, rehosted


@BOTH_PATHS
async def test_a_retry_while_the_first_copy_is_dispatched_is_retryable_and_runs_nothing(
        redis, webhooks, deliveries_run_workflows, slow_rehost, deliver):
    rows, run = webhooks
    entered, release, rehosted = slow_rehost
    webhook = str(uuid.uuid4())
    rows[webhook] = whatsapp_trigger(webhook)

    first = asyncio.create_task(deliver(webhook, delivery()))
    await asyncio.wait_for(entered.wait(), timeout=10)
    # The lease is short enough for a later retry to take over a copy that died holding it.
    leases = await redis.keys("*:lease")
    assert len(leases) == 2  # the event's id and the message's
    assert all(0 < ttl <= 60 for ttl in [await redis.ttl(lease) for lease in leases])

    status, body = await deliver(webhook, delivery())
    assert status == 503 and "already in progress" in body
    assert rehosted == ["evt_01test"] and run.await_count == 0

    release.set()
    status, body = await first
    assert status == 200 and "workflow triggered" in body
    assert run.await_count == 1 and rehosted == ["evt_01test"]
    assert not await redis.keys("*:lease")


@BOTH_PATHS
async def test_a_retry_after_the_run_was_dispatched_is_a_200_without_a_run(
        redis, webhooks, deliveries_run_workflows, deliver):
    rows, run = webhooks
    webhook = str(uuid.uuid4())
    rows[webhook] = whatsapp_trigger(webhook)

    status, body = await deliver(webhook, delivery())
    assert status == 200 and "workflow triggered" in body
    status, body = await deliver(webhook, delivery())

    assert status == 200 and "already delivered" in body
    assert run.await_count == 1
    # Remembered for about a day, well past WAHooks' retries and a manual re-send.
    delivered = await redis.keys("*:delivered")
    assert len(delivered) == 2
    assert all(23 * 3600 < ttl <= 24 * 3600 for ttl in [await redis.ttl(key) for key in delivered])


@BOTH_PATHS
async def test_one_whatsapp_message_starts_one_run_on_a_trigger_whatever_event_carries_it(
        redis, webhooks, deliveries_run_workflows, deliver):
    """A re-sync after a reconnect sends a message again under a new event id."""
    rows, run = webhooks
    webhook = str(uuid.uuid4())
    rows[webhook] = whatsapp_trigger(webhook)

    assert (await deliver(webhook, delivery("evt_01test")))[0] == 200
    status, body = await deliver(webhook, delivery("evt_01test_resync"))
    assert status == 200 and "already delivered" in body
    assert run.await_count == 1

    # Another message is another run.
    other = f"false_{CHAT}_3A1B2C3D4E5F60718294"
    status, body = await deliver(webhook, delivery("evt_01test_next", other, "3A1B2C3D4E5F60718294"))
    assert status == 200 and "workflow triggered" in body
    assert run.await_count == 2


@BOTH_PATHS
async def test_one_event_sent_to_two_triggers_runs_both(redis, webhooks, deliveries_run_workflows, deliver):
    """WAHooks sends an event to every webhook on its connection, under one id."""
    rows, run = webhooks
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    rows[first], rows[second] = whatsapp_trigger(first), whatsapp_trigger(second)

    for webhook in (first, second):
        status, body = await deliver(webhook, delivery())
        assert status == 200 and "workflow triggered" in body
    assert len(_runs_of(run, first)) == 1 and len(_runs_of(run, second)) == 1

    for webhook in (first, second):
        status, body = await deliver(webhook, delivery())
        assert status == 200 and "already delivered" in body
    assert run.await_count == 2


@BOTH_PATHS
async def test_a_node_without_event_ids_runs_every_delivery_and_never_touches_redis(
        redis, webhooks, deliveries_run_workflows, deliver):
    rows, run = webhooks
    webhook = str(uuid.uuid4())
    rows[webhook] = _webhook(webhook, "trigger-webhook", {})

    for _ in range(2):
        status, body = await deliver(webhook, {"id": "evt_01test", "order": 7})
        assert status == 200 and "workflow triggered" in body
    assert run.await_count == 2
    assert await redis.keys("*") == []


def _broken_redis():
    broken = MagicMock()
    broken.eval = AsyncMock(side_effect=ConnectionError("synthetic outage"))
    return broken


@BOTH_PATHS
@pytest.mark.parametrize("client", [_broken_redis, lambda: None], ids=["redis-failing", "no-redis"])
async def test_without_redis_every_delivery_runs(monkeypatch, webhooks, deliveries_run_workflows, client, deliver):
    """WAHooks stops retrying within minutes, so a 503 during an outage (or on
    a self-hosted install without Redis) would drop the message for good: the
    guard fails open, and a retry during the outage may run again."""
    from utils import redis_client

    monkeypatch.setattr(redis_client, "_client", client())
    monkeypatch.delenv("REDIS_URL", raising=False)
    rows, run = webhooks
    webhook = str(uuid.uuid4())
    rows[webhook] = whatsapp_trigger(webhook)

    for _ in range(2):
        status, body = await deliver(webhook, delivery())
        assert status == 200 and "workflow triggered" in body
    assert run.await_count == 2


@BOTH_PATHS
async def test_a_platform_taken_delivery_is_taken_once_and_a_refusal_stays_retryable(
        redis, webhooks, monkeypatch, deliver):
    """A platform agent takes a fired trigger's delivery through
    ``TRIGGER_DELIVERY``, inside the guard: a retry never queues a second
    turn, and a refusal records nothing, so the sender's retry is judged again."""
    rows, run = webhooks
    webhook = str(uuid.uuid4())
    rows[webhook] = whatsapp_trigger(webhook)
    answers = [(409, {"error": {"type": "conflict", "message": "The agent is paused."}}),
               (202, {"object": "trigger_delivery", "status": "pending"})]
    taken = []

    async def take(*, workflow_id, node, payload, graph):
        taken.append(payload["id"])
        return answers.pop(0)

    monkeypatch.setitem(capabilities._providers, TRIGGER_DELIVERY, take)

    status, body = await deliver(webhook, delivery())
    assert status == 409 and "paused" in body
    assert await redis.keys("appwebhook:trigger:*") == []
    status, body = await deliver(webhook, delivery())
    assert status == 202 and json.loads(body)["status"] == "pending"
    status, body = await deliver(webhook, delivery())
    assert status == 200 and "already delivered" in body
    assert taken == ["evt_01test", "evt_01test"] and run.await_count == 0


@BOTH_PATHS
async def test_a_run_the_response_waits_for_starts_after_the_delivery_is_recorded(
        redis, webhooks, deliveries_run_workflows, deliver):
    """The lease covers dispatch, never the run (an agent's turn can take
    minutes): a run the response waits for starts with the lease let go."""
    rows, run = webhooks
    webhook = str(uuid.uuid4())
    rows[webhook] = whatsapp_trigger(webhook, respond="last_node")
    seen = {}

    async def run_inline(**kwargs):
        seen["leases"] = await redis.keys("*:lease")
        seen["delivered"] = await redis.keys("*:delivered")
        return WorkflowExecutionResult(execution_id="e", workflow_id=kwargs["workflow_id"], success=True,
                                       nodes_executed=1, duration=0.0, error=None)

    run.side_effect = run_inline
    status, _ = await deliver(webhook, delivery())

    assert status == 200 and run.await_count == 1
    assert seen["leases"] == [] and len(seen["delivered"]) == 2


# ── The node's ids and the shared guard ────────────────────────────────────────

def test_whatsapp_names_a_message_by_its_event_and_its_message():
    assert WhatsAppNode.trigger_event_ids(delivery(), {}) == ("event:evt_01test", f"message:{MESSAGE_ID}")
    own_chat = delivery(event="message.any")
    assert WhatsAppNode.trigger_event_ids(own_chat, {}) == ("event:evt_01test", f"message:{MESSAGE_ID}")


def test_whatsapp_names_other_events_by_their_event_alone():
    status = {"id": "evt_01status", "event": "session.status", "session": "s", "payload": {"status": "WORKING"}}
    assert WhatsAppNode.trigger_event_ids(status, {}) == ("event:evt_01status",)


def test_whatsapp_shapes_without_ids_are_not_guarded():
    cloud_api = {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": []}]}
    assert WhatsAppNode.trigger_event_ids(cloud_api, {}) is None
    assert WhatsAppNode.trigger_event_ids({"event": "message", "session": "s", "payload": {}}, {}) is None


GUARD = dict(provider="test", label="Test", lease_seconds=60, processing_seconds=50, dedup_seconds=86400)


async def test_a_delivery_known_by_several_ids_is_delivered_if_any_of_them_was(redis):
    async with guard_app_deliveries(["message:m1"], client=redis, **GUARD) as first:
        assert first
    async with guard_app_deliveries(["event:e2", "message:m1"], client=redis, **GUARD) as again:
        assert not again
    # The new event id is recorded too: its own retry is answered at once.
    async with guard_app_deliveries(["event:e2"], client=redis, **GUARD) as retry:
        assert not retry
    async with guard_app_deliveries(["event:e3", "message:m3"], client=redis, **GUARD) as other:
        assert other


async def test_failing_open_delivers_through_an_outage_and_a_lost_acknowledgement(redis):
    async with guard_app_deliveries(["event:e1"], client=_broken_redis(), fail_open=True, **GUARD) as deliver:
        assert deliver

    flaky = MagicMock()
    flaky.eval = AsyncMock(side_effect=[1, ConnectionError("synthetic outage")])
    async with guard_app_deliveries(["event:e1"], client=flaky, fail_open=True, **GUARD) as deliver:
        assert deliver  # dispatched: a 503 now would have it sent, and run, again
