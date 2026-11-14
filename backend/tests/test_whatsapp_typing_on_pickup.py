"""A WhatsApp chat sees its message read and the account typing as soon as an agent takes the message into a turn.

WAHooks counts typing already shown toward the pause it keeps before a send, so a reply that used to wait about 7s
for its own seen/typing/pause goes at once (``nodes.agent.event_pickup``). A turn that ends without sending stops the
typing it showed; a reply ends it by itself. Test runs, the owner's own chat, unverified deliveries and group talk
not addressed to the account show nothing."""

import asyncio

import fakeredis.aioredis
import pytest
from unittest.mock import AsyncMock, patch

from nodes.agent import event_pickup
from nodes.agent_node import AgentNode
from nodes.whatsapp_node import (
    WhatsAppNode,
    WhatsAppNodeConfig,
    WhatsAppQRCredential,
    WhatsAppSendReactionConfig,
    WhatsAppSendTextConfig,
)

CHAT = "12025550101@c.us"
GROUP = "120000000000000001@g.us"
ME = {"id": "12025550108@c.us", "lid": "99887766@lid"}
CONVERSATION = "ck:wf-1:agent:12025550101@c.us"


def _message(chat=CHAT, *, verified=True, from_me=False, participant=None, mentions=(), reply_to=None):
    key = {"remoteJid": chat, "fromMe": from_me, "id": "ABC", **({"participant": participant} if participant else {})}
    data = {"key": key, "pushName": "Sam"}
    if mentions:
        data["message"] = {"extendedTextMessage": {"text": "hey", "contextInfo": {"mentionedJid": list(mentions)}}}
    payload = {"id": f"false_{chat}_ABC", "from": chat, "fromMe": from_me, "body": "hey", "_data": data}
    if reply_to:
        payload["replyTo"] = {"participant": reply_to, "body": "earlier"}
    output = {"event": "message", "connectionId": "conn-1", "me": ME, "payload": payload}
    if verified:
        output["_webhook"] = {"signature_verified": True}
    return output


class _WAHooks:
    """Stands in for wahooks.WAHooks, recording what reached the gateway."""

    calls: list = []

    def __init__(self, **_kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def mark_read(self, conn, chat):
        self.calls.append(("mark_read", conn, chat))

    def start_typing(self, conn, chat):
        self.calls.append(("start_typing", conn, chat))

    def stop_typing(self, conn, chat):
        self.calls.append(("stop_typing", conn, chat))

    def send_message(self, conn, *, chat_id, text, reply_to=None):
        self.calls.append(("send_message", conn, chat_id))
        return {"key": {"remoteJid": chat_id, "fromMe": True, "id": "3EB0"}, "id": f"true_{chat_id}_3EB0"}

    def react(self, conn, *, chat_id, message_id, reaction):
        self.calls.append(("react", conn, chat_id))
        return {"ok": True}


@pytest.fixture
def gateway(monkeypatch):
    """What reached WAHooks, with one Redis behind the agent's turn and the WhatsApp node alike."""
    from utils import redis_client

    redis = fakeredis.aioredis.FakeRedis()
    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    monkeypatch.setattr("wahooks.WAHooks", _WAHooks)
    monkeypatch.setattr(redis_client, "get_shared_redis", lambda: redis)
    _WAHooks.calls = []
    return _WAHooks.calls


def _event(output):
    return {"node_type": "automation-whatsapp", "output": output}


async def _shown():
    await asyncio.gather(*event_pickup._showing.values())


async def _send(config):
    node = WhatsAppNode(node_id="wa-1", node_type="automation-whatsapp", node_data={},
                        config=WhatsAppNodeConfig(config=config, credentials=WhatsAppQRCredential(connection_id="conn-1")),
                        sio=None, sid=None, workflow_id="wf-1")
    result = await node._execute_wahooks(config, WhatsAppQRCredential(connection_id="conn-1"))
    assert result["status"] == "success"


# ── what a delivery shows ───────────────────────────────────────────────────


def test_a_verified_direct_message_is_read_and_typed_in_by_its_from():
    picked = WhatsAppNode.agent_pickup(_message())
    assert {k: picked[k] for k in ("connection_id", "chat_id")} == {"connection_id": "conn-1", "chat_id": CHAT}
    assert picked["token"]


@pytest.mark.parametrize("output", [
    _message(verified=False),  # what a payload says about itself isn't the account's to vouch for
    _message(chat="12025550108@c.us", from_me=True),  # the owner's own "Message yourself" chat
    _message(chat=GROUP, participant="12025550101@c.us"),  # group talk the agent may well let pass
    {"object": "whatsapp_business_account", "entry": []},  # the Cloud API, which WAHooks doesn't serve
    {"event": "session.status", "connectionId": "conn-1", "_webhook": {"signature_verified": True}},
])
def test_nothing_is_shown_where_the_agent_has_no_chat_to_answer(output):
    assert WhatsAppNode.agent_pickup(output) is None


@pytest.mark.parametrize("output", [
    _message(chat=GROUP, participant="12025550101@c.us", mentions=["99887766@lid"]),
    _message(chat=GROUP, participant="12025550101@c.us", reply_to="12025550108@c.us"),
])
def test_a_group_message_addressed_to_the_account_shows_typing_in_the_group(output):
    assert WhatsAppNode.agent_pickup(output)["chat_id"] == GROUP


# ── a turn, from pickup to its end ──────────────────────────────────────────


async def test_typing_starts_on_pickup_and_a_quiet_ending_stops_it(gateway):
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await _shown()
    assert gateway == [("mark_read", "conn-1", CHAT), ("start_typing", "conn-1", CHAT)]

    await event_pickup.turn_ended(CONVERSATION)
    assert gateway[-1] == ("stop_typing", "conn-1", CHAT)
    await event_pickup.turn_ended(CONVERSATION)  # ended once: nothing left to stop
    assert len(gateway) == 3


async def test_a_reply_ends_the_typing_itself_so_the_turns_end_stops_nothing(gateway):
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await _shown()
    await _send(WhatsAppSendTextConfig(to=CHAT, body="On it"))
    await event_pickup.turn_ended(CONVERSATION)
    assert [c[0] for c in gateway] == ["mark_read", "start_typing", "send_message"]


async def test_a_reaction_alone_leaves_the_typing_for_the_turns_end_to_stop(gateway):
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await _shown()
    await _send(WhatsAppSendReactionConfig(to=CHAT, message_id=f"false_{CHAT}_ABC", emoji="👍"))
    await event_pickup.turn_ended(CONVERSATION)
    assert [c[0] for c in gateway] == ["mark_read", "start_typing", "react", "stop_typing"]


async def test_the_turns_end_waits_for_the_pickup_it_would_otherwise_overtake(gateway):
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await event_pickup.turn_ended(CONVERSATION)  # no _shown(): the typing request may still be in flight
    assert [c[0] for c in gateway] == ["mark_read", "start_typing", "stop_typing"]


async def test_a_gateway_failure_never_reaches_the_turn(gateway, monkeypatch):
    def down(*_a, **_kw):
        raise ConnectionError("gateway unreachable")

    monkeypatch.setattr(_WAHooks, "start_typing", down)
    monkeypatch.setattr(_WAHooks, "stop_typing", down)
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await _shown()
    await event_pickup.turn_ended(CONVERSATION)
    assert gateway == [("mark_read", "conn-1", CHAT)]


# ── where the agent node shows and ends it ──────────────────────────────────


def _agent(conversation_id=None):
    return AgentNode(node_id="agent", node_type="agent", node_data={}, config=None, sio=None, sid=None,
                     workflow_id="wf-1", conversation_id=conversation_id)


async def test_a_test_run_shows_nothing_on_the_chat():
    with patch.object(event_pickup, "picked_up", AsyncMock()) as picked_up:
        agent = _agent("rehearsal:abc")
        await agent._pick_up(_event(_message()))
        picked_up.assert_not_awaited()
        assert agent._picked_up_in is None

        agent, event = _agent(CONVERSATION), _event(_message())
        await agent._pick_up(event)
        picked_up.assert_awaited_once_with(CONVERSATION, event)
        assert agent._picked_up_in == CONVERSATION


@pytest.mark.parametrize("output,ended", [
    ({"type": "agent", "status": "completed", "response": ""}, True),
    # A sandbox has the turn: its callback ends it once the harness answers.
    ({"type": "agent", "status": "awaiting_agent_turn", "response": ""}, False),
])
async def test_the_agent_node_ends_a_turn_it_ran_itself(output, ended):
    agent = _agent(CONVERSATION)

    async def run(_inputs):
        agent._picked_up_in = CONVERSATION
        return output

    with patch.object(agent, "_execute_impl", run), patch.object(event_pickup, "turn_ended", AsyncMock()) as end:
        await agent.execute({})
    assert end.await_args_list == ([((CONVERSATION,),)] if ended else [])


async def test_a_turn_that_fails_ends_what_it_showed():
    agent = _agent(CONVERSATION)

    async def run(_inputs):
        agent._picked_up_in = CONVERSATION
        raise RuntimeError("the model is down")

    with patch.object(agent, "_execute_impl", run), patch.object(agent, "_hand_back_turn", AsyncMock()), \
            patch.object(event_pickup, "turn_ended", AsyncMock()) as end:
        with pytest.raises(RuntimeError):
            await agent.execute({})
    end.assert_awaited_once_with(CONVERSATION)
