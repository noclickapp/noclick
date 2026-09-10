"""The Slack trigger's run output names the channel the user picked.

Slack events carry channel ids only. The picker stores the label it showed
(``channel__label``), and the trigger output carries it as ``channel_label``
when the event is in that channel — the run-results frame reads it, else it
falls back to the id.
"""

from nodes.slack_node import SlackNode

ENVELOPE = {
    "type": "event_callback",
    "team_id": "T1",
    "event": {"type": "message", "subtype": "channel_join", "user": "U1", "channel": "C1",
              "text": "<@U1> has joined the channel", "ts": "1789060263.695389"},
}


def test_scoped_trigger_carries_the_picked_label():
    out = SlackNode.resolve_trigger_payload(
        ENVELOPE, {"operation": "on_channel_message", "channel": "C1", "channel__label": "#support"}
    )
    assert out["channel_label"] == "#support"
    assert out["action"] == "on_channel_message" and out["event_type"] == "message"
    assert out["data"] is ENVELOPE and out["team_id"] == "T1"


def test_label_is_only_claimed_for_the_scoped_channel():
    other = SlackNode.resolve_trigger_payload(
        ENVELOPE, {"operation": "on_channel_message", "channel": "C9", "channel__label": "#other"}
    )
    unscoped = SlackNode.resolve_trigger_payload(ENVELOPE, {"operation": "on_channel_message"})
    assert "channel_label" not in other and "channel_label" not in unscoped
