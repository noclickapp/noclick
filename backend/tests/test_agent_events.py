"""The shaping every trigger's resolve_agent_event shares (nodes/core/agent_events)
and the Slack override built on it.

A fired trigger's output is a delivery envelope around a provider payload,
and the payload carries transport fields the agent must never read as the
event (2026-09-12: a Slack agent's turn was ~300 lines of verification token,
authorizations, block-kit and a previous_message copy for one edited bot
card). The turn the model reads and the record the chat surface stores are
both bounded and free of plumbing.
"""

import json

import pytest

from nodes.core.agent_events import (
    compact_for_display,
    compact_json,
    default_agent_event,
    first_line,
    humanize_slack_markup,
    prune_empty,
    unwrap_trigger_output,
)
from nodes.slack_node import SlackNode


class TestShaping:
    def test_unwrap_takes_the_object_wrapper_and_keeps_its_scalars_as_envelope(self):
        payload, envelope = unwrap_trigger_output(
            {"type": "slack", "action": "on_x", "status": "success", "data": {"a": 1}, "_webhook": {"h": 1}}
        )
        assert payload == {"a": 1}
        assert envelope == {"type": "slack", "action": "on_x", "status": "success"}

    def test_unwrap_without_a_wrapper_keeps_provider_scalars_and_drops_routing(self):
        payload, envelope = unwrap_trigger_output(
            {"action": "opened", "issue": {"n": 1}, "workflow_id": "w", "_webhook": {}}
        )
        assert payload == {"action": "opened", "issue": {"n": 1}}
        assert envelope == {}

    def test_prune_drops_empties_and_private_keys_recursively(self):
        assert prune_empty({"a": None, "b": "", "c": [], "d": {"_x": 1, "e": [None, {"f": ""}, 2]}}) == {
            "d": {"e": [2]}
        }

    def test_compact_json_bounds_and_says_so(self):
        text = compact_json({"body": "x" * 5000}, limit=200)
        assert len(text) < 320
        assert "truncated" in text and "full payload" in text

    def test_default_event_names_the_event_from_the_payload_when_unwrapped(self):
        event = default_agent_event({"event": "meeting.started", "payload": {"object": {"topic": "Standup"}}})
        assert event["text"].startswith("Event: meeting.started\n")
        assert json.loads(event["text"].split("\n", 1)[1]) == {"object": {"topic": "Standup"}}

    def test_default_event_does_not_call_a_node_type_an_event(self):
        event = default_agent_event({"type": "webhook-trigger", "payload": {"a": 1}})
        assert json.loads(event["text"]) == {"a": 1}

    def test_display_record_keeps_provider_keys_and_bounds_the_whole(self):
        big = {"type": "slack", "data": {"event": {"text": "hi", "blob": "y" * 30_000}}, "_webhook": {}}
        record = compact_for_display(big)
        assert record["data"]["event"]["text"] == "hi"
        assert "_webhook" not in record
        assert len(json.dumps(record)) <= 24_000

    def test_display_record_that_cannot_be_clipped_keeps_scalars_and_marks_it(self):
        record = compact_for_display({"kind": "x", "items": [{"v": "z" * 100} for _ in range(2000)]})
        assert record["_truncated"] is True and record["kind"] == "x"

    def test_first_line_titles(self):
        assert first_line("\n\n  Issue #4: login broken\nbody") == "Issue #4: login broken"
        assert first_line("x" * 300, limit=10) == "x" * 10

    def test_humanize_slack_markup(self):
        text = "<@U0BOT> hey <@U2|dana> see <https://x.example|the doc> &amp; <#C1|general> <!here> <mailto:a@x.example|a@x.example>"
        assert humanize_slack_markup(text, drop_user_id="U0BOT") == (
            "hey @dana see the doc (https://x.example) & #general @here a@x.example"
        )


def _slack(event, **extra):
    return {
        "type": "slack",
        "action": "on_channel_message",
        "status": "success",
        "event_type": event.get("type"),
        "team_id": "T1",
        "data": {
            "token": "verification-secret",
            "team_id": "T1",
            "api_app_id": "A1",
            "event": event,
            "type": "event_callback",
            "event_id": "Ev1",
            "authorizations": [{"team_id": "T1", "user_id": "U0BOT", "is_bot": True}],
        },
        "timestamp": 1789143296.7,
        **extra,
    }


class TestSlackTurn:
    """The user's 2026-09-12 case: a support desk's bot card edited in
    #crisp-chats reached the agent as the whole Events API envelope."""

    CARD = {
        "subtype": "bot_message",
        "text": "*Chat with a visitor.*\n_Use Slack actions to change details._",
        "username": "Support desk",
        "icons": {"image_48": "https://cdn.example/48.png"},
        "attachments": [
            {
                "id": 1,
                "color": "4A90E3",
                "fallback": "[no preview available]",
                "fields": [
                    {"value": ":flag-ro: Bucharest, Romania", "title": "Location", "short": True},
                    {"value": ":email: <mailto:casey@example.com|casey@example.com>", "title": "Email Address"},
                    {"value": "<https://desk.example/inbox/session_1/|Go to Conversation>", "title": "See Full Conversation"},
                ],
            }
        ],
        "type": "message",
        "bot_id": "B1",
        "app_id": "A9",
        "thread_ts": "1788884081.346399",
        "blocks": [{"type": "rich_text", "block_id": "x"}],
        "ts": "1788884081.631519",
    }

    def test_edited_bot_card_reads_as_its_fields_by_the_picked_label(self):
        event = SlackNode.resolve_agent_event(
            _slack(
                {
                    "type": "message",
                    "subtype": "message_changed",
                    "message": self.CARD,
                    "previous_message": {**self.CARD, "text": "OLD TEXT"},
                    "channel": "C1",
                    "hidden": True,
                    "ts": "1789143280.012600",
                    "event_ts": "1789143280.012600",
                    "channel_type": "channel",
                },
                channel_label="#crisp-chats",
            )
        )
        text = event["text"]
        assert text.splitlines()[0] == (
            "Slack message from Support desk (bot) in #crisp-chats (edited a message) "
            "[channel C1, thread 1788884081.346399]:"
        )
        assert "- Location: :flag-ro: Bucharest, Romania" in text
        assert "- Email Address: :email: casey@example.com" in text
        assert "Go to Conversation (https://desk.example/inbox/session_1/)" in text
        assert text.endswith("To reply, send to channel=C1 with thread_ts=1788884081.346399.")
        for noise in ("verification-secret", "authorizations", "OLD TEXT", "no preview", "rich_text", "image_48"):
            assert noise not in text
        assert len(text) < 600
        assert event["conversation_key"] == "C1:1788884081.346399"
        assert event["title"] == "#crisp-chats"

    def test_app_mention_drops_the_bots_own_mention_and_humanizes_the_rest(self):
        event = SlackNode.resolve_agent_event(
            _slack({"type": "app_mention", "user": "U1", "text": "<@U0BOT> check <https://x.example|the doc> &amp; <#C2|general>", "channel": "C1", "ts": "1.1"})
        )
        assert "check the doc (https://x.example) & #general" in event["text"]
        assert "@U0BOT" not in event["text"]
        assert event["conversation_key"] == "C1:1.1"

    def test_dm_keys_on_the_channel_and_says_dm(self):
        event = SlackNode.resolve_agent_event(
            _slack({"type": "message", "user": "U1", "text": "hi", "channel": "D1", "ts": "2.2", "channel_type": "im"})
        )
        assert event["text"].startswith("Slack message from U1 in DM [channel D1]:\nhi")
        assert event["text"].endswith("To reply, send to channel=D1.")
        assert event["conversation_key"] == "D1" and event["title"] == "DM"

    def test_shared_file_is_named_not_dumped(self):
        event = SlackNode.resolve_agent_event(
            _slack({"type": "message", "subtype": "file_share", "user": "U1", "text": "here", "channel": "C1", "ts": "4.4",
                    "files": [{"id": "F1", "name": "q3.pdf", "title": "Q3 report", "filetype": "pdf", "url_private": "https://files.example/private"}]})
        )
        assert "(shared a file)" in event["text"]
        assert "📎 Q3 report (pdf)" in event["text"]
        assert "url_private" not in event["text"]

    def test_deleted_message_is_one_line(self):
        event = SlackNode.resolve_agent_event(
            _slack({"type": "message", "subtype": "message_deleted", "previous_message": {"user": "U1", "text": "oops"}, "deleted_ts": "5.5", "channel": "C1", "ts": "5.6"})
        )
        assert event["text"] == "Slack: U1 deleted a message in channel C1 (ts 5.5)."

    def test_non_message_events_carry_only_the_events_own_fields(self):
        event = SlackNode.resolve_agent_event(
            _slack({"type": "member_joined_channel", "user": "U1", "channel": "C1", "inviter": "U2", "event_ts": "6.6"})
        )
        assert event["text"].startswith("Slack member_joined_channel in channel C1:")
        body = json.loads(event["text"].split("\n", 1)[1])
        assert body == {"user": "U1", "channel": "C1", "inviter": "U2"}
        assert event["conversation_key"] == "C1"

    def test_no_event_falls_back_to_the_default(self):
        event = SlackNode.resolve_agent_event({"type": "slack", "data": {"something": "else"}})
        assert event["conversation_key"] is None
        assert json.loads(event["text"]) == {"something": "else"}


@pytest.mark.asyncio
async def test_persist_writes_the_trigger_record_on_the_user_event(monkeypatch):
    from types import SimpleNamespace

    from nodes.agent_node import AgentNode

    executed = []

    class FakePool:
        async def execute(self, sql, *args):
            executed.append(args)

    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: FakePool())
    fake = SimpleNamespace(
        user_id="u-1", workflow_id="wf-1", node_id="agent_1",
        _UPSERT_INTERFACE_EVENT_SQL=AgentNode._UPSERT_INTERFACE_EVENT_SQL,
    )
    record = {"node_id": "s1", "node_type": "automation-slack", "label": "Support",
              "operation": "on_channel_message", "output": {"data": {"event": {"text": "hi"}}}}
    await AgentNode._persist_interface_chat_event(
        fake, conversation_id="cid-1", role="user", message="Slack message from U1 in #support:\nhi",
        model="gpt-x", label="#support", trigger=record,
    )
    args = executed[-1]
    [event] = args[4]
    assert event == {"role": "user", "message": "Slack message from U1 in #support:\nhi", "trigger": record}
    assert args[5] == "#support"  # the conversation's title
