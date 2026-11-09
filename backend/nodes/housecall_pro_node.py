"""Housecall Pro's published v1 API using a manually supplied Company API key.

Each operation makes one documented request; paging is explicit and writes are
reported as API acknowledgements, without claiming a later business outcome.
"""
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.housecallpro.com"
CREDENTIAL_TYPE = "housecall_pro_api_key"
ResourceID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Text = Annotated[str, Field(max_length=10000)]
IDs = Annotated[list[ResourceID], Field(max_length=100)]
Tags = Annotated[list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=100)]


class HousecallProAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Housecall Pro API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.housecallpro.com/en/articles/8505035-api-overview",
            "x-credential-instructions": "An admin on a MAX plan can generate a Company API key in My Apps → All Apps → API Key Management. Choose Full access for writes or Read-only for reads. Paste the key alone; NoClick sends Authorization: Token to api.housecallpro.com. Connecting reads your company information.",
        })
    credential_type: Literal["housecall_pro_api_key"] = Field("housecall_pro_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key alone, without the Token prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="Page number. Use next_page from the preceding result.")
    page_size: int = Field(10, ge=1, le=100)
    sort_direction: Literal["asc", "desc"] = "desc"


class _CustomerFields(_Input):
    first_name: Text | None = None
    last_name: Text | None = None
    email: Text | None = None
    company: Text | None = None
    notifications_enabled: bool | None = Field(None, description="Whether Housecall Pro may notify this customer.")
    mobile_number: Text | None = None
    home_number: Text | None = None
    work_number: Text | None = None
    tags: Tags | None = None
    lead_source: Text | None = None
    notes: Text | None = None


class AddressInput(_Input):
    street: Text
    street_line_2: Text | None = None
    city: Text
    state: Text
    zip: Text
    country: Text


class LineItemInput(_Input):
    name: Annotated[str, Field(min_length=1, max_length=1000)]
    description: Text | None = None
    unit_price: float = Field(0, allow_inf_nan=False, description="Selling price per unit in cents.")
    quantity: float = Field(1, allow_inf_nan=False, gt=0, description="Quantity; up to two decimal places.")
    unit_cost: float = Field(0, allow_inf_nan=False, description="Cost per unit in cents.")

    @field_validator("quantity")
    @classmethod
    def precision(cls, value):
        if abs(value * 100 - round(value * 100)) > 1e-7:
            raise ValueError("Use at most two decimal places for quantity")
        return value


def _iso(value):
    if value is None: return value
    try: datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError): raise ValueError("Use an ISO-8601 date and time") from None
    if "T" not in value: raise ValueError("Include the time in the ISO-8601 value")
    return value


class JobSchedule(_Input):
    scheduled_start: str
    scheduled_end: str
    arrival_window: int | None = Field(None, ge=0)
    _dates = field_validator("scheduled_start", "scheduled_end")(_iso)


class EstimateOption(_Input):
    name: Text
    tags: Tags | None = None
    line_items: Annotated[list[LineItemInput], Field(max_length=100)] | None = None


class _JobID(_Input):
    job_id: ResourceID = Field(..., description="Housecall Pro job ID.")


class _CustomerID(_Input):
    customer_id: ResourceID = Field(..., description="Housecall Pro customer ID.")


class _WorkPage(_Page):
    customer_id: ResourceID | None = None
    scheduled_start_min: str | None = None
    scheduled_start_max: str | None = None
    scheduled_end_min: str | None = None
    scheduled_end_max: str | None = None
    _dates = field_validator("scheduled_start_min", "scheduled_start_max", "scheduled_end_min", "scheduled_end_max")(_iso)


class GetCompany(_Input):
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"ui:hidden": True})


class ListCustomers(_Page):
    operation: Literal["list_customers"] = Field("list_customers", title="List Customers", json_schema_extra={"ui:hidden": True})
    q: Text | None = Field(None, description="Search name, email, mobile number or address.")
    sort_by: Literal["created_at", "updated_at"] = "created_at"


class GetCustomer(_CustomerID):
    operation: Literal["get_customer"] = Field("get_customer", title="Get Customer", json_schema_extra={"ui:hidden": True})


class CreateCustomer(_CustomerFields):
    operation: Literal["create_customer"] = Field("create_customer", title="Create Customer", json_schema_extra={"ui:hidden": True})
    first_name: Annotated[str, Field(min_length=1, max_length=1000)]
    addresses: Annotated[list[AddressInput], Field(max_length=100)] | None = None


class UpdateCustomer(_CustomerID, _CustomerFields):
    operation: Literal["update_customer"] = Field("update_customer", title="Update Customer", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set - {"operation", "customer_id"}:
            raise ValueError("Supply at least one customer field to update")
        return self


class CreateCustomerAddress(_CustomerID, AddressInput):
    operation: Literal["create_customer_address"] = Field("create_customer_address", title="Create Customer Address", json_schema_extra={"ui:hidden": True})


class ListEmployees(_Page):
    operation: Literal["list_employees"] = Field("list_employees", title="List Employees", json_schema_extra={"ui:hidden": True})


class ListJobs(_WorkPage):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Jobs", json_schema_extra={"ui:hidden": True})
    sort_by: Literal["created_at", "updated_at", "invoice_number", "id", "description", "work_status"] = "created_at"


class GetJob(_JobID):
    operation: Literal["get_job"] = Field("get_job", title="Get Job", json_schema_extra={"ui:hidden": True})


class CreateJob(_CustomerID):
    operation: Literal["create_job"] = Field("create_job", title="Create Job", json_schema_extra={"ui:hidden": True})
    address_id: ResourceID
    schedule: JobSchedule | None = None
    assigned_employee_ids: IDs | None = None
    line_items: Annotated[list[LineItemInput], Field(max_length=100)] | None = None
    tags: Tags | None = None
    lead_source: Text | None = None
    notes: Text | None = None


class ListJobLineItems(_JobID):
    operation: Literal["list_job_line_items"] = Field("list_job_line_items", title="List Job Line Items", json_schema_extra={"ui:hidden": True})


class CreateJobLineItem(_JobID, LineItemInput):
    operation: Literal["create_job_line_item"] = Field("create_job_line_item", title="Create Job Line Item", json_schema_extra={"ui:hidden": True})
    kind: Literal["materials", "labor", "fixed gratuity", "fixed discount", "percent discount"] = "labor"
    taxable: bool = True


class ListJobAppointments(_JobID):
    operation: Literal["list_job_appointments"] = Field("list_job_appointments", title="List Job Appointments", json_schema_extra={"ui:hidden": True})


class CreateJobAppointment(_JobID):
    operation: Literal["create_job_appointment"] = Field("create_job_appointment", title="Create Job Appointment", json_schema_extra={"ui:hidden": True})
    start_time: str
    end_time: str
    dispatched_employees_ids: IDs
    arrival_window_minutes: int | None = Field(None, ge=0)
    _dates = field_validator("start_time", "end_time")(_iso)


class AddJobNote(_JobID):
    operation: Literal["add_job_note"] = Field("add_job_note", title="Add Job Note", json_schema_extra={"ui:hidden": True})
    content: Annotated[str, Field(min_length=1, max_length=10000)]


class DeleteJobNote(_JobID):
    operation: Literal["delete_job_note"] = Field("delete_job_note", title="Delete Job Note", json_schema_extra={"ui:hidden": True})
    note_id: ResourceID


class AddJobTag(_JobID):
    operation: Literal["add_job_tag"] = Field("add_job_tag", title="Add Job Tag", json_schema_extra={"ui:hidden": True})
    tag_id: ResourceID


class RemoveJobTag(_JobID):
    operation: Literal["remove_job_tag"] = Field("remove_job_tag", title="Remove Job Tag", json_schema_extra={"ui:hidden": True})
    tag_id: ResourceID


class ListEstimates(_WorkPage):
    operation: Literal["list_estimates"] = Field("list_estimates", title="List Estimates", json_schema_extra={"ui:hidden": True})
    sort_by: Literal["created_at", "updated_at", "id"] = "created_at"


class CreateEstimate(_CustomerID):
    operation: Literal["create_estimate"] = Field("create_estimate", title="Create Estimate", json_schema_extra={"ui:hidden": True})
    address_id: ResourceID
    options: Annotated[list[EstimateOption], Field(min_length=1, max_length=100)]
    assigned_employee_ids: IDs | None = None
    lead_source: Text | None = None
    note: Text | None = None
    message: Text | None = None


class ListLeads(_Page):
    operation: Literal["list_leads"] = Field("list_leads", title="List Leads", json_schema_extra={"ui:hidden": True})
    customer_id: ResourceID | None = None
    status: Literal["lost", "open", "won"] | None = None
    sort_by: Literal["created_at", "updated_at", "id", "status"] = "created_at"


class GetLead(_Input):
    operation: Literal["get_lead"] = Field("get_lead", title="Get Lead", json_schema_extra={"ui:hidden": True})
    lead_id: ResourceID


class CreateLead(_CustomerID):
    operation: Literal["create_lead"] = Field("create_lead", title="Create Lead", json_schema_extra={"ui:hidden": True})
    address_id: ResourceID | None = None
    assigned_employee_id: ResourceID | None = None
    lead_source: Text | None = None
    note: Text | None = None
    tags: Tags | None = None


class ListTags(_Page):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})
    sort_by: Literal["created_at", "name"] = "created_at"


class ListLeadSources(_Page):
    operation: Literal["list_lead_sources"] = Field("list_lead_sources", title="List Lead Sources", json_schema_extra={"ui:hidden": True})
    q: Text | None = None


HousecallProConfig = Annotated[Union[
    GetCompany, ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer,
    CreateCustomerAddress, ListEmployees, ListJobs, GetJob, CreateJob,
    ListJobLineItems, CreateJobLineItem, ListJobAppointments, CreateJobAppointment,
    AddJobNote, DeleteJobNote, AddJobTag, RemoveJobTag, ListEstimates,
    CreateEstimate, ListLeads, GetLead, CreateLead, ListTags, ListLeadSources,
], Field(discriminator="operation")]


class HousecallProFullConfig(NodeConfig[HousecallProConfig, HousecallProAPIKeyCredential]):
    pass


# method, path template, expected status, list envelope (when applicable).
OPERATIONS = {
    "get_company": ("GET", "/company", 200, None),
    "list_customers": ("GET", "/customers", 200, "customers"),
    "get_customer": ("GET", "/customers/{customer_id}", 200, None),
    "create_customer": ("POST", "/customers", 201, None),
    "update_customer": ("PUT", "/customers/{customer_id}", 200, None),
    "create_customer_address": ("POST", "/customers/{customer_id}/addresses", 200, None),
    "list_employees": ("GET", "/employees", 200, "employees"),
    "list_jobs": ("GET", "/jobs", 200, "jobs"),
    "get_job": ("GET", "/jobs/{job_id}", 200, None),
    "create_job": ("POST", "/jobs", 201, None),
    "list_job_line_items": ("GET", "/jobs/{job_id}/line_items", 200, "data"),
    "create_job_line_item": ("POST", "/jobs/{job_id}/line_items", 201, None),
    "list_job_appointments": ("GET", "/jobs/{job_id}/appointments", 200, "appointments"),
    "create_job_appointment": ("POST", "/jobs/{job_id}/appointments", 201, None),
    "add_job_note": ("POST", "/jobs/{job_id}/notes", 201, None),
    "delete_job_note": ("DELETE", "/jobs/{job_id}/notes/{note_id}", 200, None),
    "add_job_tag": ("POST", "/jobs/{job_id}/tags", 201, "tags"),
    "remove_job_tag": ("DELETE", "/jobs/{job_id}/tags/{tag_id}", 200, "tags"),
    "list_estimates": ("GET", "/estimates", 200, "estimates"),
    "create_estimate": ("POST", "/estimates", 200, None),
    "list_leads": ("GET", "/leads", 200, "leads"),
    "get_lead": ("GET", "/leads/{lead_id}", 200, None),
    "create_lead": ("POST", "/leads", 201, None),
    "list_tags": ("GET", "/tags", 200, "tags"),
    "list_lead_sources": ("GET", "/lead_sources", 200, "lead_sources"),
}


def _guard(config_data):
    raw = config_data.get("credentials")
    if raw is not None and (not isinstance(raw, dict) or raw.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE):
        raise ValueError("Supply a Housecall Pro API key credential")


class HousecallProNode(WorkflowNode):
    integration_type = "automation-housecall-pro"
    connection_evidence = ConnectionEvidence(noun="company", identity_operation="get_company")

    @classmethod
    def get_config_model(cls):
        return HousecallProFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try: _guard(config_data)
        except ValueError as exc: return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not isinstance(self.config, HousecallProFullConfig) or not self.config.credentials:
            raise ValueError("Supply a Housecall Pro API key credential")
        config = self.config.config
        method, path, expected, envelope = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, mode="json")
        values.pop("operation")
        # Substitute only validated single IDs; paths and origin are never user supplied.
        for name in tuple(values):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(values.pop(name), safe=""))
        kwargs = {"params": values} if method == "GET" else {"json": values} if method in {"POST", "PUT"} else {}
        result = {"operation": config.operation}
        token = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Token " + token, "Accept": "application/json"}, **kwargs)
            if response.status_code != expected:
                # Keep rejection text for the shared connection verdict, with secrets removed.
                message = "Housecall Pro returned HTTP " + str(response.status_code)
                if response.headers.get("content-type", "").split(";", 1)[0] == "application/json" and len(response.content) < 10000:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"].replace(token, "[redacted]")[:1000]
                return {**result, "status": "error", "error": message, "http_status": response.status_code}
            if config.operation == "delete_job_note":
                return {**result, "status": "success", "acknowledged": True, "http_status": response.status_code}
            if len(response.content) > 4_000_000 or response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                raise ValueError("Expected a bounded JSON response")
            body = response.json()
            if not isinstance(body, dict) or any(k in body for k in ("error", "errors")):
                raise ValueError("Housecall Pro returned an invalid response")
            output = {**result, "status": "success", "data": body, "http_status": response.status_code}
            if envelope:
                rows = body.get(envelope)
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("Housecall Pro list envelope is missing")
                output["items"] = rows
            if isinstance(config, _Page):
                page, total = body.get("page"), body.get("total_pages")
                # Published examples use zero pagination values. Preserve them; don't infer completion from row count.
                if type(page) not in (int, float) or type(total) not in (int, float) or page < 0 or total < 0:
                    raise ValueError("Housecall Pro pagination metadata is missing")
                output["next_page"] = int(page) + 1 if page < total else None
                output["has_more"] = page < total
            if method != "GET": output["acknowledged"] = True
            return output
        except (httpx.HTTPError, ValueError):
            return {**result, "status": "error", "error": "Housecall Pro did not return a valid completed response"}
