"""Arbox public API v3 operations, pinned to the provider's 0.0.1 contract.

Contract: https://arboxserver.arboxapp.com/docs/api.json
Each operation makes one request. Lists return one explicit page; writes return
provider acknowledgements, without claiming downstream effects or readback.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://arboxserver.arboxapp.com/api/public"
CREDENTIAL_TYPE = "arbox_api_key"


class ArboxAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Arbox API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://arboxserver.arboxapp.com/docs",
            "x-credential-instructions": "Paste your Arbox API key. NoClick sends it in the api-key header to Arbox's public API. The location read checks the connected account; available operations depend on your Arbox permissions.",
        },
    )
    credential_type: Literal["arbox_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def check_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page", description="One page per run; repeat with the next page to continue.")
    limit: int = Field(100, ge=1, le=500, title="Items per page")
    location_id: int | None = Field(None, ge=1, title="Location ID")
    sort: Literal["asc", "desc"] = Field("asc", title="Sort order")


class _DateRange(_Page):
    from_date: date = Field(..., title="Start date")
    to_date: date = Field(..., title="End date")

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.to_date < self.from_date:
            raise ValueError("End date must be on or after start date")
        return self


class _Contact(_Input):
    first_name: str | None = Field(None, min_length=1, title="First name")
    last_name: str | None = Field(None, title="Last name")
    email: str | None = Field(None, title="Email")
    phone: str | None = Field(None, title="Phone")
    additional_phone: str | None = Field(None, title="Additional phone")
    gender: Literal["male", "female", "other"] | None = None
    birthday: date | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    allow_sms: Literal["yes", "no"] | None = Field(None, title="Allow SMS", description="Only set with the person's consent; omission preserves provider defaults.")
    allow_email: Literal["yes", "no"] | None = Field(None, title="Allow email", description="Only set with the person's consent; omission preserves provider defaults.")


class ArboxListLocations(_Page):
    operation: Literal["list_locations"] = Field("list_locations", title="List Locations", json_schema_extra={"ui:hidden": True})


class ArboxListLeads(_Page):
    operation: Literal["list_leads"] = Field("list_leads", title="List Leads", json_schema_extra={"ui:hidden": True})


class ArboxListConvertedLeads(_Page):
    operation: Literal["list_converted_leads"] = Field("list_converted_leads", title="List Converted Leads", json_schema_extra={"ui:hidden": True})


class ArboxListLostLeads(_Page):
    operation: Literal["list_lost_leads"] = Field("list_lost_leads", title="List Lost Leads", json_schema_extra={"ui:hidden": True})


class ArboxListLeadStatuses(_Page):
    operation: Literal["list_lead_statuses"] = Field("list_lead_statuses", title="List Lead Statuses", json_schema_extra={"ui:hidden": True})


class ArboxListLeadSources(_Page):
    operation: Literal["list_lead_sources"] = Field("list_lead_sources", title="List Lead Sources", json_schema_extra={"ui:hidden": True})


class ArboxListLostReasons(_Page):
    operation: Literal["list_lost_reasons"] = Field("list_lost_reasons", title="List Lost Reasons", json_schema_extra={"ui:hidden": True})


class ArboxListTaskTypes(_Page):
    operation: Literal["list_task_types"] = Field("list_task_types", title="List Task Types", json_schema_extra={"ui:hidden": True})


class ArboxListStaffMembers(_Page):
    operation: Literal["list_staff_members"] = Field("list_staff_members", title="List Staff Members", json_schema_extra={"ui:hidden": True})


class ArboxCreateLead(_Contact):
    operation: Literal["create_lead"] = Field("create_lead", title="Create Lead", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, title="First name")
    phone: str = Field(..., min_length=1, title="Phone")
    location_id: int = Field(..., ge=1, title="Location ID")
    source_id: int | None = Field(None, ge=1, title="Source ID")
    status_id: int | None = Field(None, ge=1, title="Status ID")
    campaign: str | None = None
    assignee_id: int | None = Field(None, ge=1, title="Assignee ID")
    comment: str | None = None


class ArboxUpdateLeadStatus(_Input):
    operation: Literal["update_lead_status"] = Field("update_lead_status", title="Update Lead Status", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1, title="Lead user ID")
    status_id: int = Field(..., ge=1, title="Status ID")
    comment: str | None = None


class ArboxMarkLeadLost(_Input):
    operation: Literal["mark_lead_lost"] = Field("mark_lead_lost", title="Mark Lead Lost", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1, title="Lead user ID")
    lost_reason_id: int = Field(..., ge=1, title="Lost reason ID")
    comment: str | None = None


class ArboxAddLeadNote(_Input):
    operation: Literal["add_lead_note"] = Field("add_lead_note", title="Add Lead Note", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1, title="User ID")
    description: str = Field(..., min_length=1, title="Note")


class ArboxAddUserNote(_Input):
    operation: Literal["add_user_note"] = Field("add_user_note", title="Add User Note", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1, title="User ID")
    description: str = Field(..., min_length=1, title="Note")


class ArboxListTasks(_DateRange):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True})
    include_completed: Literal["0", "1"] | None = None
    task_type_id: int | None = Field(None, ge=1, title="Task type ID")


class ArboxCreateTask(_Input):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", description='Creates a task with a reminder; Arbox controls reminder delivery.', json_schema_extra={"ui:hidden": True})
    location_id: int = Field(..., ge=1, title="Location ID")
    task_type_id: int = Field(..., ge=1, title="Task type ID")
    reminder_date: date = Field(..., title="Reminder date")
    reminder_time: str = Field(..., pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$", title="Reminder time", description="24-hour HH:MM")
    user_id: int | None = Field(None, ge=1, title="User ID")
    assigned_to: int | None = Field(None, ge=1, title="Assigned staff ID")
    description: str | None = None


class ArboxCompleteTask(_Input):
    operation: Literal["complete_task"] = Field("complete_task", title="Complete Task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., ge=1, title="Task ID")


class ArboxListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})
    active: Literal["0", "1"] | None = None
    only_clients: Literal["0", "1"] | None = None


class ArboxGetUser(_Input):
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1, title="User ID")


class ArboxCreateUser(_Contact):
    operation: Literal["create_user"] = Field("create_user", title="Create User", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, title="First name")
    last_name: str = Field(..., min_length=1, title="Last name")
    location_id: int | None = Field(None, ge=1, title="Location ID")
    active: bool | None = None
    send_welcome_email: bool = Field(False, title="Send welcome email", description="Explicitly requests a welcome email when true; delivery is controlled by Arbox.")


class ArboxUpdateUser(_Contact):
    operation: Literal["update_user"] = Field("update_user", title="Update User", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1, title="User ID")
    location_id: int | None = Field(None, ge=1, title="Location ID")
    active: Literal[0, 1] | None = None
    assignee_id: int | None = Field(None, ge=1, title="Assignee ID")

    @model_validator(mode="after")
    def changed_field(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "user_id"}):
            raise ValueError("Provide at least one user field to update")
        return self


class ArboxSearchUsers(_Page):
    operation: Literal["search_users"] = Field("search_users", title="Search Users", json_schema_extra={"ui:hidden": True})
    type: Literal["email", "phone", "user_id", "personal_id", "rf_id"] = Field(..., title="Search by")
    value: str = Field(..., min_length=1, title="Search value")


class ArboxListMembershipTypes(_Page):
    operation: Literal["list_membership_types"] = Field("list_membership_types", title="List Membership Types", json_schema_extra={"ui:hidden": True})
    active: Literal["0", "1"] | None = None
    with_membership_types_props: Literal["0", "1"] | None = None


class ArboxListUserMemberships(_Page):
    operation: Literal["list_user_memberships"] = Field("list_user_memberships", title="List User Memberships", json_schema_extra={"ui:hidden": True})
    active: Literal["0", "1", "2"] | None = None
    membership_type_id: int | None = Field(None, ge=1, title="Membership type ID")
    membership_user_id: int | None = Field(None, ge=1, title="Membership user ID")
    user_id: int | None = Field(None, ge=1, title="User ID")
    type: str | None = Field(None, title="Membership type filter")


class ArboxListSchedule(_DateRange):
    operation: Literal["list_schedule"] = Field("list_schedule", title="List Schedule", json_schema_extra={"ui:hidden": True})
    box_category_id: int | None = Field(None, ge=1, title="Service ID")
    staff_id: int | None = Field(None, ge=1, title="Staff ID")
    schedule_user_id: int | None = Field(None, ge=1, title="Schedule user ID")
    cancelled: Literal["0", "1"] | None = None
    registration_count: Literal["0", "1"] | None = None
    registration_details: Literal["0", "1"] | None = None
    transparent: Literal["0", "1"] | None = None
    waiting_list_count: Literal["0", "1"] | None = None


ArboxOperation = Annotated[Union[
    ArboxListLocations,
    ArboxListLeads,
    ArboxListConvertedLeads,
    ArboxListLostLeads,
    ArboxListLeadStatuses,
    ArboxListLeadSources,
    ArboxListLostReasons,
    ArboxListTaskTypes,
    ArboxListStaffMembers,
    ArboxCreateLead,
    ArboxUpdateLeadStatus,
    ArboxMarkLeadLost,
    ArboxAddLeadNote,
    ArboxAddUserNote,
    ArboxListTasks,
    ArboxCreateTask,
    ArboxCompleteTask,
    ArboxListUsers,
    ArboxGetUser,
    ArboxCreateUser,
    ArboxUpdateUser,
    ArboxSearchUsers,
    ArboxListMembershipTypes,
    ArboxListUserMemberships,
    ArboxListSchedule
], Field(discriminator="operation")]


class ArboxFullConfig(NodeConfig[ArboxOperation, ArboxAPIKeyCredential]):
    pass


ROUTES = {'list_locations': ('GET', '/v3/locations'), 'list_leads': ('GET', '/v3/leads'), 'list_converted_leads': ('GET', '/v3/leads/converted'), 'list_lost_leads': ('GET', '/v3/leads/lost'), 'list_lead_statuses': ('GET', '/v3/statuses'), 'list_lead_sources': ('GET', '/v3/sources'), 'list_lost_reasons': ('GET', '/v3/lostReasons'), 'list_task_types': ('GET', '/v3/tasks/types'), 'list_staff_members': ('GET', '/v3/users/allStaffMembers'), 'create_lead': ('POST', '/v3/leads'), 'update_lead_status': ('POST', '/v3/leads/updateStatus'), 'mark_lead_lost': ('POST', '/v3/leads/markAsLost'), 'add_lead_note': ('POST', '/v3/leads/createNote'), 'add_user_note': ('POST', '/v3/users/createNote'), 'list_tasks': ('GET', '/v3/tasks'), 'create_task': ('POST', '/v3/tasks'), 'complete_task': ('POST', '/v3/tasks/markAsCompleted/{task_id}'), 'list_users': ('GET', '/v3/users'), 'get_user': ('GET', '/v3/users/{userId}'), 'create_user': ('POST', '/v3/users'), 'update_user': ('PATCH', '/v3/users'), 'search_users': ('GET', '/v3/users/searchUser'), 'list_membership_types': ('GET', '/v3/membershipTypes'), 'list_user_memberships': ('GET', '/v3/users/memberships'), 'list_schedule': ('GET', '/v3/schedule')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items() if k.lower() not in {"api-key", "api_key", "authorization"}}
    return value


class ArboxNode(WorkflowNode):
    integration_type = "automation-arbox"
    connection_evidence = ConnectionEvidence(
        noun="Arbox locations", operation="list_locations", label_keys=("location_name", "location_id"),
    )

    @classmethod
    def get_config_model(cls):
        return ArboxFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Arbox API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, route = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if op.operation == "get_user":
            route = route.replace("{userId}", str(values.pop("user_id")))
        elif op.operation == "complete_task":
            route = route.replace("{task_id}", str(values.pop("task_id")))
        elif op.operation == "create_task":
            values["reminder"] = {"date": values.pop("reminder_date"), "time": values.pop("reminder_time")}
        params = values if method == "GET" else None
        body = values if method != "GET" and op.operation != "complete_task" else None
        writing = method != "GET"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"api-key": secret, "Accept": "application/json"}, params=params, json=body)
            http_status = response.status_code
            if http_status != 200:
                message = "Arbox did not return the documented HTTP 200 response"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"][:1000]
                except (ValueError, UnicodeError):
                    pass
                output = {"success": False, "error": message, "http_status": http_status,
                    "write_outcome": "unverified" if writing and (http_status < 400 or http_status >= 500) else None}
            else:
                media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media != "application/json" or len(response.content) > 10_000_000:
                    raise ValueError("Arbox returned an unsupported or oversized response")
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Arbox returned an unexpected JSON envelope")
                code = payload.get("statusCode")
                if payload.get("error") or payload.get("errors") or payload.get("success") is False or (code is not None and (type(code) is not int or code not in {200, 204})):
                    message = payload.get("message")
                    output = {"success": False, "error": message[:1000] if isinstance(message, str) else "Arbox reported an API error", "http_status": http_status, "provider_status": code}
                else:
                    # The published envelopes have array data/extra. They have no
                    # authoritative total or next link, so do not infer completion.
                    if "data" in payload and not isinstance(payload["data"], list):
                        raise ValueError("Arbox data must be an array")
                    output = {"success": True, "data": payload.get("data", []), "extra": payload.get("extra", []), "http_status": http_status}
                    if "page" in values:
                        output["pagination"] = {"page": op.page, "limit": op.limit, "next_page_to_try": op.page + 1, "completion_known": False}
                    if writing:
                        output["write_outcome"] = "acknowledged"
        except httpx.RequestError:
            output = {"success": False, "error": "Arbox request could not be completed", "write_outcome": "unverified" if writing else None}
        except (ValueError, UnicodeError):
            output = {"success": False, "error": "Arbox response could not be interpreted", "write_outcome": "unverified" if writing else None}
        output = _redact(output, secret)
        await self.emit(output)
        return output
