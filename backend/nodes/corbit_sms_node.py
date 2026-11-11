"""Corbit SMS/Gateway API, pinned to the provider's published Postman collection.

SMS tokens from sms.corbit.sa cover these endpoints. WhatsApp uses a different
key and is deliberately a separate product. No automatic retries of SMS writes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.corbit.sa"


class CorbitSMSCredential(BaseModel):
    model_config = ConfigDict(title="Corbit SMS API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://sms.corbit.sa",
            "x-credential-instructions": "Paste the API token created in your Corbit SMS account at sms.corbit.sa. Use the SMS token, not a WhatsApp API key. NoClick sends it as a Bearer token to api.corbit.sa.",
        })
    credential_type: Literal["corbit_sms_api_token"] = Field("corbit_sms_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class SendOptions(Operation):
    sender_name: str = Field(..., title="Approved Sender Name", min_length=1, max_length=100)
    idempotency_key: Optional[str] = Field(None, title="Idempotency Key", min_length=1, max_length=255,
        description="Reuse the same key only when retrying the same request, to avoid sending twice.")

    @field_validator("idempotency_key")
    @classmethod
    def header(cls, value):
        if value is not None and (not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use a printable ASCII idempotency key")
        return value


Phone = Annotated[str, Field(pattern=r"^[0-9]{8,15}$")]


class SendSMS(SendOptions):
    """Send a single SMS with duplicate protection enabled by default."""
    operation: Literal["send_sms"] = "send_sms"
    number: Phone = Field(..., title="Recipient Number", description="International format, 8–15 digits, without +.")
    message_body: str = Field(..., title="Message", min_length=1, max_length=1600)
    send_at_option: Literal["NOW"] = Field("NOW", title="Delivery Timing")
    allow_duplicate: bool = Field(False, title="Allow Duplicate", description="Explicitly allow an identical SMS within the one-hour duplicate window.")


class SendBulkSMS(SendOptions):
    """Send the same SMS to multiple numbers."""
    operation: Literal["send_bulk_sms"] = "send_bulk_sms"
    numbers: list[Phone] = Field(..., title="Recipient Numbers", min_length=1)
    message_body: str = Field(..., title="Message", min_length=1, max_length=1600)
    send_at_option: Literal["Now"] = Field("Now", title="Delivery Timing")
    allow_duplicate: bool = Field(False, title="Allow Duplicate")


class GetBalance(Operation):
    """Read the account's remaining SMS balance."""
    operation: Literal["get_balance"] = "get_balance"


class ListSenderNames(Operation):
    """List the account's sender names and their approval status."""
    operation: Literal["list_sender_names"] = "list_sender_names"


class MessageID(Operation):
    message_id: str = Field(..., title="Message ID", min_length=1, max_length=255)


class GetMessageStatus(MessageID):
    """Read the current status of an accepted SMS."""
    operation: Literal["get_message_status"] = "get_message_status"


class GetMessageReport(MessageID):
    """Read delivery details for each destination."""
    operation: Literal["get_message_report"] = "get_message_report"


class ListTemplates(Operation):
    """List the account's saved message templates."""
    operation: Literal["list_templates"] = "list_templates"


class TemplateName(Operation):
    name: str = Field(..., title="Template Name", pattern=r"^[A-Za-z0-9_.-]{1,64}$")


class SaveTemplate(TemplateName):
    """Create or replace a template with merge fields."""
    operation: Literal["save_template"] = "save_template"
    text: str = Field(..., title="Template Text", min_length=1, max_length=1600,
        description="Use Corbit merge fields such as {{name}} or {{code|0000}}.")


class GetTemplate(TemplateName):
    """Read a saved template."""
    operation: Literal["get_template"] = "get_template"


class DeleteTemplate(TemplateName):
    """Delete a saved template."""
    operation: Literal["delete_template"] = "delete_template"


class Recipient(BaseModel):
    number: Phone
    vars: dict[str, str] = Field(default_factory=dict, title="Merge Values")


class SendTemplate(SendOptions):
    """Send a saved template with shared and per-recipient merge values."""
    operation: Literal["send_template"] = "send_template"
    template: str = Field(..., title="Saved Template", pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    vars: dict[str, str] = Field(default_factory=dict, title="Shared Merge Values")
    recipients: list[Union[Phone, Recipient]] = Field(..., title="Recipients", min_length=1, max_length=1000)


class GetUsage(Operation):
    """Read rate limits and last known balance."""
    operation: Literal["get_usage"] = "get_usage"


class ArchiveFilters(Operation):
    from_time: Optional[str] = Field(None, title="From", description="Oldest date: YYYY-MM-DD, ISO date-time, or epoch seconds.")
    to_time: Optional[str] = Field(None, title="To", description="Newest date; a bare date includes that entire day.")
    number: Optional[str] = Field(None, title="Destination Filter", description="A number or a piece of it.")
    sender: Optional[str] = Field(None, title="Sender Filter")
    include_status: bool = Field(False, title="Include Delivery Status")

    @field_validator("from_time", "to_time")
    @classmethod
    def date(cls, value):
        if value is not None:
            try:
                if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Use an ISO date/date-time or epoch seconds") from None
        return value


class ListMessages(ArchiveFilters):
    """Read a page of the sent-message archive, newest first."""
    operation: Literal["list_messages"] = "list_messages"
    limit: int = Field(50, title="Page Size", ge=1, le=200)
    cursor: Optional[str] = Field(None, title="Cursor", description="nextCursor from the preceding page. Continue even when a filtered page is short.")


class OnNewSentMessage(PollTriggerConfigBase, ArchiveFilters):
    """Poll the date-filtered sent archive; emits new records after an initial baseline."""
    operation: Literal["on_new_sent_message"] = Field("on_new_sent_message", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On New Sent Message"})


CorbitSMSConfig = Annotated[Union[SendSMS, SendBulkSMS, GetBalance, ListSenderNames,
    GetMessageStatus, GetMessageReport, ListTemplates, SaveTemplate, GetTemplate,
    DeleteTemplate, SendTemplate, GetUsage, ListMessages, OnNewSentMessage], Field(discriminator="operation")]


class CorbitSMSNodeConfig(NodeConfig[CorbitSMSConfig, CorbitSMSCredential]):
    pass


# One operation maps to one published request; the poll uses the archive request.
ROUTES = {
    "send_sms": ("POST", "/api/v1/send"),
    "send_bulk_sms": ("POST", "/api/v1/send-bulk"),
    "get_balance": ("POST", "/api/v1/get-balance"),
    "list_sender_names": ("GET", "/api/v1/sendernames"),
    "get_message_status": ("POST", "/api/v1/message-status/{message_id}"),
    "get_message_report": ("POST", "/api/v1/message-report/{message_id}"),
    "list_templates": ("GET", "/gateway/v1/templates"),
    "save_template": ("PUT", "/gateway/v1/templates/{name}"),
    "get_template": ("GET", "/gateway/v1/templates/{name}"),
    "delete_template": ("DELETE", "/gateway/v1/templates/{name}"),
    "send_template": ("POST", "/gateway/v1/send-template"),
    "get_usage": ("GET", "/gateway/v1/usage"),
    "list_messages": ("GET", "/gateway/v1/messages"),
    "on_new_sent_message": ("GET", "/gateway/v1/messages"),
}


class CorbitSMSNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-corbit-sms"
    connection_evidence = ConnectionEvidence(noun="approved sender names", operation="list_sender_names", label_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return CorbitSMSNodeConfig

    async def _request(self, method, path, *, params=None, body=None, headers=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Corbit SMS API token")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                json=body, headers={"Authorization": "Bearer " + credential.api_token,
                                    "Accept": "application/json", **(headers or {})})
        # Do not retry sends automatically: use the explicit idempotency key.
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected a Corbit JSON object")
        if data.get("status") == "Error":
            raise ValueError(data.get("message") or "Corbit rejected the request")
        return data

    @staticmethod
    def _archive_params(config):
        params = {key: value for key, value in {
            "from": config.from_time, "to": config.to_time, "number": config.number,
            "sender": config.sender, "status": "1" if config.include_status else None,
        }.items() if value is not None}
        if isinstance(config, ListMessages):
            params["limit"] = config.limit
            if config.cursor is not None:
                params["cursor"] = config.cursor
        return params

    async def _poll_messages(self, config):
        params = {**self._archive_params(config), "limit": 200}
        messages, seen_cursors = [], set()
        # Fetch every page before committing seen state; partial polls never
        # consume records. Follow nextCursor even when the page is short.
        for _ in range(50):
            result = await self._request("GET", "/gateway/v1/messages", params=params)
            page = result["data"]
            rows = page["messages"]
            if not isinstance(rows, list):
                raise ValueError("Expected a Corbit message archive list")
            for row in rows:
                if (not isinstance(row, dict) or not isinstance(row.get("id"), list)
                        or not row["id"] or not all(isinstance(x, str) and x for x in row["id"])):
                    raise ValueError("Corbit archive record lacks message IDs")
            messages.extend(rows)
            cursor = page["nextCursor"]
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise ValueError("Corbit archive cursor did not advance")
            seen_cursors.add(cursor)
            params = {**params, "cursor": cursor}
        else:
            raise ValueError("Corbit archive exceeds 50 pages; narrow the date or sender filters")
        # Bound the scan to the shared 10,000-id retention and deduplicate
        # overlapping pages before detecting unseen records.
        unique = {json.dumps(sorted(row["id"]), separators=(",", ":")): row for row in messages}
        fresh = await self._filter_unseen(list(unique.values()),
            lambda row: json.dumps(sorted(row["id"]), separators=(",", ":")))
        return {"messages": fresh, "new_message_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "messages" not in output:
            return super().resolve_agent_event(output)
        messages = output["messages"]
        if not messages:
            return None
        lines = [f"- {row['sender']} sent an SMS to {', '.join(row['to'])} at {row['ts']}; "
                 f"{row['length']} characters; message IDs: {', '.join(row['id'])}"
                 for row in messages[:10]]
        return {"text": f"Corbit SMS: {len(messages)} new sent message(s). The archive does not include message text.\n" + "\n".join(lines),
                "conversation_key": None}

    async def execute(self, inputs):
        if not isinstance(self.config, CorbitSMSNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Corbit SMS API token")
        config = self.config.config
        if isinstance(config, OnNewSentMessage):
            return await self._poll_messages(config)
        method, path = ROUTES[config.operation]
        for field in ("message_id", "name"):
            marker = "{" + field + "}"
            if marker in path:
                value = getattr(config, field)
                if value in {".", ".."} or any(ord(c) < 32 for c in value):
                    raise ValueError("Use a valid Corbit resource identifier")
                path = path.replace(marker, quote(value, safe=""))
        body, params, headers = None, None, {}
        if isinstance(config, (SendSMS, SendBulkSMS)):
            body = {"senderName": config.sender_name, "messageBody": config.message_body,
                    "sendAtOption": config.send_at_option}
            body.update({"number": config.number} if isinstance(config, SendSMS) else {"numbers": config.numbers})
            if config.allow_duplicate:
                headers["X-Allow-Duplicate"] = "true"
        elif isinstance(config, SaveTemplate):
            body = {"text": config.text}
        elif isinstance(config, SendTemplate):
            body = {"senderName": config.sender_name, "template": config.template,
                    "vars": config.vars, "recipients": [r.model_dump() if isinstance(r, Recipient) else r for r in config.recipients]}
        elif isinstance(config, ListMessages):
            params = self._archive_params(config)
        if isinstance(config, SendOptions) and config.idempotency_key:
            headers["Idempotency-Key"] = config.idempotency_key
        data = await self._request(method, path, params=params, body=body, headers=headers)
        # Preserve the provider's envelope, including bare DLR jobId/msgs and
        # Partial results from personalized bulk sends, without inventing fields.
        return data
