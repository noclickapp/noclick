"""Ticket Tailor v1: box-office reports and existing-draft metadata updates."""
from __future__ import annotations

import base64
from datetime import date, datetime, time
import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_serializer, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

TYPE = "ticket_tailor"
_INVALID = "Ticket Tailor returned an unexpected response; this outcome is unverified"
Id = Annotated[StrictStr, Field(min_length=4, max_length=128, pattern=r"^[a-z]+_[A-Za-z0-9_-]+$")]
EventId = Annotated[StrictStr, Field(min_length=4, max_length=128, pattern=r"^ev_[A-Za-z0-9_-]+$")]
SeriesId = Annotated[StrictStr, Field(min_length=4, max_length=128, pattern=r"^es_[A-Za-z0-9_-]+$")]
OrderId = Annotated[StrictStr, Field(min_length=4, max_length=128, pattern=r"^or_[A-Za-z0-9_-]+$")]
TicketId = Annotated[StrictStr, Field(min_length=4, max_length=128, pattern=r"^it_[A-Za-z0-9_-]+$")]
Text = Annotated[StrictStr, Field(min_length=1, max_length=500)]


class TicketTailorCredential(BaseModel):
    model_config = ConfigDict(title="Ticket Tailor API Key", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.tickettailor.com/docs/api/ticket-tailor-api/",
        "x-credential-instructions": "Create your own box-office API key in Ticket Tailor settings. The key accesses only that box office. Enter its exact displayed name to check the protected overview response. No OAuth, account creation or automatic key minting is used.",
    })
    credential_type: Literal["ticket_tailor"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: Annotated[StrictStr, Field(min_length=1, max_length=4096)] = Field(..., title="Box-office API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    expected_box_office_name: Text = Field(..., title="Expected Box-office Name", description="Exact protected overview name. The API does not provide a stable account ID here.", repr=False)

    @field_validator("api_key", "expected_box_office_name")
    @classmethod
    def clean(cls, value, info):
        if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value) or (info.field_name == "api_key" and (":" in value or any(c.isspace() for c in value))):
            raise ValueError("Enter the exact Ticket Tailor field without controls or surrounding whitespace")
        return value

    @model_serializer(mode="wrap")
    def connect_type(self, handler):
        return {**handler(self), "credential_type": TYPE}


def _credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("A Ticket Tailor API-key credential is required")
    try:
        return TicketTailorCredential.model_validate(raw)
    except Exception:
        raise ValueError("Ticket Tailor credential fields are invalid") from None


def _raw_guard(data):
    raw = data.get("credentials") if isinstance(data, dict) else None
    if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != TYPE:
        raise ValueError("A Ticket Tailor API-key credential is required")


def op(name, title, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


def picker(name, resource, parent=None):
    options = {"field_name": name, "allow_custom": True, "searchable": name == "event_id", "custom_placeholder": "Exact same-box-office ID"}
    if parent:
        options["depends_on"] = parent
    return {"x-dynamic-options": options, "x-resource-type": resource}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(Config):
    operation: Literal["check_connection"] = op("check_connection", "Check Box-office Access", "Account")


class GetOverview(Config):
    operation: Literal["get_overview"] = op("get_overview", "Get Box-office Overview", "Reports")


class Page(Config):
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = Field(25, title="Page Size")
    starting_after: Optional[Id] = Field(None, title="Next-page Cursor", description="One page only. Enter the returned next cursor; provider link URLs are never followed.")


class ListEvents(Page):
    operation: Literal["list_events"] = op("list_events", "List Event Metadata", "Events")
    name: Optional[Text] = None
    status: Optional[Literal["draft", "published", "sales_closed"]] = None


class GetEvent(Config):
    operation: Literal["get_event"] = op("get_event", "Get Event Metadata", "Events")
    event_id: EventId = Field(..., title="Event ID", json_schema_extra=picker("event_id", "ticket_tailor_event"))


class ListSeries(Page):
    operation: Literal["list_event_series"] = op("list_event_series", "List Event Series", "Event Series")


class GetSeries(Config):
    operation: Literal["get_event_series"] = op("get_event_series", "Get Event Series", "Event Series")
    event_series_id: SeriesId = Field(..., title="Event Series ID", json_schema_extra=picker("event_series_id", "ticket_tailor_series"))


class ListSeriesEvents(Page, GetSeries):
    operation: Literal["list_series_events"] = op("list_series_events", "List Series Occurrences", "Event Series")


class GetSeriesEvent(GetSeries):
    operation: Literal["get_series_event"] = op("get_series_event", "Get Series Occurrence", "Event Series")
    occurrence_id: EventId = Field(..., title="Occurrence ID", json_schema_extra=picker("occurrence_id", "ticket_tailor_event", "event_series_id"))


class ListTickets(Page, GetEvent):
    operation: Literal["list_issued_tickets"] = op("list_issued_tickets", "List Event Ticket Reports", "Reports")
    status: Optional[Literal["valid", "voided"]] = None


class GetTicket(GetEvent):
    operation: Literal["get_issued_ticket"] = op("get_issued_ticket", "Get Event Ticket Report", "Reports")
    ticket_id: TicketId = Field(..., title="Issued Ticket ID", json_schema_extra=picker("ticket_id", "ticket_tailor_ticket", "event_id"))


class ListOrders(Page, GetEvent):
    operation: Literal["list_orders"] = op("list_orders", "List Event Order Reports", "Reports")
    status: Optional[Literal["completed", "pending", "canceled"]] = None


class GetOrder(GetEvent):
    operation: Literal["get_order"] = op("get_order", "Get Event Order Report", "Reports")
    order_id: OrderId = Field(..., title="Order ID", json_schema_extra=picker("order_id", "ticket_tailor_order", "event_id"))


class UpdateDraftSeries(GetSeries):
    operation: Literal["update_draft_series"] = op("update_draft_series", "Update Draft Series Metadata", "Event Series")
    name: Text
    description: Optional[Annotated[StrictStr, Field(max_length=10000)]] = None
    venue: Optional[Text] = None


class UpdateDraftOccurrence(GetSeriesEvent):
    operation: Literal["update_draft_occurrence"] = op("update_draft_occurrence", "Update Draft Occurrence Dates", "Event Series")
    start_date: StrictStr = Field(..., description="YYYY-MM-DD in the series timezone")
    start_time: StrictStr = Field(..., description="HH:MM:SS in the series timezone")
    end_date: StrictStr = Field(..., description="YYYY-MM-DD in the series timezone")
    end_time: StrictStr = Field(..., description="HH:MM:SS in the series timezone")

    @model_validator(mode="after")
    def dates(self):
        try:
            if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in (self.start_date, self.end_date)) or any(not re.fullmatch(r"\d{2}:\d{2}:\d{2}", value) for value in (self.start_time, self.end_time)):
                raise ValueError
            start = datetime.combine(date.fromisoformat(self.start_date), time.fromisoformat(self.start_time))
            end = datetime.combine(date.fromisoformat(self.end_date), time.fromisoformat(self.end_time))
            if end < start:
                raise ValueError
        except ValueError:
            raise ValueError("Use valid local dates/times with end at or after start; the provider validates its series timezone") from None
        return self


class TicketTailorNodeConfig(NodeConfig):
    model_config = ConfigDict(hide_input_in_errors=True)
    credentials: Optional[TicketTailorCredential] = None
    config: Annotated[Union[CheckConnection, GetOverview, ListEvents, GetEvent, ListSeries, GetSeries, ListSeriesEvents, GetSeriesEvent, ListTickets, GetTicket, ListOrders, GetOrder, UpdateDraftSeries, UpdateDraftOccurrence], Field(discriminator="operation")]


class TicketTailorApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        super().__init__({401: "Ticket Tailor rejected the API key", 403: "Ticket Tailor denied this operation; key validity is unverified", 404: "Ticket Tailor resource was not found", 429: "Ticket Tailor rate limit reached; retry later"}.get(status, "Ticket Tailor request outcome is unverified"))


async def _request(credential, method, path, *, params=None, body=None):
    headers = {"Accept": "application/json", "User-Agent": "NoClick-TicketTailor/1.0", "Authorization": "Basic " + base64.b64encode((credential.api_key + ":").encode()).decode()}
    try:
        async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, "https://api.tickettailor.com/v1/" + path, params=params, data=body, headers=headers) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 1048576:
                        raise ValueError("Ticket Tailor response exceeded the native bound")
                    raw.extend(chunk)
                if response.status_code != 200:
                    raise TicketTailorApiError(response.status_code)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError(_INVALID)
                def pairs(entries):
                    result = {}
                    for key, value in entries:
                        if key in result:
                            raise ValueError
                        result[key] = value
                    return result
                try:
                    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeError, RecursionError):
                    raise ValueError(_INVALID) from None
    except httpx.RequestError:
        raise ValueError("Ticket Tailor transport outcome is unverified") from None


def _text(value, bound=10000):
    if not isinstance(value, str) or len(value) > bound:
        raise ValueError(_INVALID)
    return value


def _id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[A-Za-z0-9_-]{1,124}", value):
        raise ValueError(_INVALID)
    return value


def _overview(raw, credential):
    if not isinstance(raw, dict) or raw.get("box_office_name") != credential.expected_box_office_name:
        raise ValueError("Ticket Tailor box-office name does not match the credential")
    result = {"box_office_name": raw["box_office_name"]}
    for key in ("event_occurrences_draft", "event_occurrences_published", "event_series_draft", "event_series_published", "orders_received", "total_issued_tickets", "waitlist_signups", "next_event_in"):
        if key in raw and raw[key] is not None:
            if type(raw[key]) is not int or raw[key] < 0:
                raise ValueError(_INVALID)
            result[key] = raw[key]
    return result


def _record(raw, kind, *, resource_id=None, event_id=None, series_id=None):
    objects = {"event": "ev", "event_series": "es", "order": "or", "issued_ticket": "it"}
    if not isinstance(raw, dict) or raw.get("object") != kind:
        raise ValueError(_INVALID)
    record_id = _id(raw.get("id"), objects[kind])
    if resource_id and record_id != resource_id:
        raise ValueError("Ticket Tailor returned a different resource ID")
    result = {"id": record_id, "object": kind}
    if kind in {"event", "event_series"}:
        if kind == "event_series" and (not raw.get("name") or raw.get("status") not in {"draft", "published", "sales_closed"}):
            raise ValueError(_INVALID)
        if kind == "event" and not raw.get("name") and not isinstance(raw.get("start"), dict):
            raise ValueError(_INVALID)
        for key in ("name", "description", "timezone", "currency", "status"):
            if raw.get(key) is not None:
                result[key] = _text(raw[key])
        if raw.get("venue") is not None:
            venue = raw["venue"]
            if not isinstance(venue, dict):
                raise ValueError(_INVALID)
            result["venue"] = {key: _text(venue[key], 500) for key in ("name", "country", "postal_code") if venue.get(key) is not None}
        for key in ("start", "end"):
            if key in raw:
                value = raw[key]
                if not isinstance(value, dict):
                    raise ValueError(_INVALID)
                result[key] = {name: _text(value[name], 128) for name in ("date", "time", "timezone", "iso") if value.get(name) is not None}
        if raw.get("event_series_id") is not None:
            result["event_series_id"] = _id(raw["event_series_id"], "es")
        if series_id and result.get("event_series_id") != series_id:
            raise ValueError("Ticket Tailor occurrence is outside the selected series")
    elif kind == "issued_ticket":
        if raw.get("status") not in {"valid", "voided"} or raw.get("event_id") != event_id:
            raise ValueError("Ticket Tailor ticket is outside the selected event or malformed")
        result.update({"event_id": _id(raw["event_id"], "ev"), "status": raw["status"]})
        for key, prefix in (("event_series_id", "es"), ("order_id", "or"), ("ticket_type_id", "tt")):
            if raw.get(key) is not None:
                result[key] = _id(raw[key], prefix)
    else:
        summary = raw.get("event_summary")
        if not isinstance(summary, dict) or summary.get("event_id") != event_id or raw.get("status") not in {"completed", "pending", "canceled"}:
            raise ValueError("Ticket Tailor order is outside the selected event or its binding is unverified")
        currency = raw.get("currency")
        if not isinstance(currency, dict) or type(currency.get("base_multiplier")) is not int or currency["base_multiplier"] < 1:
            raise ValueError(_INVALID)
        result.update({"event_id": _id(summary["event_id"], "ev"), "status": raw["status"], "currency": {"code": _text(currency.get("code"), 16), "base_multiplier": currency["base_multiplier"]}})
        for key in ("subtotal", "tax", "total", "refund_amount"):
            if type(raw.get(key)) is not int:
                raise ValueError(_INVALID)
            result[key] = raw[key]
        # The published Order example omits total_paid; preserve it when returned.
        if raw.get("total_paid") is not None:
            if type(raw["total_paid"]) is not int:
                raise ValueError(_INVALID)
            result["total_paid"] = raw["total_paid"]
    for key in ("created_at", "updated_at", "voided_at"):
        if raw.get(key) is not None:
            if type(raw[key]) is not int or raw[key] < 0:
                raise ValueError(_INVALID)
            result[key] = raw[key]
    return result


def _page(raw, kind, path, args, *, event_id=None, series_id=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list) or len(raw["data"]) > args.limit or not isinstance(raw.get("links"), dict) or "next" not in raw["links"]:
        raise ValueError(_INVALID)
    rows = [_record(row, kind, event_id=event_id, series_id=series_id) for row in raw["data"]]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError(_INVALID)
    next_cursor = None
    link = raw["links"].get("next")
    if link is not None:
        if not isinstance(link, str) or len(link) > 4096:
            raise ValueError(_INVALID)
        parsed = urlsplit(link)
        if (parsed.scheme or parsed.netloc) and (parsed.scheme != "https" or parsed.netloc != "api.tickettailor.com"):
            raise ValueError("Ticket Tailor pagination link is outside the fixed API host")
        if parsed.fragment or parsed.path != "/v1/" + path:
            raise ValueError("Ticket Tailor pagination link is outside the selected resource")
        params = parse_qs(parsed.query, keep_blank_values=True)
        cursor = params.get("starting_after")
        if not rows or not isinstance(cursor, list) or len(cursor) != 1 or cursor[0] != rows[-1]["id"] or cursor[0] == args.starting_after:
            raise ValueError("Ticket Tailor pagination cursor is inconsistent")
        next_cursor = cursor[0]
    return {"items": rows, "next_cursor": next_cursor, "limit": args.limit, "automatic_paging": False}


class TicketTailorNode(WorkflowNode):
    integration_type = "automation-ticket-tailor"
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", identity_keys=("box_office_name",), noun="Ticket Tailor box office", proves="account")

    @classmethod
    def get_config_model(cls):
        return TicketTailorNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        _raw_guard(config_data)
        return super().validate_config(config_data)

    async def execute(self, input_data):
        _raw_guard(self.node_data)
        if self.config.credentials is None:
            raise ValueError("Ticket Tailor credentials are required")
        args = self.config.config
        action = args.operation
        kinds = {"list_events": ("event", "events"), "list_event_series": ("event_series", "event_series"), "list_series_events": ("event", "event_series/" + getattr(args, "event_series_id", "") + "/events"), "list_issued_tickets": ("issued_ticket", "issued_tickets"), "list_orders": ("order", "orders")}
        if action in kinds and args.starting_after:
            _id(args.starting_after, {"event": "ev", "event_series": "es", "issued_ticket": "it", "order": "or"}[kinds[action][0]])
        credential = _credential(self.config.credentials.model_dump())
        overview = _overview(await _request(credential, "GET", "overview"), credential)
        async def exact(kind, resource_id, path=None, **parents):
            return _record(await _request(credential, "GET", path or kind + "s/" + resource_id), kind, resource_id=resource_id, **parents)
        if action in {"check_connection", "get_overview"}:
            data = overview
        elif action == "get_event":
            data = await exact("event", args.event_id)
        elif action == "get_event_series":
            data = await exact("event_series", args.event_series_id, "event_series/" + args.event_series_id)
        elif action in kinds:
            kind, path = kinds[action]
            params = {"limit": args.limit}
            for key in ("starting_after", "name", "status"):
                if getattr(args, key, None) is not None:
                    params[key] = getattr(args, key)
            if action == "list_series_events":
                await exact("event_series", args.event_series_id, "event_series/" + args.event_series_id)
            if action in {"list_issued_tickets", "list_orders"}:
                await exact("event", args.event_id)
                params["event_id"] = args.event_id
            data = _page(await _request(credential, "GET", path, params=params), kind, path, args, event_id=getattr(args, "event_id", None), series_id=getattr(args, "event_series_id", None))
        elif action in {"get_issued_ticket", "get_order"}:
            await exact("event", args.event_id)
            kind, resource_id, path = ("issued_ticket", args.ticket_id, "issued_tickets/" + args.ticket_id) if action == "get_issued_ticket" else ("order", args.order_id, "orders/" + args.order_id)
            data = await exact(kind, resource_id, path, event_id=args.event_id)
        elif action in {"get_series_event", "update_draft_series", "update_draft_occurrence"}:
            path = "event_series/" + args.event_series_id
            parent = await exact("event_series", args.event_series_id, path)
            if action.startswith("update_") and parent.get("status") != "draft":
                raise ValueError("Only a verified draft event series may be edited")
            if action == "update_draft_occurrence" and not parent.get("timezone"):
                raise ValueError("Draft series timezone is unverified")
            if action != "update_draft_series":
                path += "/events/" + args.occurrence_id
                data = await exact("event", args.occurrence_id, path, series_id=args.event_series_id)
            else:
                data = parent
            if action.startswith("update_"):
                body = {key: getattr(args, key) for key in (("name", "description", "venue") if action == "update_draft_series" else ("start_date", "start_time", "end_date", "end_time")) if getattr(args, key) is not None}
                data = _record(await _request(credential, "POST", path, body=body), "event_series" if action == "update_draft_series" else "event", resource_id=args.event_series_id if action == "update_draft_series" else args.occurrence_id, series_id=args.event_series_id if action == "update_draft_occurrence" else None)
                current_parent = await exact("event_series", args.event_series_id, "event_series/" + args.event_series_id)
                if current_parent.get("status") != "draft" or (action == "update_draft_series" and data.get("status") != "draft"):
                    raise ValueError("Draft state changed; reconcile the metadata update before retrying")
                data.update({"write_acknowledged": True, "readback_verified": False, "readback_operation": "get_event_series" if action == "update_draft_series" else "get_series_event"})
        else:
            raise ValueError("Unsupported Ticket Tailor operation")
        return {"status": "success", "operation": action, "data": data}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"event_id", "event_series_id", "occurrence_id", "ticket_id", "order_id"} or (context is not None and not isinstance(context, dict)):
            raise ValueError("Unsupported Ticket Tailor picker context")
        if search is not None and (not isinstance(search, str) or len(search) > 500):
            raise ValueError("Invalid Ticket Tailor picker search")
        args = {"limit": 25, "starting_after": page_token}
        if field_name == "event_id":
            args.update({"operation": "list_events", "name": search or None})
        elif field_name == "event_series_id":
            if search:
                raise ValueError("Series picker search is unsupported; use an exact custom ID")
            args["operation"] = "list_event_series"
        elif field_name == "occurrence_id":
            if search:
                raise ValueError("Occurrence picker search is unsupported; use an exact custom ID")
            args.update({"operation": "list_series_events", "event_series_id": (context or {}).get("event_series_id")})
        else:
            if search:
                raise ValueError("Report picker search is unsupported; use an exact custom ID")
            args.update({"operation": "list_issued_tickets" if field_name == "ticket_id" else "list_orders", "event_id": (context or {}).get("event_id")})
        config = TicketTailorNodeConfig.model_validate({"credentials": credential_data, "config": args})
        node = cls(node_id="ticket-tailor-picker", node_type="automation-ticket-tailor", node_data={"config": args, "credentials": config.credentials.model_dump()}, config=config, sio=None, sid=None)
        result = await node.execute({})
        return {"options": [{"value": row["id"], "label": row.get("name") or row["id"]} for row in result["data"]["items"]], "next_page_token": result["data"]["next_cursor"]}
