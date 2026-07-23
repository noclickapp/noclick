"""Tests for DiscordNode.resolve_agent_event — slash-command → agent turn.

A Discord slash-command trigger wired into an AI agent must deliver the
invoking user + command + args as the turn, surface the channel id VERBATIM as
the reply target (send_message_to_channel takes a channel_id), and key the
conversation on that channel so senders don't collapse into one thread. The
non-conversational Discord events (entitlement, application authorized) fall
through to the base JSON delivery with conversation_key=None.

The `output` passed to resolve_agent_event is whatever resolve_trigger_payload
returns; for a slash command that is the interaction dict built by
DiscordNode._resolve_app_event_payload (body type=2).
"""
import sys
import time

sys.path.insert(0, "backend")

from nodes.discord_node import DiscordNode

CHANNEL_ID = "1234567890123456789"
GUILD_ID = "9876543210987654321"


def _slash_command_output(
    *, channel_id=CHANNEL_ID, command_name="weather", options=None, username="alice"
):
    """A realistic resolve_trigger_payload OUTPUT for on_slash_command
    (mirrors _resolve_app_event_payload's body type=2 branch)."""
    return {
        "type": "discord",
        "action": "on_slash_command",
        "status": "success",
        "event_type": "on_slash_command",
        "command_name": command_name,
        "application_id": "111111111111111111",
        "guild_id": GUILD_ID,
        "channel_id": channel_id,
        "user_id": "222222222222222222",
        "username": username,
        "options": options if options is not None else {"city": "London"},
        "interaction_token": "tok_abc",
        "data": {"type": 2},
        "timestamp": time.time(),
    }


# ── Slash command: conversation-keyed on the channel id ────────────────────────

def test_slash_command_conversation_key_is_channel_id():
    result = DiscordNode.resolve_agent_event(_slash_command_output())
    assert result is not None
    assert result["conversation_key"] == CHANNEL_ID


def test_slash_command_text_surfaces_channel_and_command():
    result = DiscordNode.resolve_agent_event(_slash_command_output())
    text = result["text"]
    # Channel id appears verbatim as the reply target for the send tool.
    assert CHANNEL_ID in text
    assert "send_message_to_channel" in text
    assert f"channel_id={CHANNEL_ID}" in text
    # Command name + invoking user surface in the header.
    assert "/weather" in text
    assert "alice" in text


def test_slash_command_options_render_as_arguments():
    result = DiscordNode.resolve_agent_event(
        _slash_command_output(options={"city": "Paris", "unit": "c"})
    )
    text = result["text"]
    assert "city=Paris" in text
    assert "unit=c" in text


def test_slash_command_without_options_still_resolves():
    result = DiscordNode.resolve_agent_event(_slash_command_output(options={}))
    assert result["conversation_key"] == CHANNEL_ID
    assert CHANNEL_ID in result["text"]


def test_slash_command_missing_channel_falls_back_to_base():
    """No resolvable channel id → no reply target → base JSON delivery."""
    output = _slash_command_output(channel_id=None)
    result = DiscordNode.resolve_agent_event(output)
    assert result["conversation_key"] is None


# ── Non-conversational events fall through to base ─────────────────────────────

def test_entitlement_event_falls_back_to_base():
    output = {
        "type": "discord",
        "action": "on_entitlement_create",
        "status": "success",
        "event_type": "on_entitlement_create",
        "application_id": "111111111111111111",
        "data": {"type": 1, "event": {"type": "ENTITLEMENT_CREATE"}},
        "timestamp": time.time(),
    }
    result = DiscordNode.resolve_agent_event(output)
    assert result is not None
    assert result["conversation_key"] is None
    # Base delivers the raw output as JSON.
    assert "ENTITLEMENT_CREATE" in result["text"]


def test_unknown_shape_falls_back_to_base():
    result = DiscordNode.resolve_agent_event({"hello": "world"})
    assert result["conversation_key"] is None
    assert "world" in result["text"]
