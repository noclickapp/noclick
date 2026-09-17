"""The Phone node: a number the workflow owns. Its trigger routes the number's
calls at the platform, its tool dials out through the platform, and an
instance with neither capability says so."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nodes.agent.node_op_tools import is_trigger_operation, node_supports_op_tools
from nodes.core.registry import NODE_REGISTRY
from nodes.phone_node import PHONE_NUMBER_MONTHLY_CREDITS, PhoneNode
from utils import capabilities
from utils.capabilities import PHONE_CALLS, PHONE_NUMBERS, provide

CRED = {"credential_type": "phone_number", "phone_number": "+15674833618", "number_sid": "PN123"}


@pytest.fixture(autouse=True)
def _own_capabilities():
    saved = dict(capabilities._providers)
    capabilities.clear()
    yield
    capabilities.clear()
    capabilities._providers.update(saved)


def test_registered_as_a_trigger_and_a_tool_provider_with_a_purchase_credential():
    assert NODE_REGISTRY["automation-phone"] is PhoneNode
    assert is_trigger_operation("automation-phone", "on_call")
    assert not is_trigger_operation("automation-phone", "place_call")
    assert node_supports_op_tools("automation-phone")
    schema = PhoneNode.get_config_schema()
    cred = schema["$defs"]["PhoneNumberCredential"]
    assert cred["x-credential-type"] == "purchase"
    assert str(PHONE_NUMBER_MONTHLY_CREDITS) in cred["x-credential-instructions"]
    assert cred["properties"]["number_sid"]["ui:hidden"] is True


async def test_routing_points_the_number_at_the_platform_and_needs_a_provider():
    numbers = MagicMock()
    numbers.route = AsyncMock()
    numbers.unroute = AsyncMock()
    with pytest.raises(RuntimeError, match="cannot route"):
        await PhoneNode._register_external_webhook(webhook_url="https://x", credential=CRED, config={"webhook_id": "wh1"}, node_id="n1")
    provide(PHONE_NUMBERS, numbers)
    extra = await PhoneNode._register_external_webhook(webhook_url="https://x", credential=CRED, config={"webhook_id": "wh1"}, node_id="n1")
    numbers.route.assert_awaited_once_with("PN123", webhook_id="wh1")
    assert extra == {"external_webhook_id": "PN123"}
    with pytest.raises(RuntimeError, match="not provisioned"):
        await PhoneNode._register_external_webhook(webhook_url="https://x", credential=CRED, config={}, node_id="n1")
    await PhoneNode._unregister_external_webhook(credential=None, config={"external_webhook_id": "PN123"}, node_id="n1")
    numbers.unroute.assert_awaited_once_with("PN123")
    assert PhoneNode.verify_webhook_signature(b"", {}, {}) is False  # calls never arrive on the worker webhook URL


def test_a_finished_call_reads_as_one_conversation_per_caller_and_number():
    event = PhoneNode.resolve_agent_event({
        "caller": "+14155550100", "to": "+15674833618",
        "transcript": [{"role": "user", "text": "Hi, is the shop open?"}, {"role": "assistant", "text": "Until six."}],
    })
    assert event["conversation_key"] == "+14155550100:+15674833618" and event["title"] == "Call from +14155550100"
    assert "Caller: Hi, is the shop open?" in event["text"] and "You: Until six." in event["text"]


def _node(op_config):
    from nodes.phone_node import PhoneNodeConfig, PhoneNumberCredential
    node_config = PhoneNodeConfig(config=op_config, credentials=PhoneNumberCredential(**CRED))
    return PhoneNode(node_id="n1", node_type="automation-phone", node_data={}, config=node_config,
                     workflow_id="wf-1", user_id="u1")


async def test_execute_reports_no_event_and_no_outbound_provider_honestly():
    from nodes.phone_node import PhoneOnCallConfig, PhonePlaceCallConfig
    node = _node(PhoneOnCallConfig())
    assert (await node.execute({}))["status"] == "no_event"
    node = _node(PhonePlaceCallConfig(to_number="+14155550100", goal="Confirm the booking"))
    out = await node.execute({})
    assert out["status"] == "error" and "not enabled" in out["error"]
    calls = MagicMock()
    calls.place = AsyncMock(return_value={"status": "completed", "summary": "Booked."})
    provide(PHONE_CALLS, calls)
    assert (await node.execute({}))["summary"] == "Booked."
    assert calls.place.await_args.kwargs["from_number"] == "+15674833618" and calls.place.await_args.kwargs["goal"] == "Confirm the booking"


async def test_get_number_is_the_credentials_proof():
    from nodes.phone_node import PhoneGetNumberConfig
    node = _node(PhoneGetNumberConfig())
    out = await node.execute({})
    assert out["phone_number"] == "+15674833618" and out["active"] is None  # no provider: cannot judge
    numbers = MagicMock(); numbers.exists = AsyncMock(return_value=True)
    provide(PHONE_NUMBERS, numbers)
    assert (await node.execute({}))["active"] is True
    assert PhoneNode.connection_evidence.identity_operation == "get_number"
