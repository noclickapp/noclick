"""Reclaim AI task, habit and calendar operations from the published API 0.1.

A personal API key authenticates fixed routes; each operation makes one request.
Task pages expose the provider's cursor without silently fetching more pages.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.app.reclaim.ai"


class ReclaimAIAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Reclaim AI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.reclaim.ai/settings/integrations/raycast",
            "x-credential-instructions": "In Reclaim, open Settings > Integrations > Raycast and generate an API key. Paste the key without the Bearer prefix. Choose an expiration lifetime and replace the saved key when it expires. NoClick verifies it by reading your current Reclaim profile.",
        })
    credential_type: Literal["reclaim_ai_api_key"] = Field("reclaim_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current User", json_schema_extra={"ui:hidden": True})


class ListTasks(_Input):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", description="Read one cursor page. Pass last as after when hasNextPage is true.", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, title="Search text")
    sort: Literal["DUE_DATE", "NAME", "PRIORITY", "SORT_ORDER"] | None = None
    relativeDue: Literal["TODAY", "THIS_WEEK", "THIS_MONTH"] | None = Field(None, title="Relative due date")
    completed: bool | None = None
    dueBefore: date | None = Field(None, title="Due before")
    dueAfter: date | None = Field(None, title="Due after")
    overdue: bool | None = None
    hasDuration: bool | None = Field(None, title="Has duration")
    after: str | None = Field(None, title="Page cursor", description="The last cursor from the previous page.")
    order: Literal["ASCENDING", "DESCENDING", "UNSORTED"] | None = None
    count: int = Field(20, ge=1, le=100, title="Page size")


class _Task(_Input):
    task_id: int = Field(..., ge=1, title="Task ID", description="Numeric Reclaim task ID.")


class GetTask(_Task):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})


class DeleteTask(_Task):
    operation: Literal["delete_task"] = Field("delete_task", title="Delete Task", description="Permanently delete the selected task.", json_schema_extra={"ui:hidden": True})


class _TaskFields(_Input):
    description: str | None = None
    dueDate: date | None = Field(None, title="Due date")
    startDate: date | None = Field(None, title="Start date")
    estimateMinutes: int | None = Field(None, ge=0, title="Estimated minutes")
    priority: Literal["P1", "P2", "P3", "P4", "PRIORITIZE", "DEFAULT"] | None = None


class CreateTask(_TaskFields):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, title="Title")


class UpdateTask(_Task, _TaskFields):
    operation: Literal["update_task"] = Field("update_task", title="Update Task", description="Update supplied fields. Set completed to true to complete a task or false to reopen it.", json_schema_extra={"ui:hidden": True})
    title: str | None = Field(None, min_length=1)
    completed: bool | None = None


class GetPrimaryCalendar(_Input):
    operation: Literal["get_primary_calendar"] = Field("get_primary_calendar", title="Get Primary Calendar", json_schema_extra={"ui:hidden": True})


class ListPersonalCalendars(_Input):
    operation: Literal["list_personal_calendars"] = Field("list_personal_calendars", title="List Personal Calendars", json_schema_extra={"ui:hidden": True})


class ListHabits(_Input):
    operation: Literal["list_habits"] = Field("list_habits", title="List Smart Habits", json_schema_extra={"ui:hidden": True})


class _Habit(_Input):
    lineage_id: int = Field(..., ge=1, title="Habit lineage ID", description="The lineage ID returned by List Smart Habits.")


class GetHabit(_Habit):
    operation: Literal["get_habit"] = Field("get_habit", title="Get Smart Habit", json_schema_extra={"ui:hidden": True})


class UpdateHabit(_Habit):
    operation: Literal["update_habit"] = Field("update_habit", title="Update Smart Habit", description="Change title, description or duration. Only supplied fields are sent.", json_schema_extra={"ui:hidden": True})
    title: str = Field(None, min_length=1)
    description: str | None = None
    durationMinMins: int = Field(None, ge=1, title="Minimum duration in minutes")
    durationMaxMins: int | None = Field(None, ge=1, title="Maximum duration in minutes")
    sendUpdates: bool | None = Field(None, title="Send calendar updates")


class DeleteHabit(_Habit):
    operation: Literal["delete_habit"] = Field("delete_habit", title="Delete Smart Habit", description="Delete the selected habit lineage.", json_schema_extra={"ui:hidden": True})
    sendUpdates: bool | None = Field(None, title="Send calendar updates")
    restoreIfAvailable: bool | None = Field(None, title="Restore original event if available")


class DisableHabit(_Habit):
    operation: Literal["disable_habit"] = Field("disable_habit", title="Disable Smart Habit", json_schema_extra={"ui:hidden": True})


class EnableHabit(_Habit):
    operation: Literal["enable_habit"] = Field("enable_habit", title="Enable Smart Habit", json_schema_extra={"ui:hidden": True})


ReclaimAIOperation = Annotated[Union[GetCurrentUser, ListTasks, GetTask, CreateTask, UpdateTask, DeleteTask,
    GetPrimaryCalendar, ListPersonalCalendars, ListHabits, GetHabit, UpdateHabit, DeleteHabit,
    DisableHabit, EnableHabit], Field(discriminator="operation")]


class ReclaimAIConfig(NodeConfig[ReclaimAIOperation, ReclaimAIAPIKeyCredential]):
    pass


# Every entry names exactly one operation in Reclaim's published contract.
ROUTES = {
    "get_current_user": ("GET", "/api/users/current", (), False),
    "list_tasks": ("GET", "/api/reclaim-tasks/page", ("query", "sort", "relativeDue", "completed", "dueBefore", "dueAfter", "overdue", "hasDuration", "after", "order", "count"), False),
    "get_task": ("GET", "/api/reclaim-tasks/{task_id}", (), False),
    "create_task": ("POST", "/api/reclaim-tasks", (), True),
    "update_task": ("PATCH", "/api/reclaim-tasks/{task_id}", (), True),
    "delete_task": ("DELETE", "/api/reclaim-tasks/{task_id}", (), False),
    "get_primary_calendar": ("GET", "/api/calendars/primary", (), False),
    "list_personal_calendars": ("GET", "/api/calendars/personal", (), False),
    "list_habits": ("GET", "/api/smart-habits", (), False),
    "get_habit": ("GET", "/api/smart-habits/{lineage_id}", (), False),
    "update_habit": ("PATCH", "/api/smart-habits/{lineage_id}", ("sendUpdates",), True),
    "delete_habit": ("DELETE", "/api/smart-habits/{lineage_id}", ("sendUpdates", "restoreIfAvailable"), False),
    "disable_habit": ("DELETE", "/api/smart-habits/{lineage_id}/disable", (), False),
    "enable_habit": ("POST", "/api/smart-habits/{lineage_id}/enable", (), False),
}


class ReclaimAINode(WorkflowNode):
    integration_type = "automation-reclaim-ai"
    connection_evidence = ConnectionEvidence(noun="Reclaim profile", identity_operation="get_current_user",
        label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return ReclaimAIConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Reclaim AI API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, query_names, has_body = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_unset=True, exclude={"operation"})
        if isinstance(op, ListTasks):
            values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("task_id", "lineage_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        params = {k: values.pop(k) for k in query_names if k in values}
        params = {k: v for k, v in params.items() if v is not None}
        if has_body and not values:
            raise ValueError("Supply at least one field to update")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": values} if has_body else {}))
        if response.status_code != 200:
            message = response.text.replace(token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": message or "Reclaim did not confirm the request"}
        if op.operation == "delete_task":
            return {"status": "success", "data": None}
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Expected a Reclaim JSON object or array")
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            return {"status": "error", "error": str(data).replace(token, "[redacted]")[:2000]}
        if isinstance(op, GetCurrentUser):
            # User includes internal settings and hashes; expose only connection identity.
            data = {k: data[k] for k in ("id", "name", "email", "timezone") if k in data}
            if not data.get("id"):
                raise ValueError("Reclaim profile did not contain an account ID")
        return {"status": "success", "data": data}
