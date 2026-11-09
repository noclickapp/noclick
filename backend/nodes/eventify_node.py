"""Eventify Admin API 4.0.1, using pasted event-scoped session tokens.

Contract: https://adminapi.eventify.io/swg/eventify-swagger-editor.json
Each action makes one request and retains the provider response envelope.
The public contract offers neither webhook registration nor created/updated
ordering or filtering for list endpoints (trigger brief 1).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote
import json

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://adminapi.eventify.io/dev.php"
DOCS_URL = "https://adminapi.eventify.io/swg/eventify-swagger-editor.json"


class EventifySessionTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Eventify Session Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://adminapi.eventify.io/swg/",
            "x-credential-instructions": "Paste the session_token for your event from Eventify's generateToken API. NoClick lists your associated events to check the connection. Replace the token here if it expires; NoClick does not store your Eventify password or generate or refresh tokens.",
        },
    )
    credential_type: Literal["eventify_session_token"] = Field(
        "eventify_session_token", json_schema_extra={"ui:hidden": True})
    session_token: str = Field(..., title="Session token", min_length=1,
                               json_schema_extra={"ui:widget": "password"})

    @field_validator("session_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Session token", key=True)
        if any(ch.isspace() for ch in value):
            raise ValueError("Paste the session token without spaces or an authorization header")
        return value


def event_field():
    return Field(..., title="Event ID", gt=0, json_schema_extra={"x-dynamic-options": {
        "field_name": "eventid", "allow_custom": True, "searchable": True,
        "placeholder": "Choose an Eventify event", "custom_placeholder": "Enter event ID",
    }})


class EventifyInput(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class FormAnswer(BaseModel):
    id: str
    value: Optional[Union[str, list[Any]]] = None


class EventifyListEventsConfig(EventifyInput):
    """Events associated with User."""
    operation: Literal["list_events"] = Field("list_events", title="List Events", json_schema_extra={"ui:hidden": True, "x-category": "Events"})


class EventifyGetEventConfig(EventifyInput):
    """Details of a specific event."""
    operation: Literal["get_event"] = Field("get_event", title="Get Event", json_schema_extra={"ui:hidden": True, "x-category": "Events"})
    eventid: int = event_field()


class EventifyListUserCategoriesConfig(EventifyInput):
    """Types of users specified for an event."""
    operation: Literal["list_user_categories"] = Field("list_user_categories", title="List User Categories", json_schema_extra={"ui:hidden": True, "x-category": "Events"})
    eventid: int = event_field()


class EventifyListInterestsConfig(EventifyInput):
    """Event specific interest list."""
    operation: Literal["list_interests"] = Field("list_interests", title="List Interests", json_schema_extra={"ui:hidden": True, "x-category": "Events"})
    eventid: int = event_field()


class EventifyListFormsConfig(EventifyInput):
    """List of all forms."""
    operation: Literal["list_forms"] = Field("list_forms", title="List Forms", json_schema_extra={"ui:hidden": True, "x-category": "Checkout Forms"})
    eventid: int = event_field()


class EventifyListAttendeesConfig(EventifyInput):
    """Fetch attendee list."""
    operation: Literal["list_attendees"] = Field("list_attendees", title="List Attendees", json_schema_extra={"ui:hidden": True, "x-category": "Users"})
    eventid: int = event_field()


class EventifySearchAttendeeConfig(EventifyInput):
    """Search for an attendee in an event."""
    operation: Literal["search_attendee"] = Field("search_attendee", title="Search Attendee", json_schema_extra={"ui:hidden": True, "x-category": "Users"})
    eventid: int = event_field()
    searchtype: Literal["email", "id", "name"] = Field("email", title="Search by")
    searchvalue: str = Field(..., min_length=1, title="Search value")


class EventifyCreateAttendeeConfig(EventifyInput):
    """Add an attendee."""
    operation: Literal["create_attendee"] = Field("create_attendee", title="Create Attendee", json_schema_extra={"ui:hidden": True, "x-category": "Users"})
    eventid: int = event_field()
    email: str = Field(..., min_length=1, title="Email")
    firstname: str = Field(..., min_length=1, title="First name")
    lastname: str = Field(..., min_length=1, title="Last name")
    userpassword: str = Field(..., min_length=6, pattern=r"^[A-Za-z0-9]+$", title="Attendee password", json_schema_extra={"ui:widget": "password"})
    form_number: int = Field(..., gt=0, title="Form number", description="Attendee form_number from List Forms. Keep the answer items in that form's order.")
    details_form: str = Field(..., title="Form answers", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description="Paste the ordered details_form JSON array from List Forms. Supply ordinary items' values; omit for sections and dynamic fields.")
    usercategory: str = Field(..., min_length=1, title="User category IDs", description="Comma separated IDs from List User Categories, including an attendee category.")
    userinterests: str = Field("", title="Interest IDs", description="Comma separated IDs from List Interests, or empty.")
    isadmin: Literal[0, 1] = Field(0, title="Administrator")
    isactive: Literal[0, 1] = Field(1, title="Active")
    isnetworking: Literal[0, 1] = Field(1, title="Networking")
    userwaitlistmode: Literal[0, 1] = Field(0, title="Waitlisted")
    profileurl: Optional[str] = Field(None, title="Profile image URL")
    exhibitoridfk: Optional[int] = Field(None, title="Associated exhibitor ID", gt=0)
    speakeridfk: Optional[int] = Field(None, title="Associated speaker ID", gt=0)
    sponsoridfk: Optional[int] = Field(None, title="Associated sponsor ID", gt=0)
    sendwelcomeemail: bool = Field(False, title="Send welcome email")

    @field_validator("details_form", mode="before")
    @classmethod
    def form_answers(cls, value):
        try:
            items = json.loads(value) if isinstance(value, str) else value
            if not isinstance(items, list):
                raise ValueError()
            answers = [FormAnswer.model_validate(item).model_dump(exclude_none=True) for item in items]
        except (ValueError, TypeError):
            raise ValueError("Paste a JSON array of form answers from List Forms") from None
        return json.dumps(answers)


class EventifyUpdateAttendeeConfig(EventifyInput):
    """Update an attendee."""
    operation: Literal["update_attendee"] = Field("update_attendee", title="Update Attendee", json_schema_extra={"ui:hidden": True, "x-category": "Users"})
    userid: int = Field(..., gt=0, title="userid")
    firstname: Optional[str] = Field(None, min_length=1, title="First name")
    lastname: Optional[str] = Field(None, min_length=1, title="Last name")
    usercategory: Optional[str] = Field(None, min_length=1, title="User category IDs")
    exhibitoridfk: Optional[int] = Field(None, gt=0, title="Associated exhibitor ID")
    form_number: Optional[int] = Field(None, gt=0, title="Form number")
    details_form: Optional[str] = Field(None, title="Form answers", json_schema_extra={"ui:widget": "textarea"}, description="JSON array copied from List Forms, paired with form_number.")

    @model_validator(mode="after")
    def answers(self):
        if (self.details_form is None) != (self.form_number is None):
            raise ValueError("Provide both form_number and details_form when changing form answers")
        if self.details_form is not None:
            try:
                answers = json.loads(self.details_form)
            except (ValueError, TypeError):
                raise ValueError("Form answers must be a JSON array copied from List Forms") from None
            if not isinstance(answers, list) or not all(isinstance(a, dict) for a in answers):
                raise ValueError("Form answers must be a JSON array of form items")
        if not self.model_dump(exclude_none=True, exclude={"operation", "userid"}):
            raise ValueError("Provide at least one attendee field to update")
        return self


class EventifyDeleteAttendeeConfig(EventifyInput):
    """Delete an attendee."""
    operation: Literal["delete_attendee"] = Field("delete_attendee", title="Delete Attendee", json_schema_extra={"ui:hidden": True, "x-category": "Users"})
    userid: int = Field(..., gt=0, title="userid")


class EventifyListSessionsConfig(EventifyInput):
    """List of all sessions in an event."""
    operation: Literal["list_sessions"] = Field("list_sessions", title="List Sessions", json_schema_extra={"ui:hidden": True, "x-category": "Sessions"})


class EventifyGetSessionConfig(EventifyInput):
    """Get detail of a specific session."""
    operation: Literal["get_session"] = Field("get_session", title="Get Session", json_schema_extra={"ui:hidden": True, "x-category": "Sessions"})
    sessionid: int = Field(..., gt=0, title="sessionid")


class EventifyCreateSessionConfig(EventifyInput):
    """Create a new session for your session track."""
    operation: Literal["create_session"] = Field("create_session", title="Create Session", json_schema_extra={"ui:hidden": True, "x-category": "Sessions"})
    eventid: int = event_field()
    apptabid: int = Field(..., gt=0, title="Schedule app tab ID")
    scheduledateid: int = Field(..., gt=0, title="Schedule date ID")
    scheduletrackid: int = Field(..., gt=0, title="Schedule track ID")
    title: str = Field(..., min_length=1, title="Session title")
    starttime: str = Field(..., title="Start time", description="Event-local time as yyyy-MM-dd HH:mm:ss.")
    endtime: str = Field(..., title="End time", description="Event-local time as yyyy-MM-dd HH:mm:ss.")
    sessiontype: Literal["general", "private", "additional", "addprivate", "rsvp"] = Field("general", title="Session type")
    colorid: int = Field(..., gt=0, title="Session color ID")
    checkintype: Literal["nocheckinneeded", "showqr", "scanqr"] = Field("showqr", title="Check-in type")
    description: Optional[str] = None
    location: Optional[str] = None
    rsvp: Optional[bool] = None
    rsvp_capacity: Optional[Literal["unlimited", "fixed"]] = None
    capacity: Optional[int] = Field(None, ge=0)
    tags: Optional[str] = Field(None, description="Comma separated tag IDs.")


class EventifyDeleteSessionConfig(EventifyInput):
    """Delete a specific session."""
    operation: Literal["delete_session"] = Field("delete_session", title="Delete Session", json_schema_extra={"ui:hidden": True, "x-category": "Sessions"})
    sessionid: int = Field(..., gt=0, title="sessionid")


class EventifyListSpeakersConfig(EventifyInput):
    """Get list of all speakers."""
    operation: Literal["list_speakers"] = Field("list_speakers", title="List Speakers", json_schema_extra={"ui:hidden": True, "x-category": "Speakers"})
    eventid: int = event_field()


class EventifyGetSpeakerConfig(EventifyInput):
    """Get details of a specific speaker."""
    operation: Literal["get_speaker"] = Field("get_speaker", title="Get Speaker", json_schema_extra={"ui:hidden": True, "x-category": "Speakers"})
    speakerid: int = Field(..., gt=0, title="speakerid")


class EventifyCreateSpeakerConfig(EventifyInput):
    """Add a new speaker."""
    operation: Literal["create_speaker"] = Field("create_speaker", title="Create Speaker", json_schema_extra={"ui:hidden": True, "x-category": "Speakers"})
    eventid: int = event_field()
    firstname: str = Field(..., min_length=1, title="First name")
    lastname: str = Field(..., min_length=1, title="Last name")
    email: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    description: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    profileimage: Optional[str] = Field(None, title="Profile image URL")
    createuser: Literal[False] = Field(False, title="Also create an attendee", description="Creates a speaker profile only. Use Create Attendee separately for registration.", json_schema_extra={"ui:hidden": True})


class EventifyUpdateSpeakerConfig(EventifyInput):
    """Update a speaker details."""
    operation: Literal["update_speaker"] = Field("update_speaker", title="Update Speaker", json_schema_extra={"ui:hidden": True, "x-category": "Speakers"})
    speakerid: int = Field(..., gt=0, title="speakerid")
    eventid: int = event_field()
    firstname: Optional[str] = Field(None, min_length=1, title="First name")
    lastname: Optional[str] = Field(None, min_length=1, title="Last name")
    email: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    description: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    profileimage: Optional[str] = Field(None, title="Profile image URL")
    createuser: Literal[False] = Field(False, title="Also create an attendee", description="Updates the profile without creating an attendee.", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "speakerid", "eventid", "createuser"}):
            raise ValueError("Provide at least one speaker field to update")
        return self


class EventifyDeleteSpeakerConfig(EventifyInput):
    """Delete a specific speaker."""
    operation: Literal["delete_speaker"] = Field("delete_speaker", title="Delete Speaker", json_schema_extra={"ui:hidden": True, "x-category": "Speakers"})
    speakerid: int = Field(..., gt=0, title="speakerid")


class EventifyListExhibitorsConfig(EventifyInput):
    """Get list of all the exhibitors in an event."""
    operation: Literal["list_exhibitors"] = Field("list_exhibitors", title="List Exhibitors", json_schema_extra={"ui:hidden": True, "x-category": "Exhibitors"})
    eventid: int = event_field()


class EventifyGetExhibitorConfig(EventifyInput):
    """Get details of a specific exhibitor."""
    operation: Literal["get_exhibitor"] = Field("get_exhibitor", title="Get Exhibitor", json_schema_extra={"ui:hidden": True, "x-category": "Exhibitors"})
    exhibitorid: int = Field(..., gt=0, title="exhibitorid")


class EventifyListSponsorsConfig(EventifyInput):
    """List of all sponsors in an event."""
    operation: Literal["list_sponsors"] = Field("list_sponsors", title="List Sponsors", json_schema_extra={"ui:hidden": True, "x-category": "Sponsors"})
    eventid: int = event_field()


class EventifyGetSalesSummaryConfig(EventifyInput):
    """Sales summary card for an event."""
    operation: Literal["get_sales_summary"] = Field("get_sales_summary", title="Get Sales Summary", json_schema_extra={"ui:hidden": True, "x-category": "Sales"})
    eventid: int = event_field()


class EventifyListOrdersConfig(EventifyInput):
    """Sales report, grouped by order."""
    operation: Literal["list_orders"] = Field("list_orders", title="List Orders", json_schema_extra={"ui:hidden": True, "x-category": "Sales"})
    eventid: int = event_field()
    ticketid: str = Field("all", title="Ticket ID", description="A ticket ID or all.")
    offset: int = Field(0, ge=0, title="Offset", description="Records to skip. Increment by limit for the next page.")
    limit: int = Field(20, ge=1, le=100, title="Page size")


class EventifyGetOrderConfig(EventifyInput):
    """Full details of a single order."""
    operation: Literal["get_order"] = Field("get_order", title="Get Order", json_schema_extra={"ui:hidden": True, "x-category": "Sales"})
    eventid: int = event_field()
    ordernumber: int = Field(..., gt=0, title="ordernumber")


EventifyConfig = Annotated[Union[
    EventifyListEventsConfig,
    EventifyGetEventConfig,
    EventifyListUserCategoriesConfig,
    EventifyListInterestsConfig,
    EventifyListFormsConfig,
    EventifyListAttendeesConfig,
    EventifySearchAttendeeConfig,
    EventifyCreateAttendeeConfig,
    EventifyUpdateAttendeeConfig,
    EventifyDeleteAttendeeConfig,
    EventifyListSessionsConfig,
    EventifyGetSessionConfig,
    EventifyCreateSessionConfig,
    EventifyDeleteSessionConfig,
    EventifyListSpeakersConfig,
    EventifyGetSpeakerConfig,
    EventifyCreateSpeakerConfig,
    EventifyUpdateSpeakerConfig,
    EventifyDeleteSpeakerConfig,
    EventifyListExhibitorsConfig,
    EventifyGetExhibitorConfig,
    EventifyListSponsorsConfig,
    EventifyGetSalesSummaryConfig,
    EventifyListOrdersConfig,
    EventifyGetOrderConfig
], Field(discriminator="operation")]


class EventifyNodeConfig(NodeConfig[EventifyConfig, EventifySessionTokenCredential]):
    pass


OPERATIONS = {
    "list_events": ("GET", "/events", ()),
    "get_event": ("GET", "/events/{eventid}", ('eventid',)),
    "list_user_categories": ("GET", "/events/user_categories", ('eventid',)),
    "list_interests": ("GET", "/events/interest", ('eventid',)),
    "list_forms": ("GET", "/myForms", ('eventid',)),
    "list_attendees": ("GET", "/attendee", ('eventid',)),
    "search_attendee": ("GET", "/attendee/search", ('eventid', 'searchtype', 'searchvalue')),
    "create_attendee": ("POST", "/attendee", ()),
    "update_attendee": ("PATCH", "/attendee/{userid}", ('userid',)),
    "delete_attendee": ("DELETE", "/attendee/{userid}", ('userid',)),
    "list_sessions": ("GET", "/sessions", ()),
    "get_session": ("GET", "/sessions/{sessionid}", ('sessionid',)),
    "create_session": ("POST", "/sessions", ()),
    "delete_session": ("DELETE", "/sessions/{sessionid}", ('sessionid',)),
    "list_speakers": ("GET", "/speakers", ('eventid',)),
    "get_speaker": ("GET", "/speakers/{speakerid}", ('speakerid',)),
    "create_speaker": ("POST", "/speakers", ()),
    "update_speaker": ("PATCH", "/speakers/{speakerid}", ('speakerid',)),
    "delete_speaker": ("DELETE", "/speakers/{speakerid}", ('speakerid',)),
    "list_exhibitors": ("GET", "/exhibitors", ('eventid',)),
    "get_exhibitor": ("GET", "/exhibitors/{exhibitorid}", ('exhibitorid',)),
    "list_sponsors": ("GET", "/sponsors", ('eventid',)),
    "get_sales_summary": ("GET", "/sales/summary", ('eventid',)),
    "list_orders": ("GET", "/sales/orders", ('eventid', 'ticketid', 'offset', 'limit')),
    "get_order": ("GET", "/sales/order-details", ('eventid', 'ordernumber')),
}


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()
                if k.lower() not in {"session_token", "userpassword", "password"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class EventifyNode(WorkflowNode):
    integration_type = "automation-eventify"
    connection_evidence = ConnectionEvidence(field="eventid", noun="events", label_keys=("eventname", "eventid"))
    edit_examples = ["Find an Eventify attendee by email", "Create a speaker for my event", "Read ticket sales for my event"]

    @classmethod
    def get_config_model(cls):
        return EventifyNodeConfig

    @classmethod
    async def _request(cls, credential, method, path, *, params=None, body=None):
        token = credential.session_token
        try:
            async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    params={**(params or {}), "session_token": token},
                    headers={"Accept": "application/json", "User-Agent": "NoClick Eventify Integration"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Eventify request did not complete; check the provider before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"Eventify returned a non-JSON response (HTTP {response.status_code})") from None
        error = isinstance(data, dict) and (
            bool(data.get("is_error")) or data.get("success") in (False, 0, "0"))
        if response.status_code >= 300 or error:
            message = data.get("message") if isinstance(data, dict) else None
            message = message if isinstance(message, str) else f"Eventify rejected the request (HTTP {response.status_code})"
            raise ValueError(_redact(message, token))
        if not isinstance(data, (dict, list)):
            raise ValueError("Eventify returned an unexpected JSON response")
        return _redact(data, token)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Eventify session token")
        config = self.config.config
        method, path, parameters = OPERATIONS[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        params = {}
        for field in parameters:
            value = values.pop(field)
            marker = "{" + field + "}"
            if marker in path:
                path = path.replace(marker, quote(str(value), safe=""))
            else:
                params[field] = value
        if config.operation == "create_attendee":
            # The endpoint prose permits null; the schema lists these required
            # but omits nullable on the string and integer property types.
            for key in ("profileurl", "exhibitoridfk", "speakeridfk", "sponsoridfk"):
                values[key] = getattr(config, key)
            values["details_form"] = json.loads(config.details_form)
        if config.operation == "update_speaker":
            # Required by the endpoint prose, missing from schema properties.
            values["speakerid"] = config.speakerid
        result = await self._request(self.config.credentials, method, path, params=params,
                                     body=values if method in {"POST", "PATCH"} else None)
        output = {"status": "success", "operation": config.operation, "data": result}
        if config.operation == "list_orders":
            rows = result.get("resource") if isinstance(result, dict) else None
            if not isinstance(rows, list):
                raise ValueError("Eventify sales response has no resource list")
            output["next_offset"] = config.offset + config.limit if len(rows) == config.limit else None
        await self.emit(output)
        return output

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, **kwargs):
        if field_name != "eventid":
            return []
        credential = EventifySessionTokenCredential.model_validate(credential_data)
        data = await cls._request(credential, "GET", "/events")
        if not isinstance(data, list):
            raise ValueError("Eventify did not return the associated event list")
        return [{"value": str(row["eventid"]), "label": str(row.get("eventname") or row["eventid"])}
                for row in data if isinstance(row, dict) and row.get("eventid") is not None]
