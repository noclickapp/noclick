"""Zoho Cliq v3 chats, channels and text messaging for US accounts.

Each action makes one request to the publisher's pinned v3 contract; list
responses retain the provider's cursors so workflows can fetch later pages.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.zoho_cliq_oauth import OAUTH_PROVIDER
from nodes.scopes.zoho_cliq import ZOHO_CLIQ_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://cliq.zoho.com/api/v3"


class ZohoCliqOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Zoho Cliq OAuth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "zoho_cliq",
            "x-oauth-scopes": sorted(ZOHO_CLIQ_SCOPES.declared_scopes()),
            "x-credential-url": "https://api-console.zoho.com/",
            "x-credential-instructions": "Connect a Zoho Cliq account in the US data center. Authorize the chat, channel and messaging permissions requested. An existing US OAuth access token can also be supplied by hand; refresh token and expiry are optional for that method.",
        })
    credential_type: Literal["zoho_cliq_oauth"] = Field("zoho_cliq_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = None

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def secret(cls, value):
        if value is None:
            return value
        return clean_secret(value, field_name="OAuth token")


Identifier = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=5000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListChats(_Input):
    operation: Literal["list_chats"] = "list_chats"
    name: str | None = None
    limit: int = Field(100, ge=1, le=100)
    modified_before: int | None = Field(None, ge=0, description="Epoch milliseconds; use the last chat timestamp to retrieve older chats.")


class GetChat(_Input):
    operation: Literal["get_chat"] = "get_chat"
    chat_id: Identifier


class ListChatMembers(_Input):
    operation: Literal["list_chat_members"] = "list_chat_members"
    chat_id: Identifier


class CreateChat(_Input):
    operation: Literal["create_chat"] = "create_chat"
    user_id: Identifier = Field(..., description="Zoho user ID of the other participant in a direct chat.")


class RenameChat(_Input):
    operation: Literal["rename_chat"] = "rename_chat"
    chat_id: Identifier
    title: str = Field(..., min_length=1, max_length=255)


class AddChatMembers(_Input):
    operation: Literal["add_chat_members"] = "add_chat_members"
    chat_id: Identifier
    user_ids: list[Identifier] = Field(..., min_length=1, max_length=100)


class LeaveChat(_Input):
    operation: Literal["leave_chat"] = "leave_chat"
    chat_id: Identifier


class ListChannels(_Input):
    operation: Literal["list_channels"] = "list_channels"
    limit: int = Field(100, ge=1, le=100)
    next_token: str | None = Field(None, description="Pass the provider's next_token unchanged to retrieve the next page.")


class GetChannel(_Input):
    operation: Literal["get_channel"] = "get_channel"
    channel_id: Identifier


class CreateChannel(_Input):
    operation: Literal["create_channel"] = "create_channel"
    name: str = Field(..., min_length=1, max_length=90)
    level: Literal["organization", "private"] = Field("private", description="Create an organization or private channel.")
    description: str | None = Field(None, max_length=10500)
    visibility: Literal["open", "closed"] = "closed"


class UpdateChannel(_Input):
    operation: Literal["update_channel"] = "update_channel"
    channel_id: Identifier
    description: str = Field(..., max_length=10500, description="Replace the channel description; empty text clears it.")
    name: str | None = Field(None, min_length=1, max_length=90)
    visibility: Literal["open", "closed"] | None = None


class ListChannelMembers(_Input):
    operation: Literal["list_channel_members"] = "list_channel_members"
    channel_id: Identifier
    limit: int = Field(50, ge=1, le=100)
    next_token: str | None = None


class AddChannelMembers(_Input):
    operation: Literal["add_channel_members"] = "add_channel_members"
    channel_id: Identifier
    user_ids: list[Identifier] = Field(..., min_length=1, max_length=100)


class RemoveChannelMember(_Input):
    operation: Literal["remove_channel_member"] = "remove_channel_member"
    channel_id: Identifier
    user_id: Identifier


class SendChatMessage(_Input):
    operation: Literal["send_chat_message"] = "send_chat_message"
    chat_id: Identifier
    text: Text
    reply_to: Identifier | None = None
    sync_message: bool = True


class SendChannelMessage(_Input):
    operation: Literal["send_channel_message"] = "send_channel_message"
    channel_id: Identifier
    text: Text
    reply_to: Identifier | None = None
    sync_message: bool = True


class SearchMessages(_Input):
    operation: Literal["search_messages"] = "search_messages"
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(50, ge=1, le=50)
    next_token: int | None = None
    chat_ids: str | None = Field(None, description="Comma-separated chat IDs, at most five.", pattern=r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+){0,4}$")


class EditMessage(_Input):
    operation: Literal["edit_message"] = "edit_message"
    chat_id: Identifier
    message_id: Identifier
    text: Text
    notify_edit: bool = False


CliqOperation = Annotated[Union[ListChats, GetChat, ListChatMembers, CreateChat,
    RenameChat, AddChatMembers, LeaveChat, ListChannels, GetChannel, CreateChannel,
    UpdateChannel, ListChannelMembers, AddChannelMembers, RemoveChannelMember,
    SendChatMessage, SendChannelMessage, SearchMessages, EditMessage], Field(discriminator="operation")]


class ZohoCliqConfig(NodeConfig[CliqOperation, ZohoCliqOAuthCredential]):
    pass


# Keys are operation names, values are exactly one pinned method and path.
ROUTES = {
    "list_chats": ("GET", "/chats"),
    "get_chat": ("GET", "/chats/{chat_id}"),
    "list_chat_members": ("GET", "/chats/{chat_id}/members"),
    "create_chat": ("POST", "/chats"),
    "rename_chat": ("PUT", "/chats/{chat_id}"),
    "add_chat_members": ("POST", "/chats/{chat_id}/members"),
    "leave_chat": ("POST", "/chats/{chat_id}/leave"),
    "list_channels": ("GET", "/channels"),
    "get_channel": ("GET", "/channels/{channel_id}"),
    "create_channel": ("POST", "/channels"),
    "update_channel": ("PUT", "/channels/{channel_id}"),
    "list_channel_members": ("GET", "/channels/{channel_id}/members"),
    "add_channel_members": ("POST", "/channels/{channel_id}/members"),
    "remove_channel_member": ("DELETE", "/channels/{channel_id}/members/{user_id}"),
    "send_chat_message": ("POST", "/chats/{chat_id}/messages"),
    "send_channel_message": ("POST", "/channels/{channel_id}/messages"),
    "search_messages": ("GET", "/messages/search"),
    "edit_message": ("PUT", "/chats/{chat_id}/messages/{message_id}"),
}


class ZohoCliqNode(WorkflowNode):
    integration_type = "automation-zoho-cliq"
    scope_registry = ZOHO_CLIQ_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_channels", noun="channels")

    @classmethod
    def get_config_model(cls):
        return ZohoCliqConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool,
            user_id=user_id, credential_id=credential_id, provider="zoho_cliq",
            refresh=OAUTH_PROVIDER.refresh)

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Zoho Cliq US account")
        credential = self.config.credentials.model_dump()
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential, refresh=OAUTH_PROVIDER.refresh,
            provider="zoho_cliq", caller_path="execute")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        values.pop("operation")
        for key in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        if op.operation == "create_chat":
            values["chat_type"] = "direct_message"
        elif op.operation == "rename_chat":
            values["operation"] = "update_title"
        elif op.operation == "add_channel_members":
            values = {"members": [{"user_id": uid} for uid in values.pop("user_ids")]}
        kwargs = {"params": values} if method == "GET" else ({"json": values} if values else {})
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential["access_token"],
                         "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for connection evidence, without echoing tokens.
            detail = response.text[:2000]
            for key in ("access_token", "refresh_token"):
                if credential.get(key):
                    detail = detail.replace(credential[key], "[redacted]")
            raise ValueError(f"Zoho Cliq HTTP {response.status_code}: {detail}")
        if not response.content:
            return {"status": "success", "http_status": response.status_code}
        if "json" not in response.headers.get("content-type", ""):
            raise ValueError("Zoho Cliq returned a non-JSON response")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Zoho Cliq returned an unexpected JSON response")
        if isinstance(data, dict) and (data.get("error") or data.get("code") and data.get("message")):
            raise ValueError("Zoho Cliq returned an error: " + str(data).replace(credential["access_token"], "[redacted]")[:2000])
        return {"status": "success", "http_status": response.status_code, "data": data}
