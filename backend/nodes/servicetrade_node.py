"""ServiceTrade field-service workflows against the published REST API.

Each operation makes one request to the fixed provider origin. A manually
supplied session token uses the documented PHPSESSID cookie authentication.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.servicetrade.com/api"
CREDENTIAL_TYPE = "servicetrade_session_token"


class ServiceTradeSessionToken(BaseModel):
    model_config = ConfigDict(
        title="ServiceTrade Session Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.servicetrade.com/api/docs/tag/authentication",
            "x-credential-instructions": "Paste an existing API session's authToken (the PHPSESSID cookie value) from ServiceTrade. Send only the value, without PHPSESSID= or a Cookie header. The API documents this legacy session method alongside OAuth client credentials. Sessions expire: replace the token when ServiceTrade rejects it. NoClick does not sign in or renew this session. The session's user permissions govern reads and writes.",
        },
    )
    credential_type: Literal["servicetrade_session_token"] = Field(
        "servicetrade_session_token", json_schema_extra={"ui:hidden": True})
    session_token: str = Field(..., title="Session Token", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("session_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Session token")
        if not re.fullmatch(r"[A-Za-z0-9,-]{1,4096}", value):
            raise ValueError("Paste only the ServiceTrade session token value")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def numeric_values(cls, values):
        if isinstance(values, dict):
            for name, value in values.items():
                field = cls.model_fields.get(name)
                if field and "int" in str(field.annotation) and isinstance(value, bool):
                    raise ValueError("Use a number, not a boolean")
        return values



class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="One-based page number. Each run reads one page.")
    limit: int = Field(100, ge=1, le=2000, description="Page size; see ServiceTrade's general pagination contract.")


class Address(_Input):
    street: str = Field(..., min_length=1, max_length=100)
    city: str = Field(..., min_length=1, max_length=45)
    state: str = Field(..., min_length=2, max_length=2, description="Two-letter state or province code.")
    postal_code: str | None = Field(None, max_length=15)



class ServiceTradeListCompaniesConfig(_Page):
    'List all companies. Returns one page; pass the next_page value to continue.'
    operation: Literal['list_companies'] = Field('list_companies', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, max_length=500, description='Filter by company name (case-insensitive substring match)')
    status: Literal['active', 'pending', 'inactive', 'on_hold'] | None = Field(None, max_length=500, description='Filter by company status')
    is_customer: bool | None = Field(None, description='If `true`, returns only companies listed as customers')
    updated_after: int | None = Field(None, ge=0, description='Filter by records updated on or after this timestamp')
    updated_before: int | None = Field(None, ge=0, description='Filter by records updated on or before this timestamp')


class ServiceTradeGetCompanyConfig(_Input):
    'Retrieve a single company.'
    operation: Literal['get_company'] = Field('get_company', json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, le=9223372036854775807)


class ServiceTradeListContactsConfig(_Page):
    'List all contacts. Returns one page; pass the next_page value to continue.'
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True})
    company_id: int | None = Field(None, ge=1, le=9223372036854775807, description='Filter by company ID. Returns contacts belonging to this company or its locations. To only include contacts directly related to the company (excluding location contacts), also set `locationId` to empty string')
    search: str | None = Field(None, max_length=500, description='Search by contact name, phone numbers, or email address')
    email: str | None = Field(None, max_length=500, description='Exact match on contact email address')
    updated_after: int | None = Field(None, ge=0, description='Filter by contacts updated on or after this timestamp')
    updated_before: int | None = Field(None, ge=0, description='Filter by contacts updated on or before this timestamp')


class ServiceTradeGetContactConfig(_Input):
    'Get a single contact.'
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., ge=1, le=9223372036854775807)


class ServiceTradeListLocationsConfig(_Page):
    'List all locations. Returns one page; pass the next_page value to continue.'
    operation: Literal['list_locations'] = Field('list_locations', json_schema_extra={"ui:hidden": True})
    company_id: str | None = Field(None, max_length=500, description='Comma-separated list of company IDs; returns locations belonging to any of these')
    name: str | None = Field(None, max_length=500, description='Filter by location name or store number (substring match)')
    status: Literal['active', 'inactive', 'pending'] | None = Field(None, max_length=500, description='Comma-separated list of statuses to filter by')
    updated_after: int | None = Field(None, ge=0, description='Return locations updated on or after this timestamp')
    updated_before: int | None = Field(None, ge=0, description='Return locations updated on or before this timestamp')


class ServiceTradeGetLocationConfig(_Input):
    'Get a single location.'
    operation: Literal['get_location'] = Field('get_location', json_schema_extra={"ui:hidden": True})
    location_id: int = Field(..., ge=1, le=9223372036854775807)


class ServiceTradeListJobsConfig(_Page):
    'List all jobs. Returns one page; pass the next_page value to continue.'
    operation: Literal['list_jobs'] = Field('list_jobs', json_schema_extra={"ui:hidden": True})
    location_id: str | None = Field(None, max_length=500, description='Comma-separated list of location IDs')
    customer_id: str | None = Field(None, max_length=500, description='Comma-separated list of customer company IDs')
    name: str | None = Field(None, max_length=500, description='Filter by job custom name (substring match)')
    status: Literal['*', 'all', 'new', 'scheduled', 'canceled', 'bidding', 'completed', 'pending_invoice', 'sending_invoice', 'invoiced', 'closed'] | None = Field(None, max_length=500, description='Filter by one status; use * for all statuses. If omitted, ServiceTrade returns scheduled jobs only.')
    updated_after: int | None = Field(None, ge=0, description='Filter by records updated on or after this timestamp')
    updated_before: int | None = Field(None, ge=0, description='Filter by records updated on or before this timestamp')


class ServiceTradeGetJobConfig(_Input):
    'Get a single job.'
    operation: Literal['get_job'] = Field('get_job', json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., ge=1, le=9223372036854775807)


class ServiceTradeListAppointmentsConfig(_Page):
    'List all appointments. Returns one page; pass the next_page value to continue.'
    operation: Literal['list_appointments'] = Field('list_appointments', json_schema_extra={"ui:hidden": True})
    job_id: int | None = Field(None, ge=1, le=9223372036854775807, description='Filter by job ID')
    status: Literal['scheduled', 'unscheduled', 'canceled_by_vendor', 'canceled_by_customer', 'completed', 'no_show'] | None = Field(None, max_length=500, description='Comma-separated list of statuses, defaults to all except `unscheduled`')


class ServiceTradeGetAppointmentConfig(_Input):
    'Get a single appointment.'
    operation: Literal['get_appointment'] = Field('get_appointment', json_schema_extra={"ui:hidden": True})
    appointment_id: int = Field(..., ge=1, le=9223372036854775807)


class ServiceTradeListQuotesConfig(_Page):
    'List all quotes. Returns one page; pass the next_page value to continue.'
    operation: Literal['list_quotes'] = Field('list_quotes', json_schema_extra={"ui:hidden": True})
    location_id: str | None = Field(None, max_length=500, description='Comma-delimited list of integers, return only quotes applying to these locations')
    customer_id: int | None = Field(None, ge=1, le=9223372036854775807, description='Return only quotes for customer with this company ID')
    updated_after: int | None = Field(None, ge=0, description='Return only quotes whose last update time is on or after this timestamp')
    updated_before: int | None = Field(None, ge=0, description='Return only quotes whose last update time is on or before this timestamp')


class ServiceTradeGetQuoteConfig(_Input):
    'Retrieve a single quote.'
    operation: Literal['get_quote'] = Field('get_quote', json_schema_extra={"ui:hidden": True})
    quote_id: int = Field(..., ge=1, le=9223372036854775807)


class ServiceTradeListInvoicesConfig(_Page):
    'List all invoices. Returns one page; pass the next_page value to continue.'
    operation: Literal['list_invoices'] = Field('list_invoices', json_schema_extra={"ui:hidden": True})
    job_id: int | None = Field(None, ge=1, le=9223372036854775807, description='Job to which this invoice is attached')
    customer_id: int | None = Field(None, ge=1, le=9223372036854775807, description='Customer for this invoice')
    status: Literal['ok', 'internal_review', 'pending_accounting', 'pending_sales_tax', 'processed', 'paid', 'sent', 'failed', 'void'] | None = Field(None, max_length=500, description='Filter by status (multiple allowed). Note: `sent` and `paid` statuses are deprecated')
    updated_after: int | None = Field(None, ge=0, description='Updated on or after this timestamp')
    updated_before: int | None = Field(None, ge=0, description='Updated on or before this timestamp')


class ServiceTradeGetInvoiceConfig(_Input):
    'Retrieve a single invoice by ID.'
    operation: Literal['get_invoice'] = Field('get_invoice', json_schema_extra={"ui:hidden": True})
    invoice_id: int = Field(..., ge=1, le=9223372036854775807)


class ServiceTradeListDeficienciesConfig(_Page):
    'List all deficiencies. Returns one page; pass the next_page value to continue.'
    operation: Literal['list_deficiencies'] = Field('list_deficiencies', json_schema_extra={"ui:hidden": True})
    asset_id: int | None = Field(None, ge=1, le=9223372036854775807, description='Filter by asset ID')
    severity: Literal['inoperable', 'deficient', 'suggested'] | None = Field(None, max_length=500, description='Filter by severity level')
    updated_after: int | None = Field(None, ge=0, description='Filter by records updated on or after this timestamp')
    updated_before: int | None = Field(None, ge=0, description='Filter by records updated on or before this timestamp')


class ServiceTradeGetDeficiencyConfig(_Input):
    'Get a single deficiency.'
    operation: Literal['get_deficiency'] = Field('get_deficiency', json_schema_extra={"ui:hidden": True})
    deficiency_id: int = Field(..., ge=1, le=9223372036854775807)


class ServiceTradeCreateAppointmentConfig(_Input):
    'Create a new appointment. Only supplied fields are sent.'
    operation: Literal['create_appointment'] = Field('create_appointment', json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., ge=1, le=9223372036854775807, description='Job ID this appointment is for')
    status: Literal['scheduled', 'unscheduled', 'canceled_by_vendor', 'canceled_by_customer', 'completed', 'no_show'] | None = Field(None, max_length=500, description='Initial status, defaults to `scheduled`')
    service_request_ids: list[int] | None = Field(None, max_length=2000, description='Service request IDs to fulfill on this appointment (must belong to the job)')
    tech_ids: list[int] | None = Field(None, max_length=2000, description='Technician user IDs to assign to this appointment')
    window_start: int | None = Field(None, ge=0, description='Window start timestamp (defaults to `null` for unscheduled, current time for other statuses)')
    window_end: int | None = Field(None, ge=0, description='Window end timestamp (defaults to `null` for unscheduled, current time for other statuses)')
    released: bool | None = Field(None, description='Release appointment to assigned technicians (default depends on account settings)')


class ServiceTradeUpdateAppointmentConfig(_Input):
    'Update an appointment. Only supplied fields are sent.'
    operation: Literal['update_appointment'] = Field('update_appointment', json_schema_extra={"ui:hidden": True})
    appointment_id: int = Field(..., ge=1, le=9223372036854775807)
    status: Literal['scheduled', 'canceled_by_vendor', 'canceled_by_customer', 'completed', 'no_show'] | None = Field(None, max_length=500, description='New appointment status')
    service_request_ids: list[int] | None = Field(None, max_length=2000, description='Service request IDs to fulfill (replaces existing)')
    tech_ids: list[int] | None = Field(None, max_length=2000, description='Technician user IDs to assign (replaces existing)')
    window_start: int | None = Field(None, ge=0, description='Window start timestamp')
    window_end: int | None = Field(None, ge=0, description='Window end timestamp')
    released: bool | None = Field(None, description='Release appointment to assigned technicians')

    @model_validator(mode="after")
    def change_required(self):
        changes = self.model_dump(exclude_none=True, exclude={"operation", "appointment_id"})
        if not changes:
            raise ValueError("Provide at least one field to update")
        return self


class ServiceTradeCreateContactConfig(_Input):
    'Create a new contact. Only supplied fields are sent.'
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, max_length=50, description='Contact first name (required if `lastName` not provided)')
    last_name: str | None = Field(None, max_length=50, description='Contact last name (required if `firstName` not provided)')
    email: str | None = Field(None, max_length=100, description='Contact email address')
    phone: str | None = Field(None, max_length=30, description='Contact phone number')
    mobile: str | None = Field(None, max_length=30, description='Contact mobile phone number')
    status: Literal['public', 'private', 'inactive'] | None = Field(None, max_length=500, description='Contact visibility status (defaults to `private`)')
    company_ids: list[int] | None = Field(None, max_length=2000, description='IDs of companies to assign this contact to')
    location_ids: list[int] | None = Field(None, max_length=2000, description='IDs of locations to assign this contact to')
    types: list[str] | None = Field(None, max_length=2000, description='Contact types (e.g., `["management", "financial"]`). Takes precedence over `type`')

    @model_validator(mode="after")
    def name_required(self):
        if not (self.first_name or self.last_name):
            raise ValueError("Provide at least a first or last name")
        return self


class ServiceTradeUpdateContactConfig(_Input):
    'Update an existing contact. Only supplied fields are sent.'
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., ge=1, le=9223372036854775807)
    first_name: str | None = Field(None, max_length=50, description='Contact first name')
    last_name: str | None = Field(None, max_length=50, description='Contact last name')
    email: str | None = Field(None, max_length=100, description='Contact email address')
    phone: str | None = Field(None, max_length=30, description='Contact phone number')
    mobile: str | None = Field(None, max_length=30, description='Contact mobile phone number')
    status: Literal['public', 'private', 'inactive'] | None = Field(None, max_length=500, description='Contact visibility status')
    company_ids: list[int] | None = Field(None, max_length=2000, description='IDs of companies to assign this contact to (replaces existing assignments)')
    location_ids: list[int] | None = Field(None, max_length=2000, description='IDs of locations to assign this contact to (replaces existing assignments)')
    types: list[str] | None = Field(None, max_length=2000, description='Contact types (e.g., `["management", "financial"]`). Takes precedence over `type`')

    @model_validator(mode="after")
    def change_required(self):
        changes = self.model_dump(exclude_none=True, exclude={"operation", "contact_id"})
        if not changes:
            raise ValueError("Provide at least one field to update")
        return self


class ServiceTradeCreateLocationConfig(_Input):
    'Create a new location. Only supplied fields are sent.'
    operation: Literal['create_location'] = Field('create_location', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500, description='Location name')
    company_id: int = Field(..., ge=1, le=9223372036854775807, description='ID of the company this location belongs to')
    address: Address = Field(..., description='Address object: `street`, `city`, and `state` are required; `postalCode` is optional')
    ref_number: str | None = Field(None, max_length=500, description='Reference number. Auto-generated if not specified.')
    phone_number: str | None = Field(None, max_length=500, description='Phone number for the location')
    email: str | None = Field(None, max_length=500, description='Email address for the location')
    status: Literal['active', 'pending', 'inactive'] | None = Field(None, max_length=500, description='Location status, defaults to `active`')
    primary_contact_id: int | None = Field(None, ge=1, le=9223372036854775807, description='ID of contact to set as primary. Contact must belong to this location or company. `null` to clear.')


class ServiceTradeUpdateLocationConfig(_Input):
    'Update a location. Only supplied fields are sent.'
    operation: Literal['update_location'] = Field('update_location', json_schema_extra={"ui:hidden": True})
    location_id: int = Field(..., ge=1, le=9223372036854775807)
    name: str | None = Field(None, max_length=500, description='Location name')
    company_id: int | None = Field(None, ge=1, le=9223372036854775807, description='ID of the company this location belongs to')
    address: Address | None = Field(None, description='Address object containing `street`, `city`, `state`, and `postalCode` properties')
    ref_number: str | None = Field(None, max_length=500, description='Reference number')
    phone_number: str | None = Field(None, max_length=500, description='Phone number for the location')
    email: str | None = Field(None, max_length=500, description='Email address for the location')
    status: Literal['active', 'pending', 'inactive'] | None = Field(None, max_length=500, description='Location status')
    primary_contact_id: int | None = Field(None, ge=1, le=9223372036854775807, description='ID of contact to set as primary. Contact must belong to this location or company. `null` to clear.')

    @model_validator(mode="after")
    def change_required(self):
        changes = self.model_dump(exclude_none=True, exclude={"operation", "location_id"})
        if not changes:
            raise ValueError("Provide at least one field to update")
        return self


class ServiceTradeCreateJobConfig(_Input):
    'Create a new job. Only supplied fields are sent.'
    operation: Literal['create_job'] = Field('create_job', json_schema_extra={"ui:hidden": True})
    location_id: int = Field(..., ge=1, le=9223372036854775807, description='Location where the job will be performed')
    type: Literal['administrative', 'buildout', 'cleaning', 'construction', 'consultation', 'delivery', 'design', 'emergency_service_call', 'exchange', 'hookup', 'inspection', 'inspection_repair', 'installation', 'monitoring', 'pickup', 'planned_maintenance', 'preventative_maintenance', 'priority_inspection', 'priority_service_call', 'quality_assurance', 'reinspection', 'repair', 'replacement', 'retrofit', 'sales', 'service_call', 'start_up', 'survey', 'testing', 'training', 'unknown', 'upgrade', 'urgent_service_call', 'warranty'] = Field(..., min_length=1, max_length=500, description='Job type')
    custom_name: str | None = Field(None, max_length=500, description='Custom name for the job')
    description: str | None = Field(None, max_length=10000, description='Job description')
    customer_po: str | None = Field(None, max_length=40, description='Customer purchase order number')
    status: Literal['new', 'scheduled', 'canceled', 'bidding', 'completed', 'pending_invoice', 'sending_invoice', 'invoiced', 'closed'] | None = Field(None, max_length=500, description='Initial job status. `invoiced` is deprecated')
    percent_complete: int | None = Field(None, ge=0, le=100, description='Completion percentage (0-100), or `null` if unknown')
    owner_id: int | None = Field(None, ge=1, le=9223372036854775807, description='User ID of the job owner')
    service_request_ids: list[int] | None = Field(None, max_length=2000, description="Service request IDs to fulfill by this job (services must belong to the job's location)")


class ServiceTradeUpdateJobConfig(_Input):
    'Update a job. Only supplied fields are sent.'
    operation: Literal['update_job'] = Field('update_job', json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., ge=1, le=9223372036854775807)
    type: Literal['administrative', 'buildout', 'cleaning', 'construction', 'consultation', 'delivery', 'design', 'emergency_service_call', 'exchange', 'hookup', 'inspection', 'inspection_repair', 'installation', 'monitoring', 'pickup', 'planned_maintenance', 'preventative_maintenance', 'priority_inspection', 'priority_service_call', 'quality_assurance', 'reinspection', 'repair', 'replacement', 'retrofit', 'sales', 'service_call', 'start_up', 'survey', 'testing', 'training', 'unknown', 'upgrade', 'urgent_service_call', 'warranty'] | None = Field(None, max_length=500, description='Job type')
    custom_name: str | None = Field(None, max_length=500, description='Custom name for the job')
    description: str | None = Field(None, max_length=10000, description='Job description')
    customer_po: str | None = Field(None, max_length=40, description='Customer purchase order number')
    status: Literal['new', 'scheduled', 'canceled', 'bidding', 'completed', 'pending_invoice', 'sending_invoice', 'invoiced', 'closed'] | None = Field(None, max_length=500, description='Job status. `invoiced` is deprecated')
    percent_complete: int | None = Field(None, ge=0, le=100, description='Completion percentage (0-100), or `null` if unknown')
    owner_id: int | None = Field(None, ge=1, le=9223372036854775807, description='User ID of the job owner')
    service_request_ids: list[int] | None = Field(None, max_length=2000, description='Service request IDs to fulfill by this job')

    @model_validator(mode="after")
    def change_required(self):
        changes = self.model_dump(exclude_none=True, exclude={"operation", "job_id"})
        if not changes:
            raise ValueError("Provide at least one field to update")
        return self


class ServiceTradeCreateCommentConfig(_Input):
    'Create a comment. The entity type is the documented numeric constant (3 for a job).'
    operation: Literal['create_comment'] = Field('create_comment', json_schema_extra={"ui:hidden": True})
    entity_id: int = Field(..., ge=1, le=9223372036854775807, description='ID of the entity to comment on')
    entity_type: int = Field(..., ge=0, description='Entity type constant of the entity to comment on (see the list of [Entity Types](/api/docs/description/entity-types))')
    content: str = Field(..., min_length=1, max_length=10000, description='Text of the comment')
    visibility: list[Literal['public', 'schedule', 'tech', 'billing']] | None = Field(None, max_length=2000, description='Privacy level and context flags. For assets, only `public` and `tech` are accepted.')
    pinned: bool | None = Field(None, description='Set to `true` to pin the comment')


# Entity constants and delivery format: /api/docs/tag/webhook and /description/entity-types.
WEBHOOK_ENTITY_TYPES = {
    "job": 3, "invoice": 6, "quote": 9, "appointment": 16,
    "deficiency": 10, "company": 5, "contact": 22, "location": 11,
}


class ServiceTradeOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On ServiceTrade Event", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On ServiceTrade Event",
    })
    entity_type: Literal["job", "invoice", "quote", "appointment", "deficiency", "company", "contact", "location"] = Field(
        "job", title="Entity", description="The kind of record to watch. Requires ServiceTrade admin.account permission.")
    action: Literal["all", "created", "updated", "deleted"] = Field(
        "all", title="Action", description="Start on creation, update, deletion, or all three. Updates include available field changes.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with ServiceTrade automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


ServiceTradeConfig = Annotated[Union[
    ServiceTradeListCompaniesConfig,
    ServiceTradeGetCompanyConfig,
    ServiceTradeListContactsConfig,
    ServiceTradeGetContactConfig,
    ServiceTradeListLocationsConfig,
    ServiceTradeGetLocationConfig,
    ServiceTradeListJobsConfig,
    ServiceTradeGetJobConfig,
    ServiceTradeListAppointmentsConfig,
    ServiceTradeGetAppointmentConfig,
    ServiceTradeListQuotesConfig,
    ServiceTradeGetQuoteConfig,
    ServiceTradeListInvoicesConfig,
    ServiceTradeGetInvoiceConfig,
    ServiceTradeListDeficienciesConfig,
    ServiceTradeGetDeficiencyConfig,
    ServiceTradeCreateAppointmentConfig,
    ServiceTradeUpdateAppointmentConfig,
    ServiceTradeCreateContactConfig,
    ServiceTradeUpdateContactConfig,
    ServiceTradeCreateLocationConfig,
    ServiceTradeUpdateLocationConfig,
    ServiceTradeCreateJobConfig,
    ServiceTradeUpdateJobConfig,
    ServiceTradeCreateCommentConfig,
    ServiceTradeOnEventConfig
], Field(discriminator="operation")]


class ServiceTradeFullConfig(NodeConfig[ServiceTradeConfig, ServiceTradeSessionToken]):
    pass


ROUTES = {
    'list_companies': ('GET', '/company', 'companies'),
    'get_company': ('GET', '/company/{id}', None),
    'list_contacts': ('GET', '/contact', 'contacts'),
    'get_contact': ('GET', '/contact/{id}', None),
    'list_locations': ('GET', '/location', 'locations'),
    'get_location': ('GET', '/location/{id}', None),
    'list_jobs': ('GET', '/job', 'jobs'),
    'get_job': ('GET', '/job/{id}', None),
    'list_appointments': ('GET', '/appointment', 'appointments'),
    'get_appointment': ('GET', '/appointment/{id}', None),
    'list_quotes': ('GET', '/quote', 'quotes'),
    'get_quote': ('GET', '/quote/{id}', None),
    'list_invoices': ('GET', '/invoice', 'invoices'),
    'get_invoice': ('GET', '/invoice/{id}', None),
    'list_deficiencies': ('GET', '/deficiency', 'deficiencies'),
    'get_deficiency': ('GET', '/deficiency/{id}', None),
    'create_appointment': ('POST', '/appointment', None),
    'update_appointment': ('PUT', '/appointment/{id}', None),
    'create_contact': ('POST', '/contact', None),
    'update_contact': ('PUT', '/contact/{id}', None),
    'create_location': ('POST', '/location', None),
    'update_location': ('PUT', '/location/{id}', None),
    'create_job': ('POST', '/job', None),
    'update_job': ('PUT', '/job/{id}', None),
    'create_comment': ('POST', '/comment', None),
}

WIRE_FIELDS = {
    'postal_code': 'postalCode',
    'is_customer': 'isCustomer',
    'updated_after': 'updatedAfter',
    'updated_before': 'updatedBefore',
    'company_id': 'companyId',
    'location_id': 'locationId',
    'customer_id': 'customerId',
    'job_id': 'jobId',
    'asset_id': 'assetId',
    'service_request_ids': 'serviceRequestIds',
    'tech_ids': 'techIds',
    'window_start': 'windowStart',
    'window_end': 'windowEnd',
    'first_name': 'firstName',
    'last_name': 'lastName',
    'company_ids': 'companyIds',
    'location_ids': 'locationIds',
    'ref_number': 'refNumber',
    'phone_number': 'phoneNumber',
    'primary_contact_id': 'primaryContactId',
    'custom_name': 'customName',
    'customer_po': 'customerPo',
    'percent_complete': 'percentComplete',
    'owner_id': 'ownerId',
    'entity_id': 'entityId',
    'entity_type': 'entityType',
}

def _wire(value):
    if isinstance(value, dict):
        return {WIRE_FIELDS.get(k, k): _wire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_wire(v) for v in value]
    return value


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()
                if k.lower() not in {"authtoken", "phpsessid", "session_token", "password"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class ServiceTradeNode(ExternalWebhookTriggerMixin, WorkflowNode):
    webhook_signing_secret_not_issued = True
    integration_type = "automation-servicetrade"
    connection_evidence = ConnectionEvidence(noun="companies", operation="list_companies")

    @classmethod
    def get_config_model(cls):
        return ServiceTradeFullConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        parsed = cls.parse_config({"config": {"operation": "on_event", **(config or {})}}).config
        return {"entity_type": parsed.entity_type, "action": parsed.action}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        parsed = cls.parse_config({"config": {"operation": "on_event", **(config or {})}}).config
        token = ServiceTradeSessionToken.model_validate(credential).session_token
        actions = ["created", "updated", "deleted"] if parsed.action == "all" else [parsed.action]
        result = await cls._request(token, "POST", "/webhook", json={
            "hookUrl": webhook_url, "enabled": True, "includeChangesets": True,
            "entityEvents": [{"entityType": WEBHOOK_ENTITY_TYPES[parsed.entity_type], "actions": actions}],
        })
        if result["status"] != "success":
            raise ValueError(f"ServiceTrade webhook registration failed: {result.get('message')}")
        endpoint_id = result["data"].get("id")
        if type(endpoint_id) is not int or endpoint_id < 1:
            raise ValueError("ServiceTrade did not return a webhook ID")
        return {"external_webhook_id": str(endpoint_id)}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if endpoint_id is None:
            return
        if not re.fullmatch(r"[1-9][0-9]*", str(endpoint_id)):
            raise ValueError("Invalid ServiceTrade webhook ID")
        token = ServiceTradeSessionToken.model_validate(credential).session_token
        result = await cls._request(token, "DELETE", f"/webhook/{endpoint_id}")
        if result["status"] != "success" and result.get("http_status") != 404:
            raise ValueError(f"ServiceTrade webhook removal failed: {result.get('message')}")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # No signature or signing secret is defined in ServiceTrade's delivery contract.
        # The platform's unguessable per-node delivery URL is the capability.
        return True

    @classmethod
    def _matching_events(cls, payload, config):
        parsed = cls.parse_config({"config": {"operation": "on_event", **(config or {})}}).config
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        matches = []
        for event in data:
            if not isinstance(event, dict):
                continue
            entity = event.get("entity")
            if not isinstance(entity, dict) or entity.get("type") != parsed.entity_type:
                continue
            action = event.get("action")
            if action in {"created", "updated", "deleted"} and parsed.action in {"all", action}:
                matches.append(event)
        return matches

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return bool(cls._matching_events(payload, config))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        events = cls._matching_events(payload, config)
        return {"status": "success", "events": events, "event_count": len(events),
                "message_id": payload.get("messageId"), "timestamp": payload.get("timestamp")}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "events" not in output:
            return super().resolve_agent_event(output)
        events = output["events"]
        if not events:
            return None
        lines = []
        for event in events[:20]:
            entity = event["entity"]
            actor = f"user {event['userId']}" if "userId" in event and event["userId"] is not None else "system or unspecified user"
            line = f"- {entity['type']} {entity['id']} {event['action']} by {actor} at {event['timestamp']}: {entity['uri']}"
            if "changeset" in event:
                for change in event["changeset"]:
                    line += f"; {change['field']}: {change['oldValue']} → {change['newValue']}"
            lines.append(line)
        if len(events) > 20:
            lines.append(f"- … and {len(events) - 20} more events (see trigger output)")
        return {"text": "ServiceTrade record changes:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a ServiceTrade session token")
        config = self.config.config
        if isinstance(config, ServiceTradeOnEventConfig):
            payload = (self.node_data.get("config") or {}).get("_triggerPayload")
            if not payload:
                return self.no_event_output(config.operation)
            return self.resolve_trigger_payload(payload, config.model_dump())
        token = self.config.credentials.session_token
        method, route, collection = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in route:
            kind = route.split("/")[1]
            route = route.replace("{id}", str(values.pop(kind + "_id")))
        values = _wire(values)
        kwargs = {"params": {k: ("true" if v is True else "false" if v is False else v)
                             for k, v in values.items()}} if method == "GET" else {"json": values}
        result = await self._request(token, method, route, **kwargs)
        if result["status"] != "success":
            return result
        data = result["data"]
        if collection:
            if not isinstance(data, dict) or not isinstance(data.get(collection), list):
                raise ValueError("ServiceTrade response is missing its collection")
            page, total = data.get("page"), data.get("totalPages")
            if type(page) is not int or type(total) is not int or page < 1 or total < 0:
                raise ValueError("ServiceTrade returned invalid pagination metadata")
            result.update(items=data[collection], page=page, total_pages=total,
                          next_page=page + 1 if page < total else None)
        return result

    @staticmethod
    async def _request(token, method, route, **kwargs):
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, headers={
                    "Cookie": "PHPSESSID=" + token, "Accept": "application/json"}, **kwargs)
        except httpx.RequestError:
            raise ValueError("ServiceTrade request did not complete; a write may have taken effect. Check ServiceTrade before retrying.") from None
        if method == "DELETE" and response.status_code == 204:
            return {"status": "success", "data": None}
        if len(response.content) > 10000000:
            raise ValueError("ServiceTrade response exceeds the JSON size limit")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("ServiceTrade returned an unexpected response (expected JSON)") from None
        if not isinstance(body, dict):
            raise ValueError("ServiceTrade returned an unexpected JSON envelope")
        messages = body.get("messages") or {}
        if not isinstance(messages, dict):
            raise ValueError("ServiceTrade returned an unexpected messages envelope")
        if not 200 <= response.status_code < 300 or messages.get("error") or messages.get("validation"):
            errors = messages.get("error") or messages.get("validation") or "ServiceTrade rejected the request"
            return _redact({"status": "error", "http_status": response.status_code,
                "message": errors, "messages": messages}, token)
        data = body.get("data")
        # The response contract documents data as the common envelope; never follow
        # returned URLs or interpret absent data as an empty successful collection.
        if not isinstance(data, (dict, list)):
            raise ValueError("ServiceTrade response is missing its data object")
        return _redact({"status": "success", "data": data}, token)
