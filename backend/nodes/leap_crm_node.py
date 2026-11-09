"""Leap CRM v3 operations, mapped to the provider's published OpenAPI sections.

One request per operation; list results retain the provider's pagination metadata.
Documentation: https://docs.api.jobprogress.com/
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class LeapCRMTokenCredential(BaseModel):
    model_config = ConfigDict(title="Leap CRM API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.api.jobprogress.com/",
            "x-credential-instructions": "Paste your existing Leap CRM API bearer token. Ask your Leap administrator for API access if you do not have a token. NoClick sends it only to api.jobprogress.com. Customer reads verify access; other operations depend on your account permissions.",
        })
    credential_type: Literal["leap_crm_token"] = Field("leap_crm_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=8192, title="API token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API token without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("customer_id", "job_id", "note_id", check_fields=False)
    @classmethod
    def resource_id(cls, value):
        if value is None:
            return value
        if not re.fullmatch(r"[1-9][0-9]{0,18}", value):
            raise ValueError("Use a positive numeric Leap CRM resource ID")
        return value


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page to fetch. Use meta.pagination from the response to continue.")
    limit: int = Field(50, ge=1, le=100, description="Maximum records on this page.")


class ListCustomers(_Page):
    operation: Literal["list_customers"] = "list_customers"
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class GetCustomer(_Input):
    operation: Literal["get_customer"] = "get_customer"
    customer_id: str


class _CustomerWrite(_Input):
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    phone_number: str = Field(..., pattern=r"^[0-9]{8,12}$", description="Customer phone number, 8–12 digits.")
    phone_label: Literal["home", "cell", "phone", "office", "fax", "other"] = "cell"
    email: str | None = None
    note: str | None = None


class CreateCustomer(_CustomerWrite):
    """Create a residential customer with a required phone number."""
    operation: Literal["create_customer"] = "create_customer"


class UpdateCustomer(_CustomerWrite):
    """Update customer name and phone; omitted email/note remain untouched."""
    operation: Literal["update_customer"] = "update_customer"
    customer_id: str


class ListJobs(_Page):
    operation: Literal["list_jobs"] = "list_jobs"
    customer_id: str | None = None
    job_name: str | None = None


class GetJob(_Input):
    operation: Literal["get_job"] = "get_job"
    job_id: str


class _JobWrite(_Input):
    customer_id: str
    description: str = Field(..., min_length=1)
    trade_id: int = Field(..., ge=1, description="Trade ID from List trades. This action sends one trade.")
    name: str | None = None
    same_as_customer_address: Literal[1] = Field(1, description="Use the customer's existing address.")


class CreateJob(_JobWrite):
    operation: Literal["create_job"] = "create_job"


class UpdateJob(_JobWrite):
    """Update job details, including the customer, trade and address selection."""
    operation: Literal["update_job"] = "update_job"
    job_id: str


class GetJobFinancialSummary(GetJob):
    operation: Literal["get_job_financial_summary"] = "get_job_financial_summary"


class GetJobWorkflowHistory(GetJob):
    operation: Literal["get_job_workflow_history"] = "get_job_workflow_history"


class ListJobNotes(GetJob):
    operation: Literal["list_job_notes"] = "list_job_notes"


class AddJobNote(GetJob):
    operation: Literal["add_job_note"] = "add_job_note"
    note: str = Field(..., min_length=1)


class UpdateJobNote(_Input):
    operation: Literal["update_job_note"] = "update_job_note"
    note_id: str
    note: str = Field(..., min_length=1)


class ListContacts(_Input):
    operation: Literal["list_contacts"] = "list_contacts"
    limit: int = Field(50, ge=1, le=100)
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_id: str | None = None


class ListTrades(_Page):
    operation: Literal["list_trades"] = "list_trades"


class ListUsers(_Page):
    operation: Literal["list_users"] = "list_users"
    email: str | None = None


class ListWorkflowStages(_Page):
    operation: Literal["list_workflow_stages"] = "list_workflow_stages"
    name: str | None = None


LeapCRMOperation = Annotated[Union[
    ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer,
    ListJobs, GetJob, CreateJob, UpdateJob, GetJobFinancialSummary, GetJobWorkflowHistory,
    ListJobNotes, AddJobNote, UpdateJobNote, ListContacts, ListTrades, ListUsers, ListWorkflowStages,
], Field(discriminator="operation")]


class LeapCRMConfig(NodeConfig[LeapCRMOperation, LeapCRMTokenCredential]):
    pass


ROUTES = {
    "list_customers": ("GET", "/customers"),
    "get_customer": ("GET", "/customers/{customer_id}"),
    "create_customer": ("POST", "/customers"),
    "update_customer": ("PUT", "/customers/{customer_id}"),
    "list_jobs": ("GET", "/jobs"),
    "get_job": ("GET", "/jobs/{job_id}"),
    "create_job": ("POST", "/jobs"),
    "update_job": ("PUT", "/jobs/{job_id}"),
    "get_job_financial_summary": ("GET", "/jobs/{job_id}/financial_summary"),
    "get_job_workflow_history": ("GET", "/jobs/{job_id}/workflow_history"),
    "list_job_notes": ("GET", "/jobs/{job_id}/notes"),
    "add_job_note": ("POST", "/jobs/{job_id}/notes"),
    "update_job_note": ("PUT", "/jobs/notes/{note_id}"),
    "list_contacts": ("GET", "/contacts"),
    "list_trades": ("GET", "/company/trades"),
    "list_users": ("GET", "/company/users"),
    "list_workflow_stages": ("GET", "/workflow/stages"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "<redacted>")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class LeapCRMNode(WorkflowNode):
    integration_type = "automation-leap-crm"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers",
        label_keys=("company_name", "first_name", "last_name", "id"))

    @classmethod
    def get_config_model(cls):
        return LeapCRMConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Leap CRM API token")
        values = self.config.config.model_dump(exclude_none=True)
        operation = values.pop("operation")
        method, template = ROUTES[operation]
        path = template.format(**{key: values.pop(key) for key in re.findall(r"\{(\w+)\}", template)})
        if isinstance(self.config.config, _CustomerWrite):
            values["phones[0][number]"] = values.pop("phone_number")
            values["phones[0][label]"] = values.pop("phone_label")
        if isinstance(self.config.config, _JobWrite):
            values["trades[]"] = values.pop("trade_id")
        token = self.config.credentials.access_token
        kwargs = {"headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}}
        if method == "GET":
            kwargs["params"] = values
        elif operation == "add_job_note":
            kwargs["files"] = {key: (None, str(value)) for key, value in values.items()}
        else:
            kwargs["data"] = values
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://api.jobprogress.com/api/v3" + path, **kwargs)
        if not 200 <= response.status_code < 300:
            output = {"status": "error", "http_status": response.status_code,
                "error": response.text.replace(token, "<redacted>")[:2000]}
        else:
            # Several published examples are JSON served as text/plain.
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Expected a JSON response from Leap CRM") from None
            if not isinstance(payload, dict):
                raise ValueError("Unexpected Leap CRM response shape")
            payload = _redact(payload, token)
            if "error" in payload or "errors" in payload or payload.get("success") is False:
                output = {"status": "error", "http_status": response.status_code, "error": payload}
            else:
                # Keep customer/job write envelopes and meta.pagination intact.
                if not any(key in payload for key in ("data", "customer", "job")):
                    raise ValueError("Leap CRM response is missing its resource envelope")
                resource = payload.get("data", payload.get("customer", payload.get("job")))
                list_result = operation.startswith("list_") or operation in {"get_job_financial_summary", "get_job_workflow_history"}
                if not isinstance(resource, list if list_result else dict):
                    raise ValueError("Unexpected Leap CRM resource shape")
                output = {"status": "success", "http_status": response.status_code, **payload}
                # Provider status fields must not override the platform verdict.
                output["status"] = "success"
        await self.emit(output)
        return output
