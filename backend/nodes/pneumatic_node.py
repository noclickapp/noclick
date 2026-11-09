"""Single-request operations for Pneumatic Workflow API v1.0.0.

Contract: https://api.pneumatic.app/api/schema/ . Lists return one provider
page with its pagination metadata. Writes are never retried automatically.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.pneumatic.app"


class PneumaticAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Pneumatic API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.pneumatic.app/api/schema/",
            "x-credential-instructions": "In Pneumatic, open Integrations and copy Your API Key. Paste the key here without the Bearer prefix. NoClick reads your account to verify the connection.",
        })
    credential_type: Literal["pneumatic_api_key"] = Field("pneumatic_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("due_date_tsp", "date", mode="before", check_fields=False)
    @classmethod
    def timestamp(cls, value):
        if value is None or value == "":
            return None
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Include a timezone in the ISO 8601 date")
        return value


class PneumaticGetAccountConfig(_Input):
    """Read the connected account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})

class PneumaticListUsersConfig(_Input):
    """List account users, one page at a time."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1000000)
    groups: str | None = Field(None, max_length=10000, description="Groups")
    is_ai: bool | None = Field(None, description="Is ai")
    ordering: str | None = Field(None, max_length=10000, description="Ordering")
    status: str | None = Field(None, max_length=10000, description="Status")
    type: str | None = Field(None, max_length=10000, description="Type")

class PneumaticGetUserConfig(_Input):
    """Read an account user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1)

class PneumaticListGroupsConfig(_Input):
    """List account groups, one page at a time."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1000000)
    ordering: str | None = Field(None, max_length=10000, description="Ordering")

class PneumaticGetGroupConfig(_Input):
    """Read an account group."""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., ge=1)

class PneumaticListTemplatesConfig(_Input):
    """Find workflow templates, one page at a time."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1000000)
    ordering: str | None = Field(None, max_length=10000, description="Ordering")
    search: str | None = Field(None, max_length=10000, description="Search")
    is_active: bool | None = Field(None, description="Is active")
    is_public: bool | None = Field(None, description="Is public")

class PneumaticGetTemplateConfig(_Input):
    """Read a workflow template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1)

class PneumaticGetTemplateFieldsConfig(_Input):
    """Read the fields used by a workflow template."""
    operation: Literal["get_template_fields"] = Field("get_template_fields", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1)

class PneumaticListTemplateStepsConfig(_Input):
    """List the steps of a workflow template."""
    operation: Literal["list_template_steps"] = Field("list_template_steps", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1)
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1000000)
    with_tasks_in_progress: bool | None = Field(None, description="With tasks in progress")

class PneumaticRunWorkflowConfig(_Input):
    """Start a workflow from a template with optional kickoff data."""
    operation: Literal["run_workflow"] = Field("run_workflow", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1)
    name: str | None = Field(None, max_length=10000, description="Name")
    is_urgent: bool | None = Field(None, description="Is urgent")
    kickoff: dict[str, Any] | None = Field(None, description="Kickoff")
    due_date_tsp: str | None = Field(None, max_length=10000, title="Due date", description="ISO 8601 date and time with timezone", json_schema_extra={"format": "date-time"})
    ancestor_task_id: int | None = Field(None, ge=1, description="Ancestor task id")

class PneumaticListWorkflowsConfig(_Input):
    """Find workflows, one page at a time."""
    operation: Literal["list_workflows"] = Field("list_workflows", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1000000)
    search: str | None = Field(None, max_length=10000, description="Search")
    ordering: str | None = Field(None, max_length=10000, description="Ordering")
    status: str | None = Field(None, max_length=10000, description="Status")
    template_id: str | None = Field(None, max_length=10000, description="Template id")
    current_performer: str | None = Field(None, max_length=10000, description="Current performer")
    workflow_starter: str | None = Field(None, max_length=10000, description="Workflow starter")
    fields: str | None = Field(None, max_length=10000, description="Fields")
    template_task_api_name: str | None = Field(None, max_length=10000, description="Template task api name")

class PneumaticGetWorkflowConfig(_Input):
    """Read a workflow and its progress."""
    operation: Literal["get_workflow"] = Field("get_workflow", json_schema_extra={"ui:hidden": True})
    workflow_id: int = Field(..., ge=1)

class PneumaticUpdateWorkflowConfig(_Input):
    """Change workflow name, urgency, kickoff data or due date."""
    operation: Literal["update_workflow"] = Field("update_workflow", json_schema_extra={"ui:hidden": True})
    workflow_id: int = Field(..., ge=1)
    name: str | None = Field(None, max_length=10000, description="Name")
    is_urgent: bool | None = Field(None, description="Is urgent")
    kickoff: dict[str, Any] | None = Field(None, description="Kickoff")
    due_date_tsp: str | None = Field(None, max_length=10000, title="Due date", description="ISO 8601 date and time with timezone", json_schema_extra={"format": "date-time"})
    clear_due_date: bool = Field(False, description="Clear the workflow due date instead of setting one.")


class PneumaticCommentWorkflowConfig(_Input):
    """Add a comment to a workflow."""
    operation: Literal["comment_workflow"] = Field("comment_workflow", json_schema_extra={"ui:hidden": True})
    workflow_id: int = Field(..., ge=1)
    text: str = Field(..., max_length=10000, description="Text")

class PneumaticListWorkflowEventsConfig(_Input):
    """Read workflow activity and comments."""
    operation: Literal["list_workflow_events"] = Field("list_workflow_events", json_schema_extra={"ui:hidden": True})
    workflow_id: int = Field(..., ge=1)
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1000000)
    ordering: str | None = Field(None, max_length=10000, description="Ordering")
    include_comments: bool | None = Field(None, description="Include comments")
    only_attachments: bool | None = Field(None, description="Only attachments")

class PneumaticSnoozeWorkflowConfig(_Input):
    """Pause a workflow until the selected date."""
    operation: Literal["snooze_workflow"] = Field("snooze_workflow", json_schema_extra={"ui:hidden": True})
    workflow_id: int = Field(..., ge=1)
    date: str = Field(..., max_length=10000, description="Resume date and time in ISO 8601 format with timezone", json_schema_extra={"format": "date-time"})

class PneumaticListTasksConfig(_Input):
    """Find assigned tasks, one page at a time."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1000000)
    search: str | None = Field(None, max_length=10000, description="Search")
    ordering: str | None = Field(None, max_length=10000, description="Ordering")
    assigned_to: int | None = Field(None, ge=1, description="Assigned to")
    is_completed: bool | None = Field(None, description="Is completed")
    template_id: int | None = Field(None, ge=1, description="Template id")
    template_task_api_name: str | None = Field(None, max_length=10000, description="Template task api name")

class PneumaticGetTaskConfig(_Input):
    """Read a task and its fields."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

class PneumaticCommentTaskConfig(_Input):
    """Add a comment to a task."""
    operation: Literal["comment_task"] = Field("comment_task", json_schema_extra={"ui:hidden": True})
    task_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(..., max_length=10000, description="Text")

class PneumaticCompleteTaskConfig(_Input):
    """Complete a task with optional output fields."""
    operation: Literal["complete_task"] = Field("complete_task", json_schema_extra={"ui:hidden": True})
    task_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    output: dict[str, Any] | None = Field(None, description="Output")

class PneumaticSetTaskDueDateConfig(_Input):
    """Set the due date of a task."""
    operation: Literal["set_task_due_date"] = Field("set_task_due_date", json_schema_extra={"ui:hidden": True})
    task_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    due_date_tsp: str = Field(..., max_length=10000, title="Due date", description="ISO 8601 date and time with timezone", json_schema_extra={"format": "date-time"})

class PneumaticClearTaskDueDateConfig(_Input):
    """Clear the due date of a task."""
    operation: Literal["clear_task_due_date"] = Field("clear_task_due_date", json_schema_extra={"ui:hidden": True})
    task_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

PneumaticConfig = Annotated[Union[
    PneumaticGetAccountConfig,
    PneumaticListUsersConfig,
    PneumaticGetUserConfig,
    PneumaticListGroupsConfig,
    PneumaticGetGroupConfig,
    PneumaticListTemplatesConfig,
    PneumaticGetTemplateConfig,
    PneumaticGetTemplateFieldsConfig,
    PneumaticListTemplateStepsConfig,
    PneumaticRunWorkflowConfig,
    PneumaticListWorkflowsConfig,
    PneumaticGetWorkflowConfig,
    PneumaticUpdateWorkflowConfig,
    PneumaticCommentWorkflowConfig,
    PneumaticListWorkflowEventsConfig,
    PneumaticSnoozeWorkflowConfig,
    PneumaticListTasksConfig,
    PneumaticGetTaskConfig,
    PneumaticCommentTaskConfig,
    PneumaticCompleteTaskConfig,
    PneumaticSetTaskDueDateConfig,
    PneumaticClearTaskDueDateConfig
], Field(discriminator="operation")]


class PneumaticFullConfig(NodeConfig[PneumaticConfig, PneumaticAPIKeyCredential]):
    pass


OPERATIONS = {
    'get_account': ('GET', '/accounts/account', None),
    'list_users': ('GET', '/accounts/users', None),
    'get_user': ('GET', '/accounts/users/{id}', 'user_id'),
    'list_groups': ('GET', '/accounts/groups', None),
    'get_group': ('GET', '/accounts/groups/{id}', 'group_id'),
    'list_templates': ('GET', '/templates', None),
    'get_template': ('GET', '/templates/{id}', 'template_id'),
    'get_template_fields': ('GET', '/templates/{id}/fields', 'template_id'),
    'list_template_steps': ('GET', '/templates/{id}/steps', 'template_id'),
    'run_workflow': ('POST', '/templates/{id}/run', 'template_id'),
    'list_workflows': ('GET', '/workflows', None),
    'get_workflow': ('GET', '/workflows/{id}', 'workflow_id'),
    'update_workflow': ('PATCH', '/workflows/{id}', 'workflow_id'),
    'comment_workflow': ('POST', '/workflows/{id}/comment', 'workflow_id'),
    'list_workflow_events': ('GET', '/workflows/{id}/events', 'workflow_id'),
    'snooze_workflow': ('POST', '/workflows/{id}/snooze', 'workflow_id'),
    'list_tasks': ('GET', '/v3/tasks', None),
    'get_task': ('GET', '/v2/tasks/{id}', 'task_id'),
    'comment_task': ('POST', '/v2/tasks/{id}/comment', 'task_id'),
    'complete_task': ('POST', '/v2/tasks/{id}/complete', 'task_id'),
    'set_task_due_date': ('POST', '/v2/tasks/{id}/due-date', 'task_id'),
    'clear_task_due_date': ('DELETE', '/v2/tasks/{id}/due-date', 'task_id'),
}


class PneumaticNode(WorkflowNode):
    integration_type = "automation-pneumatic"
    connection_evidence = ConnectionEvidence(noun="Pneumatic account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return PneumaticFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Pneumatic API key")
        config = self.config.config
        method, path, id_field = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        # Clearing is explicit because the shared config lens treats null as unset.
        if config.operation == "update_workflow" and values.pop("clear_due_date", False):
            values["due_date_tsp"] = None
        if id_field:
            path = path.replace("{id}", quote(str(values.pop(id_field)), safe=""))
        kwargs = {"params": {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}} if method == "GET" else ({"json": values} if method != "DELETE" else {})
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key,
                         "Accept": "application/json"}, **kwargs)
        response.raise_for_status()
        if len(response.content) > 5_000_000:
            raise ValueError("Pneumatic response exceeds the supported size")
        if not response.content:
            if config.operation not in {"set_task_due_date", "clear_task_due_date"}:
                raise ValueError("Pneumatic returned an empty response")
            return {"status": "success", "operation": config.operation, "data": None}
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from Pneumatic")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Expected a Pneumatic object or list")
        if config.operation == "get_account" and (not isinstance(data, dict) or type(data.get("id")) is not int):
            raise ValueError("Pneumatic account response has no account ID")
        return {"status": "success", "operation": config.operation, "data": data}
