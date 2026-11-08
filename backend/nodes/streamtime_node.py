"""Streamtime Public API v2: fixed operations from the published OpenAPI 1.0.0 contract.

Authentication: a subscriber's bearer token from Company Settings. Search is
one explicit page; callers use limit/offset and get_search_setup for selectors.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.streamtime.net/v2"


class StreamtimeTokenCredential(BaseModel):
    model_config = ConfigDict(title="Streamtime API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.streamtime.net/swagger.json",
            "x-credential-instructions": "In Streamtime, the subscriber can request a bearer token from Company Settings. Paste the token here without the Bearer prefix. The token acts with its user's access to the organisation.",
        })
    credential_type: Literal["streamtime_api_token"] = Field("streamtime_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyStatus(_Input):
    id: Literal[1, 2, 3]


class ContactStatus(_Input):
    id: Literal[1, 2, 3]


class JobStatus(_Input):
    id: Literal[1, 2, 3, 4, 5]


class LoggedTimeStatus(_Input):
    id: Literal[1, 2, 3]


class _CompanyFields(_Input):
    name: str = Field(None, description='Company name')
    isClient: bool = Field(None, description='Whether the company is a client')
    isSupplier: bool = Field(None, description='Whether the company is a supplier')
    companyStatus: CompanyStatus = Field(None, description='companyStatus')
    taxNumber: str | None = Field(None, description='Tax/GST/VAT number')
    phone1: str | None = Field(None, description='Primary phone number')
    phone2: str | None = Field(None, description='Secondary phone number')
    websiteAddress: str | None = Field(None, description='Website URL')
    notes: str | None = Field(None, description='Notes about the company')


class _ContactFields(_Input):
    firstName: str = Field(None, description='First name')
    lastName: str | None = Field(None, description='Last name')
    email: str | None = Field(None, description='Email address')
    phoneNumber: str | None = Field(None, description='Phone number')
    position: str | None = Field(None, description='Position / Job title')
    contactStatus: ContactStatus = Field(None, description='contactStatus')


class _JobFields(_Input):
    jobLeadUserId: int | None = Field(None, description='Job lead user ID')
    rateCardId: int = Field(None, description='The id of the rate card used for this job')
    branchId: int | None = Field(None, description='The id of the branch this job belongs to')
    jobStatus: JobStatus = Field(None, description='jobStatus')
    number: str | None = Field(None, description='Job number')
    name: str = Field(None, description='Job name')
    purchaseOrderNumber: str | None = Field(None, description='Client purchase order number')
    contactId: int | None = Field(None, description='The id of the contact this job is being done for')


class _LoggedTimeFields(_Input):
    userId: int = Field(None, description='userId')
    loggedTimeStatus: LoggedTimeStatus = Field(None, description='loggedTimeStatus')
    date: Date = Field(None, description='date')
    jobId: int | None = Field(None, description='jobId')
    jobItemUserId: int | None = Field(None, description='jobItemUserId')
    notes: str | None = Field(None, description='notes')
    private: bool = Field(None, description='private')
    minutes: int = Field(None, description='minutes')


SearchView = Literal['jobs', 'job_milestones', 'job_phases', 'job_items', 'job_item_quote_line_items', 'job_item_invoice_line_items', 'job_item_users', 'job_item_roles', 'job_item_sub_items', 'time', 'expenses', 'purchase_order_line_items', 'logged_expense_quote_line_items', 'logged_expense_invoice_line_items', 'quotes', 'quote_line_items', 'quote_line_item_invoice_line_items', 'invoices', 'invoice_line_items', 'job_groups', 'job_group_periods', 'companies', 'contacts', 'users']


class GetOrganisation(_Input):
    """Get your organisation's details."""
    operation: Literal["get_organisation"] = Field("get_organisation", json_schema_extra={"ui:hidden": True})


class ListUsers(_Input):
    """List your organisation's users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class ListBranches(_Input):
    """List branches."""
    operation: Literal["list_branches"] = Field("list_branches", json_schema_extra={"ui:hidden": True})


class ListRateCards(_Input):
    """List your organisation's rate cards."""
    operation: Literal["list_rate_cards"] = Field("list_rate_cards", json_schema_extra={"ui:hidden": True})


class CreateCompany(_CompanyFields):
    """Create a company."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class GetCompany(_Input):
    """Get company by ID."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0, description='Company Id')


class UpdateCompany(_CompanyFields):
    """Update company."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0, description='Company Id')


class ListCompanyContacts(_Input):
    """List company contacts."""
    operation: Literal["list_company_contacts"] = Field("list_company_contacts", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0, description='Company Id')


class CreateContact(_ContactFields):
    """Create company contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0, description='Company Id')
    firstName: str = Field(..., min_length=1)


class GetContact(_Input):
    """Get a specific contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0, description='Contact ID')


class UpdateContact(_ContactFields):
    """Update a contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0, description='Contact ID')


class CreateJob(_JobFields):
    """Create a job."""
    operation: Literal["create_job"] = Field("create_job", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class GetJob(_Input):
    """Get a job."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0, description='Job ID')


class UpdateJob(_JobFields):
    """Update a job."""
    operation: Literal["update_job"] = Field("update_job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0, description='Job Id')


class UpdateJobStatus(_Input):
    """Update a job's status."""
    operation: Literal["update_job_status"] = Field("update_job_status", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0, description='Job Id')
    job_status_id: Literal[1, 2, 3, 4, 5] = Field(..., description='New Job Status ID')


class ListJobItems(_Input):
    """List job items."""
    operation: Literal["list_job_items"] = Field("list_job_items", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0, description='Job Id')


class GetInvoice(_Input):
    """Get invoice by ID."""
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: int = Field(..., gt=0, description='Invoice Id')


class GetQuote(_Input):
    """Get quote by ID."""
    operation: Literal["get_quote"] = Field("get_quote", json_schema_extra={"ui:hidden": True})
    quote_id: int = Field(..., gt=0, description='Quote Id')


class CreateLoggedTime(_LoggedTimeFields):
    """Create a logged time entry."""
    operation: Literal["create_logged_time"] = Field("create_logged_time", json_schema_extra={"ui:hidden": True})
    userId: int = Field(..., gt=0)
    date: Date
    minutes: int = Field(..., ge=0)


class GetLoggedTime(_Input):
    """Get logged time entry by ID."""
    operation: Literal["get_logged_time"] = Field("get_logged_time", json_schema_extra={"ui:hidden": True})
    logged_time_id: int = Field(..., gt=0, description='Logged Time Id')


class UpdateLoggedTime(_LoggedTimeFields):
    """Update logged time entry."""
    operation: Literal["update_logged_time"] = Field("update_logged_time", json_schema_extra={"ui:hidden": True})
    logged_time_id: int = Field(..., gt=0, description='Logged Time Id')


class DeleteLoggedTime(_Input):
    """Delete logged time entry."""
    operation: Literal["delete_logged_time"] = Field("delete_logged_time", json_schema_extra={"ui:hidden": True})
    logged_time_id: int = Field(..., gt=0, description='Logged Time Id')


class GetSearchSetup(_Input):
    """Get the configuration details required to construct a search request accurately."""
    operation: Literal["get_search_setup"] = Field("get_search_setup", json_schema_extra={"ui:hidden": True})
    search_view: SearchView = Field(..., description='Get the specific details of what filters and data is available for a given search.')


class SearchRecords(_Input):
    """This route will search for individual records that match the given query. If you want to summarise records, use the report endpoint instead.."""
    operation: Literal["search_records"] = Field("search_records", json_schema_extra={"ui:hidden": True})
    search_view: SearchView = Field(..., description='What do you want to search for?')
    query: str = Field(..., min_length=1, description="Filter expression using selectors returned by get_search_setup.")
    limit: int = Field(30, ge=0, le=1000)
    offset: int = Field(0, ge=0)
    sortColumn: str = Field(None, description="A sortColumns value returned by get_search_setup.")
    sortAscending: bool = True
    additionalData: list[str] = Field(default_factory=list, description="Related objects supported by get_search_setup.")


StreamtimeOperation = Annotated[Union[
    GetOrganisation,
    ListUsers,
    ListBranches,
    ListRateCards,
    CreateCompany,
    GetCompany,
    UpdateCompany,
    ListCompanyContacts,
    CreateContact,
    GetContact,
    UpdateContact,
    CreateJob,
    GetJob,
    UpdateJob,
    UpdateJobStatus,
    ListJobItems,
    GetInvoice,
    GetQuote,
    CreateLoggedTime,
    GetLoggedTime,
    UpdateLoggedTime,
    DeleteLoggedTime,
    GetSearchSetup,
    SearchRecords
], Field(discriminator="operation")]


class StreamtimeFullConfig(NodeConfig[StreamtimeOperation, StreamtimeTokenCredential]):
    pass


# Each route maps to exactly one published contract operation.
ROUTES = {
    'get_organisation': ('GET', '/organisation', (), False),
    'list_users': ('GET', '/users', (), False),
    'list_branches': ('GET', '/branches', (), False),
    'list_rate_cards': ('GET', '/rate_cards', (), False),
    'create_company': ('POST', '/companies', (), True),
    'get_company': ('GET', '/companies/{company_id}', (), False),
    'update_company': ('PUT', '/companies/{company_id}', (), True),
    'list_company_contacts': ('GET', '/companies/{company_id}/contacts', (), False),
    'create_contact': ('POST', '/companies/{company_id}/contacts', (), True),
    'get_contact': ('GET', '/contacts/{contact_id}', (), False),
    'update_contact': ('PUT', '/contacts/{contact_id}', (), True),
    'create_job': ('POST', '/jobs', (), True),
    'get_job': ('GET', '/jobs/{job_id}', (), False),
    'update_job': ('PUT', '/jobs/{job_id}', (), True),
    'update_job_status': ('PUT', '/jobs/{job_id}/job_status', ('job_status_id',), False),
    'list_job_items': ('GET', '/jobs/{job_id}/job_items', (), False),
    'get_invoice': ('GET', '/invoices/{invoice_id}', (), False),
    'get_quote': ('GET', '/quotes/{quote_id}', (), False),
    'create_logged_time': ('POST', '/logged_times', (), True),
    'get_logged_time': ('GET', '/logged_times/{logged_time_id}', (), False),
    'update_logged_time': ('PUT', '/logged_times/{logged_time_id}', (), True),
    'delete_logged_time': ('DELETE', '/logged_times/{logged_time_id}', (), False),
    'get_search_setup': ('GET', '/search/setup', ('search_view',), False),
    'search_records': ('POST', '/search', ('search_view',), True),
}


class StreamtimeNode(WorkflowNode):
    integration_type = "automation-streamtime"
    connection_evidence = ConnectionEvidence(
        noun="Streamtime users", operation="list_users", identity_operation="get_organisation",
        label_keys=("name", "firstName", "email", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return StreamtimeFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Streamtime API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path, query_names, has_body = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_unset=True, exclude={"operation"})
        # Include defaults for the explicitly paginated search operation.
        if isinstance(op, SearchRecords):
            values = op.model_dump(mode="json", exclude={"operation"})
            values = {k: v for k, v in values.items() if v is not None}
        path_names = set()
        for name in type(op).model_fields:
            placeholder = "{" + name + "}"
            if placeholder in path:
                path = path.replace(placeholder, str(getattr(op, name)))
                path_names.add(name)
        params = {name: getattr(op, name) for name in query_names}
        body = {k: v for k, v in values.items() if k not in path_names and k not in query_names}
        if has_body and not body:
            raise ValueError("Supply at least one field to write")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if has_body else {}))
        if response.status_code < 200 or response.status_code >= 300:
            # Keep provider rejection wording so the shared connect seam can explain it.
            message = response.text.replace(token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": message}
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Expected a Streamtime JSON object or array")
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            return {"status": "error", "error": str(data).replace(token, "[redacted]")[:2000]}
        return {"status": "success", "data": data}
