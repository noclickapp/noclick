"""Hostfully PMS v3.3 operations for an account owner's agency API key.

Contract: https://dev.hostfully.com/reference/getting-started (v3.0.1).
Reads return one provider page; use next_cursor to continue paginated lists.
Writes make one request and are never retried automatically.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

UID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=20000)]
LocalTime = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")]


class HostfullyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hostfully API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dev.hostfully.com/reference/authentication",
            "x-credential-instructions": "For a Hostfully account with API access, copy the agency API key and agency UID from Agency Settings. Select the environment that issued your key. This connects your own agency; Hostfully partner applications use a separate OAuth flow. NoClick reads the agency to verify the connection.",
        })
    credential_type: Literal["hostfully_api_key"] = Field("hostfully_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    agency_uid: UID = Field(..., title="Agency UID", description="At the bottom of Hostfully Agency Settings.")
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def valid_local_time(cls, value, info):
        if info.field_name == "created_at" and value is not None and value.utcoffset() is None:
            raise ValueError("Message creation filter needs a timezone")
        if info.field_name.endswith("local_date_time") and value is not None:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        return value


class _Page(_Input):
    limit: int = Field(100, ge=1, le=100, description="Records per request; one page is returned.")
    cursor: Optional[str] = Field(None, max_length=4000, description="Use next_cursor from the preceding page with the same filters.")


class GetAgency(_Input):
    """Read the credential's agency, establishing account connection evidence."""
    operation: Literal["get_agency"] = "get_agency"


class ListProperties(_Page):
    """List properties belonging to the connected agency."""
    operation: Literal["list_properties"] = "list_properties"
    updated_since: Optional[LocalTime] = None


class GetProperty(_Input):
    operation: Literal["get_property"] = "get_property"
    property_uid: UID


class UpdateProperty(GetProperty):
    """Partially update listing name, activity or booking notes."""
    operation: Literal["update_property"] = "update_property"
    name: Optional[Text] = None
    is_active: Optional[bool] = None
    booking_notes: Optional[Text] = None

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, f) is None for f in ("name", "is_active", "booking_notes")):
            raise ValueError("Supply at least one property change")
        return self


class ListLeads(_Page):
    """Search inquiries and reservations in the connected agency."""
    operation: Literal["list_leads"] = "list_leads"
    property_uid: Optional[UID] = None
    check_in_from: Optional[date] = None
    check_in_to: Optional[date] = None
    updated_since: Optional[LocalTime] = None


class GetLead(_Input):
    operation: Literal["get_lead"] = "get_lead"
    lead_uid: UID


class CreateLead(_Input):
    """Create an inquiry, hold, booking or availability block."""
    operation: Literal["create_lead"] = "create_lead"
    property_uid: UID
    status: Literal["NEW", "ON_HOLD", "BOOKED", "BLOCKED"] = "NEW"
    check_in_date: date
    check_out_date: date
    email: Optional[str] = Field(None, max_length=320, description="Guest email; required except for availability blocks.")
    first_name: Optional[Text] = None
    last_name: Optional[Text] = None
    adult_count: int = Field(1, ge=1, le=1000)
    notes: Optional[Text] = None
    unit_uid: Optional[UID] = Field(None, description="Required by Hostfully when property UID identifies a unit type.")

    @model_validator(mode="after")
    def stay(self):
        if self.check_out_date <= self.check_in_date:
            raise ValueError("Check-out must follow check-in")
        if self.status != "BLOCKED" and (not self.email or "@" not in self.email):
            raise ValueError("Supply the guest's email for an inquiry or booking")
        return self


class UpdateLead(GetLead):
    """Update lead notes; booking status changes use the explicit actions."""
    operation: Literal["update_lead"] = "update_lead"
    notes: Text
    extra_notes: Optional[Text] = None


class BookLead(GetLead):
    """Transform an inquiry to a booking."""
    operation: Literal["book_lead"] = "book_lead"


class CancelLead(GetLead):
    """Cancel a booking."""
    operation: Literal["cancel_lead"] = "cancel_lead"


class ListMessages(_Page):
    operation: Literal["list_messages"] = "list_messages"
    lead_uid: Optional[UID] = None
    thread_uid: Optional[UID] = None
    created_at: Optional[datetime] = None


class GetMessage(_Input):
    operation: Literal["get_message"] = "get_message"
    message_uid: UID


class SendMessage(GetLead):
    """Send guest email or a supported channel direct message."""
    operation: Literal["send_message"] = "send_message"
    message_type: Literal["EMAIL", "DIRECT_MESSAGE"] = "EMAIL"
    text: Text
    subject: Optional[Text] = None
    thread_uid: Optional[UID] = None


class ListThreads(_Page):
    operation: Literal["list_threads"] = "list_threads"
    lead_uid: Optional[UID] = None


class GetThread(_Input):
    operation: Literal["get_thread"] = "get_thread"
    thread_uid: UID


class GetPropertyCalendar(GetProperty):
    operation: Literal["get_property_calendar"] = "get_property_calendar"
    from_date: date
    to_date: date
    availability_comments: bool = False

    @model_validator(mode="after")
    def date_range(self):
        if self.to_date < self.from_date:
            raise ValueError("Calendar end must not precede start")
        return self


class ListJobs(_Input):
    """List jobs in a date range with the contract's required modification filter."""
    operation: Literal["list_jobs"] = "list_jobs"
    from_date: date
    to_date: date
    modified_since: date
    property_uid: Optional[UID] = None


class GetJob(_Input):
    operation: Literal["get_job"] = "get_job"
    job_uid: UID


class CreateJob(_Input):
    operation: Literal["create_job"] = "create_job"
    property_uid: UID
    service_uid: UID
    start_local_date_time: LocalTime
    end_local_date_time: LocalTime
    status: Literal["NEW", "SCHEDULED", "DONE", "CANCELLED"] = "NEW"
    lead_uid: Optional[UID] = None
    notes: Optional[Text] = None
    unit_uid: Optional[UID] = None

    @model_validator(mode="after")
    def time_range(self):
        if self.end_local_date_time < self.start_local_date_time:
            raise ValueError("Job end must not precede start")
        return self


class MarkJobDone(GetJob):
    operation: Literal["mark_job_done"] = "mark_job_done"


HostfullyConfig = Annotated[Union[GetAgency, ListProperties, GetProperty, UpdateProperty,
    ListLeads, GetLead, CreateLead, UpdateLead, BookLead, CancelLead,
    ListMessages, GetMessage, SendMessage, ListThreads, GetThread,
    GetPropertyCalendar, ListJobs, GetJob, CreateJob, MarkJobDone], Field(discriminator="operation")]


class HostfullyFullConfig(NodeConfig[HostfullyConfig, HostfullyAPIKeyCredential]):
    pass


# Each operation maps to exactly one endpoint in the pinned v3.0.1 contract.
ROUTES = {
    "get_agency": ("GET", "/agencies/{agency_uid}", "agency"),
    "list_properties": ("GET", "/properties", "properties"),
    "get_property": ("GET", "/properties/{property_uid}", "property"),
    "update_property": ("PATCH", "/properties/{property_uid}", "property"),
    "list_leads": ("GET", "/leads", "leads"),
    "get_lead": ("GET", "/leads/{lead_uid}", "lead"),
    "create_lead": ("POST", "/leads", "lead"),
    "update_lead": ("PATCH", "/leads/{lead_uid}", "lead"),
    "book_lead": ("POST", "/leads/{lead_uid}/mark-as-booked", "lead"),
    "cancel_lead": ("POST", "/leads/{lead_uid}/cancel", "lead"),
    "list_messages": ("GET", "/messages", "messages"),
    "get_message": ("GET", "/messages/{message_uid}", "message"),
    "send_message": ("POST", "/messages", "message"),
    "list_threads": ("GET", "/threads", "threads"),
    "get_thread": ("GET", "/threads/{thread_uid}", "thread"),
    "get_property_calendar": ("GET", "/property-calendar/{property_uid}", "calendar"),
    "list_jobs": ("GET", "/jobs", "jobs"),
    "get_job": ("GET", "/jobs/{job_uid}", "job"),
    "create_job": ("POST", "/jobs", "job"),
    "mark_job_done": ("POST", "/jobs/{job_uid}/mark-as-done", None),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class HostfullyNode(WorkflowNode):
    integration_type = "automation-hostfully"
    connection_evidence = ConnectionEvidence(noun="Hostfully agency", identity_operation="get_agency")

    @classmethod
    def get_config_model(cls):
        return HostfullyFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            return {"status": "error", "error": "Connect a Hostfully API key"}
        op = self.config.config
        values = op.model_dump(mode="json", exclude_none=True)
        method, template, resource = ROUTES[op.operation]
        path_values = {**values, "agency_uid": credential.agency_uid}
        path = template.format(**{k: quote(str(v), safe="") for k, v in path_values.items()})
        params, body = {}, None
        agency = credential.agency_uid
        if isinstance(op, _Page):
            params = {"_limit": str(op.limit)}
            if op.cursor is not None:
                params["_cursor"] = op.cursor
        if op.operation in {"list_properties", "list_leads", "list_messages", "list_threads"}:
            params["agencyUid"] = agency
        query_names = {
            "list_properties": {"updated_since": "updatedSince"},
            "list_leads": {"property_uid": "propertyUid", "check_in_from": "checkInFrom", "check_in_to": "checkInTo", "updated_since": "updatedSince"},
            "list_messages": {"lead_uid": "leadUid", "thread_uid": "threadUid", "created_at": "createdAt"},
            "list_threads": {"lead_uid": "leadUid"},
            "get_property_calendar": {"from_date": "from", "to_date": "to", "availability_comments": "availabilityComments"},
            "list_jobs": {"from_date": "from", "to_date": "to", "modified_since": "modifiedSince", "property_uid": "propertiesUids"},
        }
        for field, wire in query_names.get(op.operation, {}).items():
            if field in values:
                params[wire] = values[field]
        body_names = {
            "update_property": {"name": "name", "is_active": "isActive", "booking_notes": "bookingNotes"},
            "update_lead": {"notes": "notes", "extra_notes": "extraNotes"},
            "create_lead": {"property_uid": "propertyUid", "status": "status", "check_in_date": "checkInLocalDate", "check_out_date": "checkOutLocalDate", "notes": "notes", "unit_uid": "unitUid"},
            "create_job": {"property_uid": "propertyUid", "service_uid": "serviceUid", "start_local_date_time": "startLocalDateTime", "end_local_date_time": "endLocalDateTime", "status": "status", "lead_uid": "leadUid", "notes": "notes", "unit_uid": "unitUid"},
            "send_message": {"lead_uid": "leadUid", "message_type": "type", "thread_uid": "threadUid"},
        }
        if op.operation in body_names:
            body = {wire: values[field] for field, wire in body_names[op.operation].items() if field in values}
        if op.operation == "create_lead":
            body["agencyUid"] = agency
            if op.status != "BLOCKED":
                body["guestInformation"] = {wire: values[field] for field, wire in {"email": "email", "first_name": "firstName", "last_name": "lastName", "adult_count": "adultCount"}.items() if field in values}
        if op.operation == "send_message":
            body["content"] = {key: values[key] for key in ("text", "subject") if key in values}
        host = "https://api.hostfully.com" if credential.environment == "production" else "https://sandbox-api.hostfully.com"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, host + "/api/v3.3" + path,
                    params=params, json=body, headers={"X-HOSTFULLY-APIKEY": credential.api_key, "Accept": "application/json"})
            expected = 201 if op.operation == "send_message" else 200
            if response.status_code != expected:
                # A failed mutation is never automatically replayed.
                message = "Hostfully request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"][:1000]
                except ValueError:
                    pass
                return _redact({"status": "error", "error": message, "http_status": response.status_code}, credential.api_key)
            if resource is None:
                return {"status": "success", "job_uid": op.job_uid, "completed": True}
            if len(response.content) > 10_000_000:
                raise ValueError("Hostfully JSON response is too large")
            payload = response.json()
            if not isinstance(payload, dict) or any(k in payload for k in ("error", "errors")):
                raise ValueError("Hostfully returned an unexpected response")
            data = payload.get(resource)
            is_list = op.operation.startswith("list_")
            if not isinstance(data, list if is_list else dict) or (is_list and any(not isinstance(row, dict) for row in data)):
                raise ValueError("Hostfully returned an unexpected resource")
            result = {"status": "success", "data": data, resource: data}
            if is_list:
                paging = payload.get("_paging") or {}
                if not isinstance(paging, dict):
                    raise ValueError("Hostfully returned invalid pagination")
                cursor = paging.get("_nextCursor")
                if cursor is not None and not isinstance(cursor, str):
                    raise ValueError("Hostfully returned an invalid cursor")
                result.update(next_cursor=cursor or None, has_more=bool(cursor))
                if "_metadata" in payload:
                    result["_metadata"] = payload["_metadata"]
            return _redact(result, credential.api_key)
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "Hostfully request could not be confirmed; check the environment and request fields"}
