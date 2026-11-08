"""GorillaDesk v1: company, customers, scheduling and billing.

Contract: https://api.gorilladesk.com/v1/specs (1.0.0).
Each operation makes exactly one request. Lists return one explicit offset page;
writes are never retried automatically.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.gorilladesk.com/v1"


class GorillaDeskAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="GorillaDesk API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://beta.gorilladesk.com/addons/api",
            "x-credential-instructions": "Generate a company API key in GorillaDesk → Addons → API. Paste the key without the Bearer prefix. NoClick checks your company profile when connecting.",
        })
    credential_type: Literal["gorilladesk_api_key"] = Field("gorilladesk_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ch.isspace() or ord(ch) < 33 or ord(ch) > 126 for ch in value):
            raise ValueError("Paste only the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def validate_ids(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
                raise ValueError("Use a single GorillaDesk resource ID")
        return value


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, description="Number of records in this page.")
    offset: int = Field(0, ge=0, description="Use next_offset from the preceding result.")


class Location(_Input):
    """GorillaDesk's documented writable location fields (id is read-only)."""
    name: str | None = None
    address_to: str | None = None
    address_line_1: str = Field(..., min_length=1)
    address_line_2: str | None = None
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    zip: str = Field(..., min_length=1)
    county: str | None = None
    billing_to: str | None = None
    billing_address_line_1: str | None = None
    billing_address_line_2: str | None = None
    billing_city: str | None = None
    billing_state: str | None = None
    billing_zip: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    note: str | None = None


class CustomerPhone(_Input):
    id: str | None = None
    phone: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1, description="Phone type ID from GorillaDesk.")


class _CustomerFields(_Input):
    first_name: str = Field(..., min_length=1)
    last_name: str | None = None
    account_number: str | None = Field(None, pattern=r".*[0-9]$", description="Must end with a number.")
    status: Literal["active", "inactive", "lead"] | None = None
    email: str | None = None
    company: str | None = None
    phones: list[CustomerPhone] | None = None


class GetCompanyConfig(_Input):
    """Retrieve company."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})


class ListUsersConfig(_Page):
    """List all users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class GetUserConfig(_Input):
    """Retrieve a user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class ListCustomersConfig(_Page):
    """List all customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    state: Literal['active', 'deleted'] | None = None
    status: Literal['active', 'inactive', 'lead'] | None = None
    account_number: str | None = None
    created_gt: datetime | None = None
    created_gte: datetime | None = None
    created_lt: datetime | None = None
    created_lte: datetime | None = None
    updated_gt: datetime | None = None
    updated_gte: datetime | None = None
    updated_lt: datetime | None = None
    updated_lte: datetime | None = None


class GetCustomerConfig(_Input):
    """Retrieve a customer."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class CreateCustomerConfig(_CustomerFields):
    """Create a customer."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    location: Location


class UpdateCustomerConfig(_CustomerFields):
    """Update a customer."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class AddCustomerLocationConfig(Location):
    """Add a customer location."""
    operation: Literal["add_customer_location"] = Field("add_customer_location", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class CreateCustomerNoteConfig(_Input):
    """Create a customer note."""
    operation: Literal["create_customer_note"] = Field("create_customer_note", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")
    content: str = Field(..., min_length=1, description="Text of the customer note. This operation does not notify users or upload attachments.")


class ListLeadsConfig(_Page):
    """List inbound leads."""
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})
    account_number: str | None = None
    created_gt: datetime | None = None
    created_gte: datetime | None = None
    created_lt: datetime | None = None
    created_lte: datetime | None = None


class ListJobsConfig(_Page):
    """List jobs."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})
    customer_id: str | None = None
    state: Literal['active', 'deleted'] | None = None
    date_gt: datetime | None = None
    date_gte: datetime | None = None
    date_lt: datetime | None = None
    date_lte: datetime | None = None
    keyword: str | None = None


class GetJobConfig(_Input):
    """Retrieve a job."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class ListJobActivitiesConfig(_Page):
    """List job activities."""
    operation: Literal["list_job_activities"] = Field("list_job_activities", json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")
    date_gt: datetime | None = None
    date_lt: datetime | None = None


class ListInvoicesConfig(_Page):
    """List invoices."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})
    customer_id: str | None = None
    job_id: str | None = None
    state: Literal['active', 'deleted', 'archived'] | None = None
    status: Literal['draft', 'sent', 'paid', 'partial', 'partial_paid', 'write_off', 'failed', 'void'] | None = None
    sign_status: Literal['draft', 'emailed', 'pending_sig', 'signed'] | None = None
    date_gt: datetime | None = None
    date_gte: datetime | None = None
    date_lt: datetime | None = None
    date_lte: datetime | None = None
    keyword: str | None = None


class GetInvoiceConfig(_Input):
    """Retrieve an invoice."""
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class ListEstimatesConfig(_Page):
    """List estimates."""
    operation: Literal["list_estimates"] = Field("list_estimates", json_schema_extra={"ui:hidden": True})
    customer_id: str | None = None
    job_id: str | None = None
    state: Literal['active', 'deleted', 'archived'] | None = None
    status: Literal['draft', 'pending', 'won', 'lost'] | None = None
    sign_status: Literal['draft', 'emailed', 'pending_sig', 'signed'] | None = None
    date_gt: datetime | None = None
    date_gte: datetime | None = None
    date_lt: datetime | None = None
    date_lte: datetime | None = None
    keyword: str | None = None


class GetEstimateConfig(_Input):
    """Retrieve an estimate."""
    operation: Literal["get_estimate"] = Field("get_estimate", json_schema_extra={"ui:hidden": True})
    estimate_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class ListPaymentsConfig(_Page):
    """List payments."""
    operation: Literal["list_payments"] = Field("list_payments", json_schema_extra={"ui:hidden": True})
    customer_id: str | None = None
    invoice_id: str | None = None
    status: Literal['failed', 'pending', 'paid'] | None = None
    date_gt: datetime | None = None
    date_gte: datetime | None = None
    date_lt: datetime | None = None
    date_lte: datetime | None = None


class GetPaymentConfig(_Input):
    """Retrieve a payment."""
    operation: Literal["get_payment"] = Field("get_payment", json_schema_extra={"ui:hidden": True})
    payment_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class ListSchedulesConfig(_Page):
    """List schedules."""
    operation: Literal["list_schedules"] = Field("list_schedules", json_schema_extra={"ui:hidden": True})


class GetScheduleConfig(_Input):
    """Retrieve a schedule."""
    operation: Literal["get_schedule"] = Field("get_schedule", json_schema_extra={"ui:hidden": True})
    schedule_id: str = Field(..., min_length=1, description="GorillaDesk resource ID.")


class ListServicesConfig(_Page):
    """List service templates."""
    operation: Literal["list_services"] = Field("list_services", json_schema_extra={"ui:hidden": True})


class ListBranchesConfig(_Page):
    """List all branches."""
    operation: Literal["list_branches"] = Field("list_branches", json_schema_extra={"ui:hidden": True})
    keyword: str | None = None


class ListSourcesConfig(_Page):
    """List all sources."""
    operation: Literal["list_sources"] = Field("list_sources", json_schema_extra={"ui:hidden": True})
    keyword: str | None = None


class ListJobStatusesConfig(_Page):
    """List job statuses."""
    operation: Literal["list_job_statuses"] = Field("list_job_statuses", json_schema_extra={"ui:hidden": True})
    keyword: str | None = None


GorillaDeskOperation = Annotated[Union[
    GetCompanyConfig,
    ListUsersConfig,
    GetUserConfig,
    ListCustomersConfig,
    GetCustomerConfig,
    CreateCustomerConfig,
    UpdateCustomerConfig,
    AddCustomerLocationConfig,
    CreateCustomerNoteConfig,
    ListLeadsConfig,
    ListJobsConfig,
    GetJobConfig,
    ListJobActivitiesConfig,
    ListInvoicesConfig,
    GetInvoiceConfig,
    ListEstimatesConfig,
    GetEstimateConfig,
    ListPaymentsConfig,
    GetPaymentConfig,
    ListSchedulesConfig,
    GetScheduleConfig,
    ListServicesConfig,
    ListBranchesConfig,
    ListSourcesConfig,
    ListJobStatusesConfig,
], Field(discriminator="operation")]


class GorillaDeskFullConfig(NodeConfig[GorillaDeskOperation, GorillaDeskAPIKeyCredential]):
    pass


ROUTES = {'get_company': ('GET', '/company', {}),
 'list_users': ('GET', '/users', {}),
 'get_user': ('GET', '/users/{userId}', {'userId': 'user_id'}),
 'list_customers': ('GET', '/customers', {}),
 'get_customer': ('GET', '/customers/{customerId}', {'customerId': 'customer_id'}),
 'create_customer': ('POST', '/customers', {}),
 'update_customer': ('PUT', '/customers/{customerId}', {'customerId': 'customer_id'}),
 'add_customer_location': ('POST',
                           '/customers/{customerId}/locations',
                           {'customerId': 'customer_id'}),
 'create_customer_note': ('POST', '/customers/{customerId}/notes', {'customerId': 'customer_id'}),
 'list_leads': ('GET', '/leads', {}),
 'list_jobs': ('GET', '/jobs', {}),
 'get_job': ('GET', '/jobs/{jobId}', {'jobId': 'job_id'}),
 'list_job_activities': ('GET', '/jobs/{jobId}/activities', {'jobId': 'job_id'}),
 'list_invoices': ('GET', '/invoices', {}),
 'get_invoice': ('GET', '/invoices/{invoiceId}', {'invoiceId': 'invoice_id'}),
 'list_estimates': ('GET', '/estimates', {}),
 'get_estimate': ('GET', '/estimates/{estimateId}', {'estimateId': 'estimate_id'}),
 'list_payments': ('GET', '/payments', {}),
 'get_payment': ('GET', '/payments/{paymentId}', {'paymentId': 'payment_id'}),
 'list_schedules': ('GET', '/schedules', {}),
 'get_schedule': ('GET', '/schedules/{scheduleId}', {'scheduleId': 'schedule_id'}),
 'list_services': ('GET', '/services', {}),
 'list_branches': ('GET', '/branches', {}),
 'list_sources': ('GET', '/sources', {}),
 'list_job_statuses': ('GET', '/job-statuses', {})}
QUERY_FIELDS = {'get_company': {},
 'list_users': {},
 'get_user': {},
 'list_customers': {'state': 'state',
                    'status': 'status',
                    'account_number': 'account_number',
                    'created_gt': 'created[gt]',
                    'created_gte': 'created[gte]',
                    'created_lt': 'created[lt]',
                    'created_lte': 'created[lte]',
                    'updated_gt': 'updated[gt]',
                    'updated_gte': 'updated[gte]',
                    'updated_lt': 'updated[lt]',
                    'updated_lte': 'updated[lte]'},
 'get_customer': {},
 'create_customer': {},
 'update_customer': {},
 'add_customer_location': {},
 'create_customer_note': {},
 'list_leads': {'account_number': 'account_number',
                'created_gt': 'created[gt]',
                'created_gte': 'created[gte]',
                'created_lt': 'created[lt]',
                'created_lte': 'created[lte]'},
 'list_jobs': {'customer_id': 'customer_id',
               'state': 'state',
               'date_gt': 'date[gt]',
               'date_gte': 'date[gte]',
               'date_lt': 'date[lt]',
               'date_lte': 'date[lte]',
               'keyword': 'keyword'},
 'get_job': {},
 'list_job_activities': {'date_gt': 'date[gt]', 'date_lt': 'date[lt]'},
 'list_invoices': {'customer_id': 'customer_id',
                   'job_id': 'job_id',
                   'state': 'state',
                   'status': 'status',
                   'sign_status': 'sign_status',
                   'date_gt': 'date[gt]',
                   'date_gte': 'date[gte]',
                   'date_lt': 'date[lt]',
                   'date_lte': 'date[lte]',
                   'keyword': 'keyword'},
 'get_invoice': {},
 'list_estimates': {'customer_id': 'customer_id',
                    'job_id': 'job_id',
                    'state': 'state',
                    'status': 'status',
                    'sign_status': 'sign_status',
                    'date_gt': 'date[gt]',
                    'date_gte': 'date[gte]',
                    'date_lt': 'date[lt]',
                    'date_lte': 'date[lte]',
                    'keyword': 'keyword'},
 'get_estimate': {},
 'list_payments': {'customer_id': 'customer_id',
                   'invoice_id': 'invoice_id',
                   'status': 'status',
                   'date_gt': 'date[gt]',
                   'date_gte': 'date[gte]',
                   'date_lt': 'date[lt]',
                   'date_lte': 'date[lte]'},
 'get_payment': {},
 'list_schedules': {},
 'get_schedule': {},
 'list_services': {},
 'list_branches': {'keyword': 'keyword'},
 'list_sources': {'keyword': 'keyword'},
 'list_job_statuses': {'keyword': 'keyword'}}
LIST_OPERATIONS = frozenset(['list_users', 'list_customers', 'list_leads', 'list_jobs', 'list_job_activities', 'list_invoices', 'list_estimates', 'list_payments', 'list_schedules', 'list_services', 'list_branches', 'list_sources', 'list_job_statuses'])


class GorillaDeskNode(WorkflowNode):
    integration_type = "automation-gorilladesk"
    connection_evidence = ConnectionEvidence(noun="company", identity_operation="get_company")

    @classmethod
    def get_config_model(cls):
        return GorillaDeskFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a GorillaDesk API key")
        config = self.config.config
        method, route, bindings = ROUTES[config.operation]
        for placeholder, field in bindings.items():
            route = route.replace("{" + placeholder + "}", quote(getattr(config, field), safe=""))
        query = {}
        for field, wire in QUERY_FIELDS[config.operation].items():
            value = getattr(config, field)
            if value is not None:
                query[wire] = value.isoformat() if isinstance(value, datetime) else value
        if isinstance(config, _Page):
            query.update(limit=config.limit, offset=config.offset)
        payload = {}
        if config.operation in {"create_customer", "update_customer", "add_customer_location"}:
            body = config.model_dump(mode="json", exclude_none=True, exclude={"operation", "customer_id"})
            payload["json"] = body
        elif config.operation == "create_customer_note":
            # Force multipart even without attachments, as specified by the API.
            payload["files"] = {"content": (None, config.content)}
        secret = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            try:
                response = await client.request(method, BASE_URL + route, params=query,
                    headers={"Authorization": "Bearer " + secret, "Accept": "application/json"}, **payload)
            except httpx.HTTPError:
                raise ValueError("GorillaDesk request did not complete; inspect before retrying a write") from None
        if response.status_code != 200:
            # Preserve provider rejection text for the connect verdict, without leaking keys.
            message = response.text[:2000].replace(secret, "[redacted]")
            cooldown = response.headers.get("x-rate-limit-reset")
            raise ValueError(f"GorillaDesk HTTP {response.status_code}: {message}" +
                (f"; retry after {cooldown} seconds" if response.status_code == 429 and cooldown else ""))
        if len(response.content) > 10_000_000:
            raise ValueError("GorillaDesk response exceeds the supported size")
        try:
            result = response.json()
        except ValueError:
            raise ValueError("GorillaDesk returned invalid JSON") from None
        if not isinstance(result, dict) or result.get("error") or result.get("errors") or "data" not in result:
            raise ValueError("GorillaDesk returned an unsuccessful or unexpected response")
        listing = config.operation in LIST_OPERATIONS
        if not isinstance(result["data"], list if listing else dict):
            raise ValueError("GorillaDesk returned an unexpected data shape")
        output = dict(result)
        if listing:
            if type(result.get("has_more")) is not bool:
                raise ValueError("GorillaDesk did not return its pagination flag")
            if isinstance(config, _Page):
                output["next_offset"] = config.offset + len(result["data"]) if result["has_more"] else None
                if result["has_more"] and not result["data"]:
                    raise ValueError("GorillaDesk returned an empty continuing page")
        return output
