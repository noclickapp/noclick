"""Tests for GoHighLevelNode.resolve_agent_event — inbound-message → agent turn.

A GoHighLevel "On Inbound Message" trigger wired directly into an AI agent
delivers the fired webhook via resolve_agent_event. `output` here is whatever
resolve_trigger_payload returns, which for a push trigger is the raw HighLevel
webhook payload. The agent must (a) resume the right thread (conversation_key
= the GHL conversation id) and (b) get the reply target VERBATIM in the form
send_a_new_message accepts (contactId + channel type). Outbound echoes and
non-message shapes must fall through to the raw-JSON base default so a bot
never replies to its own message or mis-addresses a non-conversation event.
"""
import json

from nodes.gohighlevel_node import GoHighLevelNode


def _inbound_message(
    *,
    conversation_id="conv_9aX2kLpQ",
    contact_id="ct_7bYh4A0e",
    message_type="SMS",
    body="Hey, has my order shipped yet?",
    direction="inbound",
):
    """Realistic HighLevel InboundMessage webhook payload (the shape
    resolve_trigger_payload passes straight through for on_inbound_message)."""
    payload = {
        "type": "InboundMessage",
        "locationId": "loc_ABC123",
        "attachments": [],
        "body": body,
        "contactId": contact_id,
        "contentType": "text/plain",
        "conversationId": conversation_id,
        "dateAdded": "2026-07-23T09:34:56.000Z",
        "messageType": message_type,
        "status": "delivered",
        "messageId": "msg_XYZ789",
    }
    if direction is not None:
        payload["direction"] = direction
    return payload


# ── Inbound conversation messages ─────────────────────────────────────────────

def test_inbound_message_keys_on_conversation_id():
    ev = GoHighLevelNode.resolve_agent_event(_inbound_message())
    assert ev["conversation_key"] == "conv_9aX2kLpQ"


def test_inbound_message_surfaces_body_and_reply_target():
    ev = GoHighLevelNode.resolve_agent_event(_inbound_message())
    text = ev["text"]
    assert "Hey, has my order shipped yet?" in text
    # Reply target must appear verbatim in the form send_a_new_message accepts.
    assert "contactId=ct_7bYh4A0e" in text
    assert "type=SMS" in text


def test_inbound_message_channel_in_header():
    ev = GoHighLevelNode.resolve_agent_event(_inbound_message(message_type="Email"))
    assert "Email" in ev["text"]
    assert "type=Email" in ev["text"]


def test_message_field_alias_is_read():
    """Some HighLevel shapes carry the text under `message` rather than `body`."""
    payload = _inbound_message()
    del payload["body"]
    payload["message"] = "alias body here"
    ev = GoHighLevelNode.resolve_agent_event(payload)
    assert "alias body here" in ev["text"]
    assert ev["conversation_key"] == "conv_9aX2kLpQ"


def test_missing_conversation_id_falls_back_to_contact_id():
    payload = _inbound_message()
    del payload["conversationId"]
    ev = GoHighLevelNode.resolve_agent_event(payload)
    assert ev["conversation_key"] == "ct_7bYh4A0e"
    assert "contactId=ct_7bYh4A0e" in ev["text"]


# ── Outbound echoes must never trigger a reply ────────────────────────────────

def test_outbound_message_falls_back_to_base():
    ev = GoHighLevelNode.resolve_agent_event(_inbound_message(direction="outbound"))
    assert ev["conversation_key"] is None  # base default → agent doesn't auto-reply


# ── Non-message shapes fall through to the raw-JSON default ────────────────────

def test_non_message_event_falls_back_to_base():
    """A ContactCreate webhook has no message body → raw JSON, no thread key."""
    contact_event = {
        "type": "ContactCreate",
        "locationId": "loc_ABC123",
        "id": "ct_new001",
        "firstName": "Ada",
    }
    ev = GoHighLevelNode.resolve_agent_event(contact_event)
    assert ev["conversation_key"] is None
    assert json.loads(ev["text"])["type"] == "ContactCreate"


def test_message_without_routable_id_falls_back_to_base():
    payload = _inbound_message()
    del payload["conversationId"]
    del payload["contactId"]
    ev = GoHighLevelNode.resolve_agent_event(payload)
    assert ev["conversation_key"] is None


def test_non_dict_output_falls_back_to_base():
    ev = GoHighLevelNode.resolve_agent_event("not a dict")
    assert ev["conversation_key"] is None
