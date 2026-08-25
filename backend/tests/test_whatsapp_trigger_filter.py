"""Tests for the WhatsApp trigger → agent seam: filter_trigger_payload (WAHooks
event filtering) and resolve_agent_event (fired message → agent turn + reply id).

A QR-linked personal WhatsApp receives EVERY WhatsApp Web event as a "message"
webhook: contact stories (status@broadcast), Channel posts (@newsletter), group
chats (@g.us), and the account's own outgoing messages (fromMe). An auto-reply
workflow wired to receive_message must only fire on real inbound DMs, plus
groups when explicitly enabled, or unrelated events can trigger replies.

resolve_agent_event surfaces the sender's chat id VERBATIM so a channel agent
replies to the right chat. Reconstructing a destination from unrelated payload
fields can address a nonexistent account and leave delivery pending.
"""
import sys

sys.path.insert(0, "backend")

from nodes.whatsapp_node import WhatsAppNode, WhatsAppSendTextConfig

RECEIVE = {"operation": "receive_message"}


def _wahooks_event(chat_id, *, from_me=False, remote_jid=None, participant=""):
    """Minimal WAHooks 'message' envelope as delivered to the webhook."""
    return {
        "event": "message",
        "payload": {
            "from": chat_id,
            "fromMe": from_me,
            "body": "hello",
            "_data": {
                "key": {
                    "fromMe": from_me,
                    "remoteJid": remote_jid if remote_jid is not None else chat_id,
                    "participant": participant,
                    "remoteJidAlt": "12025550104@s.whatsapp.net",
                }
            },
        },
    }


# ── Events that must fire ──────────────────────────────────────────────────────

def test_direct_message_fires():
    assert WhatsAppNode.filter_trigger_payload(_wahooks_event("12025550102@lid"), RECEIVE) is True

def test_direct_message_c_us_fires():
    assert WhatsAppNode.filter_trigger_payload(_wahooks_event("12025550101@c.us"), RECEIVE) is True

def test_group_message_fires_when_opted_in():
    config = {**RECEIVE, "include_group_messages": "true"}
    assert WhatsAppNode.filter_trigger_payload(_wahooks_event("120000000000000001@g.us"), config) is True


# ── Events that must be dropped ────────────────────────────────────────────────

def test_story_status_broadcast_dropped():
    """Contact stories arrive as messages on status@broadcast — never fire."""
    event = _wahooks_event("status@broadcast", participant="12025550103@lid")
    assert WhatsAppNode.filter_trigger_payload(event, RECEIVE) is False

def test_newsletter_channel_post_dropped():
    assert WhatsAppNode.filter_trigger_payload(_wahooks_event("120000000000000002@newsletter"), RECEIVE) is False

def test_own_outgoing_message_dropped():
    """fromMe events are the bot's own sends — firing on them is a self-loop."""
    event = _wahooks_event("12025550102@lid", from_me=True)
    assert WhatsAppNode.filter_trigger_payload(event, RECEIVE) is False

def test_own_message_dropped_when_only_key_flag_set():
    event = _wahooks_event("12025550102@lid")
    event["payload"]["fromMe"] = False
    event["payload"]["_data"]["key"]["fromMe"] = True
    assert WhatsAppNode.filter_trigger_payload(event, RECEIVE) is False

def test_group_message_dropped_by_default():
    assert WhatsAppNode.filter_trigger_payload(_wahooks_event("120000000000000001@g.us"), RECEIVE) is False

def test_group_message_dropped_when_toggle_explicitly_false():
    config = {**RECEIVE, "include_group_messages": "false"}
    assert WhatsAppNode.filter_trigger_payload(_wahooks_event("120000000000000001@g.us"), config) is False


# ── Envelopes/operations the filter must not touch ─────────────────────────────

def test_meta_cloud_api_payload_passes_through():
    """Cloud API deliveries use a different envelope — no WAHooks filtering."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"messages": [{"from": "1234", "text": {"body": "hi"}}]}}]}],
    }
    assert WhatsAppNode.filter_trigger_payload(payload, RECEIVE) is True

def test_non_message_wahooks_envelope_never_fires_a_run():
    # Real WAHooks envelopes carry event+session. Control-plane events
    # (session.status, …) are consumed by handle_control_event upstream; the
    # filter is the belt under those braces — they must never execute the
    # workflow as a ghost trigger now that webhooks subscribe to them.
    payload = {
        "event": "session.status",
        "session": "u_abc_s_def",
        "payload": {"status": "FAILED"},
    }
    assert WhatsAppNode.filter_trigger_payload(payload, RECEIVE) is False


def test_non_wahooks_shapes_still_pass_through():
    # Meta Cloud API envelopes (no event/session keys) keep passing through.
    payload = {"object": "whatsapp_business_account", "entry": []}
    assert WhatsAppNode.filter_trigger_payload(payload, RECEIVE) is True

def test_other_operations_unfiltered():
    event = _wahooks_event("status@broadcast")
    assert WhatsAppNode.filter_trigger_payload(event, {"operation": "receive_status_update"}) is True

def test_missing_from_falls_back_to_remote_jid():
    event = _wahooks_event("ignored@lid", remote_jid="status@broadcast")
    del event["payload"]["from"]
    assert WhatsAppNode.filter_trigger_payload(event, RECEIVE) is False


# ── Fire budget channel key ────────────────────────────────────────────────────

def test_fire_budget_channel_is_chat_id():
    event = _wahooks_event("12025550102@lid")
    assert WhatsAppNode.trigger_fire_budget_channel(event, RECEIVE) == "12025550102@lid"

def test_fire_budget_channel_none_for_other_operations():
    event = _wahooks_event("12025550102@lid")
    assert WhatsAppNode.trigger_fire_budget_channel(event, {"operation": "send_text_message"}) is None

def test_fire_budget_channel_none_for_cloud_api_envelope():
    payload = {"object": "whatsapp_business_account", "entry": []}
    assert WhatsAppNode.trigger_fire_budget_channel(payload, RECEIVE) is None


# ── resolve_agent_event: fired message → agent turn + reply id ─────────────────

def test_resolve_agent_event_surfaces_chat_id_verbatim():
    event = _wahooks_event("12025550101@c.us")
    event["payload"]["body"] = "Hey, how are you?"
    resolved = WhatsAppNode.resolve_agent_event(event)
    assert resolved is not None
    # Reply id = sender chat id, kept verbatim (with @c.us so to_chat_id no-ops it).
    assert resolved["conversation_key"] == "12025550101@c.us"
    assert "12025550101@c.us" in resolved["text"]
    assert "Hey, how are you?" in resolved["text"]


def test_resolve_agent_event_lid_chat_id_preserved():
    resolved = WhatsAppNode.resolve_agent_event(_wahooks_event("12025550102@lid"))
    assert resolved["conversation_key"] == "12025550102@lid"
    assert "12025550102@lid" in resolved["text"]


def test_resolve_agent_event_reply_hint_uses_chat_id_not_a_phone_number():
    """The regression guard: the event must tell the agent to reply with the
    chat id verbatim (to=<chat_id>), never a reconstructed phone number."""
    text = WhatsAppNode.resolve_agent_event(_wahooks_event("12025550101@c.us"))["text"]
    assert "to=12025550101@c.us" in text


def test_resolve_agent_event_falls_back_to_remote_jid():
    event = _wahooks_event("ignored", remote_jid="12025550101@c.us")
    del event["payload"]["from"]
    resolved = WhatsAppNode.resolve_agent_event(event)
    assert resolved["conversation_key"] == "12025550101@c.us"


def test_resolve_agent_event_group_names_participant():
    event = _wahooks_event("120000000000000001@g.us", participant="12025550101@c.us")
    resolved = WhatsAppNode.resolve_agent_event(event)
    # Reply to the group; the actual human sender is named in the text.
    assert resolved["conversation_key"] == "120000000000000001@g.us"
    assert "12025550101@c.us" in resolved["text"]


def test_resolve_agent_event_cloud_api_envelope():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"messages": [{"from": "12025550106", "text": {"body": "hi"}}]}}]}],
    }
    resolved = WhatsAppNode.resolve_agent_event(payload)
    assert resolved["conversation_key"] == "12025550106"
    assert "hi" in resolved["text"]
    assert "to=12025550106" in resolved["text"]


def test_resolve_agent_event_unknown_shape_falls_back_to_raw_json():
    payload = {"event": "session.status", "payload": {"status": "connected"}}
    resolved = WhatsAppNode.resolve_agent_event(payload)
    assert resolved["conversation_key"] is None  # base default
    assert "session.status" in resolved["text"]


# ── Layer 2: the send recipient field no longer nudges E.164 reconstruction ────

def test_send_to_field_description_prefers_verbatim_chat_id():
    desc = WhatsAppSendTextConfig.model_fields["to"].description
    assert "EXACTLY" in desc  # echo the trigger's chat id, don't reformat it
    # chat-id guidance leads; the E.164 fallback still exists for new chats.
    assert desc.index("chat ID") < desc.index("E.164")


def test_over_trigger_fire_budget_wiring():
    """_over_trigger_fire_budget suppresses only channel-keyed nodes over budget."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from nodes.core.base import WorkflowNode
    from utils.webhook_routes import _over_trigger_fire_budget

    node = {"id": "whatsapp_1", "type": "automation-whatsapp", "config": RECEIVE}
    event = _wahooks_event("12025550102@lid")

    async def run():
        with patch("utils.fire_budget.over_fire_budget", new=AsyncMock(return_value=True)) as m:
            # Channel-keyed node over budget → suppressed
            assert await _over_trigger_fire_budget(WhatsAppNode, node, event, "wf1") is True
            m.assert_awaited_once_with("wf1", "whatsapp_1", "12025550102@lid")
            m.reset_mock()
            # Base nodes return no channel → budget never consulted
            assert await _over_trigger_fire_budget(WorkflowNode, node, event, "wf1") is False
            m.assert_not_awaited()
        with patch("utils.fire_budget.over_fire_budget", new=AsyncMock(return_value=False)):
            assert await _over_trigger_fire_budget(WhatsAppNode, node, event, "wf1") is False

    asyncio.run(run())
