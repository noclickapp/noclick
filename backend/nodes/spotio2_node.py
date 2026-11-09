"""SPOTIO field-sales records, activities and appointments using a pasted token.

Each operation makes one fixed request to the published v1 API. Collection
responses retain the provider's scrollId so callers can explicitly fetch pages.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.spotio2.com"
FAMILY = "spotio2_api_token"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)


class Spotio2TokenCredential(BaseModel):
    model_config = ConfigDict(title="SPOTIO API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.spotio2.com/settings/integrations/api-access",
        "x-credential-instructions": "Paste an existing SPOTIO Bearer token without the Bearer prefix. SPOTIO documents exchanging the ClientId and Secret from Settings → Integrations → API Access at /api/users/apitoken. Tokens last two hours; replace an expired token here. NoClick sends this token only to api.spotio2.com.",
    })
    credential_type: Literal["spotio2_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=16384, title="API token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class Spotio2ListUsers(_Input):
    """List users visible to the connected company; also proves the connection."""
    operation: Literal["list_users"] = "list_users"
    territory_ids: str | None = Field(None, max_length=4096, description="Optional comma-separated territory IDs.")


class Spotio2ListTeams(_Input):
    operation: Literal["list_teams"] = "list_teams"


class Spotio2GetTeam(_Input):
    operation: Literal["get_team"] = "get_team"
    team_id: int = Field(..., ge=1, le=2147483647)


class Spotio2ListTerritories(_Input):
    operation: Literal["list_territories"] = "list_territories"


class Spotio2GetTerritory(_Input):
    operation: Literal["get_territory"] = "get_territory"
    territory_id: Identifier


class Spotio2ListRecordTypes(_Input):
    operation: Literal["list_record_types"] = "list_record_types"


class Spotio2GetRecordType(_Input):
    operation: Literal["get_record_type"] = "get_record_type"
    type_id: int = Field(..., ge=1, le=2147483647)


class Spotio2ListActivityTemplates(_Input):
    operation: Literal["list_activity_templates"] = "list_activity_templates"


class Spotio2SearchRecords(_Input):
    """Search one page. Pass scroll_id from the returned data to continue."""
    operation: Literal["search_records"] = "search_records"
    query: str | None = Field(None, max_length=4096)
    scroll_id: str | None = Field(None, max_length=8192)
    filter_id: Identifier | None = None
    type_id: int | None = Field(None, ge=1, le=2147483647)
    page_size: int = Field(100, ge=1, le=100)
    phone_number: str | None = Field(None, max_length=100)


class _Record(_Input):
    record_id: Identifier


class Spotio2GetRecord(_Record):
    operation: Literal["get_record"] = "get_record"


class Spotio2GetRecordByExternalId(_Input):
    operation: Literal["get_record_by_external_id"] = "get_record_by_external_id"
    external_id: str = Field(..., min_length=1, max_length=256)

    @field_validator("external_id")
    @classmethod
    def external_identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a record external ID without control characters or dot segments")
        return value


class Spotio2FieldValue(_Input):
    field_id: Identifier = Field(..., alias="fieldId")
    value: str | None = Field(None, max_length=100000)
    values: list[str] | None = Field(None, max_length=1000)


class Spotio2Pin(_Input):
    lat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    address: str | None = Field(None, max_length=4096)


class Spotio2CreateRecord(_Input):
    """Create a record from a company-defined type and its field IDs."""
    operation: Literal["create_record"] = "create_record"
    type_id: int = Field(..., ge=1, le=2147483647)
    fields: list[Spotio2FieldValue] = Field(..., min_length=1, max_length=1000)
    stage_id: int | None = Field(None, ge=1, le=2147483647)
    owner_id: int | None = Field(None, ge=1, le=2147483647)
    external_id: str | None = Field(None, max_length=256)
    source: str | None = Field(None, max_length=4096)
    pin: Spotio2Pin | None = None


class Spotio2UpdateRecord(_Record):
    """Patch only supplied record fields using SPOTIO's JSON Patch endpoint."""
    operation: Literal["update_record"] = "update_record"
    stage_id: int | None = Field(None, ge=1, le=2147483647)
    owner_id: int | None = Field(None, ge=1, le=2147483647)
    external_id: str | None = Field(None, max_length=256)
    source: str | None = Field(None, max_length=4096)
    fields: list[Spotio2FieldValue] | None = Field(None, max_length=1000, description="Replaces the fields array when supplied; include every field to retain.")

    @model_validator(mode="after")
    def nonempty(self):
        if not any(getattr(self, k) is not None for k in RECORD_KEYS):
            raise ValueError("Supply at least one record change")
        return self


class Spotio2DeleteRecord(_Record):
    """Delete the selected record. Permanent deletion requires opting in."""
    operation: Literal["delete_record"] = "delete_record"
    permanently: bool = False


class Spotio2CreateActivity(_Input):
    """Log a note or event against one record without sending a communication."""
    operation: Literal["create_activity"] = "create_activity"
    record_id: Identifier
    activity_type: Literal["Note", "Event"] = "Note"
    notes: str = Field(..., min_length=1, max_length=512)
    title: str | None = Field(None, max_length=128)
    activity_template_id: Identifier | None = None
    owner_id: Identifier | None = None
    date: AwareDatetime | None = None
    done: bool = False


class Spotio2GetActivity(_Input):
    operation: Literal["get_activity"] = "get_activity"
    activity_id: Identifier


class Spotio2ListActivities(_Input):
    """Read a page of the activity feed; preserve ScrollId for continuation."""
    operation: Literal["list_activities"] = "list_activities"
    scroll_id: str | None = Field(None, max_length=8192)
    start_date: AwareDatetime | None = None
    end_date: AwareDatetime | None = None
    territory_id: Identifier | None = None


class Spotio2CreateAppointment(_Input):
    """Schedule one appointment. Sending an email invitation is an explicit option."""
    operation: Literal["create_appointment"] = "create_appointment"
    record_id: Identifier
    owner_id: Identifier
    date: AwareDatetime
    duration: int = Field(..., ge=1, le=2147483647, description="Duration in minutes.")
    title: str = Field(..., min_length=1, max_length=1000)
    notes: str | None = Field(None, max_length=100000)
    activity_template_id: Identifier | None = None
    remind_before_in_seconds: int | None = Field(None, ge=0, le=2147483647)
    send_invitation: bool = Field(False, description="Send an invitation email through SPOTIO.")


class Spotio2GetAppointment(_Input):
    operation: Literal["get_appointment"] = "get_appointment"
    appointment_id: Identifier


class Spotio2ListRecordAppointments(_Record):
    operation: Literal["list_record_appointments"] = "list_record_appointments"
    scroll_id: str | None = Field(None, max_length=8192)


Spotio2Operation = Annotated[Union[
    Spotio2ListUsers, Spotio2ListTeams, Spotio2GetTeam, Spotio2ListTerritories,
    Spotio2GetTerritory, Spotio2ListRecordTypes, Spotio2GetRecordType,
    Spotio2ListActivityTemplates, Spotio2SearchRecords, Spotio2GetRecord,
    Spotio2GetRecordByExternalId, Spotio2CreateRecord, Spotio2UpdateRecord,
    Spotio2DeleteRecord, Spotio2CreateActivity, Spotio2GetActivity,
    Spotio2ListActivities, Spotio2CreateAppointment, Spotio2GetAppointment,
    Spotio2ListRecordAppointments,
], Field(discriminator="operation")]


class Spotio2Config(NodeConfig[Spotio2Operation, Spotio2TokenCredential]):
    pass


RECORD_KEYS = {"stage_id": "stageId", "owner_id": "ownerId", "external_id": "externalDataObjectId", "source": "source", "fields": "fields"}
READ_ROUTES = {
    "list_users": ("/api/users", {"territory_ids": "territoryIds"}),
    "list_teams": ("/api/Teams/all", {}),
    "get_team": ("/api/Teams/{team_id}", {}),
    "list_territories": ("/api/Territories/all", {}),
    "get_territory": ("/api/Territories/{territory_id}", {}),
    "list_record_types": ("/api/workflow/dataObjects", {}),
    "get_record_type": ("/api/workflow/dataObjects/{type_id}", {}),
    "list_activity_templates": ("/api/workflow/activityTemplates", {}),
    "search_records": ("/api/DataObjectsSearch/simple", {"query": "q", "scroll_id": "scrollId", "filter_id": "filterId", "type_id": "typeId", "page_size": "pageSize", "phone_number": "phoneNumber"}),
    "get_record": ("/api/DataObjects/{record_id}", {}),
    "get_record_by_external_id": ("/api/DataObjects/external/{external_id}", {}),
    "get_activity": ("/api/v2/activities/{activity_id}", {}),
    "list_activities": ("/api/v2/activities/feed", {"scroll_id": "ScrollId", "start_date": "StartDate", "end_date": "EndDate", "territory_id": "TerritoryId"}),
    "get_appointment": ("/api/v2/appointments/{appointment_id}", {}),
    "list_record_appointments": ("/api/DataObjects/{record_id}/appointments/upcoming", {"scroll_id": "scrollId"}),
}


def _request_config(config):
    values = config.model_dump(mode="json", exclude_none=True, by_alias=True)
    op = config.operation
    if op in READ_ROUTES:
        route, query = READ_ROUTES[op]
        route = re.sub(r"\{(\w+)\}", lambda match: quote(str(values[match[1]]), safe=""), route)
        return "GET", route, {wire: values[key] for key, wire in query.items() if key in values}, None, "application/json"
    if op == "create_record":
        body = {wire: values[key] for key, wire in {**RECORD_KEYS, "type_id": "typeId", "pin": "pin"}.items() if key in values}
        return "POST", "/api/DataObjects", {}, {"dataObject": body}, "application/json"
    if op == "update_record":
        body = [{"op": "add", "path": "/" + wire, "value": values[key]} for key, wire in RECORD_KEYS.items() if key in values]
        return "PATCH", "/api/DataObjects/" + quote(config.record_id, safe="") + "/jsonp", {}, body, "application/json-patch+json"
    if op == "delete_record":
        return "DELETE", "/api/DataObjects/" + quote(config.record_id, safe=""), {}, {"mode": "Delete", "permanently": config.permanently}, "application/json"
    if op == "create_activity":
        body = {wire: values[key] for key, wire in {"record_id": "dataObjectId", "activity_type": "type", "notes": "notes", "title": "title", "activity_template_id": "activityTemplateId", "owner_id": "ownerId", "date": "date", "done": "done"}.items() if key in values}
        body["isNote"] = config.activity_type == "Note"
        return "POST", "/api/v2/activities", {}, body, "application/json"
    if op == "create_appointment":
        mapping = {"record_id": "dataObjectId", "owner_id": "ownerId", "date": "date", "duration": "duration", "title": "title", "notes": "notes", "activity_template_id": "activityTemplateId", "remind_before_in_seconds": "remindBeforeInSeconds", "send_invitation": "sendInvitation"}
        return "POST", "/api/v2/appointments", {}, {wire: values[key] for key, wire in mapping.items() if key in values}, "application/json"
    raise ValueError("Unsupported SPOTIO operation")


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k.replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class Spotio2Node(WorkflowNode):
    integration_type = "automation-spotio2"
    connection_evidence = ConnectionEvidence(noun="company users", operation="list_users", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return Spotio2Config

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", FAMILY) != FAMILY:
            raise ValueError("Connect a SPOTIO API token credential")
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", FAMILY) != FAMILY:
            return {"valid": False, "errors": ["Connect a SPOTIO API token credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a SPOTIO API token")
        secret = self.config.credentials.api_token
        method, route, params, body, media = _request_config(self.config.config)
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = media
        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=30.0) as client:
            async with client.stream(method, BASE + route, params=params, headers=headers, **({"json": body} if body is not None else {})) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError("SPOTIO response exceeds 8 MiB; narrow the query")
                if not 200 <= response.status_code < 300:
                    message = "SPOTIO request failed"
                    try:
                        error = json.loads(raw)
                        if isinstance(error, dict):
                            message = error.get("message") or error.get("error") or error.get("errors") or message
                    except (ValueError, UnicodeError):
                        pass
                    return {"status": "error", "http_status": response.status_code, "error": _redact(str(message), secret)}
                if not raw.strip() and (response.status_code == 204 or method == "DELETE"):
                    return {"status": "success", "http_status": response.status_code, "data": None}
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise ValueError("SPOTIO returned an invalid JSON response") from None
                if not isinstance(data, (dict, list)):
                    raise ValueError("SPOTIO returned an unexpected JSON shape")
                if isinstance(data, dict) and (data.get("errors") or data.get("error") or data.get("success") is False):
                    return {"status": "error", "http_status": response.status_code, "error": _redact(str(data.get("errors") or data.get("error") or "SPOTIO reported a failure"), secret)}
                return {"status": "success", "http_status": response.status_code, "data": _redact(data, secret)}
