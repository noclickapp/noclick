"""MessageBird's SMS API, authenticated with a manually supplied AccessKey.

Contract: https://github.com/messagebird/openapi-specs/blob/main/sms/openapi.yaml
The published server URL repeats /messages; the official SMS documentation
defines the actual routes at https://rest.messagebird.com/messages.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://rest.messagebird.com"


class MessageBirdAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="MessageBird API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.messagebird.com/en/developers/access",
            "x-credential-instructions": "Paste your MessageBird REST API access key from Developers → API access. Use a live key for sending real SMS, or a test key to test without delivery. NoClick reads your SMS message list to check the connection.",
        })
    credential_type: Literal["messagebird_api_key"] = Field("messagebird_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the AccessKey prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _operation(name, title, category="Messages", *, trigger=False):
    return Field(name, title=title, json_schema_extra={
        "ui:hidden": True, "x-display-name": title, "x-category": category,
        "x-is-trigger": trigger,
    })


def _rfc3339(value):
    if value is not None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
        except (ValueError, AttributeError):
            raise ValueError("Use a date and time with timezone in RFC3339 format") from None
    return value


class _Send(_Input):
    originator: str = Field(..., min_length=1, max_length=20, description="Sender phone number with country code, or an alphanumeric sender of at most 11 characters.")
    recipients: list[str] = Field(..., min_length=1, max_length=50, description="Recipient phone numbers with country code.")
    body: str = Field(..., min_length=1, description="SMS content. Binary messages use a hexadecimal body.")
    reference: Optional[str] = Field(None, max_length=1000, description="Your own reference for this message.")
    validity: Optional[int] = Field(None, ge=1, description="Validity in seconds.")
    datacoding: Literal["plain", "unicode", "auto"] = "auto"

    @field_validator("recipients")
    @classmethod
    def numbers(cls, value):
        if any(not number.lstrip("+").isdigit() or not 5 <= len(number.lstrip("+")) <= 15 for number in value):
            raise ValueError("Use recipient phone numbers with country code")
        return value

    @field_validator("originator")
    @classmethod
    def sender(cls, value):
        if not value.lstrip("+").isdigit() and len(value) > 11:
            raise ValueError("Alphanumeric senders must be at most 11 characters")
        return value


class SendSMS(_Send):
    operation: Literal["send_sms"] = _operation("send_sms", "Send SMS")


class ScheduleSMS(_Send):
    operation: Literal["schedule_sms"] = _operation("schedule_sms", "Schedule SMS")
    scheduledDatetime: str = Field(..., title="Send at", description="Future RFC3339 timestamp including timezone.")
    _time = field_validator("scheduledDatetime")(_rfc3339)


class SendFlashSMS(_Send):
    operation: Literal["send_flash_sms"] = _operation("send_flash_sms", "Send Flash SMS")


class SendBinarySMS(_Send):
    operation: Literal["send_binary_sms"] = _operation("send_binary_sms", "Send Binary SMS")
    udh: str = Field(..., min_length=2, pattern=r"^(?:[0-9A-Fa-f]{2})+$", title="User data header", description="Hexadecimal UDH, for example 050003340201.")

    @field_validator("body")
    @classmethod
    def binary(cls, value):
        import re
        if not re.fullmatch(r"(?:[0-9A-Fa-f]{2})+", value):
            raise ValueError("Use hexadecimal octets for a binary SMS")
        return value


class _List(_Input):
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1_000_000, description="Number of messages to skip; use next_offset to continue.")
    originator: Optional[str] = None
    recipient: Optional[int] = Field(None, ge=1)
    status: Optional[Literal["scheduled", "sent", "buffered", "delivered", "expired", "delivery_failed"]] = None
    from_time: Optional[str] = Field(None, description="Inclusive starting RFC3339 timestamp.")
    until: Optional[str] = Field(None, description="Ending RFC3339 timestamp.")
    _time = field_validator("from_time", "until")(_rfc3339)


class ListMessages(_List):
    operation: Literal["list_messages"] = _operation("list_messages", "List Messages")
    direction: Optional[Literal["mt", "mo"]] = Field(None, description="mt = sent, mo = received.")


class ListReceivedMessages(_List):
    operation: Literal["list_received_messages"] = _operation("list_received_messages", "List Received Messages")


class ListSentMessages(_List):
    operation: Literal["list_sent_messages"] = _operation("list_sent_messages", "List Sent Messages")


class SearchMessages(_List):
    operation: Literal["search_messages"] = _operation("search_messages", "Search Messages")
    searchterm: str = Field(..., min_length=1, description="Search recipient and originator, as supported by MessageBird.")


class GetMessage(_Input):
    operation: Literal["get_message"] = _operation("get_message", "Get Message")
    message_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class DeleteMessage(_Input):
    operation: Literal["delete_message"] = _operation("delete_message", "Delete Scheduled Message")
    message_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="ID of a scheduled SMS to cancel. MessageBird only permits deletion of scheduled messages.")


class OnNewMessage(PollTriggerConfigBase):
    operation: Literal["on_new_message"] = _operation("on_new_message", "New SMS Message", "Triggers", trigger=True)
    direction: Optional[Literal["mt", "mo"]] = Field(None, description="Watch all, sent (mt), or received (mo) messages.")
    lookback_hours: int = Field(24, ge=1, le=168, description="Scan messages created in this rolling window. Set longer than the polling interval; at most 2,000 messages per poll.")
    originator: Optional[str] = None
    recipient: Optional[int] = Field(None, ge=1)


class OnDeliveryStatusChanged(PollTriggerConfigBase):
    operation: Literal["on_delivery_status_changed"] = _operation("on_delivery_status_changed", "SMS Delivery Status Changed", "Triggers", trigger=True)
    lookback_hours: int = Field(24, ge=1, le=168, description="Watch delivery status for sent messages created within this rolling window, at most 2,000 messages. Older messages are outside this trigger's scope.")
    originator: Optional[str] = None
    recipient: Optional[int] = Field(None, ge=1)


MessageBirdConfig = Annotated[Union[SendSMS, ScheduleSMS, SendFlashSMS, SendBinarySMS,
    ListMessages, ListReceivedMessages, ListSentMessages, SearchMessages, GetMessage,
    DeleteMessage, OnNewMessage, OnDeliveryStatusChanged], Field(discriminator="operation")]


class MessageBirdNodeConfig(NodeConfig[MessageBirdConfig, MessageBirdAPIKeyCredential]):
    pass


class MessageBirdNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-messagebird"
    connection_evidence = ConnectionEvidence(noun="SMS messages", operation="list_messages", label_keys=("body", "originator", "id"))

    @classmethod
    def get_config_model(cls):
        return MessageBirdNodeConfig

    @staticmethod
    async def _request(key, method, path, *, params=None, body=None):
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Authorization": "AccessKey " + key, "Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("MessageBird could not be reached; check the message status before retrying a send") from None
        if response.is_error:
            try:
                errors = response.json().get("errors", [])
                detail = "; ".join(str(item.get("description", "Request rejected")) for item in errors if isinstance(item, dict))
            except (ValueError, AttributeError, TypeError):
                detail = "Request rejected"
            raise ValueError(f"MessageBird API error {response.status_code}: {detail}".replace(key, "[redacted]")) from None
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("MessageBird returned an invalid JSON response") from None
        if not isinstance(data, dict) or data.get("errors"):
            raise ValueError("MessageBird returned an unexpected response")
        return data

    @staticmethod
    def _message(data):
        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"]:
            raise ValueError("MessageBird returned a message without an ID")
        return data

    @classmethod
    async def _list(cls, key, params):
        data = await cls._request(key, "GET", "/messages", params=params)
        if not isinstance(data.get("items"), list):
            raise ValueError("MessageBird returned an invalid message list")
        rows = [cls._message(item) for item in data["items"]]
        total, offset = data.get("totalCount"), data.get("offset")
        if type(total) is not int or type(offset) is not int or total < 0 or offset < 0:
            raise ValueError("MessageBird returned invalid pagination")
        next_offset = offset + len(rows) if rows and offset + len(rows) < total else None
        if not rows and offset < total:
            raise ValueError("MessageBird returned an incomplete message page")
        return {"items": rows, "totalCount": total, "offset": offset, "next_offset": next_offset}

    async def _poll(self, key, config):
        params = {"limit": 100, "offset": 0, "from": (datetime.now(timezone.utc) - timedelta(hours=config.lookback_hours)).isoformat()}
        for field in ("originator", "recipient"):
            if getattr(config, field) is not None:
                params[field] = getattr(config, field)
        if isinstance(config, OnDeliveryStatusChanged):
            params["direction"] = "mt"
        elif config.direction is not None:
            params["direction"] = config.direction
        rows = []
        for _ in range(20):
            data = await self._list(key, params)
            rows.extend(data["items"])
            if data["next_offset"] is None:
                break
            if data["next_offset"] <= params["offset"]:
                raise ValueError("MessageBird pagination did not advance")
            params["offset"] = data["next_offset"]
        else:
            raise ValueError("More than 2,000 messages in this poll; narrow the originator, recipient or lookback window")
        rows = list({row["id"]: row for row in rows}.values())
        if isinstance(config, OnDeliveryStatusChanged):
            deliveries = []
            for message in rows:
                recipients = message.get("recipients", {}).get("items", [])
                if not isinstance(recipients, list):
                    raise ValueError("MessageBird returned invalid recipient statuses")
                for delivery in recipients:
                    if not isinstance(delivery, dict) or any(delivery.get(k) is None for k in ("recipient", "status", "statusDatetime")):
                        raise ValueError("MessageBird returned an incomplete delivery status")
                    deliveries.append({"message_id": message["id"], "originator": message.get("originator"), "body": message.get("body"), **delivery})
            import json
            fresh = await self._filter_unseen(deliveries, lambda d: json.dumps([d["message_id"], d["recipient"], d["status"], d["statusDatetime"]]))
            return {"deliveries": fresh, "new_event_count": len(fresh)}
        fresh = await self._filter_unseen(rows, lambda item: item["id"])
        return {"messages": fresh, "new_event_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_event_count")) if config.get("operation") in {"on_new_message", "on_delivery_status_changed"} else True

    @classmethod
    def resolve_agent_event(cls, output):
        if "messages" not in output and "deliveries" not in output:
            return super().resolve_agent_event(output)
        rows = output.get("messages", output.get("deliveries", []))
        if not rows:
            return None
        lines = []
        for row in rows[:20]:
            if "message_id" in row:
                lines.append(f"SMS {row['message_id']} from {row.get('originator')} to {row['recipient']}: {row['status']} at {row['statusDatetime']}. Content: {row.get('body', '')}")
            else:
                recipients = row.get("recipients", {}).get("items", [])
                targets = ", ".join(str(r.get("recipient")) for r in recipients)
                lines.append(f"SMS {row['id']} ({row.get('direction')}) from {row.get('originator')} to {targets}: {row.get('body', '')}")
        return {"text": "MessageBird SMS event(s):\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a MessageBird API key")
        config, key = self.config.config, self.config.credentials.api_key
        if isinstance(config, (OnNewMessage, OnDeliveryStatusChanged)):
            return await self._poll(key, config)
        if isinstance(config, _Send):
            body = config.model_dump(exclude_none=True, exclude={"operation", "udh"})
            body["type"] = "flash" if isinstance(config, SendFlashSMS) else "binary" if isinstance(config, SendBinarySMS) else "sms"
            if isinstance(config, SendBinarySMS):
                body["typeDetails"] = {"udh": config.udh}
            return {"message": self._message(await self._request(key, "POST", "/messages", body=body)), "delivery_verified": False}
        if isinstance(config, _List):
            params = config.model_dump(exclude_none=True, exclude={"operation", "from_time"})
            if config.from_time is not None:
                params["from"] = config.from_time
            if isinstance(config, ListReceivedMessages):
                params["direction"] = "mo"
            elif isinstance(config, ListSentMessages):
                params["direction"] = "mt"
            return await self._list(key, params)
        path = "/messages/" + quote(config.message_id, safe="")
        if isinstance(config, DeleteMessage):
            await self._request(key, "DELETE", path)
            return {"deleted_id": config.message_id, "deletion_acknowledged": True}
        return {"message": self._message(await self._request(key, "GET", path))}
