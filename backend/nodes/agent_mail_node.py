"""AgentMail v0 REST operations. Contract: https://docs.agentmail.to/openapi.json."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.agentmail.to"


class AgentMailAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="AgentMail API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.agentmail.to",
            "x-credential-instructions": "Paste an API key from the AgentMail Console. Use a US-region key with access to the inboxes and operations you need. NoClick verifies the key by reading its identity; it does not create an account or send a verification email.",
        })
    credential_type: Literal["agent_mail_api_key"] = Field("agent_mail_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value)


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Operation):
    limit: int = Field(20, ge=1, le=100, description="Maximum items in this page. Use next_page_token from the result to continue.")
    page_token: str | None = Field(None, description="Opaque next_page_token from the preceding response.")
    ascending: bool | None = None


class InboxOperation(Operation):
    inbox_id: str = Field(..., min_length=1, description="Inbox address / ID returned by AgentMail.")


class MailPage(Page, InboxOperation):
    labels: list[str] | None = None
    before: datetime | None = Field(None, description="Filter before this RFC 3339 timestamp.")
    after: datetime | None = Field(None, description="Filter after this RFC 3339 timestamp.")


class MessageOperation(InboxOperation):
    message_id: str = Field(..., min_length=1)


class ThreadOperation(InboxOperation):
    thread_id: str = Field(..., min_length=1)


class DraftOperation(InboxOperation):
    draft_id: str = Field(..., min_length=1)


class LabelChanges(Operation):
    add_labels: list[str] | None = None
    remove_labels: list[str] | None = None


class MailContent(Operation):
    labels: list[str] | None = None
    reply_to: list[str] | None = None
    text: str | None = None
    html: str | None = None


class Recipients(Operation):
    to: list[str] | None = None
    cc: list[str] | None = None
    bcc: list[str] | None = None


class Compose(MailContent, Recipients):
    subject: str | None = None


class GetIdentity(Operation):
    operation: Literal["get_identity"] = Field("get_identity", json_schema_extra={"ui:hidden": True})


class ListInboxes(Page):
    operation: Literal["list_inboxes"] = Field("list_inboxes", json_schema_extra={"ui:hidden": True})


class CreateInbox(Operation):
    operation: Literal["create_inbox"] = Field("create_inbox", json_schema_extra={"ui:hidden": True})
    username: str | None = None
    domain: str | None = None
    display_name: str | None = None
    client_id: str | None = None


class GetInbox(InboxOperation):
    operation: Literal["get_inbox"] = Field("get_inbox", json_schema_extra={"ui:hidden": True})


class UpdateInbox(InboxOperation):
    operation: Literal["update_inbox"] = Field("update_inbox", json_schema_extra={"ui:hidden": True})
    display_name: str | None = None
    status: Literal["active", "deactivated"] | None = Field(None, description="Deactivating stops both sending and receiving mail.")


class DeleteInbox(InboxOperation):
    operation: Literal["delete_inbox"] = Field("delete_inbox", json_schema_extra={"ui:hidden": True})


class ListThreads(MailPage):
    operation: Literal["list_threads"] = Field("list_threads", json_schema_extra={"ui:hidden": True})


class GetThread(ThreadOperation):
    operation: Literal["get_thread"] = Field("get_thread", json_schema_extra={"ui:hidden": True})


class UpdateThread(ThreadOperation, LabelChanges):
    operation: Literal["update_thread"] = Field("update_thread", json_schema_extra={"ui:hidden": True})


class DeleteThread(ThreadOperation):
    operation: Literal["delete_thread"] = Field("delete_thread", json_schema_extra={"ui:hidden": True})


class ListMessages(MailPage):
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})


class GetMessage(MessageOperation):
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})


class UpdateMessage(MessageOperation, LabelChanges):
    operation: Literal["update_message"] = Field("update_message", json_schema_extra={"ui:hidden": True})


class DeleteMessage(MessageOperation):
    operation: Literal["delete_message"] = Field("delete_message", json_schema_extra={"ui:hidden": True})


class SendMessage(InboxOperation, Compose):
    to: list[str] = Field(..., min_length=1)
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})


class ReplyToMessage(MessageOperation, MailContent, Recipients):
    operation: Literal["reply_to_message"] = Field("reply_to_message", json_schema_extra={"ui:hidden": True})
    reply_all: bool | None = None


class ReplyAllMessage(MessageOperation, MailContent):
    operation: Literal["reply_all_message"] = Field("reply_all_message", json_schema_extra={"ui:hidden": True})


class ForwardMessage(MessageOperation, Compose):
    to: list[str] = Field(..., min_length=1)
    operation: Literal["forward_message"] = Field("forward_message", json_schema_extra={"ui:hidden": True})


class ListDrafts(MailPage):
    operation: Literal["list_drafts"] = Field("list_drafts", json_schema_extra={"ui:hidden": True})


class CreateDraft(InboxOperation, Compose):
    operation: Literal["create_draft"] = Field("create_draft", json_schema_extra={"ui:hidden": True})
    in_reply_to: str | None = None
    forward_of: str | None = None
    reply_all: bool | None = None
    send_at: datetime | None = Field(None, description="RFC 3339 scheduled send time.")
    client_id: str | None = None


class GetDraft(DraftOperation):
    operation: Literal["get_draft"] = Field("get_draft", json_schema_extra={"ui:hidden": True})


class UpdateDraft(DraftOperation, Recipients, LabelChanges):
    operation: Literal["update_draft"] = Field("update_draft", json_schema_extra={"ui:hidden": True})
    reply_to: list[str] | None = None
    subject: str | None = None
    text: str | None = None
    html: str | None = None


class DeleteDraft(DraftOperation):
    operation: Literal["delete_draft"] = Field("delete_draft", json_schema_extra={"ui:hidden": True})


class SendDraft(DraftOperation, LabelChanges):
    operation: Literal["send_draft"] = Field("send_draft", json_schema_extra={"ui:hidden": True})


# AgentMail's own MCP server: agents get its tools through a person's AgentMail sign-in.
AgentMailMcpCredential = mcp_credential("agent_mail", "https://mcp.agentmail.to/mcp", app="AgentMail")
AgentMailCredential = Union[AgentMailAPIKeyCredential, AgentMailMcpCredential]


AgentMailConfig = Annotated[Union[
    GetIdentity, ListInboxes, CreateInbox, GetInbox, UpdateInbox, DeleteInbox, ListThreads, GetThread, UpdateThread, DeleteThread, ListMessages, GetMessage, UpdateMessage, DeleteMessage, SendMessage, ReplyToMessage, ReplyAllMessage, ForwardMessage, ListDrafts, CreateDraft, GetDraft, UpdateDraft, DeleteDraft, SendDraft
], Field(discriminator="operation")]


class AgentMailFullConfig(NodeConfig[AgentMailConfig, AgentMailCredential]):
    pass


ROUTES = {
    "get_identity": ("GET", "/v0/auth/me"),
    "list_inboxes": ("GET", "/v0/inboxes"),
    "create_inbox": ("POST", "/v0/inboxes"),
    "get_inbox": ("GET", "/v0/inboxes/{inbox_id}"),
    "update_inbox": ("PATCH", "/v0/inboxes/{inbox_id}"),
    "delete_inbox": ("DELETE", "/v0/inboxes/{inbox_id}"),
    "list_threads": ("GET", "/v0/inboxes/{inbox_id}/threads"),
    "get_thread": ("GET", "/v0/inboxes/{inbox_id}/threads/{thread_id}"),
    "update_thread": ("PATCH", "/v0/inboxes/{inbox_id}/threads/{thread_id}"),
    "delete_thread": ("DELETE", "/v0/inboxes/{inbox_id}/threads/{thread_id}"),
    "list_messages": ("GET", "/v0/inboxes/{inbox_id}/messages"),
    "get_message": ("GET", "/v0/inboxes/{inbox_id}/messages/{message_id}"),
    "update_message": ("PATCH", "/v0/inboxes/{inbox_id}/messages/{message_id}"),
    "delete_message": ("DELETE", "/v0/inboxes/{inbox_id}/messages/{message_id}"),
    "send_message": ("POST", "/v0/inboxes/{inbox_id}/messages/send"),
    "reply_to_message": ("POST", "/v0/inboxes/{inbox_id}/messages/{message_id}/reply"),
    "reply_all_message": ("POST", "/v0/inboxes/{inbox_id}/messages/{message_id}/reply-all"),
    "forward_message": ("POST", "/v0/inboxes/{inbox_id}/messages/{message_id}/forward"),
    "list_drafts": ("GET", "/v0/inboxes/{inbox_id}/drafts"),
    "create_draft": ("POST", "/v0/inboxes/{inbox_id}/drafts"),
    "get_draft": ("GET", "/v0/inboxes/{inbox_id}/drafts/{draft_id}"),
    "update_draft": ("PATCH", "/v0/inboxes/{inbox_id}/drafts/{draft_id}"),
    "delete_draft": ("DELETE", "/v0/inboxes/{inbox_id}/drafts/{draft_id}"),
    "send_draft": ("POST", "/v0/inboxes/{inbox_id}/drafts/{draft_id}/send"),
}


class AgentMailNode(WorkflowNode):
    integration_type = "automation-agent-mail"
    credential_provider_labels = {"agent_mail": "AgentMail Account"}
    connection_evidence = ConnectionEvidence(
        noun="AgentMail account", identity_operation="get_identity",
        identity_keys=("organization_id", "scope_id"),
    )

    @classmethod
    def get_config_model(cls):
        return AgentMailFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an AgentMail API key")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in ("inbox_id", "thread_id", "message_id", "draft_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        kwargs = {"params": values} if method == "GET" else ({"json": values} if method in {"POST", "PATCH"} else {})
        key = self.config.credentials.api_key
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            raise ValueError(f"AgentMail HTTP {response.status_code}: {response.text.replace(key, '[redacted]')[:1000]}")
        if method == "DELETE" and not response.content:
            return {"success": True}
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected an AgentMail JSON object")
        return body
