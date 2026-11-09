"""Flashquotes API v1 reads, pinned to the provider's published OpenAPI contract.

Each operation makes one request; list operations preserve the provider page and
return its next cursor. The pinned contract contains no write endpoints.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.flashquotes.com/api"
CREDENTIAL_TYPE = "flashquotes_api_key"
ResourceId = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


class FlashquotesApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Flashquotes API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.flashquotes.com/settings/integrations",
            "x-credential-instructions": "Copy your API key from Flashquotes Settings > Integrations. Full REST API access requires Scale or an eligible Grandfathered Pro plan. Paste only the key; NoClick sends it as x-api-key.",
        },
    )
    credential_type: Literal["flashquotes_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        description="Your Flashquotes API key from Settings > Integrations.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListEvents(_Input):
    """List Events. Paginated list of events for your company, newest first."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, ge=1, le=100, title='Limit', description='Page size. Default 10, maximum 100.')
    starting_after: ResourceId | None = Field(None, title='Starting After', description='Cursor — the id of the last event from the previous page.')
    service_start_time_gt: AwareDatetime | None = Field(None, title='Service Start Time Gt', description='Events whose service_start_time is strictly after this ISO 8601 datetime (must include timezone, e.g. 2026-06-01T00:00:00Z).')
    service_start_time_gte: AwareDatetime | None = Field(None, title='Service Start Time Gte', description='Events whose service_start_time is at or after this ISO 8601 datetime.')
    service_start_time_lt: AwareDatetime | None = Field(None, title='Service Start Time Lt', description='Events whose service_start_time is strictly before this ISO 8601 datetime.')
    service_start_time_lte: AwareDatetime | None = Field(None, title='Service Start Time Lte', description='Events whose service_start_time is at or before this ISO 8601 datetime.')
    created_at_gt: AwareDatetime | None = Field(None, title='Created At Gt', description='Events created strictly after this ISO 8601 datetime.')
    created_at_gte: AwareDatetime | None = Field(None, title='Created At Gte', description='Events created at or after this ISO 8601 datetime.')
    created_at_lt: AwareDatetime | None = Field(None, title='Created At Lt', description='Events created strictly before this ISO 8601 datetime.')
    created_at_lte: AwareDatetime | None = Field(None, title='Created At Lte', description='Events created at or before this ISO 8601 datetime.')
    location_id: ResourceId | None = Field(None, title='Location Id', description='Filter to events at this location.')
    booking_id: ResourceId | None = Field(None, title='Booking Id', description='Filter to events on this booking.')
    expand: list[Literal['data.location', 'data.services', 'data.staff', 'data.addons', 'data.resources', 'data.checklists', 'data.checklists.tasks', 'data.booking', 'data.booking.lead', 'data.booking.eventType', 'data.booking.invoices', 'data.booking.formResponse']] | None = Field(None, max_length=20, title='Expand', description='Inline related objects. On list endpoints each path must be prefixed with `data.` (e.g. `data.booking.lead`). Allow-listed paths: data.location, data.services, data.staff, data.addons, data.resources, data.checklists, data.checklists.tasks, data.booking, data.booking.lead, data.booking.eventType, data.booking.invoices, data.booking.formResponse. Max 20 paths, max depth 4.')


class GetEvent(_Input):
    """Get Event. Retrieve a single event by id."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: ResourceId = Field(..., title='Event Id', description='The event id.')
    expand: list[Literal['location', 'services', 'staff', 'addons', 'resources', 'checklists', 'checklists.tasks', 'booking', 'booking.lead', 'booking.eventType', 'booking.invoices', 'booking.formResponse']] | None = Field(None, max_length=20, title='Expand', description='Inline related objects. Allow-listed paths: location, services, staff, addons, resources, checklists, checklists.tasks, booking, booking.lead, booking.eventType, booking.invoices, booking.formResponse. Requesting any `booking.*` path auto-promotes `booking`, and `checklists.tasks` auto-promotes `checklists`. Max 20 paths, max depth 4.')


class ListResources(_Input):
    """List Resources. Paginated list of resources for your company, newest first."""
    operation: Literal["list_resources"] = Field("list_resources", json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, ge=1, le=100, title='Limit', description='Page size. Default 10, maximum 100.')
    starting_after: ResourceId | None = Field(None, title='Starting After', description='Cursor — the id of the last resource from the previous page.')
    location_id: ResourceId | None = Field(None, title='Location Id', description='Filter to resources at this location.')


class GetResource(_Input):
    """Get Resource. Retrieve a single resource by id."""
    operation: Literal["get_resource"] = Field("get_resource", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceId = Field(..., title='Resource Id', description='The resource id.')


class GetEventLegacy(_Input):
    """Get Event Details (Legacy). Legacy endpoint returning the original flat event shape."""
    operation: Literal["get_event_legacy"] = Field("get_event_legacy", json_schema_extra={"ui:hidden": True})
    event_id: ResourceId = Field(..., title='Event Id', description='The unique identifier of the event')


class ListEventsLegacy(_Input):
    """List Events (Legacy). Legacy endpoint returning the original wrapped event list shape."""
    operation: Literal["list_events_legacy"] = Field("list_events_legacy", json_schema_extra={"ui:hidden": True})
    event_starts_after: AwareDatetime = Field(..., title='Event Starts After', description='ISO 8601 date-time with timezone (e.g., 2024-01-01T00:00:00-05:00)')
    event_starts_before: AwareDatetime = Field(..., title='Event Starts Before', description='ISO 8601 date-time with timezone (e.g., 2024-01-08T00:00:00-05:00)')

    @model_validator(mode="after")
    def valid_window(self):
        span = self.event_starts_before - self.event_starts_after
        if not timedelta(0) < span <= timedelta(days=7):
            raise ValueError("The legacy event window must be positive and at most seven days; use list_events for wider ranges")
        return self


class GetFormResponse(_Input):
    """Get Form Response. Retrieve form submission data for a specific response."""
    operation: Literal["get_form_response"] = Field("get_form_response", json_schema_extra={"ui:hidden": True})
    form_response_id: ResourceId = Field(..., title='Form Response Id', description='The form response identifier')


class GetStaff(_Input):
    """Get Staff. Retrieve a single staff member by id."""
    operation: Literal["get_staff"] = Field("get_staff", json_schema_extra={"ui:hidden": True})
    staff_id: ResourceId = Field(..., title='Staff Id', description='The staff id.')


class ListInvoices(_Input):
    """List Invoices. Retrieve all invoices for a specific booking."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})
    booking_id: ResourceId = Field(..., title='Booking Id', description='The booking identifier')


class GetQuote(_Input):
    """Get Quote. Retrieve a quote summary with live totalPriceCents."""
    operation: Literal["get_quote"] = Field("get_quote", json_schema_extra={"ui:hidden": True})
    quote_id: ResourceId = Field(..., title='Quote Id', description='Quote ID.')
    expand: list[Literal['lead', 'location', 'eventType', 'services', 'addons', 'discounts', 'taxRate', 'paymentTerms', 'serviceCharges', 'serviceDays', 'contract', 'booking', 'booking.lead', 'booking.eventType', 'booking.invoices', 'booking.formResponse', 'booking.events', 'booking.events.location', 'booking.events.services', 'booking.events.staff', 'booking.events.addons', 'booking.events.resources', 'booking.events.checklists', 'booking.events.checklists.tasks', 'booking.events.booking', 'booking.events.booking.lead', 'booking.events.booking.eventType', 'booking.events.booking.invoices', 'booking.events.booking.formResponse', 'booking.events.booking.events']] | None = Field(None, max_length=20, title='Expand', description='Use paths without a data. prefix. Repeat expand[] or use comma-separated paths. A nested path includes its parents; unrequested siblings stay absent. Maximum 20 distinct paths per request and four segments, excluding data. Unknown or malformed paths return 400. Allowed paths: lead, location, eventType, services, addons, discounts, taxRate, paymentTerms, serviceCharges, serviceDays, contract, booking, booking.lead, booking.eventType, booking.invoices, booking.formResponse, booking.events, booking.events.location, booking.events.services, booking.events.staff, booking.events.addons, booking.events.resources, booking.events.checklists, booking.events.checklists.tasks, booking.events.booking, booking.events.booking.lead, booking.events.booking.eventType, booking.events.booking.invoices, booking.events.booking.formResponse, booking.events.booking.events.')


class ListQuotes(_Input):
    """List Quotes. List quote summaries for your company with live totals, equality and date-range filters, cursor pagination, and optional related-object expansions."""
    operation: Literal["list_quotes"] = Field("list_quotes", json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, ge=1, le=100, title='Limit', description='Page size, from 1 to 100. Defaults to 10.')
    starting_after: ResourceId | None = Field(None, title='Starting After', description='ID of the last quote in the previous page. The cursor must be accessible and match all supplied filters; otherwise the response is an empty page with hasMore false. Keep filters unchanged between pages.')
    lead_id: ResourceId | None = Field(None, title='Lead Id', description='Filter by exact contact ID.')
    location_id: ResourceId | None = Field(None, title='Location Id', description='Filter by exact location ID.')
    booking_id: ResourceId | None = Field(None, title='Booking Id', description='Filter by exact booking ID.')
    event_type_id: ResourceId | None = Field(None, title='Event Type Id', description='Filter by exact event type ID.')
    created_at_gt: AwareDatetime | None = Field(None, title='Created At Gt', description='Filter quote creation time: strictly after this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    created_at_gte: AwareDatetime | None = Field(None, title='Created At Gte', description='Filter quote creation time: at or after this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    created_at_lt: AwareDatetime | None = Field(None, title='Created At Lt', description='Filter quote creation time: strictly before this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    created_at_lte: AwareDatetime | None = Field(None, title='Created At Lte', description='Filter quote creation time: at or before this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    updated_at_gt: AwareDatetime | None = Field(None, title='Updated At Gt', description='Filter quote row update time (not a complete financial change feed): strictly after this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    updated_at_gte: AwareDatetime | None = Field(None, title='Updated At Gte', description='Filter quote row update time (not a complete financial change feed): at or after this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    updated_at_lt: AwareDatetime | None = Field(None, title='Updated At Lt', description='Filter quote row update time (not a complete financial change feed): strictly before this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    updated_at_lte: AwareDatetime | None = Field(None, title='Updated At Lte', description='Filter quote row update time (not a complete financial change feed): at or before this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    service_start_time_gt: AwareDatetime | None = Field(None, title='Service Start Time Gt', description='Filter service-day start time; at least one day must satisfy all supplied bounds: strictly after this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    service_start_time_gte: AwareDatetime | None = Field(None, title='Service Start Time Gte', description='Filter service-day start time; at least one day must satisfy all supplied bounds: at or after this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    service_start_time_lt: AwareDatetime | None = Field(None, title='Service Start Time Lt', description='Filter service-day start time; at least one day must satisfy all supplied bounds: strictly before this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    service_start_time_lte: AwareDatetime | None = Field(None, title='Service Start Time Lte', description='Filter service-day start time; at least one day must satisfy all supplied bounds: at or before this ISO 8601 datetime. Include a timezone (Z or ±HH:MM); bare dates are rejected.')
    expand: list[Literal['data.lead', 'data.location', 'data.eventType', 'data.services', 'data.addons', 'data.discounts', 'data.taxRate', 'data.paymentTerms', 'data.serviceCharges', 'data.serviceDays', 'data.contract', 'data.booking', 'data.booking.lead', 'data.booking.eventType', 'data.booking.invoices', 'data.booking.formResponse', 'data.booking.events', 'data.booking.events.location', 'data.booking.events.services', 'data.booking.events.staff', 'data.booking.events.addons', 'data.booking.events.resources', 'data.booking.events.checklists', 'data.booking.events.checklists.tasks', 'data.booking.events.booking', 'data.booking.events.booking.lead', 'data.booking.events.booking.eventType', 'data.booking.events.booking.invoices', 'data.booking.events.booking.formResponse', 'data.booking.events.booking.events']] | None = Field(None, max_length=20, title='Expand', description='Every path must start with data. Repeat expand[] or use comma-separated paths. A nested path includes its parents; unrequested siblings stay absent. Maximum 20 distinct paths per request and four segments, excluding data. Unknown or malformed paths return 400. Allowed paths: data.lead, data.location, data.eventType, data.services, data.addons, data.discounts, data.taxRate, data.paymentTerms, data.serviceCharges, data.serviceDays, data.contract, data.booking, data.booking.lead, data.booking.eventType, data.booking.invoices, data.booking.formResponse, data.booking.events, data.booking.events.location, data.booking.events.services, data.booking.events.staff, data.booking.events.addons, data.booking.events.resources, data.booking.events.checklists, data.booking.events.checklists.tasks, data.booking.events.booking, data.booking.events.booking.lead, data.booking.events.booking.eventType, data.booking.events.booking.invoices, data.booking.events.booking.formResponse, data.booking.events.booking.events.')


FlashquotesOperation = Annotated[Union[ListEvents, GetEvent, ListResources, GetResource, GetEventLegacy, ListEventsLegacy, GetFormResponse, GetStaff, ListInvoices, GetQuote, ListQuotes], Field(discriminator="operation")]


class FlashquotesConfig(NodeConfig[FlashquotesOperation, FlashquotesApiKeyCredential]):
    pass


# Fixed provider routes and explicit parameter names; no custom URL or verb input.
ROUTES = {'list_events': ('/events', {}, {'limit': 'limit', 'starting_after': 'starting_after', 'service_start_time_gt': 'service_start_time[gt]', 'service_start_time_gte': 'service_start_time[gte]', 'service_start_time_lt': 'service_start_time[lt]', 'service_start_time_lte': 'service_start_time[lte]', 'created_at_gt': 'created_at[gt]', 'created_at_gte': 'created_at[gte]', 'created_at_lt': 'created_at[lt]', 'created_at_lte': 'created_at[lte]', 'location_id': 'location_id', 'booking_id': 'booking_id', 'expand': 'expand[]'}), 'get_event': ('/events/{id}', {'id': 'event_id'}, {'expand': 'expand[]'}), 'list_resources': ('/resources', {}, {'limit': 'limit', 'starting_after': 'starting_after', 'location_id': 'location_id'}), 'get_resource': ('/resources/{id}', {'id': 'resource_id'}, {}), 'get_event_legacy': ('/event/getEventData/{event_id}', {'event_id': 'event_id'}, {}), 'list_events_legacy': ('/event/get-events', {}, {'event_starts_after': 'event_starts_after', 'event_starts_before': 'event_starts_before'}), 'get_form_response': ('/form_response/{id}', {'id': 'form_response_id'}, {}), 'get_staff': ('/staff/{id}', {'id': 'staff_id'}, {}), 'list_invoices': ('/invoice/{booking_id}', {'booking_id': 'booking_id'}, {}), 'get_quote': ('/quotes/{id}', {'id': 'quote_id'}, {'expand': 'expand[]'}), 'list_quotes': ('/quotes', {}, {'limit': 'limit', 'starting_after': 'starting_after', 'lead_id': 'lead_id', 'location_id': 'location_id', 'booking_id': 'booking_id', 'event_type_id': 'event_type_id', 'created_at_gt': 'created_at[gt]', 'created_at_gte': 'created_at[gte]', 'created_at_lt': 'created_at[lt]', 'created_at_lte': 'created_at[lte]', 'updated_at_gt': 'updated_at[gt]', 'updated_at_gte': 'updated_at[gte]', 'updated_at_lt': 'updated_at[lt]', 'updated_at_lte': 'updated_at[lte]', 'service_start_time_gt': 'service_start_time[gt]', 'service_start_time_gte': 'service_start_time[gte]', 'service_start_time_lt': 'service_start_time[lt]', 'service_start_time_lte': 'service_start_time[lte]', 'expand': 'expand[]'})}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class FlashquotesNode(WorkflowNode):
    integration_type = "automation-flashquotes"
    connection_evidence = ConnectionEvidence(operation="list_resources", noun="resources", label_keys=("name", "id"))
    edit_examples = ["List upcoming events", "Get the quote and its service days", "Find invoices for a booking"]

    @classmethod
    def get_config_model(cls):
        return FlashquotesConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Flashquotes API key")
        op = self.config.config
        key = self.config.credentials.api_key
        values = op.model_dump(mode="json", exclude_none=True)
        path, path_fields, query_fields = ROUTES[op.operation]
        for placeholder, field in path_fields.items():
            path = path.replace("{" + placeholder + "}", values[field])
        params = []
        for field, wire in query_fields.items():
            if field in values:
                value = values[field]
                params.extend((wire, item) for item in (value if isinstance(value, list) else [value]))
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.get(BASE_URL + path, params=params,
                headers={"x-api-key": key, "Accept": "application/json"})
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Flashquotes HTTP {response.status_code}: expected a JSON response") from None
        if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and payload.get("error")):
            error = payload.get("error", payload.get("message", "Request refused")) if isinstance(payload, dict) else "Request refused"
            message = error.get("message", "Request refused") if isinstance(error, dict) else str(error)
            raise ValueError(f"Flashquotes HTTP {response.status_code}: {_redact(message, key)}")
        if not isinstance(payload, (dict, list)):
            raise ValueError("Flashquotes returned an unexpected JSON shape")
        # Preserve modern envelopes, legacy arrays, expanded objects, and the
        # invoice object documented separately from the pinned array schema.
        output = {"status": "success", "data": _redact(payload, key)}
        if op.operation in {"list_events", "list_resources", "list_quotes"}:
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or type(payload.get("hasMore")) is not bool:
                raise ValueError("Flashquotes returned an invalid list envelope")
            rows = payload["data"]
            output["has_more"] = payload["hasMore"]
            output["next_cursor"] = rows[-1].get("id") if payload["hasMore"] and rows and isinstance(rows[-1], dict) else None
        await self.emit(output)
        return output
