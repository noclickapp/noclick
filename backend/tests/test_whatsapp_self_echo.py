"""Two NoClick WhatsApp agents on different linked numbers must not answer
each other forever.

Agent A's reply is a genuine inbound message on agent B's connection (not
``fromMe``), so B's trigger fires, B replies, A's trigger fires... and the
per-chat fire budget can't stop it: a turn takes long enough that the loop
stays under the cap. The guard is exact, like Slack's: every WAHooks send
fingerprints its WhatsApp stanza id (utils/self_echo.py), and the receiving
connection's delivery carries the same id at ``payload._data.key.id``, where
``WhatsAppNode.drop_trigger_event`` drops it before it becomes a run.
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from nodes.core.run_op import run_node_operation
from nodes.whatsapp_node import WhatsAppNode
from utils import capabilities, webhook_routes
from utils.capabilities import TRIGGER_DELIVERY

RECEIVE = {"operation": "receive_message"}
QR_CREDENTIAL = {"credential_type": "whatsapp_qr", "connection_id": "conn-a"}
# Agent A's chat as agent B's connection sees it, and a human's.
AGENT_A_CHAT = "12025550102@lid"
HUMAN_CHAT = "12025550103@lid"


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key, seconds):
        return True

    async def ttl(self, key):
        return 300


class BrokenRedis:
    async def set(self, *a, **kw):
        raise ConnectionError("redis down")

    async def exists(self, *a, **kw):
        raise ConnectionError("redis down")


@pytest.fixture
def fake_redis(monkeypatch):
    from utils import redis_client
    fake = FakeRedis()
    monkeypatch.setattr(redis_client, "_client", fake)
    return fake


class FakeWAHooks:
    """Stands in for wahooks.WAHooks. Sends answer the way WAHA does: the
    message ``key`` with a fresh stanza id."""

    sent: list = []

    def __init__(self, **_kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def __getattr__(self, method):
        def call(connection_id, *args, **kwargs):
            if not (method.startswith("send_") or method == "react"):
                return {"contacts": []}
            stanza = f"3EB0{uuid.uuid4().hex[:18].upper()}"
            FakeWAHooks.sent.append(stanza)
            return {
                "key": {"remoteJid": kwargs.get("chat_id"), "fromMe": True, "id": stanza},
                "message": {"extendedTextMessage": {"text": kwargs.get("text")}},
                "status": "PENDING",
            }
        return call


@pytest.fixture
def wahooks(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    FakeWAHooks.sent = []
    monkeypatch.setattr("wahooks.WAHooks", FakeWAHooks)
    return FakeWAHooks


async def _agent_tool_send(operation="send_text_message", **arguments):
    """A send through the agent-tool seam (node_op → run_node_operation)."""
    return await run_node_operation(
        node_type="automation-whatsapp",
        operation=operation,
        arguments={"to": "12025550104@s.whatsapp.net", "body": "You're welcome!", **arguments},
        user_id=str(uuid.uuid4()),
        credential_data=QR_CREDENTIAL,
    )


def _delivery(stanza: str, chat: str = AGENT_A_CHAT) -> dict:
    """A WAHooks 'message' delivery as the receiving connection gets it."""
    return {
        "id": "evt_01test",
        "event": "message",
        "session": "u_test_s_test",
        "payload": {
            "id": f"false_{chat}_{stanza}",
            "from": chat,
            "fromMe": False,
            "body": "You're welcome!",
            "_data": {"key": {"remoteJid": chat, "fromMe": False, "id": stanza}},
        },
    }


# ── Send side: every WAHooks send is fingerprinted ─────────────────────────────

@pytest.mark.parametrize("operation, arguments", [
    ("send_text_message", {}),
    ("send_image_message", {"image_url": "https://example.com/a.png"}),
    ("send_video_message", {"video_url": "https://example.com/a.mp4"}),
    ("send_document_message", {"document_url": "https://example.com/a.pdf"}),
    ("send_audio_message", {"audio_url": "https://example.com/a.ogg"}),
    ("send_location_message", {"latitude": "1.5", "longitude": "2.5"}),
    ("send_contact_card", {"contact_name": "Ada", "contact_phone": "+12025550100"}),
    ("send_reaction_emoji", {"message_id": "false_12025550102@lid_3EB0AA", "emoji": "👍"}),
])
async def test_every_send_fingerprints_its_stanza_id(fake_redis, wahooks, operation, arguments):
    result = await _agent_tool_send(operation, **arguments)

    assert result["status"] == "success"
    [stanza] = wahooks.sent
    assert f"whatsapp:selfpost:{stanza}" in fake_redis.store


async def test_non_send_operations_record_nothing(fake_redis, wahooks):
    await run_node_operation(
        node_type="automation-whatsapp", operation="list_contacts", arguments={},
        user_id=str(uuid.uuid4()), credential_data=QR_CREDENTIAL,
    )
    assert fake_redis.store == {}


async def test_redis_down_never_fails_the_send(monkeypatch, wahooks):
    from utils import redis_client
    monkeypatch.setattr(redis_client, "_client", BrokenRedis())

    result = await _agent_tool_send()

    assert result["status"] == "success" and len(wahooks.sent) == 1


# ── Receive side: the echo is dropped, everything else delivers ────────────────

async def test_inbound_copy_of_a_noclick_send_is_dropped(fake_redis, wahooks):
    await _agent_tool_send()
    [stanza] = wahooks.sent

    reason = await WhatsAppNode.drop_trigger_event(_delivery(stanza), RECEIVE)

    assert reason is not None and stanza in reason


async def test_an_unrelated_inbound_message_delivers(fake_redis, wahooks):
    await _agent_tool_send()
    human = _delivery("3A1B2C3D4E5F60718293", chat=HUMAN_CHAT)

    assert await WhatsAppNode.drop_trigger_event(human, RECEIVE) is None


async def test_other_operations_and_envelopes_are_never_dropped(fake_redis, wahooks):
    await _agent_tool_send()
    [stanza] = wahooks.sent
    assert await WhatsAppNode.drop_trigger_event(_delivery(stanza), {"operation": "receive_status_update"}) is None
    status = {"event": "session.status", "session": "s", "payload": {"status": "WORKING"}}
    assert await WhatsAppNode.drop_trigger_event(status, RECEIVE) is None


@pytest.mark.parametrize("client", [BrokenRedis(), None])
async def test_lookup_failure_fails_open(monkeypatch, client):
    from utils import redis_client
    monkeypatch.setattr(redis_client, "_client", client)
    monkeypatch.delenv("REDIS_URL", raising=False)

    assert await WhatsAppNode.drop_trigger_event(_delivery("3EB0DEADBEEF"), RECEIVE) is None


# ── Both per-node delivery paths: an echo never becomes a run ──────────────────

WORKFLOW = str(uuid.uuid4())
WEBHOOK = str(uuid.uuid4())


@pytest.fixture
def agent_b(monkeypatch):
    """Agent B's workflow: a WhatsApp receive_message trigger on WEBHOOK."""
    node = {"id": "inbound", "type": "automation-whatsapp",
            "config": {"operation": "receive_message", "webhook_id": WEBHOOK}}
    config = {"id": WEBHOOK, "user_id": str(uuid.uuid4()), "workflow_id": WORKFLOW, "node_id": "inbound",
              "secret": None, "is_active": True, "workflow_config": {"nodes": [node], "edges": []}}
    run = AsyncMock(return_value=None)
    monkeypatch.setattr(webhook_routes, "get_webhook_config", AsyncMock(return_value=config))
    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", run)
    monkeypatch.setattr(webhook_routes, "update_webhook_stats", lambda *_: None)
    monkeypatch.delitem(capabilities._providers, TRIGGER_DELIVERY, raising=False)
    return run


async def _deliver_via_relay(delivery: dict):
    reply = await webhook_routes.handle_webhook_payload(WEBHOOK, json.dumps(delivery), {}, {}, return_response=True)
    await asyncio.sleep(0)  # the relay acks first and runs the workflow in a spawned task
    return reply


async def _deliver_via_route(delivery: dict):
    app = FastAPI()
    app.include_router(webhook_routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/webhook/{WEBHOOK}", json=delivery)
    return {"status": response.status_code, "body": response.text}


@pytest.mark.parametrize("deliver", [_deliver_via_relay, _deliver_via_route])
async def test_agent_a_reply_never_wakes_agent_b(fake_redis, wahooks, agent_b, deliver):
    await _agent_tool_send()
    [stanza] = wahooks.sent

    reply = await deliver(_delivery(stanza))

    assert reply["status"] == 200 and "sent by a NoClick WhatsApp node" in reply["body"]
    agent_b.assert_not_called()


@pytest.mark.parametrize("deliver", [_deliver_via_relay, _deliver_via_route])
async def test_a_human_message_still_wakes_agent_b(fake_redis, wahooks, agent_b, deliver):
    await _agent_tool_send()

    reply = await deliver(_delivery("3A1B2C3D4E5F60718293", chat=HUMAN_CHAT))

    assert reply["status"] == 200 and "workflow triggered" in reply["body"]
    assert agent_b.await_count == 1
