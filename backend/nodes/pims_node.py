"""Pims REST API v2: events, ticket sales and promotions.

Contract: https://cdn.pims.io/api/openapi_v2.json (version 2.0).
Each action maps to one contract operation; HAL collections retain pagination.
Polling scans the complete selected event scope before updating its seen set.
"""
from __future__ import annotations

from datetime import date, datetime as DateTime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client, normalize_provider_subdomain

DOCS = "https://api.pims.io/v2/index.html"


class PimsBasicCredential(BaseModel):
    model_config = ConfigDict(title="Pims API Account", hide_input_in_errors=True,
                              json_schema_extra={"x-credential-url": DOCS + "#section/Authentication"})
    credential_type: Literal["pims_basic"] = Field("pims_basic", json_schema_extra={"ui:hidden": True})
    customer_domain: str = Field(..., title="Customer Domain", description="Your Pims subdomain, such as caramba, or your https://caramba.pims.io URL. API credentials are customer-specific; request them from Pims with the customer's agreement.")
    username: str = Field(..., min_length=1, max_length=256, title="API Username", description="The API username supplied by Pims.")
    password: str = Field(..., min_length=1, max_length=4096, title="API Password", repr=False,
                          description="The API password supplied by Pims.", json_schema_extra={"ui:widget": "password"})

    @field_validator("customer_domain", mode="before")
    @classmethod
    def domain(cls, value):
        if not isinstance(value, str) or ("/" in value and not value.startswith("https://")):
            raise ValueError("Use your Pims subdomain or its HTTPS URL")
        return normalize_provider_subdomain(value, "pims.io", field_name="Customer Domain")

    @field_validator("username", "password")
    @classmethod
    def basic_parts(cls, value, info):
        if any(ord(c) < 32 or ord(c) == 127 for c in value) or (info.field_name == "username" and ":" in value):
            raise ValueError("Use API credentials without control characters; the username cannot contain a colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, le=100000, title="Page", description="HAL page number; the Pims pagination guide documents ?page=2.")
    page_size: int = Field(25, ge=1, le=1000, title="Page Size")


class _EventWrite(_Input):
    label: str | None = Field(None, max_length=100)
    datetime: DateTime | None = Field(None, description="Event time in the venue's timezone.")
    venue_id: int | None = Field(None, ge=1)
    series_id: int | None = Field(None, ge=1)
    input_type_id: Literal["DET", "GLO"] | None = None
    contract_type_id: str | None = Field(None, min_length=3, max_length=3)
    seating_type_id: str | None = None
    internal_code: str | None = None
    opening_act: str | None = None
    announcement_date: date | None = None
    onsale_date: date | None = None
    sold_out_date: date | None = None
    cancellation_date: date | None = None
    hidden: bool | None = None
    free: bool | None = None


class _PromotionWrite(_Input):
    label: str | None = Field(None, max_length=100)
    type_id: str | None = Field(None, min_length=2, max_length=3)
    cost_type_id: Literal["PAY", "P&E", "ECH", "GRA"] | None = None
    supplier_id: int | None = Field(None, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    quantity: float | None = Field(None, ge=0, allow_inf_nan=False)
    unit_cost: float | None = Field(None, ge=0, allow_inf_nan=False)
    comments: str | None = Field(None, max_length=255)
    external_url: str | None = Field(None, max_length=255)


# Operation -> (method, route, HAL collection key). No arbitrary routes or bodies.
OPERATIONS = {
    'list_events': ('GET', '/events', 'events'),
    'get_event': ('GET', '/events/{event_id}', None),
    'create_event': ('POST', '/events', None),
    'update_event': ('PATCH', '/events/{event_id}', None),
    'delete_event': ('DELETE', '/events/{event_id}', None),
    'list_series': ('GET', '/series', 'series'),
    'get_series': ('GET', '/series/{series_id}', None),
    'list_venues': ('GET', '/venues', 'venues'),
    'get_venue': ('GET', '/venues/{venue_id}', None),
    'list_tickets': ('GET', '/tickets', 'tickets'),
    'get_ticket': ('GET', '/tickets/{ticket_id}', None),
    'list_orders': ('GET', '/orders', 'orders'),
    'get_order': ('GET', '/orders/{order_id}', None),
    'list_promotions': ('GET', '/promotions', 'promotions'),
    'get_promotion': ('GET', '/promotions/{promotion_id}', None),
    'create_promotion': ('POST', '/promotions', None),
    'update_promotion': ('PATCH', '/promotions/{promotion_id}', None),
    'delete_promotion': ('DELETE', '/promotions/{promotion_id}', None),
    'list_ticket_counts': ('GET', '/events/{event_id}/ticket-counts', 'ticket_counts'),
    'list_capacities': ('GET', '/events/{event_id}/capacities', 'capacities'),
    'list_event_categories': ('GET', '/events/{event_id}/categories', 'event_categories'),
    'list_event_channels': ('GET', '/events/{event_id}/channels', 'event_channels'),
    'list_guests': ('GET', '/events/{event_id}/guests', 'guests'),
}


def _operation(name, title=None, trigger=False):
    return (Literal[name], Field(name, title=title or name.replace("_", " ").title(), json_schema_extra={
        "ui:hidden": True, **({"x-is-trigger": True, "x-category": "Triggers"} if trigger else {})}))


def _id():
    return (int, Field(..., ge=1, le=2147483647))


def _optional_id():
    return (int | None, Field(None, ge=1, le=2147483647))


def _make_config(name, method, route, collection):
    fields = {"operation": _operation(name)}
    for component in route.split("/"):
        if component.startswith("{"):
            fields[component[1:-1]] = _id()
    base = _Input
    if collection:
        base = _Page
        # Only documented query parameters, explicitly selected for useful workflows.
        if name in {"list_events", "list_series", "list_venues", "list_promotions"}:
            fields["label"] = (str | None, None)
        if name in {"list_events", "list_series", "list_venues"}:
            for key in ("from_created_at", "from_updated_at"):
                fields[key] = (int | None, Field(None, ge=0))
        if name in {"list_events", "list_series"}:
            fields.update(venue_id=_optional_id(), from_datetime=(DateTime | None, None), to_datetime=(DateTime | None, None))
        if name in {"list_events", "list_promotions"}:
            fields["series_id"] = _optional_id()
        if name in {"list_tickets", "list_promotions"}:
            fields["event_id"] = _optional_id()
        if name == "list_tickets":
            fields.update(order_id=_optional_id(), bar_code=(str | None, None), from_movement_date=(int | None, Field(None, ge=0)))
        if name == "list_orders":
            fields["customer_id"] = _optional_id()
        if name in {"list_capacities", "list_ticket_counts", "list_promotions"}:
            fields.update(from_date=(date | None, None), to_date=(date | None, None))
    if method in {"POST", "PATCH"}:
        base = _EventWrite if name.endswith("event") else _PromotionWrite
        if method == "POST":
            fields["label"] = (str, Field(..., min_length=1, max_length=100))
            if name.endswith("event"):
                fields.update(datetime=(DateTime, ...), venue_id=_id(), input_type_id=(Literal["DET", "GLO"], ...), contract_type_id=(str, Field(..., min_length=3, max_length=3)))
            else:
                fields.update(type_id=(str, Field(..., min_length=2, max_length=3)), cost_type_id=(Literal["PAY", "P&E", "ECH", "GRA"], ...))
    return create_model("Pims" + name.title().replace("_", "") + "Config", __base__=base, __module__=__name__, **fields)


CONFIG_MODELS = {name: _make_config(name, *spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class PimsOnNewEventConfig(PollTriggerConfigBase):
    operation: Literal["on_new_event"] = _operation("on_new_event", "On New Event", True)[1]
    venue_id: int | None = Field(None, ge=1)
    series_id: int | None = Field(None, ge=1)


class PimsOnUpdatedEventConfig(PollTriggerConfigBase):
    operation: Literal["on_updated_event"] = _operation("on_updated_event", "On Updated Event", True)[1]
    venue_id: int | None = Field(None, ge=1)
    series_id: int | None = Field(None, ge=1)


PimsConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (PimsOnNewEventConfig, PimsOnUpdatedEventConfig)], Field(discriminator="operation")]


class PimsNodeConfig(NodeConfig[PimsConfig, PimsBasicCredential]):
    pass


class PimsNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-pims"
    connection_evidence = ConnectionEvidence(operation="list_events", noun="events")

    @classmethod
    def get_config_model(cls):
        return PimsNodeConfig

    async def _request(self, method, route, *, params=None, body=None):
        credential = self.config.credentials
        domain = normalize_provider_subdomain(credential.customer_domain, "pims.io")
        url = f"https://{domain}.pims.io/api/v2{route}"
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, url, params=params, json=body,
                auth=httpx.BasicAuth(credential.username, credential.password),
                headers={"Accept": "application/hal+json"})
        if response.status_code not in {200, 201, 204}:
            # Keep provider problem text for the connection seam, without exposing credentials.
            try:
                problem = response.json()
                detail = problem.get("detail") or problem.get("title") or "Pims request failed"
            except (ValueError, AttributeError):
                detail = "Pims did not return a successful JSON response"
            for secret in (credential.password, credential.username):
                detail = str(detail).replace(secret, "[redacted]")
            raise ValueError(f"Pims HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            return {"deleted": True}
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Pims returned an invalid HAL response")
        return result

    @staticmethod
    def _collection(body, key):
        embedded = body.get("_embedded")
        rows = embedded.get(key) if isinstance(embedded, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Pims returned an invalid HAL collection")
        return rows

    async def _poll(self, config):
        updated = config.operation == "on_updated_event"
        params = {"page_size": 500, "sort": "-updated_at" if updated else "-created_at"}
        for key in ("venue_id", "series_id"):
            if getattr(config, key) is not None:
                params[key] = getattr(config, key)
        rows = []
        for page in range(1, 21):
            if page > 1:
                params["page"] = page
            body = await self._request("GET", "/events", params=params)
            rows.extend(self._collection(body, "events"))
            links = body.get("_links", {})
            if body.get("page_count", page) <= page or not links.get("next"):
                break
        else:
            raise ValueError("Pims event scope exceeds 10,000 events; select a venue or series before polling")
        for row in rows:
            if type(row.get("id")) is not int or type(row.get("updated_at" if updated else "created_at")) is not int:
                raise ValueError("Pims event lacks its ID or documented timestamp")
        fresh = await self._filter_unseen(rows, lambda row: f"{row['id']}:{row['updated_at']}" if updated else str(row['id']))
        return {"operation": config.operation, "events": fresh, "event_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_event", "on_updated_event"}:
            return bool(output.get("event_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") not in {"on_new_event", "on_updated_event"}:
            return super().resolve_agent_event(output)
        events = output.get("events", [])
        if not events:
            return None
        change = "updated" if output["operation"] == "on_updated_event" else "created"
        lines = [f"- {row.get('label') or 'Event'} (event {row['id']}, venue {row.get('venue_id')}, series {row.get('series_id')}), scheduled {row.get('datetime')}" for row in events[:20]]
        return {"text": f"Pims: {len(events)} event(s) {change}.\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Pims API account")
        config = self.config.config
        if isinstance(config, (PimsOnNewEventConfig, PimsOnUpdatedEventConfig)):
            return await self._poll(config)
        method, route, collection = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in tuple(values):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", str(values.pop(field)))
        if method == "PATCH" and not values:
            raise ValueError("Provide at least one field to update")
        if method == "GET" and values.get("page") == 1:
            values.pop("page")
        body = await self._request(method, route, params=values if method == "GET" else None,
                                   body=values if method in {"POST", "PATCH"} else None)
        if collection:
            return {"operation": config.operation, "data": self._collection(body, collection),
                    "page": body.get("page"), "page_count": body.get("page_count"),
                    "total_items": body.get("total_items"), "links": body.get("_links", {})}
        return {"operation": config.operation, "data": body}
