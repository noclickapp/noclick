"""Teamup Calendar API v1 operations using an API key and calendar access key.

Contract: https://stoplight.io/api/v1/projects/teamup/api/nodes/reference/generated_docs_public.yaml
Calendar access permissions govern all reads and writes. A bearer token may be
pasted for calendars whose access key additionally requires a logged-in user.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.teamup.com"


class TeamupCalendarAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Teamup Calendar API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.teamup.com/api-keys/request",
            "x-credential-instructions": "Paste your Teamup API key and the calendar access key from your calendar URL (the ks… segment). Use a key with the permissions your workflow needs. For calendars requiring login, also paste an existing bearer token. NoClick never requests a password or signs you in."})
    credential_type: Literal["teamup_calendar_api_key"] = Field("teamup_calendar_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    calendar_key: str = Field(..., min_length=1, title="Calendar access key", json_schema_extra={"ui:widget": "password"})
    bearer_token: str | None = Field(None, title="Bearer token (optional)", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "calendar_key", "bearer_token", mode="before")
    @classmethod
    def secrets(cls, value, info):
        if info.field_name == "bearer_token" and (value is None or isinstance(value, str) and not value.strip()):
            return None
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the key or token, without a header")
        if info.field_name == "calendar_key" and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Paste the calendar access key from the calendar URL")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Event(_Input):
    event_id: str = Field(..., pattern=r"^[1-9][0-9]*(?:-rid-[1-9][0-9]+)?$", description="Event ID, including -rid-timestamp for a recurring instance")


class TeamupCalendarGetConfiguration(_Input):
    operation: Literal["get_calendar_configuration"] = "get_calendar_configuration"


class TeamupCalendarListEvents(_Input):
    operation: Literal["list_events"] = "list_events"
    start_date: date | None = Field(None, description="YYYY-MM-DD; Teamup defaults to today")
    end_date: date | None = Field(None, description="YYYY-MM-DD; Teamup defaults to start date")
    timezone: str | None = None
    notes_format: Literal["html", "markdown"] | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class _EventWrite(_Input):
    start_dt: datetime = Field(..., description="Event start, including timezone")
    end_dt: datetime = Field(..., description="Event end, including timezone")
    subcalendar_ids: list[int] = Field(..., min_length=1, description="Destination sub-calendar IDs from List Sub-calendars")
    title: str | None = Field(None, max_length=1024)
    location: str | None = Field(None, max_length=255)
    who: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=65535)
    all_day: bool = False
    signup_enabled: bool = False
    signup_visibility: Literal["all_users", "users_with_modify_permission"] | None = None
    signup_limit: int | None = Field(None, ge=0)
    comments_enabled: bool = False
    comments_visibility: Literal["all_users", "users_with_modify_permission"] | None = None
    remote_id: str | None = None
    custom: dict[str, str | list[str]] | None = None
    input_format: Literal["html", "markdown"] = "html"

    @model_validator(mode="after")
    def event_settings(self):
        if self.end_dt < self.start_dt:
            raise ValueError("Event end must be on or after start")
        if self.signup_enabled and (self.signup_visibility is None or self.signup_limit is None):
            raise ValueError("Enabled signups require visibility and a signup limit")
        if self.comments_enabled and self.comments_visibility is None:
            raise ValueError("Enabled comments require visibility")
        return self


class TeamupCalendarCreateEvent(_EventWrite):
    operation: Literal["create_event"] = "create_event"


class TeamupCalendarGetEvent(_Event):
    operation: Literal["get_event"] = "get_event"


class TeamupCalendarAttachment(_Input):
    id: str = Field(..., min_length=1)
    deleted: bool = False


class TeamupCalendarUpdateEvent(_EventWrite, _Event):
    operation: Literal["update_event"] = "update_event"
    version: str | None = Field(None, max_length=12, description="Version from Get Event, for concurrent-edit protection")
    redit: Literal["single", "future", "all"] = "single"
    # Teamup requires an attachment change list on an update. The caller
    # explicitly chooses which attachment IDs to keep or delete.
    attachments: list[TeamupCalendarAttachment] = Field(..., description="Attachment changes: use {id, deleted: false} to keep an attachment or {id, deleted: true} to remove it; [] for no changes")


class TeamupCalendarDeleteEvent(_Event):
    operation: Literal["delete_event"] = "delete_event"
    version: str | None = Field(None, max_length=12)
    redit: Literal["single", "future", "all"] = "single"


class TeamupCalendarGetAuxiliary(_Event):
    operation: Literal["get_event_auxiliary"] = "get_event_auxiliary"


class _CommentWrite(_Event):
    message: str = Field(..., min_length=1)
    name: str | None = None
    email: str | None = None
    input_format: Literal["html", "markdown"] = "html"


class TeamupCalendarCreateComment(_CommentWrite):
    operation: Literal["create_comment"] = "create_comment"


class TeamupCalendarUpdateComment(_CommentWrite):
    operation: Literal["update_comment"] = "update_comment"
    comment_id: str = Field(..., pattern=r"^[0-9]+$")


class TeamupCalendarDeleteComment(_Event):
    operation: Literal["delete_comment"] = "delete_comment"
    comment_id: str = Field(..., pattern=r"^[0-9]+$")


class TeamupCalendarListSignups(_Event):
    operation: Literal["list_signups"] = "list_signups"


class _SignupWrite(_Event):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    remote_id: str | None = None


class TeamupCalendarCreateSignup(_SignupWrite):
    operation: Literal["create_signup"] = "create_signup"


class TeamupCalendarUpdateSignup(_SignupWrite):
    operation: Literal["update_signup"] = "update_signup"
    signup_id: str = Field(..., pattern=r"^[1-9][0-9]*$")


class TeamupCalendarDeleteSignup(_Event):
    operation: Literal["delete_signup"] = "delete_signup"
    signup_id: str = Field(..., pattern=r"^[1-9][0-9]*$")


class TeamupCalendarListSubcalendars(_Input):
    operation: Literal["list_subcalendars"] = "list_subcalendars"
    include_inactive: bool = False
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=1000)
    filter_by: str | None = None


class _SubcalendarWrite(_Input):
    name: str = Field(..., min_length=1, max_length=255)
    active: bool | None = None
    color: int | None = Field(None, ge=1, le=48)
    overlap: bool | None = None
    remote_id: str | None = None


class TeamupCalendarCreateSubcalendar(_SubcalendarWrite):
    operation: Literal["create_subcalendar"] = "create_subcalendar"


class _Subcalendar(_Input):
    subcalendar_id: str = Field(..., pattern=r"^[0-9]+$")


class TeamupCalendarGetSubcalendar(_Subcalendar):
    operation: Literal["get_subcalendar"] = "get_subcalendar"


class TeamupCalendarUpdateSubcalendar(_SubcalendarWrite, _Subcalendar):
    """Patch the named fields; other existing settings are preserved."""
    operation: Literal["update_subcalendar"] = "update_subcalendar"


class TeamupCalendarDeleteSubcalendar(_Subcalendar):
    operation: Literal["delete_subcalendar"] = "delete_subcalendar"


TeamupCalendarConfig = Annotated[Union[
    TeamupCalendarGetConfiguration, TeamupCalendarListEvents, TeamupCalendarCreateEvent,
    TeamupCalendarGetEvent, TeamupCalendarUpdateEvent, TeamupCalendarDeleteEvent,
    TeamupCalendarGetAuxiliary, TeamupCalendarCreateComment, TeamupCalendarUpdateComment,
    TeamupCalendarDeleteComment, TeamupCalendarListSignups, TeamupCalendarCreateSignup,
    TeamupCalendarUpdateSignup, TeamupCalendarDeleteSignup, TeamupCalendarListSubcalendars,
    TeamupCalendarCreateSubcalendar, TeamupCalendarGetSubcalendar,
    TeamupCalendarUpdateSubcalendar, TeamupCalendarDeleteSubcalendar,
], Field(discriminator="operation")]


class TeamupCalendarFullConfig(NodeConfig[TeamupCalendarConfig, TeamupCalendarAPIKeyCredential]):
    pass


# Every entry maps to one published method/path. There are no arbitrary URLs.
ROUTES = {
    "get_calendar_configuration": ("GET", "/configuration", 200),
    "list_events": ("GET", "/events", 200),
    "create_event": ("POST", "/events", 201),
    "get_event": ("GET", "/events/{event_id}", 200),
    "update_event": ("PUT", "/events/{event_id}", 200),
    "delete_event": ("DELETE", "/events/{event_id}", 200),
    "get_event_auxiliary": ("GET", "/events/{event_id}/aux", 200),
    "create_comment": ("POST", "/events/{event_id}/comments", 200),
    "update_comment": ("PUT", "/events/{event_id}/comments/{comment_id}", 200),
    "delete_comment": ("DELETE", "/events/{event_id}/comments/{comment_id}", 204),
    "list_signups": ("GET", "/events/{event_id}/signups", 200),
    "create_signup": ("POST", "/events/{event_id}/signups", 200),
    "update_signup": ("PUT", "/events/{event_id}/signups/{signup_id}", 200),
    "delete_signup": ("DELETE", "/events/{event_id}/signups/{signup_id}", 204),
    "list_subcalendars": ("GET", "/subcalendars", 200),
    "create_subcalendar": ("POST", "/subcalendars", 201),
    "get_subcalendar": ("GET", "/subcalendars/{subcalendar_id}", 200),
    "update_subcalendar": ("PATCH", "/subcalendars/{subcalendar_id}", 200),
    "delete_subcalendar": ("DELETE", "/subcalendars/{subcalendar_id}", 204),
}


def _redact(value, credential):
    secrets = [credential.api_key, credential.calendar_key, credential.bearer_token]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]").replace(quote(secret, safe=""), "[redacted]")
        return value
    if isinstance(value, dict):
        return {key: _redact(item, credential) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    return value


class TeamupCalendarNode(WorkflowNode):
    integration_type = "automation-teamup-calendar"
    connection_evidence = ConnectionEvidence(operation="list_subcalendars", noun="sub-calendars")

    @classmethod
    def get_config_model(cls):
        return TeamupCalendarFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Teamup Calendar API key and calendar access key")
        credential = self.config.credentials
        config = self.config.config
        method, route, expected_status = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        route = route.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        params, body = {}, None
        if config.operation == "list_events":
            params = {wire: values[key] for key, wire in {"start_date": "startDate", "end_date": "endDate", "timezone": "tz", "notes_format": "format"}.items() if key in values}
        elif config.operation == "list_subcalendars":
            params = {"includeInactive": str(config.include_inactive).lower(), "offset": config.offset, "limit": config.limit}
            if config.filter_by is not None:
                params["filterBy"] = config.filter_by
        elif config.operation == "delete_event":
            params = {k: values[k] for k in ("version", "redit") if k in values}
        elif method in {"POST", "PUT", "PATCH"}:
            body = {k: v for k, v in values.items() if k not in {"operation", "event_id", "comment_id", "signup_id", "subcalendar_id", "input_format"}}
            if "input_format" in values:
                params["inputFormat"] = values["input_format"]
            if config.operation == "create_event":
                body["attachments"] = []
        headers = {"Teamup-Token": credential.api_key, "Accept": "application/json"}
        if credential.bearer_token:
            headers["Authorization"] = "Bearer " + credential.bearer_token
        url = BASE + "/" + quote(credential.calendar_key, safe="") + route
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, params=params, json=body, headers=headers)
        except httpx.RequestError:
            raise ValueError("Teamup request could not be completed; a write may need verification before retrying") from None
        if response.status_code != expected_status:
            message = "Teamup returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                message += ": " + str(error.get("error", error.get("message", message))) if isinstance(error, dict) else ""
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, credential)}
        if expected_status == 204:
            return {"status": "success", "deleted": True}
        if len(response.content) > 10_000_000:
            raise ValueError("Teamup returned an oversized response")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Teamup returned an unexpected JSON response")
        if isinstance(data, dict) and ("error" in data or "errors" in data):
            return {"status": "error", "error": _redact(data, credential)}
        result = {"status": "success", "data": _redact(data, credential)}
        if config.operation in {"list_events", "list_subcalendars", "list_signups"}:
            rows = data if config.operation == "list_signups" else data.get("events" if config.operation == "list_events" else "subcalendars")
            if not isinstance(rows, list):
                raise ValueError("Teamup returned an unexpected list response")
            result["items"] = _redact(rows, credential)
            if config.operation == "list_subcalendars":
                result["next_offset"] = config.offset + len(rows) if len(rows) == config.limit else None
        return result
