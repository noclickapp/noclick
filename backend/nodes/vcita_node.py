"""vcita Platform API operations, pinned to the provider's published v3.0 contracts.

Each operation sends one request. Lists return one page; writes are never retried.
Account owners can paste the API token exposed in Settings > Integrations.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.vcita.biz"
ResourceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]


class VcitaAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="vcita API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.vcita.com/app/settings/integrations",
            "x-help-url": "https://support.vcita.com/hc/en-us/articles/227895628-vcita-REST-API-for-Developers",
            "x-credential-instructions": "As the account owner, open Settings > Integrations > Webhooks > Connect and copy the API token. Paste the token below without the Bearer prefix. It is sent only to api.vcita.biz. Your token's permissions determine which operations are available.",
        })
    credential_type: Literal["vcita_api_token"] = Field("vcita_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, title="API token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API token without whitespace or a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def valid_dates(self):
        for key in ("start_date", "end_date"):
            if getattr(self, key, None) is not None:
                date.fromisoformat(getattr(self, key))
        if getattr(self, "start_date", None) and self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        if getattr(self, "time_zone", None):
            try:
                ZoneInfo(self.time_zone)
            except (KeyError, ValueError):
                raise ValueError("Use an IANA time zone such as UTC") from None
        return self


class BookingFormData(_Input):
    """Field IDs come from Get Scheduling Form for this business and service."""
    fields: dict[str, Any] = Field(..., description="Object keyed by scheduling form field UID. Supply every required field, including when using client_id.")
    service_fields: dict[str, Any] | None = None
    meeting_details: dict[str, str] | None = Field(None, description="For client location/phone services, include meeting_interaction_details.")
    others: dict[str, str] | None = None
    policies: dict[str, bool] | None = None


class VcitaListClientsConfig(_Input):
    """Get Clients."""
    operation: Literal["list_clients"] = Field("list_clients", title="List Clients", json_schema_extra={"ui:hidden": True})
    search_term: str | None = Field(None, max_length=10000, description='Search Term')
    search_by: str | None = Field(None, max_length=10000, description='Search By - email/uid/phone/updated_at')
    updated_at: str | None = Field(None, max_length=10000, description='Specify the updated_at filter range, available operators for updated_at: gte, lte. example: updated_at[gte]=2019-01-01')
    page: int = Field(1, ge=1, le=1000000, description='Page number of results. Default: 1')
    per_page: int = Field(25, ge=1, le=100, description='How many items to return per page. Default: 25. Max: 100')
    on_behalf_of: str | None = Field(None, max_length=10000, description='Business UID to act on behalf of. Required for Directory tokens.')

class VcitaGetClientConfig(_Input):
    """Retrieves a Client by Id."""
    operation: Literal["get_client"] = Field("get_client", title="Get Client", json_schema_extra={"ui:hidden": True})
    client_id: ResourceID = Field(..., description='Client UID')

class VcitaCreateClientConfig(_Input):
    """Create a Client."""
    operation: Literal["create_client"] = Field("create_client", title="Create Client", json_schema_extra={"ui:hidden": True})
    address: str | None = Field(None, max_length=10000, description='Address')
    custom_field1: str | None = Field(None, max_length=10000, description='Custom Field 1')
    custom_field2: str | None = Field(None, max_length=10000, description='Custom Field 2')
    custom_field3: str | None = Field(None, max_length=10000, description='Custom Field 3')
    email: str | None = Field(None, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", json_schema_extra={"format": "email"}, description='Email Address. Must be a valid email format (e.g., user@example.com)')
    first_name: str = Field(..., min_length=1, max_length=10000, description='First Name')
    last_name: str | None = Field(None, max_length=10000, description='Last Name')
    opt_in: bool | None = Field(None, description='Marketing email opt-in status. Accepts boolean values (`true` / `false`) or string values (`"1"` / `"0"`). When set to `true` (or `"1"`), the client is opted in to receive marketing emails; when set to `false` (or `"0"`), the client is opted out. This is distinct from `opt_in_transactional_sms`, which controls transactional SMS consent.')
    opt_in_transactional_sms: bool | None = Field(None, description='Whether the client opts in to receive transactional SMS messages.')
    phone: str | None = Field(None, max_length=10000, description='Phone Number')
    source_campaign: str | None = Field(None, max_length=10000, description='Source campaign')
    source_channel: str | None = Field(None, max_length=10000, description='Source channel')
    source_name: str | None = Field(None, max_length=10000, description='Source name')
    source_url: str | None = Field(None, max_length=10000, description='Source URL')
    staff_id: ResourceID | None = Field(None, description='Staff ID. Reference to the staff member (see staff entity).')
    status: Literal['lead', 'customer', 'loyal', 'inactive'] | None = Field(None, description='Use a client status to categorize clients according to their relationship with your business. Valid values: lead, customer, loyal, inactive')
    tags: str | None = Field(None, max_length=10000, description='The tag system is based on customized labels that you create, so you can sort your data using personalized words, phrases or themes that are meaningful to you and your business')

class VcitaUpdateClientConfig(_Input):
    """Updates a Client."""
    operation: Literal["update_client"] = Field("update_client", title="Update Client", json_schema_extra={"ui:hidden": True})
    client_id: ResourceID = Field(..., description='Client UID')
    address: str | None = Field(None, max_length=10000, description='Address. Send `null` or `""` to clear this field if force_nullifying is true.')
    custom_field1: str | None = Field(None, max_length=10000, description='Custom Field 1')
    custom_field2: str | None = Field(None, max_length=10000, description='Custom Field 2')
    custom_field3: str | None = Field(None, max_length=10000, description='Custom Field 3')
    email: str | None = Field(None, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", json_schema_extra={"format": "email"}, description='Email Address. Must be a valid email format (e.g., user@example.com)')
    first_name: str | None = Field(None, max_length=10000, description='First Name')
    force_nullifying: bool | None = Field(None, description='If true, allows nullable fields (address, mobile_phone) to be cleared by sending `null` or empty string. Must be boolean true or string "true".')
    last_name: str | None = Field(None, max_length=10000, description='Last Name')
    mobile_phone: str | None = Field(None, max_length=10000, description='Phone Number. Send `null` or `""` to clear this field if force_nullifying is true.')
    opt_in: bool | None = Field(None, description='Marketing email opt-in status. Accepts boolean values (`true` / `false`) or string values (`"1"` / `"0"`). When set to `true` (or `"1"`), the client is opted in to receive marketing emails; when set to `false` (or `"0"`), the client is opted out. This is distinct from `opt_in_transactional_sms`, which controls transactional SMS consent.')
    phone: str | None = Field(None, max_length=10000, description='Phone Number')
    source_name: str | None = Field(None, max_length=10000, description='Source name. Updates the client\'s source label (e.g., "website", "client_portal", "contact_form"). The new value is reflected in the `source` field on subsequent GET responses. Note: unlike `POST /platform/v1/clients`, this does NOT create or update the underlying source record, so existing `source_url`, `channel`, and `campaign` values remain unchanged.')
    source_url: str | None = Field(None, max_length=10000, description='Source URL. Persists the URL on the client record but, unlike `POST /platform/v1/clients`, does NOT update the underlying source record. As a result, the value will not be reflected in the `source_url` field returned by subsequent GET responses (which is read from the source record). To change the visible `source_url`, `channel`, or `campaign` of an existing client, the source record itself must be updated through other means.')
    spam: bool | None = Field(None, description='Client marked as spam')
    staff_id: ResourceID | None = Field(None, description='Staff ID')
    status: Literal['lead', 'customer', 'loyal', 'inactive'] | None = Field(None, description='Use a client status to categorize clients according to their relationship with your business. Valid values: lead, customer, loyal, inactive')
    tags: str | None = Field(None, max_length=10000, description='The tag system is based on customized labels that you create, so you can sort your data using personalized words, phrases or themes that are meaningful to you and your business')

    @model_validator(mode="after")
    def changes(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "client_id"}):
            raise ValueError("Supply at least one client field to update")
        return self

class VcitaDeleteClientConfig(_Input):
    """Deletes a Client by Id."""
    operation: Literal["delete_client"] = Field("delete_client", title="Delete Client", json_schema_extra={"ui:hidden": True})
    client_id: ResourceID = Field(..., description='Client UID')

class VcitaListFieldsConfig(_Input):
    """Get Fields List."""
    operation: Literal["list_fields"] = Field("list_fields", title="List Fields", json_schema_extra={"ui:hidden": True})

class VcitaGetFieldConfig(_Input):
    """Get Field Details."""
    operation: Literal["get_field"] = Field("get_field", title="Get Field", json_schema_extra={"ui:hidden": True})
    field_id: ResourceID = Field(..., description='Field ID')

class VcitaListAppointmentsConfig(_Input):
    """Get Appointments List."""
    operation: Literal["list_appointments"] = Field("list_appointments", title="List Appointments", json_schema_extra={"ui:hidden": True})
    business_id: ResourceID | None = Field(None, description='Business ID (optional)')
    client_id: ResourceID | None = Field(None, description='Client ID Filter')
    state: str | None = Field(None, max_length=10000, description='State Filter - rejected/scheduled/done/cancelled/pending_reschedule/reschedule e.g state=done,rejected')
    sort: str | None = Field(None, max_length=10000, description='Multiple order by option - updated:DESC,start_at:ASC,created:DESC')
    page: int = Field(1, ge=1, le=1000000, description='Page number of results. Default: 1')
    per_page: int = Field(25, ge=1, le=100, description='How many items to return per page. Default: 25. Max: 100')

class VcitaGetAppointmentConfig(_Input):
    """Get Appointment."""
    operation: Literal["get_appointment"] = Field("get_appointment", title="Get Appointment", json_schema_extra={"ui:hidden": True})
    appointment_id: ResourceID = Field(..., description='Appointment id')

class VcitaCreateBookingConfig(_Input):
    """Create New Booking [Alpha]."""
    operation: Literal["create_booking"] = Field("create_booking", title="Create Booking", json_schema_extra={"ui:hidden": True})
    business_id: ResourceID = Field(..., description='Business uid')
    campaign: str | None = Field(None, max_length=10000, description='Source campaign')
    channel: str | None = Field(None, max_length=10000, description='Source channel')
    client_id: ResourceID | None = Field(None, description='Client uid. Only usable with a Client token. Does not exempt the request from scheduling-form validation: fields marked `required: true` must still be supplied via `form_data.fields`, otherwise the request fails with 422 `FORM_VALIDATION_ERROR`.')
    event_instance_id: ResourceID | None = Field(None, description='Event instance uid. Required for event registration (not appointment booking).')
    form_data: BookingFormData = Field(..., description='Client form data for the scheduling form. **Required** - every field marked `required: true` in the form definition must be present here, even when `client_id` is supplied. Field uids come from `GET /platform/v1/scheduling/scheduling_forms/get_form?business_id={business_id}&service_id={service_id}`.\n\n## Structure\n`form_data` is an object of named sections - `fields`, `service_fields`, `meeting_details`, `others`, `policies`, `client_settings`. Every section is an object, never an array, and `fields` is keyed by field uid:\n```json\n{\n  "form_data": {\n    "fields": {\n      "{email_field_id}": "client@example.com",\n      "{first_name_field_id}": "John"\n    },\n    "others": { "notes": null },\n    "policies": {}\n  }\n}\n```\n\nThere is no `field_id` / `type` / `new_data` wrapper.')
    matter_uid: ResourceID | None = Field(None, description='Matter uid (conversation context)')
    portal_id: ResourceID | None = Field(None, description='Business uid (same as business_id, for portal context)')
    service_id: ResourceID | None = Field(None, description='Service uid. Required for appointment booking.')
    source_name: str | None = Field(None, max_length=10000, description="Source name (e.g., 'client_portal', 'api')")
    source_url: str | None = Field(None, max_length=10000, description='Source URL')
    staff_id: ResourceID | None = Field(None, description="Staff uid. Required for appointment booking. Must be one of the service's `providers_staff` (see `GET /platform/v1/services`).")
    start_time: str | None = Field(None, max_length=10000, description='ISO 8601 format (e.g., "2026-09-16T15:00:00Z"). Required for appointment. Must be a slot where the whole service duration fits - see `GET /platform/v1/staff/availability`.')
    time_zone: str | None = Field(None, max_length=10000, description='Default is set to UTC if not provided')

    @model_validator(mode="after")
    def booking_target(self):
        if not self.event_instance_id and not (self.service_id and self.staff_id and self.start_time):
            raise ValueError("Supply service_id, staff_id and start_time for an appointment, or event_instance_id for an event")
        if self.start_time:
            value = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            if value.tzinfo is None:
                raise ValueError("Start time must include a time zone")
        return self

class VcitaCancelBookingConfig(_Input):
    """Cancel a Booking [Alpha]."""
    operation: Literal["cancel_booking"] = Field("cancel_booking", title="Cancel Booking", json_schema_extra={"ui:hidden": True})
    booking_id: ResourceID = Field(..., description='Booking (appointment/event) uid. Can be obtained from:\n- `GET /platform/v1/scheduling/bookings` (requires Client token)\n- `GET /platform/v1/scheduling/appointments` (returns `id` field which is the booking_id)\n- Response from `POST /platform/v1/scheduling/bookings` (returns `data.booking.id`)')
    business_id: ResourceID = Field(..., description='Business uid')
    event_instance_id: ResourceID | None = Field(None, description='Event instance uid. Required only for cancelling event registrations (not appointments).')

class VcitaListServicesConfig(_Input):
    """Get Services List."""
    operation: Literal["list_services"] = Field("list_services", title="List Services", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000, description='Page number of results. Default: 1')
    per_page: int = Field(25, ge=1, le=100, description='How many items to return per page. Default: 25. Max: 100')
    business_id: ResourceID = Field(..., description="The business's unique identifier")

class VcitaGetServiceConfig(_Input):
    """Get Service Details."""
    operation: Literal["get_service"] = Field("get_service", title="Get Service", json_schema_extra={"ui:hidden": True})
    service_uid: ResourceID = Field(..., description='Service UID')

class VcitaListPaymentsConfig(_Input):
    """Get Payments List."""
    operation: Literal["list_payments"] = Field("list_payments", title="List Payments", json_schema_extra={"ui:hidden": True})
    on_behalf_of: str | None = Field(None, max_length=10000, description='A unique identifer of the business. Can be the Business UID or nickname\\external ID')
    page: str = Field('1', pattern=r"^[1-9][0-9]*$", max_length=10000, description='Page offset')
    per_page: str = Field('25', pattern=r"^[1-9][0-9]*$", max_length=10000, description='Page size')
    sort: str | None = Field(None, max_length=10000, description='Sort by one of the following: created_at, updated_at.\n                                                                      Available operators: asc, desc.\n                                                                      Example: sort=created_at:asc,updated_at:desc')

class VcitaGetPaymentConfig(_Input):
    """Get Payment by ID."""
    operation: Literal["get_payment"] = Field("get_payment", title="Get Payment", json_schema_extra={"ui:hidden": True})
    payment_uid: ResourceID = Field(..., description='Payment UID')

class VcitaListInvoicesConfig(_Input):
    """Get Invoices List."""
    operation: Literal["list_invoices"] = Field("list_invoices", title="List Invoices", json_schema_extra={"ui:hidden": True})
    sort: str | None = Field(None, max_length=10000, description='Sort by one of the following: created_at, updated_at, state. available operators: asc, desc. example: sort=created_at:asc,updated_at:desc')
    page: str = Field('1', pattern=r"^[1-9][0-9]*$", max_length=10000, description='Page offset')
    per_page: str = Field('25', pattern=r"^[1-9][0-9]*$", max_length=10000, description='Page size')

class VcitaGetInvoiceConfig(_Input):
    """Get Invoice By ID."""
    operation: Literal["get_invoice"] = Field("get_invoice", title="Get Invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: ResourceID = Field(..., description='Invoice ID')

class VcitaListEstimatesConfig(_Input):
    """Get Estimates List."""
    operation: Literal["list_estimates"] = Field("list_estimates", title="List Estimates", json_schema_extra={"ui:hidden": True})
    sort: str | None = Field(None, max_length=10000, description='Sort results. Available fields: created_at, updated_at, state. Operators: asc, desc. Example: sort=created_at:asc,updated_at:desc')
    page: int = Field(1, ge=1, le=1000000, description='Page number of results. Default: 1')
    per_page: int = Field(25, ge=1, le=100, description='How many items to return per page. Default: 25')

class VcitaGetSchedulingFormConfig(_Input):
    """Get Scheduling Form."""
    operation: Literal["get_scheduling_form"] = Field("get_scheduling_form", title="Get Scheduling Form", json_schema_extra={"ui:hidden": True})
    business_id: ResourceID = Field(..., description='Business uid')
    service_id: str | None = Field(None, max_length=10000, description='Service uid, to get the form for a specific service. Omit it and the business-level form is returned, which can miss service-specific fields. Accepts a comma-separated list of uids for a multi-service booking (e.g. "vpa6mzkt11f1n2pc,x8enou59f38uy7kb").')

class VcitaGetStaffAvailabilityConfig(_Input):
    """Get Staff Availability."""
    operation: Literal["get_staff_availability"] = Field("get_staff_availability", title="Get Staff Availability", json_schema_extra={"ui:hidden": True})
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=10000, description='The start date of the availability window in `YYYY-MM-DD` format (e.g., "2026-03-03"). Must be a valid date string that can be parsed into a timezone-aware datetime.')
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=10000, description='The end date of the availability window in `YYYY-MM-DD` format (e.g., "2026-03-10"). Must be a valid date string that can be parsed into a timezone-aware datetime. The range between `start_date` and `end_date` determines the window for which availability slots are returned.')
    staff_ids_array: str = Field(..., max_length=10000, description='Comma-separated list of staff member UIDs to query availability for (e.g., "j9c1xh0vzvkr2g0g" or "j9c1xh0vzvkr2g0g, abc123def456"). If the value is a comma-separated string, it will be split into an array internally. At least one staff UID should be provided for meaningful results.')
    time_zone: str | None = Field(None, max_length=10000, description='IANA time zone identifier used to localize the returned availability slots (e.g., "UTC", "America/New_York", "Asia/Jerusalem"). Defaults to "UTC" if not provided. The time zone affects the `start_time` formatting and date grouping in the response.')
    aggregate_by: Literal['date', 'staff'] | None = Field(None, description='Controls how the availability slots are grouped in the response. When set to "date" (the default), slots are grouped by date string (e.g., "2026-03-03"). When set to "staff", slots are grouped first by staff UID and then by date, and the `staff_id` field is removed from individual slot objects.')
    booking_instance_id: ResourceID | None = Field(None, description='An existing booking instance UID to exclude from the availability calculation. This is useful when rescheduling an appointment — the time currently occupied by this booking will be treated as available. (e.g., "bk_abc123")')
    include_dst: Literal['true', 'false'] | None = Field(None, description='When set to "true", the returned `start_time` values will include daylight saving time (DST) offset adjustments for the specified time zone. When "false" or omitted, DST adjustments may not be applied.')
    show_past_availabilities: Literal['true', 'false'] | None = Field(None, description='When set to "true", includes availability slots that fall before the current time. By default ("false"), only future availability is returned.')
    ignore_min_schedule: Literal['true', 'false'] | None = Field(None, description='When set to "true", ignores the business\'s minimum scheduling notice (the minimum amount of time before an appointment can be booked). Useful for internal tools or admin-level booking where the minimum lead time should not apply.')
    type: Literal['AppointmentService', 'EventService'] | None = Field(None, description='The type of service to check availability for. "AppointmentService" returns individual appointment slots based on staff schedules. "EventService" returns event instance availability with additional fields such as pricing and interaction details.')


VcitaConfig = Annotated[Union[
    VcitaListClientsConfig,
    VcitaGetClientConfig,
    VcitaCreateClientConfig,
    VcitaUpdateClientConfig,
    VcitaDeleteClientConfig,
    VcitaListFieldsConfig,
    VcitaGetFieldConfig,
    VcitaListAppointmentsConfig,
    VcitaGetAppointmentConfig,
    VcitaCreateBookingConfig,
    VcitaCancelBookingConfig,
    VcitaListServicesConfig,
    VcitaGetServiceConfig,
    VcitaListPaymentsConfig,
    VcitaGetPaymentConfig,
    VcitaListInvoicesConfig,
    VcitaGetInvoiceConfig,
    VcitaListEstimatesConfig,
    VcitaGetSchedulingFormConfig,
    VcitaGetStaffAvailabilityConfig
], Field(discriminator="operation")]


class VcitaFullConfig(NodeConfig[VcitaConfig, VcitaAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'list_clients': ('GET',
                  '/platform/v1/clients',
                  'clients',
                  {'search_term': ('query', 'search_term'),
                   'search_by': ('query', 'search_by'),
                   'updated_at': ('query', 'updated_at'),
                   'page': ('query', 'page'),
                   'per_page': ('query', 'per_page'),
                   'on_behalf_of': ('header', 'X-On-Behalf-Of')}),
 'get_client': ('GET', '/platform/v1/clients/{client_id}', 'client', {'client_id': ('path', 'client_id')}),
 'create_client': ('POST', '/platform/v1/clients', 'client', {}),
 'update_client': ('PUT', '/platform/v1/clients/{client_id}', 'client', {'client_id': ('path', 'client_id')}),
 'delete_client': ('DELETE',
                   '/platform/v1/clients/{client_id}',
                   'client',
                   {'client_id': ('path', 'client_id')}),
 'list_fields': ('GET', '/platform/v1/fields', None, {}),
 'get_field': ('GET', '/platform/v1/fields/{field_id}', 'field', {'field_id': ('path', 'field_id')}),
 'list_appointments': ('GET',
                       '/platform/v1/scheduling/appointments',
                       'appointments',
                       {'business_id': ('query', 'business_id'),
                        'client_id': ('query', 'client_id'),
                        'state': ('query', 'state'),
                        'sort': ('query', 'sort'),
                        'page': ('query', 'page'),
                        'per_page': ('query', 'per_page')}),
 'get_appointment': ('GET',
                     '/platform/v1/scheduling/appointments/{appointment_id}',
                     'appointment',
                     {'appointment_id': ('path', 'appointment_id')}),
 'create_booking': ('POST', '/platform/v1/scheduling/bookings', 'booking', {}),
 'cancel_booking': ('POST', '/platform/v1/scheduling/bookings/cancel', None, {}),
 'list_services': ('GET',
                   '/platform/v1/services',
                   'services',
                   {'page': ('query', 'page'),
                    'per_page': ('query', 'per_page'),
                    'business_id': ('query', 'business_id')}),
 'get_service': ('GET',
                 '/platform/v1/services/{service_uid}',
                 'service',
                 {'service_uid': ('path', 'service_uid')}),
 'list_payments': ('GET',
                   '/platform/v1/payments',
                   'payments',
                   {'on_behalf_of': ('header', 'X-On-Behalf-Of'),
                    'page': ('query', 'page'),
                    'per_page': ('query', 'per_page'),
                    'filter': ('query', 'filter'),
                    'sort': ('query', 'sort')}),
 'get_payment': ('GET',
                 '/platform/v1/payments/{payment_uid}',
                 'payment',
                 {'payment_uid': ('path', 'payment_uid')}),
 'list_invoices': ('GET',
                   '/platform/v1/invoices',
                   'invoices',
                   {'filter': ('query', 'filter'),
                    'sort': ('query', 'sort'),
                    'page': ('query', 'page'),
                    'per_page': ('query', 'per_page')}),
 'get_invoice': ('GET',
                 '/platform/v1/invoices/{invoice_id}',
                 'invoice',
                 {'invoice_id': ('path', 'invoice_id')}),
 'list_estimates': ('GET',
                    '/platform/v1/estimates',
                    'estimates',
                    {'filter': ('query', 'filter'),
                     'sort': ('query', 'sort'),
                     'page': ('query', 'page'),
                     'per_page': ('query', 'per_page')}),
 'get_scheduling_form': ('GET',
                         '/platform/v1/scheduling/scheduling_forms/get_form',
                         None,
                         {'business_id': ('query', 'business_id'), 'service_id': ('query', 'service_id')}),
 'get_staff_availability': ('GET',
                            '/platform/v1/staff/availability',
                            None,
                            {'start_date': ('query', 'start_date'),
                             'end_date': ('query', 'end_date'),
                             'staff_ids_array': ('query', 'staff_ids_array'),
                             'time_zone': ('query', 'time_zone'),
                             'aggregate_by': ('query', 'aggregate_by'),
                             'booking_instance_id': ('query', 'booking_instance_id'),
                             'include_dst': ('query', 'include_dst'),
                             'show_past_availabilities': ('query', 'show_past_availabilities'),
                             'ignore_min_schedule': ('query', 'ignore_min_schedule'),
                             'type': ('query', 'type')})}

# Some Platform GET endpoints deliberately return HTTP 201 in the published contract.
SUCCESS_STATUS = {name: (201 if name in {"create_client", "create_booking", "list_payments", "get_payment", "list_invoices", "get_invoice"} else 200) for name in ROUTES}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()
            if key.lower() not in {"token", "access_token", "refresh_token", "api_token", "authorization", "password"}}
    return value


class VcitaNode(WorkflowNode):
    integration_type = "automation-vcita"
    connection_evidence = ConnectionEvidence(operation="list_clients", noun="vcita clients",
        label_keys=("email", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return VcitaFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a vcita API token")
        config, credential = self.config.config, self.config.credentials
        operation = config.operation
        method, path, record_key, parameters = ROUTES[operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        params, headers = {}, {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        for field, (location, name) in parameters.items():
            if field not in values:
                continue
            value = values.pop(field)
            if location == "path":
                path = path.replace("{" + name + "}", quote(value, safe=""))
            elif location == "header":
                if any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise ValueError("Business header cannot contain control characters")
                headers[name] = value
            else:
                params[name] = value
        body = values if method in {"POST", "PUT"} else None
        if operation == "update_client" and config.force_nullifying:
            for field in ("address", "mobile_phone"):
                if field in config.model_fields_set and getattr(config, field) is None:
                    body[field] = ""
        result = {"operation": operation, "status": "error"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, headers=headers,
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            return {**result, "error": "vcita request did not complete; check provider state before retrying a write"}
        result["http_status"] = response.status_code
        if len(response.content) > 5 * 1024 * 1024:
            return {**result, "error": "vcita response exceeded the supported size"}
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            return {**result, "error": "vcita returned a non-JSON response"}
        if not isinstance(payload, dict):
            return {**result, "error": "vcita returned an invalid response envelope"}
        if (response.status_code != SUCCESS_STATUS[operation] or payload.get("status") != "OK"
                or payload.get("error") or payload.get("errors")):
            message = payload.get("error") or payload.get("message") or payload.get("errors") or "vcita did not confirm the request"
            return {**result, "error": _redact(message, credential.api_token)}
        data = payload.get("data")
        if not isinstance(data, (dict, list)):
            return {**result, "error": "vcita response is missing its data"}
        result.update(status="success", data=data)
        if operation.startswith("list_"):
            items = data.get(record_key) if record_key and isinstance(data, dict) else data
            if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                return {"operation": operation, "status": "error", "http_status": response.status_code,
                    "error": "vcita list response is missing its records"}
            result["items"] = items
            # A page is never represented as an exhaustive export. Keep vcita's
            # pagination in data and expose an explicit next page when supplied.
            result["page"] = getattr(config, "page", None)
            result["per_page"] = getattr(config, "per_page", None)
            if isinstance(data, dict) and "next_page" in data:
                result["next_page"] = data["next_page"]
        elif record_key:
            record = data.get(record_key) if isinstance(data, dict) else None
            # The documented payment detail envelope contains a one-item array.
            if operation == "get_payment" and isinstance(record, list) and len(record) == 1:
                record = record[0]
            if not isinstance(record, dict):
                return {"operation": operation, "status": "error", "http_status": response.status_code,
                    "error": "vcita response is missing its record"}
            result["item"] = record
        return _redact(result, credential.api_token)
