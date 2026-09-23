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
