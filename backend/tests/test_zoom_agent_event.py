"""Tests for ZoomNode.resolve_agent_event — conversational trigger → agent event.

A Zoom trigger wired directly into an AI agent delivers its fired webhook via
``resolve_agent_event``. Zoom passes the raw webhook through (base
``resolve_trigger_payload``), so the input is ``{"event", "payload": {"object"},
...}``. Only the chat/SMS events carry a human message + a reply target; every
other event (meetings, recordings, users, ...) must fall back to the base JSON
delivery so distinct conversations don't collapse and reply ids stay accurate.
"""
import json
import sys

sys.path.insert(0, "backend")

from nodes.zoom_node import ZoomNode


# ── Payload builders (realistic Zoom webhook shapes) ───────────────────────────

def _team_chat_channel_event(channel_id="8f2b3c4d5e6f", channel_name="general", message="deploy prod?"):
    """chat_message.sent to a Team Chat channel (object.type == to_channel)."""
    return {
        "event": "chat_message.sent",
        "event_ts": 1626230691572,
        "payload": {
            "account_id": "AbCdEfGhIj",
            "operator": "alice@example.com",
            "operator_id": "op-123",
            "object": {
                "message_id": "m-abc",
                "type": "to_channel",
                "channel_id": channel_id,
                "channel_name": channel_name,
                "sender": "alice@example.com",
                "message": message,
                "date_time": "2026-07-23T04:04:51Z",
                "timestamp": 1626230691572,
            },
        },
    }


def _team_chat_dm_event(operator="bob@example.com", message="can you check the logs?"):
    """chat_message.sent 1:1 direct message (object.type == to_contact)."""
    return {
        "event": "chat_message.sent",
        "event_ts": 1626230691572,
        "payload": {
            "account_id": "AbCdEfGhIj",
            "operator": operator,
            "operator_id": "op-456",
            "object": {
                "message_id": "m-def",
                "type": "to_contact",
                "contact_id": "c-789",
                "sender": operator,
                "message": message,
                "date_time": "2026-07-23T04:05:10Z",
                "timestamp": 1626230711000,
            },
        },
    }


def _phone_sms_event(sender="+13125550101", to_number="+12065550199", message="what time do you close?"):
    """phone.sms_received — inbound Zoom Phone SMS."""
    return {
        "event": "phone.sms_received",
        "event_ts": 1626230691572,
        "payload": {
            "account_id": "AbCdEfGhIj",
            "object": {
                "session_id": "s-abc123",
                "message_id": "sms-1",
                "direction": "inbound",
                "message": message,
                "sender": {"phone_number": sender, "display_name": "A Customer"},
                "to_members": [{"phone_number": to_number, "display_name": "Support"}],
                "date_time": "2026-07-23T04:06:00Z",
            },
        },
    }


def _meeting_chat_event(uuid="abcUUID==", meeting_id="8912345678", message="link please", sender_name="Carol"):
    """meeting.chat_message_sent — in-meeting chat (nested chat_message)."""
    return {
        "event": "meeting.chat_message_sent",
        "event_ts": 1626230691572,
        "payload": {
            "account_id": "AbCdEfGhIj",
            "operator": "host@example.com",
            "object": {
                "id": meeting_id,
                "uuid": uuid,
                "host_id": "host-1",
                "topic": "Standup",
                "chat_message": {
                    "date_time": "2026-07-23T04:07:00Z",
                    "message_id": "cm-1",
                    "message_content": message,
                    "sender_name": sender_name,
                    "sender_email": "carol@example.com",
                    "sender_type": "attendee",
                    "recipient_type": "everyone",
                },
            },
        },
    }


# ── Team Chat channel message ──────────────────────────────────────────────────

def test_team_chat_channel_surfaces_channel_id_and_reply_tool():
    event = _team_chat_channel_event(channel_id="CHAN99", message="ship it")
    result = ZoomNode.resolve_agent_event(event)
    assert result is not None
    # conversation_key keys on the channel so each channel is its own conversation.
    assert result["conversation_key"] == "CHAN99"
    text = result["text"]
    assert "ship it" in text
    assert "CHAN99" in text  # reply id surfaced verbatim
    assert "send_chat_message" in text
    assert "to_channel=CHAN99" in text


# ── Team Chat 1:1 direct message ───────────────────────────────────────────────

def test_team_chat_dm_replies_to_sender_email():
    event = _team_chat_dm_event(operator="bob@example.com", message="hey there")
    result = ZoomNode.resolve_agent_event(event)
    assert result is not None
    assert result["conversation_key"] == "bob@example.com"
    text = result["text"]
    assert "hey there" in text
    assert "bob@example.com" in text  # reply id surfaced verbatim
    assert "send_chat_message" in text
    assert "to_contact=bob@example.com" in text


def test_team_chat_dm_distinct_senders_distinct_conversations():
    a = ZoomNode.resolve_agent_event(_team_chat_dm_event(operator="a@x.com"))
    b = ZoomNode.resolve_agent_event(_team_chat_dm_event(operator="b@x.com"))
    assert a["conversation_key"] != b["conversation_key"]


# ── Zoom Phone SMS ─────────────────────────────────────────────────────────────

def test_phone_sms_surfaces_sender_number_and_reply_tool():
    event = _phone_sms_event(sender="+13125550101", message="are you open?")
    result = ZoomNode.resolve_agent_event(event)
    assert result is not None
    # conversation_key keys on the sender phone (task spec).
    assert result["conversation_key"] == "+13125550101"
    text = result["text"]
    assert "are you open?" in text
    assert "+13125550101" in text  # reply id surfaced verbatim
    assert "cc_send_sms" in text


def test_phone_sms_missing_sender_falls_back_to_base():
    event = _phone_sms_event()
    event["payload"]["object"]["sender"] = {}  # no phone_number
    result = ZoomNode.resolve_agent_event(event)
    # Base fallback: whole payload as JSON, no conversation key.
    assert result["conversation_key"] is None
    assert json.loads(result["text"])["event"] == "phone.sms_received"


# ── In-meeting chat (conversation anchor, no send-into-meeting op) ──────────────

def test_meeting_chat_keys_on_meeting_uuid():
    event = _meeting_chat_event(uuid="MTG-UUID-1", message="share the deck", sender_name="Carol")
    result = ZoomNode.resolve_agent_event(event)
    assert result is not None
    assert result["conversation_key"] == "MTG-UUID-1"
    text = result["text"]
    assert "share the deck" in text
    assert "Carol" in text
    assert "MTG-UUID-1" in text


def test_meeting_chat_falls_back_to_meeting_id_without_uuid():
    event = _meeting_chat_event(meeting_id="777")
    del event["payload"]["object"]["uuid"]
    result = ZoomNode.resolve_agent_event(event)
    assert result["conversation_key"] == "777"


# ── Non-conversational events fall through to base JSON delivery ────────────────

def test_meeting_started_uses_base_fallback():
    event = {
        "event": "meeting.started",
        "event_ts": 1626230691572,
        "payload": {"account_id": "AbCdEfGhIj", "object": {"id": "8912345678", "topic": "Standup"}},
    }
    result = ZoomNode.resolve_agent_event(event)
    # Base default: whole output as JSON, conversation_key None.
    assert result["conversation_key"] is None
    assert json.loads(result["text"])["event"] == "meeting.started"


def test_recording_completed_uses_base_fallback():
    event = {
        "event": "recording.completed",
        "payload": {"object": {"uuid": "rec-1", "topic": "Sync"}},
    }
    result = ZoomNode.resolve_agent_event(event)
    assert result["conversation_key"] is None
    assert json.loads(result["text"])["event"] == "recording.completed"


def test_malformed_payload_uses_base_fallback():
    """Guarded nested access: a chat event with no object dict falls back safely."""
    event = {"event": "chat_message.sent", "payload": None}
    result = ZoomNode.resolve_agent_event(event)
    assert result["conversation_key"] is None
