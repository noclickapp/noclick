"""Native SignalWire project, communication logs, numbers and Fabric inventory.

Project Basic credentials use a fixed validated Space origin. Sending SMS and
redacting message bodies have explicit effects; no SDK, call or model wrapper is used.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import SSRFError, allow_private_hosts, guarded_async_client

TYPE = "signalwire_project_token"
TYPES = (TYPE,)
MAX_BYTES = 2 * 1024 * 1024
CURRENT_ORGANIZATION = object()


def space_url(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f]", value):
        raise ValueError("Use your HTTPS SignalWire Space origin")
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.username or parts.password or parts.port is not None or parts.query or parts.fragment or parts.path not in ("", "/") or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.signalwire\.com", parts.netloc):
            raise ValueError()
        return "https://" + parts.netloc
    except ValueError:
        raise ValueError("Use https://<your-space>.signalwire.com without a port, API path or URL credentials") from None


def uuid_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ValueError("Use the UUID returned by SignalWire")
    return value.lower()


def record_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Use a native SignalWire log ID, without a URL or path")
    return value


def text_value(value):
    if not isinstance(value, str) or not value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Use nonempty text without control characters")
    return value.strip()


def iso_date(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("Use a valid YYYY-MM-DD date") from None
    return value


SpaceURL = Annotated[str, BeforeValidator(space_url)]
UUID = Annotated[str, BeforeValidator(uuid_value)]
RecordID = Annotated[str, BeforeValidator(record_id)]
Text = Annotated[str, BeforeValidator(text_value)]
ISODate = Annotated[str, BeforeValidator(iso_date)]


class SignalWireProjectTokenCredential(BaseModel):
    credential_type: Literal["signalwire_project_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    space_url: SpaceURL = Field(..., title="SignalWire Space URL", description="Your exact HTTPS <space>.signalwire.com origin. Custom domains, API routes and private hosts are unsupported.")
    project_id: UUID = Field(..., title="Project ID", description="The UUID of the project that issued this API token; not a Compatibility SID or personal user ID.")
    api_token: str = Field(..., min_length=1, max_length=6000, repr=False, title="Project API Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="SignalWire Project Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://signalwire.com/docs/platform/your-signalwire-api-space",
        "x-credential-instructions": "Supply a Project ID and its API token. Management is needed for the connection project probe; Messaging, Voice, Numbers or the documented Fabric scopes are required for their operations. Actual enabled token scopes remain provider authoritative. Personal pat_ and subscriber/guest Bearer tokens are separate unsupported families. Paste the opaque token only, including legacy PT tokens; no OAuth, minting, rotation or SDK default credential chain is performed.",
    })

    @model_validator(mode="before")
    @classmethod
    def manual_family(cls, value):
        return {"credential_type": TYPE, **value} if isinstance(value, dict) else value

    @field_validator("api_token", mode="before")
    @classmethod
    def valid_token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Supply the opaque Project API token only")
        value = clean_secret(value)
        if not value or value.startswith("pat_") or re.search(r"[\x00-\x20\x7f:]", value):
            raise ValueError("Supply a Project API token without a header prefix or whitespace")
        return value


def credential_value(raw, *, manual=False):
    if isinstance(raw, SignalWireProjectTokenCredential):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE and not (manual and not raw.get("credential_type")):
        raise ValueError("Connect a typed SignalWire Project API token")
    try:
        return SignalWireProjectTokenCredential.model_validate(raw)
    except ValueError:
        raise ValueError("Supply a valid SignalWire Space, Project UUID and Project API token") from None


def picker(field):
    return {"x-resource-type": "signalwire_" + field, "x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True, "custom_placeholder": "Paste a native SignalWire ID"}}


def operation_field(value, name, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": name, "x-category": category})


def operation_meta(name, category, effect=None):
    extra = {"x-display-name": name, "x-category": category, "x-is-trigger": False}
    if effect:
        extra["x-operation-effect"] = effect
    return ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra=extra)


class Page(BaseModel):
    page_size: int = Field(50, strict=True, ge=1, le=100, title="Page Size", description="A bounded subset of the provider's 1–1000 range. One page per invocation.")
    page_token: str | None = Field(None, max_length=5000, title="Next Page Token", description="Use the continuation returned by this node; not a URL or a raw provider token.")


class LogPage(Page):
    created_on: ISODate | None = Field(None, title="Created On")
    created_after: ISODate | None = Field(None, title="Created After")
    created_before: ISODate | None = Field(None, title="Created Before")

    @model_validator(mode="after")
    def date_range(self):
        if self.created_on and (self.created_after or self.created_before) or self.created_after and self.created_before and self.created_after >= self.created_before:
            raise ValueError("Use one exact date or an increasing date range")
        return self


class GetProject(BaseModel):
    operation: Literal["get_project"] = operation_field("get_project", "Get connected project", "Project")
    model_config = operation_meta("Get connected project", "Project")


class ListMessages(LogPage):
    operation: Literal["list_message_logs"] = operation_field("list_message_logs", "List message logs", "Messaging")
    model_config = operation_meta("List message logs", "Messaging")


class GetMessage(BaseModel):
    operation: Literal["get_message_log"] = operation_field("get_message_log", "Get message log", "Messaging")
    message_id: RecordID = Field(..., title="Message Log ID", json_schema_extra=picker("message_id"))
    model_config = operation_meta("Get message log", "Messaging")


class ListCalls(LogPage):
    operation: Literal["list_call_logs"] = operation_field("list_call_logs", "List call logs", "Voice")
    model_config = operation_meta("List call logs", "Voice")


class GetCall(BaseModel):
    operation: Literal["get_call_log"] = operation_field("get_call_log", "Get call log", "Voice")
    call_id: RecordID = Field(..., title="Voice Log ID", json_schema_extra=picker("call_id"))
    model_config = operation_meta("Get call log", "Voice")


class ListNumbers(Page):
    operation: Literal["list_phone_numbers"] = operation_field("list_phone_numbers", "List owned phone numbers", "Phone numbers")
    model_config = operation_meta("List owned phone numbers", "Phone numbers")


class GetNumber(BaseModel):
    operation: Literal["get_phone_number"] = operation_field("get_phone_number", "Get owned phone number", "Phone numbers")
    phone_number_id: UUID = Field(..., title="Phone Number ID", json_schema_extra=picker("phone_number_id"))
    model_config = operation_meta("Get owned phone number", "Phone numbers")


class ListResources(Page):
    operation: Literal["list_resources"] = operation_field("list_resources", "List Fabric resource metadata", "Resources")
    model_config = operation_meta("List Fabric resource metadata", "Resources")


class GetResource(BaseModel):
    operation: Literal["get_resource"] = operation_field("get_resource", "Get Fabric resource metadata", "Resources")
    resource_id: UUID = Field(..., title="Resource ID", json_schema_extra=picker("resource_id"))
    model_config = operation_meta("Get Fabric resource metadata", "Resources")


class SendSMS(BaseModel):
    operation: Literal["send_sms"] = operation_field("send_sms", "Send SMS", "Messaging")
    from_number: str = Field(..., pattern=r"^\+[1-9][0-9]{4,16}$", title="From Number", description="An existing SMS-capable number owned by this project; verified caller IDs are unsupported.")
    to_number: str = Field(..., pattern=r"^\+[1-9][0-9]{4,16}$", title="Recipient Number", description="Explicit E.164 recipient. Provider consent, registration, geographic and account restrictions still apply.")
    message: str = Field(..., min_length=1, max_length=1600, title="Message", json_schema_extra={"ui:widget": "textarea"})
    confirm_send: Literal[True] = Field(..., title="Confirm Sending This SMS")
    model_config = operation_meta("Send SMS", "Messaging", "Queues a real outbound SMS and may incur charges. 201 means queued, not delivered. No retry, receipt polling, WhatsApp, MMS, callback or consent provisioning.")

    @field_validator("confirm_send", mode="before")
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError("Explicitly confirm sending this SMS")
        return value

    @field_validator("message")
    @classmethod
    def valid_message(cls, value):
        if not value.strip() or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value) or len(value.encode()) > 6400:
            raise ValueError("Use bounded SMS text without binary control characters")
        return value


class RedactMessage(BaseModel):
    operation: Literal["redact_message"] = operation_field("redact_message", "Redact message body", "Messaging")
    message_id: UUID = Field(..., title="Message Segment ID", description="The segment UUID returned by sending or message logs; not a Compatibility SID.", json_schema_extra=picker("message_id"))
    confirm_redact: Literal[True] = Field(..., title="Confirm Irreversible Body Redaction")
    model_config = operation_meta("Redact message body", "Messaging", "Irreversibly clears only the body of a terminal message. queued/initiated messages are ineligible. Metadata/logs remain; no message deletion, arbitrary update or automatic retry.")

    @field_validator("confirm_redact", mode="before")
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError("Explicitly confirm irreversible message redaction")
        return value


class RenameNumber(GetNumber):
    operation: Literal["rename_phone_number"] = operation_field("rename_phone_number", "Rename owned phone number", "Phone numbers")
    name: Text = Field(..., max_length=128, title="Display Name", description="Changes the project's number label only, not caller ID/CNAM, routing, ownership or carrier settings.")
    model_config = operation_meta("Rename owned phone number", "Phone numbers", "Updates only the existing number's display name. Does not purchase, release, port, reroute or change caller ID/E911 settings.")


OPERATIONS = (GetProject, ListMessages, GetMessage, ListCalls, GetCall, ListNumbers, GetNumber, ListResources, GetResource, SendSMS, RedactMessage, RenameNumber)
SignalWireOperation = Annotated[Union[GetProject, ListMessages, GetMessage, ListCalls, GetCall, ListNumbers, GetNumber, ListResources, GetResource, SendSMS, RedactMessage, RenameNumber], Discriminator("operation")]


class SignalWireNodeConfig(NodeConfig[SignalWireOperation, SignalWireProjectTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


SIGNALWIRE_SCOPES = ScopeRegistry("signalwire", {cls.model_fields["operation"].default: ScopeRequirement((), credential_types=TYPES, note="Actual enabled Project API scopes are checked by SignalWire, not inferred from a supplied token.") for cls in OPERATIONS})
PATHS = {"messages": "/api/messaging/logs", "calls": "/api/voice/logs", "numbers": "/api/relay/rest/phone_numbers", "resources": "/api/fabric/resources"}
LISTS = {"list_message_logs": "messages", "list_call_logs": "calls", "list_phone_numbers": "numbers", "list_resources": "resources"}
GETS = {"get_message_log": ("messages", "message_id"), "get_call_log": ("calls", "call_id"), "get_phone_number": ("numbers", "phone_number_id"), "get_resource": ("resources", "resource_id")}
FIELDS = {
    "project": ("name", "parent_project_id", "subproject", "region_preference", "created_at", "updated_at"),
    "messages": ("status", "direction", "kind", "source", "type", "number_of_segments", "created_at", "error_code"),
    "calls": ("status", "direction", "source", "type", "duration", "duration_ms", "created_at", "discarded_at", "parent_id"),
    "numbers": ("number", "name", "capabilities", "number_type", "country_code", "created_at", "updated_at"),
    "resources": ("display_name", "type", "created_at", "updated_at"),
}


def finite_json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def decimal(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
        return number
    try:
        return json.loads(content, object_pairs_hook=pairs, parse_float=decimal, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("SignalWire returned malformed or nonfinite JSON") from None


class SignalWireAPIError(ValueError):
    def __init__(self, status, retry_after=None):
        self.http_status, self.retry_after = status, retry_after
        super().__init__(f"SignalWire HTTP {status}: request was not confirmed" + (f"; retry after {retry_after} seconds" if retry_after is not None else ""))


def auth_header(credential):
    return "Basic " + base64.b64encode((credential.project_id + ":" + credential.api_token).encode()).decode()


async def fetch(credential, operation, method, path, *, params=None, body=None):
    credential = credential_value(credential)
    SIGNALWIRE_SCOPES.enforce_credential_type(operation, credential.credential_type)
    allowed_read = method == "GET" and body is None and (path == "/api/projects/" + credential.project_id or any(path == route or re.fullmatch(re.escape(route) + r"/[A-Za-z0-9_-]{1,128}", path) for route in PATHS.values()))
    allowed_write = operation == "send_sms" and method == "POST" and path == "/api/messaging/messages" or operation == "redact_message" and method == "PATCH" and re.fullmatch(r"/api/messaging/messages/[0-9a-f-]{36}", path) or operation == "rename_phone_number" and method == "PUT" and re.fullmatch(r"/api/relay/rest/phone_numbers/[0-9a-f-]{36}", path)
    if not (allowed_read or allowed_write) or allow_private_hosts():
        raise ValueError("Use native public SignalWire operations; private overrides and arbitrary routes are unsupported")
    expected = 201 if operation == "send_sms" and method == "POST" else 200
    try:
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, credential.space_url + path, headers={"Authorization": auth_header(credential), "Accept": "application/json"}, params=params, **({"json": body} if body is not None else {})) as response:
                if response.status_code != expected:
                    retry = response.headers.get("retry-after", "")
                    raise SignalWireAPIError(response.status_code, int(retry) if re.fullmatch(r"[0-9]{1,6}", retry) else None)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("SignalWire response exceeds 2 MiB; no partial result accepted")
                    content.extend(chunk)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("SignalWire returned a non-JSON success response")
                raw = finite_json(bytes(content))
                if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors")):
                    raise ValueError("SignalWire did not return a native success envelope")
                return raw
    except SSRFError:
        raise ValueError("SignalWire destination is not publicly reachable") from None
    except httpx.RequestError:
        raise ValueError("SignalWire request could not be completed; no automatic retry") from None


def safe_text(value, credential):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2000 or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("SignalWire returned invalid metadata text")
    for secret in (credential.api_token, auth_header(credential).split(" ", 1)[1]):
        value = value.replace(secret, "[redacted]").replace(quote(secret, safe=""), "[redacted]")
    return re.sub(r"(?i)(?:api_token|authorization|password|access_token)\s*[=:]\s*[^\s&]+", "[redacted]", value)


def project(raw, credential, kind, expected_id=None):
    if not isinstance(raw, dict):
        raise ValueError("SignalWire returned invalid metadata")
    identity = uuid_value(raw.get("id")) if kind in {"project", "numbers", "resources"} else record_id(raw.get("id"))
    if expected_id is not None and identity != expected_id or raw.get("project_id") is not None and uuid_value(raw["project_id"]) != credential.project_id:
        raise ValueError("SignalWire returned a different resource or project")
    if kind == "resources" and uuid_value(raw.get("project_id")) != credential.project_id:
        raise ValueError("SignalWire resource is outside the connected project")
    data = {"id": identity}
    for field in FIELDS[kind]:
        if field not in raw:
            continue
        value = raw[field]
        if field in {"duration", "duration_ms", "number_of_segments"}:
            if value is not None and (type(value) is not int or not 0 <= value <= 9223372036854775807):
                raise ValueError("SignalWire returned an invalid metadata count")
        elif field == "subproject":
            if type(value) is not bool:
                raise ValueError("SignalWire returned an invalid project flag")
        elif field == "capabilities":
            if not isinstance(value, list) or len(value) > 4 or any(item not in {"voice", "sms", "mms", "fax"} for item in value):
                raise ValueError("SignalWire returned invalid number capabilities")
            value = list(value)
        else:
            value = safe_text(value, credential)
        data[field] = value
    return data


def page_binding(credential, kind, config, search=None):
    fields = config.model_dump(exclude={"operation", "page_token"}, exclude_none=True)
    return hashlib.sha256(json.dumps([credential.model_dump(), kind, fields, search], sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32] + ":"


def read_continuation(token, prefix):
    if token is None:
        return 0, None
    try:
        if not isinstance(token, str) or not token.startswith(prefix) or len(token) > 5000:
            raise ValueError()
        encoded = token[len(prefix):]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
            raise ValueError()
        value = finite_json(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if not isinstance(value, dict) or set(value) != {"page", "token"} or type(value["page"]) is not int or not 1 <= value["page"] <= 1000000 or not isinstance(value["token"], str) or not 1 <= len(value["token"]) <= 2048 or re.search(r"[\x00-\x20\x7f]", value["token"]):
            raise ValueError()
        return value["page"], value["token"]
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("Continuation changed credential, Space, project, collection, date, size or search") from None


def next_continuation(raw, credential, path, params, prefix):
    links = raw.get("links")
    if not isinstance(links, dict):
        raise ValueError("SignalWire omitted native pagination links")
    href = links.get("next")
    if href in (None, ""):
        return None
    try:
        if not isinstance(href, str) or len(href) > 4096 or re.search(r"[\x00-\x20\x7f]", href):
            raise ValueError()
        parts = urlsplit(href)
        if parts.fragment or parts.username or parts.password or parts.port is not None or parts.path != path or parts.scheme and (parts.scheme != "https" or parts.netloc != urlsplit(credential.space_url).netloc) or not parts.scheme and parts.netloc:
            raise ValueError()
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        if len(query) != len(pairs) or set(query) - set(params) - {"page_token"} or query.get("page_number") != str(params["page_number"] + 1) or query.get("page_size") != str(params["page_size"]):
            raise ValueError()
        for key, value in params.items():
            if key not in {"page_number", "page_size", "page_token"} and key in query and query[key] != str(value):
                raise ValueError()
        token = query.get("page_token")
        if not token or len(token) > 2048 or re.search(r"[\x00-\x20\x7f]", token) or params["page_number"] >= 1000000:
            raise ValueError()
        encoded = base64.urlsafe_b64encode(json.dumps({"page": params["page_number"] + 1, "token": token}, separators=(",", ":")).encode()).decode().rstrip("=")
        return prefix + encoded
    except ValueError:
        raise ValueError("SignalWire continuation changed Space, resource, paging or filters; no URL followed") from None


async def list_records(credential, config, kind, *, search=None):
    prefix = page_binding(credential, kind, config, search)
    page, token = read_continuation(config.page_token, prefix)
    params = {"page_number": page, "page_size": config.page_size}
    if token is not None:
        params["page_token"] = token
    if isinstance(config, LogPage):
        params["include_deleted"] = "false"
        for key in ("created_on", "created_after", "created_before"):
            if getattr(config, key) is not None:
                params[key] = getattr(config, key)
    raw = await fetch(credential, config.operation, "GET", PATHS[kind], params=params)
    items = raw.get("data")
    if not isinstance(items, list) or len(items) > config.page_size:
        raise ValueError("SignalWire returned an invalid or oversized page")
    data = [project(item, credential, kind) for item in items]
    if len({item["id"] for item in data}) != len(data):
        raise ValueError("SignalWire returned duplicate resource IDs")
    continuation = next_continuation(raw, credential, PATHS[kind], params, prefix)
    if continuation and not items:
        raise ValueError("SignalWire returned an empty continuing page")
    return {"items": data, "page_size": config.page_size, "next_page_token": continuation}


async def request_operation(credential_data, config):
    credential = credential_value(credential_data)
    operation = config.operation
    if operation == "get_project":
        raw = await fetch(credential, operation, "GET", "/api/projects/" + credential.project_id)
        return {"data": project(raw, credential, "project", credential.project_id)}
    if operation in LISTS:
        return {"data": await list_records(credential, config, LISTS[operation])}
    if operation in GETS:
        kind, field = GETS[operation]
        identity = getattr(config, field)
        raw = await fetch(credential, operation, "GET", PATHS[kind] + "/" + identity)
        return {"data": project(raw, credential, kind, identity)}
    if isinstance(config, SendSMS):
        if credential.api_token in config.message or auth_header(credential).split(" ", 1)[1] in config.message:
            raise ValueError("Do not place credential bytes in SMS content")
        raw = await fetch(credential, operation, "POST", "/api/messaging/messages", body={"from": config.from_number, "to": config.to_number, "body": config.message})
        if uuid_value(raw.get("project_id")) != credential.project_id or raw.get("from") != config.from_number or raw.get("to") != config.to_number or raw.get("kind") != "sms":
            raise ValueError("SignalWire did not confirm the requested project, sender, recipient and SMS channel; no retry")
        data = project(raw, credential, "messages")
        uuid_value(data["id"])
        return {"data": {**data, "queued_request_accepted": True, "delivery_verified": False, "http_status": 201}}
    if isinstance(config, RedactMessage):
        raw = await fetch(credential, operation, "GET", PATHS["messages"] + "/" + config.message_id)
        before = project(raw, credential, "messages", config.message_id)
        if before.get("status") not in {"delivered", "undelivered", "failed", "sent", "received"}:
            raise ValueError("Only terminal messages can be redacted")
        raw = await fetch(credential, operation, "PATCH", "/api/messaging/messages/" + config.message_id, body={"body": ""})
        data = project(raw, credential, "messages", config.message_id)
        if uuid_value(raw.get("project_id")) != credential.project_id or raw.get("body") != "":
            raise ValueError("SignalWire did not confirm cleared message body; no retry")
        return {"data": {**data, "body_redaction_confirmed": True, "irreversible": True}}
    if isinstance(config, RenameNumber):
        if credential.api_token in config.name:
            raise ValueError("Do not place credential bytes in number metadata")
        project(await fetch(credential, operation, "GET", PATHS["numbers"] + "/" + config.phone_number_id), credential, "numbers", config.phone_number_id)
        raw = await fetch(credential, operation, "PUT", PATHS["numbers"] + "/" + config.phone_number_id, body={"name": config.name})
        data = project(raw, credential, "numbers", config.phone_number_id)
        if raw.get("name") != config.name:
            raise ValueError("SignalWire did not confirm the number label; no retry")
        readback = project(await fetch(credential, operation, "GET", PATHS["numbers"] + "/" + config.phone_number_id), credential, "numbers", config.phone_number_id)
        if readback.get("name") != config.name:
            raise ValueError("SignalWire number label readback is unconfirmed; no retry")
        return {"data": readback, "readback_verified": True}
    raise ValueError("Use a native SignalWire operation")


class SignalWireNode(WorkflowNode):
    integration_type = "automation-signalwire"
    scope_registry = SIGNALWIRE_SCOPES
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="get_project", noun="SignalWire project metadata", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return SignalWireNodeConfig

    @classmethod
    def _require_raw(cls, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("config"), dict):
            raise ValueError("Use native SignalWire configuration")
        credential_value(raw.get("credentials"))
        controls = {"url", "base_url", "endpoint", "headers", "method", "body", "params", "api_token", "project_id", "space_url", "webhook", "signature", "media", "status_callback", "custom_variables", "purchase", "call_commands", "model"}
        if controls.intersection(raw) or controls.intersection(raw["config"]):
            raise ValueError("Use typed SignalWire fields without arbitrary requests or callbacks")

    @classmethod
    def parse_config(cls, config_data):
        cls._require_raw(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._require_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Use native SignalWire fields and a typed Project credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._load_current_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id
        )

    @classmethod
    async def _load_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=CURRENT_ORGANIZATION):
        if credential_id:
            if not user_id:
                raise ValueError("Stored SignalWire credential requires an authorized caller")
            from utils.database_pool import get_native_pool
            from wss.handlers.workflow_handler import get_user_org_context
            from utils.credentials import resolve_credential_with_owner_fallback
            pool = pool if pool is not None else get_native_pool()
            if organization_id is CURRENT_ORGANIZATION:
                async with pool.acquire() as conn:
                    organization_id = await get_user_org_context(conn, user_id)
            credential_data = await resolve_credential_with_owner_fallback(
                credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id
            )
            if not credential_data:
                raise ValueError("SignalWire credential unavailable, revoked or access denied")
        return credential_value(credential_data, manual=not credential_id).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try:
            credential_value(credential_data)
        except ValueError:
            return {"valid": False, "error": "Connect a typed SignalWire Project credential"}
        # Staging's legacy hook has no saved-row context. The declared evidence
        # probe verifies the provider through this node's protected operation.
        return {"valid": None, "error": "Use the connected project read to verify SignalWire access"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        collections = {"message_id": (ListMessages, "messages"), "call_id": (ListCalls, "calls"), "phone_number_id": (ListNumbers, "numbers"), "resource_id": (ListResources, "resources")}
        if field_name not in collections:
            return {"options": [], "next_page_token": None}
        credential = credential_value(credential_data, manual=True)
        if search is not None and (not isinstance(search, str) or len(search) > 200 or re.search(r"[\x00-\x1f\x7f]", search)):
            raise ValueError("Use bounded picker search text")
        if context is not None and not isinstance(context, dict):
            raise ValueError("Use native SignalWire picker context")
        context = context or {}
        if any(key in context for key in ("space_url", "project_id", "credential_type", "credentials", "api_token", "_space_url", "_project_id", "_credential_type")):
            raise ValueError("Use the saved SignalWire project scope")
        model, kind = collections[field_name]
        filters = {key: iso_date(context[key]) for key in ("created_on", "created_after", "created_before") if context.get(key) is not None} if kind in {"messages", "calls"} else {}
        config = model(page_size=100, page_token=page_token, **filters)
        query = normalize_search(search)
        data = await list_records(credential, config, kind, search=query)
        options = [{"value": item["id"], "label": item.get("name") or item.get("display_name") or item.get("status") or item["id"], "metadata": {"id": item["id"]}} for item in data["items"]]
        return {"options": filter_options_by_search(options, query), "next_page_token": data["next_page_token"]}

    async def execute(self, inputs: dict[str, Any]):
        if self.node_data:
            self._require_raw(self.node_data)
        if not isinstance(self.config, SignalWireNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a typed SignalWire Project credential")
        credential = await self._load_current_credential(self.config.credentials.model_dump(), pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id, credential_id=(self.node_data or {}).get("credential_id"), workflow_id=self.workflow_id, organization_id=self.organization_id)
        return {"status": "success", "action": self.config.config.operation, **await request_operation(credential, self.config.config)}
