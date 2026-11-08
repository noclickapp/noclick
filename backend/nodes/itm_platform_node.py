"""ITM Platform's published v1/v2 contract, with a manually supplied session token.

Each action sends exactly one documented request. Search returns one page;
callers advance page themselves. Writes are never retried automatically.
Contract: https://developers.itmplatform.com/documentation/openapi.json (2.0.0).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ITMPlatformTokenCredential(BaseModel):
    model_config = ConfigDict(title="ITM Platform Session Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.itmplatform.com/documentation/#authentication",
            "x-credential-instructions": "Enter your company URL segment and paste an existing session token obtained using ITM Platform's documented API-key login. Paste the Token value, without a header prefix. Tokens expire; replace an expired token here. NoClick checks account users and never creates a new session for you.",
        })
    credential_type: Literal["itm_platform_token"] = Field("itm_platform_token", json_schema_extra={"ui:hidden": True})
    company: str = Field(..., title="Company URL segment", min_length=1, max_length=128,
        description="The companyURL segment from your ITM Platform API URL, for example companyURL. Enter only the segment.")
    token: str = Field(..., title="Session token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("company")
    @classmethod
    def company_segment(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
            raise ValueError("Enter a single company URL segment using letters, digits, underscores or hyphens")
        return value

    @field_validator("token", mode="before")
    @classmethod
    def session_token(cls, value):
        value = clean_secret(value, field_name="Session token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the session token without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Search(_Input):
    page: int = Field(1, ge=1, description="One-based page number; this action returns only this page.")
    page_size: int = Field(50, ge=1, le=500)
    filter: dict[str, Any] | None = Field(None, description="Documented MongoDB-style Filter, for example {\"Name\": {\"$regex\": \"Digital\"}}.")
    columns: list[str] | None = Field(None, description="Optional property selection, for example Id and Name.")
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] = "asc"


class TimeReport(_Input):
    """One replacement total for a task/date, rather than an additive event."""
    entity_id: int = Field(..., gt=0)
    work_item_id: int = Field(..., gt=0)
    date: date
    reported_hours: str = Field(..., pattern=r"^[0-9]+:[0-5][0-9]$", description="Replacement total in H:MM. 0:00 removes the entry.")
    user_comment: str | None = None
    billing_category_id: int | None = Field(None, ge=0)
    non_billable_mins: str | None = Field(None, pattern=r"^[0-9]+$")


class GetMeConfig(_Input):
    """Get my details."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})

class SearchProjectsConfig(_Search):
    """Get Projects."""
    operation: Literal["search_projects"] = Field("search_projects", json_schema_extra={"ui:hidden": True})

class CreateProjectConfig(_Input):
    """Add a project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    description: str | None = Field(None)
    type_id: int = Field(..., ge=0)
    external_client_id: int | None = Field(None, ge=0)
    performing_unit_id: int | None = Field(None, ge=0)
    priority_id: int | None = Field(None, ge=0)
    status_id: int | None = Field(None, ge=0)
    start_date: str | None = Field(None)
    end_date: str | None = Field(None)
    sponsor_id: int | None = Field(None, ge=0)
    internal_code: str | None = Field(None)
    internal_cost_center: str | None = Field(None)

class GetProjectConfig(_Input):
    """Get a project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0, description="ITM Platform ProjectId.")

class UpdateProjectConfig(_Input):
    """Update a project."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0, description="ITM Platform ProjectId.")
    name: str | None = Field(None)
    description: str | None = Field(None)
    type_id: int | None = Field(None, ge=0)
    external_client_id: int | None = Field(None, ge=0)
    performing_unit_id: int | None = Field(None, ge=0)
    priority_id: int | None = Field(None, ge=0)
    status_id: int | None = Field(None, ge=0)
    start_date: str | None = Field(None)
    end_date: str | None = Field(None)
    sponsor_id: int | None = Field(None, ge=0)
    internal_code: str | None = Field(None)
    internal_cost_center: str | None = Field(None)

    @model_validator(mode="after")
    def changed_fields(self):
        if not any(getattr(self, key) is not None for key in ROUTES[self.operation]["body"]):
            raise ValueError("Supply at least one field to update")
        return self

class SearchTasksConfig(_Search):
    """Get Project Tasks Search."""
    operation: Literal["search_tasks"] = Field("search_tasks", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0, description="ITM Platform ProjectId.")

class CreateTaskConfig(_Input):
    """Add a task."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0, description="ITM Platform ProjectId.")
    name: str = Field(..., min_length=1)
    details: str | None = Field(None)
    display_in_portfolio: bool | None = Field(None)
    type_name: str | None = Field(None)
    priority_name: str | None = Field(None)
    status_name: str | None = Field(None)
    parent_id: str | None = Field(None)
    swimlane_name: str | None = Field(None)
    start_date: str | None = Field(None)
    end_date: str | None = Field(None)
    sprint_id: str | None = Field(None)
    task_managers: str | None = Field(None, description="Comma-separated task managers to add: usernames (the user's EmailAddress) or numeric user ids. Add-only: existing assignees are kept, and users not yet on the project team are added to it. Non-login users have no username, so use their UserId. Kanban projects save managers as plain members.")
    task_members: str | None = Field(None, description="Comma-separated team members to add: usernames (the user's EmailAddress) or numeric user ids. Add-only: existing assignees are kept, and users not yet on the project team are added to it. Non-login users have no username, so use their UserId.")

class GetTaskConfig(_Input):
    """Get a Task."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0, description="ITM Platform ProjectId.")
    task_id: int = Field(..., gt=0, description="ITM Platform TaskId.")

class UpdateTaskConfig(_Input):
    """Update a task."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0, description="ITM Platform ProjectId.")
    task_id: int = Field(..., gt=0, description="ITM Platform TaskId.")
    name: str | None = Field(None)
    details: str | None = Field(None)
    display_in_portfolio: bool | None = Field(None)
    parent_id: str | None = Field(None)
    swimlane_name: str | None = Field(None)
    start_date: str | None = Field(None)
    end_date: str | None = Field(None)
    sprint_id: str | None = Field(None)
    task_managers: str | None = Field(None, description="Comma-separated task managers to add: usernames (the user's EmailAddress) or numeric user ids. Add-only: existing assignees are kept, and users not yet on the project team are added to it. Non-login users have no username, so use their UserId. Kanban projects save managers as plain members.")
    task_members: str | None = Field(None, description="Comma-separated team members to add: usernames (the user's EmailAddress) or numeric user ids. Add-only: existing assignees are kept, and users not yet on the project team are added to it. Non-login users have no username, so use their UserId.")

    @model_validator(mode="after")
    def changed_fields(self):
        if not any(getattr(self, key) is not None for key in ROUTES[self.operation]["body"]):
            raise ValueError("Supply at least one field to update")
        return self

class DeleteTaskConfig(_Input):
    """Bulk Delete tasks."""
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0, description="ITM Platform ProjectId.")
    task_id: int = Field(..., gt=0, description="ITM Platform TaskId.")

class ListUsersConfig(_Input):
    """Get users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})

class GetUserConfig(_Input):
    """Get a user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., gt=0, description="ITM Platform UserId.")

class ListClientsConfig(_Input):
    """Get clients."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})
    client_id: str | None = Field(None, description="Optional documented v1 ClientId filter.")

class SearchServicesConfig(_Search):
    """Get Services."""
    operation: Literal["search_services"] = Field("search_services", json_schema_extra={"ui:hidden": True})

class CreateServiceConfig(_Input):
    """Add a service."""
    operation: Literal["create_service"] = Field("create_service", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    description: str | None = Field(None)
    type_id: int = Field(..., ge=0)
    external_client_id: int | None = Field(None, ge=0)
    priority_id: int | None = Field(None, ge=0)
    start_date: str | None = Field(None)
    end_date: str | None = Field(None)
    sponsor_id: int | None = Field(None, ge=0)
    internal_code: str | None = Field(None)
    internal_cost_center: str | None = Field(None)

class GetServiceConfig(_Input):
    """Get a service."""
    operation: Literal["get_service"] = Field("get_service", json_schema_extra={"ui:hidden": True})
    service_id: int = Field(..., gt=0, description="ITM Platform ServiceId.")

class UpdateServiceConfig(_Input):
    """Update a service."""
    operation: Literal["update_service"] = Field("update_service", json_schema_extra={"ui:hidden": True})
    service_id: int = Field(..., gt=0, description="ITM Platform ServiceId.")
    name: str | None = Field(None)
    description: str | None = Field(None)
    type_id: int | None = Field(None, ge=0)
    external_client_id: int | None = Field(None, ge=0)
    priority_id: int | None = Field(None, ge=0)
    start_date: str | None = Field(None)
    end_date: str | None = Field(None)
    sponsor_id: int | None = Field(None, ge=0)
    internal_code: str | None = Field(None)
    internal_cost_center: str | None = Field(None)

    @model_validator(mode="after")
    def changed_fields(self):
        if not any(getattr(self, key) is not None for key in ROUTES[self.operation]["body"]):
            raise ValueError("Supply at least one field to update")
        return self

class GetTimesheetConfig(_Input):
    """Get one user's timesheet."""
    operation: Literal["get_timesheet"] = Field("get_timesheet", json_schema_extra={"ui:hidden": True})
    start_date: date
    end_date: date
    teammember: str | None = Field(None, description="Omit for yourself; another user's ID or username requires permission.")

    @model_validator(mode="after")
    def window(self):
        if not 0 <= (self.end_date - self.start_date).days <= 30:
            raise ValueError("Use an inclusive date range of at most 31 days")
        return self

class SetTimeEntriesConfig(_Input):
    """Add time entries."""
    operation: Literal["set_time_entries"] = Field("set_time_entries", json_schema_extra={"ui:hidden": True})
    user_id: int | None = Field(None, ge=0, description="Omit or use zero for yourself. Targeting another user requires Company Admin or Full Access rights.")
    time_reports: list[TimeReport] = Field(..., min_length=1, max_length=500,
        description="Each item REPLACES the user's total and comment for that task/date; 0:00 removes it. Read current hours first when adding time.")

class ListProgramsConfig(_Input):
    """Get Programs."""
    operation: Literal["list_programs"] = Field("list_programs", json_schema_extra={"ui:hidden": True})


ROUTES = {'get_me': {'method': 'GET',
            'path': '/mydetail',
            'v2': False,
            'path_fields': {},
            'body': {},
            'query': {},
            'operation_id': 'getMyDetails'},
 'search_projects': {'method': 'POST',
                     'path': '/projects/search',
                     'v2': True,
                     'path_fields': {},
                     'body': {},
                     'query': {},
                     'operation_id': 'getProjectsV2_1'},
 'create_project': {'method': 'POST',
                    'path': '/projects',
                    'v2': True,
                    'path_fields': {},
                    'body': {'name': 'Name',
                             'description': 'Description',
                             'type_id': 'TypeId',
                             'external_client_id': 'ExternalClientId',
                             'performing_unit_id': 'PerformingUnitId',
                             'priority_id': 'PriorityId',
                             'status_id': 'StatusId',
                             'start_date': 'StartDate',
                             'end_date': 'EndDate',
                             'sponsor_id': 'SponsorId',
                             'internal_code': 'InternalCode',
                             'internal_cost_center': 'InternalCostCenter'},
                    'query': {},
                    'operation_id': 'addAProjectV2'},
 'get_project': {'method': 'GET',
                 'path': '/projects/{ProjectId}',
                 'v2': True,
                 'path_fields': {'project_id': 'ProjectId'},
                 'body': {},
                 'query': {},
                 'operation_id': 'getAProjectV2'},
 'update_project': {'method': 'PATCH',
                    'path': '/projects/{ProjectId}',
                    'v2': True,
                    'path_fields': {'project_id': 'ProjectId'},
                    'body': {'name': 'Name',
                             'description': 'Description',
                             'type_id': 'TypeId',
                             'external_client_id': 'ExternalClientId',
                             'performing_unit_id': 'PerformingUnitId',
                             'priority_id': 'PriorityId',
                             'status_id': 'StatusId',
                             'start_date': 'StartDate',
                             'end_date': 'EndDate',
                             'sponsor_id': 'SponsorId',
                             'internal_code': 'InternalCode',
                             'internal_cost_center': 'InternalCostCenter'},
                    'query': {},
                    'operation_id': 'updateAProjectV2'},
 'search_tasks': {'method': 'POST',
                  'path': '/Projects/{ProjectId}/Tasks/Search',
                  'v2': False,
                  'path_fields': {'project_id': 'ProjectId'},
                  'body': {},
                  'query': {},
                  'operation_id': 'getProjectTasksSearch'},
 'create_task': {'method': 'POST',
                 'path': '/Projects/{ProjectId}/Tasks',
                 'v2': True,
                 'path_fields': {'project_id': 'ProjectId'},
                 'body': {'name': 'Name',
                          'details': 'Details',
                          'display_in_portfolio': 'DisplayInPortfolio',
                          'type_name': 'TypeName',
                          'priority_name': 'PriorityName',
                          'status_name': 'StatusName',
                          'parent_id': 'ParentId',
                          'swimlane_name': 'SwimlaneName',
                          'start_date': 'StartDate',
                          'end_date': 'EndDate',
                          'sprint_id': 'SprintId',
                          'task_managers': 'TaskManagers',
                          'task_members': 'TaskMembers'},
                 'query': {},
                 'operation_id': 'addATaskV2'},
 'get_task': {'method': 'GET',
              'path': '/Projects/{ProjectId}/Tasks/{TaskId}',
              'v2': False,
              'path_fields': {'project_id': 'ProjectId', 'task_id': 'TaskId'},
              'body': {},
              'query': {},
              'operation_id': 'getATask'},
 'update_task': {'method': 'PATCH',
                 'path': '/Projects/{ProjectId}/Tasks/{TaskId}',
                 'v2': True,
                 'path_fields': {'project_id': 'ProjectId', 'task_id': 'TaskId'},
                 'body': {'name': 'Name',
                          'details': 'Details',
                          'display_in_portfolio': 'DisplayInPortfolio',
                          'parent_id': 'ParentId',
                          'swimlane_name': 'SwimlaneName',
                          'start_date': 'StartDate',
                          'end_date': 'EndDate',
                          'sprint_id': 'SprintId',
                          'task_managers': 'TaskManagers',
                          'task_members': 'TaskMembers'},
                 'query': {},
                 'operation_id': 'updateATaskV2'},
 'delete_task': {'method': 'DELETE',
                 'path': '/Projects/{ProjectId}/Tasks/{TaskId}',
                 'v2': True,
                 'path_fields': {'project_id': 'ProjectId', 'task_id': 'TaskId'},
                 'body': {},
                 'query': {},
                 'operation_id': 'bulkDeleteTasksV2'},
 'list_users': {'method': 'GET',
                'path': '/users',
                'v2': False,
                'path_fields': {},
                'body': {},
                'query': {},
                'operation_id': 'getUsers'},
 'get_user': {'method': 'GET',
              'path': '/users/{UserId}',
              'v2': True,
              'path_fields': {'user_id': 'UserId'},
              'body': {},
              'query': {},
              'operation_id': 'getAUserV2'},
 'list_clients': {'method': 'GET',
                  'path': '/clients',
                  'v2': False,
                  'path_fields': {},
                  'body': {},
                  'query': {'client_id': 'ClientId'},
                  'operation_id': 'getClients'},
 'search_services': {'method': 'POST',
                     'path': '/Services/Search',
                     'v2': True,
                     'path_fields': {},
                     'body': {},
                     'query': {},
                     'operation_id': 'getServicesV2'},
 'create_service': {'method': 'POST',
                    'path': '/Services',
                    'v2': True,
                    'path_fields': {},
                    'body': {'name': 'Name',
                             'description': 'Description',
                             'type_id': 'TypeId',
                             'external_client_id': 'ExternalClientId',
                             'priority_id': 'PriorityId',
                             'start_date': 'StartDate',
                             'end_date': 'EndDate',
                             'sponsor_id': 'SponsorId',
                             'internal_code': 'InternalCode',
                             'internal_cost_center': 'InternalCostCenter'},
                    'query': {},
                    'operation_id': 'addAServiceV2'},
 'get_service': {'method': 'GET',
                 'path': '/Services/{ServiceId}',
                 'v2': True,
                 'path_fields': {'service_id': 'ServiceId'},
                 'body': {},
                 'query': {},
                 'operation_id': 'getAServiceV2'},
 'update_service': {'method': 'PATCH',
                    'path': '/Services/{ServiceId}',
                    'v2': True,
                    'path_fields': {'service_id': 'ServiceId'},
                    'body': {'name': 'Name',
                             'description': 'Description',
                             'type_id': 'TypeId',
                             'external_client_id': 'ExternalClientId',
                             'priority_id': 'PriorityId',
                             'start_date': 'StartDate',
                             'end_date': 'EndDate',
                             'sponsor_id': 'SponsorId',
                             'internal_code': 'InternalCode',
                             'internal_cost_center': 'InternalCostCenter'},
                    'query': {},
                    'operation_id': 'updateAServiceV2'},
 'get_timesheet': {'method': 'GET',
                   'path': '/timehours/',
                   'v2': False,
                   'path_fields': {},
                   'body': {},
                   'query': {'start_date': 'StartDate',
                             'end_date': 'EndDate',
                             'teammember': 'teammember'},
                   'operation_id': 'getTimeEntries'},
 'set_time_entries': {'method': 'POST',
                      'path': '/timehours/',
                      'v2': False,
                      'path_fields': {},
                      'body': {'user_id': 'UserId', 'time_reports': 'TimeReports'},
                      'query': {},
                      'operation_id': 'addTimeEntries'},
 'list_programs': {'method': 'GET',
                   'path': '/programs',
                   'v2': True,
                   'path_fields': {},
                   'body': {},
                   'query': {},
                   'operation_id': 'getProgramsV2'}}

Operation = Annotated[Union[GetMeConfig, SearchProjectsConfig, CreateProjectConfig, GetProjectConfig, UpdateProjectConfig, SearchTasksConfig, CreateTaskConfig, GetTaskConfig, UpdateTaskConfig, DeleteTaskConfig, ListUsersConfig, GetUserConfig, ListClientsConfig, SearchServicesConfig, CreateServiceConfig, GetServiceConfig, UpdateServiceConfig, GetTimesheetConfig, SetTimeEntriesConfig, ListProgramsConfig], Field(discriminator="operation")]

class ITMPlatformFullConfig(NodeConfig[Operation, ITMPlatformTokenCredential]):
    pass


def _wire_name(name):
    return {"entity_id": "EntityId", "work_item_id": "WorkItemId", "date": "Date",
        "reported_hours": "ReportedHours", "user_comment": "UserComment",
        "billing_category_id": "BillingCategoryId", "non_billable_mins": "NonBillableMins"}[name]


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"token", "authorization", "apikey"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class ITMPlatformNode(WorkflowNode):
    integration_type = "automation-itm-platform"
    connection_evidence = ConnectionEvidence(noun="account users", operation="list_users",
        identity_operation="get_me", label_keys=("DisplayName", "UserName", "UserId"),
        identity_keys=("LoginName", "FirstName", "LastName"))

    @classmethod
    def get_config_model(cls):
        return ITMPlatformFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an ITM Platform session token")
        credential = self.config.credentials
        op = self.config.config
        route = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for field, key in route["path_fields"].items():
            path = path.replace("{" + key + "}", str(values[field]))
        base = "https://api.itmplatform.com/" + ("v2/" if route["v2"] else "") + credential.company
        params = {wire: values[field] for field, wire in route["query"].items() if field in values}
        body = {wire: values[field] for field, wire in route["body"].items() if field in values}
        if isinstance(op, _Search):
            body = {"page": op.page, "pageSize": op.page_size}
            if op.filter is not None:
                body["Filter"] = op.filter
            if op.columns is not None:
                body["Columns"] = {"$in": op.columns}
            if op.sort_by is not None:
                body.update(sortBy=op.sort_by, sortOrder=op.sort_order)
        if op.operation == "set_time_entries":
            body["TimeReports"] = [{_wire_name(k): v for k, v in row.items()} for row in values["time_reports"]]
        kwargs = {"headers": {"Token": credential.token, "Accept": "application/json"}, "params": params}
        if route["method"] in {"POST", "PATCH"}:
            kwargs["json"] = body
        # Only a fixed provider host; company is a validated single path segment.
        # Preserve HTTP errors as errors, including legacy HTTP-200 error bodies.
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], base + path, **kwargs)
        except Exception:
            raise ValueError("ITM Platform request could not be completed; a write may have reached the service") from None
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                message = error.get("StatusMessage") or error.get("message") if isinstance(error, dict) else None
            except Exception:
                message = None
            output = {"status": "error", "success": False, "http_status": response.status_code,
                "message": _redact(message or f"ITM Platform returned HTTP {response.status_code}", credential.token)}
        else:
            if response.status_code == 204:
                data = None
            else:
                try:
                    data = response.json()
                except Exception:
                    raise ValueError("Expected ITM Platform JSON response") from None
                if not isinstance(data, (dict, list)):
                    raise ValueError("Expected an ITM Platform object or array")
            failed = isinstance(data, dict) and (str(data.get("StatusCode", "200")) not in {"0", "200", "201", "204"}
                or bool(data.get("Errors")) or str(data.get("ResultStatus", "200")) not in {"200", "201", "204"})
            output = {"status": "error" if failed else "success", "success": not failed,
                "operation": op.operation, "data": _redact(data, credential.token)}
            if failed:
                output["message"] = _redact(data.get("StatusMessage") or "ITM Platform rejected one or more records", credential.token)
        await self.emit(output)
        return output
