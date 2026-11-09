"""Text Request v3: one published API operation per workflow operation.

API contract: https://www.textrequest.com/dist/swagger/apiv3docs.json
Lists return one page and the provider's pagination metadata. Writes acknowledge
API acceptance; message delivery is reported by the provider's response fields.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from datetime import datetime
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.textrequest.com/api/v3"


class TextRequestAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Text Request API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.textrequest.com/app/integrations/api",
            "x-credential-instructions": "In Text Request, open Integrations, then API, and copy your API key. Administrator access and API access on your plan are required. Paste the key below."})
    credential_type: Literal["text_request_api_key"] = Field("text_request_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Operation):
    page: int = Field(0, ge=0, description="Zero-based page number; increment to read the next page.")
    page_size: int = Field(100, ge=1, le=100, description="Items per page.")


class _Dashboard(_Operation):
    dashboard_id: int = Field(..., ge=1, description="Dashboard ID from List dashboards.")


class _DashboardPage(_Dashboard, _Page):
    pass


class _Contact(_Dashboard):
    phone_number: str = Field(..., min_length=1, max_length=32, description="Contact phone number, including country code.")


class _Group(_Dashboard):
    group_id: int = Field(..., ge=1)


class _Tag(_Dashboard):
    tag_id: str = Field(..., min_length=1, max_length=128)


class _Scheduled(_Dashboard):
    message_id: UUID = Field(..., description="Scheduled message UUID returned by Text Request.")


class ListDashboards(_Page):
    operation: Literal["list_dashboards"] = Field("list_dashboards", json_schema_extra={"ui:hidden": True})


class GetDashboard(_Dashboard):
    operation: Literal["get_dashboard"] = Field("get_dashboard", json_schema_extra={"ui:hidden": True})


class ListContacts(_DashboardPage):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    contact_phone_number: str | None = None
    display_name: str | None = None
    is_resolved: bool | None = None
    is_blocked: bool | None = None
    is_archived: bool | None = None
    is_suppressed: bool | None = None
    has_opted_out: bool | None = None
    tags: str | None = Field(None, description="Comma-separated tag IDs.")
    groups: str | None = Field(None, description="Comma-separated group IDs.")


class GetContact(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class UpsertContact(_Contact):
    operation: Literal["upsert_contact"] = Field("upsert_contact", json_schema_extra={"ui:hidden": True})
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    note: str | None = None
    is_resolved: bool | None = None
    is_blocked: bool | None = None
    is_archived: bool | None = None
    is_suppressed: bool | None = None
    suppressed_reason: str | None = None
    groups: list[int] | None = Field(None, description="Group membership IDs to set.")
    contact_tags: list[str] | None = Field(None, description="Tag IDs to set; an empty list removes all tags.")


class DeleteContact(_Contact):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class SendMessage(_Contact):
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, description="Message text sent to this contact.")
    sender_name: str | None = Field(None, max_length=41)
    schedule_date_utc: str | None = Field(None, description="Optional future ISO 8601 UTC timestamp; omitted sends immediately.")

    @field_validator("schedule_date_utc")
    @classmethod
    def utc_timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError("Use an ISO 8601 UTC timestamp")
        return value


class ListConversations(_DashboardPage):
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    tags: str | None = None
    show_unresolved_only: bool | None = None
    include_archived: bool | None = None


class ListContactMessages(_Contact, _Page):
    operation: Literal["list_contact_messages"] = Field("list_contact_messages", json_schema_extra={"ui:hidden": True})


class ListMessages(_DashboardPage):
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})


class ArchiveConversation(_Contact):
    operation: Literal["archive_conversation"] = Field("archive_conversation", json_schema_extra={"ui:hidden": True})


class UnarchiveConversation(_Contact):
    operation: Literal["unarchive_conversation"] = Field("unarchive_conversation", json_schema_extra={"ui:hidden": True})


class ListGroups(_DashboardPage):
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})


class GetGroup(_Group):
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})


class CreateGroup(_Dashboard):
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    notes: str | None = None


class UpdateGroup(_Group):
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    notes: str | None = None


class DeleteGroup(_Group):
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"ui:hidden": True})


class ListTags(_DashboardPage):
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})


class GetTag(_Tag):
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra={"ui:hidden": True})


class CreateTag(_Dashboard):
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    tag: str = Field(..., min_length=1)
    tag_color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")


class UpdateTag(_Tag):
    operation: Literal["update_tag"] = Field("update_tag", json_schema_extra={"ui:hidden": True})
    tag: str = Field(..., min_length=1)
    tag_color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")


class DeleteTag(_Tag):
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"ui:hidden": True})


class ListScheduledMessages(_DashboardPage):
    operation: Literal["list_scheduled_messages"] = Field("list_scheduled_messages", json_schema_extra={"ui:hidden": True})


class GetScheduledMessage(_Scheduled):
    operation: Literal["get_scheduled_message"] = Field("get_scheduled_message", json_schema_extra={"ui:hidden": True})


class CancelScheduledMessage(_Scheduled):
    operation: Literal["cancel_scheduled_message"] = Field("cancel_scheduled_message", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[
    ListDashboards,
    GetDashboard,
    ListContacts,
    GetContact,
    UpsertContact,
    DeleteContact,
    SendMessage,
    ListConversations,
    ListContactMessages,
    ListMessages,
    ArchiveConversation,
    UnarchiveConversation,
    ListGroups,
    GetGroup,
    CreateGroup,
    UpdateGroup,
    DeleteGroup,
    ListTags,
    GetTag,
    CreateTag,
    UpdateTag,
    DeleteTag,
    ListScheduledMessages,
    GetScheduledMessage,
    CancelScheduledMessage
], Field(discriminator="operation")]


class TextRequestConfig(NodeConfig[Operation, TextRequestAPIKeyCredential]):
    pass


# method, fixed contract route, query fields, body fields, paginated result
OPERATIONS = {
    "list_dashboards": ('GET', '/dashboards', ('page', 'page_size'), (), True),
    "get_dashboard": ('GET', '/dashboards/{dashboard_id}', (), (), False),
    "list_contacts": ('GET', '/dashboards/{dashboard_id}/contacts', ('page', 'page_size', 'contact_phone_number', 'display_name', 'is_resolved', 'is_blocked', 'is_archived', 'is_suppressed', 'has_opted_out', 'tags', 'groups'), (), True),
    "get_contact": ('GET', '/dashboards/{dashboard_id}/contacts/{phone_number}', (), (), False),
    "upsert_contact": ('POST', '/dashboards/{dashboard_id}/contacts/{phone_number}', (), ('first_name', 'last_name', 'display_name', 'note', 'is_resolved', 'is_blocked', 'is_archived', 'is_suppressed', 'suppressed_reason', 'groups', 'contact_tags'), False),
    "delete_contact": ('DELETE', '/dashboards/{dashboard_id}/contacts/{phone_number}', (), (), False),
    "send_message": ('POST', '/dashboards/{dashboard_id}/contacts/{phone_number}/messages', (), ('body', 'sender_name', 'schedule_date_utc'), False),
    "list_conversations": ('GET', '/dashboards/{dashboard_id}/conversations', ('page', 'page_size', 'search', 'tags', 'show_unresolved_only', 'include_archived'), (), True),
    "list_contact_messages": ('GET', '/dashboards/{dashboard_id}/contacts/{phone_number}/messages', ('page', 'page_size'), (), True),
    "list_messages": ('GET', '/dashboards/{dashboard_id}/messages', ('page', 'page_size'), (), True),
    "archive_conversation": ('PUT', '/dashboards/{dashboard_id}/contacts/{phone_number}/conversations/archive', (), (), False),
    "unarchive_conversation": ('PUT', '/dashboards/{dashboard_id}/contacts/{phone_number}/conversations/unarchive', (), (), False),
    "list_groups": ('GET', '/dashboards/{dashboard_id}/groups', ('page', 'page_size'), (), True),
    "get_group": ('GET', '/dashboards/{dashboard_id}/groups/{group_id}', (), (), False),
    "create_group": ('POST', '/dashboards/{dashboard_id}/groups', (), ('name', 'notes'), False),
    "update_group": ('PUT', '/dashboards/{dashboard_id}/groups/{group_id}', (), ('name', 'notes'), False),
    "delete_group": ('DELETE', '/dashboards/{dashboard_id}/groups/{group_id}', (), (), False),
    "list_tags": ('GET', '/dashboards/{dashboard_id}/tags', ('page', 'page_size'), (), True),
    "get_tag": ('GET', '/dashboards/{dashboard_id}/tags/{tag_id}', (), (), False),
    "create_tag": ('POST', '/dashboards/{dashboard_id}/tags', (), ('tag', 'tag_color'), False),
    "update_tag": ('PUT', '/dashboards/{dashboard_id}/tags/{tag_id}', (), ('tag', 'tag_color'), False),
    "delete_tag": ('DELETE', '/dashboards/{dashboard_id}/tags/{tag_id}', (), (), False),
    "list_scheduled_messages": ('GET', '/dashboards/{dashboard_id}/scheduledmessages', ('page', 'page_size'), (), True),
    "get_scheduled_message": ('GET', '/dashboards/{dashboard_id}/scheduledmessages/{message_id}', (), (), False),
    "cancel_scheduled_message": ('DELETE', '/dashboards/{dashboard_id}/scheduledmessages/{message_id}', (), (), False),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(secret, "[redacted]"): _redact(item, secret) for key, item in value.items()}
    return value


class TextRequestNode(WorkflowNode):
    integration_type = "automation-text-request"
    connection_evidence = ConnectionEvidence(operation="list_dashboards", noun="dashboards",
        label_keys=("name", "phone", "id"))

    @classmethod
    def get_config_model(cls):
        return TextRequestConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Text Request API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, template, query_fields, body_fields, paginated = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        route = template.format_map({key: quote(str(value), safe="") for key, value in values.items()})
        params = {key: values[key] for key in query_fields if key in values}
        payload = {key: values[key] for key in body_fields if key in values} if body_fields else None
        try:
            async with guarded_async_client() as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"x-api-key": secret, "Accept": "application/json"},
                    params=params, **({"json": payload} if payload is not None else {}),
                    timeout=30, follow_redirects=False)
        except httpx.HTTPError:
            raise ValueError("Text Request could not be reached; a write may have been accepted, so inspect before retrying") from None
        data = response.json() if response.content else None
        if response.status_code >= 300:
            message = data.get("message") if isinstance(data, dict) else None
            output = {"status": "error", "http_status": response.status_code,
                "error": message or "Text Request rejected the request"}
        elif isinstance(data, dict) and (data.get("status") == "error" or data.get("errorCode") is not None):
            output = {"status": "error", "http_status": response.status_code,
                "error": data.get("message") or "Text Request reported an error", "data": data}
        else:
            output = {"status": "success", "http_status": response.status_code, "data": data}
            if paginated and isinstance(data, dict):
                meta = data.get("meta")
                if isinstance(meta, dict):
                    page, size, total = (meta.get(key) for key in ("page", "page_size", "total_items"))
                    if all(type(value) is int for value in (page, size, total)) and size > 0:
                        output["next_page"] = page + 1 if (page + 1) * size < total else None
        output = _redact(output, secret)
        await self.emit(output)
        return output
