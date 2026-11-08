"""AgencyZoom CRM operations against the published v1 REST API.

Each action makes one documented request with a supplied bearer token. Search
results retain the provider's page metadata; writes report its acknowledgement.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.agencyzoom.com"
DOCS_URL = "https://app.agencyzoom.com/openapi/agencyzoom.yaml"


class AgencyZoomBearerToken(BaseModel):
    model_config = ConfigDict(
        title="Agencyzoom Bearer Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS_URL,
            "x-credential-instructions": "Paste an existing JWT access token returned by AgencyZoom's POST /v1/api/auth/login. Omit the Bearer prefix. Requests use the permissions of that user; an agency owner is needed for full agency access. Replace expired tokens here. NoClick does not sign in or refresh the token.",
        },
    )
    credential_type: Literal["agencyzoom_bearer_token"] = Field(
        "agencyzoom_bearer_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(
        ..., title="Access Token", min_length=1, max_length=8192, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access Token")
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or not value.isascii():
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(0, ge=0, description="Zero-based page number. Each execution returns one page.")
    pageSize: int = Field(20, ge=1, le=100, title="Page Size")
    order: Literal["asc", "desc"] | None = None
    location: str | None = None


class SearchLeads(_Page):
    """Search leads by contact, assignment and pipeline."""
    operation: Literal["search_leads"] = "search_leads"
    customerName: str | None = Field(None, title="Customer Name")
    customerEmail: str | None = Field(None, title="Customer Email")
    customerPhone: str | None = Field(None, title="Customer Phone")
    assignedTo: int | None = Field(None, ge=1, title="Assigned Employee ID")
    leadSourceId: int | None = Field(None, ge=1, title="Lead Source ID")
    workflowId: int | None = Field(None, ge=1, title="Pipeline ID")
    workflowStageId: str | None = Field(None, title="Stage IDs", description="Separate multiple stage IDs with /.")
    status: Literal[0, 1, 2, 3, 4, 5] | None = None
    sort: Literal["firstname", "lastname", "lastEnterStageDate", "lastActivityDate"] | None = None
    startDate: str | None = Field(None, title="Created From", description="YYYY-MM-DD")
    endDate: str | None = Field(None, title="Created Through", description="YYYY-MM-DD")


class CreateLead(_Input):
    """Create a personal lead in an explicit pipeline and stage."""
    operation: Literal["create_lead"] = "create_lead"
    firstname: str = Field(..., min_length=1, title="First Name")
    email: str = Field(..., min_length=1, title="Email")
    country: str = Field(..., min_length=1, title="Country")
    leadSourceId: int = Field(..., ge=1, title="Lead Source ID")
    assignTo: int = Field(..., ge=1, title="Assigned Employee ID")
    pipelineId: int = Field(..., ge=1, title="Pipeline ID")
    stageId: int = Field(..., ge=1, title="Stage ID")
    lastname: str | None = Field(None, title="Last Name")
    phone: str | None = None
    notes: str | None = None
    streetAddress: str | None = Field(None, title="Street Address")
    city: str | None = None
    state: str | None = None
    zip: str | None = Field(None, title="Postal Code")
    tagNames: str | None = Field(None, title="Tag Names", description="Separate tags with semicolons.")


class _Lead(_Input):
    lead_id: int = Field(..., ge=1, title="Lead ID")


class GetLead(_Lead):
    """Get lead details."""
    operation: Literal["get_lead"] = "get_lead"


class ListLeadNotes(_Lead):
    """List notes on a lead."""
    operation: Literal["list_lead_notes"] = "list_lead_notes"


class AddLeadNote(_Lead):
    """Add a note to a lead."""
    operation: Literal["add_lead_note"] = "add_lead_note"
    note: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "textarea"})


class ListLeadTasks(_Lead):
    """List tasks for a lead."""
    operation: Literal["list_lead_tasks"] = "list_lead_tasks"


class SearchCustomers(_Page):
    """Search customer records, returning one page."""
    operation: Literal["search_customers"] = "search_customers"
    firstname: str | None = Field(None, title="First Name")
    lastname: str | None = Field(None, title="Last Name")
    email: str | None = None
    phone: str | None = None
    policyNumber: str | None = Field(None, title="Policy Number")
    agentId: int | None = Field(None, ge=1, title="Agent ID")
    status: Literal[-1, 0, 1] | None = Field(None, description="-1 all, 0 inactive, 1 active")


class CreateCustomer(_Input):
    """Create a customer assigned to an explicit agent."""
    operation: Literal["create_customer"] = "create_customer"
    firstname: str = Field(..., min_length=1, title="First Name")
    email: str = Field(..., min_length=1)
    agentId: int = Field(..., ge=1, title="Agent ID")
    lastname: str | None = Field(None, title="Last Name")
    phone: str | None = None
    streetAddress: str | None = Field(None, title="Street Address")
    city: str | None = None
    state: str | None = None
    country: str | None = None
    zip: str | None = Field(None, title="Postal Code")
    csrId: int | None = Field(None, ge=1, title="CSR ID")
    tagNames: str | None = Field(None, title="Tag Names", description="Separate tags with semicolons.")


class _Customer(_Input):
    customer_id: int = Field(..., ge=1, title="Customer ID")


class GetCustomer(_Customer):
    """Get customer details."""
    operation: Literal["get_customer"] = "get_customer"


class AddCustomerNote(_Customer):
    """Add a note to a customer."""
    operation: Literal["add_customer_note"] = "add_customer_note"
    note: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "textarea"})


class ListCustomerTasks(_Customer):
    """List tasks for a customer."""
    operation: Literal["list_customer_tasks"] = "list_customer_tasks"


class ListCustomerPolicies(_Customer):
    """List written policies for a customer."""
    operation: Literal["list_customer_policies"] = "list_customer_policies"


class ListCustomerAMSPolicies(_Customer):
    """List AMS policies for a customer."""
    operation: Literal["list_customer_ams_policies"] = "list_customer_ams_policies"


class SearchTasks(_Page):
    """Search tasks by assignee, status, period and dates."""
    operation: Literal["search_tasks"] = "search_tasks"
    pageSize: int = Field(20, ge=1, le=200, title="Page Size")
    assigneeId: int | None = Field(None, ge=1, title="Assignee ID")
    status: Literal[0, 1] | None = Field(None, description="0 open, 1 completed")
    type: Literal["sales", "onboarding"] | None = Field(None, title="Task Category")
    period: Literal["past-due-rotting", "past-due", "remainder-week", "next-week", "today"] | None = None
    startDate: str | None = Field(None, title="Created From", description="YYYY-MM-DD")
    endDate: str | None = Field(None, title="Created Through", description="YYYY-MM-DD")


class _TaskFields(_Input):
    title: str = Field(..., min_length=1)
    dueDatetime: str = Field(..., min_length=1, title="Due Date and Time", description="YYYY-MM-DD HH:mm:ss in the agency's timezone.")
    assigneeId: int = Field(..., ge=1, title="Assignee ID")
    type: Literal["todo", "email", "call", "meeting"] = Field("todo", title="Task Type")
    comments: str | None = Field(None, json_schema_extra={"ui:widget": "textarea"})
    leadId: int | None = Field(None, ge=1, title="Lead ID")
    customerId: int | None = Field(None, ge=1, title="Customer ID")
    duration: int | None = Field(None, ge=1, description="Duration in minutes")
    timeSpecific: bool | None = Field(None, title="Time Specific")
    invitees: list[str] | None = Field(None, title="Invitee Emails")


class CreateTask(_TaskFields):
    """Create a task; meeting invitees may receive invitations."""
    operation: Literal["create_task"] = "create_task"


class _Task(_Input):
    task_id: int = Field(..., ge=1, title="Task ID")


class GetTask(_Task):
    """Get task details."""
    operation: Literal["get_task"] = "get_task"


class UpdateTask(_TaskFields, _Task):
    """Update task details; supply the intended title, due time and assignee."""
    operation: Literal["update_task"] = "update_task"
    status: Literal[0, 1] | None = Field(None, description="0 open, 1 completed")


class CompleteTask(_Task):
    """Mark a task completed."""
    operation: Literal["complete_task"] = "complete_task"


class ReopenTask(_Task):
    """Reopen a completed task."""
    operation: Literal["reopen_task"] = "reopen_task"
    comments: str | None = Field(None, json_schema_extra={"ui:widget": "textarea"})


class DeleteTask(_Task):
    """Permanently delete a task."""
    operation: Literal["delete_task"] = "delete_task"


class ListEmployees(_Input):
    """List the agency's employees to prove the connected account."""
    operation: Literal["list_employees"] = "list_employees"


class ListPipelines(_Input):
    """List pipelines and their stages."""
    operation: Literal["list_pipelines"] = "list_pipelines"
    type: Literal["lead", "service"] | None = Field(None, title="Pipeline Type")


class ListLeadSources(_Input):
    """List the agency's lead sources."""
    operation: Literal["list_lead_sources"] = "list_lead_sources"


class ListTags(_Input):
    """List the agency's tags."""
    operation: Literal["list_tags"] = "list_tags"


AgencyZoomOperation = Annotated[Union[
    SearchLeads, CreateLead, GetLead, ListLeadNotes, AddLeadNote, ListLeadTasks,
    SearchCustomers, CreateCustomer, GetCustomer, AddCustomerNote,
    ListCustomerTasks, ListCustomerPolicies, ListCustomerAMSPolicies,
    SearchTasks, CreateTask, GetTask, UpdateTask, CompleteTask, ReopenTask,
    DeleteTask, ListEmployees, ListPipelines, ListLeadSources, ListTags,
], Field(discriminator="operation")]


class AgencyZoomConfig(NodeConfig[AgencyZoomOperation, AgencyZoomBearerToken]):
    pass


# One fixed method/path per action. Resource IDs are positive integers from the
# operation model; neither a user-supplied URL nor a continuation URL is followed.
ROUTES = {
    "search_leads": ("POST", "/v1/api/leads/list"),
    "create_lead": ("POST", "/v1/api/leads/create"),
    "get_lead": ("GET", "/v1/api/leads/{lead_id}"),
    "list_lead_notes": ("GET", "/v1/api/leads/{lead_id}/notes"),
    "add_lead_note": ("POST", "/v1/api/leads/{lead_id}/notes"),
    "list_lead_tasks": ("GET", "/v1/api/leads/{lead_id}/tasks"),
    "search_customers": ("POST", "/v1/api/customers"),
    "create_customer": ("POST", "/v1/api/customers/create"),
    "get_customer": ("GET", "/v1/api/customers/{customer_id}"),
    "add_customer_note": ("POST", "/v1/api/customers/{customer_id}/notes"),
    "list_customer_tasks": ("GET", "/v1/api/customers/{customer_id}/tasks"),
    "list_customer_policies": ("GET", "/v1/api/customers/{customer_id}/policies"),
    "list_customer_ams_policies": ("GET", "/v1/api/customers/{customer_id}/ams-policies"),
    "search_tasks": ("POST", "/v1/api/tasks/list"),
    "create_task": ("POST", "/v1/api/tasks"),
    "get_task": ("GET", "/v1/api/tasks/{task_id}"),
    "update_task": ("PUT", "/v1/api/tasks/{task_id}"),
    "complete_task": ("PUT", "/v1/api/tasks/{task_id}/completed"),
    "reopen_task": ("PUT", "/v1/api/tasks/{task_id}/reopened"),
    "delete_task": ("DELETE", "/v1/api/tasks/{task_id}"),
    "list_employees": ("GET", "/v1/api/employees"),
    "list_pipelines": ("GET", "/v1/api/pipelines-and-stages"),
    "list_lead_sources": ("GET", "/v1/api/lead-sources"),
    "list_tags": ("GET", "/v1/api/tags"),
}


class AgencyZoomNode(WorkflowNode):
    integration_type = "automation-agencyzoom"
    connection_evidence = ConnectionEvidence(
        operation="list_employees", noun="employees",
        label_keys=("email", "firstname", "lastname", "id"))

    @classmethod
    def get_config_model(cls):
        return AgencyZoomConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an AgencyZoom bearer token")
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template.format(**values)
        payload = {k: v for k, v in values.items()
                   if k not in {"operation", "lead_id", "customer_id", "task_id"}}
        kwargs = {"params": payload} if method == "GET" else {"json": payload} if payload or config.operation == "reopen_task" else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers={
                    "Authorization": "Bearer " + credential.access_token,
                    "Accept": "application/json",
                }, **kwargs)
            if len(response.content) > 10_000_000:
                raise ValueError("AgencyZoom response exceeds the size limit")
            body = response.json()
            if not isinstance(body, (dict, list)):
                raise ValueError("AgencyZoom returned an unexpected JSON response")
            failed = response.is_error or response.is_redirect or (
                isinstance(body, dict) and (body.get("error") or body.get("fieldErrors") or body.get("result") is False))
            if failed:
                message = (body.get("error") or body.get("message") or body.get("fieldErrors")) if isinstance(body, dict) else None
                return {"status": "error", "http_status": response.status_code,
                        "error": str(message or "AgencyZoom rejected the request").replace(credential.access_token, "[redacted]")}
            return {"status": "success", "operation": config.operation,
                    "data": body, "http_status": response.status_code}
        except httpx.HTTPError:
            return {"status": "error", "error": "AgencyZoom request did not complete; check the account before retrying a write"}
        except ValueError:
            return {"status": "error", "error": "AgencyZoom returned an invalid JSON response; check the account before retrying a write"}
