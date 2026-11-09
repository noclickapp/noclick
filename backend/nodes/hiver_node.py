"""Hiver v1 inbox and conversation operations, using a pasted admin API key.

Each operation makes one published API call. Lists return one page and the
provider's continuation token; writes are never automatically retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api2.hiverhq.com/v1"
DOCS = "https://developer.hiverhq.com/hiver-api"


class HiverAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hiver API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://help.hiverhq.com/apps-and-integrations/hiver-api",
        "x-credential-instructions": "In Hiver's Admin Panel, open Integrations → Developer APIs, create and enable an API key, then paste it here. Hiver API keys have admin access. NoClick verifies the key by listing your inboxes.",
    })
    credential_type: Literal["hiver_api_key"] = Field("hiver_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(10, ge=10, le=100, description="Results per page, from 10 to 100.")
    next_page: str | None = Field(None, max_length=8192, description="Copy data.pagination.next_page from the previous result. Omit for the first page.")


class _Inbox(_Input):
    inbox_id: str = Field(..., min_length=1, max_length=32, pattern=r"^[0-9]+$", title="Inbox ID")


class ListInboxes(_Page):
    operation: Literal["list_inboxes"] = "list_inboxes"


class GetInbox(_Inbox):
    operation: Literal["get_inbox"] = "get_inbox"


class ListUsers(_Inbox, _Page):
    operation: Literal["list_users"] = "list_users"


class SearchUsers(_Inbox):
    operation: Literal["search_users"] = "search_users"
    email: str = Field(..., min_length=3, max_length=320, description="Exact email address to search for.")


class ListTags(_Inbox, _Page):
    operation: Literal["list_tags"] = "list_tags"


class SearchTags(_Inbox):
    operation: Literal["search_tags"] = "search_tags"
    name: str = Field(..., min_length=1, max_length=500)


class CreateTag(_Inbox):
    operation: Literal["create_tag"] = "create_tag"
    name: str = Field(..., min_length=1, max_length=500)
    color_hexcode: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    description: str | None = Field(None, max_length=10000)


class ListConversations(_Inbox, _Page):
    operation: Literal["list_conversations"] = "list_conversations"


class _Conversation(_Inbox):
    conversation_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Hiver conversation ID or Gmail thread ID.")
    user_email: str | None = Field(None, max_length=320, description="Required when the Gmail thread ID belongs to an individual user's mailbox.")


class GetConversation(_Conversation):
    operation: Literal["get_conversation"] = "get_conversation"


class UpdateConversation(_Conversation):
    operation: Literal["update_conversation"] = "update_conversation"
    status_name: str | None = Field(None, min_length=1, max_length=100, description="Hiver status name, for example open or closed.")
    assignee_email: str | None = Field(None, min_length=3, max_length=320, description="Email of the inbox member to assign.")

    @model_validator(mode="after")
    def change_required(self):
        if self.status_name is None and self.assignee_email is None:
            raise ValueError("Supply a status name or assignee email")
        return self


class CreateSharedDraft(_Inbox):
    operation: Literal["create_shared_draft"] = "create_shared_draft"
    body: str = Field(..., min_length=1, max_length=100000, description="Shared draft email body.")
    gmail_message_id: str | None = Field(None, min_length=1, max_length=998, description="Source user's Gmail message ID, or global SMTP Message-ID. Required unless Hiver message ID is supplied.")
    hiver_message_id: int | None = Field(None, gt=0)
    reply_type: str = Field("reply", max_length=50)

    @model_validator(mode="after")
    def message_required(self):
        if self.gmail_message_id is None and self.hiver_message_id is None:
            raise ValueError("Supply a Gmail message ID or Hiver message ID")
        return self


class CreateNote(_Conversation):
    operation: Literal["create_note"] = "create_note"
    content: str = Field(..., min_length=1, max_length=100000, description="Note text or supported HTML. For mentions, include each teammate's bare email here too.")
    mentions: list[str] | None = Field(None, max_length=100, description="Teammate email addresses to mention.")
    notify_all: bool = Field(False, description="Notify every inbox member.")
    parent_note_id: str | None = Field(None, max_length=128)


HiverConfig = Annotated[Union[ListInboxes, GetInbox, ListUsers, SearchUsers, ListTags, SearchTags,
    CreateTag, ListConversations, GetConversation, UpdateConversation, CreateSharedDraft, CreateNote], Field(discriminator="operation")]


class HiverFullConfig(NodeConfig[HiverConfig, HiverAPIKeyCredential]):
    pass


class HiverNode(WorkflowNode):
    integration_type = "automation-hiver"
    connection_evidence = ConnectionEvidence(operation="list_inboxes", noun="Hiver inboxes")

    @classmethod
    def get_config_model(cls):
        return HiverFullConfig

    async def execute(self, inputs):
        config = self.config
        if not config.credentials:
            raise ValueError("Connect a Hiver API key")
        op = config.config
        action = op.operation
        path, method, params, kwargs = "/inboxes", "GET", {}, {}
        if isinstance(op, _Inbox):
            path += "/" + quote(op.inbox_id, safe="")
        if isinstance(op, _Page):
            params["limit"] = op.limit
            if op.next_page is not None:
                params["next_page"] = op.next_page
        if action in {"list_users", "search_users"}:
            path += "/users" + ("/search" if action == "search_users" else "")
            if action == "search_users":
                params["email"] = op.email
        elif action in {"list_tags", "search_tags", "create_tag"}:
            path += "/tags" + ("/search" if action == "search_tags" else "")
            if action == "search_tags":
                params["name"] = op.name
            elif action == "create_tag":
                method = "POST"
                kwargs["json"] = op.model_dump(include={"name", "color_hexcode", "description"}, exclude_none=True)
        elif action == "list_conversations":
            path += "/conversations"
        elif isinstance(op, _Conversation):
            path += "/conversations/" + quote(op.conversation_id, safe="")
            if op.user_email is not None:
                params["user_email"] = op.user_email
            if action == "update_conversation":
                method, body = "PATCH", {}
                if op.status_name is not None:
                    body["status"] = {"name": op.status_name}
                if op.assignee_email is not None:
                    body["assignee"] = {"email": op.assignee_email}
                kwargs["json"] = body
            elif action == "create_note":
                path += "/notes"
                method = "POST"
                fields = {"content": op.content}
                if op.notify_all:
                    fields["notify_all"] = "true"
                if op.parent_note_id is not None:
                    fields["parent_note_id"] = op.parent_note_id
                parts = [(key, (None, value)) for key, value in fields.items()]
                parts.extend(("mentions", (None, value)) for value in op.mentions or [])
                kwargs["files"] = parts
        elif action == "create_shared_draft":
            path += "/conversations/shared-drafts"
            method = "POST"
            fields = op.model_dump(include={"body", "gmail_message_id", "hiver_message_id", "reply_type"}, exclude_none=True)
            kwargs["files"] = [(key, (None, str(value))) for key, value in fields.items()]
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"Authorization": "Bearer " + config.credentials.api_key, "Accept": "application/json"}, **kwargs)
        if response.status_code >= 300 or response.status_code < 200:
            # Keep the provider's rejection text for the shared connect verdict,
            # while removing any accidental echo of our credential.
            detail = response.text[:2000].replace(config.credentials.api_key, "[redacted]")
            raise ValueError(f"Hiver HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            return {"status": "success", "http_status": 204}
        if len(response.content) > 10_000_000:
            raise ValueError("Hiver response exceeds 10 MB")
        body = response.json()
        if not isinstance(body, dict) or "errors" in body or "Message" in body or "data" not in body:
            raise ValueError("Hiver returned an unexpected response envelope")
        return {"status": "success", "http_status": response.status_code, "data": body["data"]}
