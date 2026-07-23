"""Tests for MicrosoftTeamsNode.resolve_agent_event — the fired Graph
change-notification → directly-wired-agent turn translation.

A Teams channel/chat trigger wired straight into an agent must deliver the
human's message as the agent's turn, surface the reply ids VERBATIM in the
exact form the send/reply tools accept, and set a stable per-conversation key
so each chat keeps its own memory. This node registers 'basic' subscriptions
(no includeResourceData), so the notification carries only the resource PATH +
message id — never the body — which is why the event points the agent at the
get_* tool to fetch the text. Payload shapes mirror the real Graph
notifications exercised in nodes/tests/test_microsoft_teams_trigger_e2e.py.
"""
import json
import sys

sys.path.insert(0, "backend")

from nodes.microsoft_teams_node import MicrosoftTeamsNode

# Realistic Teams ids: team GUID, channel/chat opaque thread ids, message ts.
TEAM_ID = "86bc71a0-4a3f-4e2b-9d1c-0e5f2a3b4c5d"
CHANNEL_ID = "19:abc123def456@thread.tacv2"
CHAT_ID = "19:2da4c29f6d7041eca70b638b43d45437@thread.v2"
MSG_ID = "1616989002104"


def _channel_notification(team_id, channel_id, message_id, change="created"):
    """A basic Graph change notification for a channel message (parentheses
    resource form, as Graph delivers and the e2e roundtrip test asserts)."""
    return {
        "value": [
            {
                "subscriptionId": "sub-123",
                "clientState": "secret",
                "changeType": change,
                "resource": f"teams('{team_id}')/channels('{channel_id}')/messages('{message_id}')",
                "resourceData": {
                    "@odata.type": "#Microsoft.Graph.Message",
                    "@odata.id": f"teams('{team_id}')/channels('{channel_id}')/messages('{message_id}')",
                    "id": message_id,
                },
                "tenantId": "tenant-xyz",
            }
        ]
    }


def _chat_notification(chat_id, message_id, change="created"):
    return {
        "value": [
            {
                "subscriptionId": "sub-456",
                "clientState": "secret",
                "changeType": change,
                "resource": f"chats('{chat_id}')/messages('{message_id}')",
                "resourceData": {"@odata.type": "#Microsoft.Graph.chatMessage", "id": message_id},
            }
        ]
    }


# ── Channel messages ───────────────────────────────────────────────────────────

def test_channel_message_surfaces_reply_ids_and_key():
    event = MicrosoftTeamsNode.resolve_agent_event(
        _channel_notification(TEAM_ID, CHANNEL_ID, MSG_ID)
    )
    assert event is not None
    # per-channel conversation key (team:channel), stable across senders
    assert event["conversation_key"] == f"{TEAM_ID}:{CHANNEL_ID}"
    text = event["text"]
    # every id the reply op needs is present, verbatim
    assert TEAM_ID in text
    assert CHANNEL_ID in text
    assert MSG_ID in text
    # points the agent at the reply op by name
    assert "reply_channel_message" in text


def test_channel_message_notes_body_must_be_fetched():
    """Basic notifications omit the body; the event must say so and name the
    fetch tool rather than inventing text."""
    event = MicrosoftTeamsNode.resolve_agent_event(
        _channel_notification(TEAM_ID, CHANNEL_ID, MSG_ID)
    )
    assert "get_channel_message" in event["text"]
    assert "does not include the message text" in event["text"]


def test_channel_message_slash_resource_form_also_parsed():
    """Graph also emits plain-path resources; both encodings must yield ids."""
    payload = {
        "value": [
            {
                "clientState": "secret",
                "changeType": "updated",
                "resource": f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages/{MSG_ID}",
                "resourceData": {"id": MSG_ID},
            }
        ]
    }
    event = MicrosoftTeamsNode.resolve_agent_event(payload)
    assert event["conversation_key"] == f"{TEAM_ID}:{CHANNEL_ID}"
    assert CHANNEL_ID in event["text"]
    assert MSG_ID in event["text"]


# ── Chat messages ──────────────────────────────────────────────────────────────

def test_chat_message_surfaces_reply_id_and_key():
    event = MicrosoftTeamsNode.resolve_agent_event(_chat_notification(CHAT_ID, MSG_ID))
    assert event is not None
    # chat id is the per-conversation key (one conversation per chat)
    assert event["conversation_key"] == CHAT_ID
    text = event["text"]
    assert CHAT_ID in text
    assert MSG_ID in text
    # points the agent at the chat send op with the chat id to pass
    assert "send_chat_message" in text
    assert "get_chat_message" in text


# ── Fallback to the base default ───────────────────────────────────────────────

def test_non_message_notification_falls_back_to_raw_json():
    """A membership/lifecycle notification (no message resource) is not a
    conversation — deliver the raw JSON with no conversation key."""
    payload = {
        "value": [
            {
                "clientState": "secret",
                "changeType": "created",
                "resource": f"teams('{TEAM_ID}')/members('mem-42')",
                "resourceData": {"id": "mem-42"},
            }
        ]
    }
    event = MicrosoftTeamsNode.resolve_agent_event(payload)
    assert event["conversation_key"] is None
    # base default dumps the whole payload as JSON
    assert json.loads(event["text"])["value"][0]["resource"].startswith("teams")


def test_unknown_payload_shape_falls_back_to_raw_json():
    payload = {"foo": "bar", "not": "a graph notification"}
    event = MicrosoftTeamsNode.resolve_agent_event(payload)
    assert event["conversation_key"] is None
    assert json.loads(event["text"]) == payload
