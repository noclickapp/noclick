"""Apptoto appointments, contacts, booking pages and conversation operations.

Each action makes one documented API call. Basic authentication uses the person's
username and API key; calendar reads provide account connection evidence.
"""
from __future__ import annotations

import base64
from datetime import date, datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.apptoto.com"


class ApptotoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Apptoto API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.apptoto.com/",
            "x-credential-instructions": "Enter your Apptoto username and the API key from Settings > Integrations > API. NoClick uses HTTP Basic authentication."
        })
    credential_type: Literal["apptoto_api_key"] = Field("apptoto_api_key", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, title="Username", description="Your Apptoto account username.")
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter your Apptoto username without a colon or control characters")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without spaces or an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="One-based page. Increase to retrieve the next page.")
    page_size: int = Field(30, ge=1, le=100, description="Results per request. This action returns one page.")


class _ID(_Input):
    id: int = Field(..., ge=1, title="Apptoto ID")


class GetUserInfo(_Input):
    operation: Literal["get_user_info"] = Field("get_user_info", title="Get User Information", json_schema_extra={"ui:hidden": True})


class ListCalendars(_Input):
    operation: Literal["list_calendars"] = Field("list_calendars", title="List Calendars", json_schema_extra={"ui:hidden": True})


class ListEvents(_Page):
    operation: Literal["list_events"] = Field("list_events", title="List Appointments", json_schema_extra={"ui:hidden": True})
    begin: date | None = Field(None, description="Include appointments on or after this date.")
    end: date | None = Field(None, description="Include appointments on or before this date.")
    q: str | None = Field(None, title="Search Query")
    calendar_id: int | None = Field(None, ge=1)
    phone_number: str | None = None
    email_address: str | None = None
    participant_id: int | None = Field(None, ge=1)
    include_deleted: bool = False
    include_conversations: bool = False
    include_total: bool = False


class GetEvent(_ID):
    operation: Literal["get_event"] = Field("get_event", title="Get Appointment", json_schema_extra={"ui:hidden": True})


class _EventFields(_Input):
    title: str | None = Field(None, min_length=1)
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    content: str | None = None
    external_id: str | None = None
    time_zone: str | None = None
    all_day: bool | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def aware_time(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Include the appointment's time zone offset")
        return value

    @model_validator(mode="after")
    def time_order(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("End time must be after start time")
        return self


class CreateEvent(_EventFields):
    operation: Literal["create_event"] = Field("create_event", title="Create Appointment", description="Apptoto may send automatic reminders according to the account's settings.", json_schema_extra={"ui:hidden": True})
    calendar_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    start_time: datetime
    end_time: datetime
    participants: list[dict] | None = Field(None, description="Participant objects with name, email, phone, or contact_id, as documented by Apptoto.")
    custom_data: dict | None = Field(None, description="Custom appointment fields.")


class UpdateEvent(_ID, _EventFields):
    operation: Literal["update_event"] = Field("update_event", title="Update Appointment", description="Fields supplied are patched. Participants and custom_data replace their entire collections; reminders may be sent.", json_schema_extra={"ui:hidden": True})
    participants: list[dict] | None = None
    custom_data: dict | None = None

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, name) is not None for name in _EventFields.model_fields) and self.participants is None and self.custom_data is None:
            raise ValueError("Supply at least one appointment field to update")
        return self


class DeleteEvent(_ID):
    operation: Literal["delete_event"] = Field("delete_event", title="Delete Appointment", description="Removes the appointment and halts its messages.", json_schema_extra={"ui:hidden": True})


class TagEvent(_Input):
    operation: Literal["tag_event"] = Field("tag_event", title="Add or Remove Appointment Tag", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title="Appointment ID")
    tag: str = Field(..., min_length=1)
    remove: Literal["true", "false"] = "false"


class ListParticipants(_Input):
    operation: Literal["list_participants"] = Field("list_participants", title="List Appointment Participants", json_schema_extra={"ui:hidden": True})
    event_id: int = Field(..., ge=1)
    include_conversations: bool = False


class AddParticipant(_Input):
    operation: Literal["add_participant"] = Field("add_participant", title="Add Appointment Participant", json_schema_extra={"ui:hidden": True})
    event_id: int = Field(..., ge=1)
    contact_id: int | None = Field(None, ge=1)
    name: str | None = None
    phone: str | None = None
    email: str | None = None

    @model_validator(mode="after")
    def participant_details(self):
        if not any((self.contact_id, self.name, self.phone, self.email)):
            raise ValueError("Supply a contact ID or participant name, phone or email")
        return self


class UpdateParticipant(_ID):
    operation: Literal["update_participant"] = Field("update_participant", title="Update Participant RSVP", json_schema_extra={"ui:hidden": True})
    state: Literal["confirmed", "not_coming", "needs_reschedule", "initial"]


class DeleteParticipant(_ID):
    operation: Literal["delete_participant"] = Field("delete_participant", title="Delete Participant", description="Removes the participant and halts their messages.", json_schema_extra={"ui:hidden": True})


class ListAddressBooks(_Input):
    operation: Literal["list_address_books"] = Field("list_address_books", title="List Address Books", json_schema_extra={"ui:hidden": True})


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    address_book_id: int | None = Field(None, ge=1)
    q: str | None = Field(None, title="Search Query")


class GetContact(_ID):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class _ContactFields(_Input):
    name: str | None = Field(None, min_length=1)
    phone: str | None = None
    email: str | None = None
    external_id: str | None = None


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    address_book_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1)


class UpdateContact(_ID, _ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, name) is not None for name in _ContactFields.model_fields):
            raise ValueError("Supply at least one contact field to update")
        return self


class DeleteContact(_ID):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})


class TagContact(_Input):
    operation: Literal["tag_contact"] = Field("tag_contact", title="Add or Remove Contact Tag", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title="Contact ID")
    tag: str = Field(..., min_length=1)
    remove: Literal["true", "false"] = "false"


class ListBookingPages(_Page):
    operation: Literal["list_booking_pages"] = Field("list_booking_pages", title="List Booking Pages", json_schema_extra={"ui:hidden": True})


class BookAppointment(_Input):
    operation: Literal["book_appointment"] = Field("book_appointment", title="Book Appointment", description="Creates a booking and may send confirmations or reminders. Supply fields and consent required by the selected booking page.", json_schema_extra={"ui:hidden": True})
    booking_page: str = Field(..., min_length=1, description="Booking page ID or token, for example bookwithfred.")
    time: str = Field(..., min_length=1, description="Time to book, for example 2025-06-21T08:00:00, interpreted by the booking page.")
    appointment_type_token: str | None = None
    name: str | None = None
    phone_number: str | None = None
    email_address: str | None = None
    field_data: dict | None = Field(None, description="Values for the booking page's custom fields.")
    opted_into_text_messaging: bool | None = None
    opted_into_text_messaging_for_marketing: bool | None = None


class ListConversations(_Page):
    operation: Literal["list_conversations"] = Field("list_conversations", title="List Conversations", json_schema_extra={"ui:hidden": True})
    folder: Literal["inbox", "inbox-appointments", "inbox-campaigns", "inbox-other", "outbox", "outbox-appointments", "outbox-campaigns", "outbox-other", "archived", "spam"] = "inbox"
    q: str | None = None


class ListConversationMessages(_Input):
    operation: Literal["list_conversation_messages"] = Field("list_conversation_messages", title="List Conversation Messages", json_schema_extra={"ui:hidden": True})
    conversation_id: int = Field(..., ge=1)


class ListConversationTemplates(_Input):
    operation: Literal["list_conversation_templates"] = Field("list_conversation_templates", title="List Conversation Templates", json_schema_extra={"ui:hidden": True})


class ReplyToConversation(_Input):
    operation: Literal["reply_to_conversation"] = Field("reply_to_conversation", title="Reply to Conversation", description="Sends a message through the existing conversation's channel.", json_schema_extra={"ui:hidden": True})
    conversation_id: int = Field(..., ge=1)
    message: str = Field(..., min_length=1)
    and_archive: bool = False
    allow_number_change: bool = False


Operation = Annotated[Union[GetUserInfo, ListCalendars, ListEvents, GetEvent, CreateEvent, UpdateEvent, DeleteEvent, TagEvent, ListParticipants, AddParticipant, UpdateParticipant, DeleteParticipant, ListAddressBooks, ListContacts, GetContact, CreateContact, UpdateContact, DeleteContact, TagContact, ListBookingPages, BookAppointment, ListConversations, ListConversationMessages, ListConversationTemplates, ReplyToConversation], Field(discriminator="operation")]


class ApptotoConfig(NodeConfig[Operation, ApptotoAPIKeyCredential]):
    pass


# JSON bodies for nested appointment, contact and booking writes follow the
# provider examples; its OpenAPI declares only a form media type for these.
ROUTES = {
    "get_user_info": ("GET", "/v1/userinfo"),
    "list_calendars": ("GET", "/v1/calendars"),
    "list_events": ("GET", "/v1/events"),
    "get_event": ("GET", "/v1/event"),
    "create_event": ("POST", "/v1/events"),
    "update_event": ("PUT", "/v1/events"),
    "delete_event": ("DELETE", "/v1/events"),
    "tag_event": ("POST", "/v1/event/tag"),
    "list_participants": ("GET", "/v1/participants"),
    "add_participant": ("POST", "/v1/participants"),
    "update_participant": ("PUT", "/v1/participants"),
    "delete_participant": ("DELETE", "/v1/participants"),
    "list_address_books": ("GET", "/v1/address_books"),
    "list_contacts": ("GET", "/v1/contacts"),
    "get_contact": ("GET", "/v1/contact"),
    "create_contact": ("POST", "/v1/contacts"),
    "update_contact": ("PUT", "/v1/contacts"),
    "delete_contact": ("DELETE", "/v1/contacts"),
    "tag_contact": ("POST", "/v1/contacts/tag"),
    "list_booking_pages": ("GET", "/v1/booking_pages"),
    "book_appointment": ("POST", "/v1/book_now"),
    "list_conversations": ("GET", "/v1/conversations"),
    "list_conversation_messages": ("GET", "/v1/conversation_messages"),
    "list_conversation_templates": ("GET", "/v1/conversation_templates"),
    "reply_to_conversation": ("POST", "/v1/conversation_reply"),
}


class ApptotoNode(WorkflowNode):
    integration_type = "automation-apptoto"
    connection_evidence = ConnectionEvidence(noun="calendars", operation="list_calendars", identity_operation="get_user_info")

    @classmethod
    def get_config_model(cls):
        return ApptotoConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Apptoto username and API key")
        cfg = self.config.config
        method, path = ROUTES[cfg.operation]
        values = cfg.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if cfg.operation in {"create_event", "update_event"}:
            payload = {"events": [values], "prevent_calendar_creation": True}
            request = {"json": payload}
        elif cfg.operation in {"create_contact", "update_contact"}:
            request = {"json": {"contacts": [values]}}
        elif cfg.operation == "book_appointment":
            request = {"json": values}
        else:
            # The provider's scalar actions use URL-encoded fields. Booleans
            # must be lowercase, including explicitly supplied false values.
            values = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
            request = {"params" if method in {"GET", "DELETE"} else "data": values}
        auth = base64.b64encode(f"{credential.username}:{credential.api_key}".encode()).decode()
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Basic " + auth, "Accept": "application/json"}, **request)
        if not 200 <= response.status_code < 300:
            message = response.text[:2000]
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("error") or error.get("message") or message
            except ValueError:
                pass
            return {"status": "error", "status_code": response.status_code, "error": str(message)}
        if response.status_code == 204:
            return {"status": "success", "data": None}
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("Expected an Apptoto JSON object or list")
        if isinstance(payload, dict) and (payload.get("error") or payload.get("errors") or payload.get("success") is False):
            return {"status": "error", "error": payload.get("error") or payload.get("errors") or "Apptoto reported failure"}
        return {"status": "success", "data": payload}
