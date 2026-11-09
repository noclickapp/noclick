"""Hubstaff Time Tracking API v2 using a pasted organization access token.

Contract: https://api.hubstaff.com/v2/docs (2.0).
Token setup: https://developer.hubstaff.com/authentication/#organization-access-tokens
Hubstaff Tasks is a separate product and API.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


def _operation(name, category):
    return Field(name, description=name.replace("_", " ").capitalize(), json_schema_extra={
        "ui:hidden": True, "x-display-name": name.replace("_", " ").title(),
        "x-category": category, "x-is-trigger": False,
    })


class HubstaffOrganizationTokenCredential(BaseModel):
    model_config = ConfigDict(title="Hubstaff Organization Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.hubstaff.com/time-tracking-api/",
            "x-credential-instructions": "In Hubstaff, open Settings → All settings → Organization → Security & log in → API access tokens. Create an organization access token assigned to an active member with the permissions your workflow needs, then paste the secret shown once. These tokens start with hsoat_ and are sent directly as Bearer credentials. Personal access tokens from the developer portal require exchange and are not supported here. API access requires a Team plan or above.",
        })
    credential_type: Literal["hubstaff_organization_token"] = Field("hubstaff_organization_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Organization access token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password", "ui:help": "Paste the organization token secret without the Bearer prefix."})

    @field_validator("access_token", mode="before")
    @classmethod
    def clean_token(cls, value):
        value = clean_secret(value, field_name="Organization access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the organization access token secret")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page_start_id: int = Field(0, ge=0, le=2147483647, description="Use next_page_start_id from the previous result.")
    page_limit: int = Field(100, ge=1, le=500)


class HubstaffListOrganizations(_Page):
    operation: Literal["list_organizations"] = _operation("list_organizations", "Organizations")


class HubstaffGetOrganization(_Input):
    operation: Literal["get_organization"] = _operation("get_organization", "Organizations")
    organization_id: int = Field(..., gt=0, le=2147483647)


class HubstaffListMembers(_Page):
    operation: Literal["list_members"] = _operation("list_members", "Members")
    organization_id: int = Field(..., gt=0, le=2147483647)


class HubstaffListProjects(_Page):
    operation: Literal["list_projects"] = _operation("list_projects", "Projects")
    organization_id: int = Field(..., gt=0, le=2147483647)
    status: Literal["active", "archived", "all"] | None = None


class HubstaffGetProject(_Input):
    operation: Literal["get_project"] = _operation("get_project", "Projects")
    project_id: int = Field(..., gt=0, le=2147483647)


class HubstaffCreateProject(_Input):
    operation: Literal["create_project"] = _operation("create_project", "Projects")
    organization_id: int = Field(..., gt=0, le=2147483647)
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=10000)
    client_id: int | None = Field(None, gt=0, le=2147483647)
    billable: bool | None = None


class HubstaffUpdateProject(_Input):
    operation: Literal["update_project"] = _operation("update_project", "Projects")
    project_id: int = Field(..., gt=0, le=2147483647)
    name: str | None = Field(None, min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=10000)
    client_id: int | None = Field(None, gt=0, le=2147483647)
    billable: bool | None = None
    status: Literal["active", "archived"] | None = None


class HubstaffListClients(_Page):
    operation: Literal["list_clients"] = _operation("list_clients", "Clients")
    organization_id: int = Field(..., gt=0, le=2147483647)
    status: Literal["active", "archived", "all"] | None = None


class HubstaffGetClient(_Input):
    operation: Literal["get_client"] = _operation("get_client", "Clients")
    client_id: int = Field(..., gt=0, le=2147483647)


class HubstaffCreateClient(_Input):
    operation: Literal["create_client"] = _operation("create_client", "Clients")
    organization_id: int = Field(..., gt=0, le=2147483647)
    name: str = Field(..., min_length=1, max_length=1000)
    emails: list[str] | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=1000)
    address: str | None = Field(None, max_length=10000)


class HubstaffUpdateClient(_Input):
    operation: Literal["update_client"] = _operation("update_client", "Clients")
    client_id: int = Field(..., gt=0, le=2147483647)
    name: str | None = Field(None, min_length=1, max_length=1000)
    emails: list[str] | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=1000)
    address: str | None = Field(None, max_length=10000)
    status: Literal["active", "archived"] | None = None


class HubstaffListTasks(_Page):
    operation: Literal["list_tasks"] = _operation("list_tasks", "Tasks")
    project_id: int = Field(..., gt=0, le=2147483647)


class HubstaffGetTask(_Input):
    operation: Literal["get_task"] = _operation("get_task", "Tasks")
    task_id: int = Field(..., gt=0, le=2147483647)


class HubstaffCreateTask(_Input):
    operation: Literal["create_task"] = _operation("create_task", "Tasks")
    project_id: int = Field(..., gt=0, le=2147483647)
    summary: str = Field(..., min_length=1, max_length=10000)
    assignee_id: int | None = Field(None, gt=0, le=2147483647)


class HubstaffUpdateTask(_Input):
    operation: Literal["update_task"] = _operation("update_task", "Tasks")
    task_id: int = Field(..., gt=0, le=2147483647)
    lock_version: int = Field(..., ge=0, le=2147483647, description="Current lock_version from Get Task; prevents overwriting concurrent edits.")
    summary: str | None = Field(None, min_length=1, max_length=10000)
    status: Literal["active", "completed"] | None = None
    assignee_id: int | None = Field(None, gt=0, le=2147483647)


class HubstaffDeleteTask(_Input):
    operation: Literal["delete_task"] = _operation("delete_task", "Tasks")
    task_id: int = Field(..., gt=0, le=2147483647)


class HubstaffListDailyActivities(_Page):
    operation: Literal["list_daily_activities"] = _operation("list_daily_activities", "Activity")
    organization_id: int = Field(..., gt=0, le=2147483647)
    date_start: date = Field(..., description="Inclusive start date (YYYY-MM-DD).")
    date_stop: date = Field(..., description="Inclusive stop date (YYYY-MM-DD).")

    @model_validator(mode="after")
    def date_order(self):
        if self.date_start and self.date_stop and self.date_start > self.date_stop:
            raise ValueError("Stop date must be on or after start date")
        return self


class HubstaffListTimesheets(_Page):
    operation: Literal["list_timesheets"] = _operation("list_timesheets", "Timesheets")
    organization_id: int = Field(..., gt=0, le=2147483647)
    date_start: date | None = None
    date_stop: date | None = None
    status: Literal["open", "submitted", "approved", "denied"] | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.date_start and self.date_stop and self.date_start > self.date_stop:
            raise ValueError("Stop date must be on or after start date")
        return self


class HubstaffUpdateTimesheet(_Input):
    operation: Literal["update_timesheet"] = _operation("update_timesheet", "Timesheets")
    timesheet_id: int = Field(..., gt=0, le=2147483647)
    status: Literal["open", "submitted", "approved", "denied"]
    denial_reason: str | None = Field(None, max_length=10000)
    confirm_pending_manual_time_request_denial: bool | None = None
    acknowledge_pending_time_off_requests: bool | None = None


class HubstaffCreateTimeEntry(_Input):
    operation: Literal["create_time_entry"] = _operation("create_time_entry", "Time Entries")
    user_id: int = Field(..., gt=0, le=2147483647)
    project_id: int = Field(..., gt=0, le=2147483647)
    start_time: datetime = Field(..., description="ISO 8601 timestamp with timezone.")
    tracked: int = Field(..., gt=0, le=2147483647, description="Seconds tracked.")
    note: str = Field(..., min_length=1, max_length=10000, description="Reason required by the default organization setting.")
    task_id: int | None = Field(None, gt=0, le=2147483647)
    billable: bool | None = None

    @field_validator("start_time")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Include the timezone in start_time")
        return value


HubstaffConfig = Annotated[Union[
    HubstaffListOrganizations,
    HubstaffGetOrganization,
    HubstaffListMembers,
    HubstaffListProjects,
    HubstaffGetProject,
    HubstaffCreateProject,
    HubstaffUpdateProject,
    HubstaffListClients,
    HubstaffGetClient,
    HubstaffCreateClient,
    HubstaffUpdateClient,
    HubstaffListTasks,
    HubstaffGetTask,
    HubstaffCreateTask,
    HubstaffUpdateTask,
    HubstaffDeleteTask,
    HubstaffListDailyActivities,
    HubstaffListTimesheets,
    HubstaffUpdateTimesheet,
    HubstaffCreateTimeEntry,
], Field(discriminator="operation")]


class HubstaffFullConfig(NodeConfig[HubstaffConfig, HubstaffOrganizationTokenCredential]):
    pass


ROUTES = {
    "list_organizations": ('GET', '/v2/organizations', 'organizations'),
    "get_organization": ('GET', '/v2/organizations/{organization_id}', 'organization'),
    "list_members": ('GET', '/v2/organizations/{organization_id}/members', 'members'),
    "list_projects": ('GET', '/v2/organizations/{organization_id}/projects', 'projects'),
    "get_project": ('GET', '/v2/projects/{project_id}', 'project'),
    "create_project": ('POST', '/v2/organizations/{organization_id}/projects', 'project'),
    "update_project": ('PUT', '/v2/projects/{project_id}', 'project'),
    "list_clients": ('GET', '/v2/organizations/{organization_id}/clients', 'clients'),
    "get_client": ('GET', '/v2/clients/{client_id}', 'client'),
    "create_client": ('POST', '/v2/organizations/{organization_id}/clients', 'client'),
    "update_client": ('PUT', '/v2/clients/{client_id}', 'client'),
    "list_tasks": ('GET', '/v2/projects/{project_id}/tasks', 'tasks'),
    "get_task": ('GET', '/v2/tasks/{task_id}', 'task'),
    "create_task": ('POST', '/v2/projects/{project_id}/tasks', 'task'),
    "update_task": ('PUT', '/v2/tasks/{task_id}', 'task'),
    "delete_task": ('DELETE', '/v2/tasks/{task_id}', None),
    "list_daily_activities": ('GET', '/v2/organizations/{organization_id}/activities/daily', 'daily_activities'),
    "list_timesheets": ('GET', '/v2/organizations/{organization_id}/timesheets', 'timesheets'),
    "update_timesheet": ('PUT', '/v2/timesheets/{timesheet_id}', 'timesheet'),
    "create_time_entry": ('POST', '/v2/users/{user_id}/time_entries', None),
}


class HubstaffNode(WorkflowNode):
    integration_type = "automation-hubstaff"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_organizations")

    @classmethod
    def get_config_model(cls):
        return HubstaffFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Hubstaff organization access token")
        config = self.config.config
        method, route, key = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        for field in tuple(values):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", str(values.pop(field)))
        if method == "PUT" and not values:
            raise ValueError("Supply at least one field to update")
        params = None
        body = None
        if method == "GET":
            params = { {"date_start": "date[start]", "date_stop": "date[stop]"}.get(k, k): v for k, v in values.items()}
        elif method in {"POST", "PUT"}:
            body = values
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, "https://api.hubstaff.com" + route,
                    headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                    params=params, json=body)
            if not 200 <= response.status_code < 300:
                message = "Hubstaff API returned HTTP " + str(response.status_code)
                # Preserve provider rejection text for the connect seam, redacting the secret.
                if "json" in response.headers.get("content-type", "") and len(response.content) < 10000:
                    error = response.json()
                    if isinstance(error, dict):
                        detail = error.get("error") or error.get("message")
                        if isinstance(detail, str):
                            message += ": " + detail.replace(credential.access_token, "[redacted]")
                return {"status": "error", "status_code": response.status_code, "error": message}
            if key is None:
                return {"status": "success", "http_status": response.status_code, "acknowledged": True}
            if "json" not in response.headers.get("content-type", "") or len(response.content) > 8_000_000:
                raise ValueError("Expected a bounded Hubstaff JSON response")
            data = response.json()
            if not isinstance(data, dict) or "error" in data or "errors" in data:
                raise ValueError("Hubstaff returned an error or malformed response")
            resource = data.get(key)
            if config.operation.startswith("list_"):
                if not isinstance(resource, list) or any(not isinstance(item, dict) for item in resource):
                    raise ValueError("Hubstaff list response is missing " + key)
                pagination = data.get("pagination") or {}
                if not isinstance(pagination, dict):
                    raise ValueError("Invalid Hubstaff pagination")
                next_id = pagination.get("next_page_start_id")
                if next_id is not None and (type(next_id) is not int or next_id < 0):
                    raise ValueError("Invalid Hubstaff next page start ID")
                return {"status": "success", key: resource, "next_page_start_id": next_id}
            if not isinstance(resource, dict):
                raise ValueError("Hubstaff response is missing " + key)
            return {"status": "success", key: resource}
        except httpx.RequestError:
            return {"status": "error", "error": "Hubstaff request failed; try again later"}
