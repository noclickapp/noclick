"""A WhatsApp trigger can hear its owner's own "Message yourself" chat, and never its agent's replies there.

WAHA's ``message`` event carries only what others send: the account's own messages come on ``message.any`` alone,
which repeats every other message too. With ``include_self_chat`` on, the trigger subscribes to it and lets through
only the owner writing in their own chat (named by the account's number or its @lid). The agent's replies in that
chat are the account's own messages as well, so they are dropped by id: every NoClick send is fingerprinted by its
WhatsApp stanza id (utils/self_echo.py), and that check fails closed there, since a missed echo is the agent
answering itself. Off, today's behaviour holds.
"""

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
    WEBHOOK, WORKFLOW, BrokenRedis, _deliver_via_relay, _deliver_via_route, fake_redis, wahooks,
)

pytestmark = pytest.mark.usefixtures("claimed_accounts")

ON = {"operation": "receive_message", "include_self_chat": "true"}
OFF = {"operation": "receive_message"}
ME = {"id": "12025550101@c.us", "lid": "12025550102@lid", "pushName": "Ada"}
OWN_NUMBER = "12025550101@c.us"
OWN_LID = "12025550102@lid"
FRIEND = "12025550107@c.us"
GROUP = "120000000000000001@g.us"


def _delivery(event=SELF_CHAT_EVENT, *, chat=OWN_LID, alt="12025550101@s.whatsapp.net", from_me=True,
              stanza="3A00000000000000AA01", body="Remind me to call the bank at 5", source="app",
              message=None, participant=None):
    """A WAHooks delivery as a receiving connection gets it (``me`` names the linked account)."""
    key = {"remoteJid": chat, "fromMe": from_me, "id": stanza,
           **({"remoteJidAlt": alt} if alt else {}), **({"participant": participant} if participant else {})}
    return {
        "event": event, "session": "u_test_s_test", "me": ME,
        "payload": {
            "id": f"{'true' if from_me else 'false'}_{chat}_{stanza}", "from": chat, "fromMe": from_me,
            "source": source, "body": body,
            "_data": {"key": key, "message": message or {"extendedTextMessage": {"text": body}}},
        },
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

@pytest.fixture
def owner_agent(monkeypatch):
    """A workflow whose WhatsApp trigger hears its owner's own chat."""
    from unittest.mock import AsyncMock

    from utils import capabilities, webhook_routes
    from utils.capabilities import TRIGGER_DELIVERY

    node = {"id": "inbound", "type": "automation-whatsapp", "config": {**ON, "webhook_id": WEBHOOK}}
    config = {"id": WEBHOOK, "user_id": str(uuid.uuid4()), "workflow_id": WORKFLOW, "node_id": "inbound",
              "secret": None, "is_active": True, "workflow_config": {"nodes": [node], "edges": []}}
    run = AsyncMock(return_value=None)
    monkeypatch.setattr(webhook_routes, "get_webhook_config", AsyncMock(return_value=config))
    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", run)
    monkeypatch.setattr(webhook_routes, "update_webhook_stats", lambda *_: None)
    monkeypatch.delitem(capabilities._providers, TRIGGER_DELIVERY, raising=False)
    return run


@pytest.mark.parametrize("deliver", [_deliver_via_relay, _deliver_via_route])
async def test_the_owners_note_runs_and_the_agents_reply_doesnt(fake_redis, wahooks, owner_agent, deliver):
    stanza = await _reply_to_the_owner()

    echo = await deliver(_delivery(chat="12025550101@s.whatsapp.net", alt=None, stanza=stanza))
    assert echo["status"] == 200 and "sent by a NoClick WhatsApp node" in echo["body"]
    owner_agent.assert_not_called()

    note = await deliver(_delivery())
    assert note["status"] == 200 and "workflow triggered" in note["body"]
    assert owner_agent.await_count == 1


# ── The owner's turn ───────────────────────────────────────────────────────────

def test_the_owners_note_is_their_turn_in_one_conversation_on_their_number():
    event = WhatsAppNode.resolve_agent_event(_delivery())
    assert event["from_owner"] is True
    assert event["conversation_key"] == OWN_NUMBER  # however the chat was named: one conversation
    assert "from the account's owner" in event["text"] and f"to={OWN_NUMBER}" in event["text"]
    assert "Remind me to call the bank at 5" in event["text"]


def test_anyone_elses_message_is_not_the_owners():
    event = WhatsAppNode.resolve_agent_event(_delivery("message", chat=FRIEND, alt=None, from_me=False))
    assert "from_owner" not in event and event["conversation_key"] == FRIEND


# ── Registration ───────────────────────────────────────────────────────────────

def test_the_own_chat_takes_its_event_only_when_on():
    assert SELF_CHAT_EVENT not in wahooks_webhook_events(OFF)
    assert wahooks_webhook_events(ON) == [*WAHOOKS_WEBHOOK_EVENTS, SELF_CHAT_EVENT]


def test_registrations_made_before_the_setting_keep_their_fingerprint():
    before = registration_fingerprint(WhatsAppNode, "receive_message", "cred-1", {})
    assert registration_fingerprint(WhatsAppNode, "receive_message", "cred-1", {"include_self_chat": "false"}) == before
    assert registration_fingerprint(WhatsAppNode, "receive_message", "cred-1", ON) != before


def test_turning_it_on_adds_the_event_to_a_live_webhook(monkeypatch):
    class Client:
        updated = []

        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def list_webhooks(self, _connection_id):
            return [{"id": "wh-1", "url": "https://wh.example.run", "events": list(WAHOOKS_WEBHOOK_EVENTS)}]

        def update_webhook(self, webhook_id, **kw):
            Client.updated.append((webhook_id, kw))

    monkeypatch.setattr("wahooks.WAHooks", Client)
    assert _wahooks_ensure_webhook("k", "conn-a", "https://wh.example.run", events=wahooks_webhook_events(ON))
    assert Client.updated == [("wh-1", {"events": sorted([*WAHOOKS_WEBHOOK_EVENTS, SELF_CHAT_EVENT])})]


async def test_toggling_it_on_a_saved_trigger_re_registers(monkeypatch):
    reconciled = []

    async def reconcile(pool, workflow_id, node_id, **_kw):
        reconciled.append(node_id)
        return {"state": "registered"}

    monkeypatch.setattr(WebhookManager, "reconcile_node", staticmethod(reconcile))
    changed = await WebhookManager.handle_registration_fields_change(
        None, "automation-whatsapp", WORKFLOW, "inbound", OFF, ON)
    assert changed is True and reconciled == ["inbound"]
    assert await WebhookManager.handle_registration_fields_change(
        None, "automation-whatsapp", WORKFLOW, "inbound", OFF, {**OFF, "chat_ids": [FRIEND]}) is False
