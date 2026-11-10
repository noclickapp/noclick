"""RingCentral RingEX calls, SMS, text faxes, call logs and personal contacts.

API contract: https://developers.ringcentral.com/api-reference
Authentication: a pasted OAuth access token (not a JWT assertion). Tokens expire;
users obtain a replacement through their RingCentral app. No sign-in or refresh
flow is performed here. Subscriptions/webhook triggers are not implemented.
"""

import json
import time
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Discriminator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.ringcentral import RINGCENTRAL_SCOPES

API_BASE = "https://platform.ringcentral.com/restapi/v1.0"


class RingCentralAccessTokenCredential(BaseModel):
    credential_type: Literal["ringcentral_access_token"] = Field(
        "ringcentral_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., min_length=1, title="Access Token",
        description="Paste a production RingCentral access token without the Bearer prefix; JWT assertions cannot call the API directly.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(title="Ringcentral Access Token", json_schema_extra={
        "x-oauth-scopes": RINGCENTRAL_SCOPES.declared_scopes(),
        "x-credential-url": "https://developers.ringcentral.com/guide/authentication/tokens",
        "x-credential-instructions": "Paste an access token issued for your production RingCentral app. Access tokens expire; replace this credential when yours expires. The app needs ReadAccounts, ReadCallLog, RingOut, SMS, Faxes, ReadMessages, EditMessages, ReadContacts and Contacts permissions for all operations. A JWT credential must first be exchanged for an access token by your app.",
    })


class RingCentralExtensionConfig(BaseModel):
    account_id: str = Field("~", title="Account ID", description="Use ~ for the authenticated account.")
    extension_id: str = Field("~", title="Extension ID", description="Use ~ for the authenticated extension.")


class RingCentralPageConfig(RingCentralExtensionConfig):
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(100, ge=1, le=1000, title="Page Size", description="Returns one page; use paging and navigation in the output to request more.")


class RingCentralGetExtensionConfig(RingCentralExtensionConfig):
    """Get the extension and account identity."""
    operation: Literal["get_extension"] = Field("get_extension", json_schema_extra={"const": "get_extension", "ui:hidden": True})
    pass


class RingCentralListPhoneNumbersConfig(RingCentralPageConfig):
    """List phone numbers assigned to an extension."""
    operation: Literal["list_phone_numbers"] = Field("list_phone_numbers", json_schema_extra={"const": "list_phone_numbers", "ui:hidden": True})
    pass


class RingCentralListCallLogsConfig(RingCentralPageConfig):
    """List call history for an extension."""
    operation: Literal["list_call_logs"] = Field("list_call_logs", json_schema_extra={"const": "list_call_logs", "ui:hidden": True})
    date_from: str | None = Field(None, title="From", description="ISO 8601 date and time, including timezone.")
    date_to: str | None = Field(None, title="To", description="ISO 8601 date and time, including timezone.")
    direction: Literal["Inbound", "Outbound"] | None = Field(None, title="Direction")
    view: Literal["Simple", "Detailed"] = Field("Detailed", title="View")


class RingCentralGetCallLogConfig(RingCentralExtensionConfig):
    """Get a call log record."""
    operation: Literal["get_call_log"] = Field("get_call_log", json_schema_extra={"const": "get_call_log", "ui:hidden": True})
    call_record_id: str = Field(..., min_length=1, title="Call Record ID")


class RingCentralListActiveCallsConfig(RingCentralPageConfig):
    """List currently active extension calls."""
    operation: Literal["list_active_calls"] = Field("list_active_calls", json_schema_extra={"const": "list_active_calls", "ui:hidden": True})
    pass


class RingCentralCreateRingoutConfig(RingCentralExtensionConfig):
    """Place a two-leg RingOut call."""
    operation: Literal["create_ringout"] = Field("create_ringout", json_schema_extra={"const": "create_ringout", "ui:hidden": True})
    from_number: str = Field(..., min_length=1, title="Call From", description="Phone to ring first, in E.164 format.")
    to_number: str = Field(..., min_length=1, title="Call To", description="Destination phone in E.164 format.")
    play_prompt: bool = Field(True, title="Play Connection Prompt")


class RingCentralGetRingoutConfig(RingCentralExtensionConfig):
    """Get RingOut call status."""
    operation: Literal["get_ringout"] = Field("get_ringout", json_schema_extra={"const": "get_ringout", "ui:hidden": True})
    ringout_id: str = Field(..., min_length=1, title="RingOut ID")


class RingCentralCancelRingoutConfig(RingCentralExtensionConfig):
    """Cancel an active RingOut call."""
    operation: Literal["cancel_ringout"] = Field("cancel_ringout", json_schema_extra={"const": "cancel_ringout", "ui:hidden": True})
    ringout_id: str = Field(..., min_length=1, title="RingOut ID")


class RingCentralSendSmsConfig(RingCentralExtensionConfig):
    """Send an SMS from an SMS-enabled RingCentral number."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"const": "send_sms", "ui:hidden": True})
    from_number: str = Field(..., min_length=1, title="From Number", description="Your SMS-enabled RingCentral number in E.164 format.")
    to_number: str = Field(..., min_length=1, title="To Number", description="Recipient phone in E.164 format.")
    text: str = Field(..., min_length=1, max_length=1000, title="Message", json_schema_extra={"ui:widget": "textarea"})


class RingCentralListMessagesConfig(RingCentralPageConfig):
    """List SMS, fax, voicemail and pager messages."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"const": "list_messages", "ui:hidden": True})
    message_type: Literal["Fax", "SMS", "VoiceMail", "Pager"] | None = Field(None, title="Message Type")
    read_status: Literal["Read", "Unread"] | None = Field(None, title="Read Status")
    date_from: str | None = Field(None, title="From", description="ISO 8601 date and time, including timezone.")
    date_to: str | None = Field(None, title="To", description="ISO 8601 date and time, including timezone.")


class RingCentralGetMessageConfig(RingCentralExtensionConfig):
    """Get a message, including fax status and attachment metadata."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"const": "get_message", "ui:hidden": True})
    message_id: str = Field(..., min_length=1, title="Message ID")


class RingCentralUpdateMessageConfig(RingCentralExtensionConfig):
    """Mark a message read or unread."""
    operation: Literal["update_message"] = Field("update_message", json_schema_extra={"const": "update_message", "ui:hidden": True})
    message_id: str = Field(..., min_length=1, title="Message ID")
    read_status: Literal["Read", "Unread"] = Field(..., title="Read Status")


class RingCentralDeleteMessageConfig(RingCentralExtensionConfig):
    """Delete a message (optionally purge permanently)."""
    operation: Literal["delete_message"] = Field("delete_message", json_schema_extra={"const": "delete_message", "ui:hidden": True})
    message_id: str = Field(..., min_length=1, title="Message ID")
    purge: bool = Field(False, title="Permanently Purge")


class RingCentralListContactsConfig(RingCentralPageConfig):
    """List personal contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"const": "list_contacts", "ui:hidden": True})
    starts_with: str | None = Field(None, title="Starts With", description="Filter contact names by prefix.")


class RingCentralGetContactConfig(RingCentralExtensionConfig):
    """Get a personal contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"const": "get_contact", "ui:hidden": True})
    contact_id: str = Field(..., min_length=1, title="Contact ID")


class RingCentralContactFields(RingCentralExtensionConfig):
    first_name: str | None = Field(None, title="First Name")
    last_name: str | None = Field(None, title="Last Name")
    company: str | None = Field(None, title="Company")
    email: str | None = Field(None, title="Email")
    business_phone: str | None = Field(None, title="Business Phone", description="Phone number in E.164 format.")
    mobile_phone: str | None = Field(None, title="Mobile Phone", description="Phone number in E.164 format.")
    notes: str | None = Field(None, title="Notes")

    @model_validator(mode="after")
    def require_contact_fields(self):
        if not any(getattr(self, key) is not None for key in CONTACT_FIELDS):
            raise ValueError("Supply at least one contact field")
        return self


class RingCentralCreateContactConfig(RingCentralContactFields):
    """Create a personal contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"const": "create_contact", "ui:hidden": True})
    pass


class RingCentralUpdateContactConfig(RingCentralContactFields):
    """Update selected fields of a personal contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"const": "update_contact", "ui:hidden": True})
    contact_id: str = Field(..., min_length=1, title="Contact ID")


class RingCentralDeleteContactConfig(RingCentralExtensionConfig):
    """Delete a personal contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"const": "delete_contact", "ui:hidden": True})
    contact_id: str = Field(..., min_length=1, title="Contact ID")


class RingCentralSendFaxConfig(RingCentralExtensionConfig):
    """Send a text document as a fax."""
    operation: Literal["send_fax"] = Field("send_fax", json_schema_extra={"const": "send_fax", "ui:hidden": True})
    to_number: str = Field(..., min_length=1, title="Fax Number", description="Recipient phone in E.164 format.")
    document_text: str = Field(..., min_length=1, title="Document Text", description="Text sent as a UTF-8 fax.txt attachment.", json_schema_extra={"ui:widget": "textarea"})
    fax_resolution: Literal["High", "Low"] = Field("High", title="Resolution")
    cover_index: int = Field(0, ge=0, le=13, title="Cover Page", description="0 disables the cover page; 1–13 select a RingCentral cover page.")
    cover_page_text: str | None = Field(None, max_length=1024, title="Cover Page Text")


class RingCentralListFaxCoverPagesConfig(BaseModel):
    """List available fax cover pages."""
    operation: Literal["list_fax_cover_pages"] = Field("list_fax_cover_pages", json_schema_extra={"const": "list_fax_cover_pages", "ui:hidden": True})
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(100, ge=1, le=1000, title="Page Size")


RingCentralConfig = Annotated[Union[
    RingCentralGetExtensionConfig,
    RingCentralListPhoneNumbersConfig,
    RingCentralListCallLogsConfig,
    RingCentralGetCallLogConfig,
    RingCentralListActiveCallsConfig,
    RingCentralCreateRingoutConfig,
    RingCentralGetRingoutConfig,
    RingCentralCancelRingoutConfig,
    RingCentralSendSmsConfig,
    RingCentralListMessagesConfig,
    RingCentralGetMessageConfig,
    RingCentralUpdateMessageConfig,
    RingCentralDeleteMessageConfig,
    RingCentralListContactsConfig,
    RingCentralGetContactConfig,
    RingCentralCreateContactConfig,
    RingCentralUpdateContactConfig,
    RingCentralDeleteContactConfig,
    RingCentralSendFaxConfig,
    RingCentralListFaxCoverPagesConfig,
], Discriminator("operation")]


class RingCentralNodeConfig(NodeConfig[RingCentralConfig, RingCentralAccessTokenCredential]):
    pass


CONTACT_FIELDS = {
    "first_name": "firstName", "last_name": "lastName", "company": "company",
    "email": "email", "business_phone": "businessPhone", "mobile_phone": "mobilePhone", "notes": "notes",
}

# Each entry maps to one RingCentral API operation; paths are relative to an extension.
ENDPOINTS = {
    "get_extension": ("GET", ""),
    "list_phone_numbers": ("GET", "/phone-number"),
    "list_call_logs": ("GET", "/call-log"),
    "get_call_log": ("GET", "/call-log/{call_record_id}"),
    "list_active_calls": ("GET", "/active-calls"),
    "create_ringout": ("POST", "/ring-out"),
    "get_ringout": ("GET", "/ring-out/{ringout_id}"),
    "cancel_ringout": ("DELETE", "/ring-out/{ringout_id}"),
    "send_sms": ("POST", "/sms"),
    "list_messages": ("GET", "/message-store"),
    "get_message": ("GET", "/message-store/{message_id}"),
    "update_message": ("PUT", "/message-store/{message_id}"),
    "delete_message": ("DELETE", "/message-store/{message_id}"),
    "list_contacts": ("GET", "/address-book/contact"),
    "get_contact": ("GET", "/address-book/contact/{contact_id}"),
    "create_contact": ("POST", "/address-book/contact"),
    "update_contact": ("PUT", "/address-book/contact/{contact_id}"),
    "delete_contact": ("DELETE", "/address-book/contact/{contact_id}"),
    "send_fax": ("POST", "/fax"),
    "list_fax_cover_pages": ("GET", "/dictionary/fax-cover-page"),
}
QUERY_FIELDS = {
    "page": "page", "per_page": "perPage", "date_from": "dateFrom", "date_to": "dateTo",
    "direction": "direction", "view": "view", "message_type": "messageType",
    "read_status": "readStatus", "starts_with": "startsWith", "purge": "purge",
}


class RingCentralNode(WorkflowNode):
    integration_type = "automation-ringcentral"
    credential_provider_labels = {"ringcentral": "Ringcentral Account"}
    scope_registry = RINGCENTRAL_SCOPES
    connection_evidence = ConnectionEvidence(
        identity_operation="get_extension", noun="RingCentral extension", identity_keys=("name",),
    )
    edit_examples = [
        "Send an SMS when a lead submits a form",
        "List missed calls from yesterday",
        "Create a personal contact from a CRM record",
        "Send a text document by fax and check its delivery status",
    ]

    @classmethod
    def get_config_model(cls):
        return RingCentralNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, RingCentralNodeConfig):
            raise ValueError("Valid RingCentral configuration is required")
        if not self.config.credentials:
            raise ValueError("Credentials are required. Add your RingCentral access token.")
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        action = config.operation
        method, suffix = ENDPOINTS[action]
        path_values = {key: quote(str(value), safe="") for key, value in values.items()}
        suffix = suffix.format(**path_values)
        endpoint = suffix if action == "list_fax_cover_pages" else (
            f"/account/{path_values['account_id']}/extension/{path_values['extension_id']}{suffix}"
        )
        params = {wire: values[key] for key, wire in QUERY_FIELDS.items() if key in values}
        body = None
        files = None
        if action in {"create_ringout", "send_sms"}:
            body = {"from": {"phoneNumber": config.from_number}, "to": {"phoneNumber": config.to_number}}
            if action == "send_sms":
                body["to"] = [body["to"]]
                body["text"] = config.text
            else:
                body["playPrompt"] = config.play_prompt
        elif action in {"create_contact", "update_contact"}:
            body = {wire: values[key] for key, wire in CONTACT_FIELDS.items() if key in values}
        elif action == "update_message":
            params = {}
            body = {"readStatus": config.read_status}
        elif action == "send_fax":
            # RingCentral's sending-faxes guide uses a JSON metadata file part.
            metadata = {
                "to": [{"phoneNumber": config.to_number}],
                "faxResolution": config.fax_resolution,
                "coverIndex": config.cover_index,
            }
            if config.cover_page_text is not None:
                metadata["coverPageText"] = config.cover_page_text
            files = {
                "json": ("request.json", json.dumps(metadata), "application/json"),
                "attachment": ("fax.txt", config.document_text.encode("utf-8"), "text/plain"),
            }
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self.config.credentials.access_token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(method, API_BASE + endpoint, headers=headers, params=params, json=body, files=files)
        except httpx.HTTPError:
            return {"status": "error", "action": action, "error": "Could not reach the RingCentral API"}
        elapsed = round((time.monotonic() - started) * 1000, 2)
        result = {"action": action, "status_code": response.status_code, "timing_ms": {"api_request": elapsed}}
        if not 200 <= response.status_code < 300:
            # Error bodies and exception text can echo credentials and message content.
            return {**result, "status": "error", "error": f"RingCentral API request failed (HTTP {response.status_code})"}
        if response.status_code == 204:
            data = {}
        else:
            try:
                data = response.json()
            except ValueError:
                data = None
            if not isinstance(data, dict) or not data or data.get("errorCode") or data.get("error"):
                return {**result, "status": "error", "error": "RingCentral returned an invalid JSON response"}
        if action == "get_extension" and (
            not data.get("id") or not isinstance(data.get("name"), str) or not data["name"].strip()
        ):
            return {**result, "status": "error", "error": "RingCentral returned no extension identity"}
        return {**result, "status": "success", "data": data}
