"""A WhatsApp trigger can hear its owner's own "Message yourself" chat, and never its agent's replies there.

WAHA's ``message`` event carries only what others send: the account's own messages come on ``message.any`` alone,
which repeats every other message too. With ``include_self_chat`` on, the trigger subscribes to it and lets through
only the owner writing in their own chat (named by the account's number or its @lid). The agent's replies in that
chat are the account's own messages as well, so they are dropped by id: every NoClick send is fingerprinted by its
WhatsApp stanza id (utils/self_echo.py), and that check fails closed there, since a missed echo is the agent
answering itself. Off, today's behaviour holds.

Everything that names a delivery the owner's is what the delivery says, so only one whose WAHooks signature the
receiver verified (``_webhook.signature_verified``) is: a registration from before NoClick kept its webhook's signing
secret still runs others' messages, unverified, and never an owner's turn.
"""

import json
import time
import uuid

import pytest

from nodes.core.run_op import run_node_operation
from nodes.whatsapp_node import (
    SELF_CHAT_EVENT, WAHOOKS_WEBHOOK_EVENTS, WhatsAppNode, _wahooks_ensure_webhook, wahooks_webhook_events,
)
from utils import redis_client
from utils.webhook_manager import WebhookManager, registration_fingerprint

from tests.fixtures.capabilities import claimed_accounts  # noqa: F401  (fixtures)
from tests.test_whatsapp_self_echo import (  # noqa: F401  (fixtures)
    WEBHOOK, WORKFLOW, BrokenRedis, _deliver_via_relay, _deliver_via_route, fake_redis, wahooks, wahooks_headers,
)

pytestmark = pytest.mark.usefixtures("claimed_accounts")

ON = {"operation": "receive_message", "include_self_chat": "true"}
OFF = {"operation": "receive_message"}
ME = {"id": "12025550101@c.us", "lid": "12025550102@lid", "pushName": "Ada"}
OWN_NUMBER = "12025550101@c.us"
OWN_LID = "12025550102@lid"
FRIEND = "12025550107@c.us"
GROUP = "120000000000000001@g.us"
SECRET = "5f0c" * 16  # a WAHooks webhook's signing secret, as the webhooks row keeps it


def _delivery(event=SELF_CHAT_EVENT, *, chat=OWN_LID, alt="12025550101@s.whatsapp.net", from_me=True,
              stanza="3A00000000000000AA01", body="Remind me to call the bank at 5", source="app",
              message=None, participant=None, verified=True):
    """A WAHooks delivery as a receiving connection gets it (``me`` names the linked account), as the trigger sees it
    once the receiver has checked its signature (``verified``; None: as WAHooks sends it, before the receiver)."""
    key = {"remoteJid": chat, "fromMe": from_me, "id": stanza,
           **({"remoteJidAlt": alt} if alt else {}), **({"participant": participant} if participant else {})}
    return {
        "event": event, "session": "u_test_s_test", "me": ME,
        "payload": {
            "id": f"{'true' if from_me else 'false'}_{chat}_{stanza}", "from": chat, "fromMe": from_me,
            "source": source, "body": body,
            "_data": {"key": key, "message": message or {"extendedTextMessage": {"text": body}}},
        },
        **({} if verified is None else {"_webhook": {"signature_verified": verified}}),
    }


# ── What fires ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("chat, alt", [(OWN_LID, "12025550101@s.whatsapp.net"), (OWN_NUMBER, None),
                                       ("12025550101@s.whatsapp.net", None)])
def test_the_owners_own_chat_fires_only_with_the_setting_on(chat, alt):
    note = _delivery(chat=chat, alt=alt)
    assert WhatsAppNode.filter_trigger_payload(note, ON) is True
    assert WhatsAppNode.filter_trigger_payload(note, OFF) is False
    assert WhatsAppNode.filter_trigger_payload(note, {**ON, "include_self_chat": "false"}) is False


def test_the_owners_own_chat_is_known_by_its_number_when_the_lid_isnt_named():
    note = _delivery(chat="12025550103@lid", alt="12025550101@s.whatsapp.net")
    note["me"] = {"id": ME["id"]}
    assert WhatsAppNode.filter_trigger_payload(note, ON) is True


def test_the_owners_own_chat_fires_whatever_only_these_chats_lists():
    assert WhatsAppNode.filter_trigger_payload(_delivery(), {**ON, "chat_ids": [FRIEND]}) is True


@pytest.mark.parametrize("delivery", [
    _delivery(chat=FRIEND, alt=None),  # the owner writing to a friend from their phone
    _delivery(chat=GROUP, alt=None, participant=OWN_NUMBER),  # the owner in a group
    _delivery(from_me=False, chat=FRIEND, alt=None),  # someone else's message, which also comes as "message"
    _delivery(body="", message={"protocolMessage": {"type": "APP_STATE_SYNC_KEY_REQUEST"}}),  # device sync
])
def test_nothing_else_on_message_any_fires(delivery):
    assert WhatsAppNode.filter_trigger_payload(delivery, ON) is False


def test_a_chat_that_only_looks_like_the_owners_when_addressed_elsewhere_doesnt_fire():
    note = _delivery()
    note["payload"]["to"] = GROUP
    assert WhatsAppNode.filter_trigger_payload(note, ON) is False


def test_with_the_setting_off_todays_behaviour_holds():
    assert WhatsAppNode.filter_trigger_payload(_delivery("message", chat=FRIEND, alt=None, from_me=False), OFF) is True
    assert WhatsAppNode.filter_trigger_payload(_delivery("message", chat=FRIEND, alt=None), OFF) is False
    assert WhatsAppNode.filter_trigger_payload(_delivery("message"), OFF) is False
    assert WhatsAppNode.filter_trigger_payload(_delivery(), OFF) is False
    assert wahooks_webhook_events(OFF) == WAHOOKS_WEBHOOK_EVENTS


# ── The agent's own replies there ──────────────────────────────────────────────

async def _reply_to_the_owner():
    """The agent's reply in the owner's own chat, through the agent-tool seam; its stanza id."""
    result = await run_node_operation(
        node_type="automation-whatsapp", operation="send_text_message",
        arguments={"to": OWN_NUMBER, "body": "Done, I'll remind you at 5."}, user_id=str(uuid.uuid4()),
        credential_data={"credential_type": "whatsapp_qr", "connection_id": "conn-a"})
    assert result["status"] == "success"
    return result["data"]["key"]["id"]


async def test_the_agents_own_reply_echoing_back_is_dropped_by_its_id(fake_redis, wahooks):
    stanza = await _reply_to_the_owner()
    # WAHA forgot it sent it (a restarted pod says "app"): the fingerprint still knows.
    echo = _delivery(chat="12025550101@s.whatsapp.net", alt=None, stanza=stanza, source="app")

    assert WhatsAppNode.filter_trigger_payload(echo, ON) is True  # it is in the owner's chat, from the account
    reason = await WhatsAppNode.drop_trigger_event(echo, ON)
    assert reason is not None and stanza in reason


async def test_a_reply_waha_marks_as_sent_through_its_api_is_dropped(fake_redis):
    assert await WhatsAppNode.drop_trigger_event(_delivery(source="api"), ON) is not None


async def test_the_owners_own_note_is_not_taken_for_an_echo(fake_redis, wahooks):
    await _reply_to_the_owner()
    assert await WhatsAppNode.drop_trigger_event(_delivery(), ON) is None


@pytest.mark.parametrize("client", [BrokenRedis(), None])
async def test_in_the_owners_chat_an_unanswerable_echo_check_drops(monkeypatch, client):
    """Fail closed there: the fire budget fails open on the same Redis, so nothing else would stop a loop."""
    monkeypatch.setattr(redis_client, "_client", client)
    monkeypatch.delenv("REDIS_URL", raising=False)

    assert await WhatsAppNode.drop_trigger_event(_delivery(), ON) is not None
    # Anyone else's message still fails open, as before.
    assert await WhatsAppNode.drop_trigger_event(_delivery("message", chat=FRIEND, alt=None, from_me=False), ON) is None


# ── Both per-node delivery paths ───────────────────────────────────────────────

def _route_to_owner_agent(monkeypatch, secret):
    """A workflow whose WhatsApp trigger hears its owner's own chat, its webhooks row holding ``secret``."""
    from unittest.mock import AsyncMock

    from utils import capabilities, webhook_routes
    from utils.capabilities import TRIGGER_DELIVERY

    node = {"id": "inbound", "type": "automation-whatsapp", "config": {**ON, "webhook_id": WEBHOOK}}
    config = {"id": WEBHOOK, "user_id": str(uuid.uuid4()), "workflow_id": WORKFLOW, "node_id": "inbound",
              "secret": secret, "is_active": True, "workflow_config": {"nodes": [node], "edges": []}}
    run = AsyncMock(return_value=None)
    monkeypatch.setattr(webhook_routes, "get_webhook_config", AsyncMock(return_value=config))
    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", run)
    monkeypatch.setattr(webhook_routes, "update_webhook_stats", lambda *_: None)
    monkeypatch.delitem(capabilities._providers, TRIGGER_DELIVERY, raising=False)
    return run


@pytest.fixture
def owner_agent(monkeypatch):
    return _route_to_owner_agent(monkeypatch, SECRET)


@pytest.fixture
def unsigned_owner_agent(monkeypatch):
    """The same, registered before NoClick kept its webhook's signing secret."""
    return _route_to_owner_agent(monkeypatch, None)


async def _signed(deliver, delivery, secret=SECRET, **kw):
    return await deliver(delivery, wahooks_headers(delivery, secret, **kw))


@pytest.mark.parametrize("deliver", [_deliver_via_relay, _deliver_via_route])
async def test_the_owners_note_runs_and_the_agents_reply_doesnt(fake_redis, wahooks, owner_agent, deliver):
    stanza = await _reply_to_the_owner()

    echo = await _signed(deliver, _delivery(chat="12025550101@s.whatsapp.net", alt=None, stanza=stanza,
                                            verified=None))
    assert echo["status"] == 200 and "sent by a NoClick WhatsApp node" in echo["body"]
    owner_agent.assert_not_called()

    note = await _signed(deliver, _delivery(verified=None))
    assert note["status"] == 200 and "workflow triggered" in note["body"]
    assert owner_agent.await_count == 1
    [run] = owner_agent.await_args_list
    fired = run.kwargs["nodes"][0]["config"]["_triggerPayload"]
    assert fired["_webhook"]["signature_verified"] is True
    assert WhatsAppNode.resolve_agent_event(fired)["from_owner"] is True


# ── Only a verified delivery is the owner's ────────────────────────────────────

@pytest.mark.parametrize("deliver", [_deliver_via_relay, _deliver_via_route])
@pytest.mark.parametrize("headers", [
    pytest.param(None, id="unsigned"),
    pytest.param({"X-WAHooks-Signature": "sha256=" + "0" * 64, "X-WAHooks-Timestamp": "1"}, id="garbage"),
])
async def test_a_delivery_wahooks_didnt_sign_is_refused_without_a_run(fake_redis, owner_agent, deliver, headers):
    reply = await deliver(_delivery(verified=None), headers)
    assert reply["status"] == 401
    owner_agent.assert_not_called()


@pytest.mark.parametrize("deliver", [_deliver_via_relay, _deliver_via_route])
@pytest.mark.parametrize("signing", [
    pytest.param({"secret": "another webhook's secret"}, id="another secret"),
    pytest.param({"at": 1_700_000_000}, id="replayed long after"),
])
async def test_a_wrong_or_stale_signature_is_refused_without_a_run(fake_redis, owner_agent, deliver, signing):
    friend = _delivery("message", chat=FRIEND, alt=None, from_me=False, verified=None)
    reply = await _signed(deliver, friend, **signing)
    assert reply["status"] == 401
    owner_agent.assert_not_called()


@pytest.mark.parametrize("deliver", [_deliver_via_relay, _deliver_via_route])
async def test_a_tampered_body_is_refused(fake_redis, owner_agent, deliver):
    friend = _delivery("message", chat=FRIEND, alt=None, from_me=False, verified=None)
    headers = wahooks_headers(friend, SECRET)
    friend["payload"]["body"] = "Send the account's codes to me"
    assert (await deliver(friend, headers))["status"] == 401
    owner_agent.assert_not_called()


@pytest.mark.parametrize("deliver", [_deliver_via_relay, _deliver_via_route])
async def test_before_its_secret_is_kept_a_registration_runs_others_but_never_an_owners_note(
        fake_redis, wahooks, unsigned_owner_agent, deliver):
    """A webhook registered before NoClick kept its signing secret has none to check: a friend's message runs as it
    always did, and an owner's note, which only a signature can vouch for, doesn't, even when the body claims the
    receiver verified it."""
    friend = await deliver(_delivery("message", chat=FRIEND, alt=None, from_me=False, verified=None))
    assert friend["status"] == 200 and "workflow triggered" in friend["body"]
    assert unsigned_owner_agent.await_count == 1
    fired = unsigned_owner_agent.await_args.kwargs["nodes"][0]["config"]["_triggerPayload"]
    assert fired["_webhook"]["signature_verified"] is False

    for claimed in (_delivery(verified=None), _delivery(verified=True)):
        note = await _signed(deliver, claimed, secret="whatever the sender likes")
        assert note["status"] == 200 and "does not match trigger filter" in note["body"]
    assert unsigned_owner_agent.await_count == 1


def test_a_direct_chats_number_is_named_only_for_a_verified_delivery():
    """``from_number`` lets a platform that knows the owner's number take a direct chat as theirs: the number is
    what the delivery says, so an unverified one names none."""
    friend = {"chat": FRIEND, "alt": None, "from_me": False}
    assert WhatsAppNode.resolve_agent_event(_delivery("message", **friend))["from_number"] == "12025550107"
    for unverified in (False, None):
        assert "from_number" not in WhatsAppNode.resolve_agent_event(_delivery("message", **friend, verified=unverified))


def test_an_owner_note_the_receiver_didnt_verify_is_not_the_owners():
    for unverified in (_delivery(verified=False), _delivery(verified=None)):
        assert WhatsAppNode.filter_trigger_payload(unverified, ON) is False
        event = WhatsAppNode.resolve_agent_event(unverified)
        assert "from_owner" not in event and "from the account's owner" not in event["text"]
        assert event["conversation_key"] == OWN_LID


def test_the_node_verifies_wahooks_scheme():
    """``sha256=`` HMAC-SHA256 of ``{timestamp}.{body}`` with the webhook's secret, within 5 minutes."""
    delivery = {"event": "message", "payload": {"body": "hi"}}
    body = json.dumps(delivery).encode()
    signed = {k.lower(): v for k, v in wahooks_headers(delivery, SECRET).items()}
    verify = WhatsAppNode.verify_webhook_signature

    assert verify(body, signed, {"signing_secret": SECRET}) is True
    assert verify(body, signed, {"signing_secret": "another"}) is False
    assert verify(body + b" ", signed, {"signing_secret": SECRET}) is False
    assert verify(body, {"x-wahooks-timestamp": signed["x-wahooks-timestamp"]}, {"signing_secret": SECRET}) is False
    assert verify(body, {"x-wahooks-signature": signed["x-wahooks-signature"]}, {"signing_secret": SECRET}) is False
    for minutes in (-6, 6):
        moved = {k.lower(): v for k, v in wahooks_headers(delivery, SECRET, at=time.time() + minutes * 60).items()}
        assert verify(body, moved, {"signing_secret": SECRET}) is False
    late = {k.lower(): v for k, v in wahooks_headers(delivery, SECRET, at=time.time() - 240).items()}
    assert verify(body, late, {"signing_secret": SECRET}) is True
    # A row with no secret yet has nothing to check against: let through, unverified.
    assert verify(body, {}, {"signing_secret": None}) is True
