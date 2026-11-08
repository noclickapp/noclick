"""Workiz v2 API. Contract: https://developer.workiz.com/v2/openapi.json (2.0)."""
from __future__ import annotations
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence

class WorkizTokenCredential(BaseModel):
    model_config = ConfigDict(title="Workiz API Token", json_schema_extra={
        "x-credential-url": "https://developer.workiz.com/v2/",
        "x-credential-instructions": "Paste your Workiz v2 API token. It is sent as a Bearer token; omit the Bearer prefix. The key needs permission for the operations you use, including reading clients to verify the connection."})
    credential_type: Literal["workiz_api_token"] = Field("workiz_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if any(c.isspace() for c in value) or value.lower().startswith(("bearer ", "https://", "http://")):
            raise ValueError("Paste only the Workiz API token")
        return value

class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ListClients(_Model):
    operation: Literal['list_clients'] = Field('list_clients', title='List Clients', json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(50, ge=1, description='Number of records to return per page.')
    page: int = Field(1, ge=1, description='The page index. `page * pageSize` must be less than 10000; use filters (e.g. a date range) to reach clients beyond that point.')
    searchQuery: str | None = Field(None, description='Free-text search string matched against full name, company name, full address, parent full name, custom fields, primary phone, and email address.')
    isDue: Literal['PastDue', 'Due'] | None = Field(None, description='Filter clients by outstanding balance status. `Due` returns clients with any open balance; `PastDue` returns clients whose balance is overdue.')
    tags: str | None = Field(None, description='Comma-separated list of tag IDs to filter by. Only clients that have **all** specified tags are returned.')
    field: Literal['serialId', 'firstName', 'fullName', 'clientCompany', 'primaryPhone'] | None = Field(None, description='Field to sort results by. When omitted the default sort is by `serialId` descending.')
    order: Literal['ASC', 'DESC'] | None = Field(None, description='Sort direction. Defaults to `DESC`.')
    dateProperty: Literal['created'] | None = Field(None, description='The client date field to apply the date filter to. Must be combined with `dateOperator` and `date`.')
    dateOperator: Literal['prev', 'next', 'between'] | None = Field(None, description='Comparison operator for the date filter. Must be combined with `dateProperty` and `date`.')
    date: str | None = Field(None, description='Date value(s) for the filter. Format depends on `dateOperator`: `prev` / `next` accept a single date (`YYYY-MM-DD`); `between` accepts two dates separated by `_` (`YYYY-MM-DD_YYYY-MM-DD`).')

class GetClient(_Model):
    operation: Literal['get_client'] = Field('get_client', title='Get Client', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The client ID (prefix `CL-`).')

class CreateClientAddressDetailsV2Dto(_Model):
    country: str | None = Field(None, description='The country of the address.')
    state: str | None = Field(None, description='The state of the address.')
    city: str | None = Field(None, description='The city of the address.')
    zipCode: str | None = Field(None, description='The ZIP code of the address.')
    address: str | None = Field(None, description='The street address.')
    unit: str | None = Field(None, description='The unit or suite number.')

class CustomFieldValueV2Dto(_Model):
    id: str = Field(..., description='The ID of the custom field (prefix `CF-`).')
    value: str = Field(..., description='The value of the custom field.')

class CreateClientV2Dto(_Model):
    firstName: str = Field(..., description='The first name of the client.')
    lastName: str | None = Field(None, description='The last name of the client.')
    companyName: str | None = Field(None, description='The company name of the client.')
    email: str | None = Field(None, description='The email address of the client. Either email or primaryPhone must be provided.')
    primaryExt: str | None = Field(None, description='The extension number for the primary phone number.')
    primaryPhone: str | None = Field(None, description='The primary phone number of the client. Either email or primaryPhone must be provided.')
    secondaryExt: str | None = Field(None, description='The extension number for the secondary phone number.')
    secondaryPhone: str | None = Field(None, description='The secondary phone number of the client.')
    addressDetails: CreateClientAddressDetailsV2Dto | None = Field(None, description='The service address details of the client. When provided, a service location is created for the client.')
    billingAddressDetails: CreateClientAddressDetailsV2Dto | None = Field(None, description='The billing address details of the client. When different from the service address, a separate billing location is created.')
    adGroupId: str | None = Field(None, description='The ID of the ad group (prefix `AG-`).')
    allowBilling: bool | None = Field(None, description='Whether the client allows billing. Defaults to the account-level setting when omitted.')
    parentClientId: str | None = Field(None, description='The ID of the parent client (prefix `CL-`). The created client is set as a sub-client of it.')
    taxExempt: bool | None = Field(None, description='Whether the client is tax exempt.')
    taxExemptReason: Literal['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15', '99'] | None = Field(None, description='The tax exemption reason code. Can only be provided when taxExempt is true; defaults to `99` (Other) when taxExempt is true and no reason is provided. Allowed values: `1` = Federal Government, `2` = State Government, `3` = Local Government, `4` = Tribal Government, `5` = Charitable Organization, `6` = Religious Organization, `7` = Educational Organization, `8` = Hospital, `9` = Resale, `10` = Direct Pay Permit, `11` = Multiple Points Of Use, `12` = Direct Mail, `13` = Agricultural Production, `14` = Industrial Production / Manufacturing, `15` = Foreign Diplomat, `99` = Other.')
    description: str | None = Field(None, description='The description of the client.')
    customFields: list[CustomFieldValueV2Dto] | None = Field(None, description='The custom fields of the client.')

class CreateClient(CreateClientV2Dto):
    operation: Literal['create_client'] = Field('create_client', title='Create Client', json_schema_extra={"ui:hidden": True})

class ListJobs(_Model):
    operation: Literal['list_jobs'] = Field('list_jobs', title='List Jobs', json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(50, ge=1, description='Number of records to return per page.')
    page: int = Field(1, ge=1, description='The page index.')
    field: Literal['created', 'updated', 'statusUpdated', 'utcUpdated'] | None = Field(None, description='The field to sort results by. Must be combined with `order`.')
    order: Literal['ASC', 'DESC'] | None = Field(None, description='The sort direction. Must be combined with `field`.')
    isOpen: bool | None = Field(None, description='When true, returns only open jobs. When false, returns only closed (Canceled or Done) jobs. When omitted, no status filter is applied.')
    dateProperty: Literal['date', 'endDate', 'utcUpdated', 'updated', 'created'] | None = Field(None, description='The job date field to apply the date filter to. Must be combined with `dateOperator` and `date`. When these date filter params are omitted, results default to the last 30 days by scheduled date (`date`).')
    dateOperator: Literal['prev', 'next', 'between'] | None = Field(None, description='Comparison operator for the date filter. Must be combined with `dateProperty` and `date`.')
    date: str | None = Field(None, description='Date value(s) for the filter. Format depends on `dateOperator`: `prev` / `next` accept a single date (`YYYY-MM-DD`); `between` accepts two dates separated by `_` (`YYYY-MM-DD_YYYY-MM-DD`).')

class GetJob(_Model):
    operation: Literal['get_job'] = Field('get_job', title='Get Job', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The job ID (prefix `JOB-`).')

class CreateUpdateAddressDetailsV2Dto(_Model):
    country: str | None = Field(None, description='The country of the address.')
    state: str | None = Field(None, description='The state of the address.')
    city: str | None = Field(None, description='The city of the address.')
    zipCode: str | None = Field(None, description='The ZIP code of the address.')
    address: str | None = Field(None, description='The street address.')
    unit: str | None = Field(None, description='The unit or suite number.')

class CreateClientInfoV2Dto(_Model):
    clientId: str | None = Field(None, description='The ID of the client (prefix `CL-`). Used to fill in any missing fields from the existing client record.')
    firstName: str | None = Field(None, description='The first name of the client. Required when clientId is not provided.')
    lastName: str | None = Field(None, description='The last name of the client.')
    email: str | None = Field(None, description='The email address of the client. Required when clientId is not provided and primaryPhone is not provided.')
    companyName: str | None = Field(None, description='The company name of the client.')
    primaryExt: str | None = Field(None, description='The extension number for the primary phone number.')
    primaryPhone: str | None = Field(None, description='The primary phone number of the client. Required when clientId is not provided and email is not provided.')
    secondaryExt: str | None = Field(None, description='The extension number for the secondary phone number.')
    secondaryPhone: str | None = Field(None, description='The secondary phone number of the client.')
    addressDetails: CreateUpdateAddressDetailsV2Dto | None = Field(None, description='The address details of the client.')

class CreateJobV2Dto(_Model):
    date: str | None = Field(None, description='The scheduled start date and time for the job (Must be before the endDate). Required when isScheduled is true. Note: Both dates are rounded to the nearest quarter hour (0, 15, 30, 45 minutes) for validation.')
    endDate: str | None = Field(None, description='The scheduled end date and time for the job (Must be after the start date). Required when isScheduled is true. Note: Both dates are rounded to the nearest quarter hour (0, 15, 30, 45 minutes) for validation.')
    isAllDay: bool | None = Field(None, description='> **Beta:** This property is subject to change.\n\nWhether the job is an all-day event. Defaults to false.')
    isScheduled: bool | None = Field(None, description='> **Beta:** This property is subject to change.\n\nWhether the job is scheduled. When false, the job is created as unscheduled and date/endDate become optional. Defaults to true.')
    name: str | None = Field(None, description='The name of the job.')
    description: str | None = Field(None, description='The description of the job.')
    timeZone: str | None = Field(None, description='The timezone of the job.')
    jobTypeId: str = Field(..., description='The ID of the job type (prefix `JT-`).')
    adGroupId: str | None = Field(None, description='The ID of the ad group (prefix `AG-`).')
    clientInfo: CreateClientInfoV2Dto = Field(..., description='The client information including address details.')
    createdBy: str | None = Field(None, description='The ID of the user who created the job (prefix `USR-`).')
    createdDate: str | None = Field(None, description='The date and time when the job record was created. If not provided, defaults to the current timestamp.')
    customFields: list[CustomFieldValueV2Dto] | None = Field(None, description='The custom fields of the job.')

class CreateJob(CreateJobV2Dto):
    operation: Literal['create_job'] = Field('create_job', title='Create Job', json_schema_extra={"ui:hidden": True})

class UpdateClientInfoV2Dto(_Model):
    firstName: str | None = Field(None, description='The first name of the client (required when clientId is not provided).')
    lastName: str | None = Field(None, description='The last name of the client.')
    email: str | None = Field(None, description='The email address of the client (required when clientId is not provided).')
    companyName: str | None = Field(None, description='The company name of the client.')
    primaryExt: str | None = Field(None, description='The extension number for the primary phone number.')
    primaryPhone: str | None = Field(None, description='The primary phone number of the client.')
    secondaryExt: str | None = Field(None, description='The extension number for the secondary phone number.')
    secondaryPhone: str | None = Field(None, description='The secondary phone number of the client.')
    addressDetails: CreateUpdateAddressDetailsV2Dto | None = Field(None, description='The address details of the client.')

class UpdateJobV2Dto(_Model):
    status: Literal['Submitted', 'In progress', 'Pending', 'done pending approval', 'Canceled', 'Done'] | None = Field(None, description='The status of the job.')
    subStatusId: str | None = Field(None, description='The ID of the job sub status (prefix `JSS-`).')
    date: str | None = Field(None, description='The scheduled start date and time for the job (Must be before the endDate). Note: Both dates are rounded to the nearest quarter hour (0, 15, 30, 45 minutes) for validation.')
    endDate: str | None = Field(None, description='The scheduled end date and time for the job (Must be after the start date). Note: Both dates are rounded to the nearest quarter hour (0, 15, 30, 45 minutes) for validation.')
    isAllDay: bool | None = Field(None, description='> **Beta:** This property is subject to change.\n\nWhether the job is an all-day event. When omitted, the current value is left unchanged.')
    isScheduled: bool | None = Field(None, description='> **Beta:** This property is subject to change.\n\nWhether the job is scheduled. When false, the job is marked as unscheduled. When omitted, the current schedule state is left unchanged.')
    name: str | None = Field(None, description='The name of the job.')
    description: str | None = Field(None, description='The description of the job.')
    timeZone: str | None = Field(None, description='The timezone of the job.')
    jobTypeId: str | None = Field(None, description='The ID of the job type (prefix `JT-`).')
    adGroupId: str | None = Field(None, description='The ID of the ad group (prefix `AG-`).')
    clientInfo: UpdateClientInfoV2Dto | None = Field(None, description='The client information including address details.')
    createdBy: str | None = Field(None, description='The ID of the user who created the job (prefix `USR-`).')
    tags: list[str] | None = Field(None, description='Array of tag IDs to assign to the job (prefix `TAG-`).')
    customFields: list[CustomFieldValueV2Dto] | None = Field(None, description='The custom fields of the job.')

class UpdateJob(UpdateJobV2Dto):
    operation: Literal['update_job'] = Field('update_job', title='Update Job', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The job ID (prefix `JOB-`).')

class ListLeads(_Model):
    operation: Literal['list_leads'] = Field('list_leads', title='List Leads', json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(50, ge=1, description='Number of records to return per page.')
    page: int = Field(1, ge=1, description='The page index.')
    field: Literal['created', 'updated', 'statusUpdated', 'utcUpdated'] | None = Field(None, description='The field to sort results by. Must be combined with `order`.')
    order: Literal['ASC', 'DESC'] | None = Field(None, description='The sort direction. Must be combined with `field`.')
    isOpen: bool | None = Field(None, description='When true, returns only open (not lost) leads. When false, returns only lost leads. When omitted, no filter is applied.')
    dateProperty: Literal['date', 'endDate', 'utcUpdated', 'updated', 'created'] | None = Field(None, description='The lead date field to apply the date filter to. Must be combined with `dateOperator` and `date`. When these date filter params are omitted, results default to the last 30 days by scheduled date (`date`).')
    dateOperator: Literal['prev', 'next', 'between'] | None = Field(None, description='Comparison operator for the date filter. Must be combined with `dateProperty` and `date`.')
    date: str | None = Field(None, description='Date value(s) for the filter. Format depends on `dateOperator`: `prev` / `next` accept a single date (`YYYY-MM-DD`); `between` accepts two dates separated by `_` (`YYYY-MM-DD_YYYY-MM-DD`).')

class GetLead(_Model):
    operation: Literal['get_lead'] = Field('get_lead', title='Get Lead', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The lead ID (prefix `LD-`).')

class CreateLeadV2Dto(_Model):
    date: str | None = Field(None, description='The scheduled start date and time for the lead (Must be before the endDate). Required when isScheduled is true. Note: Both dates are rounded to the nearest quarter hour (0, 15, 30, 45 minutes) for validation.')
    endDate: str | None = Field(None, description='The scheduled end date and time for the lead (Must be after the start date). Required when isScheduled is true. Note: Both dates are rounded to the nearest quarter hour (0, 15, 30, 45 minutes) for validation.')
    isAllDay: bool | None = Field(None, description='> **Beta:** This property is subject to change.\n\nWhether the lead is an all-day event. Defaults to false.')
    isScheduled: bool | None = Field(None, description='> **Beta:** This property is subject to change.\n\nWhether the lead is scheduled. When false, the lead is created as unscheduled and date/endDate become optional. Defaults to true.')
    description: str | None = Field(None, description='The description of the lead.')
    timeZone: str | None = Field(None, description='The timezone of the lead.')
    jobTypeId: str | None = Field(None, description='The ID of the job type (prefix `JT-`).')
    adGroupId: str | None = Field(None, description='The ID of the ad group (prefix `AG-`).')
    clientInfo: CreateClientInfoV2Dto = Field(..., description='The client information including address details.')
    createdBy: str | None = Field(None, description='The ID of the user who created the lead (prefix `USR-`).')
    createdDate: str | None = Field(None, description='The date and time when the lead record was created. If not provided, defaults to the current timestamp.')
    customFields: list[CustomFieldValueV2Dto] | None = Field(None, description='The custom fields of the lead.')

class CreateLead(CreateLeadV2Dto):
    operation: Literal['create_lead'] = Field('create_lead', title='Create Lead', json_schema_extra={"ui:hidden": True})

class UpdateLeadV2Dto(_Model):
    status: Literal['new', 'scheduled', 'in progress', 'estimated', 'approved', 'and any user-defined status'] | None = Field(None, description='The status of the lead.')
    date: str | None = Field(None, description='The scheduled start date and time for the lead (Must be before the endDate). Note: Both dates are rounded to the nearest quarter hour (0, 15, 30, 45 minutes) for validation.')
    endDate: str | None = Field(None, description='The scheduled end date and time for the lead (Must be after the start date). Note: Both dates are rounded to the nearest quarter hour (0, 15, 30, 45 minutes) for validation.')
    isAllDay: bool | None = Field(None, description='> **Beta:** This property is subject to change.\n\nWhether the lead is an all-day event. When omitted, the current value is left unchanged.')
    isScheduled: bool | None = Field(None, description='> **Beta:** This property is subject to change.\n\nWhether the lead is scheduled. When false, the lead is marked as unscheduled. When omitted, the current schedule state is left unchanged.')
    description: str | None = Field(None, description='The description of the lead.')
    timeZone: str | None = Field(None, description='The timezone of the lead.')
    jobTypeId: str | None = Field(None, description='The ID of the job type (prefix `JT-`). Pass an empty value to remove the job type from the lead.')
    adGroupId: str | None = Field(None, description='The ID of the ad group (prefix `AG-`).')
    clientInfo: UpdateClientInfoV2Dto | None = Field(None, description='The client information including address details.')
    createdBy: str | None = Field(None, description='The ID of the user who created the lead (prefix `USR-`).')
    tags: list[str] | None = Field(None, description='Array of tag IDs to assign to the lead (prefix `TAG-`).')
    customFields: list[CustomFieldValueV2Dto] | None = Field(None, description='The custom fields of the lead.')

class UpdateLead(UpdateLeadV2Dto):
    operation: Literal['update_lead'] = Field('update_lead', title='Update Lead', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The lead ID (prefix `LD-`).')

class ListUsers(_Model):
    operation: Literal['list_users'] = Field('list_users', title='List Users', json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(50, ge=1, description='Number of records to return per page.')
    page: int = Field(1, ge=1, description='The page index.')

class GetUser(_Model):
    operation: Literal['get_user'] = Field('get_user', title='Get User', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The user ID (prefix `USR-`).')

class ListInvoices(_Model):
    operation: Literal['list_invoices'] = Field('list_invoices', title='List Invoices', json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(50, ge=1, description='Number of records to return per page.')
    page: int = Field(1, ge=1, description='The page index.')
    field: Literal['created'] | None = Field(None, description='> **Beta:** This property is subject to change.\n\nThe field to sort results by. Must be combined with `order`. Defaults to `created`.')
    order: Literal['ASC', 'DESC'] | None = Field(None, description='> **Beta:** This property is subject to change.\n\nThe sort direction. Must be combined with `field`. Defaults to `DESC`.')
    isDue: Literal['Due', 'PastDue'] | None = Field(None, description='Filter invoices by outstanding balance status. `Due` returns invoices with any open balance, overdue included; `PastDue` returns invoices whose due date has passed and still have an open balance.')
    dateProperty: Literal['updated', 'created'] | None = Field(None, description='The invoice date field to apply the date filter to. Must be combined with `dateOperator` and `date`.')
    dateOperator: Literal['prev', 'next', 'between'] | None = Field(None, description='Comparison operator for the date filter. Must be combined with `dateProperty` and `date`.')
    date: str | None = Field(None, description='Date value(s) for the filter. Format depends on `dateOperator`: `prev` / `next` accept a single date (`YYYY-MM-DD`); `between` accepts two dates separated by `_` (`YYYY-MM-DD_YYYY-MM-DD`).')

class GetInvoice(_Model):
    operation: Literal['get_invoice'] = Field('get_invoice', title='Get Invoice', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The invoice ID (prefix `IV-`).')

class ListItems(_Model):
    operation: Literal['list_items'] = Field('list_items', title='List Items', json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(50, ge=1, description='Number of records to return per page.')
    page: int = Field(1, ge=1, description='The page index.')
    field: str | None = Field(None, description='The field to sort by. Allowed values: serialId, name, price, cost, updated. Must be combined with order. Defaults to serialId descending.')
    order: str | None = Field(None, description='The sort direction. Allowed values: ASC, DESC. Must be combined with field.')
    serialId: str | None = Field(None, description='Filter items by serial ID. Accepts a comma separated list of up to 300 values.')
    categoryId: str | None = Field(None, description='Filter items by category ID (prefix `ITC-`).')
    type: Literal['service', 'product', 'hours', 'expense', 'equipment', 'warranty'] | None = Field(None, description='Filter items by type.')
    active: bool | None = Field(None, description='Filter items by whether they are active.')
    inventoryManaged: bool | None = Field(None, description='Filter items by whether their inventory is managed.')
    booking: bool | None = Field(None, description='Filter items by whether they are available in online booking.')
    dateProperty: str | None = Field(None, description='The date property to filter by. Allowed values: updated.')
    dateOperator: str | None = Field(None, description='The date comparison to apply. Allowed values: prev, next, between.')
    date: str | None = Field(None, description='The date to filter by, as `YYYY-MM-DD`, or `YYYY-MM-DD_YYYY-MM-DD` for the between operator.')

class GetItem(_Model):
    operation: Literal['get_item'] = Field('get_item', title='Get Item', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The item ID (prefix `ITM-`).')

class ListClientNotes(_Model):
    operation: Literal['list_client_notes'] = Field('list_client_notes', title='List Client Notes', json_schema_extra={"ui:hidden": True})
    clientId: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The client ID (prefix `CL-`).')
    pageSize: int = Field(50, ge=1, description='Number of records to return per page.')
    page: int = Field(1, ge=1, description='The page index.')

class CreateClientNoteV2Dto(_Model):
    note: str = Field(..., description='The note content.')
    pin: bool | None = Field(None, description='Whether the note is pinned to the top of the list.')

class CreateClientNote(CreateClientNoteV2Dto):
    operation: Literal['create_client_note'] = Field('create_client_note', title='Create Client Note', json_schema_extra={"ui:hidden": True})
    clientId: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The client ID (prefix `CL-`).')

class UpdateClientNoteV2Dto(_Model):
    note: str | None = Field(None, description='The note content.')
    pin: bool | None = Field(None, description='Whether the note is pinned to the top of the list.')

class UpdateClientNote(UpdateClientNoteV2Dto):
    operation: Literal['update_client_note'] = Field('update_client_note', title='Update Client Note', json_schema_extra={"ui:hidden": True})
    clientId: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The client ID (prefix `CL-`).')
    noteId: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The client note ID (prefix `CLN-`).')

class DeleteClientNote(_Model):
    operation: Literal['delete_client_note'] = Field('delete_client_note', title='Delete Client Note', json_schema_extra={"ui:hidden": True})
    clientId: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The client ID (prefix `CL-`).')
    noteId: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The client note ID (prefix `CLN-`).')

class ConvertLead(_Model):
    operation: Literal['convert_lead'] = Field('convert_lead', title='Convert Lead', json_schema_extra={"ui:hidden": True})
    leadId: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description='The lead ID (prefix `LD-`).')

class ListJobTypes(_Model):
    operation: Literal['list_job_types'] = Field('list_job_types', title='List Job Types', json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(50, ge=1, description='Number of records to return per page.')
    page: int = Field(1, ge=1, description='The page index.')
    disabled: bool | None = Field(None, description='Filter by disabled state. When true, returns only disabled job types; when false, returns only enabled job types.')

Operation = Annotated[Union[ListClients, GetClient, CreateClient, ListJobs, GetJob, CreateJob, UpdateJob, ListLeads, GetLead, CreateLead, UpdateLead, ListUsers, GetUser, ListInvoices, GetInvoice, ListItems, GetItem, ListClientNotes, CreateClientNote, UpdateClientNote, DeleteClientNote, ConvertLead, ListJobTypes], Field(discriminator="operation")]

class WorkizNodeConfig(NodeConfig[Operation, WorkizTokenCredential]):
    pass

ROUTES = {'list_clients': ('GET',
                  '/v2/clients',
                  [],
                  ['pageSize',
                   'page',
                   'searchQuery',
                   'isDue',
                   'tags',
                   'field',
                   'order',
                   'dateProperty',
                   'dateOperator',
                   'date']),
 'get_client': ('GET', '/v2/clients/{id}', ['id'], []),
 'create_client': ('POST', '/v2/clients', [], []),
 'list_jobs': ('GET',
               '/v2/jobs',
               [],
               ['pageSize',
                'page',
                'field',
                'order',
                'isOpen',
                'dateProperty',
                'dateOperator',
                'date']),
 'get_job': ('GET', '/v2/jobs/{id}', ['id'], []),
 'create_job': ('POST', '/v2/jobs', [], []),
 'update_job': ('PUT', '/v2/jobs/{id}', ['id'], []),
 'list_leads': ('GET',
                '/v2/leads',
                [],
                ['pageSize',
                 'page',
                 'field',
                 'order',
                 'isOpen',
                 'dateProperty',
                 'dateOperator',
                 'date']),
 'get_lead': ('GET', '/v2/leads/{id}', ['id'], []),
 'create_lead': ('POST', '/v2/leads', [], []),
 'update_lead': ('PUT', '/v2/leads/{id}', ['id'], []),
 'list_users': ('GET', '/v2/users', [], ['pageSize', 'page']),
 'get_user': ('GET', '/v2/users/{id}', ['id'], []),
 'list_invoices': ('GET',
                   '/v2/invoices',
                   [],
                   ['pageSize',
                    'page',
                    'field',
                    'order',
                    'isDue',
                    'dateProperty',
                    'dateOperator',
                    'date']),
 'get_invoice': ('GET', '/v2/invoices/{id}', ['id'], []),
 'list_items': ('GET',
                '/v2/items',
                [],
                ['pageSize',
                 'page',
                 'field',
                 'order',
                 'serialId',
                 'categoryId',
                 'type',
                 'active',
                 'inventoryManaged',
                 'booking',
                 'dateProperty',
                 'dateOperator',
                 'date']),
 'get_item': ('GET', '/v2/items/{id}', ['id'], []),
 'list_client_notes': ('GET', '/v2/clients/{clientId}/notes', ['clientId'], ['pageSize', 'page']),
 'create_client_note': ('POST', '/v2/clients/{clientId}/notes', ['clientId'], []),
 'update_client_note': ('PUT', '/v2/clients/{clientId}/notes/{noteId}', ['clientId', 'noteId'], []),
 'delete_client_note': ('DELETE',
                        '/v2/clients/{clientId}/notes/{noteId}',
                        ['clientId', 'noteId'],
                        []),
 'convert_lead': ('POST', '/v2/leads/{leadId}/convert', ['leadId'], []),
 'list_job_types': ('GET', '/v2/jobtypes', [], ['pageSize', 'page', 'disabled'])}

class WorkizNode(WorkflowNode):
    integration_type = "automation-workiz"
    connection_evidence = ConnectionEvidence(operation="list_clients", noun="clients", label_keys=("fullName", "firstName", "companyName", "id"))
    edit_examples = ["Create a Workiz job for this client", "List open jobs", "Convert this lead to a job"]

    @classmethod
    def get_config_model(cls):
        return WorkizNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        return TypeAdapter(WorkizNodeConfig).validate_python(runtime_config_view(config_data, WorkizNodeConfig))

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Workiz API token")
        config = self.config.config
        method, path, path_fields, query_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for field in path_fields:
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = {k: values[k] for k in query_fields if k in values}
        body = {k: v for k, v in values.items() if k not in {*path_fields, *query_fields, "operation"}}
        token = self.config.credentials.api_token
        # One operation, one request. No automatic retries of mutations.
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, "https://api.workiz.com/crm/api" + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if method in {"POST", "PUT"} and body else {}))
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json().get("message", "Workiz request failed")
            except (ValueError, AttributeError):
                detail = "Workiz request failed"
            return {"status": "error", "http_status": response.status_code, "error": str(detail).replace(token, "[redacted]")}
        if response.status_code == 204:
            return {"status": "success", "data": None}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "error": "Workiz returned invalid JSON"}
        if not isinstance(data, (dict, list)):
            return {"status": "error", "error": "Workiz returned an unexpected response"}
        if isinstance(data, dict) and (data.get("error") or data.get("statusCode", 200) >= 400):
            return {"status": "error", "error": str(data.get("message", "Workiz request failed")).replace(token, "[redacted]")}
        # Preserve provider pagination (page, pageSize, hasMore, totalResults).
        return {"status": "success", "data": data}
