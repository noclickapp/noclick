"""Blooio v4 messaging, contacts and chats. Contract: https://docs.blooio.com/openapi.json."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

BASE_URL = "https://api.blooio.com/v4"


class BlooioApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Blooio API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.blooio.com",
            "x-credential-instructions": "Create an API key in the Blooio dashboard, then paste it here without the Bearer prefix."})
    credential_type: Literal["blooio_api_key"] = Field("blooio_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
        description="Your Blooio API key from the dashboard. Paste the key alone, without Bearer.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("Paste the API key alone, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(50, ge=1, le=200, title="Page Size")
    cursor: str | None = Field(None, title="Cursor", description="Use next_cursor from the previous response to fetch another page.")


class _Channel(_Input):
    channel: str = Field(..., min_length=1, title="Channel", description="Channel ID, alias, or sender phone number.")


class _Contact(_Input):
    contact_id: str = Field(..., min_length=1, title="Contact ID")


class _Chat(_Input):
    chat_id: str = Field(..., min_length=1, title="Chat ID")


class _Message(_Chat):
    message_id: str = Field(..., min_length=1, title="Message ID")


class _Text(_Input):
    text: str = Field(..., min_length=1, title="Message Text", json_schema_extra={"ui:widget": "textarea"})
    format: Literal["plain", "markdown"] = Field("plain", title="Text Format")
    dry_run: bool = Field(False, title="Dry Run", description="Validate and route without sending a message.")
    idempotency_key: str | None = Field(None, title="Idempotency Key", description="Reuse the same key only when retrying the same send.", max_length=255)


class GetAccount(_Input):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})


class ListChannels(_Page):
    operation: Literal["list_channels"] = Field("list_channels", title="List Channels", json_schema_extra={"ui:hidden": True})


class GetChannel(_Channel):
    operation: Literal["get_channel"] = Field("get_channel", title="Get Channel", json_schema_extra={"ui:hidden": True})


class GetChannelHealth(_Channel):
    operation: Literal["get_channel_health"] = Field("get_channel_health", title="Get Channel Health", json_schema_extra={"ui:hidden": True})
    days: int = Field(7, ge=1, le=30, title="Trailing Days")


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, title='Search')
    tag: str | None = Field(None, title='Tag')
    identifier: str | None = Field(None, title='Phone or Email')


class CreateContact(_Input):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Name")
    identifier: str | None = Field(None, title="Phone or Email", description="E.164 phone number or email to attach as the first identity.")


class GetContact(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class UpdateContact(_Contact):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Name")


class DeleteContact(_Contact):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})


class ListContactTags(_Contact):
    operation: Literal["list_contact_tags"] = Field("list_contact_tags", title="List Contact Tags", json_schema_extra={"ui:hidden": True})


class AddContactTags(_Contact):
    operation: Literal["add_contact_tags"] = Field("add_contact_tags", title="Add Contact Tags", json_schema_extra={"ui:hidden": True})
    tags: list[str] = Field(..., min_length=1, title="Tags")


class RemoveContactTag(_Contact):
    operation: Literal["remove_contact_tag"] = Field("remove_contact_tag", title="Remove Contact Tag", json_schema_extra={"ui:hidden": True})
    tag: str = Field(..., min_length=1, title="Tag")


class ListChats(_Page):
    operation: Literal["list_chats"] = Field("list_chats", title="List Chats", json_schema_extra={"ui:hidden": True})
    channel_id: str | None = Field(None, title='Channel ID')
    contact_id: str | None = Field(None, title='Contact ID')


class CreateChat(_Input):
    operation: Literal["create_chat"] = Field("create_chat", title="Create Chat", json_schema_extra={"ui:hidden": True})
    channel_id: str = Field(..., min_length=1, title="Channel ID")
    to: str = Field(..., min_length=1, title="Recipient", description="Phone, email, or provider recipient identifier.")


class GetChat(_Chat):
    operation: Literal["get_chat"] = Field("get_chat", title="Get Chat", json_schema_extra={"ui:hidden": True})


class UpdateChat(_Chat):
    operation: Literal["update_chat"] = Field("update_chat", title="Update Chat", json_schema_extra={"ui:hidden": True})
    state: Literal["open", "closed"] = Field(..., title="Chat State", description="Apple Messages for Business only. Closing blocks sends until the customer messages again.")


class MarkChatRead(_Chat):
    operation: Literal["mark_chat_read"] = Field("mark_chat_read", title="Mark Chat Read", json_schema_extra={"ui:hidden": True})


class ListChatMessages(_Chat, _Page):
    operation: Literal["list_chat_messages"] = Field("list_chat_messages", title="List Chat Messages", json_schema_extra={"ui:hidden": True})
    order: Literal["asc", "desc"] = Field("desc", title="Order")


class SendMessageToChat(_Chat, _Text):
    operation: Literal["send_message_to_chat"] = Field("send_message_to_chat", title="Send Message To Chat", json_schema_extra={"ui:hidden": True})


class SendMessage(_Text):
    operation: Literal["send_message"] = Field("send_message", title="Send Message", json_schema_extra={"ui:hidden": True})
    to: str = Field(..., min_length=1, title="Recipient", description="One phone number, email, or provider recipient identifier.")
    sender: str | None = Field(None, title="Sender", description="Optional exact sender phone number, alias, or channel ID. Omit for automatic routing.")


class GetMessage(_Message):
    operation: Literal["get_message"] = Field("get_message", title="Get Message", json_schema_extra={"ui:hidden": True})


class GetMessageStatus(_Message):
    operation: Literal["get_message_status"] = Field("get_message_status", title="Get Message Status", json_schema_extra={"ui:hidden": True})


class AddReaction(_Message):
    operation: Literal["add_reaction"] = Field("add_reaction", title="Add Reaction", json_schema_extra={"ui:hidden": True})
    reaction: str = Field(..., min_length=1, title="Reaction", description="For example +love to add or -love to remove a reaction.")


class ListEvents(_Page):
    operation: Literal["list_events"] = Field("list_events", title="List Events", json_schema_extra={"ui:hidden": True})
    type: str | None = Field(None, title='Event Type or Wildcard')
    chat_id: str | None = Field(None, title='Chat ID')
    message_id: str | None = Field(None, title='Message ID')


BlooioConfig = Annotated[Union[GetAccount, ListChannels, GetChannel, GetChannelHealth, ListContacts, CreateContact, GetContact, UpdateContact, DeleteContact, ListContactTags, AddContactTags, RemoveContactTag, ListChats, CreateChat, GetChat, UpdateChat, MarkChatRead, ListChatMessages, SendMessageToChat, SendMessage, GetMessage, GetMessageStatus, AddReaction, ListEvents], Field(discriminator="operation")]


class BlooioFullConfig(NodeConfig[BlooioConfig, BlooioApiKeyCredential]):
    pass


# Each entry issues exactly one published Blooio operation.
ROUTES = {'get_account': ('GET', '/me', (), ()),
 'list_channels': ('GET', '/channels', ('limit', 'cursor'), ()),
 'get_channel': ('GET', '/channels/{channel}', (), ()),
 'get_channel_health': ('GET', '/channels/{channel}/health', ('days',), ()),
 'list_contacts': ('GET', '/contacts', ('limit', 'cursor', 'q', 'tag', 'identifier'), ()),
 'create_contact': ('POST', '/contacts', (), ('name', 'identifier')),
 'get_contact': ('GET', '/contacts/{contact_id}', (), ()),
 'update_contact': ('PATCH', '/contacts/{contact_id}', (), ('name',)),
 'delete_contact': ('DELETE', '/contacts/{contact_id}', (), ()),
 'list_contact_tags': ('GET', '/contacts/{contact_id}/tags', (), ()),
 'add_contact_tags': ('POST', '/contacts/{contact_id}/tags', (), ('tags',)),
 'remove_contact_tag': ('DELETE', '/contacts/{contact_id}/tags/{tag}', (), ()),
 'list_chats': ('GET', '/chats', ('limit', 'cursor', 'channel_id', 'contact_id'), ()),
 'create_chat': ('POST', '/chats', (), ('channel_id', 'to')),
 'get_chat': ('GET', '/chats/{chat_id}', (), ()),
 'update_chat': ('PATCH', '/chats/{chat_id}', (), ('state',)),
 'mark_chat_read': ('POST', '/chats/{chat_id}/read', (), ()),
 'list_chat_messages': ('GET', '/chats/{chat_id}/messages', ('limit', 'cursor', 'order'), ()),
 'send_message_to_chat': ('POST', '/chats/{chat_id}/messages', (), ('text', 'format', 'dry_run')),
 'send_message': ('POST', '/messages', (), ('to', 'from', 'text', 'format', 'dry_run')),
 'get_message': ('GET', '/chats/{chat_id}/messages/{message_id}', (), ()),
 'get_message_status': ('GET', '/chats/{chat_id}/messages/{message_id}/status', (), ()),
 'add_reaction': ('POST', '/chats/{chat_id}/messages/{message_id}/reactions', (), ('reaction',)),
 'list_events': ('GET', '/events', ('limit', 'cursor', 'type', 'chat_id', 'message_id'), ())}


class BlooioNode(WorkflowNode):
    integration_type = "automation-blooio"
    connection_evidence = ConnectionEvidence(noun="channels", operation="list_channels", identity_operation="get_account",
        label_keys=("name", "alias", "address", "id"))

    @classmethod
    def get_config_model(cls):
        return BlooioFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Blooio API key")
        method, template, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        if "sender" in values:
            values["from"] = values.pop("sender")
        path = template
        for field in re.findall(r"\{(\w+)\}", template):
            value = values[field]
            if value in {".", ".."} or any(ord(c) < 32 for c in value):
                raise ValueError("Invalid Blooio path parameter")
            path = path.replace("{" + field + "}", quote(value, safe=""))
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        if values.get("idempotency_key"):
            headers["Idempotency-Key"] = values["idempotency_key"]
        kwargs = {"params": {k: values[k] for k in query_fields if k in values}, "headers": headers}
        if body_fields:
            kwargs["json"] = {k: values[k] for k in body_fields if k in values}
        output = {"operation": config.operation}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, **kwargs)
            try:
                body = response.json()
            except ValueError:
                return {**output, "status": "error", "http_status": response.status_code, "error": "Blooio returned a non-JSON response"}
            if not isinstance(body, dict):
                return {**output, "status": "error", "error": "Blooio returned an invalid response envelope"}
            if not 200 <= response.status_code < 300 or body.get("error") or body.get("status") == "failed":
                error = body.get("error")
                message = error.get("message") if isinstance(error, dict) else body.get("message") or error
                message = str(message or "Blooio did not accept the request").replace(credential.api_key, "[redacted]")
                return {**output, "status": "error", "http_status": response.status_code, "error": message}
            sending = config.operation in {"send_message", "send_message_to_chat"}
            if sending or config.operation == "create_chat":
                # Send results are top-level; queued/pending means acceptance, never delivery.
                return {**output, "status": "success", "http_status": response.status_code, "data": body}
            if "data" not in body or not isinstance(body["data"], (dict, list)):
                return {**output, "status": "error", "error": "Blooio response is missing data"}
            return {**body, **output, "status": "success", "http_status": response.status_code}
        except httpx.HTTPError:
            return {**output, "status": "error", "error": "Blooio request did not complete; inspect the result before retrying a write"}
