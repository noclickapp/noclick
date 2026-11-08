"""Fomo v1 events, templates, application settings and statistics.

Routes and JSON write envelopes follow the provider's published curl examples
at https://docs.usefomo.com/reference (the ReadMe export has malformed paths).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.fomo.com/api/v1"


class FomoTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Fomo API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.usefomo.com/reference/fomo-api-auth-token",
            "x-credential-instructions": "Select your website in Fomo and open Settings > Site. Copy the Auth Token near the bottom and paste it here. API access requires a paid plan. Each token belongs to one application.",
        },
    )
    credential_type: Literal["fomo_api_token"] = Field("fomo_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class ListEvents(_Input):
    """Read one page of events for the connected application."""
    operation: Literal["list_events"] = "list_events"
    show_meta: bool = Field(False, description="Include Fomo's pagination metadata.")
    per_page: int = Field(100, ge=1, le=100, description="Number of events in this page. Request subsequent pages explicitly.")
    page: int = Field(1, ge=1)
    order_by: Literal["created_at", "event_type_id"] = "created_at"
    order_direction: Literal["asc", "desc"] = "desc"


class GetEvent(_Input):
    """Get an event by its Fomo ID."""
    operation: Literal["get_event"] = "get_event"
    event_id: int = Field(..., gt=0)


class DeleteEvent(_Input):
    """Delete one event by its Fomo ID."""
    operation: Literal["delete_event"] = "delete_event"
    event_id: int = Field(..., gt=0)


class CustomEventField(BaseModel):
    key: str = Field(..., min_length=1)
    value: str
    id: Optional[int] = Field(None, gt=0, description="Existing custom field ID when updating.")


class _EventFields(_Input):
    event_type_id: int = Field(..., gt=0, title="Template ID", description="The Fomo event_type_id for this notification template.")
    external_id: Optional[str] = None
    first_name: Optional[str] = None
    email_address: Optional[str] = None
    ip_address: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    country: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    custom_event_fields_attributes: Optional[list[CustomEventField]] = Field(None, max_length=100)


class CreateEvent(_EventFields):
    """Create a social proof notification event."""
    operation: Literal["create_event"] = "create_event"


class UpdateEvent(_EventFields):
    """Update an event and its notification fields."""
    operation: Literal["update_event"] = "update_event"
    event_id: int = Field(..., gt=0)
    created_at: Optional[str] = Field(None, description="ISO 8601 event timestamp.")


class SearchEventByEmail(_Input):
    """Find an event by the customer's email address."""
    operation: Literal["search_event_by_email"] = "search_event_by_email"
    email_address: str = Field(..., min_length=1)


class SearchEventByExternalID(_Input):
    """Find an event by its identifier in another system."""
    operation: Literal["search_event_by_external_id"] = "search_event_by_external_id"
    external_id: str = Field(..., min_length=1)


class CreateTemplate(_Input):
    """Create a reusable notification template."""
    operation: Literal["create_template"] = "create_template"
    name: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, description="Fomo template text, including any Fomo placeholders.")
    markdown_enabled: Optional[bool] = None
    image_url: Optional[str] = None
    use_avatar: Optional[bool] = None
    use_ip_mapping: Optional[bool] = None


class GetStatistics(_Input):
    """Read application impressions, clicks and conversions in a date range."""
    operation: Literal["get_statistics"] = "get_statistics"
    date_from: Optional[date] = None
    date_to: Optional[date] = None

    @model_validator(mode="after")
    def date_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("The end date must be on or after the start date")
        return self


class UpdateApplication(_Input):
    """Update the application's widget settings."""
    operation: Literal["update_application"] = "update_application"
    application_id: int = Field(..., gt=0)
    name: Optional[str] = None
    url: Optional[str] = None
    language: Optional[str] = None
    page_load: Optional[int] = Field(None, ge=0)
    maximum_per_page: Optional[int] = Field(None, ge=1)
    display_for: Optional[int] = Field(None, ge=0)
    display_interval: Optional[int] = Field(None, ge=0)
    randomize: Optional[bool] = None
    closable: Optional[bool] = None
    display_period: Optional[Literal[1, 2, 3, 4]] = None
    display_threshold: Optional[int] = Field(None, ge=0)
    time_ago_period: Optional[Literal[1, 2, 3, 4]] = None
    time_ago_threshold: Optional[int] = Field(None, ge=0)
    hide_mobile: Optional[bool] = None
    loop_notification: Optional[bool] = None
    position: Optional[Literal["bottom_left", "bottom_right", "top_left", "top_right"]] = None
    theme: Optional[Literal["theme1", "theme2", "custom"]] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None

    @model_validator(mode="after")
    def has_update(self):
        if not self.model_dump(exclude={"operation", "application_id"}, exclude_none=True):
            raise ValueError("Provide at least one application setting to update")
        return self


FomoOperation = Annotated[Union[
    ListEvents, GetEvent, CreateEvent, UpdateEvent, DeleteEvent,
    SearchEventByEmail, SearchEventByExternalID, CreateTemplate, GetStatistics, UpdateApplication,
], Field(discriminator="operation")]


class FomoConfig(NodeConfig[FomoOperation, FomoTokenCredential]):
    pass


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"client_secret", "api_token", "auth_token", "access_token"}}
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value


class FomoNode(WorkflowNode):
    integration_type = "automation-fomo"
    connection_evidence = ConnectionEvidence(noun="events", operation="list_events", label_keys=("title", "message", "id"))

    @classmethod
    def get_config_model(cls):
        return FomoConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Fomo API token")
        op = self.config.config
        values = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        method, path, params, body = "GET", "/applications/me/events", None, None
        if isinstance(op, ListEvents):
            params = values
        elif isinstance(op, (GetEvent, DeleteEvent, UpdateEvent)):
            path += "/" + str(values.pop("event_id"))
            if isinstance(op, DeleteEvent):
                method = "DELETE"
            elif isinstance(op, UpdateEvent):
                method, body = "PATCH", {"event": values}
        elif isinstance(op, CreateEvent):
            method, body = "POST", {"event": values}
        elif isinstance(op, (SearchEventByEmail, SearchEventByExternalID)):
            path += "/find"
            field = "email_address" if isinstance(op, SearchEventByEmail) else "external_id"
            params = {"field": field, "q": values[field]}
        elif isinstance(op, CreateTemplate):
            method, path, body = "POST", "/applications/me/event_types", {"event_type": values}
        elif isinstance(op, GetStatistics):
            path = "/applications/me/dashboard"
            params = {"date_range[" + k.removeprefix("date_") + "]": v for k, v in values.items()}
        elif isinstance(op, UpdateApplication):
            path = "/users/me/applications/" + str(values.pop("application_id"))
            method, body = "PATCH", {"application": values}

        token = self.config.credentials.api_token
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": "Token " + token, "Accept": "application/json", "Content-Type": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Fomo request could not be completed; check the service before retrying a write") from None
        if len(response.content) > 5_000_000:
            raise ValueError("Fomo response exceeds the size limit")
        if response.is_redirect:
            raise ValueError("Fomo redirected the API request")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Fomo returned an unexpected non-JSON response") from None
        if response.is_error or isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
            return _redact({"status": "error", "http_status": response.status_code, "error": data}, token)
        if response.status_code not in {200, 201}:
            raise ValueError("Fomo did not confirm the request")
        if not isinstance(data, (dict, list)):
            raise ValueError("Fomo returned an unexpected JSON shape")
        if isinstance(op, ListEvents):
            # show_meta changes the documented array into an events/meta envelope.
            events = data.get("events") if isinstance(data, dict) else data
            if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
                raise ValueError("Fomo returned an unexpected event list")
            result = {"data": events, "page": op.page, "per_page": op.per_page,
                "meta": data.get("meta") if isinstance(data, dict) else None}
        else:
            if not isinstance(data, dict):
                raise ValueError("Fomo returned an unexpected resource shape")
            result = {"data": data}
        return _redact({"status": "success", "http_status": response.status_code, **result}, token)
