"""Chili Piper tenant API, pinned to the published 1.1021.1 contract.

Each operation makes exactly one request. Meeting writes can send calendar
invites and notifications; failed or interrupted writes are never retried.
Contract: https://fire.chilipiper.com/api/fire-edge/public/org/docs/docs.yaml
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://fire.chilipiper.com/api/fire-edge"
CREDENTIAL_TYPE = "chili_piper_api_key"


def _identifier(value: str) -> str:
    if not value or value in {".", ".."} or any(c.isspace() or c in "/\\" or ord(c) < 32 for c in value):
        raise ValueError("Use a single Chili Piper resource ID")
    return value


ResourceId = Annotated[str, Field(min_length=1, max_length=512, pattern=r"[^\s\\/]+")]
Email = Annotated[str, Field(min_length=3, max_length=320, pattern=r".+@.+")]


class ChiliPiperAPIKey(BaseModel):
    model_config = ConfigDict(
        title="Chili Piper API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://fire.chilipiper.com/api/fire-edge/public/org/docs/docs.yaml",
            "x-credential-instructions": "In Chili Piper Admin Center → API Keys, create a tenant API key with permissions for the operations you need. Paste only the key. NoClick sends it as Authorization: Bearer to fire.chilipiper.com. Workspace reads prove the connection; individual writes may require additional key permissions.",
        },
    )
    credential_type: Literal["chili_piper_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def ids(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            return _identifier(value)
        if info.field_name.endswith("_ids") and isinstance(value, list):
            for item in value:
                _identifier(item)
        return value


class _Page(_Operation):
    page: int = Field(0, ge=0, strict=True, description="Zero-based page index. Pass next_page from the previous result.")
    page_size: int = Field(10, ge=1, le=50, strict=True, description="Number of records to request, up to 50.")


class GetTenant(_Operation):
    operation: Literal["get_tenant"] = Field("get_tenant", title="Get Tenant", json_schema_extra={"ui:hidden": True})


class ListWorkspaces(_Page):
    operation: Literal["list_workspaces"] = Field("list_workspaces", title="List Workspaces", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, description="Case-insensitive substring of the workspace name.")


class GetWorkspace(_Operation):
    operation: Literal["get_workspace"] = Field("get_workspace", title="Get Workspace", json_schema_extra={"ui:hidden": True})
    workspace_id: ResourceId


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})
    workspace_id: ResourceId | None = None


class GetUser(_Operation):
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})
    user_id: ResourceId


class FindUsers(_Page):
    operation: Literal["find_users"] = Field("find_users", title="Find Users", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, description="Search by email or name.")


class ListTeams(_Page):
    operation: Literal["list_teams"] = Field("list_teams", title="List Teams", json_schema_extra={"ui:hidden": True})


def _instant(value):
    if value is None:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Use an ISO-8601 date and time with a timezone") from None
    return value


class ListMeetings(_Page):
    operation: Literal["list_meetings"] = Field("list_meetings", title="List Meetings", json_schema_extra={"ui:hidden": True})
    start: str = Field(..., description="Inclusive ISO-8601 instant; the query window must be at most seven days.")
    end: str = Field(..., description="Exclusive ISO-8601 instant, after start.")
    workspace_ids: list[ResourceId] | None = Field(None, min_length=1)
    status: list[Literal["Active", "Canceled", "NoShow", "Completed"]] | None = Field(None, min_length=1)
    host_ids: list[ResourceId] | None = Field(None, min_length=1)
    assignee_ids: list[ResourceId] | None = Field(None, min_length=1)
    guest_email: Email | None = None
    _dates = field_validator("start", "end")(_instant)

    @model_validator(mode="after")
    def window(self):
        delta = datetime.fromisoformat(self.end.replace("Z", "+00:00")) - datetime.fromisoformat(self.start.replace("Z", "+00:00"))
        if not timedelta(0) < delta <= timedelta(days=7):
            raise ValueError("Meeting query windows must be greater than zero and at most seven days")
        return self


class _Meeting(_Operation):
    meeting_id: UUID = Field(..., description="Chili Piper meeting UUID.")


class GetMeeting(_Meeting):
    operation: Literal["get_meeting"] = Field("get_meeting", title="Get Meeting", json_schema_extra={"ui:hidden": True})


class CreateMeeting(_Operation):
    operation: Literal["create_meeting"] = Field("create_meeting", title="Create Meeting", description="Books immediately and sends calendar invites. Only personal meeting types owned by this host are supported. An unavailable slot can return Failure without an HTTP error.", json_schema_extra={"ui:hidden": True})
    host_user_id: ResourceId
    meeting_type_id: UUID = Field(..., description="The host's personal meeting type; obtain it with List Personal Meeting Types.")
    start_time: str = Field(..., description="ISO-8601 instant in a free slot; duration comes from the meeting type.")
    guest_email: Email
    guest_first_name: str | None = Field(None, description="Personal meeting types require this by default.")
    guest_last_name: str | None = Field(None, description="Personal meeting types require this by default.")
    guest_timezone: str | None = Field(None, description="Guest IANA timezone, e.g. America/New_York.")
    guest_crm_id: str | None = None
    meeting_notifications: Literal["SendNotifications", "DoNotSendNotifications"] | None = Field(None, description="Controls internal email/Slack notifications only; guest calendar invites are always sent.")
    _start = field_validator("start_time")(_instant)


class UpdateMeeting(_Meeting):
    operation: Literal["update_meeting"] = Field("update_meeting", title="Update Meeting", description="Reschedules or edits a meeting; triggers calendar and CRM updates and may send notification emails.", json_schema_extra={"ui:hidden": True})
    start_time: str | None = None
    host_id: ResourceId | None = None
    primary_guest_attendance: Literal["Required", "Optional", "Removed"] | None = None
    _start = field_validator("start_time")(_instant)

    @model_validator(mode="after")
    def change(self):
        if all(value is None for value in (self.start_time, self.host_id, self.primary_guest_attendance)):
            raise ValueError("Choose at least one meeting field to update")
        return self


class CancelMeeting(_Meeting):
    operation: Literal["cancel_meeting"] = Field("cancel_meeting", title="Cancel Meeting", description="Permanently cancels the meeting; may email attendees.", json_schema_extra={"ui:hidden": True})


class MarkMeetingNoShow(_Meeting):
    operation: Literal["mark_meeting_no_show"] = Field("mark_meeting_no_show", title="Mark Meeting No Show", description="Changes attendance and distribution counters.", json_schema_extra={"ui:hidden": True})


class MarkMeetingShowed(_Meeting):
    operation: Literal["mark_meeting_showed"] = Field("mark_meeting_showed", title="Mark Meeting Showed", json_schema_extra={"ui:hidden": True})


class ListPersonalLinks(_Operation):
    operation: Literal["list_personal_links"] = Field("list_personal_links", title="List Personal Scheduling Links", json_schema_extra={"ui:hidden": True})
    user_id: ResourceId


class ListPersonalMeetingTypes(_Page):
    operation: Literal["list_personal_meeting_types"] = Field("list_personal_meeting_types", title="List Personal Meeting Types", json_schema_extra={"ui:hidden": True})
    workspace_id: ResourceId | None = Field(None, description="Use the host's personalWorkspaceId from Find Users to find their own booking templates.")


class ListWebhooks(_Operation):
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Webhooks", json_schema_extra={"ui:hidden": True})


class _Webhook(_Operation):
    trigger_type: Literal["MeetingCreated", "MeetingUpdated", "MeetingDeleted"]
    url: str = Field(..., min_length=1, description="Destination URL registered with Chili Piper. NoClick does not fetch this URL.")


class CreateWebhook(_Webhook):
    operation: Literal["create_webhook"] = Field("create_webhook", title="Create Webhook", json_schema_extra={"ui:hidden": True})
    enabled: bool = Field(True, strict=True)


class UpdateWebhook(_Webhook):
    operation: Literal["update_webhook"] = Field("update_webhook", title="Update Webhook", json_schema_extra={"ui:hidden": True})
    enabled: bool = Field(..., strict=True)


class DeleteWebhook(_Webhook):
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True})


ChiliPiperOperation = Annotated[Union[
    GetTenant, ListWorkspaces, GetWorkspace, ListUsers, GetUser, FindUsers,
    ListTeams, ListMeetings, GetMeeting, CreateMeeting, UpdateMeeting,
    CancelMeeting, MarkMeetingNoShow, MarkMeetingShowed, ListPersonalLinks,
    ListPersonalMeetingTypes, ListWebhooks, CreateWebhook, UpdateWebhook, DeleteWebhook,
], Field(discriminator="operation")]


class ChiliPiperConfig(NodeConfig[ChiliPiperOperation, ChiliPiperAPIKey]):
    pass


# One fixed provider contract operation per user operation. No arbitrary URL,
# method, query or JSON-body passthrough is available.
ROUTES = {
    "get_tenant": ("GET", "/v1/org/tenant/get"),
    "list_workspaces": ("GET", "/v1/org/workspace"),
    "get_workspace": ("GET", "/v1/org/workspace/{workspace_id}"),
    "list_users": ("GET", "/v1/org/workspace/users"),
    "get_user": ("GET", "/v1/org/user/read/{user_id}"),
    "find_users": ("GET", "/v1/org/user/find"),
    "list_teams": ("PUT", "/v2/org/team"),
    "list_meetings": ("PUT", "/v2/org/meetings/meetings"),
    "get_meeting": ("GET", "/v1/org/meetings/get/{meeting_id}"),
    "create_meeting": ("POST", "/v1/org/meetings/create"),
    "update_meeting": ("PATCH", "/v1/org/meetings/{meeting_id}"),
    "cancel_meeting": ("POST", "/v2/org/meetings/cancel/{meeting_id}"),
    "mark_meeting_no_show": ("POST", "/v2/org/meetings/noshow/{meeting_id}"),
    "mark_meeting_showed": ("POST", "/v2/org/meetings/showed/{meeting_id}"),
    "list_personal_links": ("GET", "/v1/org/schedulingLinks/list-personal-v2/{user_id}"),
    "list_personal_meeting_types": ("GET", "/v1/org/personal-meeting-types"),
    "list_webhooks": ("GET", "/v1/org/webhook/list"),
    "create_webhook": ("POST", "/v1/org/webhook"),
    "update_webhook": ("PUT", "/v1/org/webhook"),
    "delete_webhook": ("DELETE", "/v1/org/webhook"),
}
_ALIASES = {
    "page_size": "pageSize", "workspace_id": "workspaceId", "workspace_ids": "workspaceIds",
    "host_ids": "hostIds", "assignee_ids": "assigneeIds", "guest_email": "guestEmail",
    "host_user_id": "hostUserId", "meeting_type_id": "meetingTypeId", "start_time": "startTime",
    "guest_first_name": "guestFirstName", "guest_last_name": "guestLastName",
    "guest_timezone": "guestTimezone", "guest_crm_id": "guestCrmId",
    "meeting_notifications": "meetingNotifications", "host_id": "hostId",
    "primary_guest_attendance": "primaryGuestAttendance", "trigger_type": "triggerType",
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class ChiliPiperNode(WorkflowNode):
    integration_type = "automation-chili-piper"
    connection_evidence = ConnectionEvidence(
        noun="workspaces", operation="list_workspaces", identity_operation="get_tenant",
        identity_keys=("subdomain", "tenantId"),
    )
    edit_examples = ["Find a host by email", "Book a meeting with this host", "Cancel a meeting", "List upcoming meetings"]

    @classmethod
    def get_config_model(cls):
        return ChiliPiperConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Chili Piper API key")
        key = self.config.credentials.api_key
        op = self.config.config
        method, route = ROUTES[op.operation]
        fields = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in tuple(fields):
            placeholder = "{" + field + "}"
            if placeholder in route:
                route = route.replace(placeholder, quote(str(fields.pop(field)), safe=""))
        values = {_ALIASES.get(name, name): value for name, value in fields.items()}
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        kwargs = {"params": values} if method == "GET" else {"json": values}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, **kwargs)
        except httpx.HTTPError:
            return {"status": "error", "message": "Chili Piper request did not complete", "write_outcome": "unverified" if method != "GET" else None}

        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("errorMessage")
            except (ValueError, AttributeError):
                message = None
            return {"status": "error", "http_status": response.status_code,
                    "message": _redact(message, key) if isinstance(message, str) else "Chili Piper rejected the request"}
        if not response.content:
            if op.operation != "delete_webhook":
                raise ValueError("Chili Piper returned an empty response")
            return {"status": "success", "data": None}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Chili Piper returned an invalid JSON response") from None
        if not isinstance(payload, dict):
            raise ValueError("Chili Piper returned an invalid response object")
        if "errorCode" in payload or payload.get("type") == "Failure" or (op.operation == "create_meeting" and "reason" in payload and "meetingId" not in payload):
            return _redact({"status": "error", "data": payload, "message": payload.get("errorMessage", payload.get("reason", "Chili Piper could not complete the operation"))}, key)

        output = {"status": "success", "data": payload}
        if isinstance(op, _Page) and op.operation != "list_meetings":
            rows = payload.get("results", [])
            total, page, size = (payload.get(k) for k in ("total", "page", "pageSize"))
            if not isinstance(rows, list) or any(type(v) is not int for v in (total, page, size)) or total < 0 or page != op.page or size != op.page_size:
                raise ValueError("Chili Piper returned invalid pagination metadata")
            output.update(items=rows, has_more=(page + 1) * size < total,
                          next_page=page + 1 if (page + 1) * size < total else None)
        elif op.operation == "list_meetings":
            has_more = payload.get("hasMoreItems")
            if type(has_more) is not bool:
                raise ValueError("Chili Piper omitted meeting pagination metadata")
            output.update(items=payload.get("data"), has_more=has_more,
                          next_page=op.page + 1 if has_more else None)
        elif op.operation == "get_tenant":
            tenant = payload.get("tenantData")
            if not isinstance(tenant, dict) or not tenant.get("tenantId"):
                raise ValueError("Chili Piper omitted tenant identity")
            output.update(tenant)
        return _redact(output, key)
