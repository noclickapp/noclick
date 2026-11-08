"""Process Street v1.1 workflow automation, pinned to its published OpenAPI contract.

Each action sends one documented request. Lists return one page and an opaque
cursor; writes report the API acknowledgement, without claiming readback.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://public-api.process.st/api/v1.1"
CREDENTIAL = "process_street_api_key"
DOCS = "https://public-api.process.st/api/v1.1/docs/openapi.json"


def _identifier(value):
    import re
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", value):
        raise ValueError("Use the 22-character Process Street resource ID")
    return value


Identifier = Annotated[str, BeforeValidator(_identifier), Field(pattern=r"^[A-Za-z0-9_-]{22}$", examples=["laeBb_tXVTkBobaKyAB7oA"])]


def _timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Use an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except ValueError:
        raise ValueError("Use an ISO-8601 UTC timestamp") from None


Timestamp = Annotated[str, BeforeValidator(_timestamp), Field(json_schema_extra={"format": "date-time"})]


class ProcessStreetAPIKey(BaseModel):
    model_config = ConfigDict(title="Process Street API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.process.st/help/docs/api/",
        "x-credential-instructions": "In Process Street organization settings, generate an API key and paste it here. The key uses its creator's permissions. NoClick checks access by listing your workflows; individual actions may require additional permissions.",
    })
    credential_type: Literal["process_street_api_key"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the API key, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page_cursor: str | None = Field(None, min_length=1, max_length=8192, description="Use next_cursor from the preceding page; omit for the first page.")


class ListWorkflows(_Page):
    operation: Literal["list_workflows"] = "list_workflows"
    name: str | None = Field(None, max_length=1024, description="Case-insensitive partial workflow name.")


class GetWorkflow(_Input):
    operation: Literal["get_workflow"] = "get_workflow"
    workflow_id: Identifier


class ListWorkflowTasks(_Page):
    operation: Literal["list_workflow_tasks"] = "list_workflow_tasks"
    workflow_id: Identifier


class ListWorkflowRuns(_Page):
    operation: Literal["list_workflow_runs"] = "list_workflow_runs"
    workflow_id: Identifier | None = None
    status: Literal["Active", "Completed", "Archived"] | None = None


class CreateWorkflowRun(_Input):
    operation: Literal["create_workflow_run"] = "create_workflow_run"
    workflow_id: Identifier
    name: str | None = Field(None, max_length=1024)
    due_date: Timestamp | None = None
    shared: StrictBool | None = Field(None, description="Enable the public run share link. Omit to use the workflow's default.")


class GetWorkflowRun(_Input):
    operation: Literal["get_workflow_run"] = "get_workflow_run"
    workflow_run_id: Identifier


class UpdateWorkflowRun(_Input):
    operation: Literal["update_workflow_run"] = "update_workflow_run"
    workflow_run_id: Identifier
    name: str = Field(..., max_length=1024)
    status: Literal["Active", "Completed", "Archived", "Deleted"]
    shared: StrictBool = Field(..., description="Whether the run can be accessed without signing in.")
    due_date: Timestamp | None = Field(None, description="Replacement due date; omitting clears the existing due date.")


class DeleteWorkflowRun(_Input):
    operation: Literal["delete_workflow_run"] = "delete_workflow_run"
    workflow_run_id: Identifier


class AssignWorkflowRun(_Input):
    """Assign by email; Process Street invites unknown users as internal guests."""
    operation: Literal["assign_workflow_run"] = "assign_workflow_run"
    workflow_run_id: Identifier
    email: str = Field(..., min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", description="Users outside the organization will be invited as guests.")


class UnassignWorkflowRun(_Input):
    operation: Literal["unassign_workflow_run"] = "unassign_workflow_run"
    workflow_run_id: Identifier
    email: str = Field(..., min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", description="Email of the assignee to remove.")


class ListWorkflowRunAssignees(_Page):
    operation: Literal["list_workflow_run_assignees"] = "list_workflow_run_assignees"
    workflow_run_id: Identifier


class ListTasks(_Page):
    operation: Literal["list_tasks"] = "list_tasks"
    workflow_run_id: Identifier


class GetTask(_Input):
    operation: Literal["get_task"] = "get_task"
    workflow_run_id: Identifier
    task_id: Identifier


class UpdateTask(GetTask):
    operation: Literal["update_task"] = "update_task"
    status: Literal["NotCompleted", "Completed"]
    due_date: Timestamp | None = Field(None, description="Replacement due date; omitting clears the existing due date.")


class AssignTask(GetTask):
    operation: Literal["assign_task"] = "assign_task"
    email: str = Field(..., min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class UnassignTask(AssignTask):
    operation: Literal["unassign_task"] = "unassign_task"


class ListFormFields(ListWorkflowTasks):
    operation: Literal["list_form_fields"] = "list_form_fields"


class ListFormFieldValues(ListTasks):
    operation: Literal["list_form_field_values"] = "list_form_field_values"


class FormFieldValue(_Input):
    id: Identifier
    value: str | None = None
    values: list[str] | None = Field(None, max_length=1000)
    timeHidden: StrictBool | None = None
    dataSetRowId: Identifier | None = None

    @model_validator(mode="after")
    def one_value(self):
        if sum(v is not None for v in (self.value, self.values, self.dataSetRowId)) != 1:
            raise ValueError("Provide exactly one of value, values or dataSetRowId")
        return self


class UpdateFormFieldValues(_Input):
    operation: Literal["update_form_field_values"] = "update_form_field_values"
    workflow_run_id: Identifier
    fields: list[FormFieldValue] = Field(..., min_length=1, max_length=100, description="Field IDs and documented value/values keys; omitted fields are unchanged.")


class ListComments(_Page):
    operation: Literal["list_comments"] = "list_comments"
    workflow_id: Identifier | None = None
    workflow_run_id: Identifier | None = None
    task_id: Identifier | None = None


class CreateComment(GetTask):
    operation: Literal["create_comment"] = "create_comment"
    text: str = Field(..., min_length=1)


class ListUsers(_Page):
    operation: Literal["list_users"] = "list_users"


ProcessStreetOperation = Annotated[Union[
    ListWorkflows, GetWorkflow, ListWorkflowTasks, ListWorkflowRuns,
    CreateWorkflowRun, GetWorkflowRun, UpdateWorkflowRun, DeleteWorkflowRun,
    AssignWorkflowRun, UnassignWorkflowRun, ListWorkflowRunAssignees,
    ListTasks, GetTask, UpdateTask, AssignTask, UnassignTask, ListFormFields,
    ListFormFieldValues, UpdateFormFieldValues, ListComments, CreateComment, ListUsers,
], Field(discriminator="operation")]


class ProcessStreetConfig(NodeConfig[ProcessStreetOperation, ProcessStreetAPIKey]):
    pass


def _check_credential_family(value):
    if isinstance(value, dict):
        credentials = value.get("credentials")
        if isinstance(credentials, dict) and credentials.get("credential_type", CREDENTIAL) != CREDENTIAL:
            raise ValueError("Attach a Process Street API key credential")


# Each action has exactly one operation in the published v1.1 contract.
ROUTES = {
    "list_workflows": ("GET", "/workflows", "workflows"),
    "get_workflow": ("GET", "/workflows/{workflow_id}", None),
    "list_workflow_tasks": ("GET", "/workflows/{workflow_id}/tasks", "tasks"),
    "list_workflow_runs": ("GET", "/workflow-runs/list", "data"),
    "create_workflow_run": ("POST", "/workflow-runs", None),
    "get_workflow_run": ("GET", "/workflow-runs/{workflow_run_id}", None),
    "update_workflow_run": ("PUT", "/workflow-runs/{workflow_run_id}", None),
    "delete_workflow_run": ("DELETE", "/workflow-runs/{workflow_run_id}", None),
    "assign_workflow_run": ("POST", "/workflow-runs/{workflow_run_id}/assignees/{email}", None),
    "unassign_workflow_run": ("DELETE", "/workflow-runs/{workflow_run_id}/assignees/{email}", None),
    "list_workflow_run_assignees": ("GET", "/workflow-runs/{workflow_run_id}/assignees", "assignees"),
    "list_tasks": ("GET", "/workflow-runs/{workflow_run_id}/tasks", "tasks"),
    "get_task": ("GET", "/workflow-runs/{workflow_run_id}/tasks/{task_id}", None),
    "update_task": ("PUT", "/workflow-runs/{workflow_run_id}/tasks/{task_id}", None),
    "assign_task": ("PUT", "/workflow-runs/{workflow_run_id}/tasks/{task_id}/assignees/{email}", None),
    "unassign_task": ("DELETE", "/workflow-runs/{workflow_run_id}/tasks/{task_id}/assignees/{email}", None),
    "list_form_fields": ("GET", "/workflows/{workflow_id}/form-fields", "fields"),
    "list_form_field_values": ("GET", "/workflow-runs/{workflow_run_id}/form-fields", "fields"),
    "update_form_field_values": ("POST", "/workflow-runs/{workflow_run_id}/form-fields", None),
    "list_comments": ("GET", "/comments", "data"),
    "create_comment": ("POST", "/comments", None),
    "list_users": ("GET", "/users", "users"),
}
ACKNOWLEDGEMENTS = {
    "update_workflow_run": 204, "delete_workflow_run": 200,
    "assign_workflow_run": 204, "unassign_workflow_run": 204,
    "update_task": 204, "assign_task": 204, "unassign_task": 204,
}
SUCCESS_STATUS = {**ACKNOWLEDGEMENTS, "create_workflow_run": 201, "create_comment": 201}
WIRE_NAMES = {"workflow_id": "workflowId", "workflow_run_id": "workflowRunId", "task_id": "taskId", "due_date": "dueDate", "page_cursor": "_"}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


def _next_cursor(payload, path, params):
    links = payload.get("links", [])
    if not isinstance(links, list):
        raise ValueError("Process Street returned invalid pagination")
    next_links = [link for link in links if isinstance(link, dict) and link.get("name") == "next"]
    if not next_links:
        return None
    if len(next_links) != 1 or not isinstance(next_links[0].get("href"), str):
        raise ValueError("Process Street returned invalid pagination")
    url = urlsplit(next_links[0]["href"])
    query = parse_qs(url.query, keep_blank_values=True)
    expected = {k: [str(v)] for k, v in params.items() if k != "_"}
    if (url.scheme != "https" or url.hostname not in {"public-api.process.st", "api.process.st"}
            or url.port not in {None, 443} or url.username or url.password or url.fragment
            or url.path != "/api/v1.1" + path or {k: v for k, v in query.items() if k != "_"} != expected
            or len(query.get("_", [])) != 1 or not query["_"][0]
            or query["_"][0] == params.get("_") or len(query["_"][0]) > 8192):
        raise ValueError("Process Street returned an invalid continuation")
    return query["_"][0]


class ProcessStreetNode(WorkflowNode):
    integration_type = "automation-process-street"
    connection_evidence = ConnectionEvidence(noun="workflows", operation="list_workflows")

    @classmethod
    def get_config_model(cls):
        return ProcessStreetConfig

    @classmethod
    def parse_config(cls, config_data):
        _check_credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _check_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Process Street API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, template, collection = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path_fields = [name for name in values if "{" + name + "}" in template]
        path = template.format(**{name: quote(str(values.pop(name)), safe="") for name in path_fields})
        values = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        params = values if method == "GET" else {}
        body = values if method in {"POST", "PUT"} and values else None
        write = method != "GET"
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers={"X-API-Key": key, "Accept": "application/json"}, params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            return {"status": "unknown" if write else "error", "success": False, "message": "Process Street could not be reached; inspect the resource before retrying a write.", "write_outcome": "unverified" if write else None}
        if response.status_code != SUCCESS_STATUS.get(op.operation, 200):
            try:
                error = response.json()
                message = error.get("error") if isinstance(error, dict) else None
            except ValueError:
                message = None
            return _redact({"status": "unknown" if write and response.status_code >= 500 else "error", "success": False,
                "http_status": response.status_code, "message": message if isinstance(message, str) else "Process Street request failed",
                "write_outcome": "unverified" if write else None}, key)
        result = {"status": "success", "success": True, "http_status": response.status_code, "action": op.operation}
        if op.operation in ACKNOWLEDGEMENTS:
            if not write:
                raise ValueError("Process Street returned an unexpected empty read")
            result.update(acknowledged=True, readback_verified=False)
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Process Street returned invalid JSON; inspect a write before retrying") from None
            if not isinstance(payload, dict) or "error" in payload:
                raise ValueError("Process Street returned an unexpected response; inspect a write before retrying")
            result["data"] = payload
            if collection:
                rows = payload.get(collection)
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("Process Street returned an invalid collection")
                cursor = _next_cursor(payload, path, params)
                result.update(items=rows, next_cursor=cursor, has_more=cursor is not None)
            if write:
                result.update(acknowledged=True, readback_verified=False)
        return _redact(result, key)
