"""WildJar API v2 fixed operations, checked against its published Postman examples.

Bearer tokens are supplied by the person connecting. Lists return one provider-default
page (normally 100 records); no output claims a complete export or SMS delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.trkcall.com/v2"
ResourceID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]


class WildJarTokenCredential(BaseModel):
    model_config = ConfigDict(title="WildJar Access Token", hide_input_in_errors=True, extra="ignore",
        json_schema_extra={
            "x-credential-url": "https://developer.wildjar.com/",
            "x-credential-instructions": "Paste an existing WildJar access token, without the Bearer prefix. WildJar documents obtaining tokens using your username and password at /v2/token/. Tokens expire (normally after one hour); replace this token when it expires. NoClick does not request or renew tokens. Listing your accounts proves read access; it does not prove write permissions.",
        })
    credential_type: Literal["wildjar_access_token"] = Field("wildjar_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def validate_token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError("Paste the access token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListAccountsConfig(_Input):
    """List accounts."""
    operation: Literal["list_accounts"] = Field("list_accounts", title="List accounts", json_schema_extra={"ui:hidden": True})


class GetOutboundCallConfig(_Input):
    """Show outbound call details."""
    operation: Literal["get_outbound_call"] = Field("get_outbound_call", title="Show outbound call details", json_schema_extra={"ui:hidden": True})
    call_uuid: ResourceID = Field(..., title="Call Uuid")


class ListNumbersConfig(_Input):
    """List active tracking numbers."""
    operation: Literal["list_numbers"] = Field("list_numbers", title="List active tracking numbers", json_schema_extra={"ui:hidden": True})


class GetNumberConfig(_Input):
    """Show tracking number details."""
    operation: Literal["get_number"] = Field("get_number", title="Show tracking number details", json_schema_extra={"ui:hidden": True})
    tracking_number: ResourceID = Field(..., title="Tracking Number")


class ListInboundSmsConfig(_Input):
    """List inbound SMS messages."""
    operation: Literal["list_inbound_sms"] = Field("list_inbound_sms", title="List inbound SMS messages", json_schema_extra={"ui:hidden": True})


class ListSmsInboxConfig(_Input):
    """List full SMS inbox (inbound/outbound)."""
    operation: Literal["list_sms_inbox"] = Field("list_sms_inbox", title="List full SMS inbox (inbound/outbound)", json_schema_extra={"ui:hidden": True})


class SendSmsConfig(_Input):
    """Send a single SMS."""
    operation: Literal["send_sms"] = Field("send_sms", title="Send a single SMS", json_schema_extra={"ui:hidden": True})
    account: ResourceID
    sender: str = Field(..., pattern=r"[0-9]{6,15}", description="Sending tracking number in international format without plus.")
    target: str = Field(..., pattern=r"[0-9]{6,15}", description="Recipient in international format without plus.")
    content: str = Field(..., min_length=1, max_length=10000)


class ListTransfersConfig(_Input):
    """List transfers in an account."""
    operation: Literal["list_transfers"] = Field("list_transfers", title="List transfers in an account", json_schema_extra={"ui:hidden": True})
    account_id: ResourceID = Field(..., title="Account Id")


class GetTransferConfig(_Input):
    """Show detailed transfer routing."""
    operation: Literal["get_transfer"] = Field("get_transfer", title="Show detailed transfer routing", json_schema_extra={"ui:hidden": True})
    account_id: ResourceID = Field(..., title="Account Id")
    action_id: ResourceID = Field(..., title="Action Id")


class CreateTransferConfig(_Input):
    """Create transfer."""
    operation: Literal["create_transfer"] = Field("create_transfer", title="Create transfer", json_schema_extra={"ui:hidden": True})
    account_id: ResourceID = Field(..., title="Account Id")
    name: str = Field(..., min_length=1, max_length=200)
    target: str = Field(..., pattern=r"[+][0-9]{6,15}")
    timeout: int = Field(25, ge=1, le=3600)
    next_action: Literal["hangup", "voicemail", "transfer", "ivr"] | None = None
    next_action_id: ResourceID | None = None
    record: Literal["yes", "no"] = "no"
    recording: str | None = Field(None, max_length=2048, description="Provider preamble audio URL; NoClick does not fetch this URL.")
    whisper: str | None = Field(None, max_length=1000)
    force_caller: str | None = Field(None, max_length=32)
    notify: Literal["yes", "no", "missed"] = "no"
    group_id: ResourceID | None = None


class UpdateTransferConfig(_Input):
    """Update transfer."""
    operation: Literal["update_transfer"] = Field("update_transfer", title="Update transfer", json_schema_extra={"ui:hidden": True})
    account_id: ResourceID = Field(..., title="Account Id")
    action_id: ResourceID = Field(..., title="Action Id")
    name: str = Field(..., min_length=1, max_length=200)
    target: str = Field(..., pattern=r"[+][0-9]{6,15}")
    timeout: int = Field(25, ge=1, le=3600)
    next_action: Literal["hangup", "voicemail", "transfer", "ivr"] | None = None
    next_action_id: ResourceID | None = None
    record: Literal["yes", "no"] = "no"
    recording: str | None = Field(None, max_length=2048, description="Provider preamble audio URL; NoClick does not fetch this URL.")
    whisper: str | None = Field(None, max_length=1000)
    force_caller: str | None = Field(None, max_length=32)
    notify: Literal["yes", "no", "missed"] = "no"
    group_id: ResourceID | None = None


class ListVoicemailsConfig(_Input):
    """List voicemail actions in an account."""
    operation: Literal["list_voicemails"] = Field("list_voicemails", title="List voicemail actions in an account", json_schema_extra={"ui:hidden": True})
    account_id: ResourceID = Field(..., title="Account Id")


class GetVoicemailConfig(_Input):
    """Show detailed voicemail action configuration."""
    operation: Literal["get_voicemail"] = Field("get_voicemail", title="Show detailed voicemail action configuration", json_schema_extra={"ui:hidden": True})
    account_id: ResourceID = Field(..., title="Account Id")
    action_id: ResourceID = Field(..., title="Action Id")


class ListDniConfig(_Input):
    """List DNI configurations."""
    operation: Literal["list_dni"] = Field("list_dni", title="List DNI configurations", json_schema_extra={"ui:hidden": True})


class ListIvrsConfig(_Input):
    """List IVRs in an account."""
    operation: Literal["list_ivrs"] = Field("list_ivrs", title="List IVRs in an account", json_schema_extra={"ui:hidden": True})
    account_id: ResourceID = Field(..., title="Account Id")


class GetIvrConfig(_Input):
    """Show detailed IVR routing."""
    operation: Literal["get_ivr"] = Field("get_ivr", title="Show detailed IVR routing", json_schema_extra={"ui:hidden": True})
    account_id: ResourceID = Field(..., title="Account Id")
    action_id: ResourceID = Field(..., title="Action Id")


class CreateSmsContactListConfig(_Input):
    """Create an SMS contact list."""
    operation: Literal["create_sms_contact_list"] = Field("create_sms_contact_list", title="Create an SMS contact list", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=200)
    account: ResourceID
    contacts: list[Annotated[str, StringConstraints(pattern=r"^[0-9]{6,15}$")]] = Field(..., min_length=1, max_length=2000)


class UpdateSmsContactListConfig(_Input):
    """Update an SMS contact list."""
    operation: Literal["update_sms_contact_list"] = Field("update_sms_contact_list", title="Update an SMS contact list", json_schema_extra={"ui:hidden": True})
    contact_list_id: ResourceID = Field(..., title="Contact List Id")
    name: str = Field(..., min_length=1, max_length=200)
    account: ResourceID
    contacts: list[Annotated[str, StringConstraints(pattern=r"^[0-9]{6,15}$")]] = Field(..., min_length=1, max_length=2000)

WildJarConfig = Annotated[Union[ListAccountsConfig, GetOutboundCallConfig, ListNumbersConfig, GetNumberConfig, ListInboundSmsConfig, ListSmsInboxConfig, SendSmsConfig, ListTransfersConfig, GetTransferConfig, CreateTransferConfig, UpdateTransferConfig, ListVoicemailsConfig, GetVoicemailConfig, ListDniConfig, ListIvrsConfig, GetIvrConfig, CreateSmsContactListConfig, UpdateSmsContactListConfig], Field(discriminator="operation")]


class WildJarFullConfig(NodeConfig[WildJarConfig, WildJarTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'list_accounts': ('GET', '/account/'), 'get_outbound_call': ('GET', '/call/outbound/{call_uuid}'), 'list_numbers': ('GET', '/number/'), 'get_number': ('GET', '/number/{tracking_number}'), 'list_inbound_sms': ('GET', '/sms/'), 'list_sms_inbox': ('GET', '/sms/mix/'), 'send_sms': ('PUT', '/sms/send'), 'list_transfers': ('GET', '/routing/{account_id}/transfer'), 'get_transfer': ('GET', '/routing/{account_id}/transfer/{action_id}'), 'create_transfer': ('PUT', '/routing/{account_id}/transfer/'), 'update_transfer': ('POST', '/routing/{account_id}/transfer/{action_id}'), 'list_voicemails': ('GET', '/routing/{account_id}/voicemail'), 'get_voicemail': ('GET', '/routing/{account_id}/voicemail/{action_id}'), 'list_dni': ('GET', '/web/'), 'list_ivrs': ('GET', '/routing/{account_id}/ivr'), 'get_ivr': ('GET', '/routing/{account_id}/ivr/{action_id}'), 'create_sms_contact_list': ('PUT', '/sms/list/'), 'update_sms_contact_list': ('POST', '/sms/list/{contact_list_id}')}


class WildJarNode(WorkflowNode):
    integration_type = "automation-wildjar"
    connection_evidence = ConnectionEvidence(noun="accounts", operation="list_accounts", label_keys=("name", "id"))
    edit_examples = ["Get a tracking number", "Read an outbound call", "Send an SMS from a tracking number"]

    @classmethod
    def get_config_model(cls):
        return WildJarFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a WildJar access token")
        op = self.config.config
        method, template = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = template.format(**values)
        body = None
        if op.operation in {"send_sms", "create_sms_contact_list", "update_sms_contact_list"}:
            body = {k: v for k, v in values.items() if k != "contact_list_id"}
        elif op.operation in {"create_transfer", "update_transfer"}:
            keys = {"next_action": "nextAction", "next_action_id": "nextActionId", "force_caller": "forceCaller", "group_id": "groupId"}
            body = {keys.get(k, k): str(v) if k == "timeout" else v for k, v in values.items() if k not in {"account_id", "action_id"}}
        # The collection's primary Send a single SMS request explicitly declares
        # application/javascript, even though its saved original uses application/json.
        headers = {"Accept": "application/json"}
        if op.operation == "send_sms":
            headers["Content-Type"] = "application/javascript"
        token = self.config.credentials.access_token
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, headers={**headers, "Authorization": "Bearer " + token}, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("WildJar request could not be completed; inspect writes before retrying") from None
        if not response.is_success:
            # Preserve the provider's rejection text while withholding our token.
            try:
                error = response.json()
                message = error.get("message") or error.get("error")
            except (ValueError, AttributeError):
                message = None
            detail = str(message).replace(token, "[redacted]")[:1000] if message else "Request rejected"
            raise ValueError(f"WildJar HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("WildJar returned an invalid JSON response; inspect writes before retrying") from None
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            message = payload.get("message", payload.get("error", "Unexpected response status")) if isinstance(payload, dict) else "Unexpected response shape"
            raise ValueError("WildJar: " + str(message).replace(token, "[redacted]")[:1000])
        data = payload.get("data")
        listing = op.operation.startswith("list_")
        if not isinstance(data, list if listing else dict) or (listing and any(not isinstance(row, dict) for row in data)):
            raise ValueError("WildJar returned an unexpected data envelope; inspect writes before retrying")
        identity = {"get_outbound_call": ("uuid", "call_uuid"), "get_number": ("did", "tracking_number"), "get_transfer": ("id", "action_id"), "get_voicemail": ("id", "action_id"), "update_transfer": ("id", "action_id"), "get_ivr": ("id", "action_id"), "update_sms_contact_list": ("uuid", "contact_list_id")}.get(op.operation)
        if identity and str(data.get(identity[0])) != values[identity[1]]:
            raise ValueError("WildJar returned a different resource; inspect writes before retrying")
        if "account_id" in values:
            rows = data if listing else [data]
            if any(str(row.get("account")) != values["account_id"] for row in rows):
                raise ValueError("WildJar returned data for a different account; inspect writes before retrying")
        if op.operation in {"create_sms_contact_list", "update_sms_contact_list"} and str(data.get("account")) != values["account"]:
            raise ValueError("WildJar returned data for a different account; inspect writes before retrying")
        if method != "GET":
            identifier = "id" if op.operation in {"create_transfer", "update_transfer"} else "uuid"
            if not isinstance(data.get(identifier), str) or not data[identifier]:
                raise ValueError("WildJar returned no write identifier; inspect writes before retrying")
        def redact(value):
            if isinstance(value, str):
                return value.replace(token, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items()}
            return value
        output = {"status": "success", "data": redact(data), "http_status": response.status_code}
        if listing:
            output.update({"complete": False, "page_scope": "provider_default_page"})
            for key in ("recordsTotal", "recordsFiltered"):
                if key in payload:
                    output[key] = payload[key]
        if method != "GET":
            output.update({"write_acknowledged": True, "readback_verified": False})
        if op.operation == "send_sms":
            output["delivery_verified"] = False
        await self.emit(output)
        return output
