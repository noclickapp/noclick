"""Native Bookeo v2 metadata and explicit customer/booking management.

Keys use documented headers, never URL parameters. Booking writes are real
reservations/cancellations, not drafts. No payment or account-key operations.
"""
import base64
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from opentelemetry import propagate
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.core.dynamic_options import load_paginated_options, normalize_search
from utils.credentials import resolve_credential_with_owner_fallback
from utils.outbound_trace_privacy import OutboundTraceProvider
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ORIGIN = "https://api.bookeo.com"
BASE = ORIGIN + "/v2"
FAMILIES = {"bookeo_oauth", "bookeo_api_key", "bookeo_bearer_token"}
MAX_BYTES, MAX_ROWS = 2_000_000, 100
PRIVATE_REQUEST = ContextVar("bookeo_private_http_request", default=None)
_BACKOFF = {}
_HTTPX_FORMAT = 'HTTP Request: %s %s "%s %d %s"'
_EVENT = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\.(?:started|complete|failed)\Z")


class _RequestFilter(logging.Filter):
    def filter(self, record):
        safe = PRIVATE_REQUEST.get()
        if safe is None:
            return True
        method, url = safe
        if record.name == "httpx" and record.msg == _HTTPX_FORMAT and isinstance(record.args, tuple) and len(record.args) == 5 and type(record.args[3]) is int:
            protocol = record.args[2]
            protocol = protocol if isinstance(protocol, str) and re.fullmatch(r"HTTP/(?:1\.[01]|2|3)", protocol) else "HTTP"
            record.msg, record.args = 'HTTP Request: %s %s "%s %d"', (method, url, protocol, record.args[3])
        else:
            event = record.msg.split(" ", 1)[0] if isinstance(record.msg, str) else ""
            record.msg, record.args = event if _EVENT.fullmatch(event) else "Bookeo HTTP transport activity", ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _RequestFilter()


def _install_privacy():
    # Filters stay installed; only the current native request context changes
    # records. Concurrent unrelated HTTP diagnostics keep their normal data.
    names = {"httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(n for n in tuple(logging.Logger.manager.loggerDict) if n.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("Enter a Bookeo identifier, without a URL or path")
    return value


Identifier = Annotated[str, BeforeValidator(_id)]
Text = Annotated[str, Field(min_length=1, max_length=255)]


def _family(raw):
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or ("credential_type" in raw and (not isinstance(raw["credential_type"], str) or raw["credential_type"] not in FAMILIES)):
        raise ValueError("Connect a native Bookeo credential")
    return raw


class BookeoAPIKeyCredential(BaseModel):
    credential_type: Literal["bookeo_api_key"] = Field("bookeo_api_key", json_schema_extra={"ui:hidden": True})
    secret_key: str = Field(..., min_length=1, max_length=4096, title="Application Secret Key", json_schema_extra={"ui:widget": "password"})
    api_key: str = Field(..., min_length=1, max_length=4096, title="Account API Key", json_schema_extra={"ui:widget": "password"})
    expected_account_id: Optional[Identifier] = Field(None, title="Expected Account ID", description="Optional stable business account ID, verified against Bookeo before every operation.")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"title": "Bookeo API Key", "x-credential-url": "https://www.bookeo.com/api/setup/"})

    @field_validator("secret_key", "api_key")
    @classmethod
    def header_value(cls, value):
        if value != value.strip() or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter a valid Bookeo key")
        return value


class BookeoBearerTokenCredential(BaseModel):
    credential_type: Literal["bookeo_bearer_token"] = Field("bookeo_bearer_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Supplied OAuth Access Token", description="Already issued Bookeo Bearer token. No automatic OAuth registration or refresh.", json_schema_extra={"ui:widget": "password"})
    expires_at: datetime = Field(..., title="Token Expiry", description="Actual finite expiry supplied by your application. Reconnect when expired.")
    expected_account_id: Optional[Identifier] = Field(None, title="Expected Account ID")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"title": "Bookeo Access Token", "x-credential-url": "https://www.bookeo.com/api/setup/"})

    @field_validator("access_token")
    @classmethod
    def header_value(cls, value):
        return BookeoAPIKeyCredential.header_value(value)

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Supply a token expiry with its timezone")
        return value


from nodes.scopes.bookeo import BOOKEO_SCOPES


class BookeoOAuthCredential(BaseModel):
    credential_type: Literal["bookeo_oauth"] = Field("bookeo_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = None
    scope: str | None = None
    token_type: str = "Bearer"
    name: str | None = None
    expected_account_id: Optional[Identifier] = None
    model_config = ConfigDict(hide_input_in_errors=True, json_schema_extra={
        "title": "Bookeo OAuth", "x-credential-type": "oauth", "x-oauth-provider": "bookeo",
        "x-oauth-scopes": sorted(BOOKEO_SCOPES.declared_scopes()),
        "x-credential-url": "https://www.bookeo.com/api/setup/",
    })

    @field_validator("access_token", "refresh_token")
    @classmethod
    def header_value(cls, value):
        return BookeoAPIKeyCredential.header_value(value) if value is not None else None


Credentials = Union[BookeoOAuthCredential, BookeoAPIKeyCredential, BookeoBearerTokenCredential]


def _credential(raw):
    raw = _family(raw)
    try:
        credential = TypeAdapter(Credentials).validate_python({k: v for k, v in raw.items() if k not in ("token_version", "updated_at")})
        if isinstance(credential, BookeoBearerTokenCredential) and credential.expires_at <= datetime.now(timezone.utc):
            raise ValueError
        return credential
    except Exception:
        raise ValueError("Bookeo credential is invalid or expired; reconnect") from None


def _op(value, title, group):
    return Field(value, title=title, json_schema_extra={"x-operation-group": group})


def _selector(name, title, required=True):
    return Field(... if required else None, title=title, json_schema_extra={"ui:widget": "select", "ui:options": {"loadOptions": True, "dependsOn": []}, "x-resource-type": "bookeo_" + name})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetBusiness(Settings):
    operation: Literal["get_business"] = _op("get_business", "Get Business Account", "Account")


class GetKeyPermissions(Settings):
    operation: Literal["get_key_permissions"] = _op("get_key_permissions", "Get API Key Permissions", "Account")


class Page(Settings):
    page_token: Optional[str] = Field(None, max_length=12000, title="Continuation Token", json_schema_extra={"ui:hidden": True})
    items_per_page: int = Field(50, ge=1, le=100, title="Items Per Page")


class ListProducts(Page):
    operation: Literal["list_products"] = _op("list_products", "List Product Metadata", "Settings")
    product_type: Optional[Literal["fixed", "fixedCourse", "flexibleTime"]] = Field(None, title="Product Type")


class ListResources(Page):
    operation: Literal["list_resources"] = _op("list_resources", "List Resource Types and Resources", "Settings")


class ListPeopleCategories(Settings):
    operation: Literal["list_people_categories"] = _op("list_people_categories", "List People Categories", "Settings")


class ListLanguages(Settings):
    operation: Literal["list_languages"] = _op("list_languages", "List Account Languages", "Settings")


class Window(Page):
    start_time: datetime = Field(..., title="Start Time", description="Timezone-qualified reporting window, at most 31 days.")
    end_time: datetime = Field(..., title="End Time")

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def absolute_offset(cls, value):
        if isinstance(value, str) and value.endswith("-00:00"):
            raise ValueError("Use an explicit UTC or timezone offset, not Bookeo's local-time sentinel")
        return value

    @model_validator(mode="after")
    def window(self):
        if any(v.tzinfo is None or v.utcoffset() is None for v in (self.start_time, self.end_time)) or not timedelta(0) < self.end_time - self.start_time <= timedelta(days=31):
            raise ValueError("Supply an aware increasing window of at most 31 days")
        return self


class ListAvailability(Window):
    operation: Literal["list_availability"] = _op("list_availability", "List Fixed Product Availability", "Availability")
    product_id: Identifier = _selector("product_id", "Product")


class ListCustomers(Page):
    operation: Literal["list_customers"] = _op("list_customers", "List Customer Metadata", "Customers")
    created_since: Optional[datetime] = Field(None, title="Created Since")
    search_field: Literal["name", "firstName", "lastName", "emailAddress"] = Field("name", title="Search Field")
    search_text: Optional[Text] = Field(None, title="Search Text")

    @field_validator("created_since")
    @classmethod
    def aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Include a timezone in Created Since")
        return value


class GetCustomer(Settings):
    operation: Literal["get_customer"] = _op("get_customer", "Get Customer Metadata", "Customers")
    customer_id: Identifier = _selector("customer_id", "Customer")


class CustomerFields(Settings):
    first_name: Text = Field(..., title="First Name")
    last_name: Text = Field(..., title="Last Name")
    email_address: Optional[Annotated[str, Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]] = Field(None, title="Email Address")


class CreateCustomer(CustomerFields):
    operation: Literal["create_customer"] = _op("create_customer", "Create Customer", "Customers")


class UpdateCustomer(CustomerFields):
    operation: Literal["update_customer"] = _op("update_customer", "Update Customer Name and Email", "Customers")
    customer_id: Identifier = _selector("customer_id", "Customer")


class DeleteCustomer(GetCustomer):
    operation: Literal["delete_customer"] = _op("delete_customer", "Delete Customer", "Customers")


class ListBookings(Window):
    operation: Literal["list_bookings"] = _op("list_bookings", "List Booking Report", "Bookings")
    product_id: Optional[Identifier] = _selector("product_id", "Product", False)
    include_canceled: bool = Field(False, title="Include Canceled Bookings")


class GetBooking(Settings):
    operation: Literal["get_booking"] = _op("get_booking", "Get Booking Metadata", "Bookings")
    booking_number: Identifier = Field(..., title="Booking Number", description="Bookeo booking numbers are always strings.", json_schema_extra={"x-resource-type": "bookeo_booking"})


class PeopleNumber(Settings):
    people_category_id: Identifier = Field(..., title="People Category ID", json_schema_extra={"x-resource-type": "bookeo_people_category"})
    number: int = Field(..., ge=1, le=1000, title="Number of Participants")


class CreateBooking(Window):
    operation: Literal["create_booking"] = _op("create_booking", "Create Booking (Reserves Seats)", "Bookings")
    product_id: Identifier = _selector("product_id", "Product")
    customer_id: Identifier = _selector("customer_id", "Customer")
    event_id: Identifier = Field(..., title="Available Event ID", description="An available fixed or fixed-course event in the selected window.", json_schema_extra={"x-resource-type": "bookeo_event"})
    people_numbers: list[PeopleNumber] = Field(..., min_length=1, max_length=30, title="Participant Numbers")
    external_ref: Optional[Annotated[str, Field(min_length=1, max_length=64)]] = Field(None, title="External Reference")

    @model_validator(mode="after")
    def categories(self):
        if len({p.people_category_id for p in self.people_numbers}) != len(self.people_numbers):
            raise ValueError("Use each people category only once")
        return self


class CancelBooking(GetBooking):
    operation: Literal["cancel_booking"] = _op("cancel_booking", "Cancel Booking (Frees Seats)", "Bookings")


Operations = Annotated[Union[GetBusiness, GetKeyPermissions, ListProducts, ListResources, ListPeopleCategories,
    ListLanguages, ListAvailability, ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer, DeleteCustomer,
    ListBookings, GetBooking, CreateBooking, CancelBooking], Field(discriminator="operation")]


class BookeoNodeConfig(NodeConfig[Operations, Credentials]):
    pass


class _Authority:
    def __init__(self, credential, *, credential_id=None, user_id=None, pool=None, organization_id=None, workflow_id=None):
        self.credential = _credential(credential)
        self.credential_id, self.user_id, self.pool = credential_id, user_id, pool
        self.organization_id, self.workflow_id, self.anchor = organization_id, workflow_id, None

    async def check(self):
        _credential(self.credential)
        if not self.credential_id:
            return
        if not self.user_id:
            raise ValueError("Bookeo saved credential requires an authorized actor")
        data = await resolve_credential_with_owner_fallback(self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id)
        if not data:
            raise ValueError("Bookeo current credential is unavailable or revoked")
        if _credential(data).model_dump() != self.credential.model_dump():
            raise ValueError("Bookeo credential changed; retry with the current connection")


def _secrets(credential):
    values = [credential.secret_key, credential.api_key] if isinstance(credential, BookeoAPIKeyCredential) else [credential.access_token]
    if isinstance(credential, BookeoOAuthCredential):
        values += [v for v in (credential.refresh_token,) if v]
    return {form for value in values for form in (value, quote(value, safe=""), base64.b64encode(value.encode()).decode(), base64.urlsafe_b64encode(value.encode()).decode(), value.encode().hex())}


def _public(value, credential):
    serialized = json.dumps(value, ensure_ascii=False)
    if any(s in serialized for s in _secrets(credential)):
        raise ValueError("Bookeo response contained protected credential data")
    return value


PUBLIC = {
    "business": ("id", "name"), "apikeyinfo": ("accountId", "permissions", "creationTime"),
    "products": ("productId", "name", "productCode", "type", "apiBookingsAllowed", "shownToCustomers", "acceptDeny", "membersOnly", "prepaidOnly", "dropInOnly"),
    "resources": ("id", "name", "isPublic"), "peoplecategories": ("id", "name", "numSeats"),
    "languages": ("name", "tag", "customersDefault"), "slots": ("productId", "eventId", "startTime", "endTime", "numSeatsAvailable", "numSeatsAvailableAsDropin", "privateEvent"),
    "customers": ("id", "creationTime", "member", "membershipEnd", "numBookings", "numCancelations", "numNoShows", "startTimeOfNextBooking", "startTimeOfPreviousBooking"),
    "bookings": ("bookingNumber", "productId", "eventId", "startTime", "endTime", "canceled", "accepted", "creationTime", "lastChangeTime", "cancelationTime", "noShow"),
}


def _project(kind, row, credential):
    if not isinstance(row, dict):
        raise ValueError("Bookeo resource response is invalid")
    identity = {"apikeyinfo": "accountId", "products": "productId", "slots": "eventId", "bookings": "bookingNumber", "languages": "tag"}.get(kind, "id")
    _id(row.get(identity))
    result = {k: row[k] for k in PUBLIC[kind] if k in row}
    for key, value in result.items():
        if value is not None and not isinstance(value, (str, bool, int, list)):
            raise ValueError("Bookeo metadata response is invalid")
        if isinstance(value, str) and len(value) > 10000:
            raise ValueError("Bookeo metadata text exceeds its limit")
        if isinstance(value, list) and (key != "permissions" or len(value) > 100 or any(not isinstance(v, str) or len(v) > 100 for v in value)):
            raise ValueError("Bookeo permission metadata is invalid")
        if key in {"isPublic", "apiBookingsAllowed", "shownToCustomers", "acceptDeny", "membersOnly", "prepaidOnly", "dropInOnly", "customersDefault", "privateEvent", "canceled", "accepted", "noShow", "member"} and value is not None and type(value) is not bool:
            raise ValueError("Bookeo boolean metadata is invalid")
        if key in {"numSeats", "numSeatsAvailable", "numSeatsAvailableAsDropin", "numBookings", "numCancelations", "numNoShows"} and value is not None and (type(value) is not int or value < 0):
            raise ValueError("Bookeo numeric metadata is invalid")
    if kind in {"business", "products", "resources", "languages", "peoplecategories"} and (not isinstance(result.get("name"), str) or not result["name"]):
        raise ValueError("Bookeo resource omitted its name")
    if kind == "products" and result.get("type") not in {"fixed", "fixedCourse", "flexibleTime"}:
        raise ValueError("Bookeo product type is invalid")
    if kind == "resources":
        resources = row.get("resources", [])
        if not isinstance(resources, list) or len(resources) > 1000:
            raise ValueError("Bookeo resource list exceeds its limit")
        result["resources"] = []
        for resource in resources:
            if not isinstance(resource, dict) or not isinstance(resource.get("name"), str):
                raise ValueError("Bookeo resource shape is invalid")
            result["resources"].append({"id": _id(resource.get("id")), "name": resource["name"][:10000]})
    return _public(result, credential)


class _Client:
    def __init__(self, authority):
        self.authority, self.credential = authority, authority.credential
        self.account_id, self.permissions = None, None

    async def request(self, method, path, *, params=None, body=None):
        valid = ((method == "GET" and path in {"/settings/" + k for k in ("business", "apikeyinfo", "products", "resources", "peoplecategories", "languages")})
            or (method == "GET" and path == "/availability/slots")
            or (method in {"GET", "POST"} and path in {"/customers", "/bookings"})
            or (method in {"GET", "PUT", "DELETE"} and re.fullmatch(r"/(?:customers|bookings)/[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", path)))
        if not valid:
            raise ValueError("Unsupported Bookeo native route")
        await self.authority.check()
        backoff_key = hashlib.sha256(self._key()).hexdigest()
        if max(_BACKOFF.get(backoff_key, 0), _BACKOFF.get(self.account_id, 0)) > time.monotonic():
            raise ValueError("Bookeo account is still throttled; wait before another request")
        if body is not None:
            _public(body, self.credential)
        params = dict(params or {})
        if set(params) & {"secretKey", "apiKey", "access_token", "mode"}:
            raise ValueError("Unsupported Bookeo request parameter")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if isinstance(self.credential, BookeoAPIKeyCredential):
            headers.update({"X-Bookeo-secretKey": self.credential.secret_key, "X-Bookeo-apiKey": self.credential.api_key})
        else:
            headers["Authorization"] = "Bearer " + self.credential.access_token
        url = BASE + path
        assert_exact_url_origin(url, ORIGIN)
        _install_privacy()
        private = PRIVATE_REQUEST.set((method, url))
        try:
            tracer = OutboundTraceProvider().get_tracer(__name__)
            # Suppress native auto-instrumentation BEFORE sampling/hooks can see
            # raw headers/body. A safe diagnostic span keeps trace propagation.
            with tracer.start_as_current_span(method, kind=SpanKind.CLIENT, attributes={"http.request.method": method,
                    "url.full": url, "url.scheme": "https", "server.address": "api.bookeo.com", "server.port": 443},
                    record_exception=False, set_status_on_exception=False) as span:
                try:
                    propagate.inject(headers)
                    with suppress_http_instrumentation():
                        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20)) as client:
                            async with client.stream(method, url, headers=headers, params=params, json=body) as response:
                                span.set_attributes({"http.response.status_code": response.status_code})
                                content = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(content) + len(chunk) > MAX_BYTES:
                                        raise ValueError("Bookeo response exceeds its metadata limit")
                                    content.extend(chunk)
                                status, media = response.status_code, response.headers.get("content-type", "")
                                retry = response.headers.get("retry-after", "")
                                if status >= 300:
                                    span.set_status(StatusCode.ERROR)
                except BaseException as error:
                    span.set_status(StatusCode.ERROR)
                    span.record_exception(error)
                    if isinstance(error, httpx.HTTPError):
                        raise ValueError("Bookeo request could not be read; write outcome is unknown, verify before retrying" if method != "GET" else "Bookeo request could not be read; connection is unverified") from None
                    raise
        finally:
            PRIVATE_REQUEST.reset(private)
        await self.authority.check()
        if status == 429:
            seconds = int(retry) if re.fullmatch(r"[0-9]{1,9}", retry) else None
            deadline = time.monotonic() + (seconds if seconds is not None else 60)
            _BACKOFF[backoff_key] = deadline
            if self.account_id:
                _BACKOFF[self.account_id] = deadline
            raise ValueError(f"Bookeo account is throttled; do not send another request for {seconds} seconds" if seconds is not None else "Bookeo account is throttled; wait for the provider Retry-After before another request")
        expected = {"GET": 200, "POST": 201, "PUT": 200, "DELETE": 204}[method]
        if status != expected:
            raise ValueError(f"Bookeo request returned HTTP {status}; access or outcome is unverified")
        if status == 204:
            if content:
                raise ValueError("Bookeo empty success response contained an unexpected body")
            return None
        if media.split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Bookeo response was not JSON")
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except Exception:
            raise ValueError("Bookeo JSON response is invalid") from None

    async def identity(self):
        business = _project("business", await self.request("GET", "/settings/business"), self.credential)
        self.account_id = business["id"]
        if self.credential.expected_account_id and self.account_id != self.credential.expected_account_id:
            raise ValueError("Bookeo credential belongs to a different account")
        if isinstance(self.credential, BookeoAPIKeyCredential):
            info = _project("apikeyinfo", await self.request("GET", "/settings/apikeyinfo"), self.credential)
            if info["accountId"] != self.account_id or not isinstance(info.get("permissions"), list):
                raise ValueError("Bookeo API key account or permissions are inconsistent")
            self.permissions = frozenset(info["permissions"])
        return business

    def require(self, resource, action="read"):
        if self.permissions is None:
            # Bearer scope is application-issued; do not invent key-info scope
            # evidence for this distinct family. Provider still enforces it.
            return
        if resource == "availability":
            allowed = {"availability_r"}
        else:
            grades = {"read": ("r", "rw", "rwd"), "write": ("rw", "rwd"), "delete": ("rwd",)}[action]
            allowed = {f"{resource}_{g}_{scope}" for g in grades for scope in ("all", "own") if not (g == "r" and scope == "own")}
        if not allowed & self.permissions:
            raise ValueError("Bookeo key lacks the granted permission for this operation")

    def _key(self):
        return (self.credential.secret_key + ":" + self.credential.api_key).encode() if isinstance(self.credential, BookeoAPIKeyCredential) else self.credential.access_token.encode()

    def _scope(self, path, params):
        return hashlib.sha256(json.dumps([self.account_id, self.credential.expected_account_id, path, params], sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _encode(self, path, params, nav, page):
        blob = json.dumps({"scope": self._scope(path, params), "nav": nav, "page": page}, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(blob).decode().rstrip("=") + "." + hmac.new(self._key(), blob, hashlib.sha256).hexdigest()

    def _decode(self, path, params, token):
        try:
            encoded, signature = token.split(".")
            blob = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            value = json.loads(blob)
            if not hmac.compare_digest(signature, hmac.new(self._key(), blob, hashlib.sha256).hexdigest()) or set(value) != {"scope", "nav", "page"} or value["scope"] != self._scope(path, params):
                raise ValueError
            if not isinstance(value["nav"], str) or not 1 <= len(value["nav"]) <= 4096 or type(value["page"]) is not int or not 2 <= value["page"] <= 100:
                raise ValueError
            return value["nav"], value["page"]
        except Exception:
            raise ValueError("Bookeo continuation belongs to another credential, account, resource or filter") from None

    async def page(self, kind, path, params, token=None):
        nav, page = self._decode(path, params, token) if token else (None, 1)
        sent = {"pageNavigationToken": nav, "pageNumber": page} if nav else params
        payload = await self.request("GET", path, params=sent)
        info, rows = payload.get("info"), payload.get("data")
        if not isinstance(info, dict) or not isinstance(rows, list) or len(rows) > MAX_ROWS or any(type(info.get(k)) is not int or info[k] < 0 for k in ("currentPage", "totalPages", "totalItems")) or info["currentPage"] != page:
            raise ValueError("Bookeo page envelope is invalid")
        pages = info["totalPages"]
        if pages > 100 or pages < page and not (page == 1 and pages == 0 and not rows and info["totalItems"] == 0):
            raise ValueError("Bookeo page count is invalid or exceeds its bound")
        continuation = None
        if page < pages:
            returned = info.get("pageNavigationToken")
            if not isinstance(returned, str) or not 1 <= len(returned) <= 4096 or (nav is not None and nav != returned):
                raise ValueError("Bookeo page navigation token is missing or changed")
            _public(returned, self.credential)
            continuation = self._encode(path, params, returned, page + 1)
        data = [_project(kind, r, self.credential) for r in rows]
        if kind in {"slots", "bookings"} and params.get("productId") and any(r.get("productId") != params["productId"] for r in data):
            raise ValueError("Bookeo result returned a different product")
        return {"data": data, "next_page_token": continuation, "total": info["totalItems"]}

    async def simple(self, kind):
        payload = await self.request("GET", "/settings/" + kind)
        rows = payload.get("categories" if kind == "peoplecategories" else "data")
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("Bookeo settings list is invalid")
        return [_project(kind, row, self.credential) for row in rows]

    async def one(self, kind, identifier):
        row = await self.request("GET", "/" + kind + "/" + identifier, params={"expandCustomer": "false", "expandParticipants": "false"} if kind == "bookings" else None)
        projected = _project(kind, row, self.credential)
        if projected["bookingNumber" if kind == "bookings" else "id"] != identifier:
            raise ValueError("Bookeo selected resource does not match the response")
        return row, projected

    async def product(self, identifier):
        token = None
        for _ in range(100):
            result = await self.page("products", "/settings/products", {"itemsPerPage": 100}, token)
            rows = [r for r in result["data"] if r["productId"] == identifier]
            if len(rows) == 1:
                return rows[0]
            if not result["next_page_token"]:
                break
            token = result["next_page_token"]
        raise ValueError("Bookeo product is not in the current account")


class BookeoNode(WorkflowNode):
    workflow_credential_refresh = True
    integration_type = "automation-bookeo"
    credential_provider_labels = {"bookeo": "Bookeo"}
    scope_registry = BOOKEO_SCOPES
    connection_evidence = ConnectionEvidence(noun="business account", operation="get_business", identity_operation="get_business", identity_keys=("name",), proves="account")

    @classmethod
    def get_config_model(cls):
        return BookeoNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None:
            _family(raw)
        try:
            data = runtime_config_view(config_data, BookeoNodeConfig)
            TypeAdapter(Operations).validate_python(data["config"])
            if raw is not None:
                data["credentials"] = _credential(raw).model_dump()
        except Exception:
            raise ValueError("Bookeo configuration is invalid; check typed operation fields") from None
        return super().parse_config(data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            data = dict(config_data)
            if data.get("credentials") is not None:
                data["credentials"] = _credential(data["credentials"]).model_dump()
            return super().validate_config(data)
        except Exception:
            return {"valid": False, "errors": ["Bookeo credential or configuration is invalid"], "satisfied_set": None}

    def _authority(self):
        return _Authority(self.config.credentials, credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            pool=self.node_data.get("_approval_pool"), organization_id=self.organization_id, workflow_id=self.workflow_id)

    async def run(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        if isinstance(self.config.credentials, BookeoOAuthCredential):
            prepared = await self.freshen_credential(self.config.credentials.model_dump(),
                credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
                pool=self.node_data.get("_approval_pool"))
            self.config.credentials = _credential(prepared)
        self._native_authority = self._authority()
        await self._native_authority.check()
        return await super().run(inputs)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        credential = _credential(credential_data)
        if isinstance(credential, BookeoOAuthCredential):
            from nodes.core.oauth_refresh import freshen_oauth_credential
            from nodes.oauth.bookeo_oauth import refresh_access_token
            return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
                credential_id=credential_id, refresh=refresh_access_token, provider="bookeo")
        return credential.model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        _credential(credential_data)
        return {"valid": None, "error": "Run business account connection evidence to verify access"}

    async def execute(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        client = _Client(getattr(self, "_native_authority", None) or self._authority())
        if self.config.config.operation == "get_key_permissions" and not isinstance(client.credential, BookeoAPIKeyCredential):
            raise ValueError("API key permissions require the API key credential family")
        business = await client.identity()
        cfg = self.config.config
        op = cfg.operation
        base = {"account_id": client.account_id}
        if op == "get_business":
            return {**base, "business": business, "name": business.get("name")}
        if op == "get_key_permissions":
            if client.permissions is None:
                raise ValueError("API key permissions are available only for the API key credential family")
            return {**base, "permissions": sorted(client.permissions)}
        if op in {"list_people_categories", "list_languages"}:
            return {**base, "data": await client.simple("peoplecategories" if op == "list_people_categories" else "languages")}
        if op in {"list_products", "list_resources", "list_availability", "list_customers", "list_bookings"}:
            kind = {"list_products": "products", "list_resources": "resources", "list_availability": "slots", "list_customers": "customers", "list_bookings": "bookings"}[op]
            path = "/settings/" + kind if kind in {"products", "resources"} else "/availability/slots" if kind == "slots" else "/" + kind
            params = {"itemsPerPage": cfg.items_per_page}
            if isinstance(cfg, ListProducts) and cfg.product_type:
                params["type"] = cfg.product_type
            if isinstance(cfg, (ListAvailability, ListBookings)):
                params.update(startTime=cfg.start_time.isoformat(), endTime=cfg.end_time.isoformat())
                if cfg.product_id:
                    product = await client.product(cfg.product_id)
                    params["productId"] = cfg.product_id
                    if kind == "slots" and product.get("type") not in {"fixed", "fixedCourse"}:
                        raise ValueError("Fixed availability requires a fixed or fixed-course product")
            if kind in {"customers", "bookings"}:
                client.require(kind)
            if kind == "slots":
                client.require("availability")
            if isinstance(cfg, ListBookings):
                params.update(includeCanceled=str(cfg.include_canceled).lower(), expandCustomer="false", expandParticipants="false")
            if isinstance(cfg, ListCustomers):
                if cfg.created_since:
                    params["createdSince"] = cfg.created_since.isoformat()
                if cfg.search_text:
                    params.update(searchField=cfg.search_field, searchText=cfg.search_text)
            return {**base, **await client.page(kind, path, params, cfg.page_token)}
        kind = "customers" if "customer" in op else "bookings"
        action = op.split("_", 1)[0]
        client.require(kind, "delete" if action in {"delete", "cancel"} else "read" if action == "get" else "write")
        target = getattr(cfg, "customer_id" if kind == "customers" else "booking_number", None) if action != "create" else None
        existing, projected = await client.one(kind, target) if target else (None, None)
        if action == "get":
            return {**base, "data": projected}
        if action in {"delete", "cancel"}:
            params = {"notifyUsers": "false", "notifyCustomer": "false", "applyCancellationPolicy": "false", "trackInCustomerHistory": "false", "cancelRemainingSeries": "false"} if kind == "bookings" else None
            await client.request("DELETE", "/" + kind + "/" + target, params=params)
            return {**base, "canceled" if kind == "bookings" else "deleted": True, "bookingNumber" if kind == "bookings" else "id": target}
        if kind == "customers":
            # PUT a complete documented writable representation, preserving
            # existing contact fields. Read-only credit/identity never enter it.
            writable = {"firstName", "middleName", "lastName", "emailAddress", "phoneNumbers", "streetAddress", "dateOfBirth", "customFields", "gender", "facebookId", "languageCode", "acceptSmsReminders"}
            body = {k: v for k, v in (existing or {}).items() if k in writable}
            body.update(firstName=cfg.first_name, lastName=cfg.last_name)
            if cfg.email_address is not None:
                body["emailAddress"] = cfg.email_address
            if action == "create":
                body["acceptSmsReminders"] = False
            params = None
        elif action == "create":
            product = await client.product(cfg.product_id)
            if product.get("type") not in {"fixed", "fixedCourse"} or product.get("apiBookingsAllowed") is not True or product.get("shownToCustomers") is not True or product.get("prepaidOnly") is not False or product.get("membersOnly") is not False:
                raise ValueError("Choose an API-bookable public fixed product without membership or prepaid-credit requirements")
            client.require("customers")
            await client.one("customers", cfg.customer_id)
            client.require("availability")
            params_for_slots = {"itemsPerPage": 100, "productId": cfg.product_id, "startTime": cfg.start_time.isoformat(), "endTime": cfg.end_time.isoformat()}
            token, event = None, None
            for _ in range(100):
                slots = await client.page("slots", "/availability/slots", params_for_slots, token)
                event = next((r for r in slots["data"] if r["eventId"] == cfg.event_id and r.get("productId") == cfg.product_id), None)
                if event or not slots["next_page_token"]:
                    break
                token = slots["next_page_token"]
            if event is None:
                raise ValueError("The selected event is not available for this product/window")
            categories = {r["id"] for r in await client.simple("peoplecategories")}
            if any(p.people_category_id not in categories for p in cfg.people_numbers):
                raise ValueError("Participant categories are not in the current account")
            body = {"productId": cfg.product_id, "customerId": cfg.customer_id, "eventId": cfg.event_id,
                    "participants": {"numbers": [{"peopleCategoryId": p.people_category_id, "number": p.number} for p in cfg.people_numbers]}}
            if cfg.external_ref:
                body["externalRef"] = cfg.external_ref
            params = {"notifyUsers": "false", "notifyCustomer": "false", "sendCustomerReminders": "false", "sendCustomerThankyou": "false"}
        else:
            raise ValueError("Unsupported Bookeo mutation")
        row = await client.request("POST" if action == "create" else "PUT", "/" + kind + ("/" + target if target else ""), params=params, body=body)
        data = _project(kind, row, client.credential)
        if target and data["id" if kind == "customers" else "bookingNumber"] != target:
            raise ValueError("Bookeo write response changed resource identity; verify before retrying")
        return {**base, "data": data, "effect": "Customer record changed" if kind == "customers" else "Booking reservation changed; returned accepted status may still require business approval"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name not in {"product_id", "customer_id"}:
            raise ValueError("Unsupported Bookeo selector")
        _credential(credential_data)
        authority = _Authority(credential_data)
        client = _Client(authority)
        await client.identity()
        kind, path = ("products", "/settings/products") if field_name == "product_id" else ("customers", "/customers")
        if kind == "customers":
            client.require("customers")
        async def fetch(token):
            page = await client.page(kind, path, {"itemsPerPage": 100}, token)
            key = "productId" if kind == "products" else "id"
            # Customer names/contact details stay out of option evidence.
            return [{"value": r[key], "label": r.get("name") or r[key]} for r in page["data"]], page["next_page_token"]
        return await load_paginated_options(fetch, page_token=page_token, search=normalize_search(search), cap=1000)
