"""Zenoti v1 protected center metadata and narrowly scoped guest CRM updates.

Issued organization API keys and expiring user tokens are separate families.
No authentication mint, booking, communication, payment or membership actions.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-zenoti"
FAMILIES = ("zenoti_api_key", "zenoti_bearer_token")
BASE = "https://api.zenoti.com"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000
WRITE_OPS = ("update_guest_crm_metadata",)
GUID = r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"


def _token(value):
    value = value.strip()
    if not 1 <= len(value) <= 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or value.lower().startswith(("bearer ", "apikey ", "basic ")):
        raise ValueError("Supply the issued Zenoti credential without an authorization prefix")
    return value


def _expiry(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Supply the actual timezone-aware user-token expiry")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Supply the actual timezone-aware user-token expiry") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("User-token expiry requires a timezone")
    return parsed


class ZenotiAPIKeyCredential(BaseModel):
    credential_type: Literal["zenoti_api_key"] = Field("zenoti_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Organization API Key", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Zenoti API Key", extra="ignore", json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-url": "https://docs.zenoti.com/docs/authentication",
        "x-credential-instructions": "Supply an existing organization-issued API key. Sent as Authorization: apikey KEY. Organization-wide key access is distinct from a role-bound user token. API enablement and write permission are not proved by a catalog read. No environment fallback or key creation.",
    })
    _validate_token = field_validator("api_key")(_token)


class ZenotiBearerTokenCredential(BaseModel):
    credential_type: Literal["zenoti_bearer_token"] = Field("zenoti_bearer_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Existing User Token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., title="Actual Token Expiry", description="Timezone-aware ISO 8601 expiry supplied with the issued token; no assumed duration or renewal.")
    model_config = ConfigDict(title="Zenoti User Token", extra="ignore", json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-url": "https://docs.zenoti.com/docs/authentication",
        "x-credential-instructions": "Supply an existing role-bound Zenoti user token and its actual expiry. Sent as Authorization: bearer TOKEN. Employee permissions, password changes, departures and token expiry can restrict access. This node does not obtain or refresh tokens and does not prove a user identity from public catalog metadata.",
    })
    _validate_token = field_validator("access_token")(_token)

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        _expiry(value)
        return value


ZenotiCredential = Union[ZenotiAPIKeyCredential, ZenotiBearerTokenCredential]


def _op(name, label, category):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(GUID, value):
        raise ValueError("Use an exact Zenoti GUID")
    return str(UUID(value))


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use an ISO calendar date")
    date.fromisoformat(value)
    return value


def _dynamic(name, parent=None):
    meta = {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True}, "x-resource-type": "zenoti_" + name.removesuffix("_id"), "x-resource-id-path": name}
    if parent:
        meta["x-dynamic-options"]["depends_on"] = parent
    return meta


class ZenotiOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ZenotiCheckConfig(ZenotiOperation):
    operation: Literal["check_api_access"] = _op("check_api_access", "Check API Reachability", "Connection")


class ZenotiPage(ZenotiOperation):
    page: int = Field(1, ge=1, le=10000, description="One vendor page; continuation is verified only when page_info is returned.")
    size: int = Field(10, ge=1, le=100, description="Zenoti maximum 100. Missing page_info does not prove exhaustion.")

    @field_validator("page", "size", mode="before")
    @classmethod
    def whole_number(cls, value):
        if isinstance(value, str) and re.fullmatch(r"[0-9]{1,5}", value):
            value = int(value)
        if type(value) is not int:
            raise ValueError("Page and size must be whole numbers")
        return value


class ZenotiCenterScope(ZenotiOperation):
    center_id: str = Field(..., title="Center", json_schema_extra=_dynamic("center_id"))
    _center = field_validator("center_id", mode="before")(_id)


class ZenotiListCentersConfig(ZenotiPage):
    operation: Literal["list_centers"] = _op("list_centers", "List Centers", "Centers")


class ZenotiGetCenterConfig(ZenotiCenterScope):
    operation: Literal["get_center"] = _op("get_center", "Get Center Metadata", "Centers")


class ZenotiOrganizationConfig(ZenotiOperation):
    operation: Literal["get_organization_metadata"] = _op("get_organization_metadata", "Get Organization Metadata", "Organization")


class ZenotiGuestSettingsConfig(ZenotiOperation):
    operation: Literal["get_guest_configuration"] = _op("get_guest_configuration", "Get Guest Configuration Metadata", "Organization")


class ZenotiListServicesConfig(ZenotiPage, ZenotiCenterScope):
    operation: Literal["list_center_services"] = _op("list_center_services", "List Center Service Metadata", "Services")


class ZenotiServiceScope(ZenotiCenterScope):
    service_id: str = Field(..., title="Service", json_schema_extra=_dynamic("service_id", "center_id"))
    _service = field_validator("service_id", mode="before")(_id)


class ZenotiGetServiceConfig(ZenotiServiceScope):
    operation: Literal["get_service"] = _op("get_service", "Get Service Metadata", "Services")


class ZenotiListEmployeesConfig(ZenotiPage, ZenotiCenterScope):
    operation: Literal["list_center_employees"] = _op("list_center_employees", "List Center Employee Metadata", "Employees")


class ZenotiGetEmployeeConfig(ZenotiCenterScope):
    operation: Literal["get_center_employee"] = _op("get_center_employee", "Find Center Employee Metadata", "Employees")
    employee_id: str = Field(..., title="Employee", json_schema_extra=_dynamic("employee_id", "center_id"))
    _employee = field_validator("employee_id", mode="before")(_id)


class ZenotiListGuestsConfig(ZenotiPage, ZenotiCenterScope):
    operation: Literal["list_center_guests"] = _op("list_center_guests", "List Center Guest Metadata", "Guests")
    last_updated: Optional[str] = Field(None, description="Optional ISO date. Guest names and contact details are excluded from output.")

    @field_validator("last_updated")
    @classmethod
    def day(cls, value):
        return None if value is None else _day(value)


class ZenotiGuestScope(ZenotiCenterScope):
    guest_id: str = Field(..., title="Guest", json_schema_extra=_dynamic("guest_id", "center_id"))
    _guest = field_validator("guest_id", mode="before")(_id)


class ZenotiGetGuestConfig(ZenotiGuestScope):
    operation: Literal["get_guest"] = _op("get_guest", "Get Guest CRM Metadata", "Guests")


class ZenotiAppointmentsConfig(ZenotiGuestScope, ZenotiPage):
    operation: Literal["list_guest_appointments"] = _op("list_guest_appointments", "List Guest Appointment Metadata", "Appointments")
    start_date: str = Field(..., description="ISO date; local privacy window at most 31 days.")
    end_date: str = Field(..., description="ISO date, on or after start date.")
    _dates = field_validator("start_date", "end_date")(_day)

    @model_validator(mode="after")
    def window(self):
        days = (date.fromisoformat(self.end_date) - date.fromisoformat(self.start_date)).days
        if not 0 <= days <= 30:
            raise ValueError("Use an ordered appointment window of at most 31 calendar days")
        return self


class ZenotiUpdateGuestConfig(ZenotiGuestScope):
    operation: Literal["update_guest_crm_metadata"] = _op("update_guest_crm_metadata", "Update Guest CRM Metadata", "Guests")
    guest_code: Optional[str] = Field(None, min_length=1, max_length=80, description="Optional replacement CRM code. Blank omits; it does not clear.")
    preferred_service_id: Optional[str] = Field(None, title="Preferred Service", json_schema_extra={**_dynamic("service_id", "center_id"), "x-resource-id-path": "preferred_service_id"}, description="Optional existing service in the selected center. No booking or price change.")
    confirm_update: bool = Field(False, description="Confirm a full-profile read-modify-write. Unchanged profile fields are preserved; concurrent changes can race. Notification behavior remains unverified.")

    @field_validator("guest_code")
    @classmethod
    def code(cls, value):
        if value is not None and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use a nonblank bounded CRM code")
        return value

    @field_validator("preferred_service_id", mode="before")
    @classmethod
    def preferred(cls, value):
        return None if value is None else _id(value)

    @model_validator(mode="after")
    def changes(self):
        if self.guest_code is None and self.preferred_service_id is None:
            raise ValueError("Select at least one CRM metadata change")
        return self


ZenotiConfig = Annotated[Union[ZenotiCheckConfig, ZenotiListCentersConfig, ZenotiGetCenterConfig, ZenotiOrganizationConfig, ZenotiGuestSettingsConfig, ZenotiListServicesConfig, ZenotiGetServiceConfig, ZenotiListEmployeesConfig, ZenotiGetEmployeeConfig, ZenotiListGuestsConfig, ZenotiGetGuestConfig, ZenotiAppointmentsConfig, ZenotiUpdateGuestConfig], Field(discriminator="operation")]


class ZenotiNodeConfig(NodeConfig[ZenotiConfig, ZenotiCredential]):
    model_config = ConfigDict(title="Zenoti Node Configuration")


class ZenotiAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False):
        super().__init__(message)
        self.authority_rejected = authority_rejected


def _shape(data):
    if not isinstance(data, dict):
        raise ValueError("Zenoti credentials are invalid")
    family = data.get("credential_type")
    if family is None:
        has_key, has_token = bool(data.get("api_key")), bool(data.get("access_token"))
        if has_key == has_token:
            raise ValueError("Select an unambiguous Zenoti credential family")
        family = FAMILIES[0] if has_key else FAMILIES[1]
    if family not in FAMILIES:
        raise ValueError("Zenoti credential family is unsupported")
    model = ZenotiAPIKeyCredential if family == FAMILIES[0] else ZenotiBearerTokenCredential
    try:
        shaped = model.model_validate({**data, "credential_type": family}).model_dump()
    except Exception:
        raise ValueError("Zenoti credentials are invalid") from None
    if family == FAMILIES[1] and _expiry(shaped["expires_at"]) <= datetime.now(timezone.utc):
        raise ZenotiAPIError("Zenoti user token has expired; supply a current issued token", authority_rejected=True)
    return {**data, **shaped}


def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("Zenoti configuration is invalid")
    creds = data.get("credentials") if isinstance(data, dict) else None
    if (data.get("credential_id") or data.get("credentialIds")) and not isinstance(creds, dict):
        raise ValueError("Zenoti saved credential family is missing or unsupported")
    if isinstance(creds, dict) and (creds.get("credential_type") is not None or data.get("credential_id") or data.get("credentialIds")) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("Zenoti saved credential family is missing or unsupported")


def _secret(data):
    return data["api_key"] if data["credential_type"] == FAMILIES[0] else data["access_token"]


def _binding(data):
    return (data["credential_type"], _secret(data), data.get("expires_at"), data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))


@dataclass(frozen=True, repr=False)
class _LookupAuthority:
    pool: Any
    user_id: str
    credential_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]


async def _current_data(data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
    if not credential_id:
        return _shape(data)
    if not user_id:
        raise ValueError("Stored Zenoti credential requires an authorized caller")
    from utils.credentials import resolve_credential_with_owner_fallback
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()
    if organization_id is None:
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
    result = await resolve_credential_with_owner_fallback(
        credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id)
    if not isinstance(result, dict) or result.get("credential_type") not in FAMILIES:
        raise ValueError("Zenoti current credential is unavailable or access denied")
    return {**_shape(result), "_zenoti_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_zenoti_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("Zenoti picker actor does not match saved authority")
        result.update({"_approval_pool": bound.pool, "_user_id": bound.user_id, "_credential_id": bound.credential_id, "_organization_id": bound.organization_id, "_workflow_id": bound.workflow_id})
    return result


def _authority(context):
    return {"pool": context.get("_approval_pool"), "user_id": context.get("_user_id"), "credential_id": context.get("_credential_id"), "organization_id": context.get("_organization_id"), "workflow_id": context.get("_workflow_id")}


def _bounded(value, depth=0):
    if depth > 32 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Unverified JSON depth or non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if len(key) > 512:
                raise ValueError("Unverified JSON key")
            _bounded(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise ValueError("Unverified JSON row bound")
        for child in value:
            _bounded(child, depth + 1)


def _redact(value, secret):
    if isinstance(value, str):
        variants = (secret, quote(secret, safe=""), quote_plus(secret, safe=""), base64.b64encode(secret.encode()).decode(), base64.b64encode((secret + ":").encode()).decode())
        for variant in variants:
            pattern = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: '%' + ''.join('[' + c.lower() + c.upper() + ']' for c in m[1]), re.escape(variant))
            value = re.sub(pattern, "[redacted]", value)
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"\1[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


def _route_allowed(route, write):
    if write:
        return re.fullmatch(r"/v1/guests/" + GUID, route) is not None
    return route in ("/v1/centers", "/v1/guests", "/v1/organizations/settings/general", "/v1/organizations/settings/guest") or re.fullmatch(r"/v1/Centers/" + GUID + r"(?:/services(?:/" + GUID + r")?)?", route) is not None or re.fullmatch(r"/v1/centers/" + GUID + r"/employees", route) is not None or re.fullmatch(r"/v1/guests/" + GUID + r"(?:/appointments)?", route) is not None


async def _request(data, context, route, params=None, *, body=None):
    write = body is not None
    if not _route_allowed(route, write):
        raise ValueError("Unsupported Zenoti native route or effect")
    current = await _current_data(data, **_authority(context))
    if _binding(current) != _binding(data):
        raise ValueError("Zenoti current credential changed; rerun with current authority")
    suffix = " Write outcome is unverified; read the owned guest before retrying." if write else ""
    if write:
        _bounded(body)
        if len(json.dumps(body, allow_nan=False, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError("Zenoti full guest profile exceeds the local request bound; no update was sent")
    auth = ("apikey " if current["credential_type"] == FAMILIES[0] else "bearer ") + _secret(current)
    try:
        async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream("PUT" if write else "GET", BASE + route,
                                     headers={"Authorization": auth, "Accept": "application/json", **({"Content-Type": "application/json"} if write else {})},
                                     **({"json": body} if write else {"params": params or {}})) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(raw) + len(chunk) > MAX_BYTES:
                        raise ZenotiAPIError("Zenoti response exceeds the local byte bound." + suffix)
                    raw.extend(chunk)
                if response.status_code in (401, 403):
                    raise ZenotiAPIError(f"Zenoti HTTP {response.status_code}: authority rejected." + suffix, authority_rejected=True)
                if response.status_code != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ZenotiAPIError(f"Zenoti HTTP {response.status_code}: documented JSON success is unverified." + suffix)
                try:
                    result = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _bounded(result)
                except (ValueError, UnicodeError, RecursionError):
                    raise ZenotiAPIError("Zenoti response JSON is unverified." + suffix) from None
                if not isinstance(result, dict):
                    raise ZenotiAPIError("Zenoti response envelope is unverified." + suffix)
                error = result.get("error")
                if error is not None:
                    code = error.get("code") if isinstance(error, dict) else None
                    raise ZenotiAPIError("Zenoti returned a provider error." + suffix, authority_rejected=code in (401, 403, "401", "403"))
                if result.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"):
                    raise ZenotiAPIError("Zenoti returned an unverified execution result." + suffix)
                return result
    except ZenotiAPIError:
        raise
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise ZenotiAPIError("Zenoti transport failed; result is unverified." + suffix) from None


def _pick(row, fields):
    out = {}
    for key, expected in fields.items():
        if key not in row:
            continue
        value = row[key]
        if value is None:
            out[key] = None
        elif expected == "id":
            try:
                out[key] = _id(value)
            except ValueError:
                raise ZenotiAPIError("Zenoti linked resource ID is unverified") from None
        elif type(value) is not expected or isinstance(value, str) and (len(value) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ZenotiAPIError("Zenoti selected metadata is unverified")
        else:
            out[key] = value
    return out


def _record(row, kind, *, wanted=None, center=None):
    if not isinstance(row, dict):
        raise ZenotiAPIError("Zenoti resource is unverified")
    key = "appointment_group_id" if kind == "appointment" else "id"
    try:
        identifier = _id(row.get(key))
    except ValueError:
        raise ZenotiAPIError("Zenoti resource ID is unverified") from None
    if wanted is not None and identifier != wanted:
        raise ZenotiAPIError("Zenoti returned another resource")
    fields = {
        "center": {"name": str, "code": str, "display_name": str, "time_zone_id": int},
        "service": {"name": str, "code": str, "duration": int, "recovery_time": int},
        "employee": {},
        "guest": {"center_id": "id", "code": str, "preferred_service_id": "id", "created_date": str, "is_virtual_guest": bool, "is_guest_custom_form_filled": bool},
        "appointment": {"center_id": "id", "is_rebooking": bool, "is_feedback_submitted": bool},
    }[kind]
    # An empty preferred-service identifier denotes no preference in Zenoti's
    # published guest examples; it is not a resource identifier.
    if kind == "guest" and row.get("preferred_service_id") == "":
        row = {k: v for k, v in row.items() if k != "preferred_service_id"}
    out = {key: identifier, **_pick(row, fields)}
    if center is not None and kind in ("guest", "appointment") and out.get("center_id") != center:
        raise ZenotiAPIError("Zenoti resource does not match the selected center")
    if kind == "employee" and row.get("job_info") is not None:
        if not isinstance(row["job_info"], dict):
            raise ZenotiAPIError("Zenoti employee job metadata is unverified")
        out["job_info"] = _pick(row["job_info"], {"id": "id"})
    if kind == "appointment" and "appointment_services" in row:
        if not isinstance(row["appointment_services"], list):
            raise ZenotiAPIError("Zenoti appointment service metadata is unverified")
        services = []
        for item in row["appointment_services"]:
            if not isinstance(item, dict):
                raise ZenotiAPIError("Zenoti appointment service metadata is unverified")
            projected = _pick(item, {"appointment_id": "id", "start_time": str, "end_time": str, "appointment_status": int})
            if "appointment_id" not in projected:
                raise ZenotiAPIError("Zenoti appointment service ID is unverified")
            if item.get("service") is not None:
                projected["service"] = _record(item["service"], "service")
            services.append(projected)
        out["appointment_services"] = services
    return out


async def _page(data, context, route, kind, params, *, center=None):
    result = await _request(data, context, route, params)
    key = {"center": "centers", "service": "services", "employee": "employees", "guest": "guests", "appointment": "appointments"}[kind]
    size, page = params.get("size", params.get("Size")), params.get("page", params.get("Page"))
    if not isinstance(result.get(key), list) or len(result[key]) > size:
        raise ZenotiAPIError("Zenoti paginated resources are unverified")
    rows = [_record(row, kind, center=center) for row in result[key]]
    id_key = "appointment_group_id" if kind == "appointment" else "id"
    if len({r[id_key] for r in rows}) != len(rows):
        raise ZenotiAPIError("Zenoti page repeats resource IDs")
    info = result.get("page_info")
    if info is None:
        return {"results": rows, "returned_count": len(rows), "next_page": None, "pagination_verified": False, "possible_more": True}
    if not isinstance(info, dict) or any(type(info.get(k)) is not int for k in ("total", "page", "size")) or info["total"] < 0 or info["page"] != page or info["size"] != size:
        raise ZenotiAPIError("Zenoti page_info is unverified")
    total, offset = info["total"], (page - 1) * size
    expected = min(size, max(0, total - offset))
    if len(rows) != expected:
        raise ZenotiAPIError("Zenoti page length does not match page_info")
    return {"results": rows, "returned_count": len(rows), "next_page": page + 1 if page * size < total else None, "pagination_verified": True, "total": total, "possible_more": page * size < total}


async def _center(data, context, center_id):
    raw = await _request(data, context, "/v1/Centers/" + center_id)
    return _record(raw.get("center"), "center", wanted=center_id)


async def _guest(data, context, guest_id, center_id):
    raw = await _request(data, context, "/v1/guests/" + guest_id)
    _record(raw, "guest", wanted=guest_id, center=center_id)
    return raw


def _profile(raw):
    # Published PUT contract requires the complete expanded GET profile, not a patch.
    mandatory = ("code", "center_id", "personal_info", "address_info", "preferences", "tags", "referral", "primary_employee")
    if any(k not in raw for k in mandatory) or not isinstance(raw["personal_info"], dict) or not isinstance(raw["code"], str):
        raise ValueError("Zenoti full expanded guest profile is unavailable; no update was sent")
    def sensitive(value):
        if isinstance(value, dict):
            return any(k.lower() in ("login_info", "password", "access_token", "api_key", "authorization", "credentials") or sensitive(v) for k, v in value.items())
        return isinstance(value, list) and any(sensitive(v) for v in value)
    if sensitive(raw):
        raise ValueError("Zenoti guest snapshot contains authentication fields; no update was sent")
    return {k: v for k, v in raw.items() if k != "error"}


class ZenotiNode(WorkflowNode):
    integration_type = "automation-zenoti"
    credential_provider_labels = {"zenoti": "Zenoti Account"}
    node_type = NODE_TYPE
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="check_api_access", noun="Zenoti API access", proves="reachability")
    edit_examples = ["List service metadata in a selected Zenoti center", "Read scoped guest CRM and appointment metadata", "Update an owned guest CRM code while preserving the full profile"]

    @classmethod
    def get_config_model(cls):
        return ZenotiNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data)
        shaped = dict(config_data)
        if config_data.get("credentials") is not None:
            shaped["credentials"] = _shape(config_data["credentials"])
        try:
            ZenotiNodeConfig.model_validate(runtime_config_view(shaped, ZenotiNodeConfig))
        except ValueError:
            raise ValueError("Zenoti configuration is invalid; check selected GUIDs, dates and paging") from None
        return super().parse_config(shaped)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data)
            shaped = dict(config_data)
            if config_data.get("credentials") is not None:
                shaped["credentials"] = _shape(config_data["credentials"])
            ZenotiNodeConfig.model_validate(runtime_config_view(shaped, ZenotiNodeConfig))
        except (ValueError, TypeError):
            return ValidationResult(valid=False, errors=["Zenoti configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await _current_data(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def validate_credential_access(cls, data):
        try:
            data = _shape(data)
            await _page(data, {}, "/v1/centers", "center", {"Page": 1, "Size": 1})
            return True, None
        except ZenotiAPIError as exc:
            return (False if exc.authority_rejected else None), str(exc)
        except ValueError:
            return False, "Zenoti credential is invalid or expired"

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, ZenotiNodeConfig) or self.config.credentials is None:
            raise ValueError("Zenoti requires its explicit native credential and configuration")
        cfg = self.config.config
        if cfg.operation in WRITE_OPS and not cfg.confirm_update:
            raise ValueError("Confirm the scoped guest CRM update")
        context = {"_approval_pool": (self.node_data or {}).get("_approval_pool"), "_credential_id": (self.node_data or {}).get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        data = await _current_data(self.config.credentials.model_dump(), **_authority(context))
        result = await self._operation(cfg, data, context)
        return {"status": "success", "operation": cfg.operation, "data": _redact(result, _secret(data))}

    async def _operation(self, cfg, data, context):
        op = cfg.operation
        if op in ("check_api_access", "list_centers"):
            params = {"Page": 1, "Size": 1} if op == "check_api_access" else {"Page": cfg.page, "Size": cfg.size}
            page = await _page(data, context, "/v1/centers", "center", params)
            if op == "check_api_access":
                return {"protected_read_completed": True, "proves": "reachability", "account_identity_verified": False, "write_permission_verified": False, "returned_count": page["returned_count"]}
            return page
        if op in ("get_organization_metadata", "get_guest_configuration"):
            section = "general" if op == "get_organization_metadata" else "guest"
            raw = await _request(data, context, "/v1/organizations/settings/" + section)
            fields = {"org_name": str, "enable_classes": bool} if section == "general" else {"is_mobile_number_mandatory": bool, "search_guest_across_centers": bool, "auto_generate_code": bool, "guest_form_type": int}
            # Settings may be returned as a section object or as an all-section envelope.
            section_data = raw.get(section, raw)
            if not isinstance(section_data, dict):
                raise ZenotiAPIError("Zenoti selected organization section metadata is unverified")
            projected = _pick(section_data, fields)
            if not projected:
                raise ZenotiAPIError("Zenoti selected organization section metadata is unverified")
            return {"section": section, "metadata": projected, "account_identity_verified": False}
        if op == "get_center":
            return await _center(data, context, cfg.center_id)
        if op == "get_service":
            return {"request_center_id": cfg.center_id, "service": _record(await _request(data, context, "/v1/Centers/" + cfg.center_id + "/services/" + cfg.service_id), "service", wanted=cfg.service_id)}
        if op in ("list_center_services", "list_center_employees", "list_center_guests"):
            route, kind = {"list_center_services": ("/v1/Centers/" + cfg.center_id + "/services", "service"), "list_center_employees": ("/v1/centers/" + cfg.center_id + "/employees", "employee"), "list_center_guests": ("/v1/guests", "guest")}[op]
            params = {"page": cfg.page, "size": cfg.size}
            if kind == "guest":
                params["center_id"] = cfg.center_id
                if cfg.last_updated:
                    params["last_updated"] = cfg.last_updated
            return {"request_center_id": cfg.center_id, **await _page(data, context, route, kind, params, center=cfg.center_id if kind == "guest" else None)}
        if op == "get_center_employee":
            seen = set()
            for page_number in range(1, 41):
                page = await _page(data, context, "/v1/centers/" + cfg.center_id + "/employees", "employee", {"page": page_number, "size": 25})
                ids = {r["id"] for r in page["results"]}
                if ids & seen:
                    raise ZenotiAPIError("Zenoti employee traversal repeats IDs")
                seen.update(ids)
                found = next((r for r in page["results"] if r["id"] == cfg.employee_id), None)
                if found:
                    return {"request_center_id": cfg.center_id, "employee": found}
                if not page["pagination_verified"]:
                    raise ValueError("Zenoti employee continuation is unverified; no absence claim is possible")
                if page["next_page"] is None:
                    raise ValueError("Selected employee was not returned in the verified center traversal")
            raise ValueError("Zenoti employee lookup exceeded the local 1,000-record bound")
        raw = await _guest(data, context, cfg.guest_id, cfg.center_id)
        if op == "get_guest":
            return _record(raw, "guest", wanted=cfg.guest_id, center=cfg.center_id)
        if op == "list_guest_appointments":
            # The documented endpoint returns all appointments of the guest,
            # including visits outside the guest's home center. Each returned
            # center ID is still validated and exposed as metadata.
            return {"request_guest_id": cfg.guest_id, "request_center_id": cfg.center_id, **await _page(data, context, "/v1/guests/" + cfg.guest_id + "/appointments", "appointment", {"page": cfg.page, "size": cfg.size, "start_date": cfg.start_date, "end_date": cfg.end_date}, center=None)}
        if op == "update_guest_crm_metadata":
            body = _profile(raw)
            if cfg.preferred_service_id:
                _record(await _request(data, context, "/v1/Centers/" + cfg.center_id + "/services/" + cfg.preferred_service_id), "service", wanted=cfg.preferred_service_id)
                body["preferred_service_id"] = cfg.preferred_service_id
            if cfg.guest_code is not None:
                body["code"] = cfg.guest_code
            response = await _request(data, context, "/v1/guests/" + cfg.guest_id, body=body)
            try:
                result = _record(response, "guest", wanted=cfg.guest_id, center=cfg.center_id)
                if cfg.guest_code is not None and result.get("code") != cfg.guest_code or cfg.preferred_service_id and result.get("preferred_service_id") != cfg.preferred_service_id:
                    raise ZenotiAPIError("Zenoti returned CRM metadata does not match the requested changes")
            except ZenotiAPIError:
                raise ZenotiAPIError("Zenoti CRM update response is unverified. Write outcome is unverified; read the owned guest before retrying.") from None
            return {"accepted": True, "guest": result, "returned_changes_verified": True, "independent_readback_verified": False, "notification_behavior_verified": False}
        raise ValueError("Unsupported Zenoti native operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("center_id", "service_id", "employee_id", "guest_id"):
            return {"options": [], "next_page_token": None}
        context = _context(credential_data, context or {})
        query = (search or "").strip()
        if len(query) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in query):
            raise ValueError("Use a bounded Zenoti ID picker search")
        center = _id(context.get("center_id")) if field_name != "center_id" else None
        data = await _current_data(credential_data, **_authority(context))
        binding = hashlib.sha256(json.dumps([field_name, center, query, context.get("_credential_id"), context.get("_user_id"), context.get("_organization_id"), context.get("_workflow_id"), _binding(data)], separators=(",", ":")).encode()).hexdigest()
        page_number, seen = 1, []
        if page_token:
            try:
                if not isinstance(page_token, str) or len(page_token) > 60000:
                    raise ValueError()
                saved = json.loads(base64.urlsafe_b64decode(page_token + "=" * (-len(page_token) % 4)))
                if not isinstance(saved, dict) or set(saved) != {"page", "binding", "seen"} or saved["binding"] != binding or type(saved["page"]) is not int or not 2 <= saved["page"] <= 40 or not isinstance(saved["seen"], list) or len(saved["seen"]) > 1000:
                    raise ValueError()
                page_number, seen = saved["page"], [_id(v) for v in saved["seen"]]
                if len(set(seen)) != len(seen):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                raise ValueError("Zenoti continuation belongs to another actor, current credential or center scope") from None
        if center:
            await _center(data, context, center)
        route, kind = {"center_id": ("/v1/centers", "center"), "service_id": ("/v1/Centers/" + (center or "") + "/services", "service"), "employee_id": ("/v1/centers/" + (center or "") + "/employees", "employee"), "guest_id": ("/v1/guests", "guest")}[field_name]
        params = {"Page": page_number, "Size": 25} if kind == "center" else {"page": page_number, "size": 25, **({"center_id": center} if kind == "guest" else {})}
        page = await _page(data, context, route, kind, params, center=center if kind == "guest" else None)
        if not page["pagination_verified"]:
            raise ValueError("Zenoti picker continuation is unverified because page_info is missing; use an exact owned ID")
        ids = [r["id"] for r in page["results"]]
        if set(ids) & set(seen):
            raise ZenotiAPIError("Zenoti picker traversal repeats IDs")
        next_page = page["next_page"]
        if next_page and page_number == 40:
            raise ValueError("Zenoti picker exceeded the local 1,000-record bound; use an exact owned ID")
        label = kind.title()
        options = [{"value": row["id"], "label": label + " " + row["id"]} for row in page["results"] if not query or query.casefold() in (label + " " + row["id"]).casefold()]
        token = base64.urlsafe_b64encode(json.dumps({"page": next_page, "binding": binding, "seen": seen + ids}, separators=(",", ":")).encode()).decode().rstrip("=") if next_page else None
        return {"options": options, "next_page_token": token}
