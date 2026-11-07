"""Read Bookwhen v2 public schedule metadata using a supplied API token.

Fixed read operations preserve JSON:API resource and event-ticket boundaries;
booking, attendee, download and mutation APIs are not exposed.
"""
from __future__ import annotations
import base64
import json
import math
import re
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

NODE_TYPE = "automation-bookwhen"
FAMILY = "bookwhen_api_token"
FAMILIES = frozenset({FAMILY})
BASE = "https://api.bookwhen.com/v2"
_MISSING = object()
KINDS = {"events": "event", "tickets": "ticket", "locations": "location", "attachments": "attachment", "class_passes": "class_pass"}
FIELDS = {"event_id": "events", "ticket_id": "tickets", "location_id": "locations", "attachment_id": "attachments", "class_pass_id": "class_passes"}


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("Use a single bounded Bookwhen resource ID")
    return value


def _offset(value):
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError("Offset must be an integer from 0 to 1000000")
    return value


def _picker(field, *, parent=None):
    options = {"field_name": field, "placeholder": "Choose resource", "searchable": field != "ticket_id",
        "allow_custom": True, "custom_placeholder": "Paste Bookwhen ID"}
    if parent: options["depends_on"] = parent
    return {"x-dynamic-options": options}


class BookwhenAPITokenCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Bookwhen API Token",
        json_schema_extra={"x-credential-url": "https://support.bookwhen.com/en/articles/753664-bookwhen-api",
            "x-credential-instructions": "Paste an existing Bookwhen v2 access token with the schedule permissions needed for these reads. NoClick sends the token as the Basic username with an empty password to api.bookwhen.com only. No token creation, refresh or OAuth flow is provided. Public schedule reads establish reachability, not user identity or account ownership."})
    credential_type: Literal["bookwhen_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})
    check_resource: Literal["events", "locations", "attachments", "class_passes"] = Field("events", title="Connection read resource")
    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str): raise ValueError("Paste the supplied API token")
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or ":" in value: raise ValueError("Paste the token without a header or colon")
        try: value.encode("utf-8", errors="strict")
        except UnicodeEncodeError: raise ValueError("Use a valid UTF-8 token") from None
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Input):
    offset: int = Field(0, ge=0, le=1_000_000, description="Documented page[offset]; use next_offset returned by the previous page. Server default page size is 20.")
    @field_validator("offset", mode="before")
    @classmethod
    def strict_offset(cls, value): return _offset(value)


class BookwhenCheckConfig(_Input):
    """Read one public schedule page without claiming an account identity."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class BookwhenListEventsConfig(_List):
    """Filter events with documented AND-combined v2 filters."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    calendar: Optional[str] = Field(None, max_length=1000, description="Comma-separated calendar codes; not an ownership proof.")
    entry: Optional[str] = Field(None, max_length=1000, description="Comma-separated entry codes.")
    location: Optional[str] = Field(None, max_length=1000, description="Comma-separated location IDs.")
    tag: Optional[str] = Field(None, min_length=1, max_length=1000)
    title: Optional[str] = Field(None, min_length=1, max_length=1000)
    detail: Optional[str] = Field(None, min_length=1, max_length=1000)
    from_time: Optional[str] = Field(None, description="Inclusive YYYYMMDD or YYYYMMDDHHMISS. If absent Bookwhen defaults to today.")
    to_time: Optional[str] = Field(None, description="Exclusive YYYYMMDD or YYYYMMDDHHMISS.")
    compact: Optional[StrictBool] = Field(None, description="Combine course events into one virtual event.")
    @field_validator("calendar", "entry", "location", mode="before")
    @classmethod
    def ids(cls, value):
        if value is None: return value
        if not isinstance(value, str) or len(value) > 1000 or len(value.split(",")) > 50: raise ValueError("Use bounded comma-separated codes")
        for item in value.split(","): _id(item)
        return value
    @field_validator("from_time", "to_time", mode="before")
    @classmethod
    def time(cls, value):
        if value is None: return value
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}(?:[0-9]{6})?", value): raise ValueError("Use YYYYMMDD or YYYYMMDDHHMISS")
        try: datetime.strptime(value, "%Y%m%d" if len(value) == 8 else "%Y%m%d%H%M%S")
        except ValueError: raise ValueError("Use a valid date or time") from None
        return value
    @model_validator(mode="after")
    def time_order(self):
        if self.from_time and self.to_time and self.from_time.ljust(14, "0") >= self.to_time.ljust(14, "0"):
            raise ValueError("End must be after start")
        return self


class BookwhenListTicketsConfig(_List):
    """List tickets for the selected event and verify returned event relationships."""
    operation: Literal["list_tickets"] = Field("list_tickets", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., json_schema_extra=_picker("event_id"))
    @field_validator("event_id", mode="before")
    @classmethod
    def event(cls, value): return _id(value)


class BookwhenListLocationsConfig(_List):
    """Read location metadata with documented text filters."""
    operation: Literal["list_locations"] = Field("list_locations", json_schema_extra={"ui:hidden": True})
    address_text: Optional[str] = Field(None, min_length=1, max_length=1000)
    additional_info: Optional[str] = Field(None, min_length=1, max_length=1000)


class BookwhenListAttachmentsConfig(_List):
    """Read attachment descriptions without returning or downloading file URLs."""
    operation: Literal["list_attachments"] = Field("list_attachments", json_schema_extra={"ui:hidden": True})
    title: Optional[str] = Field(None, min_length=1, max_length=1000)
    file_name: Optional[str] = Field(None, min_length=1, max_length=1000)
    file_type: Optional[str] = Field(None, min_length=1, max_length=1000)


class BookwhenListClassPassesConfig(_List):
    """Read public class-pass availability and usage metadata."""
    operation: Literal["list_class_passes"] = Field("list_class_passes", json_schema_extra={"ui:hidden": True})
    title: Optional[str] = Field(None, min_length=1, max_length=1000)
    detail: Optional[str] = Field(None, min_length=1, max_length=1000)
    usage_type: Optional[Literal["personal", "any"]] = None


class BookwhenGetEventConfig(_Input):
    """Read one event with optional safe location, ticket and attachment metadata."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., json_schema_extra=_picker("event_id"))
    include_related: StrictBool = Field(False, description="Request location, attachments, tickets and ticket class passes; no leader profiles.")
    @field_validator("event_id", mode="before")
    @classmethod
    def event(cls, value): return _id(value)


class BookwhenGetTicketConfig(_Input):
    """Read one ticket only within the selected event relationship."""
    operation: Literal["get_ticket"] = Field("get_ticket", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., json_schema_extra=_picker("event_id"))
    ticket_id: str = Field(..., json_schema_extra=_picker("ticket_id", parent="event_id"))
    include_related: StrictBool = Field(False, description="Request related event and class-pass metadata.")
    @field_validator("event_id", "ticket_id", mode="before")
    @classmethod
    def ids(cls, value): return _id(value)


class BookwhenGetLocationConfig(_Input):
    """Read one selected location without following map links."""
    operation: Literal["get_location"] = Field("get_location", json_schema_extra={"ui:hidden": True})
    location_id: str = Field(..., json_schema_extra=_picker("location_id"))
    @field_validator("location_id", mode="before")
    @classmethod
    def location(cls, value): return _id(value)


class BookwhenGetAttachmentConfig(_Input):
    """Read attachment file metadata without exposing its download URL."""
    operation: Literal["get_attachment"] = Field("get_attachment", json_schema_extra={"ui:hidden": True})
    attachment_id: str = Field(..., json_schema_extra=_picker("attachment_id"))
    @field_validator("attachment_id", mode="before")
    @classmethod
    def attachment(cls, value): return _id(value)


class BookwhenGetClassPassConfig(_Input):
    """Read one class pass without purchasing or booking it."""
    operation: Literal["get_class_pass"] = Field("get_class_pass", json_schema_extra={"ui:hidden": True})
    class_pass_id: str = Field(..., json_schema_extra=_picker("class_pass_id"))
    @field_validator("class_pass_id", mode="before")
    @classmethod
    def class_pass(cls, value): return _id(value)


BookwhenConfig = Annotated[Union[BookwhenCheckConfig, BookwhenListEventsConfig, BookwhenGetEventConfig,
    BookwhenListTicketsConfig, BookwhenGetTicketConfig, BookwhenListLocationsConfig, BookwhenGetLocationConfig,
    BookwhenListAttachmentsConfig, BookwhenGetAttachmentConfig, BookwhenListClassPassesConfig, BookwhenGetClassPassConfig], Field(discriminator="operation")]


class BookwhenFullConfig(NodeConfig[BookwhenConfig, BookwhenAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)

def _credential_id(data):
    ids = []
    selected = data.get("credential_id")
    if selected is not None and selected != "":
        ids.append(selected)
    for scope in (data, data.get("config", {})):
        mapping = scope.get("credentialIds", {}) if isinstance(scope, dict) else {}
        if not isinstance(mapping, dict):
            raise ValueError("Credential attachment is invalid")
        for family, value in mapping.items():
            if family == "credential_type":
                continue
            if value is not None and value != "":
                if family not in FAMILIES:
                    raise ValueError("Attach only a Bookwhen credential")
                ids.append(value)
    if not ids:
        return None
    if any(not isinstance(value, str) or "{{" in value for value in ids) or len(set(ids)) != 1:
        raise ValueError("Choose one saved Bookwhen credential")
    try:
        UUID(ids[0])
    except ValueError:
        raise ValueError("Credential attachment is invalid") from None
    return ids[0]


def _guard(data):
    cid = _credential_id(data)
    raw = data.get("credentials")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError("Bookwhen credential data is invalid")
    tag = raw.get("credential_type", _MISSING)
    if tag is not _MISSING and (not isinstance(tag, str) or tag not in FAMILIES):
        raise ValueError("This credential is not a Bookwhen credential")
    if cid and tag is _MISSING:
        raise ValueError("Saved Bookwhen credentials require their original family")


def _native_config_view(data):
    if not isinstance(data.get("config"), dict):
        return data
    labels = {"credentialIds", "event_id__label", "ticket_id__label", "location_id__label", "attachment_id__label", "class_pass_id__label"}
    return {**data, "config": {k: v for k, v in data["config"].items() if k not in labels}}


class _ResponseError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__("Bookwhen request was not confirmed")


class BookwhenNode(WorkflowNode):
    integration_type = "automation-bookwhen"
    connection_evidence = ConnectionEvidence(noun="Bookwhen public schedule data", operation="check_connection", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BookwhenFullConfig

    @classmethod
    def validate_config(cls, config_data):
        try:
            _guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(_native_config_view(config_data))

    @classmethod
    def parse_config(cls, config_data):
        _guard(config_data)
        return super().parse_config(_native_config_view(config_data))

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name not in FIELDS:
            raise ValueError("Unknown Bookwhen choice field")
        credential = BookwhenAPITokenCredential.model_validate(credential_data)
        offset = 0
        if page_token is not None:
            if not isinstance(page_token, str) or not re.fullmatch(r"0|[1-9][0-9]{0,6}", page_token):
                raise ValueError("Use the returned offset token")
            offset = _offset(int(page_token))
        config = {"operation": "list_" + FIELDS[field_name], "offset": offset}
        if field_name == "ticket_id":
            if search:
                raise ValueError("Ticket choices do not support text search")
            config["event_id"] = _id(context.get("event_id") if isinstance(context, dict) else None)
        elif search:
            if not isinstance(search, str) or len(search) > 1000:
                raise ValueError("Search exceeds the choice bound")
            config["address_text" if field_name == "location_id" else "title"] = search
        # Callers load the saved credential and admit lookups through staging's
        # shared hooks. API tokens do not rotate and need no refresh hook.
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="bookwhen-options", node_type=NODE_TYPE,
            node_data={"config": config, "credentials": credential.model_dump()})
        result = await node.execute({})
        if result.get("status") != "success":
            raise ValueError("Bookwhen choices were not completed; check token permissions")
        return {"options": [{"value": row["id"], "label": row.get("title") or row.get("address_text") or row.get("file_name") or row["id"]} for row in result["items"]],
            "next_page_token": str(result["next_offset"]) if result["has_more"] else None}

    async def _request(self, kind, resource_id=None, *, params):
        if not isinstance(self.config, BookwhenFullConfig) or not self.config.credentials:
            raise ValueError("Supply a Bookwhen API token credential")
        credential = self.config.credentials
        auth = "Basic " + base64.b64encode((credential.api_token + ":").encode("utf-8")).decode("ascii")
        path = "/" + kind + ("/" + quote(_id(resource_id), safe="") if resource_id is not None else "")
        query = urlencode(params, quote_via=quote, safe="~")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request("GET", BASE + path + ("?" + query if query else ""), headers={"Authorization": auth, "Accept": "application/json"})
        if response.status_code != 200: raise _ResponseError(response.status_code)
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if len(response.content) > 2_000_000 or mime not in {"application/json", "application/vnd.api+json"}: raise ValueError("Expected bounded JSON from Bookwhen")
        body = response.json()
        if not isinstance(body, dict) or "errors" in body: raise ValueError("Bookwhen response was not confirmed")
        return body

    @staticmethod
    def _record(raw, kind):
        if not isinstance(raw, dict) or raw.get("type") != KINDS[kind] or not isinstance(raw.get("attributes"), dict): raise ValueError("Resource shape or type is invalid")
        item = {"id": _id(raw.get("id")), "type": raw["type"]}
        strings = {"events": ("title", "start_at", "end_at"), "tickets": ("title", "available_from", "available_to"),
            "locations": ("address_text",), "attachments": ("title", "file_name", "file_type", "content_type", "file_size_bytes", "file_size_text"), "class_passes": ("title", "usage_type")}
        booleans = {"events": ("all_day", "waiting_list"), "tickets": ("course_ticket", "group_ticket", "available")}
        numbers = {"events": ("attendee_limit", "attendee_count", "max_tickets_per_booking"), "tickets": ("number_issued", "number_taken", "group_min", "group_max"),
            "locations": ("latitude", "longitude", "zoom"), "class_passes": ("usage_allowance", "number_available", "use_restricted_for_days")}
        attrs = raw["attributes"]
        for name in strings[kind]:
            if name not in attrs: continue
            value = attrs[name]
            if value is not None and (not isinstance(value, str) or len(value) > 10_000): raise ValueError("Metadata text is invalid")
            item[name] = value
        for name in booleans.get(kind, ()):
            if name not in attrs: continue
            value = attrs[name]
            if value is not None and type(value) is not bool: raise ValueError("Metadata flag is invalid")
            item[name] = value
        for name in numbers.get(kind, ()):
            if name not in attrs: continue
            value = attrs[name]
            integer = kind in {"events", "class_passes"} or name == "zoom"
            if value is not None and (type(value) not in ({int} if integer else {int, float}) or (type(value) is float and not math.isfinite(value))): raise ValueError("Metadata number is invalid")
            item[name] = value
        if kind == "events" and "tags" in attrs:
            tags = attrs["tags"]
            if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(tag, str) or len(tag) > 1000 for tag in tags): raise ValueError("Event tags are invalid")
            item["tags"] = tags
        if kind == "class_passes" and item.get("usage_type") not in {None, "personal", "any"}: raise ValueError("Class-pass usage type is invalid")
        relations = raw.get("relationships", {})
        if not isinstance(relations, dict): raise ValueError("Relationships are invalid")
        permitted = {"events": ("locations", "attachments", "tickets"), "tickets": ("events", "class_passes")}.get(kind, ())
        for related in permitted:
            name = "location" if related == "locations" else related
            if name not in relations: continue
            relationship = relations[name]
            if not isinstance(relationship, dict) or "data" not in relationship: raise ValueError("Relationship data is missing")
            refs = relationship["data"]
            if related == "locations":
                refs = [] if refs is None else [refs]
            if not isinstance(refs, list) or len(refs) > 1000: raise ValueError("Relationship data is invalid")
            ids = []
            for ref in refs:
                if not isinstance(ref, dict) or ref.get("type") != KINDS[related]: raise ValueError("Relationship type is invalid")
                ids.append(_id(ref.get("id")))
            if len(ids) != len(set(ids)): raise ValueError("Duplicate relationship IDs")
            item["location_id" if related == "locations" else related + "_ids"] = ids[0] if related == "locations" and ids else None if related == "locations" else ids
        return item

    @staticmethod
    def _params(config):
        result = {"page[offset]": str(config.offset)}
        if isinstance(config, BookwhenListTicketsConfig): result["event"] = config.event_id
        else:
            for name, value in config.model_dump(exclude_none=True).items():
                if name in {"operation", "offset"}: continue
                wire_name = {"from_time": "from", "to_time": "to"}.get(name, name)
                result["filter[" + wire_name + "]"] = "true" if value is True else "false" if value is False else value
        return result

    @staticmethod
    def _next(link, kind, params, offset):
        if not isinstance(link, str) or len(link) > 8192 or any(ord(c) < 32 for c in link): raise ValueError("Continuation URL is invalid")
        parts = urlsplit(link)
        if parts.fragment or parts.path != "/v2/" + kind: raise ValueError("Continuation changed the resource")
        if parts.scheme or parts.netloc:
            if parts.scheme != "https" or parts.netloc != "api.bookwhen.com": raise ValueError("Continuation changed the API origin")
        elif not link.startswith("/"): raise ValueError("Continuation is not API-relative")
        query = parse_qs(parts.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()) or set(query) - set(params): raise ValueError("Continuation changed the filter boundary")
        for name, values in query.items():
            if name != "page[offset]" and values != [str(params[name])]: raise ValueError("Continuation changed a selected filter")
        value = query.get("page[offset]", [None])[0]
        if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,6}", value): raise ValueError("Continuation lacks a valid offset")
        value = _offset(int(value))
        if value <= offset: raise ValueError("Continuation did not progress")
        return value

    async def _list(self, kind, config):
        params = self._params(config)
        body = await self._request(kind, params=params)
        raw, links = body.get("data"), body.get("links")
        if not isinstance(raw, list) or len(raw) > 200 or not isinstance(links, dict): raise ValueError("List envelope is incomplete")
        items = [self._record(row, kind) for row in raw]
        if len({item["id"] for item in items}) != len(items): raise ValueError("Duplicate resource IDs")
        if kind == "tickets" and any(config.event_id not in item.get("events_ids", []) for item in items): raise ValueError("Ticket crossed the selected event")
        next_offset = None
        if "next" in links:
            if not items: raise ValueError("An empty page cannot claim continuation")
            next_offset = self._next(links["next"], kind, params, config.offset)
        return {"items": items, "offset": config.offset, "next_offset": next_offset, "has_more": next_offset is not None, "complete": next_offset is None}

    @staticmethod
    def _included(body, raw, primary, kind):
        if "included" in body and "included" in raw: raise ValueError("Ambiguous included envelope")
        included = body.get("included", raw.get("included", []))
        if not isinstance(included, list) or len(included) > 200: raise ValueError("Included resources exceed the response bound")
        allowed = {"events": {"locations", "attachments", "tickets", "class_passes"}, "tickets": {"events", "class_passes"}}[kind]
        records = {}
        for resource in included:
            if not isinstance(resource, dict): raise ValueError("Included resource is invalid")
            related = next((name for name, tag in KINDS.items() if tag == resource.get("type")), None)
            if related not in allowed: raise ValueError("Included resource is outside the requested scope")
            item = BookwhenNode._record(resource, related)
            key = (related, item["id"])
            if key in records: raise ValueError("Duplicate included resource")
            records[key] = item
        def references(item, resource_kind):
            selected = {"events": ("locations", "attachments", "tickets"), "tickets": ("events", "class_passes")}.get(resource_kind, ())
            if kind == "events" and resource_kind == "tickets": selected = ("class_passes",)
            if kind == "tickets" and resource_kind == "events": selected = ()
            return {(related, value) for related in selected for value in ([item["location_id"]] if related == "locations" and item.get("location_id") else item.get(related + "_ids", []))}
        expected = references(primary, kind)
        for key in list(expected):
            if key in records: expected.update(references(records[key], key[0]))
        if set(records) - expected: raise ValueError("Included resource is not related to the selected record")
        return {"included": [records[key] for key in sorted(records)], "included_complete": expected <= set(records)}

    async def execute(self, inputs):
        if not isinstance(self.config, BookwhenFullConfig) or not self.config.credentials:
            raise ValueError("Supply a Bookwhen API token credential")
        credential = self.config.credentials
        config = self.config.config
        output = {"operation": config.operation, "public_schedule_data": True, "user_identity_verified": False, "ownership_verified": False}
        try:
            if config.operation == "check_connection":
                kind = credential.check_resource
                cls = {"events": BookwhenListEventsConfig, "locations": BookwhenListLocationsConfig, "attachments": BookwhenListAttachmentsConfig, "class_passes": BookwhenListClassPassesConfig}[kind]
                return {**output, "status": "success", "read_completed": True, "resource": kind, **await self._list(kind, cls())}
            if config.operation.startswith("list_"):
                return {**output, "status": "success", **await self._list(config.operation.removeprefix("list_"), config)}
            field = config.operation.removeprefix("get_") + "_id"
            resource_id = getattr(config, field)
            kind = FIELDS[field]
            params = {}
            include = getattr(config, "include_related", False)
            if include: params["include"] = "location,attachments,tickets,tickets.class_passes" if kind == "events" else "events,class_passes"
            body = await self._request(kind, resource_id, params=params)
            raw = body.get("data")
            item = self._record(raw, kind)
            if item["id"] != resource_id: raise ValueError("Resource crossed the selected ID")
            if kind == "tickets" and config.event_id not in item.get("events_ids", []): raise ValueError("Ticket crossed the selected event")
            included = self._included(body, raw, item, kind) if include else {}
            return {**output, "status": "success", "item": item, **included}
        except _ResponseError as exc:
            return {**output, "status": "error", "http_status": exc.status, "error": "Bookwhen did not confirm this read; check token permissions or resource availability"}
        except (ValueError, SSRFError, httpx.HTTPError):
            return {**output, "status": "error", "error": "Bookwhen returned an invalid or incomplete read response"}
