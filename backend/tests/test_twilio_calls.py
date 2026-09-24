"""The Twilio node answers and places live calls on a number the user
brought from their own Twilio account, on the same voice stack as a number
bought inside NoClick: on_call points the number's voice webhook at the
platform's call receiver, place_call dials through PHONE_CALLS with the
account's own credentials."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from nodes.agent.node_op_tools import is_trigger_operation
from nodes.core.agent_events import phone_call_event
from nodes.twilio_node import TWILIO_API_BASE, TwilioNode, TwilioNodeFullConfig
from utils import capabilities
from utils.capabilities import PHONE_CALLS, provide

ACCOUNT = {"credential_type": "twilio_account", "account_sid": "AC" + "1" * 32, "auth_token": "tok"}
API_KEY = {"credential_type": "twilio_api_key", "account_sid": "AC" + "1" * 32, "api_key_sid": "SK" + "1" * 32, "api_key_secret": "s"}


@pytest.fixture(autouse=True)
def _own_capabilities():
    saved = dict(capabilities._providers)
    capabilities.clear()
    yield
    capabilities.clear()
    capabilities._providers.update(saved)


def test_on_call_is_a_trigger_and_place_call_a_tool_with_the_number_picker():
    assert is_trigger_operation("automation-twilio", "on_call")
    assert not is_trigger_operation("automation-twilio", "place_call")
    schema = TwilioNode.get_config_schema()
    on_call, place = schema["$defs"]["TwilioOnCallConfig"], schema["$defs"]["TwilioPlaceCallConfig"]
    assert on_call["x-requires-webhook"] is True and on_call["properties"]["webhook_url"]["ui:widget"] == "webhook"
    assert on_call["properties"]["phone_number_sid"]["x-dynamic-options"]["field_name"] == "phone_number_sid"
    assert place["properties"]["phone_number_sid"]["x-dynamic-options"]["field_name"] == "phone_number_sid"
    assert {"to_number", "goal", "phone_number_sid"} <= set(place["required"])


async def test_on_call_routes_the_number_at_the_platforms_call_receiver(monkeypatch):
    calls = MagicMock(receiver_url=lambda webhook_id: f"https://voice.example.com/voice/incoming/number?webhook_id={webhook_id}")
    monkeypatch.setattr("nodes.twilio_node.number_holder", AsyncMock(return_value=None))
    config = {"operation": "on_call", "phone_number_sid": "PN1", "webhook_id": "wh1"}
    with pytest.raises(RuntimeError, match="cannot take live calls"):
        await TwilioNode._register_external_webhook(webhook_url="https://wh.hooks.example.test/x", credential=ACCOUNT, config=config, node_id="n1")
    provide(PHONE_CALLS, calls)
    with patch("nodes.twilio_node.set_twilio_voice_webhook", new=AsyncMock()) as voice, \
            patch("nodes.twilio_node.set_twilio_sms_webhook", new=AsyncMock()) as sms:
        extra = await TwilioNode._register_external_webhook(webhook_url="https://wh.hooks.example.test/x", credential=ACCOUNT, config=config, node_id="n1")
    voice.assert_awaited_once_with(ACCOUNT["account_sid"], "tok", "PN1", "https://voice.example.com/voice/incoming/number?webhook_id=wh1")
    sms.assert_not_awaited()
    assert extra == {"external_webhook_id": "PN1", "signing_secret": "tok"}
    with pytest.raises(RuntimeError, match="not provisioned"):
        await TwilioNode._register_external_webhook(webhook_url="https://x", credential=ACCOUNT, config={**config, "webhook_id": ""}, node_id="n1")
    with pytest.raises(ValueError, match="Account SID"):
        await TwilioNode._register_external_webhook(webhook_url="https://x", credential=API_KEY, config=config, node_id="n1")
    # One number rings one agent, whichever node holds it.
    monkeypatch.setattr("nodes.twilio_node.number_holder", AsyncMock(return_value='"Support line"'))
    with pytest.raises(RuntimeError, match='already answers calls for "Support line"'):
        await TwilioNode._register_external_webhook(webhook_url="https://x", credential=ACCOUNT, config=config, node_id="n2")
    # Calls never arrive on the worker's webhook URL.
    assert TwilioNode.verify_webhook_signature(b"", {}, {"operation": "on_call", "signing_secret": "tok", "webhook_url": "https://x"}) is False


async def test_teardown_clears_the_voice_webhook_it_set_even_after_the_operation_changed():
    with patch("nodes.twilio_node.set_twilio_voice_webhook", new=AsyncMock()) as voice, \
            patch("nodes.twilio_node.set_twilio_sms_webhook", new=AsyncMock()) as sms:
        await TwilioNode._unregister_external_webhook(credential=ACCOUNT, config={"operation": "send_sms_message", "external_webhook_id": "PN1"}, node_id="n1")
        voice.assert_awaited_once_with(ACCOUNT["account_sid"], "tok", "PN1", "")
        sms.assert_not_awaited()
        await TwilioNode._unregister_external_webhook(credential=ACCOUNT, config={"operation": "on_incoming_sms", "phone_number_sid": "PN1"}, node_id="n1")
        sms.assert_awaited_once_with(ACCOUNT["account_sid"], "tok", "PN1", "")


def _node(config, credentials=ACCOUNT, credential_id="cred-1"):
    node_config = TwilioNodeFullConfig(config=config, credentials=credentials)
    return TwilioNode(node_id="n1", node_type="automation-twilio", node_data={"credential_id": credential_id}, config=node_config,
                      workflow_id="wf-1", user_id="u1")


async def test_on_call_without_a_live_call_says_so():
    node = _node({"operation": "on_call", "phone_number_sid": "PN1"})
    assert (await node.execute({}))["status"] == "no_event"


@respx.mock
async def test_place_call_dials_from_the_users_number_on_their_own_account():
    respx.get(f"{TWILIO_API_BASE}/2010-04-01/Accounts/{ACCOUNT['account_sid']}/IncomingPhoneNumbers/PN1.json").mock(
        return_value=httpx.Response(200, json={"sid": "PN1", "phone_number": "+15674833618"}))
    node = _node({"operation": "place_call", "phone_number_sid": "PN1", "to_number": "+14155550100", "goal": "Confirm the booking"})
    out = await node.execute({})
    assert out["status"] == "error" and "not enabled" in out["error"]
    calls = MagicMock()
    calls.place = AsyncMock(return_value={"status": "calling", "call_sid": "CA1"})
    provide(PHONE_CALLS, calls)
    assert (await node.execute({}))["call_sid"] == "CA1"
    sent = calls.place.await_args.kwargs
    assert sent["from_number"] == "+15674833618" and sent["number_sid"] == "PN1" and sent["to_number"] == "+14155550100"
    assert sent["credential_id"] == "cred-1" and sent["carrier"] == {"account_sid": ACCOUNT["account_sid"], "auth_token": "tok"}
    # An API key cannot verify the call's signed webhooks, so it cannot carry a live call.
    node = _node({"operation": "place_call", "phone_number_sid": "PN1", "to_number": "+14155550100", "goal": "x"}, credentials=API_KEY)
    out = await node.execute({})
    assert out["status"] == "error" and "Auth Token" in out["error"]
    calls.place.assert_awaited_once()


def test_a_finished_call_is_the_agents_event_on_either_node():
    record = {"channel": "phone", "direction": "inbound", "caller": "+14155550100", "to": "+15674833618",
              "transcript": [{"role": "user", "text": "Is the shop open?"}, {"role": "assistant", "text": "Until six."}]}
    event = TwilioNode.resolve_agent_event(record)
    assert event == phone_call_event(record)
    assert event["conversation_key"] == "+14155550100:+15674833618" and event["title"] == "Call from +14155550100"
    assert "Caller: Is the shop open?" in event["text"] and "You: Until six." in event["text"]
    placed = phone_call_event({**record, "direction": "outbound", "caller": "+15674833618", "to": "+14155550100"})
    assert placed["title"] == "Call to +14155550100" and placed["conversation_key"] == "+14155550100:+15674833618"
    assert "They: Is the shop open?" in placed["text"]
    # An SMS is still an SMS.
    sms = TwilioNode.resolve_agent_event({"From": "+15551234567", "To": "+14155238886", "Body": "hi"})
    assert "SMS" in sms["text"]
