"""Easybizy customers, leads, activities, scheduling and invoices.

Requests follow the provider's public OpenAPI 1.4.35 contract. Poll triggers
use its timeUpdated filter and baseline records before emitting changes.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.easybizy.net"
DOCS_URL = "https://api.easybizy.net/documentation"


class EasybizyCredential(BaseModel):
    model_config = ConfigDict(title="Easybizy API Key and Secret", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS_URL,
            "x-credential-instructions": "An account owner must enable API access in Easybizy's API documentation panel, copy the API key and secret, and grant read/create/update/delete permissions for the entities you use. Paste both values below.",
        })
    credential_type: Literal["easybizy_api_key"] = Field("easybizy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="API Secret", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value)
        if any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
            raise ValueError("Paste the API value without spaces or control characters")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EasybizyCustomerCreate(_Input):
    mobile: str = Field(..., title='Mobile', description='Primary mobile number.')
    firstName: str = Field(..., title='First Name', description='First name.')
    lastName: str | None = Field(None, title='Last Name', description='Last name.')
    email: str | None = Field(None, title='Email', description='Email address.')
    dateOfBirth: date | None = Field(None, title='Date Of Birth', description='Date of birth. A calendar date — no time of day, no timezone.')
    identificationNumber: str | None = Field(None, title='Identification Number', description='National ID or custom membership id. Not unique.')
    remarks: str | None = Field(None, title='Remarks', description='Free-text remarks.')
    gender: Literal['male', 'female'] | None = Field(None, title='Gender', description='Either `male` or `female`. A record created without it is `female`.')
    optInForMarketing: bool = Field(False, title='Opt In For Marketing', description='Mobile/SMS marketing consent. Omitting it defaults to false, opting the customer OUT of SMS marketing.')
    arrivalSource: str | None = Field(None, title='Arrival Source', description='Arrival source by name (created if new).')
    tags: list[str] | None = Field(None, title='Tags', description='Customer tags by name (created if new; full set is reconciled).')


class EasybizyCustomerPatch(_Input):
    mobile: str | None = Field(None, title='Mobile', description='Primary mobile number.')
    firstName: str | None = Field(None, title='First Name', description='First name.')
    lastName: str | None = Field(None, title='Last Name', description='Last name.')
    email: str | None = Field(None, title='Email', description='Email address.')
    dateOfBirth: date | None = Field(None, title='Date Of Birth', description='Date of birth. A calendar date — no time of day, no timezone.')
    identificationNumber: str | None = Field(None, title='Identification Number', description='National ID or custom membership id. Not unique.')
    remarks: str | None = Field(None, title='Remarks', description='Free-text remarks.')
    gender: Literal['male', 'female'] | None = Field(None, title='Gender', description='Either `male` or `female`. A record created without it is `female`.')
    optInForMarketing: bool | None = Field(None, title='Opt In For Marketing', description='Mobile/SMS marketing consent. Omitting it defaults to false, opting the customer OUT of SMS marketing.')
    arrivalSource: str | None = Field(None, title='Arrival Source', description='Arrival source by name (created if new).')
    tags: list[str] | None = Field(None, title='Tags', description='Customer tags by name (created if new; full set is reconciled).')


class EasybizyLeadRequest(_Input):
    fullName: str | None = Field(None, title='Full Name', description='Full name of the lead.')
    firstName: str | None = Field(None, title='First Name', description='The first name, will Overcome the full name if set.')
    lastName: str | None = Field(None, title='Last Name', description='The first name, will Overcome the full name if set.')
    generatedNameIfMissing: bool = Field(False, title='Generated Name If Missing', description='When true, if neither fullName nor firstName is provided, the phone or email will be used instead.')
    mobile: str | None = Field(None, title='Mobile')
    email: str | None = Field(None, title='Email')
    remarks: str | None = Field(None, title='Remarks')
    createdOn: date | None = Field(None, title='Created On')
    dateOfBirth: date | None = Field(None, title='Date Of Birth')
    gender: Literal['male', 'female'] | None = Field(None, title='Gender', description='Either male or female. Defaults to female for a new lead; an existing lead keeps its own.')
    tagStr: str | None = Field(None, title='Tag Str', description='Comma separated tags')
    arrivalSource: str | None = Field(None, title='Arrival Source')
    address: str | None = Field(None, title='Address')
    utm: str | None = Field(None, title='Utm')
    ignoreTriggers: bool = Field(False, title='Ignore Triggers')
    optInForMarketing: bool | None = Field(None, title='Opt In For Marketing', description='When true, it indicates user has voluntarily agreed to receive promotional communications.')


class EasybizyLeadPatch(_Input):
    mobile: str | None = Field(None, title='Mobile', description='Primary mobile number.')
    firstName: str | None = Field(None, title='First Name', description='First name.')
    lastName: str | None = Field(None, title='Last Name', description='Last name.')
    email: str | None = Field(None, title='Email', description='Email address.')
    dateOfBirth: date | None = Field(None, title='Date Of Birth', description='Date of birth. A calendar date — no time of day, no timezone.')
    gender: Literal['male', 'female'] | None = Field(None, title='Gender', description='Either `male` or `female`. A record created without it is `female`.')
    remarks: str | None = Field(None, title='Remarks', description='Free-text remarks.')
    address: str | None = Field(None, title='Address', description='Address.')
    utm: str | None = Field(None, title='Utm', description='Campaign UTM parameters.')
    optInForMarketing: bool | None = Field(None, title='Opt In For Marketing', description='Mobile/SMS marketing consent. When true the lead has voluntarily agreed to receive promotional communications.')
    arrivalSource: str | None = Field(None, title='Arrival Source', description='Arrival source by name (created if new).')
    status: Literal['new', 'active', 'suspended', 'inactive', 'became_a_customer', 'meeting_scheduled', 'meeting_held', 'meeting_cancelled', 'deal_closed'] | None = Field(None, title='Status', description='Where the lead stands in the pipeline. One of: *new*, *active*, *suspended*, *inactive*, *became_a_customer*, *meeting_scheduled*, *meeting_held*, *meeting_cancelled*, *deal_closed*. Writable — but the pipeline also moves it on its own (a booked meeting, a closed deal, a manual move on the leads board), so what you set is the current standing and not a lock.')
    subStatus: str | None = Field(None, title='Sub Status', description="The business's own sub-status for the lead, by name — the values are whatever that account defined, so they vary between businesses. *null* when the lead has none set. Writable by that same name: it must be one the account has already defined (anything else is a **400** listing the ones that exist — a write never invents a new sub-status), and *null* clears it.")
    tags: list[str] | None = Field(None, title='Tags', description='Lead tags by name (created if new; full set is reconciled).')


class EasybizyActivityInfoRequest(_Input):
    content: str = Field(..., title='Content', description="The activity info's content, at most 100000 characters - plain text or HTML, as `contentType` says.", min_length=1, max_length=100000)
    contentType: Literal['text', 'html'] = Field('text', title='Content Type', description='`text` - shown as written, a paragraph per line. `html` - sanitized first: unsupported tags and attributes are dropped (see the notes above).')
    language: Literal['he', 'en', 'ar'] = Field('he', title='Language', description='The language the content is written in, one of: he, en, ar. `he` and `ar` are shown right-to-left, `en` left-to-right. Hebrew unless said otherwise.')
    category: str | None = Field(None, title='Category', description='A category of your choosing. Activity info can be filtered by it in the app. An existing category is reused when the text matches it exactly; any other text creates a new category.', max_length=100)
    employeeId: int | None = Field(None, title='Employee ID', description='The employee the activity info is by, shown in the app as who added it. Must be an active employee. Leave it out for activity info by no one in particular.', ge=1)
    locked: bool = Field(False, title='Locked', description='Lock the activity info. ⚠️ Locked activity info can never be edited or removed - not in the app and not through the API - and it cannot be unlocked later. Not locked unless said otherwise.')


class EasybizyServiceSelection(_Input):
    serviceId: int = Field(..., title='Service ID', description='The service to book, from [GET /scheduling/metadata](/documentation#/operations/getApiV1SchedulingMetadata) → *services[].serviceId*.')
    employeeId: int | None = Field(None, title='Employee ID', description='*Optional.* Request a specific employee for **this** service (each service may target its own). Only used when the business allows picking employees (metadata *options.allowPickingEmployees*); the available employees are listed per service in metadata (*services[].employees*).')
    quantity: int | None = Field(None, title='Quantity', description='*Optional.* Book more than one of this service at once (e.g. a couples treatment). **Only honored when the service is configured for it** — metadata *services[].quantitySelectable* is true, up to *services[].maxQuantity*. Otherwise ignored.', ge=1)
    schedulingPolicy: Literal['parallel', 'waterfall'] | None = Field(None, title='Scheduling Policy', description='*Optional.* For *quantity > 1*: run the copies at the same time (*parallel*) or back-to-back (*waterfall*). **Only honored when *quantitySelectable* is true.**')
    gender: list[str] | None = Field(None, title='Gender', description='*Optional.* Requested employee gender(s) for this service, e.g. ["female"] or ["female","male"]. **Only honored when the service is configured for it** — metadata *services[].genderSelectable* is true. Otherwise ignored.')


class EasybizyAvailabilitiesRequest(_Input):
    customerId: int = Field(..., title='Customer ID', description='The customer to compute availabilities for. Create one first via [POST /scheduling/customers](/documentation#/operations/postApiV1SchedulingCustomers).')
    serviceSelections: list[EasybizyServiceSelection] = Field(..., title='Service Selections', min_length=1)
    dayParts: list[Literal['morning', 'noon', 'evening']] = Field(['morning', 'noon', 'evening'], title='Day Parts', description='*Optional.* Parts of the day to search within — any combination of *morning*, *noon*, *evening*. Defaults to all parts.')
    searchStartTime: str | None = Field(None, title='Search Start Time', description='*Optional.* Earliest date/time to search from, **UTC** — the same form every datetime this API returns takes. Defaults to now.', pattern='^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}(:\\d{2})?(\\.\\d{1,3})?Z?$')


class EasybizyBookingRequest(_Input):
    availabilityId: str = Field(..., title='Availability ID', description='The *id* returned by [POST /scheduling/availabilities](/documentation#/operations/postApiV1SchedulingAvailabilities).')
    optionId: str = Field(..., title='Option ID', description='The chosen *options[].id* from that same response. Options expire after ~1 day.')
    customerId: int = Field(..., title='Customer ID', description='The customer to book for. Booking never creates a customer — create one first via [POST /scheduling/customers](/documentation#/operations/postApiV1SchedulingCustomers) (or [POST /customers](/documentation#/paths/~1api~1v1~1customers/post)), which is also the *customerId* you used to request the availabilities.')
    remarks: str | None = Field(None, title='Remarks', description='Free-text note attached to the appointment. Some services ask their customers for remarks (*services[].requiresRemarks* in metadata, with *services[].remarksPlaceholder* as the prompt) — that flag is **not** enforced here, so collect and pass the remarks yourself when it is set.')


class EasybizyCancelAppointment(_Input):
    id: int = Field(..., title='Id', description='The appointment *id* from [GET /scheduling/appointments](/documentation#/operations/getApiV1SchedulingAppointments).')
    startTime: str = Field(..., title='Start Time', description="The appointment's *startTime*. Always required — it identifies the exact occurrence, so nothing is looked up and the cancel never fails for a missing date.", pattern='^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}(:\\d{2})?(\\.\\d{1,3})?Z?$')


class EasybizyCancelAppointmentsRequest(_Input):
    customerId: int = Field(..., title='Customer ID', description='The customer whose appointments these are.')
    appointments: list[EasybizyCancelAppointment] = Field(..., title='Appointments', description='The appointments to cancel. An appointment booked under an unpaid **payment link** is cancelled together with the whole booking that link holds (every appointment on it) and the link itself.', min_length=1)


class _Page(_Input):
    top: int = Field(30, ge=1, le=500, title="Page Size")
    skip: int = Field(0, ge=0, title="Offset")


class _ContactsPage(_Page):
    search: str | None = Field(None, title="Search")
    filter: dict | None = Field(None, title="Filter", description='JSON filter, for example {"mobile":{"eq":"0501234567"}}. Cannot be combined with search.')
    order: Literal["firstName", "lastName", "timeCreated", "-firstName", "-lastName", "-timeCreated"] = "-timeCreated"

    @model_validator(mode="after")
    def exclusive_search(self):
        if self.filter is not None and self.search is not None:
            raise ValueError("Use either filter or search")
        return self


class _Id(_Input):
    id: int = Field(..., ge=1, title="Record ID")


class _ActivityPage(_Input):
    top: int = Field(10, ge=1, le=20, title="Page Size")
    skip: int = Field(0, ge=0, title="Offset")


class EasybizyListCustomersConfig(_ContactsPage):
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True, "x-display-name": "List Customers", "x-category": "Customers"})


class EasybizyGetCustomerConfig(_Id):
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Customer", "x-category": "Customers"})


class EasybizyCreateCustomerConfig(EasybizyCustomerCreate):
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Customer", "x-category": "Customers"})


class EasybizyUpdateCustomerConfig(EasybizyCustomerPatch):
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True, "x-display-name": "Update Customer", "x-category": "Customers"})
    id: int = Field(..., title="Record ID", ge=1)


class EasybizyDeleteCustomerConfig(_Id):
    operation: Literal["delete_customer"] = Field("delete_customer", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Customer", "x-category": "Customers"})


class EasybizyListCustomerActivitiesConfig(_ActivityPage):
    operation: Literal["list_customer_activities"] = Field("list_customer_activities", json_schema_extra={"ui:hidden": True, "x-display-name": "List Customer Activities", "x-category": "Customers"})
    customerId: int = Field(..., title='Customer ID', ge=1)


class EasybizyAddCustomerActivitiesConfig(EasybizyActivityInfoRequest):
    operation: Literal["add_customer_activities"] = Field("add_customer_activities", json_schema_extra={"ui:hidden": True, "x-display-name": "Add Customer Activities", "x-category": "Customers"})
    customerId: int = Field(..., title='Customer ID', ge=1)


class EasybizyListLeadsConfig(_ContactsPage):
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True, "x-display-name": "List Leads", "x-category": "Leads"})


class EasybizyGetLeadConfig(_Id):
    operation: Literal["get_lead"] = Field("get_lead", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Lead", "x-category": "Leads"})


class EasybizyCreateLeadConfig(EasybizyLeadRequest):
    @model_validator(mode="after")
    def require_contact(self):
        if not (self.mobile or self.email):
            raise ValueError("Supply the lead's mobile or email")
        return self

    operation: Literal["create_lead"] = Field("create_lead", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Lead", "x-category": "Leads"})


class EasybizyUpdateLeadConfig(EasybizyLeadPatch):
    operation: Literal["update_lead"] = Field("update_lead", json_schema_extra={"ui:hidden": True, "x-display-name": "Update Lead", "x-category": "Leads"})
    id: int = Field(..., title="Record ID", ge=1)


class EasybizyDeleteLeadConfig(_Id):
    operation: Literal["delete_lead"] = Field("delete_lead", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Lead", "x-category": "Leads"})


class EasybizyListLeadActivitiesConfig(_ActivityPage):
    operation: Literal["list_lead_activities"] = Field("list_lead_activities", json_schema_extra={"ui:hidden": True, "x-display-name": "List Lead Activities", "x-category": "Leads"})
    leadId: int = Field(..., title='Lead ID', ge=1)


class EasybizyAddLeadActivitiesConfig(EasybizyActivityInfoRequest):
    operation: Literal["add_lead_activities"] = Field("add_lead_activities", json_schema_extra={"ui:hidden": True, "x-display-name": "Add Lead Activities", "x-category": "Leads"})
    leadId: int = Field(..., title='Lead ID', ge=1)


class EasybizyListCatalogItemsConfig(_Page):
    operation: Literal["list_catalog_items"] = Field("list_catalog_items", json_schema_extra={"ui:hidden": True, "x-display-name": "List Catalog Items", "x-category": "Catalog"})
    type: Literal['service', 'product'] | None = Field(None, title='Type')
    search: str | None = Field(None, title='Search')
    order: Literal['timeCreated', 'id', 'title', 'retailPrice', '-timeCreated', '-id', '-title', '-retailPrice'] = Field('-timeCreated', title='Order')


class EasybizyGetCatalogItemConfig(_Id):
    operation: Literal["get_catalog_item"] = Field("get_catalog_item", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Catalog Item", "x-category": "Catalog"})
    type: Literal['service', 'product'] = Field(..., title='Type')


class EasybizyGetSchedulingMetadataConfig(_Input):
    operation: Literal["get_scheduling_metadata"] = Field("get_scheduling_metadata", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Scheduling Metadata", "x-category": "Scheduling"})


class EasybizyFindAvailabilitiesConfig(EasybizyAvailabilitiesRequest):
    operation: Literal["find_availabilities"] = Field("find_availabilities", json_schema_extra={"ui:hidden": True, "x-display-name": "Find Availabilities", "x-category": "Scheduling"})


class EasybizyBookAppointmentConfig(EasybizyBookingRequest):
    operation: Literal["book_appointment"] = Field("book_appointment", json_schema_extra={"ui:hidden": True, "x-display-name": "Book Appointment", "x-category": "Scheduling"})


class EasybizyCancelAppointmentsConfig(EasybizyCancelAppointmentsRequest):
    operation: Literal["cancel_appointments"] = Field("cancel_appointments", json_schema_extra={"ui:hidden": True, "x-display-name": "Cancel Appointments", "x-category": "Scheduling"})


class EasybizyListAppointmentsConfig(_Page):
    operation: Literal["list_appointments"] = Field("list_appointments", json_schema_extra={"ui:hidden": True, "x-display-name": "List Appointments", "x-category": "Scheduling"})
    filter: dict = Field(..., title='Filter', description='Required startTime range (gte and lte), spanning at most 21 days. Each occurrence is identified by id AND startTime.')
    order: Literal['startTime', 'timeCreated', 'timeUpdated', '-startTime', '-timeCreated', '-timeUpdated'] = Field('startTime', title='Order')


class EasybizyListInvoicesConfig(_Input):
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True, "x-display-name": "List Invoices", "x-category": "Invoices"})
    startDate: date = Field(..., title='Start Date')
    endDate: date = Field(..., title='End Date')


class EasybizyGetInvoiceConfig(_Id):
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Invoice", "x-category": "Invoices"})
    type: Literal['invoice', 'receipt', 'partialTaxInvoice'] = Field('invoice', title='Type')


class _Poll(PollTriggerConfigBase):
    modified_since: str | None = Field(None, title="Updated Since", description="Optional UTC timestamp bounding timeUpdated. Existing matching records are baselined when armed.")

    @field_validator("modified_since")
    @classmethod
    def utc_bound(cls, value):
        if value is not None:
            if not value.endswith("Z"):
                raise ValueError("Use a UTC timestamp ending in Z")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class EasybizyOnCustomerChangedConfig(_Poll):
    operation: Literal["on_customer_changed"] = Field("on_customer_changed", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New or Updated Customer"})


class EasybizyOnLeadChangedConfig(_Poll):
    operation: Literal["on_lead_changed"] = Field("on_lead_changed", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New or Updated Lead"})


# Each action maps to exactly one published method and path.
OPERATIONS = {
    'list_customers': ('GET', '/api/v1/customers', ('top', 'skip', 'filter', 'search', 'order'), (), False),
    'get_customer': ('GET', '/api/v1/customers/{id}', (), ('id',), False),
    'create_customer': ('POST', '/api/v1/customers', (), (), True),
    'update_customer': ('PATCH', '/api/v1/customers/{id}', (), ('id',), True),
    'delete_customer': ('DELETE', '/api/v1/customers/{id}', (), ('id',), False),
    'list_customer_activities': ('GET', '/api/v1/customers/{customerId}/activity-info', ('top', 'skip'), ('customerId',), False),
    'add_customer_activities': ('POST', '/api/v1/customers/{customerId}/activity-info', (), ('customerId',), True),
    'list_leads': ('GET', '/api/v1/leads', ('top', 'skip', 'filter', 'search', 'order'), (), False),
    'get_lead': ('GET', '/api/v1/leads/{id}', (), ('id',), False),
    'create_lead': ('POST', '/api/v1/leads', (), (), True),
    'update_lead': ('PATCH', '/api/v1/leads/{id}', (), ('id',), True),
    'delete_lead': ('DELETE', '/api/v1/leads/{id}', (), ('id',), False),
    'list_lead_activities': ('GET', '/api/v1/leads/{leadId}/activity-info', ('top', 'skip'), ('leadId',), False),
    'add_lead_activities': ('POST', '/api/v1/leads/{leadId}/activity-info', (), ('leadId',), True),
    'list_catalog_items': ('GET', '/api/v1/catalog-items', ('type', 'search', 'top', 'skip', 'order'), (), False),
    'get_catalog_item': ('GET', '/api/v1/catalog-items/{type}/{id}', (), ('type', 'id'), False),
    'get_scheduling_metadata': ('GET', '/api/v1/scheduling/metadata', (), (), False),
    'find_availabilities': ('POST', '/api/v1/scheduling/availabilities', (), (), True),
    'book_appointment': ('POST', '/api/v1/scheduling/appointments', (), (), True),
    'cancel_appointments': ('DELETE', '/api/v1/scheduling/appointments', (), (), True),
    'list_appointments': ('GET', '/api/v1/appointments', ('filter', 'top', 'skip', 'order'), (), False),
    'list_invoices': ('GET', '/api/v1/invoices', ('startDate', 'endDate'), (), False),
    'get_invoice': ('GET', '/api/v1/invoices/{type}/{id}', (), ('type', 'id'), False),
}

EasybizyConfig = Annotated[Union[
    EasybizyListCustomersConfig,
    EasybizyGetCustomerConfig,
    EasybizyCreateCustomerConfig,
    EasybizyUpdateCustomerConfig,
    EasybizyDeleteCustomerConfig,
    EasybizyListCustomerActivitiesConfig,
    EasybizyAddCustomerActivitiesConfig,
    EasybizyListLeadsConfig,
    EasybizyGetLeadConfig,
    EasybizyCreateLeadConfig,
    EasybizyUpdateLeadConfig,
    EasybizyDeleteLeadConfig,
    EasybizyListLeadActivitiesConfig,
    EasybizyAddLeadActivitiesConfig,
    EasybizyListCatalogItemsConfig,
    EasybizyGetCatalogItemConfig,
    EasybizyGetSchedulingMetadataConfig,
    EasybizyFindAvailabilitiesConfig,
    EasybizyBookAppointmentConfig,
    EasybizyCancelAppointmentsConfig,
    EasybizyListAppointmentsConfig,
    EasybizyListInvoicesConfig,
    EasybizyGetInvoiceConfig,
    EasybizyOnCustomerChangedConfig,
    EasybizyOnLeadChangedConfig
], Field(discriminator="operation")]


class EasybizyFullConfig(NodeConfig[EasybizyConfig, EasybizyCredential]):
    pass


class EasybizyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-easybizy"
    connection_evidence = ConnectionEvidence(operation="list_customers", noun="customers", label_keys=("firstName", "lastName", "mobile", "id"),
        identity_operation="get_scheduling_metadata", identity_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return EasybizyFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Easybizy with an API key and secret")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                headers={"x-api-key": credential.api_key, "x-api-secret": credential.api_secret,
                         "Accept": "application/json"}, **({"json": body} if body is not None else {}))
        response.raise_for_status()
        if response.status_code == 204:
            return {"success": True}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Easybizy returned an unexpected response")
        return data

    async def _poll(self, resource, config):
        rows = []
        for page in range(20):
            params = {"top": 500, "skip": page * 500, "order": "-timeCreated"}
            if config.modified_since:
                params["filter"] = json.dumps({"timeUpdated": {"gte": config.modified_since}})
            data = await self._request("GET", "/api/v1/" + resource, params=params)
            batch = data.get("data")
            if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
                raise ValueError("Easybizy did not return a record list")
            rows.extend(batch)
            if len(batch) < 500:
                break
        else:
            raise ValueError("More than 10,000 records match; set Updated Since to narrow the poll")
        def identity(row):
            if row.get("id") is None:
                return None
            return json.dumps([row["id"], row.get("timeUpdated") or row.get("timeCreated")], separators=(",", ":"))
        fresh = await self._filter_unseen(rows, identity)
        return {"operation": config.operation, "resource": resource, "records": fresh, "count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        records = output.get("records") if isinstance(output, dict) else None
        if not isinstance(records, list):
            return super().resolve_agent_event(output)
        if not records:
            return None
        lines = []
        for row in records[:20]:
            name = " ".join(str(row.get(key) or "") for key in ("firstName", "lastName")).strip() or "Unnamed contact"
            contact = row.get("mobile") or row.get("email") or "No contact details"
            lines.append(f"- {name}, {contact}; ID {row.get('id')}; updated {row.get('timeUpdated') or row.get('timeCreated')}; remarks: {row.get('remarks') or ''}")
        return {"text": f"Easybizy: {len(records)} new or updated {output.get('resource')}:\n" + "\n".join(lines),
                "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        try:
            if isinstance(config, (EasybizyOnCustomerChangedConfig, EasybizyOnLeadChangedConfig)):
                return await self._poll("customers" if isinstance(config, EasybizyOnCustomerChangedConfig) else "leads", config)
            method, path, query_fields, path_fields, has_body = OPERATIONS[config.operation]
            values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
            for field in path_fields:
                path = path.replace("{" + field + "}", str(values[field]))
            params = {key: json.dumps(values[key], separators=(",", ":")) if isinstance(values[key], dict) else values[key]
                      for key in query_fields if key in values}
            body = None
            if has_body:
                body = config.model_dump(mode="json", exclude_unset=True, exclude_none=True,
                                         exclude={"operation", *path_fields})
                # Explicit null clears a lead's sub-status; omission preserves it.
                if isinstance(config, EasybizyUpdateLeadConfig) and "subStatus" in config.model_fields_set:
                    body["subStatus"] = config.subStatus
            return await self._request(method, path, params=params, body=body)
        except httpx.HTTPStatusError as exc:
            return {"status": "error", "http_status": exc.response.status_code, "error": exc.response.text[:2000]}
