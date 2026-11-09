"""TimeRex beta scheduling operations using a team's pasted API key.

Auth: https://timerex.stoplight.io/docs/timerex-reference-api/86cyex2iwt9fj-authorization-with-api-key
Each operation performs exactly one request; pagination is explicit and writes
are never retried automatically. User profile is OAuth-only and is not exposed.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://timerex.net/api/beta"
AUTH_DOC = "https://timerex.stoplight.io/docs/timerex-reference-api/86cyex2iwt9fj-authorization-with-api-key"


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Enter a TimeRex ID without a URL or path")
    return value


Identifier = Annotated[str, BeforeValidator(_id)]


class TimeRexAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="TimeRex API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": AUTH_DOC,
        "x-credential-instructions": "In TimeRex, open Dashboard → Team Settings → Developer Tools → TimeRex API. Create and copy the 64-character API key. Paste it here; it grants access only to the team that issued it. Enable API integration in that team's Security settings.",
    })
    credential_type: Literal["timerex_api_key"] = Field("timerex_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Paste the TimeRex API key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Operation):
    nextPageToken: str | None = Field(None, min_length=1, max_length=4096, description="Opaque nextPageToken from the previous response. Returns one page only.")


class GetPrimaryTeam(_Operation):
    """Get the team that issued the API key; also proves the connection."""
    operation: Literal["get_primary_team"] = "get_primary_team"


class ListTeams(_Page):
    """List the team available to this API key, one page at a time."""
    operation: Literal["list_teams"] = "list_teams"


class GetTeam(_Operation):
    """Get a team by its internal TimeRex ID."""
    operation: Literal["get_team"] = "get_team"
    team_id: Identifier


class ListCalendars(_Page):
    """List a team's calendars, excluding restricted folders."""
    operation: Literal["list_calendars"] = "list_calendars"
    team_id: Identifier = Field(..., description="Team ID, or primary for the issuing team's personal space.")
    sort_order: Literal["asc", "desc"] = "asc"


class GetCalendar(_Operation):
    """Get one scheduling calendar."""
    operation: Literal["get_calendar"] = "get_calendar"
    calendar_id: Identifier


class ListEvents(_Page):
    """List one page of calendar events within optional UTC bounds."""
    operation: Literal["list_events"] = "list_events"
    calendar_id: Identifier
    startTime: str | None = Field(None, description="UTC start datetime, e.g. 2023-12-19 15:00:00.")
    endTime: str | None = Field(None, description="UTC end datetime, e.g. 2023-12-19 16:00:00.")

    @field_validator("startTime", "endTime")
    @classmethod
    def utc_time(cls, value):
        if value is not None:
            try:
                if datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S") != value:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use a UTC datetime in YYYY-MM-DD HH:MM:SS format") from None
        return value

    @model_validator(mode="after")
    def order(self):
        if self.startTime and self.endTime and self.startTime >= self.endTime:
            raise ValueError("End time must follow start time")
        return self


class GetEvent(_Operation):
    """Get event details, including guest form and meeting information."""
    operation: Literal["get_event"] = "get_event"
    event_id: Identifier


class CancelEvent(_Operation):
    """Cancel a real event. This can notify attendees; inspect before retrying."""
    operation: Literal["cancel_event"] = "cancel_event"
    event_id: Identifier
    cancellation_reason: str | None = Field(None, max_length=10000)


class GetOneTimeURL(_Operation):
    """Get a single-use scheduling URL and its booking status."""
    operation: Literal["get_one_time_url"] = "get_one_time_url"
    one_time_url_id: Identifier


class CreateOneTimeURL(_Operation):
    """Create a new single-use scheduling URL for a calendar."""
    operation: Literal["create_one_time_url"] = "create_one_time_url"
    calendar_id: Identifier


class WatchOneTimeURL(_Operation):
    """Register an HTTPS endpoint for single-use URL updates."""
    operation: Literal["watch_one_time_url"] = "watch_one_time_url"
    one_time_url_id: Identifier
    token: str = Field(..., min_length=1, max_length=1024, description="Your notification correlation token, echoed by TimeRex.")
    notification_url: str = Field(..., max_length=2048, description="Public HTTPS endpoint receiving TimeRex push notifications.")

    @field_validator("notification_url")
    @classmethod
    def https(cls, value):
        try:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443) or any(c.isspace() for c in value):
                raise ValueError()
        except ValueError:
            raise ValueError("Enter an HTTPS notification endpoint without credentials or a fragment") from None
        return value


TimeRexOperation = Annotated[Union[GetPrimaryTeam, ListTeams, GetTeam, ListCalendars,
    GetCalendar, ListEvents, GetEvent, CancelEvent, GetOneTimeURL, CreateOneTimeURL,
    WatchOneTimeURL], Field(discriminator="operation")]


class TimeRexFullConfig(NodeConfig[TimeRexOperation, TimeRexAPIKeyCredential]):
    model_config = ConfigDict(title="TimeRex Node Configuration")


ROUTES = {
    "get_primary_team": ("GET", "/user/me/teams/primary", 200),
    "list_teams": ("GET", "/user/me/teams", 200),
    "get_team": ("GET", "/teams/{team_id}", 200),
    "list_calendars": ("GET", "/teams/{team_id}/calendars", 200),
    "get_calendar": ("GET", "/calendars/{calendar_id}", 200),
    "list_events": ("GET", "/calendars/{calendar_id}/events", 200),
    "get_event": ("GET", "/events/{event_id}", 200),
    "cancel_event": ("POST", "/events/{event_id}/cancel", 200),
    "get_one_time_url": ("GET", "/calendars/one-time-url/{one_time_url_id}", 200),
    "create_one_time_url": ("POST", "/calendars/{calendar_id}/one-time-url", 201),
    "watch_one_time_url": ("POST", "/calendars/one-time-url/{one_time_url_id}/watch", 201),
}


class TimeRexNode(WorkflowNode):
    integration_type = "automation-timerex"
    credential_provider_labels = {"timerex": "TimeRex"}
    connection_evidence = ConnectionEvidence(noun="TimeRex team", operation="list_teams", identity_operation="get_primary_team")

    @classmethod
    def get_config_model(cls):
        return TimeRexFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            return {"status": "error", "error": "Connect a TimeRex API key"}
        op = self.config.config
        method, template, expected = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path = template.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {key: values[key] for key in ("nextPageToken", "sort_order", "startTime", "endTime") if key in values}
        body = None
        if isinstance(op, CancelEvent):
            body = {"cancellation_reason": op.cancellation_reason} if op.cancellation_reason is not None else {}
        elif isinstance(op, WatchOneTimeURL):
            body = {"token": op.token, "notification_url": op.notification_url}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"x-api-key": self.config.credentials.api_key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if response.status_code != expected:
                message = "TimeRex request failed; check key, team API access and resource ID"
                try:
                    raw = response.json()
                    if isinstance(raw, dict) and isinstance(raw.get("message"), str):
                        message = raw["message"][:1000].replace(self.config.credentials.api_key, "[redacted]")
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code,
                    "error": message,
                    "write_outcome_unknown": method == "POST" and response.status_code >= 500}
            if isinstance(op, CancelEvent):
                return {"status": "success", "http_status": expected, "event_id": op.event_id, "cancelled": True}
            if len(response.content) > 5_000_000:
                raise ValueError("TimeRex response exceeded the size limit")
            data = response.json()
            if isinstance(op, WatchOneTimeURL):
                if not isinstance(data, (dict, list)):
                    raise ValueError("Unexpected TimeRex watch response")
                return {"status": "success", "http_status": expected, "data": data}
            if not isinstance(data, dict) or "error" in data or "errors" in data or "message" in data:
                raise ValueError("Unexpected TimeRex response")
            if isinstance(op, _Page):
                if not isinstance(data.get("items"), list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in data["items"]):
                    raise ValueError("Unexpected TimeRex list response")
                next_token = data.get("nextPageToken")
                if next_token is not None and (not isinstance(next_token, str) or not next_token or next_token == op.nextPageToken):
                    raise ValueError("Invalid TimeRex pagination token")
                return {"status": "success", "http_status": expected, "items": data["items"],
                    "nextPageToken": next_token, "has_more": next_token is not None}
            if not isinstance(data.get("id"), str) or not data["id"]:
                raise ValueError("Unexpected TimeRex resource response")
            return {"status": "success", "http_status": expected, "data": data}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "TimeRex request could not be confirmed; inspect writes before retrying",
                "write_outcome_unknown": method == "POST"}
