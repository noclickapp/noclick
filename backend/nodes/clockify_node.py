"""Clockify v1 time tracking and project automation.

Official API: https://docs.clockify.me/. Authentication uses X-Api-Key.
Regional and workspace subdomain hosts are supported without accepting arbitrary URLs.
"""

import re
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Type, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


_HOST_RE = re.compile(r"^(?:api|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)\.clockify\.me$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _id(value: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(
            "Clockify ID must contain only letters, numbers, hyphens, or underscores"
        )
    return value


_DESCRIPTIONS = {
    "get_current_user": "Get the account associated with the API key.",
    "list_workspaces": "List workspaces available to the account.",
    "list_projects": "List projects in a workspace with name and page filters.",
    "create_project": "Create a project with optional client, billing, visibility, and note.",
    "list_time_entries": "List a user's entries with date, project, and page filters.",
    "get_time_entry": "Read one time entry by ID.",
    "create_time_entry": "Record an entry or start a running timer.",
    "stop_timer": "Stop the connected user's running timer at a specified time.",
    "delete_time_entry": "Remove one time entry by ID.",
    "list_clients": "Find clients in a workspace.",
    "create_client": "Create a client in a workspace.",
    "list_tags": "Find tags in a workspace.",
    "create_tag": "Create a tag in a workspace.",
    "list_tasks": "Find tasks on a project.",
    "create_task": "Create a task on a project.",
}


def _field(operation: str, category: str, title: str) -> Any:
    return Field(
        operation,
        title=title,
        description=_DESCRIPTIONS[operation],
        json_schema_extra={
            "const": operation,
            "ui:hidden": True,
            "x-category": category,
            "x-display-name": title,
            "x-is-trigger": False,
        },
    )


def _picker(field: str, noun: str, depends_on: Optional[str] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "field_name": field,
        "placeholder": f"Select a {noun}...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": f"Or paste {noun} ID",
    }
    if depends_on:
        data["depends_on"] = depends_on
    return {"x-dynamic-options": data}


class ClockifyApiKeyCredential(BaseModel):
    credential_type: Literal["clockify_api_key"] = Field(
        "clockify_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Generate in Profile settings → Preferences → Advanced → Manage API keys.",
        json_schema_extra={"ui:widget": "password"},
    )
    api_domain: str = Field(
        "api.clockify.me",
        title="API Domain",
        description="Use api.clockify.me for global workspaces, or your regional/workspace subdomain, such as euc1.clockify.me.",
    )

    @field_validator("api_domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        value = value.strip().lower()
        if not _HOST_RE.fullmatch(value):
            raise ValueError(
                "Enter a Clockify API domain such as api.clockify.me or euc1.clockify.me"
            )
        return value

    model_config = ConfigDict(
        title="Clockify API Key",
        json_schema_extra={
            "x-credential-url": "https://app.clockify.me/user/settings",
            "x-help-text": "Generate a key in Profile settings → Preferences → Advanced → Manage API keys. For subdomain workspaces, create a key in that workspace and set its API domain.",
            "x-credential-instructions": "Generate a key in Profile settings → Preferences → Advanced → Manage API keys. For a regional or workspace subdomain, use its Clockify host and generate a key for that workspace.",
        }
    )


class GetCurrentUser(BaseModel):
    operation: Literal["get_current_user"] = _field(
        "get_current_user", "Account", "Get Current User"
    )


class ListWorkspaces(BaseModel):
    operation: Literal["list_workspaces"] = _field(
        "list_workspaces", "Workspaces", "List Workspaces"
    )


class ListProjects(BaseModel):
    operation: Literal["list_projects"] = _field(
        "list_projects", "Projects", "List Projects"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    name: Optional[str] = Field(None, title="Name Filter")
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(50, ge=1, le=500, title="Page Size")


class CreateProject(BaseModel):
    operation: Literal["create_project"] = _field(
        "create_project", "Projects", "Create Project"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    name: str = Field(..., min_length=2, max_length=250, title="Project Name")
    client_id: Optional[str] = Field(None, title="Client ID")
    billable: Optional[bool] = Field(None, title="Billable")
    is_public: Optional[bool] = Field(None, title="Public")
    note: Optional[str] = Field(
        None, title="Note", json_schema_extra={"ui:widget": "textarea"}
    )


class ListClients(BaseModel):
    operation: Literal["list_clients"] = _field(
        "list_clients", "Clients", "List Clients"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    name: Optional[str] = Field(None, title="Name Filter")
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(50, ge=1, le=500, title="Page Size")


class CreateClient(BaseModel):
    operation: Literal["create_client"] = _field(
        "create_client", "Clients", "Create Client"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    name: str = Field(..., min_length=1, max_length=100, title="Client Name")
    email: Optional[str] = Field(None, title="Email")
    address: Optional[str] = Field(None, title="Address")
    note: Optional[str] = Field(
        None, title="Note", json_schema_extra={"ui:widget": "textarea"}
    )


class ListTags(BaseModel):
    operation: Literal["list_tags"] = _field("list_tags", "Tags", "List Tags")
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    name: Optional[str] = Field(None, title="Name Filter")
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(50, ge=1, le=500, title="Page Size")


class CreateTag(BaseModel):
    operation: Literal["create_tag"] = _field("create_tag", "Tags", "Create Tag")
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    name: str = Field(..., min_length=1, max_length=100, title="Tag Name")


class ListTasks(BaseModel):
    operation: Literal["list_tasks"] = _field("list_tasks", "Tasks", "List Tasks")
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    project_id: str = Field(
        ...,
        title="Project ID",
        json_schema_extra=_picker("project_id", "project", "workspace_id"),
    )
    name: Optional[str] = Field(None, title="Name Filter")
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(50, ge=1, le=500, title="Page Size")


class CreateTask(BaseModel):
    operation: Literal["create_task"] = _field("create_task", "Tasks", "Create Task")
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    project_id: str = Field(
        ...,
        title="Project ID",
        json_schema_extra=_picker("project_id", "project", "workspace_id"),
    )
    name: str = Field(..., min_length=1, max_length=1000, title="Task Name")
    assignee_ids: Optional[List[str]] = Field(None, title="Assignee IDs")
    estimate: Optional[str] = Field(
        None, title="Estimate", description="ISO 8601 duration, e.g. PT1H30M"
    )


class ListTimeEntries(BaseModel):
    operation: Literal["list_time_entries"] = _field(
        "list_time_entries", "Time Entries", "List Time Entries"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    user_id: Optional[str] = Field(
        None, title="User ID", description="Defaults to the connected user."
    )
    start: Optional[str] = Field(
        None,
        title="Start Filter",
        description="ISO 8601 UTC, e.g. 2026-01-01T00:00:00Z",
    )
    end: Optional[str] = Field(None, title="End Filter", description="ISO 8601 UTC")
    project_id: Optional[str] = Field(
        None,
        title="Project ID",
        json_schema_extra=_picker("project_id", "project", "workspace_id"),
    )
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(50, ge=1, le=500, title="Page Size")


class GetTimeEntry(BaseModel):
    operation: Literal["get_time_entry"] = _field(
        "get_time_entry", "Time Entries", "Get Time Entry"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    entry_id: str = Field(..., title="Time Entry ID")


class CreateTimeEntry(BaseModel):
    operation: Literal["create_time_entry"] = _field(
        "create_time_entry", "Time Entries", "Create Time Entry"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    start: str = Field(
        ..., title="Start", description="ISO 8601 UTC; omit End to start a timer."
    )
    end: Optional[str] = Field(
        None, title="End", description="ISO 8601 UTC. Leave empty for a running timer."
    )
    description: Optional[str] = Field(None, title="Description", max_length=3000)
    project_id: Optional[str] = Field(
        None,
        title="Project ID",
        json_schema_extra=_picker("project_id", "project", "workspace_id"),
    )
    task_id: Optional[str] = Field(None, title="Task ID")
    billable: Optional[bool] = Field(None, title="Billable")
    tag_ids: Optional[List[str]] = Field(None, title="Tag IDs")
    custom_fields_json: Optional[str] = Field(
        None,
        title="Custom Fields JSON",
        description="JSON array of required workspace custom field values, if any.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class StopTimer(BaseModel):
    operation: Literal["stop_timer"] = _field(
        "stop_timer", "Time Entries", "Stop Timer"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    end: str = Field(
        ...,
        title="End",
        description="ISO 8601 UTC time to stop the connected user's timer.",
    )


class DeleteTimeEntry(BaseModel):
    operation: Literal["delete_time_entry"] = _field(
        "delete_time_entry", "Time Entries", "Delete Time Entry"
    )
    workspace_id: str = Field(
        ..., title="Workspace", json_schema_extra=_picker("workspace_id", "workspace")
    )
    entry_id: str = Field(..., title="Time Entry ID")


ClockifyOperation = Annotated[
    Union[
        GetCurrentUser,
        ListWorkspaces,
        ListProjects,
        CreateProject,
        ListClients,
        CreateClient,
        ListTags,
        CreateTag,
        ListTasks,
        CreateTask,
        ListTimeEntries,
        GetTimeEntry,
        CreateTimeEntry,
        StopTimer,
        DeleteTimeEntry,
    ],
    Discriminator("operation"),
]


class ClockifyNodeConfig(NodeConfig[ClockifyOperation, ClockifyApiKeyCredential]):
    pass


class ClockifyNode(WorkflowNode):
    integration_type = "automation-clockify"

    connection_evidence = ConnectionEvidence(
        operation="list_workspaces",
        noun="workspaces",
        identity_operation="get_current_user",
    )
    edit_examples = [
        "List my Clockify workspaces and projects",
        "Start a Clockify timer for this project",
        "Stop my current Clockify timer",
        "Get my Clockify time entries this week",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return ClockifyNodeConfig

    @staticmethod
    async def _request(
        credential: ClockifyApiKeyCredential,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"https://{credential.api_domain}/api/v1{path}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                method,
                url,
                headers={"X-Api-Key": credential.api_key},
                params=params,
                json=body,
            )
        response.raise_for_status()
        return response.json() if response.content else None

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name not in ("workspace_id", "project_id"):
            return {"options": []}
        credential = ClockifyApiKeyCredential.model_validate(credential_data)
        if field_name == "workspace_id":
            rows = await cls._request(credential, "GET", "/workspaces")
        else:
            workspace_id = (context or {}).get("workspace_id")
            if not workspace_id:
                return {"options": []}
            rows = await cls._request(
                credential,
                "GET",
                f"/workspaces/{_id(workspace_id)}/projects",
                params={"page": 1, "page-size": 100, "name": search}
                if search
                else {"page": 1, "page-size": 100},
            )
        return {
            "options": [
                {"value": row["id"], "label": row.get("name") or row["id"]}
                for row in rows
                if isinstance(row, dict) and row.get("id")
            ]
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not isinstance(config, ClockifyNodeConfig) or not config.credentials:
            raise ValueError(
                "Clockify API key credential and configuration are required"
            )
        op = config.config
        cred = config.credentials
        start_time = time.monotonic()
        try:
            if isinstance(op, GetCurrentUser):
                data = await self._request(cred, "GET", "/user")
            elif isinstance(op, ListWorkspaces):
                data = await self._request(cred, "GET", "/workspaces")
            elif isinstance(op, ListProjects):
                params = {"page": op.page, "page-size": op.page_size}
                if op.name:
                    params["name"] = op.name
                data = await self._request(
                    cred,
                    "GET",
                    f"/workspaces/{_id(op.workspace_id)}/projects",
                    params=params,
                )
            elif isinstance(op, CreateProject):
                body = {"name": op.name}
                for key, value in {
                    "clientId": op.client_id,
                    "billable": op.billable,
                    "isPublic": op.is_public,
                    "note": op.note,
                }.items():
                    if value is not None:
                        body[key] = value
                data = await self._request(
                    cred,
                    "POST",
                    f"/workspaces/{_id(op.workspace_id)}/projects",
                    body=body,
                )
            elif isinstance(op, ListClients):
                params = {"page": op.page, "page-size": op.page_size}
                if op.name:
                    params["name"] = op.name
                data = await self._request(
                    cred,
                    "GET",
                    f"/workspaces/{_id(op.workspace_id)}/clients",
                    params=params,
                )
            elif isinstance(op, CreateClient):
                body = {"name": op.name}
                for key, value in {
                    "email": op.email,
                    "address": op.address,
                    "note": op.note,
                }.items():
                    if value is not None:
                        body[key] = value
                data = await self._request(
                    cred,
                    "POST",
                    f"/workspaces/{_id(op.workspace_id)}/clients",
                    body=body,
                )
            elif isinstance(op, ListTags):
                params = {"page": op.page, "page-size": op.page_size}
                if op.name:
                    params["name"] = op.name
                data = await self._request(
                    cred,
                    "GET",
                    f"/workspaces/{_id(op.workspace_id)}/tags",
                    params=params,
                )
            elif isinstance(op, CreateTag):
                data = await self._request(
                    cred,
                    "POST",
                    f"/workspaces/{_id(op.workspace_id)}/tags",
                    body={"name": op.name},
                )
            elif isinstance(op, ListTasks):
                params = {"page": op.page, "page-size": op.page_size}
                if op.name:
                    params["name"] = op.name
                data = await self._request(
                    cred,
                    "GET",
                    f"/workspaces/{_id(op.workspace_id)}/projects/{_id(op.project_id)}/tasks",
                    params=params,
                )
            elif isinstance(op, CreateTask):
                body = {"name": op.name}
                if op.assignee_ids is not None:
                    body["assigneeIds"] = op.assignee_ids
                if op.estimate is not None:
                    body["estimate"] = op.estimate
                data = await self._request(
                    cred,
                    "POST",
                    f"/workspaces/{_id(op.workspace_id)}/projects/{_id(op.project_id)}/tasks",
                    body=body,
                )
            elif isinstance(op, ListTimeEntries):
                user_id = (
                    _id(op.user_id)
                    if op.user_id
                    else _id((await self._request(cred, "GET", "/user"))["id"])
                )
                params = {"page": op.page, "page-size": op.page_size}
                for key, value in {
                    "start": op.start,
                    "end": op.end,
                    "project": op.project_id,
                }.items():
                    if value:
                        params[key] = value
                data = await self._request(
                    cred,
                    "GET",
                    f"/workspaces/{_id(op.workspace_id)}/user/{user_id}/time-entries",
                    params=params,
                )
            elif isinstance(op, GetTimeEntry):
                data = await self._request(
                    cred,
                    "GET",
                    f"/workspaces/{_id(op.workspace_id)}/time-entries/{_id(op.entry_id)}",
                )
            elif isinstance(op, CreateTimeEntry):
                body = {"start": op.start}
                for key, value in {
                    "end": op.end,
                    "description": op.description,
                    "projectId": op.project_id,
                    "taskId": op.task_id,
                    "billable": op.billable,
                    "tagIds": op.tag_ids,
                }.items():
                    if value is not None:
                        body[key] = value
                if op.custom_fields_json:
                    import json

                    custom_fields = json.loads(op.custom_fields_json)
                    if not isinstance(custom_fields, list):
                        raise ValueError("Custom Fields JSON must be an array")
                    body["customFields"] = custom_fields
                data = await self._request(
                    cred,
                    "POST",
                    f"/workspaces/{_id(op.workspace_id)}/time-entries",
                    body=body,
                )
            elif isinstance(op, StopTimer):
                user_id = _id((await self._request(cred, "GET", "/user"))["id"])
                data = await self._request(
                    cred,
                    "PATCH",
                    f"/workspaces/{_id(op.workspace_id)}/user/{user_id}/time-entries",
                    body={"end": op.end},
                )
            elif isinstance(op, DeleteTimeEntry):
                data = await self._request(
                    cred,
                    "DELETE",
                    f"/workspaces/{_id(op.workspace_id)}/time-entries/{_id(op.entry_id)}",
                )
            else:
                raise ValueError("Unsupported Clockify operation")
            key = {
                "list_workspaces": "workspaces",
                "list_projects": "projects",
                "list_time_entries": "time_entries",
                "list_clients": "clients",
                "list_tags": "tags",
                "list_tasks": "tasks",
            }.get(op.operation, "result")
            return {
                "status": "success",
                "action": op.operation,
                "data": {key: data},
                "timing_ms": {
                    "total": round((time.monotonic() - start_time) * 1000, 2)
                },
            }
        except httpx.HTTPStatusError as exc:
            return {
                "status": "error",
                "action": op.operation,
                "status_code": exc.response.status_code,
                "error": f"Clockify API returned HTTP {exc.response.status_code}",
            }
        except httpx.RequestError:
            return {
                "status": "error",
                "action": op.operation,
                "error": "Clockify API request failed",
            }
