"""SimplyBook.me company/public and user/admin HTTPS JSON-RPC operations.

Official examples and library use JSON-RPC 2.0 with positional parameters.
Login tokens are ephemeral: no undocumented expiry, refresh or OAuth contract.
"""
from __future__ import annotations

import base64
from contextvars import ContextVar
from datetime import date, datetime
import hashlib
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ORIGIN = "https://user-api.simplybook.me"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
FAMILIES = ("simplybook_company_api_key", "simplybook_admin_user", "simplybook_company_token", "simplybook_admin_token")
ADMIN = ("simplybook_admin_user", "simplybook_admin_token")
OPS = ("check_connection", "list_services", "get_service", "list_providers", "get_provider", "get_timeframe", "get_first_working_day", "get_work_calendar", "get_available_start_times", "get_available_providers", "get_current_user", "list_clients", "get_client", "create_client", "update_client_name", "list_bookings", "get_booking", "list_booking_statuses", "get_booking_status", "update_booking_comment")
ADMIN_OPS = frozenset(OPS[10:])
_PRIVATE = ContextVar("simplybook_private_transport", default=False)


def plain(value, maximum=256, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]", value) or not empty and not value.strip():
        raise ValueError("SimplyBook.me requires bounded plain text")
    return value.strip()


def identifier(value):
    # Public UI and picker values remain strings; only RPC positional IDs are ints.
    if type(value) is int: value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 9223372036854775807:
        raise ValueError("Use the positive SimplyBook.me record ID")
    return value


def secret(value):
    try:
        value = clean_secret(plain(value, 8192), field_name="SimplyBook.me secret")
        if re.search(r"[\r\n]", value): raise ValueError()
        return value
    except ValueError: raise ValueError("Paste the genuine SimplyBook.me key, password or token only") from None


def token_value(value):
    value = secret(value)
    if not re.fullmatch(r"[\x21-\x7e]+", value): raise ValueError("Paste the SimplyBook.me token only, without header text or whitespace")
    return value


class _Company(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    company_login: str = Field(..., title="Company Login", description="Existing company's login, not its booking URL.")

    @field_validator("company_login", mode="before")
    @classmethod
    def company(cls, value):
        value = plain(value, 100)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value): raise ValueError("Use the company login only, not a URL")
        return value


class SimplyBookCompanyAPIKeyCredential(_Company):
    model_config = ConfigDict(title="simplybook.me Company API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://simplybook.me/en/api/developer-api/tab/doc_api",
        "x-credential-instructions": "Use the existing company's API custom feature key. Company tokens access the public booking catalogue and availability, not the admin API. API feature entitlement is account controlled. HTTPS login is repeated for each operation; keys are never sent over plaintext HTTP.",
    })
    credential_type: Literal["simplybook_company_api_key"] = Field(FAMILIES[0], json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Company API Key", json_schema_extra={"ui:widget": "password"})
    _key = field_validator("api_key", mode="before")(secret)


class SimplyBookAdminUserCredential(_Company):
    model_config = ConfigDict(title="simplybook.me Admin User", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://simplybook.me/en/api/developer-api/tab/doc_api",
        "x-credential-instructions": "Use your existing admin login and an API User Key from Settings > API User Keys (recommended), or its genuine password. Password login may require 2FA, which this node does not bypass. The admin token is minted over HTTPS for each operation; there is no OAuth callback or refresh token. Management operations require the returned admin role.",
    })
    credential_type: Literal["simplybook_admin_user"] = Field(FAMILIES[1], json_schema_extra={"ui:hidden": True})
    user_login: str = Field(..., title="Admin User Login")
    user_password: str = Field(..., title="API User Key or Password", json_schema_extra={"ui:widget": "password"})
    _login = field_validator("user_login", mode="before")(lambda value: plain(value))
    _password = field_validator("user_password", mode="before")(secret)


class SimplyBookCompanyTokenCredential(_Company):
    model_config = ConfigDict(title="simplybook.me Company Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://simplybook.me/en/api/developer-api/tab/doc_api",
        "x-credential-instructions": "Supply a genuine getToken result for this company. It is sent only as X-Token to the fixed HTTPS public service. Its lifetime is not inferred and this manual token cannot be renewed automatically.",
    })
    credential_type: Literal["simplybook_company_token"] = Field(FAMILIES[2], json_schema_extra={"ui:hidden": True})
    token: str = Field(..., title="Company API Token", json_schema_extra={"ui:widget": "password"})
    _token = field_validator("token", mode="before")(token_value)


class SimplyBookAdminTokenCredential(_Company):
    model_config = ConfigDict(title="simplybook.me Admin Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://simplybook.me/en/api/developer-api/tab/doc_api",
        "x-credential-instructions": "Supply a genuine getUserToken result for this company. It is sent only as X-User-Token to the fixed HTTPS admin service. Management requires the current admin role. This manual token is not automatically renewed.",
    })
    credential_type: Literal["simplybook_admin_token"] = Field(FAMILIES[3], json_schema_extra={"ui:hidden": True})
    user_token: str = Field(..., title="Admin User Token", json_schema_extra={"ui:widget": "password"})
    _token = field_validator("user_token", mode="before")(token_value)


SimplyBookCredential = Union[SimplyBookCompanyAPIKeyCredential, SimplyBookAdminUserCredential, SimplyBookCompanyTokenCredential, SimplyBookAdminTokenCredential]
MODELS = dict(zip(FAMILIES, (SimplyBookCompanyAPIKeyCredential, SimplyBookAdminUserCredential, SimplyBookCompanyTokenCredential, SimplyBookAdminTokenCredential)))


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") not in MODELS or data.get("revoked_at") is not None:
        raise ValueError("Connect a current native SimplyBook.me credential")
    try:
        model = MODELS[data["credential_type"]]
        # Family separation rejects hidden keys from another auth mode.
        foreign = {"api_key", "user_login", "user_password", "token", "user_token"} - set(model.model_fields)
        if any(key in data and data[key] not in (None, "") for key in foreign): raise ValueError()
        return model.model_validate(data).model_dump()
    except Exception: raise ValueError("SimplyBook.me credential shape or auth family is invalid") from None


def resource(kind, *, parent=None):
    extra = {"x-resource-type": "simplybook_"+kind, "x-dynamic-options": {"field_name": kind+"_id", "searchable": True}}
    if parent: extra["x-dynamic-options"]["depends_on"] = parent
    return extra


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="after")
    def dates(self):
        start, end = getattr(self, "date_from", None), getattr(self, "date_to", None)
        if start is not None:
            try:
                a, b = date.fromisoformat(start), date.fromisoformat(end)
                if len(start) != 10 or len(end) != 10 or not 0 <= (b-a).days <= 31: raise ValueError()
            except (ValueError, TypeError): raise ValueError("Use a YYYY-MM-DD date window of at most 32 calendar dates") from None
        return self

    @field_validator("service_id", "provider_id", "client_id", "booking_id", mode="before", check_fields=False)
    @classmethod
    def shape(cls, value, info):
        if info.field_name.endswith("_id") and value is not None: return identifier(value)
        return value


class CheckConnection(_Operation):
    operation: Literal["check_connection"] = Field("check_connection", title="Check API Read Access")


class ListServices(_Operation):
    operation: Literal["list_services"] = Field("list_services", title="List Services")


class GetService(_Operation):
    operation: Literal["get_service"] = Field("get_service", title="Get Service")
    service_id: str = Field(..., title="Service", json_schema_extra=resource("service"))


class ListProviders(_Operation):
    operation: Literal["list_providers"] = Field("list_providers", title="List Providers")
    service_id: Optional[str] = Field(None, title="Service (optional)", json_schema_extra=resource("service"))


class GetProvider(_Operation):
    operation: Literal["get_provider"] = Field("get_provider", title="Get Provider")
    service_id: str = Field(..., title="Service", json_schema_extra=resource("service"))
    provider_id: str = Field(..., title="Provider", json_schema_extra=resource("provider", parent="service_id"))


class GetTimeframe(_Operation):
    operation: Literal["get_timeframe"] = Field("get_timeframe", title="Get Scheduling Timeframe")


class _ServiceProvider(_Operation):
    service_id: str = Field(..., title="Service", json_schema_extra=resource("service"))
    provider_id: str = Field(..., title="Provider", json_schema_extra=resource("provider", parent="service_id"))


class GetFirstWorkingDay(_ServiceProvider):
    operation: Literal["get_first_working_day"] = Field("get_first_working_day", title="Get First Working Day")


class GetWorkCalendar(_ServiceProvider):
    operation: Literal["get_work_calendar"] = Field("get_work_calendar", title="Get Work Calendar")
    year: int = Field(..., strict=True, ge=2000, le=2100, title="Year")
    month: int = Field(..., strict=True, ge=1, le=12, title="Month")


class _Availability(_ServiceProvider):
    date_from: str = Field(..., title="Start Date", description="Company-local YYYY-MM-DD; maximum 32 calendar dates.")
    date_to: str = Field(..., title="End Date")
    count: int = Field(1, strict=True, ge=1, le=100, title="Participants")


class GetAvailableStartTimes(_Availability):
    operation: Literal["get_available_start_times"] = Field("get_available_start_times", title="Get Available Start Times")


class GetAvailableProviders(_ServiceProvider):
    operation: Literal["get_available_providers"] = Field("get_available_providers", title="Get Available Providers")
    date_time: str = Field(..., title="Company Local Date and Time", description="YYYY-MM-DD HH:mm:ss")
    count: int = Field(1, strict=True, ge=1, le=100, title="Participants")
    @field_validator("date_time", mode="before")
    @classmethod
    def when(cls, value):
        try:
            if not isinstance(value, str) or len(value) != 19 or datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S") != value: raise ValueError()
        except ValueError: raise ValueError("Use company-local YYYY-MM-DD HH:mm:ss") from None
        return value


class GetCurrentUser(_Operation):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current Admin User")


class ListClients(_Operation):
    operation: Literal["list_clients"] = Field("list_clients", title="Search Clients")
    search: str = Field("", max_length=100, title="Name, Email or Phone Search")
    limit: int = Field(25, strict=True, ge=1, le=100, title="Maximum Results", description="Provider limit; no provider cursor or offset is documented.")
    _search = field_validator("search", mode="before")(lambda value: plain(value, 100, empty=True))


class GetClient(_Operation):
    operation: Literal["get_client"] = Field("get_client", title="Get Client Name Metadata")
    client_id: str = Field(..., title="Client", json_schema_extra=resource("client"))


class CreateClient(_Operation):
    operation: Literal["create_client"] = Field("create_client", title="Create Client Without Welcome Email")
    name: str = Field(..., max_length=200, title="Client Name")
    email: Optional[str] = Field(None, max_length=254, title="Email (if required by company)")
    phone: Optional[str] = Field(None, max_length=64, title="Phone (if required by company)")
    _name = field_validator("name", mode="before")(lambda value: plain(value, 200))
    @field_validator("email", "phone", mode="before")
    @classmethod
    def contact(cls, value): return None if value in (None, "") else plain(value, 254)


class UpdateClientName(_Operation):
    operation: Literal["update_client_name"] = Field("update_client_name", title="Update Client Name")
    client_id: str = Field(..., title="Client", json_schema_extra=resource("client"))
    name: str = Field(..., max_length=200, title="Client Name")
    _name = field_validator("name", mode="before")(lambda value: plain(value, 200))


class ListBookings(_Operation):
    operation: Literal["list_bookings"] = Field("list_bookings", title="List Booking Metadata")
    date_from: str = Field(..., title="Start Date", description="Company-local YYYY-MM-DD; maximum 32 calendar dates.")
    date_to: str = Field(..., title="End Date")
    service_id: Optional[str] = Field(None, title="Service (optional)", json_schema_extra=resource("service"))
    provider_id: Optional[str] = Field(None, title="Provider (optional)", json_schema_extra=resource("provider", parent="service_id"))
    client_id: Optional[str] = Field(None, title="Client (optional)", json_schema_extra=resource("client"))
    booking_type: Literal["all", "cancelled", "non_cancelled"] = Field("all", title="Booking State")
    limit: int = Field(25, strict=True, ge=1, le=100, title="Maximum Detail Readbacks", description="Local cap, not a provider offset/page. Each selected booking is read back for its documented metadata and parent witness.")
    @model_validator(mode="after")
    def parent(self):
        if self.provider_id and not self.service_id: raise ValueError("Select the service before its provider")
        return self


class GetBooking(_Operation):
    operation: Literal["get_booking"] = Field("get_booking", title="Get Booking Metadata")
    booking_id: str = Field(..., title="Existing Booking ID", json_schema_extra={"x-resource-type": "simplybook_booking"})


class ListBookingStatuses(_Operation):
    operation: Literal["list_booking_statuses"] = Field("list_booking_statuses", title="List Booking Statuses")


class GetBookingStatus(GetBooking):
    operation: Literal["get_booking_status"] = Field("get_booking_status", title="Get Existing Booking Status")


class UpdateBookingComment(GetBooking):
    operation: Literal["update_booking_comment"] = Field("update_booking_comment", title="Update Existing Booking Comment")
    comment: str = Field(..., max_length=1000, title="Comment", description="Ordinary admin record change; account automations may observe changes. No quiet guarantee.")
    _comment = field_validator("comment", mode="before")(lambda value: plain(value, 1000, empty=True))


SimplyBookOperation = Annotated[Union[CheckConnection, ListServices, GetService, ListProviders, GetProvider, GetTimeframe, GetFirstWorkingDay, GetWorkCalendar, GetAvailableStartTimes, GetAvailableProviders, GetCurrentUser, ListClients, GetClient, CreateClient, UpdateClientName, ListBookings, GetBooking, ListBookingStatuses, GetBookingStatus, UpdateBookingComment], Discriminator("operation")]


class SimplyBookNodeConfig(NodeConfig[SimplyBookOperation, SimplyBookCredential]):
    pass


async def current_credential(data):
    # Stored credentials are resolved by staging's shared access/approval loader.
    # Native login tokens are obtained per operation and never persisted.
    return credential(data)


class _Privacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get() and (record.name in {"httpx", "httpcore"} or record.name.startswith(("httpx.", "httpcore."))):
            record.msg, record.args = "SimplyBook.me private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _Privacy()
def _install_privacy():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names.update(n for n in logging.Logger.manager.loggerDict if n.startswith(("httpx.", "httpcore.")))
    for name in names: logging.getLogger(name).addFilter(_FILTER)
    for handler in logging.getLogger().handlers: handler.addFilter(_FILTER)


class SimplyBookHTTPError(RuntimeError):
    def __init__(self, status):
        self.status_code = status
        super().__init__(f"SimplyBook.me HTTPS request did not complete (HTTP {status}); verify any write before retrying")


class SimplyBookRPCError(RuntimeError):
    def __init__(self, code):
        self.rpc_code = code
        # Never interpolate provider message/data: both can contain input secrets.
        super().__init__("SimplyBook.me JSON-RPC operation was refused; verify feature access, role and inputs")


def _json(content):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise ValueError()
            out[k] = v
        return out
    try: return json.loads(content, object_pairs_hook=pairs, parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()))
    except Exception: raise RuntimeError("SimplyBook.me returned invalid JSON") from None


async def rpc(data, method, params, *, login=False, token=None):
    shaped = await current_credential(data)
    admin = shaped["credential_type"] in ADMIN
    path = "/login" if login else "/admin/" if admin else "/"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if not login:
        headers["X-Company-Login"] = shaped["company_login"]
        headers["X-User-Token" if admin else "X-Token"] = token_value(token)
    # The official client uses numeric IDs; responses may echo decimal strings.
    request_id = uuid4().int % 9007199254740991 + 1
    body = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    async def exact(req):
        assert_exact_url_origin(str(req.url), ORIGIN)
        if req.url.path != path or req.url.query: raise ValueError("SimplyBook.me transport path changed")
    content = bytearray()
    marker = _PRIVATE.set(True)
    _install_privacy()
    try:
        async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False, event_hooks={"request": [exact]}) as client:
            async with client.stream("POST", ORIGIN+path, json=body, headers=headers) as response:
                if response.status_code != 200: raise SimplyBookHTTPError(response.status_code)
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > MAX_BYTES: raise RuntimeError("SimplyBook.me response exceeded its local byte bound")
    except SimplyBookHTTPError: raise
    except Exception: raise RuntimeError("SimplyBook.me transport could not complete; verify any write before retrying") from None
    finally: _PRIVATE.reset(marker)
    await current_credential(data)
    payload = _json(content)
    echoed = payload.get("id") if isinstance(payload, dict) else None
    matching_id = type(echoed) is int and echoed == request_id or isinstance(echoed, str) and echoed == str(request_id)
    if not isinstance(payload, dict) or not matching_id or payload.get("jsonrpc") != "2.0" or "result" not in payload and "error" not in payload:
        raise RuntimeError("SimplyBook.me returned an invalid JSON-RPC response envelope")
    error = payload.get("error")
    if error is not None:
        if not isinstance(error, dict) or type(error.get("code")) is not int: raise RuntimeError("SimplyBook.me returned an invalid RPC refusal")
        raise SimplyBookRPCError(error["code"])
    if "result" not in payload: raise RuntimeError("SimplyBook.me RPC result was missing")
    return payload["result"]


async def token_for(data):
    shaped = await current_credential(data)
    family = shaped["credential_type"]
    if family == FAMILIES[0]: result = await rpc(data, "getToken", [shaped["company_login"], shaped["api_key"]], login=True)
    elif family == FAMILIES[1]: result = await rpc(data, "getUserToken", [shaped["company_login"], shaped["user_login"], shaped["user_password"]], login=True)
    else: return shaped["token" if family == FAMILIES[2] else "user_token"]
    try: return token_value(result)
    except ValueError: raise RuntimeError("SimplyBook.me did not return a genuine token string") from None


def rows(result):
    if isinstance(result, dict): values = list(result.values())
    elif isinstance(result, list): values = result
    else: raise RuntimeError("SimplyBook.me returned an invalid native list")
    if len(values) > MAX_ROWS or any(not isinstance(row, dict) for row in values): raise RuntimeError("SimplyBook.me list exceeded its local shape or row bound")
    return values


FIELDS = {
    "service": ("id", "name", "duration", "is_active", "is_public"),
    "provider": ("id", "name", "is_active", "is_visible", "qty"),
    "client": ("id", "name"),
    "booking": ("id", "event_id", "unit_id", "client_id", "start_date_time", "end_date_time", "record_date", "is_confirmed"),
    "status": ("id", "name"),
    "user": ("id", "group", "is_blocked", "unit_group_id"),
}


def project(row, kind):
    if not isinstance(row, dict): raise RuntimeError("SimplyBook.me returned an invalid native record")
    out = {}
    try:
        out["id"] = identifier(row.get("id"))
        for key in FIELDS[kind][1:]:
            if key not in row: continue
            value = row[key]
            if value is None: out[key] = None
            elif key.endswith("_id"): out[key] = identifier(value)
            elif key in {"start_date_time", "end_date_time", "record_date"}:
                if not isinstance(value, str) or len(value) != 19 or datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S") != value: raise ValueError()
                out[key] = value
            elif key in {"name", "group"}: out[key] = plain(value, 300, empty=True)
            elif type(value) is bool or type(value) is int or isinstance(value, str) and re.fullmatch(r"[0-9]{1,8}", value): out[key] = value
            else: raise ValueError()
    except ValueError: raise RuntimeError("SimplyBook.me returned invalid projected metadata") from None
    return out


async def catalogue(data, token, kind):
    raw = rows(await rpc(data, "getEventList" if kind == "service" else "getUnitList", [], token=token))
    projected = [project(row, kind) for row in raw]
    if len({r["id"] for r in projected}) != len(projected): raise RuntimeError("SimplyBook.me returned duplicate catalogue IDs")
    return raw, projected


async def selected_pair(data, token, service_id, provider_id=None):
    raw, services = await catalogue(data, token, "service")
    selected = next((r for r in raw if identifier(r.get("id")) == identifier(service_id)), None)
    if selected is None: raise ValueError("Selected SimplyBook.me service is not in the current company catalogue")
    _raw, providers = await catalogue(data, token, "provider")
    unit_map = selected.get("unit_map")
    try:
        if unit_map is None or unit_map == [] or unit_map == {}: allowed = {r["id"] for r in providers}
        elif isinstance(unit_map, list): allowed = {identifier(value) for value in unit_map}
        else: raise ValueError()
    except ValueError: raise RuntimeError("SimplyBook.me returned an invalid service/provider map") from None
    providers = [r for r in providers if r["id"] in allowed]
    if provider_id is not None and identifier(provider_id) not in {r["id"] for r in providers}: raise ValueError("Selected provider is not available for this company's service")
    return providers


async def admin_identity(data, token, *, require_admin=True):
    if credential(data)["credential_type"] not in ADMIN: raise ValueError("Use a native SimplyBook.me admin credential for this operation")
    row = project(await rpc(data, "getCurrentUserDetails", [], token=token), "user")
    if row.get("is_blocked") not in (0, "0", False): raise ValueError("SimplyBook.me current admin user is blocked or its status is unknown")
    if require_admin and row.get("group") != "admin": raise ValueError("This SimplyBook.me management operation requires the current administrator role")
    return row


async def get_client(data, token, rid):
    _raw, row = await client_record(data, token, rid)
    return row


async def client_record(data, token, rid):
    raw = await rpc(data, "getClientInfo", [int(identifier(rid))], token=token)
    row = project(raw, "client")
    if row["id"] != identifier(rid): raise RuntimeError("SimplyBook.me client read returned another ID")
    return raw, row


async def get_booking(data, token, rid):
    row = project(await rpc(data, "getBookingDetails", [int(identifier(rid))], token=token), "booking")
    if row["id"] != identifier(rid): raise RuntimeError("SimplyBook.me booking read returned another ID")
    return row


def calendar(result, config, *, slots=False):
    if not isinstance(result, dict) or len(result) > 32: raise RuntimeError("SimplyBook.me returned an invalid bounded calendar")
    out = {}
    try:
        for day, value in result.items():
            parsed = date.fromisoformat(day)
            if len(day) != 10: raise ValueError()
            if slots:
                if not config["date_from"] <= day <= config["date_to"] or not isinstance(value, list) or len(value) > 288: raise ValueError()
                if any(not isinstance(t, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?", t) for t in value): raise ValueError()
                out[day] = value
            else:
                if parsed.year != config["year"] or parsed.month != config["month"] or not isinstance(value, dict): raise ValueError()
                entry = {}
                for key in ("from", "to"):
                    v = value.get(key)
                    if not isinstance(v, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]|24:00:00", v) or key == "from" and v == "24:00:00": raise ValueError()
                    entry[key] = v
                if value.get("is_day_off") not in (0, 1, "0", "1", False, True): raise ValueError()
                entry["is_day_off"] = value["is_day_off"]
                out[day] = entry
    except (ValueError, TypeError): raise RuntimeError("SimplyBook.me calendar date or time metadata was invalid") from None
    return out


async def records(data, config):
    op = config["operation"]
    if op not in OPS: raise ValueError("Unsupported native SimplyBook.me operation")
    shaped = await current_credential(data)
    if op in ADMIN_OPS and shaped["credential_type"] not in ADMIN: raise ValueError("This operation requires a native SimplyBook.me admin credential")
    token = await token_for(data)
    identity = await admin_identity(data, token, require_admin=op != "get_current_user") if op in ADMIN_OPS else None
    if op == "check_connection":
        await catalogue(data, token, "service")
        return {"reachable": True, "identity_verified": False, "proves": "reachability", "message": "Company service read accepted; admin roles, write access and feature entitlement are not established."}
    if op in {"list_services", "get_service", "list_providers", "get_provider"}:
        kind = "service" if op in {"list_services", "get_service"} else "provider"
        if kind == "provider" and config.get("service_id"):
            projected = await selected_pair(data, token, config["service_id"], config.get("provider_id"))
        else: _raw, projected = await catalogue(data, token, kind)
        if op.startswith("get_"):
            row = next((r for r in projected if r["id"] == config[kind+"_id"]), None)
            if row is None: raise ValueError("Selected record is absent from the current company catalogue")
            return {"record": row}
        return {"records": projected, "pagination": "bounded_complete_catalogue", "next_page_token": None}
    if op == "get_timeframe":
        value = await rpc(data, "getTimeframe", [], token=token)
        if type(value) is not int or value not in (5, 10, 15, 20, 30, 60): raise RuntimeError("SimplyBook.me returned an invalid scheduling timeframe")
        return {"minutes": value}
    if op in {"get_first_working_day", "get_work_calendar", "get_available_start_times", "get_available_providers"}:
        await selected_pair(data, token, config["service_id"], config["provider_id"])
        sid, pid = int(config["service_id"]), int(config["provider_id"])
        if op == "get_first_working_day":
            value = await rpc(data, "getFirstWorkingDay", [{"unit_group_id": pid, "event_id": sid}], token=token)
            try:
                if not isinstance(value, str) or len(value) != 10: raise ValueError()
                date.fromisoformat(value)
            except ValueError: raise RuntimeError("SimplyBook.me first working date was unavailable or invalid") from None
            return {"date": value}
        if op == "get_work_calendar":
            value = await rpc(data, "getWorkCalendar", [config["year"], config["month"], {"unit_group_id": pid, "event_id": sid}], token=token)
            return {"calendar": calendar(value, config)}
        if op == "get_available_start_times":
            value = await rpc(data, "getStartTimeMatrix", [config["date_from"], config["date_to"], sid, pid, config["count"]], token=token)
            return {"start_times": calendar(value, config, slots=True), "timezone": "company_local"}
        value = await rpc(data, "getAvailableUnits", [sid, config["date_time"], config["count"], pid], token=token)
        try:
            if not isinstance(value, list) or len(value) > MAX_ROWS: raise ValueError()
            ids = [identifier(v) for v in value]
            if len(ids) != len(set(ids)) or any(v != config["provider_id"] for v in ids): raise ValueError()
        except ValueError: raise RuntimeError("SimplyBook.me returned invalid available provider IDs") from None
        return {"provider_ids": ids}
    if op == "get_current_user": return {"record": identity, "identity_verified": True}
    if op == "list_clients":
        value = rows(await rpc(data, "getClientList", [config.get("search", ""), config.get("limit", 25)], token=token))
        if len(value) > config.get("limit", 25): raise RuntimeError("SimplyBook.me client results exceeded the requested bound")
        return {"records": [project(r, "client") for r in value], "next_page_token": None, "pagination": "bounded_search_no_documented_cursor", "may_be_truncated": len(value) == config.get("limit", 25)}
    if op == "get_client": return {"record": await get_client(data, token, config["client_id"])}
    if op in {"create_client", "update_client_name"}:
        if op == "create_client":
            body = {k: config[k] for k in ("name", "email", "phone") if config.get(k) is not None}
            rid = await rpc(data, "addClient", [body, False], token=token)
        else:
            previous, _row = await client_record(data, token, config["client_id"])
            body = {k: previous[k] for k in ("email", "phone", "address1", "address2", "city", "zip", "country_id", "is_email_unsubscribed", "is_sms_unsubscribed") if k in previous}
            for key, value in body.items():
                if value is not None and not (isinstance(value, str) and len(value) <= 500 and not re.search(r"[\x00-\x1f\x7f]", value) or type(value) in (int, bool)):
                    raise RuntimeError("SimplyBook.me client has unsupported metadata; name update was not sent")
            body["name"] = config["name"]
            rid = await rpc(data, "editClient", [int(config["client_id"]), body], token=token)
        try: rid = identifier(rid)
        except ValueError: raise RuntimeError("SimplyBook.me client write did not return a record ID; inspect before retrying") from None
        if op == "update_client_name" and rid != config["client_id"]: raise RuntimeError("SimplyBook.me client write returned another record ID")
        after, row = await client_record(data, token, rid)
        if row.get("name") != config["name"]: raise RuntimeError("SimplyBook.me client name readback did not match; inspect before retrying")
        if op == "update_client_name" and any(after.get(k) != value for k, value in body.items()): raise RuntimeError("SimplyBook.me retained client metadata readback did not match; inspect before retrying")
        return {"record": row, "mutation_completed": True, "readback_verified": True, "welcome_email_requested": False if op == "create_client" else None}
    if op == "list_bookings":
        if config.get("service_id"): await selected_pair(data, token, config["service_id"], config.get("provider_id"))
        if config.get("client_id"): await get_client(data, token, config["client_id"])
        filters = {"date_from": config["date_from"], "date_to": config["date_to"], "booking_type": config["booking_type"], "order": "date_start_asc"}
        for field, key in (("service_id", "event_id"), ("provider_id", "unit_group_id"), ("client_id", "client_id")):
            if config.get(field): filters[key] = int(config[field])
        listed = rows(await rpc(data, "getBookings", [filters], token=token))
        try: ids = [identifier(r.get("id")) for r in listed]
        except ValueError: raise RuntimeError("SimplyBook.me returned invalid booking list IDs") from None
        if len(ids) != len(set(ids)): raise RuntimeError("SimplyBook.me returned duplicate booking IDs")
        limit = config.get("limit", 25)
        value = [await get_booking(data, token, rid) for rid in ids[:limit]]
        for row in value:
            if any(row.get("unit_id" if key == "unit_group_id" else key) != str(filters[key]) for key in ("event_id", "unit_group_id", "client_id") if key in filters): raise RuntimeError("SimplyBook.me booking filter witness did not match")
            started = row.get("start_date_time")
            if not started or not config["date_from"] <= started[:10] <= config["date_to"]: raise RuntimeError("SimplyBook.me booking date-window witness did not match")
        return {"records": value, "next_page_token": None, "pagination": "local_detail_cap_no_documented_cursor", "may_be_truncated": len(ids) > limit}
    if op == "get_booking": return {"record": await get_booking(data, token, config["booking_id"])}
    if op == "list_booking_statuses": return {"records": [project(r, "status") for r in rows(await rpc(data, "getStatuses", [], token=token))], "next_page_token": None}
    if op == "get_booking_status":
        await get_booking(data, token, config["booking_id"])
        result = await rpc(data, "getBookingStatus", [int(config["booking_id"])], token=token)
        return {"record": project(result, "status") if result else None}
    if op == "update_booking_comment":
        row = await get_booking(data, token, config["booking_id"])
        await rpc(data, "setBookingComment", [int(config["booking_id"]), config["comment"]], token=token)
        result = await rpc(data, "getBookingComment", [int(config["booking_id"])], token=token)
        if not isinstance(result, str) or result != config["comment"]: raise RuntimeError("SimplyBook.me booking comment readback did not match; inspect before retrying")
        return {"record": row, "mutation_completed": True, "readback_verified": True, "comment_matches": True}
    raise ValueError("Unsupported native SimplyBook.me operation")


def cursor_scope(data, field, context, search):
    return hashlib.sha256(json.dumps({"company": credential(data)["company_login"], "family": credential(data)["credential_type"], "field": field, "service": (context or {}).get("service_id"), "search": search}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SimplyBookNode(WorkflowNode):
    integration_type = "automation-simplybook"
    credential_provider_labels = {"simplybook": "SimplyBook.me Account"}
    scope_registry = ScopeRegistry(provider="simplybook", enforcement=Enforcement.STRICT, requirements={op: ScopeRequirement(scopes=(), credential_types=ADMIN if op in ADMIN_OPS else FAMILIES) for op in OPS})
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="SimplyBook.me company API", proves="reachability")
    edit_examples = ["List my company's services and providers", "Find availability for a service and provider", "Read booking status", "Update an existing client name"]
    @classmethod
    def get_config_model(cls): return SimplyBookNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Connect a valid native SimplyBook.me credential"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return credential(credential_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            credential(credential_data)
        except ValueError:
            return {"valid": False, "error": "SimplyBook.me credential shape is invalid"}
        try:
            await records(credential_data, {"operation": "check_connection"})
        except SimplyBookHTTPError as error:
            return {"valid": False if error.status_code in (401, 403) else None, "error": str(error)}
        except (SimplyBookRPCError, RuntimeError, ValueError):
            return {"valid": None, "error": "SimplyBook.me read access could not be verified; check feature access and credentials"}
        return {"valid": True, "proves": "reachability", "identity_verified": False}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        kinds = {"service_id": "service", "provider_id": "provider", "client_id": "client"}
        if field_name not in kinds: raise ValueError("Unsupported SimplyBook.me native picker")
        kind = kinds[field_name]
        query = normalize_search(search) or ""
        scope = cursor_scope(credential_data, field_name, context, query)
        offset = 0
        expected_fingerprint = None
        if page_token is not None:
            if kind == "client": raise ValueError("SimplyBook.me client search has no documented paging cursor")
            try:
                if not isinstance(page_token, str) or len(page_token) > 512: raise ValueError()
                value = _json(base64.urlsafe_b64decode(page_token+"="*((-len(page_token))%4)))
                if set(value) != {"scope", "offset", "fingerprint"} or value["scope"] != scope or type(value["offset"]) is not int or not 0 < value["offset"] < MAX_ROWS or not isinstance(value["fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["fingerprint"]): raise ValueError()
                offset = value["offset"]
                expected_fingerprint = value["fingerprint"]
            except Exception: raise ValueError("SimplyBook.me picker cursor does not match the current company, field, service and search") from None
        await current_credential(credential_data)
        if kind == "client": result = await records(credential_data, {"operation": "list_clients", "search": query, "limit": 50})
        elif kind == "provider":
            sid = identifier((context or {}).get("service_id"))
            result = await records(credential_data, {"operation": "list_providers", "service_id": sid})
        else: result = await records(credential_data, {"operation": "list_services"})
        options = filter_options_by_search([{"value": r["id"], "label": r.get("name") or r["id"]} for r in result["records"]], query)
        fingerprint = hashlib.sha256(json.dumps(options, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if expected_fingerprint is not None and expected_fingerprint != fingerprint: raise ValueError("SimplyBook.me catalogue changed; restart picker paging")
        if offset >= len(options) and offset != 0: raise ValueError("SimplyBook.me catalogue changed; restart picker paging")
        next_offset = offset+50
        next_page = None if next_offset >= len(options) or kind == "client" else base64.urlsafe_b64encode(json.dumps({"scope": scope, "offset": next_offset, "fingerprint": fingerprint}, separators=(",", ":")).encode()).decode().rstrip("=")
        return {"options": options[offset:next_offset], "next_page_token": next_page}
    async def execute(self, inputs):
        if not isinstance(self.config, SimplyBookNodeConfig) or self.config.credentials is None: raise ValueError("Connect a native SimplyBook.me credential")
        return await records(self.config.credentials.model_dump(), self.config.config.model_dump())
