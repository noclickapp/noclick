"""NeetoCal workspace API v2: bookings, scheduling links and availability.

Contract: https://apidocs.neetocal.com/api/introduction (published bundled specs).
Webhooks are configured in NeetoCal's UI, so booking changes use scheduled polling
ordered by creation date. A poll scans at most 2,000 bookings; larger workspaces
must narrow the host/client scope. A failed or incomplete scan never advances state.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class NeetoCalAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="NeetoCal API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://apidocs.neetocal.com/api/authentication",
            "x-credential-instructions": "Create a workspace API key in NeetoCal's Admin Panel → API keys. Paste the key and your workspace subdomain, for example spinkart for spinkart.neetocal.com. NoClick sends X-Api-Key only to this workspace's NeetoCal API.",
        })
    credential_type: Literal["neetocal_api_key"] = Field("neetocal_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    subdomain: str = Field(..., title="Workspace Subdomain", description="The workspace part of your NeetoCal address, for example spinkart.")

    @field_validator("subdomain", mode="before")
    @classmethod
    def workspace(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value.strip().lower()):
            raise ValueError("Enter the workspace subdomain only, without a URL or dots")
        return value.strip().lower()

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if len(value) > 4096 or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def resource_ids(cls, value, info):
        if info.field_name in {"meeting_sid", "booking_sid", "booking_id", "team_member_id", "availability_id", "id"}:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
                raise ValueError("Enter a single NeetoCal resource ID")
        return value


class NeetoCalListBookingsConfig(_Input):
    """List bookings."""
    operation: Literal['list_bookings'] = Field('list_bookings', title='List bookings', json_schema_extra={"ui:hidden": True})
    type: str | None = Field(None, title='Type')
    page_number: int = Field(1, title='Page Number', ge=1, le=100000)
    page_size: int = Field(30, title='Page Size', ge=1, le=100)
    host_email: str | None = Field(None, title='Host Email')
    client_email: str | None = Field(None, title='Client Email')
    parent_booking_id: str | None = Field(None, title='Parent Booking Id')
    sorting_order: Literal['asc', 'desc'] | None = Field(None, title='Sorting Order')


class NeetoCalGetBookingConfig(_Input):
    """Get booking details."""
    operation: Literal['get_booking'] = Field('get_booking', title='Get booking details', json_schema_extra={"ui:hidden": True})
    booking_sid: str = Field(..., title='Booking Sid')


class NeetoCalCreateBookingConfig(_Input):
    """Create a booking."""
    operation: Literal['create_booking'] = Field('create_booking', title='Create a booking', json_schema_extra={"ui:hidden": True})
    meeting_slug: str = Field(..., title='Meeting Slug', description='Slug of scheduling link you want to book.')
    name: str = Field(..., title='Name', description='Name of person making the booking.')
    email: str = Field(..., title='Email', description='Email of person making the booking.')
    slot_date: str | None = Field(None, title='Slot Date', description='Date on which you want to book. This should be in "YYYY-MM-DD" format. If `slot_date` and `slot_start_time` are not provided then the first available slot will be booked. Both are required when `override_availability` is `true`.')
    slot_start_time: str | None = Field(None, title='Slot Start Time', description='Start time for the booking. This should be in "HH:MM AM/PM" format.')
    time_zone: str = Field(..., title='Time Zone', description='Time zone of person making the booking.')
    preferred_meeting_spot: Literal['custom', 'jitsi', 'in_person', 'daily', 'zoom', 'whereby', 'google_meet', 'teams'] | None = Field(None, title='Preferred Meeting Spot', description='Your preferred meeting place. This field is optional. Before passing this value, ensure that the corresponding meeting place is configured in the "Where" section of the scheduling link.\n')
    form_responses: dict[str, Any] | None = Field(None, title='Form Responses', description="Responses for the questions of booking form (optional). The key of the field should be the field code of the question. The field code can be found in scheduling link's Settings -> Questions -> 3 dot menu of the question -> Edit -> Advanced properties. You can specify guest emails using the `guest_email_s` field code.")
    add_on_service_ids: list[str] | None = Field(None, title='Add On Service Ids', description="IDs of the [add-on services](/api/add-on-services/list) to include in the booking. The booking's duration and the amount charged include the chosen add-on services. When `slot_date` and `slot_start_time` are omitted, the first slot long enough for the add-on services is booked. Returns a 422 error if an ID does not belong to the scheduling link, or if more than one is passed while the scheduling link's `allow_multiple_add_on_services` is `false`.\n")
    host_email: str | None = Field(None, title='Host Email', description='Email of the host to assign the booking to, for scheduling links with more than one host. Allowed only when `override_availability` is `true` or the scheduling link lets clients choose the host. When omitted, the host is assigned automatically. You can get the host emails from the `hosts` array in the [Get scheduling link](/api/scheduling-links/get) response.\n')

    @model_validator(mode="after")
    def slot_pair(self):
        if bool(self.slot_date) != bool(self.slot_start_time):
            raise ValueError("Supply both slot date and start time, or neither to book the first available slot")
        return self


class NeetoCalUpdateBookingConfig(_Input):
    """Update a booking."""
    operation: Literal['update_booking'] = Field('update_booking', title='Update a booking', json_schema_extra={"ui:hidden": True})
    booking_id: str = Field(..., title='Booking Id')
    name: str | None = Field(None, title='Name', description='Name of person making the booking. This is applied only as part of a reschedule, so send it alongside `slot_date` and `slot_start_time`. A request carrying it without them is rejected with a 422 error.')
    email: str | None = Field(None, title='Email', description='Email of person making the booking. This is applied only as part of a reschedule, so send it alongside `slot_date` and `slot_start_time`. A request carrying it without them is rejected with a 422 error.')
    slot_date: str | None = Field(None, title='Slot Date', description='Date on which the booking is to be rescheduled. This should be in "YYYY-MM-DD" format.')
    slot_start_time: str | None = Field(None, title='Slot Start Time', description='Start time for the booking. This should be in "HH:MM AM/PM" format.')
    time_zone: str | None = Field(None, title='Time Zone', description='Time zone of person rescheduling the booking.')
    reschedule_reason: str | None = Field(None, title='Reschedule Reason', description='Reason for rescheduling the booking (optional).')
    status: Literal['cancelled', 'approved', 'rejected'] | None = Field(None, title='Status', description='Sets booking lifecycle status in one call (replaces v1 approve / reject / cancel endpoints). Use `approved` to approve, `rejected` to reject (optional `rejection_reason`), or `cancelled` to cancel (optional `cancel_reason`). Do not send this field when you are only rescheduling or updating other attributes.\n')
    cancel_reason: str | None = Field(None, title='Cancel Reason', description='Reason for cancelling the booking. Used when status is `cancelled`.')
    rejection_reason: str | None = Field(None, title='Rejection Reason', description='Reason for rejecting the booking. Used when status is `rejected`.')
    meeting_outcome_id: str | None = Field(None, title='Meeting Outcome Id', description="Assign a meeting outcome to the booking by providing the outcome's ID. Pass `null` to remove the currently assigned outcome. This parameter cannot be combined with `status` or reschedule parameters (`slot_date`, `slot_start_time`) in the same request. Meeting outcomes can only be set on confirmed or parallel-error bookings. You can get the outcome ID from the [List meeting outcomes](/api/meeting-outcomes/list) endpoint.\n")

    @model_validator(mode="after")
    def compatible_changes(self):
        reschedule = self.slot_date is not None or self.slot_start_time is not None
        if reschedule and not (self.slot_date and self.slot_start_time and self.time_zone):
            raise ValueError("Rescheduling needs date, start time and time zone")
        if (self.name is not None or self.email is not None) and not reschedule:
            raise ValueError("Name and email can only change during a reschedule")
        if "meeting_outcome_id" in self.model_fields_set and (self.status is not None or reschedule):
            raise ValueError("Change meeting outcome separately from status or rescheduling")
        if not self.model_fields_set - {"operation", "booking_id"}:
            raise ValueError("Choose a booking change")
        return self


class NeetoCalListSchedulingLinksConfig(_Input):
    """List scheduling links."""
    operation: Literal['list_scheduling_links'] = Field('list_scheduling_links', title='List scheduling links', json_schema_extra={"ui:hidden": True})
    page_number: int = Field(1, title='Page Number', ge=1, le=100000)
    page_size: int = Field(30, title='Page Size', ge=1, le=100)
    host_email: str | None = Field(None, title='Host Email', description='Single host email')
    search: str | None = Field(None, title='Search')


class NeetoCalGetSchedulingLinkConfig(_Input):
    """Get scheduling link details."""
    operation: Literal['get_scheduling_link'] = Field('get_scheduling_link', title='Get scheduling link details', json_schema_extra={"ui:hidden": True})
    meeting_sid: str = Field(..., title='Meeting Sid')


class NeetoCalCreateSchedulingLinkConfig(_Input):
    """Create a scheduling link."""
    operation: Literal['create_scheduling_link'] = Field('create_scheduling_link', title='Create a scheduling link', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., title='Slug', description='Slug of the scheduling link. This value should be unique.')
    name: str = Field(..., title='Name', description='Name of the scheduling link.')
    description: str | None = Field(None, title='Description', description='Description of the scheduling link.')
    hosts: list[str] = Field(..., title='Hosts', description='Emails of the hosts of scheduling link in array format.')
    kind: Literal['one_on_one', 'round_robin', 'multihost', 'grouped'] | None = Field(None, title='Kind', description='Kind of scheduling link.')
    duration: int = Field(..., title='Duration', description='Duration of the scheduling link in minutes.', ge=1, le=1440)
    start_time_increment: int | None = Field(None, title='Start Time Increment', description='Start time increment for the scheduling link in minutes. Defaults to 30.')
    before_buffer_time: int | None = Field(None, title='Before Buffer Time', description='Buffer time in minutes before each meeting to allow for setup, preparation, or travel time. Must be between 0 and 1440 (24 hours).', ge=0, le=1440)
    after_buffer_time: int | None = Field(None, title='After Buffer Time', description='Buffer time in minutes after each meeting to allow for wrap-up, notes, or preparation for the next meeting. Must be between 0 and 1440 (24 hours).', ge=0, le=1440)
    locked_time_zone: str | None = Field(None, title='Locked Time Zone', description="Time zone to lock the scheduling link to. When set, all available times are displayed in this time zone regardless of the booker's location. Must be a valid IANA time zone identifier (e.g., 'America/New_York', 'Europe/London').")


class NeetoCalUpdateSchedulingLinkConfig(_Input):
    """Update a scheduling link."""
    operation: Literal['update_scheduling_link'] = Field('update_scheduling_link', title='Update a scheduling link', json_schema_extra={"ui:hidden": True})
    meeting_sid: str = Field(..., title='Meeting Sid')
    slug: str | None = Field(None, title='Slug', description='New slug of the scheduling link. This value should be unique.')
    name: str | None = Field(None, title='Name', description='New name of the scheduling link.')
    description: str | None = Field(None, title='Description', description='Description of the scheduling link.')
    hosts: list[str] = Field(..., title='Hosts', description='Emails of the hosts of scheduling link in array format.')
    kind: Literal['one_on_one', 'round_robin', 'multihost', 'grouped'] | None = Field(None, title='Kind', description='Kind of scheduling link.')
    duration: int | None = Field(None, title='Duration', description='Duration of the scheduling link in minutes.', ge=1, le=1440)
    start_time_increment: int | None = Field(None, title='Start Time Increment', description='Start time increment for the scheduling link in minutes. Defaults to 30.')
    before_buffer_time: int | None = Field(None, title='Before Buffer Time', description='Buffer time in minutes before each meeting to allow for setup, preparation, or travel time. Must be between 0 and 1440 (24 hours).', ge=0, le=1440)
    after_buffer_time: int | None = Field(None, title='After Buffer Time', description='Buffer time in minutes after each meeting to allow for wrap-up, notes, or preparation for the next meeting. Must be between 0 and 1440 (24 hours).', ge=0, le=1440)
    locked_time_zone: str | None = Field(None, title='Locked Time Zone', description="Time zone to lock the scheduling link to. When set, all available times are displayed in this time zone regardless of the booker's location. Must be a valid IANA time zone identifier (e.g., 'America/New_York', 'Europe/London').")


class NeetoCalDeleteSchedulingLinkConfig(_Input):
    """Delete a scheduling link."""
    operation: Literal['delete_scheduling_link'] = Field('delete_scheduling_link', title='Delete a scheduling link', json_schema_extra={"ui:hidden": True})
    meeting_sid: str = Field(..., title='Meeting Sid')


class NeetoCalCreateOneOffLinkConfig(_Input):
    """Create a one-time scheduling link."""
    operation: Literal['create_one_off_link'] = Field('create_one_off_link', title='Create a one-time scheduling link', json_schema_extra={"ui:hidden": True})
    meeting_sid: str = Field(..., title='Meeting Sid')


class NeetoCalListTeamMembersConfig(_Input):
    """List team members."""
    operation: Literal['list_team_members'] = Field('list_team_members', title='List team members', json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, title='Email')
    page_number: int = Field(1, title='Page Number', ge=1, le=100000)
    page_size: int = Field(30, title='Page Size', ge=1, le=100)


class NeetoCalGetTeamMemberConfig(_Input):
    """Get team member details."""
    operation: Literal['get_team_member'] = Field('get_team_member', title='Get team member details', json_schema_extra={"ui:hidden": True})
    team_member_id: str = Field(..., title='Team Member Id')


class NeetoCalListAvailableSlotsConfig(_Input):
    """List available slots."""
    operation: Literal['list_available_slots'] = Field('list_available_slots', title='List available slots', json_schema_extra={"ui:hidden": True})
    meeting_sid: str = Field(..., title='Meeting Sid')
    time_zone: str = Field(..., title='Time Zone')
    year: str = Field(..., title='Year')
    month: str = Field(..., title='Month')
    day: str | None = Field(None, title='Day')
    duration: int | None = Field(None, title='Duration', ge=1, le=1440)
    host_email: str | None = Field(None, title='Host Email')


class NeetoCalListAvailabilitiesConfig(_Input):
    """List availabilities of the team members."""
    operation: Literal['list_availabilities'] = Field('list_availabilities', title='List availabilities of the team members', json_schema_extra={"ui:hidden": True})
    emails: list[str] = Field(..., title='Emails')
    page_number: int = Field(1, title='Page Number', ge=1, le=100000)
    page_size: int = Field(30, title='Page Size', ge=1, le=100)


class NeetoCalGetAvailabilityConfig(_Input):
    """Get availability details."""
    operation: Literal['get_availability'] = Field('get_availability', title='Get availability details', json_schema_extra={"ui:hidden": True})
    availability_id: str = Field(..., title='Availability Id')


class NeetoCalListDurationsConfig(_Input):
    """List durations for a meeting."""
    operation: Literal['list_durations'] = Field('list_durations', title='List durations for a meeting', json_schema_extra={"ui:hidden": True})
    meeting_sid: str = Field(..., title='Meeting Sid')


class NeetoCalListSpotsConfig(_Input):
    """List places for a meeting."""
    operation: Literal['list_spots'] = Field('list_spots', title='List places for a meeting', json_schema_extra={"ui:hidden": True})
    meeting_sid: str = Field(..., title='Meeting Sid')


class NeetoCalListMeetingOutcomesConfig(_Input):
    """List meeting outcomes."""
    operation: Literal['list_meeting_outcomes'] = Field('list_meeting_outcomes', title='List meeting outcomes', json_schema_extra={"ui:hidden": True})
    search_term: str | None = Field(None, title='Search Term')


class NeetoCalGetMeetingOutcomeConfig(_Input):
    """Get a meeting outcome."""
    operation: Literal['get_meeting_outcome'] = Field('get_meeting_outcome', title='Get a meeting outcome', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Id')


class NeetoCalCreateMeetingOutcomeConfig(_Input):
    """Create a meeting outcome."""
    operation: Literal['create_meeting_outcome'] = Field('create_meeting_outcome', title='Create a meeting outcome', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name', description='Name of the meeting outcome.')
    color: Literal['blue', 'orange', 'gray', 'red', 'yellow', 'violet', 'pink', 'teal', 'cyan', 'green'] = Field(..., title='Color', description='Color for the meeting outcome.')


class NeetoCalUpdateMeetingOutcomeConfig(_Input):
    """Rename or recolor a meeting outcome."""
    operation: Literal['update_meeting_outcome'] = Field('update_meeting_outcome', title='Rename or recolor a meeting outcome', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Id')
    name: str | None = Field(None, title='Name', description='Name of the meeting outcome.')
    color: Literal['blue', 'orange', 'gray', 'red', 'yellow', 'violet', 'pink', 'teal', 'cyan', 'green'] | None = Field(None, title='Color', description='Color for the meeting outcome.')


class NeetoCalDeleteMeetingOutcomeConfig(_Input):
    """Delete a meeting outcome."""
    operation: Literal['delete_meeting_outcome'] = Field('delete_meeting_outcome', title='Delete a meeting outcome', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Id')


class NeetoCalOnNewBookingConfig(PollTriggerConfigBase):
    operation: Literal["on_new_booking"] = Field("on_new_booking", title="On New Booking", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Booking"})
    host_email: str | None = Field(None, title="Host Email", description="Only watch bookings for this host.")
    client_email: str | None = Field(None, title="Client Email", description="Only watch bookings from this client.")

class NeetoCalOnNewOrUpdatedBookingConfig(NeetoCalOnNewBookingConfig):
    operation: Literal["on_new_or_updated_booking"] = Field("on_new_or_updated_booking", title="On New or Updated Booking", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated Booking"})


NeetoCalConfig = Annotated[Union[NeetoCalListBookingsConfig, NeetoCalGetBookingConfig, NeetoCalCreateBookingConfig, NeetoCalUpdateBookingConfig, NeetoCalListSchedulingLinksConfig, NeetoCalGetSchedulingLinkConfig, NeetoCalCreateSchedulingLinkConfig, NeetoCalUpdateSchedulingLinkConfig, NeetoCalDeleteSchedulingLinkConfig, NeetoCalCreateOneOffLinkConfig, NeetoCalListTeamMembersConfig, NeetoCalGetTeamMemberConfig, NeetoCalListAvailableSlotsConfig, NeetoCalListAvailabilitiesConfig, NeetoCalGetAvailabilityConfig, NeetoCalListDurationsConfig, NeetoCalListSpotsConfig, NeetoCalListMeetingOutcomesConfig, NeetoCalGetMeetingOutcomeConfig, NeetoCalCreateMeetingOutcomeConfig, NeetoCalUpdateMeetingOutcomeConfig, NeetoCalDeleteMeetingOutcomeConfig, NeetoCalOnNewBookingConfig, NeetoCalOnNewOrUpdatedBookingConfig], Field(discriminator="operation")]


class NeetoCalNodeConfig(NodeConfig[NeetoCalConfig, NeetoCalAPIKeyCredential]):
    pass


# (method, route, query fields, body fields, body wrapper, wire names)
OPERATIONS = {'list_bookings': ('GET',
                   '/bookings',
                   ['type',
                    'page_number',
                    'page_size',
                    'host_email',
                    'client_email',
                    'parent_booking_id',
                    'sorting_order'],
                   [],
                   None,
                   {'type': 'type',
                    'page_number': 'page_number',
                    'page_size': 'page_size',
                    'host_email': 'host_email',
                    'client_email': 'client_email',
                    'parent_booking_id': 'parent_booking_id',
                    'sorting_order': 'sorting_order'}),
 'get_booking': ('GET', '/bookings/{booking_sid}', [], [], None, {'booking_sid': 'booking_sid'}),
 'create_booking': ('POST',
                    '/bookings',
                    [],
                    ['meeting_slug',
                     'name',
                     'email',
                     'slot_date',
                     'slot_start_time',
                     'time_zone',
                     'preferred_meeting_spot',
                     'form_responses',
                     'add_on_service_ids',
                     'host_email'],
                    None,
                    {}),
 'update_booking': ('PATCH',
                    '/bookings/{booking_id}',
                    [],
                    ['name',
                     'email',
                     'slot_date',
                     'slot_start_time',
                     'time_zone',
                     'reschedule_reason',
                     'status',
                     'cancel_reason',
                     'rejection_reason',
                     'meeting_outcome_id'],
                    None,
                    {'booking_id': 'booking_id'}),
 'list_scheduling_links': ('GET',
                           '/meetings',
                           ['page_number', 'page_size', 'host_email', 'search'],
                           [],
                           None,
                           {'page_number': 'page_number',
                            'page_size': 'page_size',
                            'host_email': 'host_email',
                            'search': 'search'}),
 'get_scheduling_link': ('GET',
                         '/meetings/{meeting_sid}',
                         [],
                         [],
                         None,
                         {'meeting_sid': 'meeting_sid'}),
 'create_scheduling_link': ('POST',
                            '/meetings',
                            [],
                            ['slug',
                             'name',
                             'description',
                             'hosts',
                             'kind',
                             'duration',
                             'start_time_increment',
                             'before_buffer_time',
                             'after_buffer_time',
                             'locked_time_zone'],
                            None,
                            {}),
 'update_scheduling_link': ('PATCH',
                            '/meetings/{meeting_sid}',
                            [],
                            ['slug',
                             'name',
                             'description',
                             'hosts',
                             'kind',
                             'duration',
                             'start_time_increment',
                             'before_buffer_time',
                             'after_buffer_time',
                             'locked_time_zone'],
                            None,
                            {'meeting_sid': 'meeting_sid'}),
 'delete_scheduling_link': ('DELETE',
                            '/meetings/{meeting_sid}',
                            [],
                            [],
                            None,
                            {'meeting_sid': 'meeting_sid'}),
 'create_one_off_link': ('POST',
                         '/meetings/{meeting_sid}/one-off-links',
                         [],
                         [],
                         None,
                         {'meeting_sid': 'meeting_sid'}),
 'list_team_members': ('GET',
                       '/team-members',
                       ['email', 'page_number', 'page_size'],
                       [],
                       None,
                       {'email': 'email', 'page_number': 'page_number', 'page_size': 'page_size'}),
 'get_team_member': ('GET',
                     '/team-members/{team_member_id}',
                     [],
                     [],
                     None,
                     {'team_member_id': 'team_member_id'}),
 'list_available_slots': ('GET',
                          '/meetings/{meeting_sid}/slots',
                          ['time_zone', 'year', 'month', 'day', 'duration', 'host_email'],
                          [],
                          None,
                          {'meeting_sid': 'meeting_sid',
                           'time_zone': 'time_zone',
                           'year': 'year',
                           'month': 'month',
                           'day': 'day',
                           'duration': 'duration',
                           'host_email': 'host_email'}),
 'list_availabilities': ('GET',
                         '/availabilities',
                         ['emails', 'page_number', 'page_size'],
                         [],
                         None,
                         {'emails': 'emails[]',
                          'page_number': 'page_number',
                          'page_size': 'page_size'}),
 'get_availability': ('GET',
                      '/availabilities/{availability_id}',
                      [],
                      [],
                      None,
                      {'availability_id': 'availability_id'}),
 'list_durations': ('GET',
                    '/meetings/{meeting_sid}/durations',
                    [],
                    [],
                    None,
                    {'meeting_sid': 'meeting_sid'}),
 'list_spots': ('GET',
                '/meetings/{meeting_sid}/spots',
                [],
                [],
                None,
                {'meeting_sid': 'meeting_sid'}),
 'list_meeting_outcomes': ('GET',
                           '/meeting-outcomes',
                           ['search_term'],
                           [],
                           None,
                           {'search_term': 'search_term'}),
 'get_meeting_outcome': ('GET', '/meeting-outcomes/{id}', [], [], None, {'id': 'id'}),
 'create_meeting_outcome': ('POST',
                            '/meeting-outcomes',
                            [],
                            ['name', 'color'],
                            'meeting_outcome',
                            {}),
 'update_meeting_outcome': ('PATCH',
                            '/meeting-outcomes/{id}',
                            [],
                            ['name', 'color'],
                            'meeting_outcome',
                            {'id': 'id'}),
 'delete_meeting_outcome': ('DELETE', '/meeting-outcomes/{id}', [], [], None, {'id': 'id'})}


class NeetoCalNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-neetocal"
    connection_evidence = ConnectionEvidence(operation="list_scheduling_links", noun="scheduling links")
    edit_examples = ["Create a NeetoCal booking", "Cancel a NeetoCal booking", "Find available appointment slots", "Watch for new NeetoCal bookings"]

    @classmethod
    def get_config_model(cls):
        return NeetoCalNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a NeetoCal workspace")
        url = f"https://{credential.subdomain}.neetocal.com/api/external/v2{path}"
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, headers={
                "X-Api-Key": credential.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Preserve provider errors for the shared connect verdict; never echo headers.
            detail = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"NeetoCal HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            return None
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("NeetoCal returned an unexpected JSON response")
        return payload

    async def _poll_bookings(self, config):
        bookings = []
        for page in range(1, 21):
            params = {"page_number": page, "page_size": 100, "sorting_order": "desc"}
            for key in ("host_email", "client_email"):
                if getattr(config, key):
                    params[key] = getattr(config, key)
            data = await self._request("GET", "/bookings", params=params)
            rows = data.get("bookings")
            if not isinstance(rows, list) or any(not isinstance(r, dict) or not r.get("id") for r in rows):
                raise ValueError("NeetoCal bookings response is missing booking IDs")
            bookings.extend(rows)
            pagination = data.get("pagination") or {}
            total_pages = pagination.get("total_pages")
            if (isinstance(total_pages, int) and page >= total_pages) or (total_pages is None and len(rows) < 100):
                break
        else:
            raise ValueError("More than 2,000 bookings; narrow the host or client email before polling")
        if config.operation == "on_new_or_updated_booking":
            if any(not row.get("updated_at") for row in bookings):
                raise ValueError("NeetoCal bookings response is missing update timestamps")
            fresh = await self._filter_unseen(bookings, lambda row: f"{row['id']}:{row['updated_at']}")
        else:
            fresh = await self._filter_unseen(bookings, lambda row: str(row["id"]))
        return {"bookings": fresh, "new_booking_count": len(fresh), "booking_event": "new or updated" if config.operation == "on_new_or_updated_booking" else "new"}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_booking_count")) if config.get("operation") in {"on_new_booking", "on_new_or_updated_booking"} else True

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("bookings") if isinstance(output, dict) else None
        if not isinstance(rows, list):
            return super().resolve_agent_event(output)
        if not rows:
            return None
        lines = [f"- {r.get('name') or 'Client'} <{r.get('email') or ''}> booked {r.get('meeting', {}).get('name') or 'an appointment'} with {r.get('host_name') or r.get('host_email') or 'a host'} at {r.get('starts_at') or 'an unspecified time'}; status {r.get('status') or 'unspecified'}, updated {r.get('updated_at') or ''}; booking {r.get('sid') or r['id']}, scheduling link {r.get('meeting_id') or ''}; {r.get('admin_booking_url') or ''}" for r in rows[:10]]
        return {"text": f"NeetoCal: {len(rows)} {output.get('booking_event') or 'new'} booking(s):\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        if not self.config.credentials:
            raise ValueError("Connect a NeetoCal workspace")
        if isinstance(config, NeetoCalOnNewBookingConfig):
            return await self._poll_bookings(config)
        method, path, query, body_keys, wrapper, rename = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        for key in re.findall(r"{([^}]+)}", path):
            path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        params = {rename.get(k, k): values[k] for k in query if k in values}
        body = {k: values[k] for k in body_keys if k in values}
        # Explicit null clears a booking's assigned meeting outcome.
        if config.operation == "update_booking" and "meeting_outcome_id" in config.model_fields_set:
            body["meeting_outcome_id"] = config.meeting_outcome_id
        if wrapper:
            body = {wrapper: body}
        payload = await self._request(method, path, params=params or None, body=body if body_keys else None)
        return {"status": "success", "data": payload}
