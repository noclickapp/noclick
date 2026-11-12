"""Everhour account, project, task and time automation using a personal API key.

Contract: https://developers.everhour.com/openapi.json (1.0.0).
List operations return one explicit page; writes are never automatically retried.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class EverhourAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Everhour API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.everhour.com/#/account/profile",
            "x-credential-instructions": "Copy your API key from the bottom of your Everhour profile page. NoClick sends it in the X-Api-Key header. Access follows your Everhour role; use an account with permission for the operations you need.",
        })
    credential_type: Literal["everhour_api_key"] = Field("everhour_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


# Everhour's own MCP server: agents get its tools through a person's Everhour sign-in.
EverhourMcpCredential = mcp_credential("everhour", "https://api.everhour.com/mcp", app="Everhour")
EverhourCredential = Union[EverhourAPIKeyCredential, EverhourMcpCredential]


ResourceID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_:.-]*$")]
Name = Annotated[str, Field(min_length=1, max_length=1000)]


class _ProjectID(_Input):
    project_id: ResourceID = Field(..., description="Encoded Everhour project ID, such as ev:1234567789001.")


class _TaskID(_Input):
    task_id: ResourceID = Field(..., description="Encoded Everhour task ID, such as ev:3000010034.")


class _ClientID(_Input):
    client_id: int = Field(..., gt=0)


class _TimeID(_Input):
    time_id: int = Field(..., gt=0)


class _ClientFields(_Input):
    name: Name | None = None
    projects: list[ResourceID] | None = None
    reference: str | None = None
    businessDetails: str | None = None
    invoicePublicNotes: str | None = None
    email: list[str] | None = Field(None, max_length=10)
    paymentDueDays: int | None = Field(None, ge=0, le=365)
    defaultDiscount: float | None = Field(None, ge=0, le=100)


class _ProjectFields(_Input):
    name: Name | None = None
    project_type: Literal["board", "list"] | None = Field(None, description="Project layout (sent as type).")
    users: list[int] | None = None
    client: int | None = None
    privacy: bool | None = None
    changeProtected: bool | None = None
    isTemplate: bool | None = None


class EverhourAssignee(_Input):
    userId: int | None = None
    accountId: str | None = None


class _TaskFields(_Input):
    name: Name | None = None
    section: int | None = None
    labels: list[str] | None = None
    task_status: Literal["open", "closed"] | None = Field(None, description="Task state (sent as status).")
    color: str | None = Field(None, max_length=15)
    dueOn: Date | None = None
    startOn: Date | None = None
    description: str | None = Field(None, max_length=2000)
    assignees: list[EverhourAssignee] | None = None
    tags: list[int] | None = Field(None, max_length=10)


class _TimeFields(_Input):
    time: int = Field(..., ge=0, description="Duration in seconds. Posting the same user/date/task replaces the duration.")
    date: Date | None = None
    task: ResourceID | None = None
    user: int | None = None
    comment: str | None = None


class EverhourGetCurrentUserConfig(_Input):
    """Read the authenticated account; API keys are excluded from output."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class EverhourListUsersConfig(_Input):
    """Read team users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    query: str | None = None
    limit: int | None = Field(None, ge=1, le=1000)


class EverhourListClientsConfig(_Input):
    """Find clients by name."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})
    query: str | None = None


class EverhourGetClientConfig(_ClientID):
    """Read one client."""
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})


class EverhourCreateClientConfig(_ClientFields):
    """Create a client; duplicate names create additional clients."""
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    name: Name


class EverhourUpdateClientConfig(_ClientFields, _ClientID):
    """Update only supplied client fields."""
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})


class EverhourListProjectsConfig(_Input):
    """Read one page of accessible projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    query: str | None = None
    platform: Literal["as", "ev", "b3", "b2", "pv", "gh", "in", "tr", "jr"] | None = None
    limit: int = Field(100, ge=1, le=1000)
    page: int = Field(1, ge=1)


class EverhourGetProjectConfig(_ProjectID):
    """Read one project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class EverhourCreateProjectConfig(_ProjectFields):
    """Create an Everhour project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    name: Name
    project_type: Literal["board", "list"]


class EverhourUpdateProjectConfig(_ProjectFields, _ProjectID):
    """Update project settings."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})


class EverhourArchiveProjectConfig(_ProjectID):
    """Archive or unarchive a project while preserving its data."""
    operation: Literal["archive_project"] = Field("archive_project", json_schema_extra={"ui:hidden": True})
    archived: bool


class EverhourListTasksConfig(_ProjectID):
    """Read one page of tasks in a project."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    query: str | None = None
    limit: int = Field(100, ge=1, le=250)
    page: int = Field(1, ge=1)
    exclude_closed: bool | None = None


class EverhourGetTaskConfig(_TaskID):
    """Read one task."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})


class EverhourCreateTaskConfig(_TaskFields, _ProjectID):
    """Create a task in an Everhour project."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    name: Name


class EverhourUpdateTaskConfig(_TaskFields, _TaskID):
    """Update supplied task fields."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})


class EverhourDeleteTaskConfig(_TaskID):
    """Delete a task and all its time records. This is irreversible."""
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True})


class EverhourSearchTasksConfig(_Input):
    """Search tasks across projects."""
    operation: Literal["search_tasks"] = Field("search_tasks", json_schema_extra={"ui:hidden": True})
    query: str | None = None
    project: ResourceID | None = None
    limit: int = Field(100, ge=1, le=100)
    searchInClosed: bool | None = None


class EverhourListTimeConfig(_Input):
    """Read a page of team time; omitted dates select the current day."""
    operation: Literal["list_time"] = Field("list_time", json_schema_extra={"ui:hidden": True})
    from_date: Date | None = None
    to_date: Date | None = None
    limit: int = Field(100, ge=1, le=50000)
    page: int = Field(1, ge=1)


class EverhourAddTimeConfig(_TimeFields):
    """Add or replace time for a user/date/task."""
    operation: Literal["add_time"] = Field("add_time", json_schema_extra={"ui:hidden": True})
    task: ResourceID
    date: Date


class EverhourUpdateTimeConfig(_TimeFields, _TimeID):
    """Update a specific time record by ID."""
    operation: Literal["update_time"] = Field("update_time", json_schema_extra={"ui:hidden": True})


class EverhourDeleteTimeConfig(_TimeID):
    """Set a time record duration to zero; its history remains."""
    operation: Literal["delete_time"] = Field("delete_time", json_schema_extra={"ui:hidden": True})


class EverhourStartTimerConfig(_Input):
    """Start a timer; Everhour stops and commits any other running timer."""
    operation: Literal["start_timer"] = Field("start_timer", json_schema_extra={"ui:hidden": True})
    task: ResourceID
    userDate: Date | None = None
    comment: str | None = None


class EverhourGetTimerConfig(_Input):
    """Read your running timer, or the empty timer payload."""
    operation: Literal["get_timer"] = Field("get_timer", json_schema_extra={"ui:hidden": True})


class EverhourStopTimerConfig(_Input):
    """Stop your timer and commit its accumulated time."""
    operation: Literal["stop_timer"] = Field("stop_timer", json_schema_extra={"ui:hidden": True})


EverhourConfig = Annotated[Union[
    EverhourGetCurrentUserConfig,
    EverhourListUsersConfig,
    EverhourListClientsConfig,
    EverhourGetClientConfig,
    EverhourCreateClientConfig,
    EverhourUpdateClientConfig,
    EverhourListProjectsConfig,
    EverhourGetProjectConfig,
    EverhourCreateProjectConfig,
    EverhourUpdateProjectConfig,
    EverhourArchiveProjectConfig,
    EverhourListTasksConfig,
    EverhourGetTaskConfig,
    EverhourCreateTaskConfig,
    EverhourUpdateTaskConfig,
    EverhourDeleteTaskConfig,
    EverhourSearchTasksConfig,
    EverhourListTimeConfig,
    EverhourAddTimeConfig,
    EverhourUpdateTimeConfig,
    EverhourDeleteTimeConfig,
    EverhourStartTimerConfig,
    EverhourGetTimerConfig,
    EverhourStopTimerConfig,
], Field(discriminator="operation")]


class EverhourFullConfig(NodeConfig[EverhourConfig, EverhourCredential]):
    pass


# Each operation maps to one published endpoint, with explicit wire field names.
ROUTES = {
    'get_current_user': ('GET', '/users/me', {}, {}),
    'list_users': ('GET', '/team/users', {'query': 'query', 'limit': 'limit'}, {}),
    'list_clients': ('GET', '/clients', {'query': 'query'}, {}),
    'get_client': ('GET', '/clients/{client_id}', {}, {}),
    'create_client': ('POST', '/clients', {}, {'name': 'name', 'projects': 'projects', 'reference': 'reference', 'businessDetails': 'businessDetails', 'invoicePublicNotes': 'invoicePublicNotes', 'email': 'email', 'paymentDueDays': 'paymentDueDays', 'defaultDiscount': 'defaultDiscount'}),
    'update_client': ('PUT', '/clients/{client_id}', {}, {'name': 'name', 'projects': 'projects', 'reference': 'reference', 'businessDetails': 'businessDetails', 'invoicePublicNotes': 'invoicePublicNotes', 'email': 'email', 'paymentDueDays': 'paymentDueDays', 'defaultDiscount': 'defaultDiscount'}),
    'list_projects': ('GET', '/projects', {'query': 'query', 'platform': 'platform', 'limit': 'limit', 'page': 'page'}, {}),
    'get_project': ('GET', '/projects/{project_id}', {}, {}),
    'create_project': ('POST', '/projects', {}, {'name': 'name', 'users': 'users', 'client': 'client', 'privacy': 'privacy', 'changeProtected': 'changeProtected', 'isTemplate': 'isTemplate', 'project_type': 'type'}),
    'update_project': ('PUT', '/projects/{project_id}', {}, {'name': 'name', 'users': 'users', 'client': 'client', 'privacy': 'privacy', 'changeProtected': 'changeProtected', 'isTemplate': 'isTemplate', 'project_type': 'type'}),
    'archive_project': ('PATCH', '/projects/{project_id}/archive', {}, {'archived': 'archived'}),
    'list_tasks': ('GET', '/projects/{project_id}/tasks', {'query': 'query', 'limit': 'limit', 'page': 'page', 'exclude_closed': 'exclude-closed'}, {}),
    'get_task': ('GET', '/tasks/{task_id}', {}, {}),
    'create_task': ('POST', '/projects/{project_id}/tasks', {}, {'name': 'name', 'section': 'section', 'labels': 'labels', 'color': 'color', 'dueOn': 'dueOn', 'startOn': 'startOn', 'description': 'description', 'assignees': 'assignees', 'tags': 'tags', 'task_status': 'status'}),
    'update_task': ('PUT', '/tasks/{task_id}', {}, {'name': 'name', 'section': 'section', 'labels': 'labels', 'color': 'color', 'dueOn': 'dueOn', 'startOn': 'startOn', 'description': 'description', 'assignees': 'assignees', 'tags': 'tags', 'task_status': 'status'}),
    'delete_task': ('DELETE', '/tasks/{task_id}', {}, {}),
    'search_tasks': ('GET', '/tasks/search', {'query': 'query', 'project': 'project', 'limit': 'limit', 'searchInClosed': 'searchInClosed'}, {}),
    'list_time': ('GET', '/team/time', {'from_date': 'from', 'to_date': 'to', 'limit': 'limit', 'page': 'page'}, {}),
    'add_time': ('POST', '/time', {}, {'time': 'time', 'date': 'date', 'task': 'task', 'user': 'user', 'comment': 'comment'}),
    'update_time': ('PUT', '/time/{time_id}', {}, {'time': 'time', 'date': 'date', 'task': 'task', 'user': 'user', 'comment': 'comment'}),
    'delete_time': ('DELETE', '/time/{time_id}', {}, {}),
    'start_timer': ('POST', '/timers', {}, {'task': 'task', 'userDate': 'userDate', 'comment': 'comment'}),
    'get_timer': ('GET', '/timers/current', {}, {}),
    'stop_timer': ('DELETE', '/timers/current', {}, {}),
}
LIST_OPERATIONS = frozenset({"list_users", "list_clients", "list_projects", "list_tasks", "search_tasks", "list_time"})


def _safe_output(value, secret):
    if isinstance(value, dict):
        return {k: _safe_output(v, secret) for k, v in value.items()
                if k.lower() not in {"apikey", "api_key", "access_token", "refresh_token", "password"}}
    if isinstance(value, list):
        return [_safe_output(v, secret) for v in value]
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    return value


class EverhourNode(WorkflowNode):
    integration_type = "automation-everhour"
    credential_provider_labels = {"everhour": "Everhour Account"}
    connection_evidence = ConnectionEvidence(noun="Everhour account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return EverhourFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Everhour API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        values = config.model_dump(mode="json", exclude_none=True)
        method, path, query_fields, body_fields = ROUTES[config.operation]
        for name, value in values.items():
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        params = {wire: (str(values[name]).lower() if isinstance(values[name], bool) else values[name])
                  for name, wire in query_fields.items() if name in values}
        body = {wire: values[name] for name, wire in body_fields.items() if name in values}
        kwargs = {"params": params, "headers": {"X-Api-Key": secret, "Accept": "application/json"}}
        if body_fields:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, "https://api.everhour.com" + path, **kwargs)
        except httpx.RequestError:
            raise ValueError("Everhour request did not complete; check the provider before repeating a write") from None
        if not 200 <= response.status_code < 300:
            message = "Everhour request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                    "message": _safe_output(message, secret)}
        if response.status_code == 204:
            data = None
        else:
            data = response.json()
            expected = list if config.operation in LIST_OPERATIONS else dict
            if not isinstance(data, expected):
                raise ValueError("Unexpected Everhour response shape")
        result = {"status": "success", "operation": config.operation, "data": _safe_output(data, secret)}
        if config.operation in LIST_OPERATIONS:
            result["page"] = values.get("page")
            result["limit"] = values.get("limit")
        await self.emit(result)
        return result
