"""TimeCamp personal-token operations from its published OpenAPI 1.0 contract."""
from __future__ import annotations

import re
from datetime import date as Date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.timecamp.com/third_party/api"


class TimecampAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Timecamp API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.timecamp.com/app#/settings/users/me",
            "x-credential-instructions": "Copy your API token from TimeCamp's profile settings and paste it here without the Bearer prefix. NoClick checks your profile and uses the token for the operations you select.",
        })
    credential_type: Literal["timecamp_api_token"] = Field("timecamp_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API token as text")
        value = clean_secret(value, field_name="API token", key=True)
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


PositiveID = Annotated[int, Field(ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=1000)]


class GetMe(_Input):
    """Read the authenticated user's profile."""
    operation: Literal["get_me"] = "get_me"


class ListUsers(_Input):
    operation: Literal["list_users"] = "list_users"
    active_only: bool | None = None


class GetUser(_Input):
    operation: Literal["get_user"] = "get_user"
    user_id: PositiveID


class ListTasks(_Input):
    """Read the provider's task map; the endpoint has no pagination parameters."""
    operation: Literal["list_tasks"] = "list_tasks"
    task_id: str | None = Field(None, pattern=r"^[1-9][0-9]*(,[1-9][0-9]*)*$", max_length=2000,
        description="Optional comma-separated task IDs.")
    external_task_id: Text | None = None
    status: Literal["active", "archived", "all"] = "active"
    minimal: Literal["0", "1"] = "0"


class _TaskFields(_Input):
    name: Text | None = None
    parent_id: int | None = Field(None, ge=0)
    external_task_id: Text | None = None
    external_parent_id: Text | None = None
    note: str | None = Field(None, max_length=10000)
    keywords: str | None = Field(None, max_length=2000)


class CreateTask(_TaskFields):
    operation: Literal["create_task"] = "create_task"
    name: Text
    billable: Literal[0, 1] | None = None
    budgeted: int | None = Field(None, ge=0)
    budget_unit: Literal["hours", "fee"] | None = None


class UpdateTask(_TaskFields):
    operation: Literal["update_task"] = "update_task"
    task_id: PositiveID
    archived: Literal[0, 1] | None = None

    @model_validator(mode="after")
    def changes(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "task_id"}):
            raise ValueError("Provide at least one task field to change")
        return self


class DeleteTask(_Input):
    operation: Literal["delete_task"] = "delete_task"
    task_id: PositiveID


class GetTaskDetails(_Input):
    operation: Literal["get_task_details"] = "get_task_details"
    tasks: str = Field(..., pattern=r"^[1-9][0-9]*(,[1-9][0-9]*)*$", max_length=2000,
        description="Comma-separated task IDs.")


class ListEntries(_Input):
    operation: Literal["list_entries"] = "list_entries"
    from_date: Date = Field(..., description="First entry date, YYYY-MM-DD; sent as from.")
    to_date: Date = Field(..., description="Last entry date, YYYY-MM-DD; sent as to.")
    user_ids: str | None = Field(None, pattern=r"^(me|[1-9][0-9]*(,[1-9][0-9]*)*)$", max_length=2000)

    @model_validator(mode="after")
    def date_order(self):
        if self.to_date < self.from_date:
            raise ValueError("The last date must be on or after the first date")
        return self


class CreateEntry(_Input):
    operation: Literal["create_entry"] = "create_entry"
    date: Date
    duration: int = Field(..., ge=1, description="Duration in seconds.")
    user_id: PositiveID | None = None
    task_id: PositiveID | None = None
    note: str | None = Field(None, max_length=10000)
    billable: bool | None = None


class UpdateEntry(_Input):
    operation: Literal["update_entry"] = "update_entry"
    id: PositiveID = Field(..., title="Entry ID")
    duration: int | None = Field(None, ge=1, description="Duration in seconds.")
    date: Date | None = None
    task_id: PositiveID | None = None
    note: str | None = Field(None, max_length=10000)
    billable: bool | None = None

    @model_validator(mode="after")
    def changes(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "id"}):
            raise ValueError("Provide at least one entry field to change")
        return self


class DeleteEntry(_Input):
    operation: Literal["delete_entry"] = "delete_entry"
    id: PositiveID = Field(..., title="Entry ID")


class GetTimerStatus(_Input):
    operation: Literal["get_timer_status"] = "get_timer_status"


class StartTimer(_Input):
    operation: Literal["start_timer"] = "start_timer"
    taskId: PositiveID | None = Field(None, title="Task ID")
    entryId: PositiveID | Literal["create"] = Field("create", title="Entry ID", description="Existing entry ID or create.")
    note: str | None = Field(None, max_length=10000)


class StopTimer(_Input):
    operation: Literal["stop_timer"] = "stop_timer"
    timerId: PositiveID | None = Field(None, title="Timer ID", description="Omit to stop the current user's timer.")


class CreateTag(_Input):
    operation: Literal["create_tag"] = "create_tag"
    list: PositiveID = Field(..., title="Tag list ID")
    name: Text


class GetTag(_Input):
    operation: Literal["get_tag"] = "get_tag"
    tag_id: PositiveID


class UpdateTag(_Input):
    operation: Literal["update_tag"] = "update_tag"
    tag_id: PositiveID
    name: Text | None = None
    archived: Literal[0, 1] | None = None

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.archived is None:
            raise ValueError("Provide a tag name or archive state")
        return self


class ListTagLists(_Input):
    operation: Literal["list_tag_lists"] = "list_tag_lists"
    task_id: PositiveID | None = None
    archived: Literal[0, 1] | None = None
    tags: Literal[0, 1] | None = None


class CreateTagList(_Input):
    operation: Literal["create_tag_list"] = "create_tag_list"
    name: Text


class ListTags(_Input):
    operation: Literal["list_tags"] = "list_tags"
    tag_list_id: PositiveID


TimecampConfig = Annotated[Union[
    GetMe, ListUsers, GetUser, ListTasks, CreateTask, UpdateTask, DeleteTask,
    GetTaskDetails, ListEntries, CreateEntry, UpdateEntry, DeleteEntry,
    GetTimerStatus, StartTimer, StopTimer, CreateTag, GetTag, UpdateTag,
    ListTagLists, CreateTagList, ListTags,
], Field(discriminator="operation")]


class TimecampFullConfig(NodeConfig[TimecampConfig, TimecampAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Exactly one contract operation per workflow operation; no implicit follow-up writes.
ROUTES = {
    "get_me": ("GET", "/me"),
    "list_users": ("GET", "/users"),
    "get_user": ("GET", "/user/{user_id}"),
    "list_tasks": ("GET", "/tasks"),
    "create_task": ("POST", "/tasks"),
    "update_task": ("PUT", "/tasks"),
    "delete_task": ("DELETE", "/tasks"),
    "get_task_details": ("GET", "/task_details"),
    "list_entries": ("GET", "/entries"),
    "create_entry": ("POST", "/entries"),
    "update_entry": ("PUT", "/entries"),
    "delete_entry": ("DELETE", "/entries"),
    "get_timer_status": ("GET", "/v3/timer/status"),
    "start_timer": ("POST", "/v3/timer/start"),
    "stop_timer": ("POST", "/v3/timer/stop"),
    "create_tag": ("POST", "/tag"),
    "get_tag": ("GET", "/tag/{tag_id}"),
    "update_tag": ("PUT", "/tag/{tag_id}"),
    "list_tag_lists": ("GET", "/tag_list"),
    "create_tag_list": ("POST", "/tag_list"),
    "list_tags": ("GET", "/tag_list/{tag_list_id}/tags"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()}
    return value


class TimecampNode(WorkflowNode):
    integration_type = "automation-timecamp"
    connection_evidence = ConnectionEvidence(noun="TimeCamp account", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return TimecampFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, TimecampFullConfig) or not self.config.credentials:
            raise ValueError("Attach a TimeCamp API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{field: values.pop(field) for field in fields})
        if config.operation == "list_entries":
            values["from"] = values.pop("from_date")
            values["to"] = values.pop("to_date")
        if config.operation == "delete_task":
            values["task_id"] = str(values["task_id"])
        kwargs = {}
        if method == "GET" or config.operation == "delete_task":
            if values:
                kwargs["params"] = values
        else:
            kwargs["json"] = values
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except Exception:
            raise ValueError("TimeCamp request did not complete; check the provider before retrying a write") from None
        if len(response.content) > 10_000_000:
            raise ValueError("TimeCamp response exceeds the size limit")
        if response.status_code >= 300:
            try:
                error = response.json()
            except ValueError:
                error = "TimeCamp rejected the request"
            return _redact({"status": "error", "http_status": response.status_code, "error": error}, token)
        # These are the two contract operations with documented empty success bodies.
        empty_ok = (config.operation == "delete_entry" and response.status_code == 204) or (config.operation == "update_tag" and response.status_code == 201)
        if empty_ok and not response.content:
            return {"status": "success", "http_status": response.status_code, "operation": config.operation,
                "data": None, "acknowledged": True}
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from TimeCamp")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("TimeCamp returned invalid JSON") from None
        if isinstance(body, dict) and (body.get("error") or body.get("errors") or body.get("success") is False):
            return _redact({"status": "error", "http_status": response.status_code, "error": body}, token)
        allowed = {201} if config.operation == "create_task" else {200, 201} if config.operation == "update_tag" else {200, 204} if config.operation == "delete_entry" else {200}
        if response.status_code not in allowed:
            raise ValueError("TimeCamp returned an undocumented success status")
        if config.operation in {"create_tag", "create_tag_list"}:
            if type(body) is not int or body < 1:
                raise ValueError("TimeCamp did not return the created resource ID")
        elif not isinstance(body, (dict, list)):
            raise ValueError("TimeCamp returned an unexpected response shape")
        if config.operation == "get_me" and (not isinstance(body, dict) or not body.get("user_id") or not body.get("email")):
            raise ValueError("TimeCamp did not return an account identity")
        # Preserve task-ID maps, arrays and timer envelopes as published; no invented paging.
        return _redact({"status": "success", "operation": config.operation,
            "http_status": response.status_code, "data": body}, token)
