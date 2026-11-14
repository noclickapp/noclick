"""A WhatsApp chat sees the account typing as soon as an agent takes its message into a turn, and never a live
status left at work by a turn that stopped partway.

WAHooks counts typing already shown toward the pause it keeps before a send, so a reply that used to wait about 7s
for its own seen/typing/pause goes at once (``nodes.agent.event_pickup``). A turn that ends without sending stops the
typing it showed; a reply ends it by itself. Test runs and unverified deliveries show nothing; the owner's own chat
and group talk not addressed to the account show no typing. A turn that stops partway edits the live status it left
("✻ Sending the panda…", 2026-11-14) to say so, and that it tries again when it goes round again."""

import asyncio

import fakeredis.aioredis
import pytest
from unittest.mock import AsyncMock, patch

from nodes.agent import event_pickup
from nodes.whatsapp_node import (
    STATUS_RETRYING,
    STATUS_STOPPED,
    WhatsAppEditMessageConfig,
    WhatsAppNode,
    WhatsAppNodeConfig,
    WhatsAppQRCredential,
    WhatsAppSendReactionConfig,
    WhatsAppSendTextConfig,
)

CHAT = "12025550101@c.us"
GROUP = "120000000000000001@g.us"
ME = {"id": "12025550108@c.us", "lid": "99887766@lid"}
OWN_CHAT = "12025550108@c.us"
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

    def start_typing(self, conn, chat):
        self.calls.append(("start_typing", conn, chat))

    def stop_typing(self, conn, chat):
        self.calls.append(("stop_typing", conn, chat))

    def send_message(self, conn, *, chat_id, text, reply_to=None):
        self.calls.append(("send_message", conn, chat_id))
        stanza = f"3EB{sum(c[0] == 'send_message' for c in self.calls)}"
        return {"key": {"remoteJid": chat_id, "fromMe": True, "id": stanza}, "id": f"true_{chat_id}_{stanza}"}

    def edit_message(self, conn, message_id, chat_id, text):
        self.calls.append(("edit_message", message_id, text))
        return {"ok": True}

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


async def _send(config, conversation_id=None):
    """A send tool call; ``conversation_id``: the turn making it, as an agent's tool call names it."""
    node = WhatsAppNode(node_id="wa-1", node_type="automation-whatsapp", node_data={},
                        config=WhatsAppNodeConfig(config=config, credentials=WhatsAppQRCredential(connection_id="conn-1")),
                        sio=None, sid=None, workflow_id="wf-1", conversation_id=conversation_id)
    result = await node._execute_wahooks(config, WhatsAppQRCredential(connection_id="conn-1"))
    assert result["status"] == "success"
    return result["data"].get("message_id")


# ── what a delivery shows ───────────────────────────────────────────────────


def test_a_verified_direct_message_is_read_and_typed_in_by_its_from():
    picked = WhatsAppNode.agent_pickup(_message())
    assert {k: picked[k] for k in ("connection_id", "chat_id")} == {"connection_id": "conn-1", "chat_id": CHAT}
    assert picked["token"]


@pytest.mark.parametrize("output", [
    _message(verified=False),  # what a payload says about itself isn't the account's to vouch for
    _message(chat=CHAT, from_me=True),  # the owner writing to someone else from their phone
    {"object": "whatsapp_business_account", "entry": []},  # the Cloud API, which WAHooks doesn't serve
    {"event": "session.status", "connectionId": "conn-1", "_webhook": {"signature_verified": True}},
])
def test_nothing_is_shown_where_the_agent_has_no_chat_to_answer(output):
    assert WhatsAppNode.agent_pickup(output) is None


@pytest.mark.parametrize("output", [
    _message(chat=OWN_CHAT, from_me=True),  # the owner's own "Message yourself" chat
    _message(chat=GROUP, participant="12025550101@c.us"),  # group talk the agent may well let pass
])
def test_a_chat_the_agent_answers_without_typing_is_still_its_turns_to_end(output):
    picked = WhatsAppNode.agent_pickup(output)
    assert picked["chat_id"] == output["payload"]["from"] and picked["typing"] is False


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
    assert gateway == [("start_typing", "conn-1", CHAT)]  # one call: a reply marks the chat read

    await event_pickup.turn_ended(CONVERSATION)
    assert gateway[-1] == ("stop_typing", "conn-1", CHAT)
    await event_pickup.turn_ended(CONVERSATION)  # ended once: nothing left to stop
    assert len(gateway) == 2


async def test_a_reply_ends_the_typing_itself_so_the_turns_end_stops_nothing(gateway):
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await _shown()
    await _send(WhatsAppSendTextConfig(to=CHAT, body="On it"))
    await event_pickup.turn_ended(CONVERSATION)
    assert [c[0] for c in gateway] == ["start_typing", "send_message"]


async def test_a_reaction_alone_leaves_the_typing_for_the_turns_end_to_stop(gateway):
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await _shown()
    await _send(WhatsAppSendReactionConfig(to=CHAT, message_id=f"false_{CHAT}_ABC", emoji="👍"))
    await event_pickup.turn_ended(CONVERSATION)
    assert [c[0] for c in gateway] == ["start_typing", "react", "stop_typing"]


async def test_the_turns_end_waits_for_the_pickup_it_would_otherwise_overtake(gateway):
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await event_pickup.turn_ended(CONVERSATION)  # no _shown(): the typing request may still be in flight
    assert [c[0] for c in gateway] == ["start_typing", "stop_typing"]


async def test_typing_the_gateway_refused_is_given_up_and_never_stopped(gateway, monkeypatch):
    """Every NoClick call shares one WAHooks token's calls a minute: a 429 is given up at once, never retried, and
    leaves the turn's end nothing to stop."""
    from wahooks import WAHooksError

    def refused(*_a, **_kw):
        _WAHooks.calls.append(("start_typing", "refused"))
        raise WAHooksError("Too many requests", 429)

    monkeypatch.setattr(_WAHooks, "start_typing", refused)
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await _shown()
    await event_pickup.turn_ended(CONVERSATION)
    assert gateway == [("start_typing", "refused")]


async def test_a_chat_already_typing_is_asked_once(gateway):
    """A second turn picking up the same chat while the first still has it typing calls nothing; the first's end
    takes it down."""
    await event_pickup.picked_up(CONVERSATION, _event(_message()))
    await _shown()
    await event_pickup.picked_up("ck:wf-1:other:12025550101@c.us", _event(_message()))
    await _shown()
    assert gateway == [("start_typing", "conn-1", CHAT)]
    await event_pickup.turn_ended("ck:wf-1:other:12025550101@c.us")
    await event_pickup.turn_ended(CONVERSATION)
    assert gateway == [("start_typing", "conn-1", CHAT), ("stop_typing", "conn-1", CHAT)]


async def test_the_owners_own_chat_sees_no_typing(gateway):
    await event_pickup.picked_up(CONVERSATION, _event(_message(chat=OWN_CHAT, from_me=True)))
    await _shown()
    await event_pickup.turn_ended(CONVERSATION)
    assert gateway == []


# ── a live status a turn left at work ───────────────────────────────────────


async def _status_left(chat=OWN_CHAT, *, conversation=CONVERSATION, picked=True):
    """A turn picks up a message in ``chat`` and sends a live status there, as the WhatsApp template's agent does."""
    if picked:
        await event_pickup.picked_up(conversation, _event(_message(chat=chat, from_me=chat == OWN_CHAT)))
        await _shown()
    return await _send(WhatsAppSendTextConfig(to=chat, body="✻ Sending the panda…"), conversation)


async def test_a_turn_that_stops_partway_says_so_in_the_status_it_left(gateway):
    status = await _status_left()
    await event_pickup.turn_ended(CONVERSATION, finished=False)
    assert gateway[-1] == ("edit_message", status, STATUS_STOPPED)
    await event_pickup.turn_ended(CONVERSATION, finished=False)  # ended once
    assert [c[0] for c in gateway].count("edit_message") == 1


async def test_a_group_turn_that_stops_partway_says_so_in_the_group(gateway):
    output = _message(chat=GROUP, participant="12025550101@c.us", mentions=["99887766@lid"])
    await event_pickup.picked_up(CONVERSATION, _event(output))
    await _shown()
    status = await _send(WhatsAppSendTextConfig(to=GROUP, body="✻ Two done, checking the third..."), CONVERSATION)
    await event_pickup.turn_ended(CONVERSATION, finished=False)
    assert ("edit_message", status, STATUS_STOPPED) in gateway


@pytest.mark.parametrize("finished", [True, False])
async def test_a_status_edited_into_the_answer_is_left_as_the_agent_wrote_it(gateway, finished):
    status = await _status_left()
    await _send(WhatsAppEditMessageConfig(chat_id=OWN_CHAT, message_id=status, body="Here's your panda 🐼"),
                CONVERSATION)
    await event_pickup.turn_ended(CONVERSATION, finished=finished)
    assert [c for c in gateway if c[0] == "edit_message"] == [("edit_message", status, "Here's your panda 🐼")]


async def test_a_finished_turn_leaves_its_status_to_the_agent(gateway):
    await _status_left()
    await event_pickup.turn_ended(CONVERSATION)
    assert "edit_message" not in [c[0] for c in gateway]


async def test_a_turn_that_goes_round_again_leaves_one_status_at_work(gateway):
    """A restart hands the turn over: its status says it tries again, and the run that picks it up (which never picks
    the event up itself) is ended by its settle, its own status the only one ever left at work."""
    first = await _status_left()
    await event_pickup.turn_ended(CONVERSATION, finished=False, again=True)
    assert gateway[-1] == ("edit_message", first, STATUS_RETRYING)

    second = await _status_left(picked=False)
    assert second != first
    await event_pickup.turn_ended(CONVERSATION, finished=False)
    edits = [c for c in gateway if c[0] == "edit_message"]
    assert edits == [("edit_message", first, STATUS_RETRYING), ("edit_message", second, STATUS_STOPPED)]


async def test_a_status_from_a_turn_that_picked_nothing_up_is_never_kept(gateway):
    await _status_left(picked=False)
    await event_pickup.turn_ended(CONVERSATION, finished=False)
    assert "edit_message" not in [c[0] for c in gateway]
