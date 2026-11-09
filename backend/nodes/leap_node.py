"""Leap CRM v3 operations pinned to docs.api.jobprogress.com/api/*.json.

Every operation sends one provider request. Lists return one page with the
provider pagination metadata; writes are never automatically retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.jobprogress.com/api/v3"


class LeapTokenCredential(BaseModel):
    model_config = ConfigDict(title="Leap API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.api.jobprogress.com/",
            "x-credential-instructions": "Paste your existing Leap CRM API bearer token. Ask your Leap administrator for API access if you do not have a token. NoClick checks the connection by reading your company users.",
        })
    credential_type: Literal["leap_api_token"] = Field("leap_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class LeapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(LeapInput):
    page: int = Field(1, ge=1, description="Page number; each run returns one page.")
    limit: int = Field(20, ge=1, le=100)


class Phone(BaseModel):
    label: Literal["home", "cell", "phone", "office", "fax", "other"] = "cell"
    number: str = Field(..., min_length=1)


class CustomerWrite(LeapInput):
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    phones: list[Phone] = Field(..., min_length=1)
    email: str | None = None
    note: str | None = None
    company_name: str | None = None
    is_commercial: Literal[0, 1] = 0


class JobWrite(LeapInput):
    customer_id: int = Field(..., gt=0)
    description: str = Field(..., min_length=1)
    trades: list[int] = Field(..., min_length=1, description="Company trade IDs from List Trades.")
    name: str | None = None
    alt_id: str | None = None
    lead_number: str | None = None
    division_id: int | None = Field(None, gt=0)
    same_as_customer_address: Literal[0, 1] = 1

    @field_validator("trades")
    @classmethod
    def positive_trades(cls, values):
        if any(value <= 0 for value in values):
            raise ValueError("Use positive trade IDs")
        return values


class ListCustomers(Page):
    """List customers in your Leap account."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    keyword: str | None = None


class GetCustomer(LeapInput):
    """Get a customer by ID."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., gt=0)


class CreateCustomer(CustomerWrite):
    """Create a customer with phone details."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})


class UpdateCustomer(CustomerWrite):
    """Update customer details; supply the required name and phone fields."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., gt=0)


class ListJobs(Page):
    """List or search jobs."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})
    keyword: str | None = None
    customer_id: int | None = Field(None, gt=0)


class GetJob(LeapInput):
    """Get a job by ID."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)


class CreateJob(JobWrite):
    """Create a job for an existing customer."""
    operation: Literal["create_job"] = Field("create_job", json_schema_extra={"ui:hidden": True})


class UpdateJob(JobWrite):
    """Update a job with its required customer, description and trades."""
    operation: Literal["update_job"] = Field("update_job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)


class GetJobFinancialSummary(LeapInput):
    """Read the financial summary for a job."""
    operation: Literal["get_job_financial_summary"] = Field("get_job_financial_summary", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)


class GetJobWorkflowHistory(LeapInput):
    """Read workflow stage history for a job."""
    operation: Literal["get_job_workflow_history"] = Field("get_job_workflow_history", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)


class UpdateJobStage(LeapInput):
    """Move a job to a workflow stage."""
    operation: Literal["update_job_stage"] = Field("update_job_stage", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)
    stage: int = Field(..., gt=0, description="Stage code from List Workflow Stages.")


class ListJobNotes(LeapInput):
    """List notes for a job."""
    operation: Literal["list_job_notes"] = Field("list_job_notes", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)


class CreateJobNote(LeapInput):
    """Add a note to a job."""
    operation: Literal["create_job_note"] = Field("create_job_note", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)
    note: str = Field(..., min_length=1)


class UpdateJobNote(LeapInput):
    """Update the text of a job note."""
    operation: Literal["update_job_note"] = Field("update_job_note", json_schema_extra={"ui:hidden": True})
    note_id: int = Field(..., gt=0)
    note: str = Field(..., min_length=1)


class ListContacts(Page):
    """List company contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class ListUsers(Page):
    """List company users to prove account access."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class ListTrades(Page):
    """List available company trades for job creation."""
    operation: Literal["list_trades"] = Field("list_trades", json_schema_extra={"ui:hidden": True})


class ListWorkflowStages(Page):
    """List configured workflow stages."""
    operation: Literal["list_workflow_stages"] = Field("list_workflow_stages", json_schema_extra={"ui:hidden": True})


class CreateTask(LeapInput):
    """Create a task assigned to company users."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1)
    users: list[int] = Field(..., min_length=1)
    origin: str = Field(..., min_length=1, max_length=30)
    notes: str | None = None
    due_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    job_id: int | None = Field(None, gt=0)


LeapConfig = Annotated[Union[
    ListCustomers,
    GetCustomer,
    CreateCustomer,
    UpdateCustomer,
    ListJobs,
    GetJob,
    CreateJob,
    UpdateJob,
    GetJobFinancialSummary,
    GetJobWorkflowHistory,
    UpdateJobStage,
    ListJobNotes,
    CreateJobNote,
    UpdateJobNote,
    ListContacts,
    ListUsers,
    ListTrades,
    ListWorkflowStages,
    CreateTask
], Field(discriminator="operation")]


class LeapNodeConfig(NodeConfig[LeapConfig, LeapTokenCredential]):
    pass


# Method, contract path, path parameter mapping, encoding. No arbitrary routes.
ROUTES = {
    "list_customers": ("GET", "/customers", {}, None),
    "get_customer": ("GET", "/customers/{customerId}", {"customer_id": "customerId"}, None),
    "create_customer": ("POST", "/customers", {}, "form"),
    "update_customer": ("PUT", "/customers/{customerId}", {"customer_id": "customerId"}, "form"),
    "list_jobs": ("GET", "/jobs", {}, None),
    "get_job": ("GET", "/jobs/{jobId}", {"job_id": "jobId"}, None),
    "create_job": ("POST", "/jobs", {}, "form"),
    "update_job": ("PUT", "/jobs/{jobId}", {"job_id": "jobId"}, "form"),
    "get_job_financial_summary": ("GET", "/jobs/{jobId}/financial_summary", {"job_id": "jobId"}, None),
    "get_job_workflow_history": ("GET", "/jobs/{jobId}/workflow_history", {"job_id": "jobId"}, None),
    "update_job_stage": ("POST", "/jobs/stage", {}, "multipart"),
    "list_job_notes": ("GET", "/jobs/{jobId}/notes", {"job_id": "jobId"}, None),
    "create_job_note": ("POST", "/jobs/{jobId}/notes", {"job_id": "jobId"}, "multipart"),
    "update_job_note": ("PUT", "/jobs/notes/{noteId}", {"note_id": "noteId"}, "form"),
    "list_contacts": ("GET", "/contacts", {}, None),
    "list_users": ("GET", "/company/users", {}, None),
    "list_trades": ("GET", "/company/trades", {}, None),
    "list_workflow_stages": ("GET", "/workflow/stages", {}, None),
    "create_task": ("POST", "/tasks", {}, "multipart"),
}


def _form_fields(values):
    """Encode PHP nested field names exactly as documented by Leap."""
    fields = []
    def add(key, value):
        if isinstance(value, dict):
            for child, item in value.items():
                add(f"{key}[{child}]", item)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                add(f"{key}[{index}]" if isinstance(item, dict) else f"{key}[]", item)
        elif value is not None:
            fields.append((key, str(value)))
    for key, value in values.items():
        add(key, value)
    return fields


class LeapNode(WorkflowNode):
    integration_type = "automation-leap"
    connection_evidence = ConnectionEvidence(
        noun="company users", operation="list_users", label_keys=("email", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return LeapNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Leap API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path, path_fields, encoding = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field, placeholder in path_fields.items():
            path = path.replace("{" + placeholder + "}", str(values.pop(field)))
        kwargs = {}
        if method == "GET":
            kwargs["params"] = values
        elif encoding == "multipart":
            kwargs["files"] = [(key, (None, value)) for key, value in _form_fields(values)]
        else:
            kwargs["content"] = urlencode(_form_fields(values))
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if encoding == "form":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            # No retries: a timeout may occur after a write was accepted.
            raise ValueError("Leap request did not complete; inspect before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = response.text.replace(token, "[redacted]")[:2000]
            raise ValueError(f"Leap HTTP {response.status_code}: {message}")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Leap returned an invalid JSON response") from None
        if not isinstance(body, dict) or body.get("error") or body.get("errors"):
            raise ValueError("Leap returned an error or unexpected response")
        # Preserve documented envelopes (customer, job, data, meta, status).
        # The platform's success marker stays separate from Leap's numeric status.
        output = {"status": "success", "action": config.operation,
                  "data": {k: v for k, v in body.items() if k != "status"},
                  "http_status": response.status_code}
        await self.emit(output)
        return output
