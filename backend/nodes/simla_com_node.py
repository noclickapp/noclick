"""Simla.com MG Bot API v1: bounded reads and explicit dialog/message writes.

Contract: https://mg-api-docs.simla.com/bot/v1/en/openapi.yaml
Each operation makes one request; write acknowledgements do not prove delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://mg-o1.retailcrm.pro/api/bot/v1"


class SimlaComBotTokenCredential(BaseModel):
    model_config = ConfigDict(title="Simla Com Bot Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://mg-api-docs.simla.com/bot/v1/en/",
            "x-credential-instructions": "Paste your existing Simla.com bot token. NoClick sends it as X-Bot-Token to the documented MG Bot API server. The bot needs access to the channels and dialogs you automate. Connection checks list your channels; they do not prove message delivery or write permissions.",
        })
    credential_type: Literal["simla_com_bot_token"] = Field("simla_com_bot_token", json_schema_extra={"ui:hidden": True})
    bot_token: str = Field(..., title="Bot token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("bot_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Bot token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    limit: int = Field(100, ge=1, le=1000, description="Maximum rows in this single page. Use the returned IDs as since_id or until_id to request another page.")
    since_id: int | None = Field(None, ge=1, description="Lower bound for object IDs, as defined by Simla.")
    until_id: int | None = Field(None, ge=1, description="Upper bound for object IDs, as defined by Simla.")


class ListBots(_Page):
    operation: Literal["list_bots"] = Field("list_bots", json_schema_extra={"ui:hidden": True})

class ListChannels(_Page):
    operation: Literal["list_channels"] = Field("list_channels", json_schema_extra={"ui:hidden": True})

class ListChats(_Page):
    operation: Literal["list_chats"] = Field("list_chats", json_schema_extra={"ui:hidden": True})
    channel_id: int | None = Field(None, ge=1)
    customer_id: int | None = Field(None, ge=1)

class ListCommands(_Page):
    operation: Literal["list_commands"] = Field("list_commands", json_schema_extra={"ui:hidden": True})

class ListCustomers(_Page):
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    channel_id: int | None = Field(None, ge=1)

class ListDialogs(_Page):
    operation: Literal["list_dialogs"] = Field("list_dialogs", json_schema_extra={"ui:hidden": True})
    chat_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    bot_id: int | None = Field(None, ge=1)

class ListMembers(_Page):
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"ui:hidden": True})
    chat_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)

class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})

class ListMessages(_Page):
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    chat_id: int | None = Field(None, ge=1)
    dialog_id: int | None = Field(None, ge=1)
    channel_id: int | None = Field(None, ge=1)
    customer_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    bot_id: int | None = Field(None, ge=1)


class UpdateBot(_Input):
    operation: Literal["update_bot"] = Field("update_bot", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255, description="New name of the authenticated bot.")


class _Dialog(_Input):
    dialog_id: int = Field(..., ge=1)


class AssignDialog(_Dialog):
    operation: Literal["assign_dialog"] = Field("assign_dialog", json_schema_extra={"ui:hidden": True})
    user_id: int | None = Field(None, ge=1)
    bot_id: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def responsible(self):
        if self.user_id is None and self.bot_id is None:
            raise ValueError("Choose a responsible user or bot")
        return self


class UnassignDialog(_Dialog):
    operation: Literal["unassign_dialog"] = Field("unassign_dialog", json_schema_extra={"ui:hidden": True})


class CloseDialog(_Dialog):
    operation: Literal["close_dialog"] = Field("close_dialog", json_schema_extra={"ui:hidden": True})


class Tag(_Input):
    name: str = Field(..., min_length=1, max_length=255)
    color_code: Literal["light-red", "light-blue", "light-green", "light-orange", "light-gray", "light-grayish-blue", "red", "blue", "green", "orange", "gray", "grayish-blue"] | None = None


class TagName(_Input):
    name: str = Field(..., min_length=1, max_length=255)


class AddDialogTags(_Dialog):
    operation: Literal["add_dialog_tags"] = Field("add_dialog_tags", json_schema_extra={"ui:hidden": True})
    tags: list[Tag] = Field(..., min_length=1, max_length=100)


class RemoveDialogTags(_Dialog):
    operation: Literal["remove_dialog_tags"] = Field("remove_dialog_tags", json_schema_extra={"ui:hidden": True})
    tags: list[TagName] = Field(..., min_length=1, max_length=100)


class CreateDialog(_Input):
    operation: Literal["create_dialog"] = Field("create_dialog", json_schema_extra={"ui:hidden": True})
    chat_id: int = Field(..., ge=1)
    bot_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)


class SendMessage(_Input):
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    chat_id: int = Field(..., ge=1)
    content: str = Field(..., min_length=1, max_length=2000, description="Text to send. A public message is visible to the customer.")
    scope: Literal["public", "private"] = "public"
    quote_message_id: int | None = Field(None, ge=1)


class EditMessage(_Input):
    operation: Literal["edit_message"] = Field("edit_message", json_schema_extra={"ui:hidden": True})
    message_id: int = Field(..., ge=1)
    content: str = Field(..., min_length=1, max_length=2000, description="Replacement text for an existing text message.")


class DeleteMessage(_Input):
    operation: Literal["delete_message"] = Field("delete_message", json_schema_extra={"ui:hidden": True})
    message_id: int = Field(..., ge=1)


SimlaComConfig = Annotated[Union[ListBots, ListChannels, ListChats, ListCommands, ListCustomers, ListDialogs, ListMembers, ListUsers, ListMessages, UpdateBot, AssignDialog, UnassignDialog, CloseDialog, AddDialogTags, RemoveDialogTags, CreateDialog, SendMessage, EditMessage, DeleteMessage], Field(discriminator="operation")]


class SimlaComFullConfig(NodeConfig[SimlaComConfig, SimlaComBotTokenCredential]):
    pass


ROUTES = {
    "list_bots": ("GET", "/bots"),
    "list_channels": ("GET", "/channels"),
    "list_chats": ("GET", "/chats"),
    "list_commands": ("GET", "/my/commands"),
    "list_customers": ("GET", "/customers"),
    "list_dialogs": ("GET", "/dialogs"),
    "list_members": ("GET", "/members"),
    "list_users": ("GET", "/users"),
    "list_messages": ("GET", "/messages"),
    "update_bot": ("PATCH", "/my/info"),
    "assign_dialog": ("PATCH", "/dialogs/{dialog_id}/assign"),
    "unassign_dialog": ("PATCH", "/dialogs/{dialog_id}/unassign"),
    "close_dialog": ("DELETE", "/dialogs/{dialog_id}/close"),
    "add_dialog_tags": ("PATCH", "/dialogs/{dialog_id}/tags/add"),
    "remove_dialog_tags": ("PATCH", "/dialogs/{dialog_id}/tags/delete"),
    "create_dialog": ("POST", "/chats/{chat_id}/dialogs"),
    "send_message": ("POST", "/messages"),
    "edit_message": ("PATCH", "/messages/{message_id}"),
    "delete_message": ("DELETE", "/messages/{message_id}"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class SimlaComNode(WorkflowNode):
    integration_type = "automation-simla-com"
    connection_evidence = ConnectionEvidence(noun="channels", operation="list_channels")

    @classmethod
    def get_config_model(cls):
        return SimlaComFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Simla Com bot token")
        op = self.config.config
        token = self.config.credentials.bot_token
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("dialog_id", "chat_id", "message_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", str(values.pop(field)))
        if op.operation == "send_message":
            values["type"] = "text"
        kwargs = {"params": values} if method == "GET" else {"json": values} if values else {}
        # No redirects, retries, or follow-up writes: tokens stay on the fixed API origin.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"X-Bot-Token": token, "Accept": "application/json"}, **kwargs)
        if response.status_code != 200:
            # Preserve the provider's JSON error text for a definitive rejection.
            message = "Simla Com request failed"
            try:
                errors = response.json().get("errors")
                if isinstance(errors, list) and all(isinstance(v, str) for v in errors):
                    message = "; ".join(errors)
            except (ValueError, AttributeError):
                pass
            raise ValueError(_redact(f"HTTP {response.status_code}: {message}", token))
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Simla Com returned an unexpected response; inspect writes before retrying")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Simla Com returned invalid JSON; inspect writes before retrying") from None
        if isinstance(data, dict) and "errors" in data:
            raise ValueError(_redact(str(data["errors"]), token))
        if method == "GET":
            if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                raise ValueError("Expected a Simla Com list response")
            output = {"status": "success", "data": data, "count": len(data),
                "page_limit": op.limit, "may_have_more": len(data) >= op.limit,
                "complete": len(data) < op.limit}
        else:
            if not isinstance(data, dict):
                raise ValueError("Expected a Simla Com write acknowledgement")
            output = {"status": "success", "data": data, "acknowledged": True,
                "delivery_verified": False}
        output = _redact(output, token)
        await self.emit(output)
        return output
