"""Native Cliniko business, practitioner, availability and external-contact API.

The issued user key and documented shard govern every authenticated request.
Medical records, appointment bookings, money and communications are excluded.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import date, datetime
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

TYPE = "cliniko_api_key"
SHARDS = {"au1", "au2", "au3", "au4", "au5", "ca1", "uk1", "uk2", "uk3", "us1", "eu1"}
Shard = Literal["au1", "au2", "au3", "au4", "au5", "ca1", "uk1", "uk2", "uk3", "us1", "eu1"]
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGE = 1000000
CURRENT_ORGANIZATION = object()


def resource_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)) or int(value) > 9223372036854775807:
        raise ValueError("Use a positive Cliniko int64 resource ID")
    return str(value)


def simple_text(value):
    if value is None:
        return None
    if not isinstance(value, str) or re.search(r"[\x00-\x1f\x7f]", value) or not value.strip():
        raise ValueError("Use nonempty text without control characters")
    return value.strip()


def contact_email(value):
    value = simple_text(value)
    if value is not None and (len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", value) or len(value.split("@")[0]) > 64 or value.startswith(".") or ".@" in value or ".." in value):
        raise ValueError("Use a contact email address without a display name")
    return value


ResourceID = Annotated[str, BeforeValidator(resource_id)]
Text = Annotated[str, BeforeValidator(simple_text)]
Email = Annotated[str, BeforeValidator(contact_email)]


class ClinikoApiKeyCredential(BaseModel):
    credential_type: Literal["cliniko_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=6000, repr=False, title="Issued Cliniko API Key", json_schema_extra={"ui:widget": "password"})
    admin_contact_email: Email = Field(..., max_length=254, title="Application Administrator Contact", description="Sent in the required NoClick User-Agent contact header. Use an address where your integration administrator can be contacted.")
    shard: Shard = Field("au1", title="Account shard", description="Derived from the issued key suffix. Legacy keys without a suffix use documented au1.", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.api.cliniko.com/#authentication",
        "x-credential-instructions": "Create your user API key under My Info → Manage API keys. Paste the issued value only, retaining its shard suffix. Permissions match that user's current role. The key is the Basic username with an empty password; this is not a Bearer token or an OAuth flow. Supply an administrator contact for NoClick's required User-Agent.",
    })

    @model_validator(mode="before")
    @classmethod
    def issued_shard(cls, value):
        if not isinstance(value, dict):
            return value
        data = {"credential_type": TYPE, **value}
        key = data.get("api_key")
        if isinstance(key, str):
            key = clean_secret(key)
            if not key or re.search(r"[\x00-\x20\x7f:]", key):
                raise ValueError("Paste the issued API key only, without a Basic/Bearer prefix or password")
            suffix = re.search(r"-([A-Za-z]{2}[0-9]{1,2})$", key)
            shard = suffix.group(1).lower() if suffix else "au1"
            if shard not in SHARDS:
                raise ValueError("The key's shard is not in Cliniko's documented current shard list")
            if data.get("shard") not in (None, shard):
                raise ValueError("The saved shard differs from the issued API key suffix")
            data.update(api_key=key, shard=shard)
        return data


def credential_value(raw, *, manual=False):
    if isinstance(raw, ClinikoApiKeyCredential):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        raise ValueError("Connect a typed Cliniko user API key")
    data = dict(raw)
    if manual and not data.get("credential_type") and data.get("api_key"):
        data["credential_type"] = TYPE
    if data.get("credential_type") != TYPE:
        raise ValueError("Current credential family is not a Cliniko user API key")
    try:
        return ClinikoApiKeyCredential.model_validate(data)
    except ValueError:
        raise ValueError("Use a valid issued key, matching shard and administrator contact") from None


def base_url(credential):
    return f"https://api.{credential.shard}.cliniko.com/v1"


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
    page: int = Field(1, strict=True, ge=1, le=MAX_PAGE, title="Page")
    per_page: int = Field(50, strict=True, ge=1, le=100, title="Records per page")


class ListBusinesses(Page):
    operation: Literal["list_businesses"] = Field("list_businesses", json_schema_extra={"const": "list_businesses", "ui:hidden": True})
    model_config = operation_meta("List business metadata", "Businesses")


class GetBusiness(Operation):
    operation: Literal["get_business"] = Field("get_business", json_schema_extra={"const": "get_business", "ui:hidden": True})
    business_id: ResourceID = Field(..., title="Business", json_schema_extra=picker("business_id"))
    model_config = operation_meta("Get business metadata", "Businesses")


class ListPractitioners(Page):
    operation: Literal["list_practitioners"] = Field("list_practitioners", json_schema_extra={"const": "list_practitioners", "ui:hidden": True})
    model_config = operation_meta("List practitioner metadata", "Practitioners")


class GetPractitioner(Operation):
    operation: Literal["get_practitioner"] = Field("get_practitioner", json_schema_extra={"const": "get_practitioner", "ui:hidden": True})
    practitioner_id: ResourceID = Field(..., title="Practitioner", json_schema_extra=picker("practitioner_id"))
    model_config = operation_meta("Get practitioner metadata", "Practitioners")


class ListBusinessPractitioners(Page):
    operation: Literal["list_business_practitioners"] = Field("list_business_practitioners", json_schema_extra={"const": "list_business_practitioners", "ui:hidden": True})
    business_id: ResourceID = Field(..., title="Business", json_schema_extra=picker("business_id"))
    model_config = operation_meta("List business practitioners", "Practitioners")


class ListAppointmentTypes(Page):
    operation: Literal["list_appointment_types"] = Field("list_appointment_types", json_schema_extra={"const": "list_appointment_types", "ui:hidden": True})
    model_config = operation_meta("List appointment-type metadata", "Appointment types")


class GetAppointmentType(Operation):
    operation: Literal["get_appointment_type"] = Field("get_appointment_type", json_schema_extra={"const": "get_appointment_type", "ui:hidden": True})
    appointment_type_id: ResourceID = Field(..., title="Appointment type", json_schema_extra=picker("appointment_type_id"))
    model_config = operation_meta("Get appointment-type metadata", "Appointment types")


class ListPractitionerAppointmentTypes(Page):
    operation: Literal["list_practitioner_appointment_types"] = Field("list_practitioner_appointment_types", json_schema_extra={"const": "list_practitioner_appointment_types", "ui:hidden": True})
    practitioner_id: ResourceID = Field(..., title="Practitioner", json_schema_extra=picker("practitioner_id"))
    model_config = operation_meta("List practitioner appointment types", "Appointment types")


class AvailabilityScope(Operation):
    business_id: ResourceID = Field(..., title="Business", json_schema_extra=picker("business_id"))
    practitioner_id: ResourceID = Field(..., title="Practitioner", json_schema_extra=picker("practitioner_id", "business_id"))
    appointment_type_id: ResourceID = Field(..., title="Appointment type", json_schema_extra=picker("appointment_type_id", "practitioner_id"))
    from_date: str = Field(..., title="From date", description="YYYY-MM-DD in the account's time zone. Provider rejects dates before its current account date.")
    to_date: str = Field(..., title="To date", description="YYYY-MM-DD; at most seven days after the from date.")

    @model_validator(mode="after")
    def window(self):
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", self.from_date) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", self.to_date):
                raise ValueError()
            start, end = date.fromisoformat(self.from_date), date.fromisoformat(self.to_date)
            if not 0 <= (end - start).days <= 7:
                raise ValueError()
        except ValueError:
            raise ValueError("Use an ordered Cliniko date window of at most seven days") from None
        return self


class ListAvailableTimes(AvailabilityScope, Page):
    operation: Literal["list_available_times"] = Field("list_available_times", json_schema_extra={"const": "list_available_times", "ui:hidden": True})
    model_config = operation_meta("List available appointment start times", "Availability")


class GetNextAvailableTime(AvailabilityScope):
    operation: Literal["get_next_available_time"] = Field("get_next_available_time", json_schema_extra={"const": "get_next_available_time", "ui:hidden": True})
    model_config = operation_meta("Get next available appointment start", "Availability")


class ListContacts(Page):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"const": "list_contacts", "ui:hidden": True})
    model_config = operation_meta("List external contact metadata", "External contacts")


class ContactOperation(Operation):
    contact_id: ResourceID = Field(..., title="External contact", json_schema_extra=picker("contact_id"))


class GetContact(ContactOperation):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"const": "get_contact", "ui:hidden": True})
    model_config = operation_meta("Get selected external contact", "External contacts")


class ContactFields(Operation):
    first_name: Text | None = Field(None, max_length=255, title="First name")
    last_name: Text | None = Field(None, max_length=255, title="Last name")
    company_name: Text | None = Field(None, max_length=255, title="Company name")
    email: Email | None = Field(None, max_length=254, title="Contact email", description="External-contact data only. Explicit null clears this field when updating.")


class CreateContact(ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"const": "create_contact", "ui:hidden": True})
    model_config = operation_meta("Create external contact", "External contacts", "Creates a separate Cliniko external contact using only name/company/email fields. Does not create a patient, booking, treatment note or communication. POST is not retried; a later confirmation failure can leave a created record.")

    @model_validator(mode="after")
    def named_contact(self):
        if not any((self.first_name, self.last_name, self.company_name)):
            raise ValueError("Provide a name or company for this external contact")
        return self


class UpdateContact(ContactOperation, ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"const": "update_contact", "ui:hidden": True})
    model_config = operation_meta("Update external contact", "External contacts", "PATCH changes only explicitly supplied name/company/email fields. Omitted fields are preserved; explicit null clears a field. Response and GET readback must confirm the requested changes. No medical/billing/notification fields are accepted.")

    @model_validator(mode="after")
    def supplied_fields(self):
        if not {"first_name", "last_name", "company_name", "email"}.intersection(self.model_fields_set):
            raise ValueError("Provide at least one external-contact field to change")
        return self


class ArchiveContact(ContactOperation):
    operation: Literal["archive_contact"] = Field("archive_contact", json_schema_extra={"const": "archive_contact", "ui:hidden": True})
    confirm_archive: Literal[True] = Field(..., title="Confirm archiving this external contact")
    model_config = operation_meta("Archive external contact", "External contacts", "POST /archive returns bodyless 204, followed by a GET archive-status check. This archives an external contact; it does not delete a patient. The deprecated DELETE alias and undocumented unarchive are not used.")

    @field_validator("confirm_archive", mode="before")
    @classmethod
    def confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicitly confirm archiving this external contact")
        return value


OPERATIONS = (ListBusinesses, GetBusiness, ListPractitioners, GetPractitioner, ListBusinessPractitioners, ListAppointmentTypes, GetAppointmentType, ListPractitionerAppointmentTypes, ListAvailableTimes, GetNextAvailableTime, ListContacts, GetContact, CreateContact, UpdateContact, ArchiveContact)
ClinikoOperation = Annotated[Union[ListBusinesses, GetBusiness, ListPractitioners, GetPractitioner, ListBusinessPractitioners, ListAppointmentTypes, GetAppointmentType, ListPractitionerAppointmentTypes, ListAvailableTimes, GetNextAvailableTime, ListContacts, GetContact, CreateContact, UpdateContact, ArchiveContact], Discriminator("operation")]


class ClinikoNodeConfig(NodeConfig[ClinikoOperation, ClinikoApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


CLINIKO_SCOPES = ScopeRegistry("cliniko", {cls.model_fields["operation"].default: ScopeRequirement((), credential_types=(TYPE,), note="Issued API key permissions equal the user's current role. No OAuth scopes or wider roles are inferred.") for cls in OPERATIONS})


def finite_json(content):
    def pairs(items):
        result = {}
        for key, value in items:
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
        raise ValueError("Cliniko returned malformed or nonfinite JSON") from None


class ClinikoAPIError(ValueError):
    def __init__(self, status, reset_at=None):
        self.http_status, self.rate_limit_reset_at = status, reset_at
        super().__init__(f"Cliniko HTTP {status}: request was not confirmed" + (f"; rate limit resets at Unix time {reset_at}" if reset_at is not None else ""))


async def fetch(credential_data, operation, method, route, *, params=None, body=None):
    credential = credential_value(credential_data)
    CLINIKO_SCOPES.enforce_credential_type(operation, credential.credential_type)
    identity = r"[1-9][0-9]{0,18}"
    reads = rf"/(?:businesses(?:/{identity}(?:/practitioners(?:/{identity}/appointment_types/{identity}/(?:available_times|next_available_time))?)?)?|practitioners(?:/{identity}(?:/appointment_types)?)?|appointment_types(?:/{identity})?|contacts(?:/{identity})?)"
    wanted = "POST" if operation in {"create_contact", "archive_contact"} else "PATCH" if operation == "update_contact" else None
    allowed = re.fullmatch(reads, route) if method == "GET" else method == wanted and re.fullmatch(r"/contacts" if operation == "create_contact" else rf"/contacts/{identity}/archive" if operation == "archive_contact" else rf"/contacts/{identity}", route)
    if not allowed or method == "GET" and body is not None:
        raise ValueError("Use a native Cliniko operation and route")
    if allow_private_hosts():
        raise ValueError("Cliniko private-host overrides are unsupported")
    status = 201 if operation == "create_contact" and method == "POST" else 204 if operation == "archive_contact" and method == "POST" else 200
    auth = "Basic " + base64.b64encode((credential.api_key + ":").encode()).decode()
    try:
        async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, base_url(credential) + route, params=params, headers={"Authorization": auth, "Accept": "application/json", "Content-Type": "application/json", "User-Agent": f"NoClick ({credential.admin_contact_email})"}, **({"json": body} if body is not None else {})) as response:
                if response.status_code != status:
                    reset = response.headers.get("x-ratelimit-reset", "")
                    raise ClinikoAPIError(response.status_code, int(reset) if re.fullmatch(r"[0-9]{1,12}", reset) else None)
                if status == 204:
                    return None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("Cliniko response exceeds 2 MiB; no partial result accepted")
                    content.extend(chunk)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Cliniko returned a non-JSON success response")
                raw = finite_json(bytes(content))
                if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors", "message")):
                    raise ValueError("Cliniko did not return a native resource envelope")
                return raw
    except SSRFError:
        raise ValueError("Cliniko destination is not publicly reachable") from None
    except httpx.RequestError:
        raise ValueError("Cliniko request could not be completed; no automatic retry") from None


def safe_text(value, credential, maximum=4096, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Cliniko returned invalid or oversized metadata text")
    encoded = base64.b64encode((credential.api_key + ":").encode()).decode()
    for secret in (credential.api_key, quote(credential.api_key, safe=""), encoded, credential.admin_contact_email):
        value = value.replace(secret, "[redacted]")
    return re.sub(r"(?i)((?:api_key|token|password|secret|signature)=)[^\s&#]+", r"\1[redacted]", value)


def timestamp(value, credential, *, nullable=False):
    if value is None and nullable:
        return None
    text = safe_text(value, credential, 80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
    except ValueError:
        raise ValueError("Cliniko returned an invalid zoned timestamp") from None
    return text


def project(raw, credential, kind, *, expected=None, selected=False):
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        raise ValueError("Cliniko returned invalid resource metadata or a non-string int64 ID")
    identity = resource_id(raw["id"])
    if expected is not None and identity != expected:
        raise ValueError("Cliniko returned a different resource ID")
    data = {"id": identity}
    keys = {"business": ("business_name", "display_name", "label", "country_code", "time_zone_identifier"), "practitioner": ("display_name", "first_name", "last_name", "title", "designation"), "appointment_type": ("name", "category"), "contact": ("first_name", "last_name", "preferred_name", "company_name", "type")}[kind]
    if kind == "contact" and selected:
        keys += ("email",)
    for key in keys:
        if key in raw:
            data[key] = safe_text(raw[key], credential, 255, nullable=True)
    if kind == "contact" and "type" in data and data["type"] not in (None, "Doctor", "3rd Party Payer", "Standard"):
        raise ValueError("Cliniko returned an unknown external-contact type")
    for key in ("created_at", "updated_at", "archived_at"):
        if key in raw:
            data[key] = timestamp(raw[key], credential, nullable=key == "archived_at")
    for key in (("active", "show_in_online_bookings") if kind == "practitioner" else ("show_in_online_bookings", "telehealth_enabled") if kind == "appointment_type" else ("show_in_online_bookings",) if kind == "business" else ()):
        if key in raw:
            if raw[key] is not None and type(raw[key]) is not bool:
                raise ValueError("Cliniko returned invalid metadata status")
            data[key] = raw[key]
    if kind == "appointment_type":
        for key, maximum in (("duration_in_minutes", 1439), ("max_attendees", 99)):
            if key in raw:
                if type(raw[key]) is not int or not 1 <= raw[key] <= maximum:
                    raise ValueError("Cliniko returned invalid appointment-type metadata")
                data[key] = raw[key]
    if "name" not in data:
        data["name"] = next((data[key] for key in ("display_name", "preferred_name", "business_name", "company_name") if data.get(key)), None) or " ".join(data.get(key) or "" for key in ("first_name", "last_name")).strip() or identity
    return data


def validated_next(value, credential, route, config, params):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\x00-\x20\x7f]", value):
        raise ValueError("Cliniko returned an invalid pagination link")
    try:
        parts = urlsplit(value)
        expected = urlsplit(base_url(credential) + route)
        if parts.scheme != "https" or parts.netloc != expected.netloc or parts.path != expected.path or parts.fragment or parts.username or parts.password:
            raise ValueError()
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        if len(query) != len(pairs) or set(query) - set(params) or not re.fullmatch(r"[1-9][0-9]{0,6}", query.get("page", "")):
            raise ValueError()
        next_page = int(query["page"])
        if next_page != config.page + 1 or next_page > MAX_PAGE:
            raise ValueError()
        for key, wanted in params.items():
            if key == "page":
                continue
            if key in {"from", "to"} and query.get(key) != str(wanted) or key in query and query[key] != str(wanted):
                raise ValueError()
        return next_page
    except (ValueError, UnicodeError):
        raise ValueError("Cliniko pagination changed shard, resource, filters, size or page; no link followed") from None


def page_result(raw, credential, kind, route, config, params):
    collection = "available_times" if kind == "available_time" else {"business": "businesses", "practitioner": "practitioners", "appointment_type": "appointment_types", "contact": "contacts"}[kind]
    items, total, links = raw.get(collection), raw.get("total_entries"), raw.get("links")
    if not isinstance(items, list) or len(items) > config.per_page or any(not isinstance(item, dict) for item in items) or type(total) is not int or not 0 <= total <= 1000000000 or not isinstance(links, dict):
        raise ValueError("Cliniko returned invalid pagination metadata")
    position = (config.page - 1) * config.per_page
    if items and position + len(items) > total or not items and position < total:
        raise ValueError("Cliniko returned inconsistent page totals")
    data = [{"appointment_start": timestamp(item.get("appointment_start"), credential)} for item in items] if kind == "available_time" else [project(item, credential, kind) for item in items]
    identities = [item["appointment_start"] if kind == "available_time" else item["id"] for item in data]
    if len(set(identities)) != len(identities):
        raise ValueError("Cliniko returned duplicate entries on a page")
    next_page = validated_next(links["next"], credential, route, config, params) if links.get("next") is not None else None
    if bool(next_page) != bool(items and position + len(items) < total):
        raise ValueError("Cliniko pagination is incomplete or has an inconsistent continuation")
    return {"items": data, "total_entries": total, "page": config.page, "per_page": config.per_page, "next_page": next_page}


async def record(credential, operation, kind, identity, *, selected=False):
    resource = {"business": "businesses", "practitioner": "practitioners", "appointment_type": "appointment_types", "contact": "contacts"}[kind]
    return project(await fetch(credential, operation, "GET", f"/{resource}/{identity}"), credential, kind, expected=identity, selected=selected)


async def request_operation(credential_data, config):
    credential = credential_value(credential_data)
    operation = config.operation
    scope = {}
    if isinstance(config, AvailabilityScope):
        for kind, identity in (("business", config.business_id), ("practitioner", config.practitioner_id), ("appointment_type", config.appointment_type_id)):
            await record(credential, operation, kind, identity)
        scope = {"business_id": config.business_id, "practitioner_id": config.practitioner_id, "appointment_type_id": config.appointment_type_id}
        route = f"/businesses/{config.business_id}/practitioners/{config.practitioner_id}/appointment_types/{config.appointment_type_id}/" + ("available_times" if isinstance(config, ListAvailableTimes) else "next_available_time")
        params = {"from": config.from_date, "to": config.to_date}
        if isinstance(config, GetNextAvailableTime):
            raw = await fetch(credential, operation, "GET", route, params=params)
            total = raw.get("total_entries")
            if type(total) is not int or total not in (0, 1) or total == 0 and raw.get("appointment_start") is not None:
                raise ValueError("Cliniko did not confirm a single next available start or an empty result")
            start = timestamp(raw.get("appointment_start"), credential) if total else None
            return {"data": {**scope, "appointment_start": start, "total_entries": total}}
        kind = "available_time"
    elif isinstance(config, Page):
        params = {}
        if isinstance(config, ListBusinessPractitioners):
            await record(credential, operation, "business", config.business_id)
            route, kind, scope = f"/businesses/{config.business_id}/practitioners", "practitioner", {"business_id": config.business_id}
        elif isinstance(config, ListPractitionerAppointmentTypes):
            await record(credential, operation, "practitioner", config.practitioner_id)
            route, kind, scope = f"/practitioners/{config.practitioner_id}/appointment_types", "appointment_type", {"practitioner_id": config.practitioner_id}
        else:
            kind = "business" if isinstance(config, ListBusinesses) else "practitioner" if isinstance(config, ListPractitioners) else "appointment_type" if isinstance(config, ListAppointmentTypes) else "contact"
            route = "/" + {"business": "businesses", "practitioner": "practitioners", "appointment_type": "appointment_types", "contact": "contacts"}[kind]
    else:
        if isinstance(config, (GetBusiness, GetPractitioner, GetAppointmentType)):
            kind, identity = ("business", config.business_id) if isinstance(config, GetBusiness) else ("practitioner", config.practitioner_id) if isinstance(config, GetPractitioner) else ("appointment_type", config.appointment_type_id)
            return {"data": await record(credential, operation, kind, identity)}
        if isinstance(config, ContactOperation):
            before = await record(credential, operation, "contact", config.contact_id, selected=True)
            if isinstance(config, GetContact):
                return {"data": before}
            if isinstance(config, ArchiveContact):
                if before.get("archived_at") is not None:
                    return {"data": before, "changed": False}
                await fetch(credential, operation, "POST", f"/contacts/{config.contact_id}/archive")
                after = await record(credential, operation, "contact", config.contact_id, selected=True)
                if after.get("archived_at") is None:
                    raise ValueError("Cliniko archive status was not confirmed; no automatic retry")
                return {"data": after, "changed": True}
        body = config.model_dump(include={"first_name", "last_name", "company_name", "email"}, exclude_unset=True)
        if credential.api_key in json.dumps(body, ensure_ascii=False):
            raise ValueError("Do not store this connection's API key in external contacts")
        route = "/contacts" if isinstance(config, CreateContact) else f"/contacts/{config.contact_id}"
        raw = await fetch(credential, operation, "POST" if isinstance(config, CreateContact) else "PATCH", route, body=body)
        data = project(raw, credential, "contact", expected=config.contact_id if isinstance(config, UpdateContact) else None, selected=True)
        if any(raw.get(key) != value for key, value in body.items()):
            raise ValueError("Cliniko contact changes were not confirmed; no automatic retry")
        raw_readback = await fetch(credential, operation, "GET", f"/contacts/{data['id']}")
        data = project(raw_readback, credential, "contact", expected=data["id"], selected=True)
        if any(raw_readback.get(key) != value for key, value in body.items()):
            raise ValueError("Cliniko contact readback did not confirm the requested fields; no automatic retry")
        return {"data": data}
    params.update(page=config.page, per_page=config.per_page)
    data = page_result(await fetch(credential, operation, "GET", route, params=params), credential, kind, route, config, params)
    return {"data": {**scope, **data}}


class ClinikoNode(WorkflowNode):
    integration_type = "automation-cliniko"
    credential_provider_labels = {"cliniko": "Cliniko User API Connection"}
    auto_select_credential = False
    scope_registry = CLINIKO_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_businesses", noun="business metadata", operation_arguments={}, proves="reachability")
    edit_examples = ["List Cliniko business metadata", "Find available start times for a selected business and practitioner", "Create an external contact without creating a patient"]

    @classmethod
    def get_config_model(cls):
        return ClinikoNodeConfig

    @classmethod
    def _require_raw(cls, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("config"), dict):
            raise ValueError("Use a native Cliniko configuration")
        credential_value(raw.get("credentials"))
        controls = {"url", "base_url", "endpoint", "headers", "method", "body", "params", "api_key", "access_token", "filter", "q", "q[]", "patient_id", "notes", "diagnosis", "billing"}
        if controls.intersection(raw) or controls.intersection(raw["config"]):
            raise ValueError("Use typed Cliniko fields; arbitrary API, medical or billing controls are unsupported")

    @classmethod
    def parse_config(cls, config_data):
        cls._require_raw(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._require_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Use native fields and a typed Cliniko user API key"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._resolve_current_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id
        )

    @classmethod
    async def _resolve_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=CURRENT_ORGANIZATION):
        if credential_id:
            if not user_id:
                raise ValueError("Stored Cliniko credential requires an authorized caller")
            from utils.database_pool import get_native_pool
            from wss.handlers.workflow_handler import get_user_org_context
            from repositories.credentials import CredentialsRepo
            from utils.credentials import resolve_credential_with_owner_fallback, get_workflow_owner_id, is_credential_authorized_for_workflow
            pool = pool if pool is not None else get_native_pool()
            if organization_id is CURRENT_ORGANIZATION:
                async with pool.acquire() as conn:
                    organization_id = await get_user_org_context(conn, user_id)
            authority_user = user_id
            repo = CredentialsRepo(pool)
            # Use staging’s accessible-row snapshot; the resolver below checks
            # revocation and supplies the authoritative credential family.
            row = await repo.fetch_with_access(credential_id, authority_user, organization_id)
            if row is None and workflow_id:
                owner = await get_workflow_owner_id(pool, workflow_id)
                if owner and owner != user_id and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
                    authority_user = owner
                    row = await repo.fetch_with_access(credential_id, authority_user, organization_id)
            if row is None or row.credential_type != TYPE:
                raise ValueError("Current Cliniko authority is unavailable or has a different family")
            credential_data = await resolve_credential_with_owner_fallback(credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id)
            if not credential_data or credential_data.get("credential_type") != row.credential_type:
                raise ValueError("Cliniko credential unavailable, revoked or access denied")
            if await repo.fetch_with_access(credential_id, authority_user, organization_id) != row:
                raise ValueError("Cliniko authority changed during resolution; reconnect and retry deliberately")
        return credential_value(credential_data, manual=not credential_id).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data):
        # Staging's post-connect hook validates the shape; connection_evidence
        # supplies the provider probe through the existing connect path.
        try:
            credential_value(credential_data)
        except ValueError:
            return {"valid": False, "error": "Connect a typed Cliniko user API key"}
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"business_id", "practitioner_id", "appointment_type_id", "contact_id"}:
            return {"options": [], "next_page_token": None}
        credential = credential_value(credential_data, manual=True)
        context = context if isinstance(context, dict) else {}
        business = resource_id(context["business_id"]) if field_name == "practitioner_id" and context.get("business_id") is not None else None
        practitioner = resource_id(context["practitioner_id"]) if field_name == "appointment_type_id" and context.get("practitioner_id") is not None else None
        if any(key in context for key in ("_business_id", "_practitioner_id", "_appointment_type_id", "_shard")):
            raise ValueError("Use public native picker parent fields")
        if search is not None and not isinstance(search, str):
            raise ValueError("Use a picker search string")
        query = normalize_search(search)
        prefix = hashlib.sha256(json.dumps([TYPE, credential.api_key, credential.shard, credential.admin_contact_email, field_name, business, practitioner, query], separators=(",", ":")).encode()).hexdigest()[:24] + ":"
        page = 1
        if page_token is not None:
            if not isinstance(page_token, str) or not page_token.startswith(prefix) or not re.fullmatch(r"[1-9][0-9]{0,6}", page_token[len(prefix):]):
                raise ValueError("Picker page belongs to a different current key, shard, parent, field or search")
            page = int(page_token[len(prefix):])
            if page > MAX_PAGE:
                raise ValueError("Picker page exceeds the supported bound")
        config = ListBusinesses(page=page, per_page=100) if field_name == "business_id" else ListBusinessPractitioners(business_id=business, page=page, per_page=100) if business else ListPractitionerAppointmentTypes(practitioner_id=practitioner, page=page, per_page=100) if practitioner else ListPractitioners(page=page, per_page=100) if field_name == "practitioner_id" else ListAppointmentTypes(page=page, per_page=100) if field_name == "appointment_type_id" else ListContacts(page=page, per_page=100)
        data = (await request_operation(credential, config))["data"]
        options = [{"value": item["id"], "label": item["name"], "metadata": {**({"business_id": business} if business else {}), **({"practitioner_id": practitioner} if practitioner else {})}} for item in data["items"]]
        return {"options": filter_options_by_search(options, query), "next_page_token": prefix + str(data["next_page"]) if data["next_page"] is not None else None}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, ClinikoNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a typed Cliniko user API key")
        credential = await self._resolve_current_credential(self.config.credentials.model_dump(), pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id, credential_id=(self.node_data or {}).get("credential_id"), workflow_id=self.workflow_id, organization_id=self.organization_id)
        return {"status": "success", "action": self.config.config.operation, **await request_operation(credential, self.config.config)}
