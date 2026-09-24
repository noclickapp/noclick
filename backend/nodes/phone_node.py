"""The Phone node: a phone number the workflow owns. Bought inside NoClick
(the ``phone_number`` credential IS the number), it answers calls with the
wired agent as the brain (``on_call``) and dials out for the agent
(``place_call``). Numbers, routing and calls are platform capabilities; an
instance without them says so instead of pretending."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional, Type, Union

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Annotated

from nodes.core.agent_events import phone_call_event
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.call_routing import already_answers, number_holder as _number_holder
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.capabilities import PHONE_CALLS, PHONE_NUMBERS, capability

logger = logging.getLogger(__name__)

PHONE_NUMBER_CREDENTIAL_TYPE = "phone_number"
PHONE_NUMBER_MONTHLY_CREDITS = 15


class PhoneNumberCredential(BaseModel):
    """A phone number your agent answers and calls from."""

    # The blob names the provider's number id; the number itself is public and
    # mirrored into metadata for listings.
    credential_type: Literal["phone_number"] = Field("phone_number", json_schema_extra={"ui:hidden": True})
    phone_number: str = Field(..., min_length=1, json_schema_extra={"ui:hidden": True})  # E.164
    number_sid: str = Field(..., min_length=1, json_schema_extra={"ui:hidden": True})  # provider id

    model_config = ConfigDict(title="Phone Number", json_schema_extra={
        "x-credential-type": "purchase",
        "x-credential-instructions": (
            f"Buy a phone number for this agent, {PHONE_NUMBER_MONTHLY_CREDITS} credits a month (Plus and Pro plans)."
        ),
    })


class PhoneOnCallConfig(WebhookTriggerConfigBase):
    """Trigger: the number is called. The wired agent answers, live."""

    operation: Literal["on_call"] = Field(
        "on_call",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Incoming Call",
            "x-keywords": ["answer calls", "phone call", "voice", "receive call", "inbound call"],
        },
        title="On Incoming Call",
    )
    greeting: Optional[str] = Field(
        None,
        title="Greeting",
        description="What the agent says when it picks up. Leave empty for a plain hello.",
    )
    # The registration marker: loading it provisions the call receiver and
    # routes the attached number at it (the mixin's load_field_value).
    webhook_url: Optional[str] = Field(
        default=None,
        title="Call routing",
        description="Set up automatically once a number is attached: calls to it reach this workflow.",
        json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True, "readOnly": True},
    )


class PhonePlaceCallConfig(BaseModel):
    """Dial a number from this one and hold the whole conversation yourself: the agent behind this tool is the voice on the call and pursues the goal end to end (keypad menus included). Returns at once while the call runs; when it ends, the full transcript arrives in this conversation as a new message — report the outcome then, never redial."""

    operation: Literal["place_call"] = Field(
        "place_call",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Calls",
            "x-is-trigger": False,
            "x-display-name": "Place a Call",
            "x-keywords": ["call", "dial", "phone", "ring", "outbound call"],
        },
        title="Place a Call",
    )
    to_number: str = Field(..., title="To", description="The number to call, in international format (+1…).")
    goal: str = Field(..., title="Goal", description=(
        "What this call should achieve, in plain words — who to ask for, what to find out or arrange, and any "
        "facts the voice may state. Everything the voice knows about the call is in here."
    ))


class PhoneGetNumberConfig(BaseModel):
    """Read-only: the number this credential holds and whether the provider still has it."""

    operation: Literal["get_number"] = Field(
        "get_number",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Number",
            "x-is-trigger": False,
            "x-display-name": "Get Number",
            "x-keywords": ["my number", "phone number", "caller id"],
        },
        title="Get Number",
    )


PhoneConfig = Annotated[
    Union[PhoneOnCallConfig, PhonePlaceCallConfig, PhoneGetNumberConfig], Field(discriminator="operation"),
]


class PhoneNodeConfig(NodeConfig[PhoneConfig, PhoneNumberCredential]):
    pass


class PhoneNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """A phone number the workflow owns: calls in to the wired agent, calls out for it."""

    edit_examples = [
        "Answer calls to my number with this agent",
        "Let the agent call the customer back with the quote",
        "Give the support agent a phone number",
    ]
    # The proof a bought number works IS the number: the provider still lists it.
    connection_evidence = ConnectionEvidence(
        noun="numbers", identity_operation="get_number", identity_keys=("phone_number",),
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type[BaseModel], type]]:
        return PhoneNodeConfig

    # ── routing: the number is pointed at the platform's call receiver ──────
    # The mixin's lifecycle (reconcile on operation/credential change, teardown
    # on trash, nightly resync) owns WHEN; the platform owns WHERE calls go.

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url: str, credential: Dict[str, Any],
                                         config: Dict[str, Any], node_id: str) -> Optional[Dict[str, Any]]:
        numbers = capability(PHONE_NUMBERS)
        if numbers is None:
            raise RuntimeError("This instance cannot route phone calls (no phone number provider is configured)")
        webhook_id = str(config.get("webhook_id") or "")
        if not webhook_id:
            raise RuntimeError("The call receiver is not provisioned yet")
        # One number rings one agent. Routing rewrites the provider's voice
        # webhook, so a second on_call node on the same number used to take
        # every call silently while the first still read "registered".
        holder = await _number_holder(credential["number_sid"], except_webhook_id=webhook_id)
        if holder is not None:
            raise RuntimeError(already_answers(credential.get("phone_number"), holder))
        await numbers.route(credential["number_sid"], webhook_id=webhook_id)
        return {"external_webhook_id": credential["number_sid"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential: Optional[Dict[str, Any]],
                                           config: Dict[str, Any], node_id: str) -> None:
        numbers = capability(PHONE_NUMBERS)
        number_sid = (credential or {}).get("number_sid") or config.get("external_webhook_id")
        if numbers is None or not number_sid:
            return
        await numbers.unroute(str(number_sid))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        # Calls never arrive on the worker's webhook URL: the platform's call
        # receiver answers them and verifies the carrier's signature itself.
        return False

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A finished call, as the wired agent reads it (nodes/core/agent_events)."""
        return phone_call_event(output) or super().resolve_agent_event(output)

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        node_config = self.config
        if not isinstance(node_config, PhoneNodeConfig):
            return {"status": "error", "error": "Invalid phone node configuration"}
        config, credential = node_config.config, node_config.credentials
        if isinstance(config, PhoneOnCallConfig):
            # A real call short-circuits through resolve_trigger_payload; this
            # runs only on manual/test runs, where there is no call.
            return self.no_event_output("On Incoming Call", "Call the number to fire it.")
        if credential is None:
            return {"status": "error", "error": "Attach a phone number first."}
        if isinstance(config, PhoneGetNumberConfig):
            numbers = capability(PHONE_NUMBERS)
            active = await numbers.exists(credential.number_sid) if numbers is not None else None
            return {"status": "success", "phone_number": credential.phone_number, "number_sid": credential.number_sid,
                    "active": active, "name": credential.phone_number}
        calls = capability(PHONE_CALLS)
        if calls is None:
            return {"status": "error", "error": "Outbound calls are not enabled on this instance."}
        return await calls.place(
            user_id=self.user_id, workflow_id=self.workflow_id, node_id=self.node_id,
            credential_id=self.node_data.get("credential_id"),
            from_number=credential.phone_number, number_sid=credential.number_sid,
            to_number=config.to_number, goal=config.goal, conversation_id=self.conversation_id,
        )
