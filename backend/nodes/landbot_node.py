"""Native Landbot Platform metadata and customer-field management.

Uses workspace agent tokens, never APIchat tokens or conversation endpoints.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import SSRFError, allow_private_hosts, guarded_async_client

BASE = "https://api.landbot.io/v1"
TYPE = "landbot_agent_token"
MAX_BYTES = 2 * 1024 * 1024
MAX_OFFSET = 2147483647
MAX_FIELD_BYTES = 16 * 1024
CURRENT_ORGANIZATION = object()
FIELD_TYPES = {"string", "integer", "float", "boolean", "date", "datetime", "object"}


def resource_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        raise ValueError("Use a positive numeric Landbot resource ID")
    return str(value)


def field_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9_]{1,128}", value):
        raise ValueError("Use a custom field name with lowercase letters, numbers and underscores")
    return value


ResourceID = Annotated[str, BeforeValidator(resource_id)]
FieldName = Annotated[str, BeforeValidator(field_name)]
FieldType = Literal["string", "integer", "float", "boolean", "date", "datetime", "object"]


class LandbotAgentTokenCredential(BaseModel):
    credential_type: Literal["landbot_agent_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    agent_token: str = Field(..., min_length=1, max_length=6000, repr=False, title="Platform Agent Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Landbot Platform Agent Token", hide_input_in_errors=True, extra="ignore", json_schema_extra={
        "x-credential-url": "https://app.landbot.io/gui/settings/account",
        "x-credential-instructions": "Supply your Landbot Platform agent token from Account settings. This token grants workspace API access. Paste the token value only, without Token or Bearer. APIchat channel/customer tokens are different and unsupported. Current workspace access and permissions are confirmed only by the provider; no OAuth onboarding or current-user identity is inferred.",
    })

    @model_validator(mode="before")
    @classmethod
    def shaped_family(cls, value):
        return {"credential_type": TYPE, **value} if isinstance(value, dict) else value

    @field_validator("agent_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Use an agent token string")
        value = clean_secret(value)
        if not value or re.search(r"[\x00-\x20\x7f]", value):
            raise ValueError("Paste the agent token value only, without whitespace or a header prefix")
        return value


def credential_value(raw, *, manual=False):
    if isinstance(raw, LandbotAgentTokenCredential):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        raise ValueError("Connect a typed Landbot Platform agent token")
    data = dict(raw)
    if manual and not data.get("credential_type") and data.get("agent_token"):
        data["credential_type"] = TYPE
    if data.get("credential_type") != TYPE:
        raise ValueError("Current credential family is not a Landbot Platform agent token")
    try:
        return LandbotAgentTokenCredential.model_validate(data)
    except ValueError:
        raise ValueError("Use a valid typed Landbot Platform agent token") from None


def picker(field, parent=None):
    extra = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        extra["depends_on"] = parent
    return {"x-dynamic-options": extra}


def operation_meta(name, category, effect=None):
    extra = {"x-display-name": name, "x-category": category, "x-is-trigger": False}
    if effect:
        extra["x-operation-effect"] = effect
    return ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra=extra)


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Operation):
    limit: int = Field(20, strict=True, ge=0, le=100, title="Records per page", description="Zero requests only the total count.")
    offset: int = Field(0, strict=True, ge=0, le=MAX_OFFSET, title="Records to skip")


class ListChannels(Page):
    operation: Literal["list_channels"] = Field("list_channels", json_schema_extra={"const": "list_channels", "ui:hidden": True})
    active: bool | None = Field(None, title="Active channels only")
    channel_type: Literal["facebook", "apichat", "landbot", "whatsapi"] | None = Field(None, title="Channel type filter", description="Documented list filter. Webchat can appear in returned records but is not a documented type filter.")
    model_config = operation_meta("List workspace channels", "Channels")


class ChannelOperation(Operation):
    channel_id: ResourceID = Field(..., title="Channel", json_schema_extra=picker("channel_id"))


class GetChannel(ChannelOperation):
    operation: Literal["get_channel"] = Field("get_channel", json_schema_extra={"const": "get_channel", "ui:hidden": True})
    model_config = operation_meta("Get channel metadata", "Channels")


class ListCustomers(Page):
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"const": "list_customers", "ui:hidden": True})
    channel_id: ResourceID = Field(..., title="Channel", json_schema_extra=picker("channel_id"))
    archived: bool | None = Field(None, title="Archived status filter")
    model_config = operation_meta("List channel customer metadata", "Customers")


class CustomerOperation(ChannelOperation):
    customer_id: ResourceID = Field(..., title="Customer", json_schema_extra=picker("customer_id", "channel_id"))


class GetCustomer(CustomerOperation):
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"const": "get_customer", "ui:hidden": True})
    model_config = operation_meta("Get customer metadata", "Customers")


class ArchiveCustomer(CustomerOperation):
    operation: Literal["archive_customer"] = Field("archive_customer", json_schema_extra={"const": "archive_customer", "ui:hidden": True})
    model_config = operation_meta("Archive customer", "Customers", "Archives this customer and checks its status by reading it again. Provider permissions and other-agent assignment can reject the change. No messages or bot assignment are sent.")


class UnarchiveCustomer(CustomerOperation):
    operation: Literal["unarchive_customer"] = Field("unarchive_customer", json_schema_extra={"const": "unarchive_customer", "ui:hidden": True})
    model_config = operation_meta("Unarchive customer", "Customers", "Restores this customer's archive status, confirmed with a GET readback. Does not send or start a conversation.")


class ListCustomerFields(CustomerOperation):
    operation: Literal["list_customer_fields"] = Field("list_customer_fields", json_schema_extra={"const": "list_customer_fields", "ui:hidden": True})
    model_config = operation_meta("List customer field metadata", "Customer fields")


class FieldOperation(CustomerOperation):
    field_name: FieldName = Field(..., title="Custom field", json_schema_extra=picker("field_name", "customer_id"))


class GetCustomerField(FieldOperation):
    operation: Literal["get_customer_field"] = Field("get_customer_field", json_schema_extra={"const": "get_customer_field", "ui:hidden": True})
    model_config = operation_meta("Get selected customer field", "Customer fields")


def parse_json(content):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def decimal(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
        return result
    try:
        return json.loads(content, object_pairs_hook=pairs, parse_float=decimal, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Use valid finite JSON without duplicate keys") from None


def bounded_value(value):
    count = 0
    def walk(item, depth):
        nonlocal count
        count += 1
        if depth > 16 or count > 2000:
            raise ValueError("Customer field exceeds the depth or item bound")
        if item is None or isinstance(item, (str, bool)) or type(item) is int:
            if isinstance(item, str) and re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", item):
                raise ValueError("Use field text without control characters")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Use a finite customer field number")
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("Use string JSON keys")
                walk(key, depth + 1)
                walk(child, depth + 1)
        else:
            raise ValueError("Unsupported customer field value")
    walk(value, 0)
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Customer field cannot be encoded as finite JSON") from None
    if len(encoded) > MAX_FIELD_BYTES:
        raise ValueError("Customer field exceeds 16 KiB")
    return value


def typed_value(kind, value):
    bounded_value(value)
    valid = kind == "string" and isinstance(value, str) or kind == "integer" and type(value) is int or kind in {"float", "datetime"} and type(value) in {int, float} or kind == "boolean" and type(value) is bool or kind == "object" and isinstance(value, (dict, list))
    if kind == "date" and isinstance(value, str):
        try:
            valid = re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None and date.fromisoformat(value).isoformat() == value
        except ValueError:
            valid = False
    if not valid:
        raise ValueError("Customer field JSON value must match its documented type")
    return value


class FieldWrite(FieldOperation):
    field_type: FieldType = Field(..., title="Field type")
    value_json: str = Field(..., min_length=1, max_length=MAX_FIELD_BYTES, title="Field value as JSON", description='Use a quoted string, number, true/false, YYYY-MM-DD string, Unix timestamp, or an object/array matching the selected type. Unknown types are refused.', json_schema_extra={"ui:widget": "textarea"})

    @model_validator(mode="after")
    def value(self):
        typed_value(self.field_type, parse_json(self.value_json))
        return self


class CreateCustomerField(FieldWrite):
    operation: Literal["create_customer_field"] = Field("create_customer_field", json_schema_extra={"const": "create_customer_field", "ui:hidden": True})
    model_config = operation_meta("Create customer field", "Customer fields", "Creates only; an existing field returns HTTP 412. It never silently overwrites or falls back to PUT. Changes this customer's stored field value.")


class UpdateCustomerField(FieldWrite):
    operation: Literal["update_customer_field"] = Field("update_customer_field", json_schema_extra={"const": "update_customer_field", "ui:hidden": True})
    model_config = operation_meta("Update existing customer field", "Customer fields", "Reads the existing field before PUT. A missing field is not created. Can change the field type and value; both are checked in the response.")


class DeleteCustomerField(FieldOperation):
    operation: Literal["delete_customer_field"] = Field("delete_customer_field", json_schema_extra={"const": "delete_customer_field", "ui:hidden": True})
    confirm_delete: Literal[True] = Field(..., title="Confirm deleting this field", description="Permanently removes this field from this customer.")
    model_config = operation_meta("Delete customer field", "Customer fields", "Deletes only the selected customer's named field. HTTP 204 has no JSON body. The node does not delete the customer or conversation.")

    @field_validator("confirm_delete", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicitly confirm deleting this customer field")
        return value


class ListMessageHooks(ChannelOperation):
    operation: Literal["list_message_hooks"] = Field("list_message_hooks", json_schema_extra={"const": "list_message_hooks", "ui:hidden": True})
    model_config = operation_meta("List message hook metadata", "Message hooks")


class GetMessageHook(ChannelOperation):
    operation: Literal["get_message_hook"] = Field("get_message_hook", json_schema_extra={"const": "get_message_hook", "ui:hidden": True})
    hook_id: ResourceID = Field(..., title="Message hook", json_schema_extra=picker("hook_id", "channel_id"))
    model_config = operation_meta("Get message hook metadata", "Message hooks")


OPERATIONS = (ListChannels, GetChannel, ListCustomers, GetCustomer, ArchiveCustomer, UnarchiveCustomer, ListCustomerFields, GetCustomerField, CreateCustomerField, UpdateCustomerField, DeleteCustomerField, ListMessageHooks, GetMessageHook)
LandbotOperation = Annotated[Union[ListChannels, GetChannel, ListCustomers, GetCustomer, ArchiveCustomer, UnarchiveCustomer, ListCustomerFields, GetCustomerField, CreateCustomerField, UpdateCustomerField, DeleteCustomerField, ListMessageHooks, GetMessageHook], Discriminator("operation")]


class LandbotNodeConfig(NodeConfig[LandbotOperation, LandbotAgentTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


LANDBOT_SCOPES = ScopeRegistry("landbot", {cls.model_fields["operation"].default: ScopeRequirement((), credential_types=(TYPE,), note="Platform agent token with provider-authoritative workspace/resource permissions. No OAuth scopes are published for this authentication scheme.") for cls in OPERATIONS})


class LandbotAPIError(ValueError):
    def __init__(self, status, retry_after=None):
        self.http_status, self.retry_after = status, retry_after
        super().__init__(f"Landbot HTTP {status}: request was not confirmed" + (f"; retry after {retry_after} seconds" if retry_after is not None else ""))


async def fetch(credential_data, operation, method, route, *, params=None, body=None):
    credential = credential_value(credential_data)
    LANDBOT_SCOPES.enforce_credential_type(operation, credential.credential_type)
    reads = r"/(?:channels/(?:[1-9][0-9]{0,18}/(?:message_hooks/(?:[1-9][0-9]{0,18}/)?)?)?|customers/(?:[1-9][0-9]{0,18}/(?:fields/[a-z0-9_]{1,128}/)?)?)"
    field_route = re.fullmatch(r"/customers/[1-9][0-9]{0,18}/fields/[a-z0-9_]{1,128}/", route)
    if method == "GET":
        allowed, status = re.fullmatch(reads, route), 200
    elif operation in {"archive_customer", "unarchive_customer"}:
        suffix = "archive" if operation == "archive_customer" else "unarchive"
        allowed, status = method == "PUT" and re.fullmatch(r"/customers/[1-9][0-9]{0,18}/" + suffix + "/", route) and body is None, 200
    else:
        wanted = {"create_customer_field": "POST", "update_customer_field": "PUT", "delete_customer_field": "DELETE"}.get(operation)
        allowed, status = method == wanted and field_route, 204 if method == "DELETE" else 200
    if not allowed or method == "GET" and body is not None:
        raise ValueError("Use a native Landbot Platform operation and route")
    if allow_private_hosts():
        raise ValueError("Landbot private-host overrides are unsupported")
    try:
        async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, BASE + route, params=params, headers={"Authorization": "Token " + credential.agent_token, "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "NoClick Landbot integration"}, **({"json": body} if body is not None else {})) as response:
                if response.status_code != status:
                    retry = response.headers.get("retry-after", "")
                    raise LandbotAPIError(response.status_code, int(retry) if re.fullmatch(r"[0-9]{1,6}", retry) else None)
                if status == 204:
                    return None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("Landbot response exceeds 2 MiB; no partial result accepted")
                    content.extend(chunk)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Landbot returned a non-JSON success response")
                try:
                    raw = parse_json(bytes(content).decode("utf-8"))
                except (ValueError, UnicodeError):
                    raise ValueError("Landbot returned malformed JSON; no partial result accepted") from None
                if not isinstance(raw, dict) or raw.get("success") is not True or any(key in raw for key in ("error", "errors")):
                    raise ValueError("Landbot did not return a successful native envelope")
                return raw
    except SSRFError:
        raise ValueError("Landbot destination is not publicly reachable") from None
    except httpx.RequestError:
        raise ValueError("Landbot request could not be completed; no automatic retry") from None


def safe_text(value, credential, maximum=4096, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise ValueError("Landbot returned invalid or oversized metadata text")
    token = credential.agent_token
    value = value.replace(token, "[redacted]").replace(quote(token, safe=""), "[redacted]")
    return re.sub(r"(?i)((?:agent_token|access_token|api_key|token|password|secret|signature)=)[^\s&#]+", r"\1[redacted]", value)


def provider_id(value):
    if type(value) is not int:
        raise ValueError("Landbot returned an invalid numeric ID")
    return resource_id(value)


def project(raw, credential, kind, *, expected=None, channel=None):
    if not isinstance(raw, dict):
        raise ValueError("Landbot returned invalid resource metadata")
    identity = provider_id(raw.get("id"))
    if expected is not None and identity != expected:
        raise ValueError("Landbot returned a different resource ID")
    result = {"id": identity}
    if "name" in raw:
        result["name"] = safe_text(raw["name"], credential, nullable=kind == "hook")
    if kind in {"customer", "hook"}:
        result["channel_id"] = provider_id(raw.get("channel_id"))
        if result["channel_id"] != channel:
            raise ValueError("Landbot returned a resource outside the selected channel")
    text_keys = ("type",) if kind == "channel" else ()
    bool_keys = ("active",) if kind == "channel" else ("unread", "archived") if kind == "customer" else ()
    number_keys = ("created_at",) if kind == "channel" else ("register_date",) if kind == "customer" else ("created_at", "updated_at")
    for key in text_keys:
        if key in raw:
            result[key] = safe_text(raw[key], credential, 80)
    for key in bool_keys:
        if key in raw:
            if type(raw[key]) is not bool:
                raise ValueError("Landbot returned invalid resource status")
            result[key] = raw[key]
    for key in number_keys:
        if key in raw:
            value = raw[key]
            if type(value) not in {int, float} or abs(value) > 1e15 or not math.isfinite(value):
                raise ValueError("Landbot returned invalid metadata timestamps")
            result[key] = value
    return result


def rows(raw, maximum=1000):
    if not isinstance(raw, list) or len(raw) > maximum or any(not isinstance(item, dict) for item in raw):
        raise ValueError("Landbot returned an invalid or oversized metadata collection")
    return raw


def page(raw, credential, kind, config, *, channel=None):
    total = raw.get("total")
    items = rows(raw.get("channels" if kind == "channel" else "customers"), config.limit)
    if type(total) is not int or not 0 <= total <= MAX_OFFSET or config.limit and not items and config.offset < total or items and config.offset + len(items) > total:
        raise ValueError("Landbot returned inconsistent numeric pagination")
    items = [project(item, credential, kind, channel=channel) for item in items]
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("Landbot returned duplicate resources on a page")
    next_offset = config.offset + len(items) if config.limit and items and config.offset + len(items) < total else None
    return {"items": items, "total": total, "offset": config.offset, "limit": config.limit, "next_offset": next_offset}


async def channel_record(credential, operation, identity):
    raw = await fetch(credential, operation, "GET", f"/channels/{identity}/")
    return project(raw.get("channel"), credential, "channel", expected=identity)


async def customer_record(credential, operation, config):
    await channel_record(credential, operation, config.channel_id)
    raw = await fetch(credential, operation, "GET", f"/customers/{config.customer_id}/")
    customer = raw.get("customer")
    data = project(customer, credential, "customer", expected=config.customer_id, channel=config.channel_id)
    return customer, data


def field_metadata(raw, credential, name):
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str) or raw["type"] not in FIELD_TYPES or "name" in raw and raw["name"] != name:
        raise ValueError("Landbot returned a different or invalid customer field")
    return {"name": safe_text(name, credential, 128), "type": raw["type"]}


def sanitized_value(value, credential):
    bounded_value(value)
    def scrub(item):
        if isinstance(item, str):
            return safe_text(item, credential, MAX_FIELD_BYTES)
        if isinstance(item, list):
            return [scrub(child) for child in item]
        if isinstance(item, dict):
            return {safe_text(key, credential, MAX_FIELD_BYTES): "[redacted]" if re.fullmatch(r"(?i)(?:agent_token|access_token|api_key|token|password|secret)", key) else scrub(child) for key, child in item.items()}
        return item
    return scrub(value)


def field_record(raw, credential, name):
    result = field_metadata(raw, credential, name)
    if raw.get("name") != name or "value" not in raw:
        raise ValueError("Landbot did not confirm the requested field name and value")
    result["value"] = sanitized_value(typed_value(raw["type"], raw["value"]), credential)
    return result


def customer_fields(raw, credential):
    fields = raw.get("custom_fields", {})
    if not isinstance(fields, dict) or len(fields) > 1000:
        raise ValueError("Customer field metadata exceeds 1000 entries or is invalid; enter an explicit field name")
    return [field_metadata(value, credential, field_name(name)) for name, value in fields.items()]


async def request_operation(credential_data, config):
    credential = credential_value(credential_data)
    operation = config.operation
    if isinstance(config, ListChannels):
        params = {"limit": config.limit, "offset": config.offset}
        if config.active is not None:
            params["active"] = str(config.active).lower()
        if config.channel_type is not None:
            params["type"] = config.channel_type
        data = page(await fetch(credential, operation, "GET", "/channels/", params=params), credential, "channel", config)
    elif isinstance(config, GetChannel):
        data = await channel_record(credential, operation, config.channel_id)
    elif isinstance(config, ListCustomers):
        await channel_record(credential, operation, config.channel_id)
        params = {"channel_id": config.channel_id, "limit": config.limit, "offset": config.offset}
        if config.archived is not None:
            params["archived"] = str(config.archived).lower()
        data = page(await fetch(credential, operation, "GET", "/customers/", params=params), credential, "customer", config, channel=config.channel_id)
        data["channel_id"] = config.channel_id
    elif isinstance(config, (ListMessageHooks, GetMessageHook)):
        await channel_record(credential, operation, config.channel_id)
        route = f"/channels/{config.channel_id}/message_hooks/"
        if isinstance(config, GetMessageHook):
            raw = await fetch(credential, operation, "GET", route + config.hook_id + "/")
            data = project(raw.get("hook"), credential, "hook", expected=config.hook_id, channel=config.channel_id)
        else:
            # The endpoint spec documents an unpaged hooks array and no query
            # parameters. The generic paging guide conflicts; don't invent
            # offsets or totals for this resource. Fail at a loud 1000 bound.
            raw = await fetch(credential, operation, "GET", route)
            items = [project(item, credential, "hook", channel=config.channel_id) for item in rows(raw.get("hooks"))]
            if "total" in raw and (type(raw["total"]) is not int or raw["total"] != len(items)):
                raise ValueError("Landbot returned a paginated hook envelope inconsistent with its endpoint spec; no partial catalog accepted")
            if len({item["id"] for item in items}) != len(items):
                raise ValueError("Landbot returned duplicate message hooks")
            data = {"channel_id": config.channel_id, "items": items, "pagination": "not documented by endpoint spec"}
    else:
        customer, data = await customer_record(credential, operation, config)
        if isinstance(config, (ArchiveCustomer, UnarchiveCustomer)):
            target = isinstance(config, ArchiveCustomer)
            if data.get("archived") is target:
                return {"data": data, "changed": False}
            suffix = "archive" if target else "unarchive"
            await fetch(credential, operation, "PUT", f"/customers/{config.customer_id}/{suffix}/")
            _, data = await customer_record(credential, operation, config)
            if data.get("archived") is not target:
                raise ValueError("Landbot archive status change was not confirmed; no automatic retry")
            return {"data": data, "changed": True}
        if isinstance(config, ListCustomerFields):
            data = {"channel_id": config.channel_id, "customer_id": config.customer_id, "items": customer_fields(customer, credential)}
        elif isinstance(config, FieldOperation):
            route = f"/customers/{config.customer_id}/fields/{config.field_name}/"
            if isinstance(config, (GetCustomerField, UpdateCustomerField, DeleteCustomerField)):
                existing = await fetch(credential, operation, "GET", route)
                data = field_record(existing.get("field"), credential, config.field_name)
            if isinstance(config, FieldWrite):
                value = typed_value(config.field_type, parse_json(config.value_json))
                if credential.agent_token in json.dumps(value, ensure_ascii=False):
                    raise ValueError("Do not store this connection's agent token in customer metadata")
                raw = await fetch(credential, operation, "POST" if isinstance(config, CreateCustomerField) else "PUT", route, body={"type": config.field_type, "value": value, "extra": {}})
                field = raw.get("field")
                data = field_record(field, credential, config.field_name)
                same_value = field["value"] == value if config.field_type in {"float", "datetime"} else json.dumps(field["value"], sort_keys=True, allow_nan=False) == json.dumps(value, sort_keys=True, allow_nan=False)
                if field["type"] != config.field_type or not same_value:
                    raise ValueError("Landbot did not confirm the exact field type and value; no automatic retry")
            elif isinstance(config, DeleteCustomerField):
                await fetch(credential, operation, "DELETE", route)
                return {"data": {"channel_id": config.channel_id, "customer_id": config.customer_id, "field_name": config.field_name, "deleted": True, "http_status": 204}}
            if isinstance(config, FieldOperation):
                data = {"channel_id": config.channel_id, "customer_id": config.customer_id, **data}
    return {"data": data}


class LandbotAuthorityRepo:
    """Read the current saved token under staging's canonical access predicate."""
    def __init__(self, pool):
        self.pool = pool

    async def load(self, credential_id, user_id, organization_id):
        from repositories.credentials import credential_access_predicate
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT c.credential, c.owner_id, c.credential_type, c.token_version,
                       c.updated_at, c.revoked_at
                FROM credentials c
                WHERE c.id = $1::uuid AND {credential_access_predicate()}
            """, credential_id, user_id, organization_id)
        return dict(row) if row is not None else None


class LandbotNode(WorkflowNode):
    integration_type = "automation-landbot"
    scope_registry = LANDBOT_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_channels", noun="workspace channels", operation_arguments={"limit": 5}, proves="reachability")
    workflow_credential_refresh = True
    edit_examples = ["List my Landbot channels", "List customer metadata for a selected channel", "Create a customer custom field", "Archive a customer without sending a message"]

    @classmethod
    def get_config_model(cls):
        return LandbotNodeConfig

    @classmethod
    def _require_raw(cls, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("config"), dict):
            raise ValueError("Use a native Landbot configuration")
        credential_value(raw.get("credentials"))
        controls = {"url", "base_url", "endpoint", "headers", "method", "body", "params", "token", "agent_token", "access_token", "filter", "search", "search_by"}
        if controls.intersection(raw) or controls.intersection(raw["config"]):
            raise ValueError("Use typed Landbot fields; arbitrary API or token controls are unsupported")

    @classmethod
    def parse_config(cls, config_data):
        cls._require_raw(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._require_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Use native fields and a typed Landbot Platform agent token"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_for_execution(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _freshen_for_execution(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=CURRENT_ORGANIZATION):
        if credential_id:
            if not user_id:
                raise ValueError("Stored Landbot credential requires an authorized caller")
            from utils.database_pool import get_native_pool
            from wss.handlers.workflow_handler import get_user_org_context
            from utils.credentials import resolve_credential_with_owner_fallback, get_workflow_owner_id, is_credential_authorized_for_workflow
            pool = pool if pool is not None else get_native_pool()
            if organization_id is CURRENT_ORGANIZATION:
                async with pool.acquire() as conn:
                    organization_id = await get_user_org_context(conn, user_id)
            authority_user = user_id
            repo = LandbotAuthorityRepo(pool)
            row = await repo.load(credential_id, authority_user, organization_id)
            if row is None and workflow_id:
                owner = await get_workflow_owner_id(pool, workflow_id)
                if owner and owner != user_id and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
                    authority_user = owner
                    row = await repo.load(credential_id, authority_user, organization_id)
            if row is None or row["credential_type"] != TYPE or row["revoked_at"] is not None:
                raise ValueError("Current Landbot authority is unavailable or has a different family")
            credential_data = await resolve_credential_with_owner_fallback(credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id)
            if not credential_data or credential_data.get("credential_type") != row["credential_type"]:
                raise ValueError("Landbot credential unavailable, revoked or access denied")
            if await repo.load(credential_id, authority_user, organization_id) != row:
                raise ValueError("Landbot authority changed during resolution; reconnect and retry deliberately")
        return credential_value(credential_data, manual=not credential_id).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            credential_value(credential_data)
        except ValueError:
            return {"valid": False, "error": "Connect a typed Landbot Platform agent token"}
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"channel_id", "customer_id", "field_name", "hook_id"}:
            return {"options": [], "next_page_token": None}
        credential = credential_value(credential_data, manual=True)
        context = context if isinstance(context, dict) else {}
        channel = resource_id(context.get("channel_id")) if field_name != "channel_id" else None
        customer = resource_id(context.get("customer_id")) if field_name == "field_name" else None
        if search is not None and not isinstance(search, str):
            raise ValueError("Use a picker search string")
        query = normalize_search(search)
        prefix = hashlib.sha256(json.dumps([TYPE, credential.agent_token, field_name, channel, customer, query], separators=(",", ":")).encode()).hexdigest()[:24] + ":"
        offset = 0
        if page_token is not None:
            if not isinstance(page_token, str) or not page_token.startswith(prefix) or not re.fullmatch(r"[0-9]{1,10}", page_token[len(prefix):]):
                raise ValueError("Picker page belongs to a different current token, parent, field or search")
            offset = int(page_token[len(prefix):])
            if offset > MAX_OFFSET:
                raise ValueError("Picker offset exceeds the supported bound")
        config = ListChannels(limit=100, offset=offset) if field_name == "channel_id" else ListCustomers(channel_id=channel, limit=100, offset=offset) if field_name == "customer_id" else ListCustomerFields(channel_id=channel, customer_id=customer) if field_name == "field_name" else ListMessageHooks(channel_id=channel)
        data = (await request_operation(credential, config))["data"]
        options = [{"value": item["name"] if field_name == "field_name" else item["id"], "label": item.get("name") or item.get("id"), "metadata": {"channel_id": channel, **({"customer_id": customer} if customer else {})} if channel else {}} for item in data["items"]]
        options = filter_options_by_search(options, query)
        if field_name in {"field_name", "hook_id"}:
            if offset > len(options):
                raise ValueError("Picker offset exceeds the current bounded metadata catalog")
            return {"options": options[offset:offset + 100], "next_page_token": prefix + str(offset + 100) if offset + 100 < len(options) else None}
        return {"options": options, "next_page_token": prefix + str(data["next_offset"]) if data["next_offset"] is not None else None}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, LandbotNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a typed Landbot Platform agent token")
        # Standalone callers can supply the parsed config without raw node data.
        # Still inspect any supplied raw fields before using the parsed model.
        self._require_raw({**self.config.model_dump(), **(self.node_data or {})})
        credential = await self._freshen_for_execution(self.config.credentials.model_dump(), pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id, credential_id=(self.node_data or {}).get("credential_id"), workflow_id=self.workflow_id, organization_id=self.organization_id)
        return {"status": "success", "action": self.config.config.operation, **await request_operation(credential, self.config.config)}
