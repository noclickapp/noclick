"""Teamcamp public API v1.0: one documented request per operation.

Contract: https://api.teamcamp.app/api-reference/introduction
Detailed project reads and task updates use their operation-level servers.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.teamcamp.app/v1.0"
INTERNAL_API_URL = "https://back.teamcamp.app/api/v1"


class TeamcampAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Teamcamp API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.teamcamp.app/api-reference/introduction",
            "x-credential-instructions": "Copy your API key from Teamcamp Account Settings and paste it here. NoClick sends it in the apiKey header. Connect reads your projects and can verify the key's workspace; write permissions are checked by Teamcamp when an action runs.",
        })
    credential_type: Literal["teamcamp_api_key"] = Field("teamcamp_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


ResourceID = Annotated[str, Field(min_length=10, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]
ReferenceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=1000)]


class CheckConnection(_Input):
    """Verify the API key and return its workspace name and ID."""
    operation: Literal["check_connection"] = "check_connection"


class ListProjects(_Input):
    """List the projects accessible to this key. No pagination is documented."""
    operation: Literal["list_projects"] = "list_projects"


class GetProject(_Input):
    """Read a project by its ID."""
    operation: Literal["get_project"] = "get_project"
    projectId: ResourceID = Field(..., title="Project ID")


class GetProjectDetails(GetProject):
    """Read current project details, including statuses, labels and settings."""
    operation: Literal["get_project_details"] = "get_project_details"


class ListProjectGroups(GetProject):
    """List the task groups in a project."""
    operation: Literal["list_project_groups"] = "list_project_groups"


class _ProjectFields(_Input):
    customerId: ReferenceID | None = Field(None, title="Customer ID")
    startDate: date | None = Field(None, title="Start date", description="YYYY-MM-DD")
    dueDate: date | None = Field(None, title="Due date", description="YYYY-MM-DD")


class CreateProject(_ProjectFields):
    """Create a project, optionally from a template."""
    operation: Literal["create_project"] = "create_project"
    projectName: Name = Field(..., title="Project name")
    templateId: ReferenceID | None = Field(None, title="Template ID")


class UpdateProject(_ProjectFields):
    """Update only the project fields you supply."""
    operation: Literal["update_project"] = "update_project"
    projectId: ReferenceID = Field(..., title="Project ID")
    projectName: Name | None = Field(None, title="Project name")
    description: str | None = Field(None, max_length=100000)
    priority: bool | None = Field(None, title="Enable task priority")
    defaultPriority: Literal["No Priority", "Urgent", "High", "Medium", "Low"] | None = Field(None, title="Default task priority")
    estimate: bool | None = Field(None, title="Enable time estimates")
    milestone: bool | None = Field(None, title="Enable milestones")

    @model_validator(mode="after")
    def changed(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "projectId"}):
            raise ValueError("Supply at least one project field to update")
        return self


class DeleteProject(_Input):
    """Permanently delete the selected project."""
    operation: Literal["delete_project"] = "delete_project"
    projectId: ReferenceID = Field(..., title="Project ID", description="The project to permanently delete")


class ListUsers(_Input):
    """Read workspace users."""
    operation: Literal["list_users"] = "list_users"


class ListCustomers(_Input):
    """Read workspace customers and their clients."""
    operation: Literal["list_customers"] = "list_customers"


class ListTasks(_Input):
    """List a project's tasks, optionally filtered by completion."""
    operation: Literal["list_tasks"] = "list_tasks"
    projectId: ReferenceID = Field(..., title="Project ID")
    complete: bool | None = Field(None, description="Omit to return both completed and incomplete tasks")


class GetTask(_Input):
    """Read one task's details."""
    operation: Literal["get_task"] = "get_task"
    taskId: ResourceID = Field(..., title="Task ID")


class TaskFile(_Input):
    fileType: str | None = None
    href: str | None = None
    name: str | None = None
    size: str | None = None


class _TaskFields(_Input):
    projectId: ReferenceID = Field(..., title="Project ID", description="Required by Teamcamp for both task creation and update")
    description: str | None = Field(None, max_length=100000)
    priority: Literal[0, 1, 2, 3, 4] | None = Field(None, description="0 none, 1 urgent, 2 high, 3 medium, 4 low")
    dueDate: date | None = Field(None, title="Due date", description="YYYY-MM-DD")
    groupId: ReferenceID | None = Field(None, title="Group ID")
    taskUsers: list[ReferenceID] | None = Field(None, title="Assignee user IDs", max_length=1000)
    files: list[TaskFile] | None = Field(None, description="Existing file metadata; this operation does not upload files", max_length=100)
    estimateTime: int | None = Field(None, title="Estimated hours", ge=0)
    milestoneId: int | None = Field(None, title="Milestone ID")
    statusId: ReferenceID | None = Field(None, title="Status ID")


class CreateTask(_TaskFields):
    """Create a task in a project."""
    operation: Literal["create_task"] = "create_task"
    name: Name = Field(..., title="Task name")


class UpdateTask(_TaskFields):
    """Update a task using Teamcamp's task-update API server."""
    operation: Literal["update_task"] = "update_task"
    taskId: ResourceID = Field(..., title="Task ID")
    name: Name | None = Field(None, title="Task name")

    @model_validator(mode="after")
    def changed(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "projectId", "taskId"}):
            raise ValueError("Supply at least one task field to update")
        return self


class PostComment(GetTask):
    """Post a comment on a task."""
    operation: Literal["post_comment"] = "post_comment"
    content: str = Field(..., min_length=1, max_length=100000, title="Comment")


TeamcampOperation = Annotated[Union[
    CheckConnection, ListProjects, GetProject, GetProjectDetails, ListProjectGroups,
    CreateProject, UpdateProject, DeleteProject, ListUsers, ListCustomers,
    ListTasks, GetTask, CreateTask, UpdateTask, PostComment,
], Field(discriminator="operation")]


class TeamcampNodeConfig(NodeConfig[TeamcampOperation, TeamcampAPIKeyCredential]):
    pass


# Fixed routes, including the operation-level server override, are never supplied by a workflow.
ROUTES = {
    "check_connection": ("GET", "/verify"),
    "list_projects": ("GET", "/project"),
    "get_project": ("GET", "/project/{projectId}"),
    "get_project_details": ("GET", "/project/{projectId}/getCurrentProjectDetails"),
    "list_project_groups": ("GET", "/project/{projectId}/group"),
    "create_project": ("POST", "/project"),
    "update_project": ("PUT", "/project/{projectId}"),
    "delete_project": ("DELETE", "/project/{projectId}"),
    "list_users": ("GET", "/company/users"),
    "list_customers": ("GET", "/company/customers"),
    "list_tasks": ("GET", "/task"),
    "get_task": ("GET", "/task/{taskId}"),
    "create_task": ("POST", "/task"),
    "update_task": ("PUT", "/task/updateTask/{taskId}"),
    "post_comment": ("POST", "/task/{taskId}/comments"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class TeamcampNode(WorkflowNode):
    integration_type = "automation-teamcamp"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects",
        label_keys=("projectName", "name", "projectId"), identity_operation="check_connection",
        identity_keys=("workspaceName", "workspaceId"))

    @classmethod
    def get_config_model(cls):
        return TeamcampNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Teamcamp API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("projectId", "taskId"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        base = INTERNAL_API_URL if op.operation in {"update_task", "get_project_details"} else BASE_URL
        params = values if method == "GET" else None
        if params and "complete" in params:
            params["complete"] = "true" if params["complete"] else "false"
        body = values if method in {"POST", "PUT"} else None
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, base + path,
                    headers={"apiKey": secret, "Accept": "application/json"}, params=params, json=body)
        except httpx.RequestError:
            # Never replay writes: a timeout does not establish whether they happened.
            raise ValueError("Teamcamp request did not complete; inspect any write before retrying") from None
        if not 200 <= response.status_code < 300:
            message = "Teamcamp returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("error"), str):
                    message += ": " + error["error"][:2000]
            except ValueError:
                pass
            raise ValueError(_redact(message, secret))
        if op.operation == "delete_project":
            data = None
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Teamcamp JSON response is too large")
            if "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected a JSON response from Teamcamp")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Teamcamp returned invalid JSON") from None
            if isinstance(data, dict) and (data.get("error") or data.get("success") is False):
                message = data.get("error") or data.get("message") or "Teamcamp rejected the request"
                raise ValueError(_redact(str(message), secret))
            if not isinstance(data, (dict, list)):
                raise ValueError("Expected a Teamcamp JSON object or list")
        output = {"status": "success", "operation": op.operation, "data": _redact(data, secret), "http_status": response.status_code}
        if op.operation == "delete_project":
            output["deleted_project_id"] = op.projectId
        await self.emit(output)
        return output
