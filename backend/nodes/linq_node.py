"""Linq Partner API v3 messaging. Each action issues exactly one API request."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.linqapp.com/api/partner"


class LinqAPIToken(BaseModel):
    model_config = ConfigDict(title="Linq API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.linqapp.com/channel/imessage/getting-started/authentication/",
        "x-credential-instructions": "Paste your existing Linq Partner API bearer token without the Bearer prefix. NoClick verifies access by reading your phone numbers."})
    credential_type: Literal["linq_api_token"] = Field("linq_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the bearer token without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, description="Maximum results in this page.")
    cursor: str | None = Field(None, max_length=4096, description="Copy next_cursor from the previous response. Each run fetches one page.")


class _Chat(_Input):
    chat_id: UUID = Field(..., description="Linq chat UUID.")


class _Message(_Input):
    message_id: UUID = Field(..., description="Linq message UUID.")


class ListChats(_Page):
    """List one page of conversations; preserve the provider's next_cursor."""
    operation: Literal["list_chats"] = "list_chats"
    from_number: str | None = Field(None, pattern=r"^\+?[1-9]\d{1,14}$", description="Filter by sending phone number.")
    to: str | None = None


class GetChat(_Chat):
    operation: Literal["get_chat"] = "get_chat"


class CreateChat(_Input):
    """Create or reuse a chat and send its required initial text message. First messages cannot contain URLs."""
    operation: Literal["create_chat"] = "create_chat"
    from_number: str = Field(..., pattern=r"^\+[1-9][0-9]{1,14}$", description="Your sending number in E.164 format.")
    to: list[str] = Field(..., min_length=1, max_length=31, description="Recipient phone numbers or email addresses.")
    text: str = Field(..., min_length=1, max_length=10000)


class UpdateChat(_Chat):
    """Request a chat name change; confirm final outcome through Linq webhook events."""
    operation: Literal["update_chat"] = "update_chat"
    display_name: str = Field(..., min_length=1, max_length=1000)


class SendMessage(_Chat):
    """Queue a text message. Acceptance does not prove delivery; read the message status later."""
    operation: Literal["send_message"] = "send_message"
    text: str = Field(..., min_length=1, max_length=10000)
    idempotency_key: str | None = Field(None, max_length=255, description="Reuse this key when retrying the same message.")
    reply_to_message_id: UUID | None = None


class ListMessages(_Chat, _Page):
    operation: Literal["list_messages"] = "list_messages"


class GetMessage(_Message):
    operation: Literal["get_message"] = "get_message"


class EditMessage(_Message):
    """Edit a text part within 15 minutes of sending, up to five times."""
    operation: Literal["edit_message"] = "edit_message"
    text: str = Field(..., min_length=1, max_length=10000)
    part_index: int = Field(0, ge=0)


class DeleteMessage(_Message):
    """Delete the API record only. This does not unsend the message from recipients' chats."""
    operation: Literal["delete_message"] = "delete_message"


class SendReaction(_Message):
    """Add or remove a standard reaction on a message part."""
    operation: Literal["send_reaction"] = "send_reaction"
    reaction_operation: Literal["add", "remove"] = "add"
    reaction_type: Literal["love", "like", "dislike", "laugh", "emphasize", "question"] = "love"
    part_index: int = Field(0, ge=0)


class ListPhoneNumbers(_Input):
    operation: Literal["list_phone_numbers"] = "list_phone_numbers"


class GetAttachment(_Input):
    """Read attachment metadata and its download URL; no file download is performed."""
    operation: Literal["get_attachment"] = "get_attachment"
    attachment_id: UUID


class ListBlockedHandles(_Input):
    operation: Literal["list_blocked_handles"] = "list_blocked_handles"


class BlockHandle(_Input):
    """Block inbound delivery and outbound sending for this handle."""
    operation: Literal["block_handle"] = "block_handle"
    handle: str = Field(..., min_length=1, max_length=320)
    reason: str | None = Field(None, max_length=1000)


class UnblockHandle(_Input):
    """Resume inbound delivery and permit sending to this handle."""
    operation: Literal["unblock_handle"] = "unblock_handle"
    handle: str = Field(..., min_length=1, max_length=320)


class MarkChatRead(_Chat):
    operation: Literal["mark_chat_read"] = "mark_chat_read"


class StartTyping(_Chat):
    operation: Literal["start_typing"] = "start_typing"


class StopTyping(_Chat):
    operation: Literal["stop_typing"] = "stop_typing"


class CheckIMessage(_Input):
    operation: Literal["check_imessage"] = "check_imessage"
    address: str = Field(..., min_length=1, max_length=320)
    from_number: str | None = Field(None, pattern=r"^\+[1-9][0-9]{1,14}$")


class CheckRCS(_Input):
    operation: Literal["check_rcs"] = "check_rcs"
    address: str = Field(..., min_length=1, max_length=320)
    from_number: str | None = Field(None, pattern=r"^\+[1-9][0-9]{1,14}$")


LinqOperation = Annotated[Union[ListChats, GetChat, CreateChat, UpdateChat, SendMessage, ListMessages,
    GetMessage, EditMessage, DeleteMessage, SendReaction, ListPhoneNumbers, GetAttachment,
    ListBlockedHandles, BlockHandle, UnblockHandle, MarkChatRead, StartTyping, StopTyping,
    CheckIMessage, CheckRCS], Field(discriminator="operation")]


class LinqConfig(NodeConfig[LinqOperation, LinqAPIToken]):
    pass


# Method, path, mandatory response field (None for asynchronous acknowledgements or 204).
ROUTES = {
    "list_chats": ("GET", "/v3/chats", "chats"),
    "get_chat": ("GET", "/v3/chats/{chat_id}", "id"),
    "create_chat": ("POST", "/v3/chats", "chat"),
    "update_chat": ("PUT", "/v3/chats/{chat_id}", None),
    "send_message": ("POST", "/v3/chats/{chat_id}/messages", "message"),
    "list_messages": ("GET", "/v3/chats/{chat_id}/messages", "messages"),
    "get_message": ("GET", "/v3/messages/{message_id}", "id"),
    "edit_message": ("PATCH", "/v3/messages/{message_id}", "id"),
    "delete_message": ("DELETE", "/v3/messages/{message_id}", None),
    "send_reaction": ("POST", "/v3/messages/{message_id}/reactions", None),
    "list_phone_numbers": ("GET", "/v3/phone_numbers", "phone_numbers"),
    "get_attachment": ("GET", "/v3/attachments/{attachment_id}", "id"),
    "list_blocked_handles": ("GET", "/v3/blocked_handles", "blocked_handles"),
    "block_handle": ("POST", "/v3/blocked_handles", "blocked_handle"),
    "unblock_handle": ("DELETE", "/v3/blocked_handles", None),
    "mark_chat_read": ("POST", "/v3/chats/{chat_id}/read", None),
    "start_typing": ("POST", "/v3/chats/{chat_id}/typing", None),
    "stop_typing": ("DELETE", "/v3/chats/{chat_id}/typing", None),
    "check_imessage": ("POST", "/v3/capability/check_imessage", "available"),
    "check_rcs": ("POST", "/v3/capability/check_rcs", "available"),
}


SUCCESS_CODES = {action: ({201} if action in {"create_chat", "block_handle"} else
    {202} if action in {"send_message", "update_chat", "send_reaction"} else
    {204} if action in {"delete_message", "unblock_handle", "mark_chat_read", "start_typing", "stop_typing"} else
    {200, 204} if action == "edit_message" else {200}) for action in ROUTES}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class LinqNode(WorkflowNode):
    integration_type = "automation-linq"
    connection_evidence = ConnectionEvidence(noun="phone numbers", operation="list_phone_numbers", label_keys=("phone_number", "id"))

    @classmethod
    def get_config_model(cls):
        return LinqConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Linq API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template, required = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template.format(**values)
        for field in ("chat_id", "message_id", "attachment_id"):
            values.pop(field, None)
        if "from_number" in values:
            values["from"] = values.pop("from_number")
        if isinstance(op, (CreateChat, SendMessage)):
            message = {"parts": [{"type": "text", "value": values.pop("text")}]}
            if "idempotency_key" in values:
                message["idempotency_key"] = values.pop("idempotency_key")
            if "reply_to_message_id" in values:
                message["reply_to"] = {"message_id": values.pop("reply_to_message_id")}
            values["message"] = message
        if isinstance(op, SendReaction):
            values["operation"] = values.pop("reaction_operation")
            values["type"] = values.pop("reaction_type")
        kwargs = {"params": values} if method == "GET" else {"json": values} if values else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Linq request did not complete; check the provider before retrying a write") from None
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for connection evidence, without returning secrets.
            try:
                error = response.json().get("error", {})
                message = error.get("message") if isinstance(error, dict) else None
            except (ValueError, AttributeError):
                message = None
            return {"status": "error", "http_status": response.status_code,
                    "error": _redact(message or "Linq did not accept this request", token)}
        if response.status_code not in SUCCESS_CODES[op.operation]:
            raise ValueError("Linq returned an undocumented success status")
        if response.status_code == 204:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Linq returned a non-JSON response") from None
            if not isinstance(data, dict) or data.get("success") is False or "error" in data:
                raise ValueError("Linq returned an invalid response envelope")
            if required and required not in data:
                raise ValueError("Linq response is missing " + required)
            if op.operation.startswith("list_") and not isinstance(data[required], list):
                raise ValueError("Linq list response is invalid")
        result = {"status": "success", "http_status": response.status_code, "operation": op.operation,
                  "data": _redact(data, token)}
        if method != "GET":
            result["outcome"] = "accepted" if response.status_code == 202 else "acknowledged"
            if isinstance(op, (CreateChat, SendMessage)):
                result["delivery_verified"] = False
            if isinstance(op, DeleteMessage):
                result["unsent"] = False
        return result
