"""Rocketlane API v1: one documented request per operation, using a pasted API key.

Contract: https://developer.rocketlane.com/v1.0/reference/get-all-projects
Authentication: https://developer.rocketlane.com/v1.0/docs/authentication
"""
from datetime import date
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.rocketlane.com/api/1.0"
NODE_TYPE = "automation-rocketlane"
FAMILY = "rocketlane_api_key"
Identifier = Annotated[int, Field(ge=1, le=9223372036854775807)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]


def _picker(field, parent=None):
    options = {"field_name": field, "allow_custom": True, "placeholder": "Choose a resource", "custom_placeholder": "Enter a Rocketlane ID"}
    if parent:
        options["depends_on"] = parent
    return {"x-dynamic-options": options}


class RocketlaneAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Rocketlane API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.rocketlane.com/v1.0/docs/authentication",
            "x-credential-instructions": "In Rocketlane, open Settings → API to create an API key, then paste it here. Your account must have access to the projects and other records you want to automate. NoClick sends the key only to api.rocketlane.com. The connection check lists projects; it does not verify write permissions.",
        })
    credential_type: Literal["rocketlane_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def editor_metadata(cls, value):
        if isinstance(value, dict):
            return {key: item for key, item in value.items()
                if key != "credentialIds" and not key.endswith("__label")}
        return value

    @model_validator(mode="after")
    def update_fields(self):
        if getattr(self, "operation", "").startswith("update_"):
            resource_id = self.operation.removeprefix("update_") + "_id"
            if not any(key not in {"operation", resource_id} for key in self.model_dump(exclude_none=True)):
                raise ValueError("Supply at least one field to update")
        return self


class _List(_Input):
    page_size: int = Field(100, ge=1, le=100, description="One page of results, up to 100 records.")
    page_token: Optional[str] = Field(None, min_length=1, max_length=4096, description="The previous page's next_page_token; Rocketlane tokens expire after 15 minutes. Keep the same filters.")


class _Dates(_Input):
    start_date: Optional[date] = None
    due_date: Optional[date] = None

    @model_validator(mode="after")
    def dates(self):
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("Due date must be on or after start date")
        return self


class _ProjectFields(_Dates):
    project_name: Optional[Text] = None
    status_value: Optional[Identifier] = Field(None, description="Numeric project status value configured in Rocketlane.")
    visibility: Optional[Literal["EVERYONE", "MEMBERS"]] = None
    external_reference_id: Optional[Text] = None


class _TaskFields(_Dates):
    task_name: Optional[Text] = None
    task_description: Optional[Text] = Field(None, description="Task description in HTML format.")
    progress: Optional[int] = Field(None, ge=0, le=100)
    status_value: Optional[Identifier] = Field(None, description="Numeric task status value configured in Rocketlane.")
    effort_in_minutes: Optional[int] = Field(None, ge=0, le=2147483647)
    at_risk: Optional[StrictBool] = None
    private: Optional[StrictBool] = None
    external_reference_id: Optional[Text] = None


class _CompanyFields(_Input):
    company_name: Optional[Text] = None
    description: Optional[Text] = None
    company_url: Optional[Text] = None
    visibility: Optional[Literal["EVERYONE", "MEMBERS"]] = None


class _PhaseFields(_Dates):
    phase_name: Optional[Text] = None
    phase_description: Optional[Text] = None
    status_value: Optional[Identifier] = Field(None, description="Numeric phase status value configured in Rocketlane.")
    private: Optional[StrictBool] = None


class ListProjects(_List):
    """List one page of projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    name_contains: Optional[Text] = None


class GetProject(_Input):
    """Read one project by ID."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: Identifier = Field(..., json_schema_extra=_picker("project_id"))


class CreateProject(_ProjectFields):
    """Create a project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    project_name: Text
    owner_id: Identifier = Field(..., json_schema_extra=_picker("user_id"))
    customer_name: Text = Field(..., description="Exact, case-sensitive name of an existing customer company.")


class UpdateProject(_ProjectFields):
    """Update supplied fields on a project."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    project_id: Identifier = Field(..., json_schema_extra=_picker("project_id"))


class ListTasks(_List):
    """List one page of tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    project_id: Optional[Identifier] = Field(None, json_schema_extra=_picker("project_id"))
    name_contains: Optional[Text] = None


class GetTask(_Input):
    """Read one task by ID."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: Identifier = Field(..., json_schema_extra=_picker("task_id"))


class CreateTask(_TaskFields):
    """Create a task."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    task_name: Text
    project_id: Identifier = Field(..., json_schema_extra=_picker("project_id"))


class UpdateTask(_TaskFields):
    """Update supplied fields on a task."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    task_id: Identifier = Field(..., json_schema_extra=_picker("task_id"))


class ListCompanies(_List):
    """List one page of companies."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})
    name_contains: Optional[Text] = None


class GetCompany(_Input):
    """Read one company by ID."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: Identifier = Field(..., json_schema_extra=_picker("company_id"))


class CreateCompany(_CompanyFields):
    """Create a company."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    company_name: Text
    account_owner_id: Identifier = Field(..., json_schema_extra=_picker("user_id"))


class UpdateCompany(_CompanyFields):
    """Update supplied fields on a company."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: Identifier = Field(..., json_schema_extra=_picker("company_id"))


class ListPhases(_List):
    """List one page of phases."""
    operation: Literal["list_phases"] = Field("list_phases", json_schema_extra={"ui:hidden": True})
    project_id: Identifier = Field(..., json_schema_extra=_picker("project_id"))


class GetPhase(_Input):
    """Read one phase by ID."""
    operation: Literal["get_phase"] = Field("get_phase", json_schema_extra={"ui:hidden": True})
    phase_id: Identifier = Field(..., description="Rocketlane phase ID.")


class CreatePhase(_PhaseFields):
    """Create a phase."""
    operation: Literal["create_phase"] = Field("create_phase", json_schema_extra={"ui:hidden": True})
    phase_name: Text
    project_id: Identifier = Field(..., json_schema_extra=_picker("project_id"))
    start_date: date
    due_date: date


class UpdatePhase(_PhaseFields):
    """Update supplied fields on a phase."""
    operation: Literal["update_phase"] = Field("update_phase", json_schema_extra={"ui:hidden": True})
    phase_id: Identifier = Field(..., description="Rocketlane phase ID.")


class ListUsers(_List):
    """List one page of users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class GetUser(_Input):
    """Read a user by ID."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: Identifier = Field(..., json_schema_extra=_picker("user_id"))


class ListTimeEntries(_List):
    """List one page of time entries, optionally for a project."""
    operation: Literal["list_time_entries"] = Field("list_time_entries", json_schema_extra={"ui:hidden": True})
    project_id: Optional[Identifier] = Field(None, json_schema_extra=_picker("project_id"))


class GetTimeEntry(_Input):
    """Read a time entry by ID."""
    operation: Literal["get_time_entry"] = Field("get_time_entry", json_schema_extra={"ui:hidden": True})
    time_entry_id: Identifier


class CreateTimeEntry(_Input):
    """Log project time."""
    operation: Literal["create_time_entry"] = Field("create_time_entry", json_schema_extra={"ui:hidden": True})
    date: date
    minutes: int = Field(..., ge=1, le=1440)
    project_id: Identifier = Field(..., json_schema_extra=_picker("project_id"), description="Log time against this project.")
    billable: Optional[StrictBool] = None
    notes: Optional[Text] = None


class DeleteTimeEntry(_Input):
    """Delete a time entry by ID."""
    operation: Literal["delete_time_entry"] = Field("delete_time_entry", json_schema_extra={"ui:hidden": True})
    time_entry_id: Identifier


RocketlaneConfig = Annotated[Union[ListProjects, GetProject, CreateProject, UpdateProject, ListTasks, GetTask, CreateTask, UpdateTask, ListCompanies, GetCompany, CreateCompany, UpdateCompany, ListPhases, GetPhase, CreatePhase, UpdatePhase, ListUsers, GetUser, ListTimeEntries, GetTimeEntry, CreateTimeEntry, DeleteTimeEntry], Field(discriminator="operation")]


class RocketlaneFullConfig(NodeConfig[RocketlaneConfig, RocketlaneAPIKeyCredential]):
    pass


# Explicit operation mapping: each UI operation is exactly one provider endpoint.
OPERATIONS = {
    "list_projects": ("GET", "projects", None),
    "get_project": ("GET", "projects", "project_id"),
    "create_project": ("POST", "projects", None),
    "update_project": ("PUT", "projects", "project_id"),
    "list_tasks": ("GET", "tasks", None),
    "get_task": ("GET", "tasks", "task_id"),
    "create_task": ("POST", "tasks", None),
    "update_task": ("PUT", "tasks", "task_id"),
    "list_companies": ("GET", "companies", None),
    "get_company": ("GET", "companies", "company_id"),
    "create_company": ("POST", "companies", None),
    "update_company": ("PUT", "companies", "company_id"),
    "list_phases": ("GET", "phases", None),
    "get_phase": ("GET", "phases", "phase_id"),
    "create_phase": ("POST", "phases", None),
    "update_phase": ("PUT", "phases", "phase_id"),
    "list_users": ('GET', 'users', None),
    "get_user": ('GET', 'users', 'user_id'),
    "list_time_entries": ('GET', 'time-entries', None),
    "get_time_entry": ('GET', 'time-entries', 'time_entry_id'),
    "create_time_entry": ('POST', 'time-entries', None),
    "delete_time_entry": ('DELETE', 'time-entries', 'time_entry_id'),
}
WIRE_FIELDS = {
    "project_name": "projectName", "task_name": "taskName", "company_name": "companyName", "phase_name": "phaseName",
    "start_date": "startDate", "due_date": "dueDate", "task_description": "taskDescription", "phase_description": "phaseDescription",
    "effort_in_minutes": "effortInMinutes", "at_risk": "atRisk", "external_reference_id": "externalReferenceId", "company_url": "companyUrl",
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(secret, "[redacted]"): _redact(item, secret) for key, item in value.items()}
    return value


class RocketlaneNode(WorkflowNode):
    integration_type = "automation-rocketlane"
    connection_evidence = ConnectionEvidence(field="project_id", operation="list_projects", noun="projects")

    @classmethod
    def get_config_model(cls):
        return RocketlaneFullConfig

    @staticmethod
    def _request_parts(op):
        method, resource, id_field = OPERATIONS[op.operation]
        path = "/" + resource + ("/" + str(getattr(op, id_field)) if id_field else "")
        values = op.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        if id_field:
            values.pop(id_field)
        params, body = {}, None
        if op.operation.startswith("list_"):
            params["pageSize"] = values.pop("page_size")
            if "page_token" in values:
                params["pageToken"] = values.pop("page_token")
            if "project_id" in values:
                params["projectId" if resource == "phases" else "projectId.eq"] = values.pop("project_id")
            if "name_contains" in values:
                params[{"projects": "projectName.cn", "tasks": "taskName.cn", "companies": "companyName.cn"}[resource]] = values.pop("name_contains")
        elif method in {"POST", "PUT"}:
            body = {}
            for key, value in values.items():
                if key == "project_id":
                    body["project"] = {"projectId": value}
                elif key == "owner_id":
                    body["owner"] = {"userId": value}
                elif key == "customer_name":
                    body["customer"] = {"companyName": value}
                elif key == "account_owner_id":
                    body["accountOwner"] = {"userId": value}
                elif key == "status_value":
                    body["status"] = {"value": value}
                else:
                    body[WIRE_FIELDS.get(key, key)] = value
            if not body:
                raise ValueError("Supply at least one field to update")
        return method, path, params, body

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Rocketlane API key")
        op, credential = self.config.config, self.config.credentials
        method, path, params, body = self._request_parts(op)
        writing = method != "GET"
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"api-key": credential.api_key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                message = "Rocketlane rejected the request"
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        message = error.get("message") or error.get("error") or message
                except ValueError:
                    pass
                return _redact({"status": "error", "http_status": response.status_code, "error": message,
                    "write_outcome": "unverified" if writing and response.status_code >= 500 else None}, credential.api_key)
            if method == "DELETE":
                return {"status": "success", "operation": op.operation, "http_status": response.status_code,
                    "deleted_id": op.time_entry_id, "deletion_acknowledged": True}
            if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected bounded JSON from Rocketlane")
            payload = response.json()
            if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
                raise ValueError("Unexpected Rocketlane response")
            output = {"status": "success", "operation": op.operation, "http_status": response.status_code}
            if op.operation.startswith("list_"):
                rows, pagination = payload.get("data"), payload.get("pagination")
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or not isinstance(pagination, dict) or type(pagination.get("hasMore")) is not bool:
                    raise ValueError("Incomplete Rocketlane page")
                token = pagination.get("nextPageToken") if pagination["hasMore"] else None
                if pagination["hasMore"] and (not isinstance(token, str) or not token or token == op.page_token):
                    raise ValueError("Rocketlane did not provide an advancing page token")
                # Never follow the response's nextPage URL; send only its token to the fixed origin.
                output.update(data=rows, pagination=pagination, has_more=pagination["hasMore"], next_page_token=token)
            else:
                output["data"] = payload
            if writing:
                output["write_acknowledged"] = True
            return _redact(output, credential.api_key)
        except (httpx.HTTPError, ValueError, SSRFError):
            return {"status": "error", "operation": op.operation,
                "error": "Rocketlane request could not be verified; inspect the record before retrying" if writing else "Rocketlane read could not be verified",
                "write_outcome": "unverified" if writing else None}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, *, page_token=None, search=None):
        choices = {"project_id": ("list_projects", "projectId", "projectName"),
            "task_id": ("list_tasks", "taskId", "taskName"),
            "company_id": ("list_companies", "companyId", "companyName"),
            "phase_id": ("list_phases", "phaseId", "phaseName"),
            "user_id": ("list_users", "userId", "firstName")}
        if field_name not in choices:
            return []
        operation, id_key, label_key = choices[field_name]
        config = {"operation": operation, "page_token": page_token}
        if field_name == "phase_id":
            # Phase lists require a project. A custom phase ID remains available without one.
            if not context or not context.get("project_id"):
                return []
            config["project_id"] = context["project_id"]
        if search and field_name in {"project_id", "task_id", "company_id"}:
            config["name_contains"] = search
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="rocketlane-options", node_type=NODE_TYPE,
            node_data={"config": config, "credentials": credential_data})
        result = await node.execute({})
        if result.get("status") != "success":
            raise ValueError(result.get("error", "Rocketlane options could not be loaded"))
        return {"options": [{"value": str(row[id_key]), "label": row.get(label_key) or str(row[id_key])}
            for row in result["data"] if row.get(id_key) is not None], "next_page_token": result["next_page_token"]}
