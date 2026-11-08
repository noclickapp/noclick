"""Native Svix application metadata and delivery-status workflows.

Only the documented regional control-plane REST API is contacted. Endpoint
URLs, payloads, responses, signing material and custom headers never become
node outputs, and delivery, recovery and consumer polling are not exposed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "svix_api_key"
MAX_BYTES = 2 * 1024 * 1024
ORIGINS = {region: f"https://api.{region}.svix.com" for region in ("us", "eu", "ca", "au", "in")}
PATTERNS = {"applications": r"app_[A-Za-z0-9]{27}", "endpoints": r"ep_[A-Za-z0-9]{27}",
    "messages": r"msg_[A-Za-z0-9]{27}", "attempts": r"atmpt_[A-Za-z0-9]{27}",
    "event_types": r"[A-Za-z0-9_.-]{1,256}"}


def _ident(value, resource):
    if not isinstance(value, str) or value in (".", "..") or not re.fullmatch(PATTERNS[resource], value):
        raise ValueError("Use the exact Svix resource ID or event-type name")
    return value


AppID = Annotated[str, BeforeValidator(lambda v: _ident(v, "applications"))]
EndpointID = Annotated[str, BeforeValidator(lambda v: _ident(v, "endpoints"))]
MessageID = Annotated[str, BeforeValidator(lambda v: _ident(v, "messages"))]
AttemptID = Annotated[str, BeforeValidator(lambda v: _ident(v, "attempts"))]
EventName = Annotated[str, BeforeValidator(lambda v: _ident(v, "event_types"))]


def _op(name, label, category, write=False):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label,
        "x-category": category, "x-is-trigger": False, "x-read-only": not write})


def _pick(name, parent=None):
    return {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True,
        **({"depends_on": parent} if parent else {})}, "x-resource-type": name}


class SvixAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Svix API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.svix.com/api-keys"})
    credential_type: Literal["svix_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    region: Literal["us", "eu", "ca", "au", "in"] = Field(..., title="Svix Environment Region",
        description="Use the region of the environment that issued this key. No self-hosted or arbitrary API origin is accepted.")
    api_key: str = Field(..., title="Environment API Key", min_length=1, max_length=8192, repr=False,
        description="Existing server-side Svix environment key. Development and production environments have separate keys; this is not an app-portal or polling-consumer token.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def header(cls, value):
        if not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Use the issued key without whitespace or header control characters")
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Config):
    page_size: int = Field(25, strict=True, ge=1, le=250, title="Page Size")
    next_page_token: str | None = Field(None, max_length=4096, title="Returned Next Page Token",
        description="Native continuation from this credential, parent, filters and page size. It wraps the returned Svix iterator; it is not a snapshot.")


class AppScope(Config):
    application_id: AppID = Field(..., title="Application", json_schema_extra=_pick("application_id"))


class MessageScope(AppScope):
    message_id: MessageID = Field(..., title="Message", json_schema_extra=_pick("message_id", "application_id"))


class TimeWindow(Config):
    after: str | None = Field(None, max_length=64, title="Created After (RFC 3339)")
    before: str | None = Field(None, max_length=64, title="Created Before (RFC 3339)")

    @field_validator("after", "before")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value):
                raise ValueError("Supply an RFC 3339 timestamp with a timezone")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.after and self.before and datetime.fromisoformat(self.after.replace("Z", "+00:00")) >= datetime.fromisoformat(self.before.replace("Z", "+00:00")):
            raise ValueError("Created After must precede Created Before")
        return self


class Change(Config):
    confirm_metadata_change: Literal[True] = Field(..., title="Confirm Environment Metadata Change",
        description="This changes the selected real Svix environment. No quiet-notification, rollback or atomic preflight guarantee is made; separate reads verify the outcome.")

    @field_validator("confirm_metadata_change", mode="before")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Confirm the metadata change explicitly")
        return value


class ListApplications(Page):
    operation: Literal["list_applications"] = _op("list_applications", "List Application Metadata", "Applications")


class GetApplication(AppScope):
    operation: Literal["get_application"] = _op("get_application", "Get Application Metadata", "Applications")


class CreateApplication(Change):
    operation: Literal["create_application"] = _op("create_application", "Create Application", "Applications", True)
    name: str = Field(..., min_length=1, max_length=500, title="Application Name")
    uid: EventName | None = Field(None, title="Optional Application UID",
        description="Optional documented unique identifier. Parent selectors use canonical app IDs, avoiding UID ambiguity.")


class UpdateApplication(AppScope, Change):
    operation: Literal["update_application"] = _op("update_application", "Rename Application", "Applications", True)
    name: str = Field(..., min_length=1, max_length=500, title="New Application Name")


class DeleteApplication(AppScope, Change):
    operation: Literal["delete_application"] = _op("delete_application", "Delete Empty Application", "Applications", True)
    expected_name: str = Field(..., min_length=1, max_length=500, title="Expected Current Name",
        description="Preflight requires this exact name and no endpoints or messages. Concurrent changes can race the final DELETE; deletion is not reversible.")


class ListEventTypes(Page):
    operation: Literal["list_event_types"] = _op("list_event_types", "List Event-Type Metadata", "Event Types")
    include_archived: bool = Field(False, strict=True, title="Include Archived Event Types")


class EventScope(Config):
    event_type_name: EventName = Field(..., title="Event Type", json_schema_extra=_pick("event_type_name"))


class GetEventType(EventScope):
    operation: Literal["get_event_type"] = _op("get_event_type", "Get Event-Type Metadata", "Event Types")


class CreateEventType(Change):
    operation: Literal["create_event_type"] = _op("create_event_type", "Create Event Type", "Event Types", True)
    name: EventName = Field(..., title="Event-Type Name")
    description: str = Field(..., max_length=4000, title="Description")
    group_name: EventName | None = Field(None, title="Group Name")
    # The documented create operation can also unarchive an existing event type.
    acknowledge_possible_unarchive: Literal[True] = Field(..., title="Acknowledge Possible Unarchive",
        description="Svix documents that creation can unarchive the same name. This does not send a message, but it can restore use by other clients.")

    @field_validator("acknowledge_possible_unarchive", mode="before")
    @classmethod
    def explicit_unarchive(cls, value):
        if value is not True:
            raise ValueError("Acknowledge the documented possible unarchive explicitly")
        return value


class UpdateEventType(EventScope, Change):
    operation: Literal["update_event_type"] = _op("update_event_type", "Update Event-Type Description", "Event Types", True)
    description: str = Field(..., max_length=4000, title="New Description")


class ArchiveEventType(EventScope, Change):
    operation: Literal["archive_event_type"] = _op("archive_event_type", "Archive Event Type", "Event Types", True)
    acknowledge_send_restriction: Literal[True] = Field(..., title="Acknowledge Future Send Restriction",
        description="DELETE archives, rather than expunges, the event type. Existing endpoint filters persist, but new messages cannot use it and new filters cannot select it.")

    @field_validator("acknowledge_send_restriction", mode="before")
    @classmethod
    def explicit_archive(cls, value):
        if value is not True:
            raise ValueError("Acknowledge the documented archive effect explicitly")
        return value


class ListEndpoints(AppScope, Page):
    operation: Literal["list_endpoints"] = _op("list_endpoints", "List Endpoint Configuration", "Endpoints")


class GetEndpoint(AppScope):
    operation: Literal["get_endpoint"] = _op("get_endpoint", "Get Endpoint Configuration", "Endpoints")
    endpoint_id: EndpointID = Field(..., title="Endpoint", json_schema_extra=_pick("endpoint_id", "application_id"))


class ListMessages(AppScope, Page, TimeWindow):
    operation: Literal["list_messages"] = _op("list_messages", "List Message Metadata", "Delivery Status")
    event_types: list[EventName] = Field(default_factory=list, max_length=20, title="Event Types",
        description="Repeated documented event_types query parameters; payload content is disabled.")

    @field_validator("event_types")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Event-type filters must be unique")
        return value


class GetMessage(MessageScope):
    operation: Literal["get_message"] = _op("get_message", "Get Message Metadata", "Delivery Status")


class ListMessageAttempts(MessageScope, Page, TimeWindow):
    operation: Literal["list_message_attempts"] = _op("list_message_attempts", "List Message Delivery Attempts", "Delivery Status")
    delivery_status: int | None = Field(None, strict=True, ge=0, le=4, title="Delivery Status",
        description="0 success, 1 pending, 2 fail, 3 sending, 4 canceled. Expanded statuses preserve cancellation.")


class ListEndpointAttempts(AppScope, Page, TimeWindow):
    operation: Literal["list_endpoint_attempts"] = _op("list_endpoint_attempts", "List Endpoint Delivery Attempts", "Delivery Status")
    endpoint_id: EndpointID = Field(..., title="Endpoint", json_schema_extra=_pick("endpoint_id", "application_id"))
    delivery_status: int | None = Field(None, strict=True, ge=0, le=4, title="Delivery Status")


class GetAttempt(MessageScope):
    operation: Literal["get_attempt"] = _op("get_attempt", "Get Delivery Attempt Status", "Delivery Status")
    attempt_id: AttemptID = Field(..., title="Attempt", json_schema_extra=_pick("attempt_id", "message_id"))


OPERATIONS = ("list_applications", "get_application", "create_application", "update_application", "delete_application",
    "list_event_types", "get_event_type", "create_event_type", "update_event_type", "archive_event_type",
    "list_endpoints", "get_endpoint", "list_messages", "get_message", "list_message_attempts", "list_endpoint_attempts", "get_attempt")
OperationConfig = Annotated[Union[ListApplications, GetApplication, CreateApplication, UpdateApplication, DeleteApplication,
    ListEventTypes, GetEventType, CreateEventType, UpdateEventType, ArchiveEventType, ListEndpoints, GetEndpoint,
    ListMessages, GetMessage, ListMessageAttempts, ListEndpointAttempts, GetAttempt], Field(discriminator="operation")]


class SvixNodeConfig(NodeConfig):
    model_config = ConfigDict(hide_input_in_errors=True)
    config: OperationConfig
    credentials: SvixAPIKeyCredential | None = None


class SvixError(ValueError):
    def __init__(self, message, status_code=None, uncertain=False):
        super().__init__(message)
        self.status_code, self.uncertain = status_code, uncertain


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number
    def constant(_):
        raise ValueError("Nonstandard JSON constant")
    return json.loads(raw, object_pairs_hook=pairs, parse_float=finite, parse_constant=constant)


class SvixSession:
    def __init__(self, credential):
        self.credential, self.base = credential, ORIGINS[credential.region] + "/api/v1"

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self.credential.api_key, "[redacted]")
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        return value

    async def request(self, method, resource, params=None, body=None, expected=(200,)):
        write, status = method != "GET", None
        try:
            content = None if body is None else json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
            if content is not None and len(content) > 65536:
                raise SvixError("Svix metadata request exceeded the body limit")
            async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, self.base + resource, params=params, content=content,
                    headers={"Authorization": "Bearer " + self.credential.api_key, "Accept": "application/json",
                        "Content-Type": "application/json", "Cache-Control": "no-cache"}) as response:
                    status = response.status_code
                    if status not in expected:
                        raise SvixError("Svix rejected or did not verify this request", status,
                            write and (200 <= status < 300 or status >= 500 or status in {408, 429}))
                    raw = bytearray()
                    async for block in response.aiter_bytes():
                        raw.extend(block)
                        if len(raw) > MAX_BYTES:
                            raise SvixError("Svix response exceeded the metadata limit", status, write)
                    if status == 204:
                        if raw:
                            raise SvixError("Svix returned an unverified deletion acknowledgement", status, write)
                        return None, status
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise SvixError("Svix returned unverified response content", status, write)
                    data = _json(raw)
                    if not isinstance(data, dict) or any(key in data for key in ("error", "detail")) or data.get("success") is False or data.get("executed") is False or data.get("status") in ("error", "halted", "not_executed"):
                        raise SvixError("Svix returned an unverified response envelope", status, write)
                    return data, status
        except SvixError:
            raise
        except Exception:
            raise SvixError("Svix transport or response could not be verified", status, write) from None

    def record(self, row, resource, status, *, expected_id=None, message_id=None, endpoint_id=None):
        try:
            if not isinstance(row, dict):
                raise ValueError
            key = "name" if resource == "event_types" else "id"
            ident = _ident(row.get(key), resource)
            if expected_id is not None and ident != expected_id:
                raise ValueError
            required = {"applications": ("name", "createdAt", "updatedAt"),
                "event_types": ("description", "createdAt", "updatedAt"),
                "endpoints": ("createdAt", "updatedAt"), "messages": ("timestamp", "eventType"),
                "attempts": ("timestamp", "statusText")}[resource]
            if any(not isinstance(row.get(name), str) for name in required):
                raise ValueError
            result = {key: ident, **{name: row[name] for name in required}}
            if resource == "applications":
                if not isinstance(row.get("metadata"), dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in row["metadata"].items()):
                    raise ValueError
                result["metadata_omitted"] = True
            if resource in ("applications", "endpoints") and row.get("uid") is not None:
                result["uid"] = _ident(row["uid"], "event_types")
            if resource == "event_types":
                if type(row.get("deprecated")) is not bool or ("archived" in row and type(row["archived"]) is not bool):
                    raise ValueError
                result.update(deprecated=row["deprecated"], schemas_omitted=True)
                if "archived" in row:
                    result["archived"] = row["archived"]
                if row.get("groupName") is not None:
                    result["groupName"] = _ident(row["groupName"], "event_types")
            if resource == "endpoints":
                if not isinstance(row.get("url"), str) or not isinstance(row.get("metadata"), dict) or not isinstance(row.get("description"), str):
                    raise ValueError
                if "disabled" in row:
                    if type(row["disabled"]) is not bool:
                        raise ValueError
                    result["disabled"] = row["disabled"]
                for name in ("channels", "eventTypes"):
                    value = row.get(name)
                    if value is not None:
                        pattern = r"[A-Za-z0-9_.:+-]{1,128}" if name == "channels" else PATTERNS["event_types"]
                        if not isinstance(value, list) or any(not isinstance(v, str) or not re.fullmatch(pattern, v) for v in value) or len(value) != len(set(value)):
                            raise ValueError
                        result[name] = value
                if row.get("throttleRate") is not None:
                    if type(row["throttleRate"]) is not int or not 0 <= row["throttleRate"] <= 65535:
                        raise ValueError
                    result["throttleRate"] = row["throttleRate"]
                result["sensitive_configuration_omitted"] = True
            if resource == "messages":
                _ident(row["eventType"], "event_types")
                result["payload_omitted"] = True
            if resource == "attempts":
                ep, msg = _ident(row.get("endpointId"), "endpoints"), _ident(row.get("msgId"), "messages")
                if (message_id is not None and msg != message_id) or (endpoint_id is not None and ep != endpoint_id):
                    raise ValueError
                code, duration, state, trigger = (row.get(n) for n in ("responseStatusCode", "responseDurationMs", "status", "triggerType"))
                if type(code) is not int or not -32768 <= code <= 32767 or type(duration) is not int or not -(2**63) <= duration < 2**63 or type(state) is not int or state not in range(5) or type(trigger) is not int or trigger not in (0, 1):
                    raise ValueError
                if row["statusText"] != ("success", "pending", "fail", "sending", "canceled")[state]:
                    raise ValueError
                result.update(endpointId=ep, msgId=msg, responseStatusCode=code, responseDurationMs=str(duration),
                    status=state, triggerType=trigger, response_content_omitted=True, destination_url_omitted=True)
            return result
        except Exception:
            raise SvixError("Svix did not verify the expected metadata record or parent", status) from None

    def scope(self, resource, path, size, filters):
        # Binding detects accidental continuation across keys/parents/filters; it is not an authorization grant.
        return hashlib.sha256(json.dumps([self.base, path, resource, size, filters,
            hashlib.sha256(self.credential.api_key.encode()).hexdigest()], sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def iterator(self, token, scope, resource):
        if token is None:
            return None
        try:
            if not isinstance(token, str) or len(token) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
                raise ValueError
            decoded = _json(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
            if not isinstance(decoded, dict) or set(decoded) != {"scope", "iterator"} or decoded["scope"] != scope:
                raise ValueError
            return _ident(decoded["iterator"], resource)
        except Exception:
            raise SvixError("Use the native continuation for this exact credential, parent and query") from None

    async def page(self, resource, path, size=25, token=None, filters=None, *, message_id=None, endpoint_id=None):
        filters = filters or []
        scope = self.scope(resource, path, size, filters)
        iterator = self.iterator(token, scope, resource)
        params = [("limit", str(size)), *filters, *(([("iterator", iterator)]) if iterator else [])]
        data, status = await self.request("GET", path, params=params)
        try:
            if not isinstance(data.get("data"), list) or len(data["data"]) > size or type(data.get("done")) is not bool or "iterator" not in data:
                raise ValueError
            following = data["iterator"]
            if following is not None:
                _ident(following, resource)
            if not data["done"] and (not data["data"] or following is None or following == iterator):
                raise ValueError
            records = [self.record(row, resource, status, message_id=message_id, endpoint_id=endpoint_id) for row in data["data"]]
            key = "name" if resource == "event_types" else "id"
            if len({row[key] for row in records}) != len(records):
                raise ValueError
            next_token = None if data["done"] else base64.urlsafe_b64encode(json.dumps({"scope": scope, "iterator": following}, separators=(",", ":")).encode()).decode().rstrip("=")
            return {"items": records, "next_page_token": next_token, "done": data["done"], "snapshot_verified": False}, status
        except SvixError:
            raise
        except Exception:
            raise SvixError("Svix returned an unverified metadata page or continuation", status) from None

    async def get(self, resource, path, ident, params=None, **parents):
        data, status = await self.request("GET", path, params=params)
        return self.record(data, resource, status, expected_id=ident, **parents), status

    async def app(self, ident):
        return await self.get("applications", "/app/" + ident, ident)

    async def message(self, app, ident):
        return await self.get("messages", f"/app/{app}/msg/{ident}", ident, params={"with_content": "false"})


class SvixNode(WorkflowNode):
    integration_type = "automation-svix"
    scope_registry = ScopeRegistry("svix", {name: ScopeRequirement(credential_types=(FAMILY,),
        note="Use the issued environment key in its matching region. These REST operations do not request OAuth scopes; app-list reachability does not establish write entitlement.") for name in OPERATIONS})
    connection_evidence = ConnectionEvidence(operation="list_applications", noun="applications", label_keys=("name", "id"), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return SvixNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type") not in (None, FAMILY):
            raise ValueError("Use current Svix environment-key credentials")
        return super().parse_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            session = SvixSession(SvixAPIKeyCredential.model_validate(credential_data))
            await session.page("applications", "/app", 5)
            return {"valid": True, "name": None}
        except SvixError as error:
            return {"valid": False if error.status_code in (401, 403) else None, "name": None,
                "error": str(error), "status_code": error.status_code}
        except Exception:
            return {"valid": False, "name": None, "error": "Use an issued Svix environment key and its exact region"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in ("application_id", "event_type_name", "endpoint_id", "message_id", "attempt_id"):
            return {"options": [], "next_page_token": None}
        context = context or {}
        app = _ident(context.get("application_id"), "applications") if field_name in ("endpoint_id", "message_id", "attempt_id") else None
        msg = _ident(context.get("message_id"), "messages") if field_name == "attempt_id" else None
        session = SvixSession(SvixAPIKeyCredential.model_validate(credential_data))
        if app:
            await session.app(app)
        if msg:
            await session.message(app, msg)
        resource, path, filters = {"application_id": ("applications", "/app", []),
            "event_type_name": ("event_types", "/event-type", [("include_archived", "false"), ("with_content", "false")]),
            "endpoint_id": ("endpoints", f"/app/{app}/endpoint", []),
            "message_id": ("messages", f"/app/{app}/msg", [("with_content", "false")]),
            "attempt_id": ("attempts", f"/app/{app}/attempt/msg/{msg}", [("with_content", "false"), ("expanded_statuses", "true")])}[field_name]
        page, _ = await session.page(resource, path, 25, page_token, filters, message_id=msg)
        options = []
        for row in page["items"]:
            value = row["name"] if resource == "event_types" else row["id"]
            label = row.get("name") or (f"{row['eventType']} · {value}" if resource == "messages" else f"{row['statusText']} · {value}" if resource == "attempts" else value)
            if not search or search.casefold() in label.casefold():
                options.append({"value": value, "label": label})
        return session.redact({"options": options, "next_page_token": page["next_page_token"]})

    async def execute(self, input_data):
        mutation, status = False, None
        try:
            if self.config.credentials is None:
                raise ValueError
            config = self.config.config
            self.scope_registry.require(config.operation)
            session = SvixSession(self.config.credentials)
            app = getattr(config, "application_id", None)
            if app:
                current_app, status = await session.app(app)
            msg = getattr(config, "message_id", None)
            if msg:
                current_message, status = await session.message(app, msg)
            if isinstance(config, (ListEndpointAttempts, GetEndpoint)):
                current_endpoint, status = await session.get("endpoints", f"/app/{app}/endpoint/{config.endpoint_id}", config.endpoint_id)
            filters = []
            if isinstance(config, TimeWindow):
                filters += [(key, getattr(config, key)) for key in ("after", "before") if getattr(config, key) is not None]
            if isinstance(config, (ListMessageAttempts, ListEndpointAttempts)):
                filters += [("with_content", "false"), ("expanded_statuses", "true")]
                if config.delivery_status is not None:
                    filters.append(("status", str(config.delivery_status)))
            if isinstance(config, ListMessages):
                filters += [("with_content", "false"), *[("event_types", name) for name in config.event_types]]
            if isinstance(config, ListEventTypes):
                filters += [("include_archived", str(config.include_archived).lower()), ("with_content", "false")]
            if isinstance(config, (ListApplications, ListEventTypes, ListEndpoints, ListMessages, ListMessageAttempts, ListEndpointAttempts)):
                resource, path = {"list_applications": ("applications", "/app"), "list_event_types": ("event_types", "/event-type"),
                    "list_endpoints": ("endpoints", f"/app/{app}/endpoint"), "list_messages": ("messages", f"/app/{app}/msg"),
                    "list_message_attempts": ("attempts", f"/app/{app}/attempt/msg/{msg}"),
                    "list_endpoint_attempts": ("attempts", f"/app/{app}/attempt/endpoint/{getattr(config, 'endpoint_id', None)}")}[config.operation]
                output, status = await session.page(resource, path, config.page_size, config.next_page_token, filters,
                    message_id=msg, endpoint_id=getattr(config, "endpoint_id", None))
            elif isinstance(config, GetApplication):
                output = {"record": current_app}
            elif isinstance(config, GetEndpoint):
                output = {"record": current_endpoint}
            elif isinstance(config, GetMessage):
                output = {"record": current_message}
            elif isinstance(config, GetAttempt):
                record, status = await session.get("attempts", f"/app/{app}/msg/{msg}/attempt/{config.attempt_id}", config.attempt_id,
                    params={"expanded_statuses": "true"}, message_id=msg)
                output = {"record": record}
            elif isinstance(config, GetEventType):
                record, status = await session.get("event_types", "/event-type/" + config.event_type_name, config.event_type_name)
                output = {"record": record}
            else:
                resource, method, path, body, ident = "applications", "POST", "/app", None, None
                if isinstance(config, CreateApplication):
                    body = {"name": config.name, **({"uid": config.uid} if config.uid is not None else {})}
                elif isinstance(config, UpdateApplication):
                    method, path, body, ident = "PATCH", "/app/" + app, {"name": config.name}, app
                elif isinstance(config, DeleteApplication):
                    if current_app["name"] != config.expected_name:
                        raise SvixError("Current application name does not match the deletion confirmation", status)
                    for child, suffix in (("endpoints", "endpoint"), ("messages", "msg")):
                        page, status = await session.page(child, f"/app/{app}/{suffix}", 1,
                            filters=[("with_content", "false")] if child == "messages" else [])
                        if page["items"] or not page["done"]:
                            raise SvixError("Only an application with no endpoints or messages can be deleted", status)
                    method, path, ident = "DELETE", "/app/" + app, app
                else:
                    resource = "event_types"
                    if isinstance(config, CreateEventType):
                        path, ident = "/event-type", config.name
                        body = {"name": config.name, "description": config.description,
                            **({"groupName": config.group_name} if config.group_name is not None else {})}
                    else:
                        ident, path = config.event_type_name, "/event-type/" + config.event_type_name
                        await session.get("event_types", path, ident)
                        method = "DELETE" if isinstance(config, ArchiveEventType) else "PATCH"
                        body = None if method == "DELETE" else {"description": config.description}
                mutation = True
                data, status = await session.request(method, path, body=body,
                    expected=(204,) if method == "DELETE" else (200, 201) if isinstance(config, CreateApplication) else (201,) if method == "POST" else (200,))
                if method == "DELETE":
                    output = {"archived_event_type": ident} if resource == "event_types" else {"deleted_application_id": ident}
                else:
                    record = session.record(data, resource, status, expected_id=ident)
                    for key, value in body.items():
                        if record.get(key) != value:
                            raise SvixError("Svix did not acknowledge the expected metadata change", status, True)
                    output = {"record": record}
                output.update(provider_acknowledged=True, readback_verified=False, preflight_atomic=False,
                    notification_behavior_verified=False, status_code=status)
            return session.redact({"status": "success", **output})
        except SvixError as error:
            return {"status": "error", "error": str(error), "status_code": error.status_code,
                "uncertain_outcome": error.uncertain or mutation and error.status_code in (200, 201, 204)}
        except Exception:
            return {"status": "error", "error": "Svix configuration or response could not be verified",
                "status_code": status, "uncertain_outcome": mutation}
