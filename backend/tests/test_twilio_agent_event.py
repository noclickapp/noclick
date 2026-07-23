"""Tests for TwilioNode.resolve_agent_event — inbound SMS/WhatsApp → agent turn.

When a Twilio ``on_incoming_sms`` trigger is wired directly into an AI agent, the
fired event must (1) surface the human message text, (2) hand the agent the reply
target VERBATIM in the exact form a send tool accepts, and (3) key a stable
per-conversation ck so each sender keeps its own memory. To reply you send FROM
the Twilio number (inbound ``To``) back TO the sender (inbound ``From``), so the
sender is the reply id and the ck is the ``sender:twilio_number`` pair.
"""
import sys
from urllib.parse import urlencode

sys.path.insert(0, "backend")

from nodes.twilio_node import TwilioNode


def _inbound_output(*, from_number, to_number, body="hello there", message_sid="SM" + "0" * 30):
    """Build the exact dict resolve_trigger_payload emits for an inbound SMS.

    Runs a realistic Twilio form-encoded webhook body through the real
    resolve_trigger_payload so the agent-event tests bind to the true shape.
    """
    form = {
        "MessageSid": message_sid,
        "SmsSid": message_sid,
        "AccountSid": "AC" + "1" * 30,
        "From": from_number,
        "To": to_number,
        "Body": body,
        "NumMedia": "0",
        "NumSegments": "1",
    }
    if from_number.lower().startswith("whatsapp:"):
        form["ProfileName"] = "Jane Doe"
        form["WaId"] = from_number.split(":")[-1].lstrip("+")
    raw = urlencode(form)
    return TwilioNode.resolve_trigger_payload({"raw": raw, "_webhook": {"id": "wh1"}}, {})


# ── Plain SMS ──────────────────────────────────────────────────────────────────

def test_plain_sms_surfaces_sender_and_ck():
    out = _inbound_output(from_number="+12025550106", to_number="+14155238886", body="what's my order status?")
    event = TwilioNode.resolve_agent_event(out)

    assert event["conversation_key"] == "+12025550106:+14155238886"
    assert "+12025550106" in event["text"]  # sender surfaced
    assert "what's my order status?" in event["text"]  # human message text
    assert "to_number=+12025550106" in event["text"]  # reply id in send-tool form
    assert "SMS" in event["text"]


def test_plain_sms_reply_targets_sender_not_twilio_number():
    out = _inbound_output(from_number="+12025550106", to_number="+14155238886")
    event = TwilioNode.resolve_agent_event(out)
    # Reply goes FROM the Twilio number TO the sender.
    assert "to_number=+12025550106" in event["text"]
    assert "from_number=+14155238886" in event["text"]


# ── WhatsApp (whatsapp: prefix must survive) ────────────────────────────────────

def test_whatsapp_preserves_prefix_in_ck_and_reply():
    out = _inbound_output(
        from_number="whatsapp:+12025550106",
        to_number="whatsapp:+14155238886",
        body="hola",
    )
    event = TwilioNode.resolve_agent_event(out)

    assert event["conversation_key"] == "whatsapp:+12025550106:whatsapp:+14155238886"
    assert "to_number=whatsapp:+12025550106" in event["text"]  # prefix preserved for send op
    assert "WhatsApp" in event["text"]
    assert "hola" in event["text"]


def test_same_sender_different_twilio_numbers_are_distinct_conversations():
    """A contact texting two business numbers must not collapse into one thread."""
    a = TwilioNode.resolve_agent_event(_inbound_output(from_number="+12025550106", to_number="+14155238886"))
    b = TwilioNode.resolve_agent_event(_inbound_output(from_number="+12025550106", to_number="+14155000000"))
    assert a["conversation_key"] != b["conversation_key"]


# ── Media-only message still delivers (sender present) ──────────────────────────

def test_media_only_message_delivers_with_placeholder_body():
    out = _inbound_output(from_number="+12025550106", to_number="+14155238886", body="")
    event = TwilioNode.resolve_agent_event(out)
    assert event["conversation_key"] == "+12025550106:+14155238886"
    assert "[non-text message]" in event["text"]


# ── Fallback: non-inbound-message shapes ────────────────────────────────────────

def test_unknown_shape_falls_back_to_base_json_dump():
    """A payload with no sender (From) can't be addressed — defer to the base."""
    out = {"message": "This trigger fires when an SMS is received", "phone_number_sid": "PN123"}
    event = TwilioNode.resolve_agent_event(out)
    assert event["conversation_key"] is None
    assert "phone_number_sid" in event["text"]  # base dumps the whole output as JSON


def test_empty_from_falls_back():
    out = _inbound_output(from_number="", to_number="+14155238886")
    event = TwilioNode.resolve_agent_event(out)
    assert event["conversation_key"] is None
