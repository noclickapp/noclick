"""Tests for IntercomNode.resolve_agent_event — trigger event → agent turn.

A conversation.* webhook wired directly into an AI agent must deliver the
latest message text, surface the conversation id VERBATIM in the reply form
the reply_conversation tool accepts, and key the turn on a per-conversation
conversation_key (so each Intercom thread keeps its own agent memory). Non
conversational topics (contact/company/ticket) fall through to the base
raw-JSON default with no conversation key.
"""
import json
import sys

sys.path.insert(0, "backend")

from nodes.intercom_node import IntercomNode

CONV_ID = "68a1f2b3c4d5e6f700112233"


def _author(name="Jane Doe", email="jane@example.com", atype="user"):
    return {"type": atype, "id": "contact_1", "name": name, "email": email}


def _conversation_event(
    topic,
    conv_id=CONV_ID,
    *,
    part_bodies=None,
    source_body="<p>Hi, my checkout is failing</p>",
    author=None,
):
    """Realistic Intercom conversation.* webhook notification envelope."""
    author = author or _author()
    parts = [
        {
            "type": "conversation_part",
            "id": f"part_{i}",
            "part_type": "comment",
            "body": b,
            "author": author,
        }
        for i, b in enumerate(part_bodies or [])
    ]
    return {
        "type": "notification_event",
        "id": "notif_abc123",
        "topic": topic,
        "app_id": "app123",
        "data": {
            "type": "notification_event_data",
            "item": {
                "type": "conversation",
                "id": conv_id,
                "source": {
                    "type": "conversation",
                    "id": "source_1",
                    "delivered_as": "customer_initiated",
                    "body": source_body,
                    "author": author,
                },
                "contacts": {"type": "contact.list", "contacts": [{"type": "contact", "id": "contact_1"}]},
                "conversation_parts": {
                    "type": "conversation_part.list",
                    "conversation_parts": parts,
                    "total_count": len(parts),
                },
            },
        },
    }


# ── Conversation events ────────────────────────────────────────────────────────

def test_user_created_uses_source_body():
    """conversation.user.created has no parts — the opening source body is used."""
    ev = IntercomNode.resolve_agent_event(_conversation_event("conversation.user.created"))
    assert ev["conversation_key"] == CONV_ID
    assert "checkout is failing" in ev["text"]
    assert CONV_ID in ev["text"]


def test_user_replied_uses_latest_part_body():
    ev = IntercomNode.resolve_agent_event(
        _conversation_event("conversation.user.replied", part_bodies=["<p>still broken, please help</p>"])
    )
    assert ev["conversation_key"] == CONV_ID
    assert "still broken" in ev["text"]


def test_latest_part_wins_over_earlier_parts():
    ev = IntercomNode.resolve_agent_event(
        _conversation_event(
            "conversation.user.replied",
            part_bodies=["<p>first reply</p>", "<p>second, newest reply</p>"],
        )
    )
    assert "second, newest reply" in ev["text"]


def test_reply_hint_is_verbatim_reply_tool_form():
    """The id must appear in the exact form the reply_conversation tool accepts."""
    ev = IntercomNode.resolve_agent_event(_conversation_event("conversation.user.replied"))
    assert f"conversation_id={CONV_ID}" in ev["text"]
    assert "reply_conversation" in ev["text"]


def test_author_and_topic_in_header():
    ev = IntercomNode.resolve_agent_event(
        _conversation_event("conversation.user.replied", author=_author(name="Alex Rivera"))
    )
    assert "Alex Rivera" in ev["text"]
    assert "conversation.user.replied" in ev["text"]


def test_conversation_key_is_string():
    ev = IntercomNode.resolve_agent_event(_conversation_event("conversation.admin.replied"))
    assert isinstance(ev["conversation_key"], str)


# ── Non-conversation events fall through to the base default ────────────────────

def _contact_event(topic="contact.user.created"):
    return {
        "type": "notification_event",
        "topic": topic,
        "data": {"item": {"type": "contact", "id": "contact_99", "email": "new@example.com"}},
    }


def test_contact_event_falls_through_to_base():
    ev = IntercomNode.resolve_agent_event(_contact_event())
    assert ev["conversation_key"] is None
    # Base default delivers the raw payload as JSON.
    assert "contact_99" in ev["text"]
    assert json.loads(ev["text"])  # valid JSON dump


def test_company_event_falls_through_to_base():
    payload = {"type": "notification_event", "topic": "company.created", "data": {"item": {"type": "company", "id": "co_1"}}}
    ev = IntercomNode.resolve_agent_event(payload)
    assert ev["conversation_key"] is None


def test_conversation_without_id_falls_through():
    ev = _conversation_event("conversation.user.replied")
    del ev["data"]["item"]["id"]
    resolved = IntercomNode.resolve_agent_event(ev)
    assert resolved["conversation_key"] is None
