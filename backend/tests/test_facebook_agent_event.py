"""Tests for FacebookNode.resolve_agent_event — Messenger trigger → agent turn.

A Facebook Page trigger (on_messages / on_messaging_postbacks) wired directly
into an AI agent delivers its fired Meta webhook payload via resolve_agent_event.
The override must surface the sender PSID verbatim (the reply id the Messenger
send tools take as recipient_id) and key the conversation on that PSID, so
different Messenger users never collapse into one thread. Non-messaging Page
events (feed/ratings/…) and Instagram deliveries must fall back to raw JSON.
"""
import json
import sys

sys.path.insert(0, "backend")

from nodes.facebook_node import FacebookNode

PAGE_ID = "111111111111111"
PSID = "9876543210123456"


def _messenger_message(psid=PSID, text="Hello there", *, is_echo=False):
    """A realistic Messenger inbound-message webhook (object=page)."""
    message = {"mid": "m_abc123", "text": text}
    if is_echo:
        message["is_echo"] = True
    return {
        "object": "page",
        "entry": [
            {
                "id": PAGE_ID,
                "time": 1690000000000,
                "messaging": [
                    {
                        "sender": {"id": psid},
                        "recipient": {"id": PAGE_ID},
                        "timestamp": 1690000000000,
                        "message": message,
                    }
                ],
            }
        ],
    }


def _messenger_postback(psid=PSID, title="Get Started", payload="START"):
    return {
        "object": "page",
        "entry": [
            {
                "id": PAGE_ID,
                "time": 1690000000000,
                "messaging": [
                    {
                        "sender": {"id": psid},
                        "recipient": {"id": PAGE_ID},
                        "timestamp": 1690000000000,
                        "postback": {"mid": "m_pb1", "title": title, "payload": payload},
                    }
                ],
            }
        ],
    }


def _feed_change():
    """A non-messaging Page delivery (feed webhook field) → base fallback."""
    return {
        "object": "page",
        "entry": [
            {
                "id": PAGE_ID,
                "time": 1690000000000,
                "changes": [
                    {"field": "feed", "value": {"item": "status", "post_id": f"{PAGE_ID}_222"}}
                ],
            }
        ],
    }


# ── Conversational events resolve to the PSID ──────────────────────────────────

def test_message_keys_on_psid():
    ev = FacebookNode.resolve_agent_event(_messenger_message())
    assert ev is not None
    assert ev["conversation_key"] == PSID


def test_message_surfaces_psid_and_text():
    ev = FacebookNode.resolve_agent_event(_messenger_message(text="I need help with my order"))
    assert PSID in ev["text"]
    assert "I need help with my order" in ev["text"]
    # The reply hint names the exact send-tool parameters verbatim (recipient_id
    # is the PSID; page_id is the receiving Page, required by the send ops).
    assert f"recipient_id={PSID}" in ev["text"]
    assert f"page_id={PAGE_ID}" in ev["text"]


def test_distinct_senders_get_distinct_keys():
    a = FacebookNode.resolve_agent_event(_messenger_message(psid="1000000000000001"))
    b = FacebookNode.resolve_agent_event(_messenger_message(psid="2000000000000002"))
    assert a["conversation_key"] != b["conversation_key"]


def test_postback_keys_on_psid_and_surfaces_label():
    ev = FacebookNode.resolve_agent_event(_messenger_postback(title="Track My Order", payload="TRACK"))
    assert ev["conversation_key"] == PSID
    assert PSID in ev["text"]
    assert "Track My Order" in ev["text"]
    assert f"recipient_id={PSID}" in ev["text"]


def test_postback_falls_back_to_payload_without_title():
    ev = FacebookNode.resolve_agent_event(_messenger_postback(title=None, payload="MENU_MAIN"))
    assert ev["conversation_key"] == PSID
    assert "MENU_MAIN" in ev["text"]


def test_attachment_only_message_still_keys_on_psid():
    payload = _messenger_message()
    payload["entry"][0]["messaging"][0]["message"] = {
        "mid": "m_att", "attachments": [{"type": "image", "payload": {"url": "https://x/y.jpg"}}]
    }
    ev = FacebookNode.resolve_agent_event(payload)
    assert ev["conversation_key"] == PSID
    assert "[non-text message]" in ev["text"]


# ── Non-conversational shapes fall back to base (conversation_key None) ─────────

def test_feed_change_falls_back_to_raw_json():
    ev = FacebookNode.resolve_agent_event(_feed_change())
    assert ev["conversation_key"] is None
    # Base fallback dumps the whole payload as JSON.
    assert json.loads(ev["text"])["object"] == "page"


def test_instagram_object_falls_back():
    payload = _messenger_message()
    payload["object"] = "instagram"
    ev = FacebookNode.resolve_agent_event(payload)
    assert ev["conversation_key"] is None


def test_echo_message_falls_back():
    """Page's own outbound sends (is_echo) must not be treated as inbound."""
    ev = FacebookNode.resolve_agent_event(_messenger_message(is_echo=True))
    assert ev["conversation_key"] is None


def test_message_without_sender_id_falls_back():
    payload = _messenger_message()
    payload["entry"][0]["messaging"][0]["sender"] = {}
    ev = FacebookNode.resolve_agent_event(payload)
    assert ev["conversation_key"] is None


def test_malformed_payload_falls_back():
    ev = FacebookNode.resolve_agent_event({"object": "page"})
    assert ev["conversation_key"] is None
