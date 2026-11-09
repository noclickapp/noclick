"""SquadCast incident response operations against its published v3/v4 API.

A manually pasted API refresh token is exchanged on the regional auth host for
each execution. Each operation performs one resource request and returns the
provider data and pagination metadata without following response URLs.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}", value):
                raise ValueError("Use a SquadCast resource ID without URL or path characters")
        return value


class SquadCastAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Squadcast API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.squadcast.com/api/",
            "x-credential-instructions": "In SquadCast, open My Profile and generate an API refresh token. Paste that token and select your account region. Your role controls which reads and changes are allowed.",
        })
    credential_type: Literal["squadcast_api_token"] = Field("squadcast_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Refresh Token", min_length=1, max_length=4096, repr=False,
        description="Paste the API refresh token from My Profile, without a header prefix.",
        json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu"] = Field("us", title="Account Region", description="Choose the region where your SquadCast account is hosted.")

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste an API refresh token without whitespace")
        return value


class GetIncident(_Input):
    """Read an incident by ID or number."""
    operation: Literal["get_incident"] = Field("get_incident", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")


class AcknowledgeIncident(_Input):
    """Acknowledge an incident and stop its pending escalation."""
    operation: Literal["acknowledge_incident"] = Field("acknowledge_incident", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")


class ResolveIncident(_Input):
    """Resolve an incident with a resolution reason."""
    operation: Literal["resolve_incident"] = Field("resolve_incident", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")
    resolution_message: str = Field(..., min_length=1, max_length=50000, title="Resolution Reason")


class ReassignIncident(_Input):
    """Reassign an unresolved incident to a user, squad or escalation policy."""
    operation: Literal["reassign_incident"] = Field("reassign_incident", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")
    assignee_id: str = Field(..., title="Assignee ID")
    assignee_type: Literal["user", "escalationpolicy", "squad"] = Field(..., title="Assignee Type")


class UpdateIncidentPriority(_Input):
    """Change incident priority."""
    operation: Literal["update_incident_priority"] = Field("update_incident_priority", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")
    priority: Literal["P1", "P2", "P3", "P4", "P5"] = Field(..., title="Priority")


class CreateNote(_Input):
    """Add a note to an incident war room."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")
    message: str = Field(..., min_length=1, max_length=50000, title="Message")
    attachments: list[str] = Field(default_factory=list, title="Attachment References", description="Existing SquadCast attachment references; this operation does not upload files.")


class ListNotes(_Input):
    """Read the notes in an incident war room."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")


class ListIncidentEvents(_Input):
    """Read one page of incident events. Preserve meta.next for the next offset."""
    operation: Literal["list_incident_events"] = Field("list_incident_events", json_schema_extra={"ui:hidden": True})
    incident_id: str = Field(..., title="Incident ID")
    offset: int = Field(1, ge=1, title="Offset")
    limit: int = Field(10, ge=1, le=10, title="Page Size")
    sort: Literal["asc", "desc"] = Field("desc", title="Sort")
    deduped: Literal["true", "false"] = Field("true", title="Deduplicated Events", description="True returns deduplicated events; false returns the original event.")


class ListServices(_Input):
    """List services belonging to an explicit owner."""
    operation: Literal["list_services"] = Field("list_services", json_schema_extra={"ui:hidden": True})
    owner_id: str = Field(..., title="Owner ID")
    name: str | None = Field(None, title="Service Name")


class GetService(_Input):
    """Read one service."""
    operation: Literal["get_service"] = Field("get_service", json_schema_extra={"ui:hidden": True})
    service_id: str = Field(..., title="Service ID")


class CreateService(_Input):
    """Create a service for an owner and escalation policy."""
    operation: Literal["create_service"] = Field("create_service", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000, title="Name")
    owner_id: str = Field(..., title="Owner ID")
    escalation_policy_id: str = Field(..., title="Escalation Policy ID")
    description: str | None = Field(None, title="Description")


class UpdateService(_Input):
    """Update the selected service name, description or escalation policy."""
    operation: Literal["update_service"] = Field("update_service", json_schema_extra={"ui:hidden": True})
    service_id: str = Field(..., title="Service ID")
    name: str | None = Field(None, min_length=1, title="Name")
    description: str | None = Field(None, title="Description")
    escalation_policy_id: str | None = Field(None, title="Escalation Policy ID")

    @model_validator(mode="after")
    def has_update(self):
        if all(getattr(self, name) is None for name in ("name", "description", "escalation_policy_id")):
            raise ValueError("Supply at least one service field to update")
        return self


class ListTeams(_Input):
    """List the account teams; also used to prove the connection."""
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True})


class GetTeam(_Input):
    """Read a team."""
    operation: Literal["get_team"] = Field("get_team", json_schema_extra={"ui:hidden": True})
    team_id: str = Field(..., title="Team ID")


class ListTeamMembers(_Input):
    """Read the members of a team."""
    operation: Literal["list_team_members"] = Field("list_team_members", json_schema_extra={"ui:hidden": True})
    team_id: str = Field(..., title="Team ID")


class ListUsers(_Input):
    """List account users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class GetUser(_Input):
    """Read a user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., title="User ID")


class ListSchedules(_Input):
    """Read one page of team schedules. Use pageInfo.nextCursor to continue."""
    operation: Literal["list_schedules"] = Field("list_schedules", json_schema_extra={"ui:hidden": True})
    team_id: str = Field(..., title="Team ID")
    page_size: int = Field(20, ge=1, le=100, title="Page Size")
    cursor: str | None = Field(None, title="Cursor")
    search: str | None = Field(None, title="Search")
    my_on_call: bool | None = Field(None, title="My On Call")


class GetSchedule(_Input):
    """Read an on-call schedule."""
    operation: Literal["get_schedule"] = Field("get_schedule", json_schema_extra={"ui:hidden": True})
    schedule_id: str = Field(..., title="Schedule ID")


class ListRunbooks(_Input):
    """Read the runbooks visible to this API token."""
    operation: Literal["list_runbooks"] = Field("list_runbooks", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetIncident, AcknowledgeIncident, ResolveIncident, ReassignIncident, UpdateIncidentPriority, CreateNote, ListNotes, ListIncidentEvents, ListServices, GetService, CreateService, UpdateService, ListTeams, GetTeam, ListTeamMembers, ListUsers, GetUser, ListSchedules, GetSchedule, ListRunbooks], Field(discriminator="operation")]


class SquadCastFullConfig(NodeConfig[Operation, SquadCastAPITokenCredential]):
    pass


# Every entry is one provider operation, separate from the authentication exchange.
ROUTES = {
    "get_incident": ("GET", "/v3/incidents/{incident_id}"),
    "acknowledge_incident": ("POST", "/v3/incidents/{incident_id}/acknowledge"),
    "resolve_incident": ("POST", "/v3/incidents/{incident_id}/resolve"),
    "reassign_incident": ("POST", "/v3/incidents/{incident_id}/reassign"),
    "update_incident_priority": ("PATCH", "/v3/incidents/{incident_id}/priority"),
    "create_note": ("POST", "/v3/incidents/{incident_id}/warroom"),
    "list_notes": ("GET", "/v3/incidents/{incident_id}/warroom"),
    "list_incident_events": ("GET", "/v3/incidents/{incident_id}/events"),
    "list_services": ("GET", "/v3/services"),
    "get_service": ("GET", "/v3/services/{service_id}"),
    "create_service": ("POST", "/v3/services"),
    "update_service": ("PUT", "/v3/services/{service_id}"),
    "list_teams": ("GET", "/v3/teams"),
    "get_team": ("GET", "/v3/teams/{team_id}"),
    "list_team_members": ("GET", "/v3/teams/{team_id}/members"),
    "list_users": ("GET", "/v3/users"),
    "get_user": ("GET", "/v3/users/{user_id}"),
    "list_schedules": ("GET", "/v4/schedules"),
    "get_schedule": ("GET", "/v4/schedules/{schedule_id}"),
    "list_runbooks": ("GET", "/v3/runbooks"),
}


class SquadCastError(ValueError):
    def __init__(self, message, status=None):
        self.status = status
        super().__init__(message)


def _redact(value, secrets):
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()
                if key.lower() not in {"access_token", "refresh_token", "api_token", "authorization"}}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


async def _response(client, method, url, *, headers, params=None, body=None):
    response = await client.request(method, url, headers=headers, params=params,
                                    **({"json": body} if body is not None else {}))
    if not 200 <= response.status_code < 300:
        message = "SquadCast request failed"
        try:
            payload = response.json()
            meta = payload.get("meta", payload) if isinstance(payload, dict) else {}
            if isinstance(meta, dict):
                candidate = meta.get("error_message") or meta.get("message") or meta.get("error")
                if isinstance(candidate, str):
                    message = candidate[:2000]
        except ValueError:
            pass
        raise SquadCastError(message, response.status_code)
    if len(response.content) > 10_000_000:
        raise SquadCastError("SquadCast response is too large")
    try:
        payload = response.json()
    except ValueError:
        raise SquadCastError("SquadCast returned an invalid JSON response") from None
    if not isinstance(payload, dict) or "data" not in payload or payload.get("error"):
        raise SquadCastError("SquadCast returned an incomplete response")
    return payload


class SquadCastNode(WorkflowNode):
    integration_type = "automation-squadcast"
    connection_evidence = ConnectionEvidence(noun="teams", operation="list_teams", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return SquadCastFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SquadCast API token")
        credential = self.config.credentials
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        route = template.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params, body = None, None
        if isinstance(config, ResolveIncident):
            body = {"resolution_reason": {"message": config.resolution_message}}
        elif isinstance(config, ReassignIncident):
            body = {"reassignTo": {"id": config.assignee_id, "type": config.assignee_type}}
        elif isinstance(config, UpdateIncidentPriority):
            body = {"priority": config.priority}
        elif isinstance(config, CreateNote):
            body = {"message": config.message, "attachments": config.attachments}
        elif isinstance(config, ListIncidentEvents):
            params = {key: str(values[key]) for key in ("offset", "limit", "sort", "deduped")}
        elif isinstance(config, ListServices):
            params = {key: values[key] for key in ("owner_id", "name") if key in values}
        elif isinstance(config, (CreateService, UpdateService)):
            body = {key: value for key, value in values.items() if key not in {"operation", "service_id"}}
            if isinstance(config, CreateService):
                params = {"owner_id": config.owner_id}
        elif isinstance(config, ListSchedules):
            params = {"teamID": config.team_id, "pageSize": config.page_size}
            for key, wire in (("cursor", "cursor"), ("search", "search"), ("my_on_call", "myOnCall")):
                if key in values:
                    params[wire] = str(values[key]).lower() if isinstance(values[key], bool) else values[key]
        suffix = ".eu" if credential.region == "eu" else ""
        secrets = [credential.api_token]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                auth = await _response(client, "GET", f"https://auth{suffix}.squadcast.com/oauth/access-token",
                    headers={"X-Refresh-Token": credential.api_token, "Accept": "application/json"})
                token = auth["data"].get("access_token") if isinstance(auth["data"], dict) else None
                if not isinstance(token, str) or not token or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
                    raise SquadCastError("SquadCast did not return an access token")
                secrets.append(token)
                payload = await _response(client, method, f"https://api{suffix}.squadcast.com" + route,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, params=params, body=body)
            if config.operation.startswith("list_") and config.operation != "list_incident_events" and not isinstance(payload["data"], list):
                raise SquadCastError("SquadCast returned an invalid list response")
            output = {**payload, "status": "success", "operation": config.operation}
        except SquadCastError as exc:
            output = {"status": "error", "operation": config.operation, "error": str(exc), "http_status": exc.status}
        except httpx.HTTPError:
            output = {"status": "error", "operation": config.operation,
                "error": "SquadCast request did not complete. Check the result before retrying a change."}
        output = _redact(output, secrets)
        await self.emit(output)
        return output
