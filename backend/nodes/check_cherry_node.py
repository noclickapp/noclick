"""Check Cherry Business API v1 operations for personal integration keys.

Each operation makes one fixed published request. JSON:API attributes, relationships,
included resources and provider pagination metadata survive in the output.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.checkcherry.com"
CREDENTIAL_TYPE = "check_cherry_api_key"


class CheckCherryCredential(BaseModel):
    model_config = ConfigDict(title="Check Cherry API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.checkcherry.com/api/docs",
            "x-credential-instructions": "In Check Cherry, open Manage → Business Settings → Integrations → API Overview → API Keys. Create an Integration Key with lead_read for the connection check and the read/write permissions needed for your operations. Paste the key here; NoClick sends it in the Api-Key header. Keys cannot exceed their creator's permissions.",
        })
    credential_type: Literal["check_cherry_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Integration key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="Integration key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the integration key without a header prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BookingPackage(_Operation):
    """One package on a new booking or proposal; IDs come from List Packages."""
    event_type_id: str = Field(..., min_length=1, description="Existing package ID from List Packages.")
    starts_at_date: date
    starts_at_time: str = Field(..., min_length=1, description="Start time, e.g. 14:30.")
    length_in_minutes: int = Field(..., ge=1, le=1440)
    staff_id: int | None = Field(None, gt=0)
    backdrop_id: int | None = Field(None, gt=0)
    add_on_ids: str | None = Field(None, description="Comma-separated add-on IDs, with optional quantities such as 2x17.")

    @field_validator("event_type_id")
    @classmethod
    def existing_package(cls, value):
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            raise ValueError("Choose an existing numeric package ID")
        return value


class ListLeadsConfig(_Operation):
    'Fetch all leads'
    operation: Literal['list_leads'] = Field('list_leads', json_schema_extra={"ui:hidden": True})
    include: str | None = Field(None, min_length=1, description='Related resources to sideload, comma-separated. The description lists what is available.')
    email: str | None = Field(None, min_length=1, description='Filter leads by exact email address match')
    text: str | None = Field(None, min_length=1, description='Full-text search across lead name, email, phone, venue, and notes')
    page: int = Field(1, ge=1, le=10000, description='Page number for pagination (default: 1)')
    per: int = Field(25, ge=1, le=100, description='Number of results per page (default: 25)')


class GetLeadConfig(_Operation):
    'Fetch lead by ID'
    operation: Literal['get_lead'] = Field('get_lead', json_schema_extra={"ui:hidden": True})
    include: str | None = Field(None, min_length=1, description='Related resources to sideload, comma-separated. The description lists what is available.')
    lead_id: int = Field(..., gt=0, description='The unique ID of the lead to retrieve')


class CreateLeadConfig(_Operation):
    'Add a lead to the database'
    operation: Literal['create_lead'] = Field('create_lead', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, description='Contact email address')
    first_name: str | None = Field(None, min_length=1, description='Contact first name')
    last_name: str | None = Field(None, min_length=1, description='Contact last name')
    phone: str | None = Field(None, min_length=1, description='Contact phone number')
    company_name: str | None = Field(None, min_length=1, description='Business or organization name')
    lead_source: Literal['Manual Entry', 'Lead Form', 'Online Booking', 'App', 'Zapier', 'API', 'Wedding Wire'] | None = Field(None, description='How the lead was acquired')
    contact_preference: Literal['Email', 'Phone', 'Text Message'] | None = Field(None, description='How the lead prefers to be contacted')
    notes: str | None = Field(None, min_length=1, description='Private internal notes about this lead')
    custom_questions: dict[str, Any] | None = Field(None, description='Responses to custom booking questions configured by the business, as key-value pairs')


class UpdateLeadConfig(_Operation):
    'Update a lead'
    operation: Literal['update_lead'] = Field('update_lead', json_schema_extra={"ui:hidden": True})
    lead_id: int = Field(..., gt=0, description='The unique ID of the lead to update')
    email: str | None = Field(None, min_length=1, description='Contact email address')
    first_name: str | None = Field(None, min_length=1, description='Contact first name')
    last_name: str | None = Field(None, min_length=1, description='Contact last name')
    phone: str | None = Field(None, min_length=1, description='Contact phone number')
    company_name: str | None = Field(None, min_length=1, description='Business or organization name')
    lead_source: str | None = Field(None, min_length=1, description='How the lead was acquired')
    contact_preference: Literal['Email', 'Phone', 'Text Message'] | None = Field(None, description='How the lead prefers to be contacted')
    notes: str | None = Field(None, min_length=1, description='Private internal notes about this lead')
    starts_at_date: date | None = Field(None, description='Requested event date (YYYY-MM-DD)')
    starts_at_time: str | None = Field(None, min_length=1, description='Requested event start time')
    length_in_minutes: int | None = Field(None, gt=0, description='Requested event duration in minutes')
    package_id: int | None = Field(None, gt=0, description='Package (event type) ID the lead is interested in, from `GET /api/v1/packages`. Must belong to this business.')
    service_id: int | None = Field(None, gt=0, description='Service (event category) ID the lead is interested in, from `GET /api/v1/event_categories`. Ignored when `package_id` is sent: the package sets the service. Must belong to this business.')
    staff_id: int | None = Field(None, gt=0, description="Staff member ID requested for the lead's package")
    next_follow_up_on: date | None = Field(None, description='Next follow-up date (YYYY-MM-DD)')
    custom_questions: dict[str, Any] | None = Field(None, description='Responses to custom booking questions, as key-value pairs')

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", 'lead_id'}):
            raise ValueError("Provide at least one field to update")
        return self


class ArchiveLeadConfig(_Operation):
    'Archive a lead'
    operation: Literal['archive_lead'] = Field('archive_lead', json_schema_extra={"ui:hidden": True})
    lead_id: int = Field(..., gt=0, description='The unique ID of the lead')


class UnarchiveLeadConfig(_Operation):
    'Unarchive a lead'
    operation: Literal['unarchive_lead'] = Field('unarchive_lead', json_schema_extra={"ui:hidden": True})
    lead_id: int = Field(..., gt=0, description='The unique ID of the lead')


class AddLeadNoteConfig(_Operation):
    'Add a note to a lead'
    operation: Literal['add_lead_note'] = Field('add_lead_note', json_schema_extra={"ui:hidden": True})
    lead_id: int = Field(..., gt=0, description='The unique ID of the lead')
    note: str = Field(..., min_length=1, description='The note text to add')
    next_follow_up_on: date | None = Field(None, description='Set or update the next follow-up date (YYYY-MM-DD)')


class ListEventsConfig(_Operation):
    'Fetch all events'
    operation: Literal['list_events'] = Field('list_events', json_schema_extra={"ui:hidden": True})
    include: str | None = Field(None, min_length=1, description='Related resources to sideload, comma-separated. The description lists what is available.')
    event_status: str | None = Field(None, min_length=1, description='Status filter. Does not filter cancellation -- use `canceled_status` for that.:\n * `proposal_date_open` \n * `proposal_date_reserved` \n * `proposal_awaiting_review` \n * `awaiting_signature` \n * `confirmed` \n * `any_proposal` \n * `any_confirmed` \n * `any_unsigned` \n ')
    canceled_status: str | None = Field(None, min_length=1, description='Cancellation filter. Defaults to `hide_canceled`.')
    postponed_status: str | None = Field(None, min_length=1, description='Postponement filter. Defaults to `hide_postponed`.')
    expired_status: str | None = Field(None, min_length=1, description='Expired-proposal filter. Defaults to `hide_expired`.')
    past_or_future: str | None = Field(None, min_length=1, description='When filter. Defaults to `both`. Ignored when an event date range is supplied.')
    event_date_start: str | None = Field(None, min_length=1, description='Event Date (Start)')
    event_date_end: str | None = Field(None, min_length=1, description='Event Date (End)')
    booked_date_start: str | None = Field(None, min_length=1, description='Booked Date (Start)')
    booked_date_end: str | None = Field(None, min_length=1, description='Booked Date (End)')
    updated_since: str | None = Field(None, min_length=1, description='Only events changed at or after this time (ISO 8601, such as `2026-10-12T15:00:00Z`)')
    search_text: str | None = Field(None, min_length=1, description='Text Search')
    events_id: int | None = Field(None, gt=0, description='Return only the event with this ID')
    brand_id: int | None = Field(None, gt=0, description='Limit to events on this brand')
    client_id: int | None = Field(None, gt=0, description='Limit to events for this client')
    staff_id: int | None = Field(None, gt=0, description='Limit to events this staff member is assigned to')
    event_category_id: int | None = Field(None, gt=0, description='Limit to events with a package in this service. Service ids come from `GET /api/v1/event_categories`.')
    proposal_viewed: bool | None = Field(None, description='Proposals only. `false` returns proposals the client has never opened, `true` those they have. Combine with `expired_status=show_all` to include expired proposals.')
    recurring_event_id: int | None = Field(None, gt=0, description='Limit to bookings generated by this recurring series (plus the booking it was made from). Series ids come from `GET /api/v1/recurring_events`. Pass `canceled_status=show_all` and `postponed_status=show_all` to see every booking in the series.')
    awaiting_deposit: bool | None = Field(None, description='Only events whose deposit is unpaid')
    balance_outstanding: bool | None = Field(None, description='Only events with a balance still owed')
    past_due: bool | None = Field(None, description='Only events with a past due payment')
    has_unselected_templates: bool | None = Field(None, description='Only events with a design template still unselected')
    has_pending_artwork: bool | None = Field(None, description='Only events with artwork pending')
    has_unapproved_artwork: bool | None = Field(None, description='Only events with artwork awaiting approval')
    unsubmitted_forms: bool | None = Field(None, description='Only events with an unsubmitted form')
    no_staff_assigned: bool | None = Field(None, description='Only events with no staff assigned')
    no_backdrop_assigned: bool | None = Field(None, description='Only events with no backdrop assigned')
    sort_by: str | None = Field(None, min_length=1, description='Sort Order. Defaults to `automatic`.')
    page: int = Field(1, ge=1, le=10000, description='Page number for pagination (default: 1)')
    per: int = Field(25, ge=1, le=100, description='Number of results per page (default: 10, max: 100)')


class GetEventConfig(_Operation):
    'Fetch event by ID'
    operation: Literal['get_event'] = Field('get_event', json_schema_extra={"ui:hidden": True})
    include: str | None = Field(None, min_length=1, description='Related resources to sideload, comma-separated. The description lists what is available.')
    event_id: int = Field(..., gt=0, description='Event ID')


class UpdateEventConfig(_Operation):
    'Update an event'
    operation: Literal['update_event'] = Field('update_event', json_schema_extra={"ui:hidden": True})
    event_id: int = Field(..., gt=0, description='Event ID')
    public_notes: str | None = Field(None, min_length=1, description='Public notes visible to the customer')
    photo_album_url: str | None = Field(None, min_length=1, description='URL to the photo album')
    photo_album_instructions: str | None = Field(None, min_length=1, description='Instructions for the photo album')
    video_url: str | None = Field(None, min_length=1, description='URL to the video')
    video_album_instructions: str | None = Field(None, min_length=1, description='Instructions for the video album')
    next_follow_up_on: date | None = Field(None, description='Next follow-up date (YYYY-MM-DD)')

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", 'event_id'}):
            raise ValueError("Provide at least one field to update")
        return self


class CancelEventConfig(_Operation):
    'Cancel an event'
    operation: Literal['cancel_event'] = Field('cancel_event', json_schema_extra={"ui:hidden": True})
    event_id: int = Field(..., gt=0, description='Event ID')
    cancel_reason: str | None = Field(None, min_length=1, description='Reason for cancellation')
    send_cancellation_messages: bool = Field(False, description='Send cancellation messages to contacts')


class UncancelEventConfig(_Operation):
    'Uncancel an event'
    operation: Literal['uncancel_event'] = Field('uncancel_event', json_schema_extra={"ui:hidden": True})
    event_id: int = Field(..., gt=0, description='Event ID')


class AddEventNoteConfig(_Operation):
    'Add a note to a booking'
    operation: Literal['add_event_note'] = Field('add_event_note', json_schema_extra={"ui:hidden": True})
    event_id: int = Field(..., gt=0, description='The unique ID of the booking')
    note: str = Field(..., min_length=1, description='The note text to add (private internal note, staff-only)')
    next_follow_up_on: date | None = Field(None, description="Set or update the booking's next follow-up date (YYYY-MM-DD)")


class CreateBookingConfig(_Operation):
    'Create a booking'
    operation: Literal['create_booking'] = Field('create_booking', json_schema_extra={"ui:hidden": True})
    packages: list[BookingPackage] = Field(..., min_length=1, description='The packages being booked. At least one is required.')
    contact_name: str = Field(..., min_length=1, description="Client's name. Required when `contact_type` is `New Customer`.")
    contact_email: str | None = Field(None, min_length=1, description="Client's email. Creates a full customer account rather than a plain contact record.")
    contact_phone: str | None = Field(None, min_length=1, description="Client's phone")
    contact_company_name: str | None = Field(None, min_length=1, description="Client's company name")
    venue_name: str | None = Field(None, min_length=1, description='Venue name')
    venue_address: str | None = Field(None, min_length=1, description='Venue street address')
    venue_city: str | None = Field(None, min_length=1, description='Venue city')
    venue_state: str | None = Field(None, min_length=1, description="Venue state or province code, in whatever form the business's country uses, e.g. `MA`")
    venue_zip: str | None = Field(None, min_length=1, description='Venue postal code')
    public_notes: str | None = Field(None, min_length=1, description='Notes visible to the client')
    private_notes: str | None = Field(None, min_length=1, description='Notes only staff can see')
    brand_id: int | None = Field(None, gt=0, description='Brand to book under, which must be an active brand of this business. Defaults to the primary brand.')
    lead_id: int | None = Field(None, gt=0, description="Lead this booking converts, from `GET /api/v1/leads`. The lead's details and attribution carry over and it is marked converted.")
    signature_collected: bool | None = Field(None, description='Has the signature already been collected? Defaults to `true`, creating a `confirmed` booking. `false` creates it `awaiting_signature`.')
    send_booking_confirmation_emails: bool | None = Field(None, description='Send the client the booking confirmation emails. Requires `contact_email`.')
    send_contact_invitation_to_create_account: bool | None = Field(None, description='Email the client an invitation to create an account. Requires `contact_email`.')
    contact_type: Literal["New Customer"] = Field("New Customer", description="Creates a new customer contact.")


class CreateProposalConfig(_Operation):
    'Create a proposal'
    operation: Literal['create_proposal'] = Field('create_proposal', json_schema_extra={"ui:hidden": True})
    packages: list[BookingPackage] = Field(..., min_length=1, description='The packages being proposed. At least one is required.')
    contact_name: str = Field(..., min_length=1, description="Client's name. Required when `contact_type` is `New Customer`.")
    contact_email: str | None = Field(None, min_length=1, description="Client's email. Creates a full customer account rather than a plain contact record.")
    contact_phone: str | None = Field(None, min_length=1, description="Client's phone")
    contact_company_name: str | None = Field(None, min_length=1, description="Client's company name")
    venue_name: str | None = Field(None, min_length=1, description='Venue name')
    venue_address: str | None = Field(None, min_length=1, description='Venue street address')
    venue_city: str | None = Field(None, min_length=1, description='Venue city')
    venue_state: str | None = Field(None, min_length=1, description="Venue state or province code, in whatever form the business's country uses, e.g. `MA`")
    venue_zip: str | None = Field(None, min_length=1, description='Venue postal code')
    public_notes: str | None = Field(None, min_length=1, description='Notes visible to the client')
    private_notes: str | None = Field(None, min_length=1, description='Notes only staff can see')
    brand_id: int | None = Field(None, gt=0, description='Brand to propose under, which must be an active brand of this business. Defaults to the primary brand.')
    lead_id: int | None = Field(None, gt=0, description="Lead this proposal converts, from `GET /api/v1/leads`. The lead's details and attribution carry over and it is marked converted.")
    proposal_date_reserved: bool | None = Field(None, description='Hold the date while the client decides, blocking other bookings. Defaults to `false`.')
    proposal_valid_through: date | None = Field(None, description="Last day the client can accept, as `YYYY-MM-DD`. Must not be in the past, and is capped at the event date. Defaults to the business's own expiry setting.")
    contact_type: Literal["New Customer"] = Field("New Customer", description="Creates a new customer contact.")


class ListAppointmentsConfig(_Operation):
    'Fetch all appointments'
    operation: Literal['list_appointments'] = Field('list_appointments', json_schema_extra={"ui:hidden": True})
    start_date: date | None = Field(None, description='Filter by start date (YYYY-MM-DD)')
    end_date: date | None = Field(None, description='Filter by end date (YYYY-MM-DD)')
    staff_id: str | None = Field(None, min_length=1, description="Filter by staff member ID, or 'my' for the authenticated user")
    brand_id: int | None = Field(None, gt=0, description='Filter by brand ID')
    canceled_status: str | None = Field(None, min_length=1, description='Filter by cancellation status')
    past_or_future: str | None = Field(None, min_length=1, description='Filter to past or future appointments')
    search_text: str | None = Field(None, min_length=1, description='Full-text search across appointment details')
    page: int = Field(1, ge=1, le=10000, description='Page number for pagination (default: 1)')
    per: int = Field(25, ge=1, le=100, description='Number of results per page (default: 25)')


class GetAppointmentConfig(_Operation):
    'Fetch an appointment by ID'
    operation: Literal['get_appointment'] = Field('get_appointment', json_schema_extra={"ui:hidden": True})
    include: str | None = Field(None, min_length=1, description='Related resources to sideload, comma-separated. The description lists what is available.')
    appointment_id: int = Field(..., gt=0, description='The unique ID of the appointment')


class CreateAppointmentConfig(_Operation):
    'Create an appointment'
    operation: Literal['create_appointment'] = Field('create_appointment', json_schema_extra={"ui:hidden": True})
    guest_name: str = Field(..., min_length=1, description='Guest name')
    guest_email: str = Field(..., min_length=1, description='Guest email address')
    guest_phone: str | None = Field(None, min_length=1, description='Guest phone number')
    additional_guests: str | None = Field(None, min_length=1, description='Additional guest names or details')
    starts_at_date: date = Field(..., description='Appointment date (YYYY-MM-DD)')
    starts_at_time: str = Field(..., min_length=1, description='Appointment start time (e.g., "2:00 PM")')
    length_in_minutes: int = Field(..., gt=0, description='Duration in minutes')
    location: str | None = Field(None, min_length=1, description='Appointment location (e.g., "Phone", "In Person")')
    private_notes: str | None = Field(None, min_length=1, description='Private internal notes')
    message: str | None = Field(None, min_length=1, description='Message to the guest')
    user_id: int | None = Field(None, gt=0, description='Staff member ID to assign (defaults to authenticated user)')
    brand_id: int | None = Field(None, gt=0, description='Brand ID (defaults to the primary brand)')
    user_appointment_calendar_id: int | None = Field(None, gt=0, description='Appointment calendar ID for scheduling')
    created_via: Literal['quick_add', 'widget', 'app'] = Field('app', description='How the appointment was created')


class UpdateAppointmentConfig(_Operation):
    'Update an appointment'
    operation: Literal['update_appointment'] = Field('update_appointment', json_schema_extra={"ui:hidden": True})
    appointment_id: int = Field(..., gt=0, description='The unique ID of the appointment')
    guest_name: str | None = Field(None, min_length=1, description='Guest name')
    guest_email: str | None = Field(None, min_length=1, description='Guest email address')
    guest_phone: str | None = Field(None, min_length=1, description='Guest phone number')
    additional_guests: str | None = Field(None, min_length=1, description='Additional guest names or details')
    starts_at_date: date | None = Field(None, description='New appointment date (YYYY-MM-DD)')
    starts_at_time: str | None = Field(None, min_length=1, description='New appointment start time (e.g., "2:00 PM")')
    length_in_minutes: int | None = Field(None, gt=0, description='Duration in minutes')
    location: str | None = Field(None, min_length=1, description='Appointment location')
    location_details: str | None = Field(None, min_length=1, description='Additional location details')
    private_notes: str | None = Field(None, min_length=1, description='Private internal notes')
    custom_title: str | None = Field(None, min_length=1, description='Custom title override')
    brand_id: int | None = Field(None, gt=0, description='Brand ID')

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", 'appointment_id'}):
            raise ValueError("Provide at least one field to update")
        return self


class CancelAppointmentConfig(_Operation):
    'Cancel an appointment'
    operation: Literal['cancel_appointment'] = Field('cancel_appointment', json_schema_extra={"ui:hidden": True})
    appointment_id: int = Field(..., gt=0, description='The unique ID of the appointment')


class ListPaymentsConfig(_Operation):
    'Fetch all payments'
    operation: Literal['list_payments'] = Field('list_payments', json_schema_extra={"ui:hidden": True})
    event_id: int | None = Field(None, gt=0, description='Filter payments by event ID')
    payment_date_start: date | None = Field(None, description='Filter payments on or after this date (YYYY-MM-DD)')
    payment_date_end: date | None = Field(None, description='Filter payments on or before this date (YYYY-MM-DD)')
    page: int = Field(1, ge=1, le=10000, description='Page number for pagination (default: 1)')
    per: int = Field(25, ge=1, le=100, description='Number of results per page (default: 25)')


class GetPaymentConfig(_Operation):
    'Fetch payment by ID'
    operation: Literal['get_payment'] = Field('get_payment', json_schema_extra={"ui:hidden": True})
    payment_id: int = Field(..., gt=0, description='The unique ID of the payment to retrieve')


class ListPackagesConfig(_Operation):
    'Fetch all packages'
    operation: Literal['list_packages'] = Field('list_packages', json_schema_extra={"ui:hidden": True})
    include: str | None = Field(None, min_length=1, description='Related resources to sideload, comma-separated. The description lists what is available.')
    visibility: str | None = Field(None, min_length=1, description="Filter by visibility (e.g., 'public_only')")


class GetPackageConfig(_Operation):
    'Fetch a package by ID'
    operation: Literal['get_package'] = Field('get_package', json_schema_extra={"ui:hidden": True})
    include: str | None = Field(None, min_length=1, description='Related resources to sideload, comma-separated. The description lists what is available.')
    package_id: int = Field(..., gt=0, description='The unique ID of the package')


CheckCherryOperation = Annotated[Union[
    ListLeadsConfig,
    GetLeadConfig,
    CreateLeadConfig,
    UpdateLeadConfig,
    ArchiveLeadConfig,
    UnarchiveLeadConfig,
    AddLeadNoteConfig,
    ListEventsConfig,
    GetEventConfig,
    UpdateEventConfig,
    CancelEventConfig,
    UncancelEventConfig,
    AddEventNoteConfig,
    CreateBookingConfig,
    CreateProposalConfig,
    ListAppointmentsConfig,
    GetAppointmentConfig,
    CreateAppointmentConfig,
    UpdateAppointmentConfig,
    CancelAppointmentConfig,
    ListPaymentsConfig,
    GetPaymentConfig,
    ListPackagesConfig,
    GetPackageConfig
], Field(discriminator="operation")]


class CheckCherryConfig(NodeConfig[CheckCherryOperation, CheckCherryCredential]):
    pass


# Fixed request contracts: method, path, path bindings, query fields, body fields.
ROUTES = {'list_leads': ('GET', '/api/v1/leads', {}, ['include', 'email', 'text', 'page', 'per'], []),
 'get_lead': ('GET', '/api/v1/leads/{lead_id}', {'lead_id': 'lead_id'}, ['include'], []),
 'create_lead': ('POST',
                 '/api/v1/leads',
                 {},
                 [],
                 ['email',
                  'first_name',
                  'last_name',
                  'phone',
                  'company_name',
                  'lead_source',
                  'contact_preference',
                  'notes',
                  'custom_questions']),
 'update_lead': ('PUT',
                 '/api/v1/leads/{lead_id}',
                 {'lead_id': 'lead_id'},
                 [],
                 ['email',
                  'first_name',
                  'last_name',
                  'phone',
                  'company_name',
                  'lead_source',
                  'contact_preference',
                  'notes',
                  'starts_at_date',
                  'starts_at_time',
                  'length_in_minutes',
                  'package_id',
                  'service_id',
                  'staff_id',
                  'next_follow_up_on',
                  'custom_questions']),
 'archive_lead': ('PUT', '/api/v1/leads/{lead_id}/archive', {'lead_id': 'lead_id'}, [], []),
 'unarchive_lead': ('PUT', '/api/v1/leads/{lead_id}/unarchive', {'lead_id': 'lead_id'}, [], []),
 'add_lead_note': ('POST',
                   '/api/v1/leads/{lead_id}/notes',
                   {'lead_id': 'lead_id'},
                   [],
                   ['note', 'next_follow_up_on']),
 'list_events': ('GET',
                 '/api/v1/events',
                 {},
                 ['include',
                  'event_status',
                  'canceled_status',
                  'postponed_status',
                  'expired_status',
                  'past_or_future',
                  'event_date_start',
                  'event_date_end',
                  'booked_date_start',
                  'booked_date_end',
                  'updated_since',
                  'search_text',
                  'id',
                  'brand_id',
                  'client_id',
                  'staff_id',
                  'event_category_id',
                  'proposal_viewed',
                  'recurring_event_id',
                  'awaiting_deposit',
                  'balance_outstanding',
                  'past_due',
                  'has_unselected_templates',
                  'has_pending_artwork',
                  'has_unapproved_artwork',
                  'unsubmitted_forms',
                  'no_staff_assigned',
                  'no_backdrop_assigned',
                  'sort_by',
                  'page',
                  'per'],
                 []),
 'get_event': ('GET', '/api/v1/events/{event_id}', {'event_id': 'event_id'}, ['include'], []),
 'update_event': ('PUT',
                  '/api/v1/events/{event_id}',
                  {'event_id': 'event_id'},
                  [],
                  ['public_notes',
                   'photo_album_url',
                   'photo_album_instructions',
                   'video_url',
                   'video_album_instructions',
                   'next_follow_up_on']),
 'cancel_event': ('PUT',
                  '/api/v1/events/{event_id}/cancel',
                  {'event_id': 'event_id'},
                  [],
                  ['cancel_reason', 'send_cancellation_messages']),
 'uncancel_event': ('PUT', '/api/v1/events/{event_id}/uncancel', {'event_id': 'event_id'}, [], []),
 'add_event_note': ('POST',
                    '/api/v1/events/{event_id}/notes',
                    {'event_id': 'event_id'},
                    [],
                    ['note', 'next_follow_up_on']),
 'create_booking': ('POST',
                    '/api/v1/bookings',
                    {},
                    [],
                    ['packages',
                     'contact_name',
                     'contact_email',
                     'contact_phone',
                     'contact_company_name',
                     'venue_name',
                     'venue_address',
                     'venue_city',
                     'venue_state',
                     'venue_zip',
                     'public_notes',
                     'private_notes',
                     'brand_id',
                     'lead_id',
                     'signature_collected',
                     'send_booking_confirmation_emails',
                     'send_contact_invitation_to_create_account',
                     'contact_type']),
 'create_proposal': ('POST',
                     '/api/v1/proposals',
                     {},
                     [],
                     ['packages',
                      'contact_name',
                      'contact_email',
                      'contact_phone',
                      'contact_company_name',
                      'venue_name',
                      'venue_address',
                      'venue_city',
                      'venue_state',
                      'venue_zip',
                      'public_notes',
                      'private_notes',
                      'brand_id',
                      'lead_id',
                      'proposal_date_reserved',
                      'proposal_valid_through',
                      'contact_type']),
 'list_appointments': ('GET',
                       '/api/v1/appointments',
                       {},
                       ['start_date',
                        'end_date',
                        'staff_id',
                        'brand_id',
                        'canceled_status',
                        'past_or_future',
                        'search_text',
                        'page',
                        'per'],
                       []),
 'get_appointment': ('GET', '/api/v1/appointments/{id}', {'id': 'appointment_id'}, ['include'], []),
 'create_appointment': ('POST',
                        '/api/v1/appointments',
                        {},
                        [],
                        ['guest_name',
                         'guest_email',
                         'guest_phone',
                         'additional_guests',
                         'starts_at_date',
                         'starts_at_time',
                         'length_in_minutes',
                         'location',
                         'private_notes',
                         'message',
                         'user_id',
                         'brand_id',
                         'user_appointment_calendar_id',
                         'created_via']),
 'update_appointment': ('PUT',
                        '/api/v1/appointments/{id}',
                        {'id': 'appointment_id'},
                        [],
                        ['guest_name',
                         'guest_email',
                         'guest_phone',
                         'additional_guests',
                         'starts_at_date',
                         'starts_at_time',
                         'length_in_minutes',
                         'location',
                         'location_details',
                         'private_notes',
                         'custom_title',
                         'brand_id']),
 'cancel_appointment': ('PUT', '/api/v1/appointments/{id}/cancel', {'id': 'appointment_id'}, [], []),
 'list_payments': ('GET',
                   '/api/v1/event_payments',
                   {},
                   ['event_id', 'payment_date_start', 'payment_date_end', 'page', 'per'],
                   []),
 'get_payment': ('GET', '/api/v1/event_payments/{id}', {'id': 'payment_id'}, [], []),
 'list_packages': ('GET', '/api/v1/packages', {}, ['include', 'visibility'], []),
 'get_package': ('GET', '/api/v1/packages/{id}', {'id': 'package_id'}, ['include'], [])}


class CheckCherryNode(WorkflowNode):
    integration_type = "automation-check-cherry"
    connection_evidence = ConnectionEvidence(operation="list_leads", noun="leads")

    @classmethod
    def get_config_model(cls):
        return CheckCherryConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Check Cherry integration key")
        config = self.config.config
        method, path, bindings, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = path.format(**{wire: values[field] for wire, field in bindings.items()})
        params = {field: values[field] for field in query_fields if field in values}
        body = {field: values[field] for field in body_fields if field in values}
        token = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Api-Key": token, "Accept": "application/json"}, params=params,
                    **({"json": body} if body_fields else {}))
        except httpx.HTTPError:
            raise ValueError("Check Cherry request could not be completed; inspect writes before retrying") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Check Cherry returned a non-JSON response (HTTP {response.status_code})") from None
        if not isinstance(payload, dict):
            raise ValueError("Check Cherry returned an unexpected response shape")
        meta = payload.get("meta")
        if not 200 <= response.status_code < 300 or (isinstance(meta, dict) and meta.get("status") == "error") or payload.get("errors"):
            message = payload.get("message") or payload.get("reason") or f"Check Cherry rejected the request (HTTP {response.status_code})"
            raise ValueError(f"Check Cherry HTTP {response.status_code}: " + str(message).replace(token, "[redacted]"))
        data = payload.get("data")
        if config.operation.startswith("list_"):
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Check Cherry returned an unexpected resource list")
        elif config.operation == "add_lead_note":
            if not isinstance(meta, dict) or meta.get("status") != "ok":
                raise ValueError("Check Cherry did not acknowledge the note")
        elif not isinstance(data, dict):
            raise ValueError("Check Cherry returned an unexpected resource")
        # Preserve additive provider fields, including the JSON:API resource envelope.
        def redact(value):
            if isinstance(value, str):
                return value.replace(token, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            return value
        result = redact(payload)
        result["status"] = "success"
        if config.operation.startswith("list_"):
            # Readable labels also let the shared connection-evidence seam show
            # the person's own leads instead of opaque JSON:API resource IDs.
            result["items"] = []
            for row in result["data"]:
                attrs = row.get("attributes") or {}
                if not isinstance(attrs, dict):
                    raise ValueError("Check Cherry returned unexpected resource attributes")
                label = attrs.get("title") or attrs.get("name") or " ".join(
                    str(attrs.get(part) or "") for part in ("first_name", "last_name")
                ).strip() or attrs.get("email") or row.get("id")
                result["items"].append({**attrs, "id": row.get("id"), "name": label})
        if config.operation.startswith("list_") and isinstance(meta, dict):
            page, total = meta.get("page"), meta.get("total_pages")
            if type(page) is int and type(total) is int:
                result["next_page"] = page + 1 if page < total else None
        await self.emit(result)
        return result
