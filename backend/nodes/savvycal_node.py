"""SavvyCal v1 operations using a manually supplied personal access token.

Contract: https://api.savvycal.com/v1/spec (1.0.0).
Authentication: https://docs.savvycal.com/developers/authentication.
Each operation makes exactly one request; cursor pages are returned unchanged.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.savvycal.com"


class SavvyCalTokenCredential(BaseModel):
    model_config = ConfigDict(title="SavvyCal Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://savvycal.com/settings/developers",
            "x-credential-instructions": "In SavvyCal, open Settings > Developers, create a personal access token, and paste its Private Key. NoClick uses it to read your account and manage events, scheduling links and webhooks. Use the private key, not the public key.",
        })
    credential_type: Literal["savvycal_token"] = Field("savvycal_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Private key", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Private key")
        if any(c.isspace() for c in value) or value.lower().startswith("bearer "):
            raise ValueError("Paste the private key without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_values(cls, value, info):
        if info.field_name in {"link_id", "event_id", "webhook_id", "workflow_id", "scope_slug"}:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                raise ValueError("Use a single SavvyCal resource ID or scope slug")
        if info.field_name == "time_zone" and isinstance(value, str):
            if not re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", value) or any(p in {".", ".."} for p in value.split("/")):
                raise ValueError("Use an IANA time zone such as America/New_York")
        return value


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, description="Page size. Return cursors are in metadata.after and metadata.before.")
    after: str | None = Field(None, min_length=1, max_length=1000, description="Cursor from metadata.after in a previous response.")
    before: str | None = Field(None, min_length=1, max_length=1000, description="Cursor from metadata.before in a previous response.")

    @model_validator(mode="after")
    def cursor_direction(self):
        if self.after and self.before:
            raise ValueError("Choose either after or before")
        return self


class SavvyCalFieldOption(_Input):
    id: str
    value: str


class SavvyCalFieldAnswer(_Input):
    id: str
    label: str
    type: Literal["short_text", "long_text", "checkboxes", "radios", "select", "url", "hidden"]
    value: str | None = None
    options: list[SavvyCalFieldOption] | None = None


class ListEvents(_Page):
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    state: Literal["all", "any", "confirmed", "canceled", "awaiting_reschedule", "awaiting_checkout", "checkout_expired", "awaiting_approval", "declined", "tentative"] | None = None
    period: Literal["past", "upcoming", "fixed", "all"] = "upcoming"
    from_date: date | None = Field(None, description="Start date for period=fixed (query parameter from).")
    until: date | None = None
    time_zone: str | None = None
    q: str | None = None
    direction: Literal["asc", "desc"] = "asc"
    attendance: Literal["attending", "any"] = "attending"
    link: str | None = Field(None, description="Scheduling link ID or any.")

    @model_validator(mode="after")
    def fixed_dates(self):
        if self.period == "fixed" and (self.from_date is None or self.until is None):
            raise ValueError("A fixed period needs from date and until date")
        if self.from_date and self.until and self.until < self.from_date:
            raise ValueError("Until must not precede from date")
        return self


class GetEvent(_Input):
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: str


class CancelEvent(_Input):
    operation: Literal["cancel_event"] = Field("cancel_event", json_schema_extra={"ui:hidden": True})
    event_id: str
    cancel_reason: str | None = None


class ListLinks(_Page):
    operation: Literal["list_links"] = Field("list_links", json_schema_extra={"ui:hidden": True})
    state: Literal["active", "pending", "disabled", "archived"] | None = None
    scope: str = Field("any", description="A scope slug, personal, or any.")
    q: str | None = None


class CreatePersonalLink(_Input):
    operation: Literal["create_personal_link"] = Field("create_personal_link", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    description: str | None = None
    private_name: str | None = None
    slug: str | None = Field(None, pattern=r"^[A-Za-z0-9-]+$")
    type: Literal["recurring", "single"] = "recurring"


class CreateScopeLink(_Input):
    operation: Literal["create_scope_link"] = Field("create_scope_link", json_schema_extra={"ui:hidden": True})
    scope_slug: str
    name: str = Field(..., min_length=1)
    description: str | None = None
    private_name: str | None = None
    slug: str | None = Field(None, pattern=r"^[A-Za-z0-9-]+$")
    type: Literal["recurring", "single"] = "recurring"


class GetLink(_Input):
    operation: Literal["get_link"] = Field("get_link", json_schema_extra={"ui:hidden": True})
    link_id: str


class UpdateLink(_Input):
    operation: Literal["update_link"] = Field("update_link", json_schema_extra={"ui:hidden": True})
    link_id: str
    name: str | None = Field(None, min_length=1)
    description: str | None = None
    private_name: str | None = None
    slug: str | None = Field(None, pattern=r"^[A-Za-z0-9-]+$")
    type: Literal["recurring", "single"] | None = None

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set.intersection({"name", "description", "private_name", "slug", "type"}):
            raise ValueError("Choose at least one link field to update")
        if any(getattr(self, k) is None for k in self.model_fields_set.intersection({"name", "slug", "type"})):
            raise ValueError("Name, slug and type cannot be cleared")
        return self


class DeleteLink(_Input):
    operation: Literal["delete_link"] = Field("delete_link", json_schema_extra={"ui:hidden": True})
    link_id: str


class DuplicateLink(_Input):
    operation: Literal["duplicate_link"] = Field("duplicate_link", json_schema_extra={"ui:hidden": True})
    link_id: str


class ToggleLink(_Input):
    operation: Literal["toggle_link"] = Field("toggle_link", json_schema_extra={"ui:hidden": True})
    link_id: str


class GetAvailableSlots(_Input):
    operation: Literal["get_available_slots"] = Field("get_available_slots", json_schema_extra={"ui:hidden": True})
    link_id: str
    from_time: datetime | None = Field(None, description="Start instant (query parameter from). Defaults to now.")
    until: datetime | None = Field(None, description="At most 31 days after from. Defaults to 7 days later.")

    @model_validator(mode="after")
    def window(self):
        for value in (self.from_time, self.until):
            if value and value.utcoffset() is None:
                raise ValueError("Use an ISO timestamp with a time zone")
        if self.from_time and self.until:
            days = (self.until - self.from_time).total_seconds() / 86400
            if not 0 < days <= 31:
                raise ValueError("Slot window must be positive and at most 31 days")
        return self


class CreateEvent(_Input):
    operation: Literal["create_event"] = Field("create_event", json_schema_extra={"ui:hidden": True})
    link_id: str
    display_name: str = Field(..., min_length=1)
    email: EmailStr
    start_at: datetime
    end_at: datetime
    time_zone: str = Field(..., description="Scheduler's local IANA time zone.")
    phone_number: str | None = Field(None, pattern=r"^\+[0-9]{7,15}$")
    fields: list[SavvyCalFieldAnswer] | None = Field(None, description="Answers matching custom fields returned by get link.")
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def event_time(self):
        if self.start_at.utcoffset() is None or self.end_at.utcoffset() is None or self.end_at <= self.start_at:
            raise ValueError("Event end must follow start; include time zones")
        return self


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class ListTimeZones(_Input):
    operation: Literal["list_time_zones"] = Field("list_time_zones", json_schema_extra={"ui:hidden": True})
    instant: datetime | None = None
    include_legacy: bool | None = None


class GetTimeZone(_Input):
    operation: Literal["get_time_zone"] = Field("get_time_zone", json_schema_extra={"ui:hidden": True})
    time_zone: str
    instant: datetime | None = None


class ListWebhooks(_Page):
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"ui:hidden": True})


class CreateWebhook(_Input):
    operation: Literal["create_webhook"] = Field("create_webhook", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description="Public HTTPS receiver for SavvyCal webhook deliveries.", json_schema_extra={"format": "uri"})

    @field_validator("url")
    @classmethod
    def webhook_url(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Use a public HTTPS webhook URL without credentials or a fragment")
        return value


class GetWebhook(_Input):
    operation: Literal["get_webhook"] = Field("get_webhook", json_schema_extra={"ui:hidden": True})
    webhook_id: str


class DeleteWebhook(_Input):
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"ui:hidden": True})
    webhook_id: str


class ListWorkflows(_Page):
    operation: Literal["list_workflows"] = Field("list_workflows", json_schema_extra={"ui:hidden": True})


class ListWorkflowRules(_Input):
    operation: Literal["list_workflow_rules"] = Field("list_workflow_rules", json_schema_extra={"ui:hidden": True})
    workflow_id: str


SavvyCalConfig = Annotated[Union[
    ListEvents, GetEvent, CancelEvent, ListLinks, CreatePersonalLink, CreateScopeLink, GetLink, UpdateLink, DeleteLink, DuplicateLink, ToggleLink, GetAvailableSlots, CreateEvent, GetCurrentUser, ListTimeZones, GetTimeZone, ListWebhooks, CreateWebhook, GetWebhook, DeleteWebhook, ListWorkflows, ListWorkflowRules
], Field(discriminator="operation")]


class SavvyCalFullConfig(NodeConfig[SavvyCalConfig, SavvyCalTokenCredential]):
    pass


# operation -> method, fixed contract path, query fields, body fields, success status
OPERATIONS = {
    'list_events': ('GET', '/v1/events', ('limit', 'after', 'before', 'state', 'period', 'from_date', 'until', 'time_zone', 'q', 'direction', 'attendance', 'link'), (), 200),
    'get_event': ('GET', '/v1/events/{event_id}', (), (), 200),
    'cancel_event': ('POST', '/v1/events/{event_id}/cancel', (), ('cancel_reason',), 200),
    'list_links': ('GET', '/v1/links', ('limit', 'after', 'before', 'state', 'scope', 'q'), (), 200),
    'create_personal_link': ('POST', '/v1/links', (), ('name', 'description', 'private_name', 'slug', 'type'), 201),
    'create_scope_link': ('POST', '/v1/scopes/{scope_slug}/links', (), ('name', 'description', 'private_name', 'slug', 'type'), 201),
    'get_link': ('GET', '/v1/links/{link_id}', (), (), 200),
    'update_link': ('PATCH', '/v1/links/{link_id}', (), ('name', 'description', 'private_name', 'slug', 'type'), 200),
    'delete_link': ('DELETE', '/v1/links/{link_id}', (), (), 200),
    'duplicate_link': ('POST', '/v1/links/{link_id}/duplicate', (), (), 200),
    'toggle_link': ('POST', '/v1/links/{link_id}/toggle', (), (), 200),
    'get_available_slots': ('GET', '/v1/links/{link_id}/slots', ('from_time', 'until'), (), 200),
    'create_event': ('POST', '/v1/links/{link_id}/events', (), ('display_name', 'email', 'start_at', 'end_at', 'time_zone', 'phone_number', 'fields', 'metadata'), 200),
    'get_current_user': ('GET', '/v1/me', (), (), 200),
    'list_time_zones': ('GET', '/v1/time_zones', ('instant', 'include_legacy'), (), 200),
    'get_time_zone': ('GET', '/v1/time_zones/{time_zone}', ('instant',), (), 200),
    'list_webhooks': ('GET', '/v1/webhooks', ('limit', 'after', 'before'), (), 200),
    'create_webhook': ('POST', '/v1/webhooks', (), ('url',), 201),
    'get_webhook': ('GET', '/v1/webhooks/{webhook_id}', (), (), 200),
    'delete_webhook': ('DELETE', '/v1/webhooks/{webhook_id}', (), (), 200),
    'list_workflows': ('GET', '/v1/workflows', ('limit', 'after', 'before'), (), 200),
    'list_workflow_rules': ('GET', '/v1/workflows/{workflow_id}/rules', (), (), 200),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class SavvyCalNode(WorkflowNode):
    integration_type = "automation-savvycal"
    connection_evidence = ConnectionEvidence(noun="scheduling links", operation="list_links", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return SavvyCalFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a SavvyCal personal access token")
        config = self.config.config
        token = self.config.credentials.access_token
        method, route, query_fields, body_fields, expected_status = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        for field in re.findall(r"{([a-z_]+)}", route):
            # SavvyCal explicitly requires unescaped slashes for IANA zones.
            route = route.replace("{" + field + "}", quote(values[field], safe="/" if field == "time_zone" else ""))
        query_names = {"from_time": "from", "from_date": "from"}
        params = {query_names.get(k, k): str(values[k]).lower() if isinstance(values[k], bool) else values[k]
                  for k in query_fields if k in values}
        # Preserve explicit null only for the two documented nullable link fields.
        body = {k: values[k] for k in body_fields if k in values}
        for field in ("description", "private_name"):
            if field in body_fields and field in config.model_fields_set and getattr(config, field) is None:
                body[field] = None
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        kwargs = {"json": body} if body_fields else {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, BASE_URL + route, headers=headers, params=params, **kwargs) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 5_000_000:
                            raise ValueError("SavvyCal response exceeds 5 MB; request a smaller page")
                    status = response.status_code
                    if status != expected_status:
                        # Preserve the provider's rejection words for connection evidence.
                        error = raw.decode("utf-8", errors="replace")[:2000]
                        return _redact({"status": "error", "success": False, "http_status": status, "status_code": status,
                            "error": error or "SavvyCal did not return the documented success status",
                            "write_outcome": "unverified" if method != "GET" and (status < 400 or status >= 500) else None}, token)
                    media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if media != "application/json":
                        raise ValueError("Expected a JSON response from SavvyCal")
                    payload = json.loads(raw)
        except httpx.HTTPError:
            raise ValueError("SavvyCal request did not complete. Inspect the provider before retrying a write.") from None
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError("SavvyCal returned invalid JSON. Inspect the provider before retrying a write.") from None
        list_response = config.operation in {"list_events", "list_links", "list_webhooks", "list_workflows"}
        array_response = config.operation in {"get_available_slots", "list_time_zones", "list_workflow_rules"}
        if list_response:
            if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list) or not isinstance(payload.get("metadata"), dict):
                raise ValueError("Unexpected SavvyCal page response")
        elif array_response:
            if not isinstance(payload, list):
                raise ValueError("Unexpected SavvyCal list response")
        elif not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
            raise ValueError("Unexpected SavvyCal resource response")
        output = {"status": "success", "data": payload, "http_status": status}
        return _redact(output, token)
