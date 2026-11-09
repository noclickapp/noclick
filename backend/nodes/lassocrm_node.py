"""LassoCRM project API operations using a manually supplied bearer API key.

Each operation calls exactly one endpoint from the published 1.0.40 contract.
Paged reads expose the next cursor without following provider links.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlencode, urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.lassocrm.com/v1"


class LassoCRMAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="LassoCRM API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://platform.lassocrm.com/api/",
            "x-credential-instructions": "Ask your Lasso Data Systems business contact for a project/location API key. Paste the JWT token alone, without Bearer. NoClick sends it only to api.lassocrm.com. Reading registrants verifies access to that project's data.",
        })
    credential_type: Literal["lassocrm_api_key"] = Field("lassocrm_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key alone, without Bearer")
        return value


class LassoCRMInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def appointment_times(self):
        if hasattr(self, "start_time"):
            if self.start_time.utcoffset() is None or self.end_time.utcoffset() is None:
                raise ValueError("Use appointment times with UTC offsets")
            if self.end_time <= self.start_time:
                raise ValueError("Appointment end must follow its start")
        return self


class LassoCRMListRegistrantsConfig(LassoCRMInput):
    """Read one page of registrants; use next_cursor for the next page."""
    operation: Literal["list_registrants"] = Field("list_registrants", json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=4096)
    rating: str | None = Field(None, max_length=50)
    last_modified_after: date | None = None
    last_modified_before: date | None = None
    registered_after: date | None = None
    registered_before: date | None = None

class LassoCRMSearchRegistrantsConfig(LassoCRMInput):
    """Search one page of registrants by name, email, phone or external ID."""
    operation: Literal["search_registrants"] = Field("search_registrants", json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=4096)
    email: str | None = Field(None, max_length=4096)
    phone: str | None = Field(None, max_length=4096)
    name: str | None = Field(None, max_length=4096)
    external_id: str | None = Field(None, max_length=4096)
    smart_search: str | None = Field(None, max_length=4096)
    fuzzy: bool | None = None

class LassoCRMGetRegistrantConfig(LassoCRMInput):
    """Retrieve full registrant data; history bodies require their separate API."""
    operation: Literal["get_registrant"] = Field("get_registrant", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LassoCRMCreateRegistrantConfig(LassoCRMInput):
    """Submit a new registrant; HTTP 202 acknowledges acceptance, not completed processing."""
    operation: Literal["create_registrant"] = Field("create_registrant", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=200)
    last_name: str = Field(..., min_length=1, max_length=200)
    company: str | None = Field(None, max_length=200)
    contact_preference: Literal["noPreference", "any", "email", "mail", "phone", "text", "noEmail", "noContact"] | None = None
    email: str | None = Field(None, min_length=1, max_length=50)
    external_id: str | None = Field(None, max_length=200)
    automatically_merge: bool = Field(True, description="Lasso defaults to merging matching emails/phones. Set false to request a separate lead.")

class LassoCRMUpdateRegistrantConfig(LassoCRMInput):
    """Update registrant personal data; first and last names are required by Lasso."""
    operation: Literal["update_registrant"] = Field("update_registrant", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    first_name: str = Field(..., min_length=1, max_length=200)
    last_name: str = Field(..., min_length=1, max_length=200)
    company: str | None = Field(None, max_length=200)
    contact_preference: Literal["noPreference", "any", "email", "mail", "phone", "text", "noEmail", "noContact"] | None = None

class LassoCRMGetContactInformationConfig(LassoCRMInput):
    """Read email, phone and address collections."""
    operation: Literal["get_contact_information"] = Field("get_contact_information", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LassoCRMSetRatingConfig(LassoCRMInput):
    """Set a registrant rating, creating that rating if absent."""
    operation: Literal["set_rating"] = Field("set_rating", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    rating: str = Field(..., min_length=1, max_length=50)

class LassoCRMAddEmailConfig(LassoCRMInput):
    """Add one email to a registrant."""
    operation: Literal["add_email"] = Field("add_email", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str = Field(..., min_length=1, max_length=50)
    contact_type: str | None = Field(None, max_length=25)
    primary: bool = False

class LassoCRMAddPhoneConfig(LassoCRMInput):
    """Add one phone to a registrant."""
    operation: Literal["add_phone"] = Field("add_phone", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    phone: str = Field(..., min_length=1, max_length=20)
    contact_type: str | None = Field(None, max_length=25)
    primary: bool = False

class LassoCRMCreateNoteConfig(LassoCRMInput):
    """Append a free-form note to a registrant."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    note: str = Field(..., min_length=1, max_length=100000, description="Lasso strips four-byte UTF-8 characters from notes.")

class LassoCRMListActivitiesConfig(LassoCRMInput):
    """Retrieve up to 150 activities, newest first; Lasso caps this endpoint at 150."""
    operation: Literal["list_activities"] = Field("list_activities", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LassoCRMCreateActivityConfig(LassoCRMInput):
    """Book a follow-up activity. Completed activities without completedBy are attributed to Lasso Autobot."""
    operation: Literal["create_activity"] = Field("create_activity", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    activity_type: str = Field(..., min_length=1, max_length=40, description="Use a type from list_activity_types.")
    details: str = Field(..., max_length=255)
    activity_date: date
    complete: bool
    note: str | None = Field(None, max_length=100000)

class LassoCRMGetActivityConfig(LassoCRMInput):
    """Retrieve one registrant activity."""
    operation: Literal["get_activity"] = Field("get_activity", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    activity_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LassoCRMListAppointmentsConfig(LassoCRMInput):
    """Retrieve a registrant appointment list."""
    operation: Literal["list_appointments"] = Field("list_appointments", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LassoCRMCreateAppointmentConfig(LassoCRMInput):
    """Create an appointment using UTC-offset times. Does not request email confirmations or SMS reminders."""
    operation: Literal["create_appointment"] = Field("create_appointment", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str = Field(..., min_length=1, max_length=1000)
    start_time: datetime
    end_time: datetime
    description: str | None = Field(None, max_length=10000)
    location: str | None = Field(None, max_length=2000)
    appointment_status: Literal["Open", "Tentative", "Confirmed", "Cancelled", "Completed", "No Show"] | None = None

class LassoCRMGetAppointmentConfig(LassoCRMInput):
    """Retrieve one registrant appointment."""
    operation: Literal["get_appointment"] = Field("get_appointment", json_schema_extra={"ui:hidden": True})
    registrant_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    appointment_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LassoCRMGetProjectSettingsConfig(LassoCRMInput):
    """Read settings, sales reps, ratings, source types and follow-up processes for this API key project."""
    operation: Literal["get_project_settings"] = Field("get_project_settings", json_schema_extra={"ui:hidden": True})

class LassoCRMListActivityTypesConfig(LassoCRMInput):
    """List available activity types for creating follow-up activities."""
    operation: Literal["list_activity_types"] = Field("list_activity_types", json_schema_extra={"ui:hidden": True})

class LassoCRMListInventoryConfig(LassoCRMInput):
    """List project inventory."""
    operation: Literal["list_inventory"] = Field("list_inventory", json_schema_extra={"ui:hidden": True})

class LassoCRMGetInventoryConfig(LassoCRMInput):
    """Retrieve full details for one inventory item."""
    operation: Literal["get_inventory"] = Field("get_inventory", json_schema_extra={"ui:hidden": True})
    inventory_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LassoCRMListProjectAppointmentsConfig(LassoCRMInput):
    """Read one page of appointments for the project."""
    operation: Literal["list_project_appointments"] = Field("list_project_appointments", json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=4096)

LassoCRMConfig = Annotated[Union[
    LassoCRMListRegistrantsConfig,
    LassoCRMSearchRegistrantsConfig,
    LassoCRMGetRegistrantConfig,
    LassoCRMCreateRegistrantConfig,
    LassoCRMUpdateRegistrantConfig,
    LassoCRMGetContactInformationConfig,
    LassoCRMSetRatingConfig,
    LassoCRMAddEmailConfig,
    LassoCRMAddPhoneConfig,
    LassoCRMCreateNoteConfig,
    LassoCRMListActivitiesConfig,
    LassoCRMCreateActivityConfig,
    LassoCRMGetActivityConfig,
    LassoCRMListAppointmentsConfig,
    LassoCRMCreateAppointmentConfig,
    LassoCRMGetAppointmentConfig,
    LassoCRMGetProjectSettingsConfig,
    LassoCRMListActivityTypesConfig,
    LassoCRMListInventoryConfig,
    LassoCRMGetInventoryConfig,
    LassoCRMListProjectAppointmentsConfig,
], Field(discriminator="operation")]


class LassoCRMFullConfig(NodeConfig[LassoCRMConfig, LassoCRMAPIKeyCredential]):
    pass


ROUTES = {'list_registrants': {'method': 'GET',
                      'path': '/registrants',
                      'query': {'cursor': 'cursor',
                                'rating': 'rating',
                                'last_modified_after': 'lastModifiedAfter',
                                'last_modified_before': 'lastModifiedBefore',
                                'registered_after': 'registeredAfter',
                                'registered_before': 'registeredBefore'},
                      'body': {},
                      'root': 'object',
                      'status': 200},
 'search_registrants': {'method': 'GET',
                        'path': '/registrants/search',
                        'query': {'cursor': 'cursor',
                                  'email': 'email',
                                  'phone': 'phone',
                                  'name': 'name',
                                  'external_id': 'externalId',
                                  'smart_search': 'smartSearch',
                                  'fuzzy': 'fuzzy'},
                        'body': {},
                        'root': 'object',
                        'status': 200},
 'get_registrant': {'method': 'GET',
                    'path': '/registrants/{registrant_id}',
                    'query': {},
                    'body': {},
                    'root': 'object',
                    'status': 200},
 'create_registrant': {'method': 'POST',
                       'path': '/registrants',
                       'query': {},
                       'body': {'first_name': 'person.firstName',
                                'last_name': 'person.lastName',
                                'company': 'person.company',
                                'contact_preference': 'person.contactPreference',
                                'email': 'emails',
                                'external_id': 'externalId',
                                'automatically_merge': 'automaticallyMerge'},
                       'root': 'object',
                       'status': 202},
 'update_registrant': {'method': 'PUT',
                       'path': '/registrants/{registrant_id}',
                       'query': {},
                       'body': {'first_name': 'firstName',
                                'last_name': 'lastName',
                                'company': 'company',
                                'contact_preference': 'contactPreference'},
                       'root': 'object',
                       'status': 200},
 'get_contact_information': {'method': 'GET',
                             'path': '/registrants/{registrant_id}/person/contact-information',
                             'query': {},
                             'body': {},
                             'root': 'object',
                             'status': 200},
 'set_rating': {'method': 'PUT',
                'path': '/registrants/{registrant_id}/rating',
                'query': {},
                'body': {'rating': 'rating'},
                'root': 'object',
                'status': 200},
 'add_email': {'method': 'POST',
               'path': '/registrants/{registrant_id}/emails',
               'query': {},
               'body': {'email': 'email', 'contact_type': 'type', 'primary': 'primary'},
               'root': 'object',
               'status': 201},
 'add_phone': {'method': 'POST',
               'path': '/registrants/{registrant_id}/phones',
               'query': {},
               'body': {'phone': 'phone', 'contact_type': 'type', 'primary': 'primary'},
               'root': 'object',
               'status': 201},
 'create_note': {'method': 'POST',
                 'path': '/registrants/{registrant_id}/notes',
                 'query': {},
                 'body': {'note': 'note'},
                 'root': 'object',
                 'status': 201},
 'list_activities': {'method': 'GET',
                     'path': '/registrants/{registrant_id}/activities',
                     'query': {},
                     'body': {},
                     'root': 'array',
                     'status': 200},
 'create_activity': {'method': 'POST',
                     'path': '/registrants/{registrant_id}/activities',
                     'query': {},
                     'body': {'activity_type': 'type',
                              'details': 'details',
                              'activity_date': 'date',
                              'complete': 'complete',
                              'note': 'note'},
                     'root': 'object',
                     'status': 201},
 'get_activity': {'method': 'GET',
                  'path': '/registrants/{registrant_id}/activities/{activity_id}',
                  'query': {},
                  'body': {},
                  'root': 'object',
                  'status': 200},
 'list_appointments': {'method': 'GET',
                       'path': '/registrants/{registrant_id}/appointments',
                       'query': {},
                       'body': {},
                       'root': 'array',
                       'status': 200},
 'create_appointment': {'method': 'POST',
                        'path': '/registrants/{registrant_id}/appointments',
                        'query': {},
                        'body': {'name': 'name',
                                 'start_time': 'startTime',
                                 'end_time': 'endTime',
                                 'description': 'description',
                                 'location': 'location',
                                 'appointment_status': 'status'},
                        'root': 'object',
                        'status': 201},
 'get_appointment': {'method': 'GET',
                     'path': '/registrants/{registrant_id}/appointments/{appointment_id}',
                     'query': {},
                     'body': {},
                     'root': 'object',
                     'status': 200},
 'get_project_settings': {'method': 'GET',
                          'path': '/projects/settings',
                          'query': {},
                          'body': {},
                          'root': 'object',
                          'status': 200},
 'list_activity_types': {'method': 'GET',
                         'path': '/projects/activities/types',
                         'query': {},
                         'body': {},
                         'root': 'array',
                         'status': 200},
 'list_inventory': {'method': 'GET',
                    'path': '/inventory',
                    'query': {},
                    'body': {},
                    'root': 'array',
                    'status': 200},
 'get_inventory': {'method': 'GET',
                   'path': '/inventory/{inventory_id}',
                   'query': {},
                   'body': {},
                   'root': 'object',
                   'status': 200},
 'list_project_appointments': {'method': 'GET',
                               'path': '/projects/appointments',
                               'query': {'cursor': 'cursor'},
                               'body': {},
                               'root': 'object',
                               'status': 200}}


def _wire(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


def _next_cursor(payload, path):
    links = payload.get("links") or {}
    if not isinstance(links, dict):
        raise ValueError("LassoCRM returned malformed pagination metadata")
    link = links.get("next")
    if not link:
        return None
    if not isinstance(link, str):
        raise ValueError("LassoCRM returned a malformed next link")
    parsed = urlsplit(link)
    # Extract the cursor only; never send a credential to a provider-returned URL.
    allowed_paths = {path, "/v1" + path}
    # ProjectAppointments.links.next documents this shorter path.
    if path == "/projects/appointments":
        allowed_paths.update({"/appointments", "/v1/appointments"})
    if (parsed.scheme and parsed.scheme != "https") or (parsed.netloc and parsed.netloc != "api.lassocrm.com") or parsed.path not in allowed_paths or parsed.fragment:
        raise ValueError("LassoCRM returned an unexpected pagination destination")
    cursors = parse_qs(parsed.query).get("cursor", [])
    if len(cursors) != 1 or not cursors[0] or len(cursors[0]) > 4096:
        raise ValueError("LassoCRM returned an invalid next cursor")
    return cursors[0]


class LassoCRMNode(WorkflowNode):
    integration_type = "automation-lassocrm"
    connection_evidence = ConnectionEvidence(
        operation="list_registrants", noun="project registrants",
        identity_operation="get_project_settings",
        label_keys=("firstName", "lastName", "registrantId", "personalId"))

    @classmethod
    def get_config_model(cls):
        return LassoCRMFullConfig

    async def execute(self, inputs):
        config = self.config
        if not isinstance(config, LassoCRMFullConfig) or not config.credentials:
            raise ValueError("Connect a LassoCRM API key")
        credential, op = config.credentials, config.config
        route = ROUTES[op.operation]
        fields = op.model_dump(exclude_none=True)
        path = route["path"]
        for key, value in fields.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        query = {target: _wire(fields[key]) for key, target in route["query"].items() if key in fields}
        body = {}
        for key, target in route["body"].items():
            if key not in fields:
                continue
            value = fields[key]
            if op.operation == "create_registrant" and key == "email":
                body["emails"] = [{"email": value, "primary": True}]
            elif "." in target:
                parent, child = target.split(".", 1)
                body.setdefault(parent, {})[child] = value
            else:
                body[target] = _wire(value) if isinstance(value, (date, datetime)) else value
        url = BASE_URL + path + ("?" + urlencode(query) if query else "")
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], url,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                    **({"json": body} if route["body"] else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "LassoCRM request could not be completed; inspect writes before retrying"}
        status = response.status_code
        if len(response.content) > 10_000_000:
            return {"status": "error", "http_status": status, "error": "LassoCRM response exceeds 10 MB"}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "http_status": status, "error": "LassoCRM returned invalid JSON"}
        if status != route["status"]:
            message = payload.get("message") or payload.get("error") or payload.get("errors") if isinstance(payload, dict) else None
            return {"status": "error", "http_status": status, "error": _redact(message or f"LassoCRM returned HTTP {status}", credential.api_key)}
        if not isinstance(payload, list if route["root"] == "array" else dict):
            return {"status": "error", "http_status": status, "error": "LassoCRM returned an unexpected JSON shape"}
        if isinstance(payload, dict) and (payload.get("error") or payload.get("errors")):
            return {"status": "error", "http_status": status, "error": _redact(payload.get("error") or payload["errors"], credential.api_key)}
        result = {"status": "success", "http_status": status, "data": _redact(payload, credential.api_key)}
        if "cursor" in route["query"]:
            try:
                result["next_cursor"] = _next_cursor(payload, path)
            except ValueError as exc:
                return {"status": "error", "http_status": status, "error": str(exc)}
            result["has_more"] = result["next_cursor"] is not None
        if op.operation == "create_registrant":
            result["accepted"] = True
            result["processing_complete"] = False
        if op.operation == "list_activities":
            result["provider_limit"] = 150
        return result
