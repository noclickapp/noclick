"""Setmore's documented scheduling routes with supplied permanent refresh tokens.

Tokens are exchanged within each invocation using staging's credential loading.
It returns bounded booking metadata and never tokens, private notes or links.
"""
from contextvars import ContextVar
from datetime import datetime
import json
import logging
import re
import time
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import is_placeholder, is_url_shaped
from utils.ssrf import SSRFError, guarded_async_client

NODE_TYPE = "automation-setmore"
FAMILIES = {"setmore_refresh_token"}
ORIGIN = "https://developer.setmore.com"
MAX_BYTES = 2_097_152
Key = Annotated[StrictStr, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[StrictStr, Field(min_length=1, max_length=200)]
Cursor = Annotated[StrictStr, Field(min_length=1, max_length=4096)]


class SetmoreRefreshTokenCredential(BaseModel):
    """An existing permanent refresh token issued after Setmore API approval."""
    model_config = ConfigDict(title="Setmore Account", extra="ignore", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://support.setmore.com/en/articles/579360-request-access-to-the-setmore-api"})
    credential_type: Literal["setmore_refresh_token"] = Field("setmore_refresh_token", json_schema_extra={"ui:hidden": True})
    refresh_token: StrictStr = Field(..., min_length=1, max_length=8192, repr=False, title="Permanent refresh token", description="Paste the existing token issued by Setmore after API access approval. A Pro account and approval are required. This does not register an OAuth application or request access.", json_schema_extra={"ui:widget": "password"})

    @field_validator("refresh_token")
    @classmethod
    def secret(cls, value):
        if not value.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or is_placeholder(value) or is_url_shaped(value):
            raise ValueError("Supply the permanent refresh token without a header, placeholder or control characters")
        return value


def _credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") not in FAMILIES:
        raise ValueError("Connect a native Setmore permanent refresh token")
    try:
        return SetmoreRefreshTokenCredential.model_validate(raw)
    except ValueError:
        raise ValueError("Supply a valid Setmore permanent refresh token") from None


def _date(value, format):
    try:
        parsed = datetime.strptime(value, format)
        if parsed.strftime(format) != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise ValueError("Use a real date in the documented format") from None


def _picker(name, depends_on=None):
    value = {"field_name": name, "searchable": True, "allow_custom": True}
    if depends_on:
        value["depends_on"] = depends_on
    return {"x-dynamic-options": value}


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def text(cls, value):
        if isinstance(value, str) and (value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use metadata without surrounding whitespace or control characters")
        return value


class _Bounded(_Config):
    item_limit: Annotated[StrictInt, Field(ge=1, le=100)] = Field(25, description="Local output cap. This does not invent provider pagination parameters.")


class SetmoreListServicesConfig(_Bounded):
    """Read the account's service metadata from one protected response."""
    operation: Literal["list_services"] = "list_services"


class SetmoreListCategoriesConfig(_Bounded):
    """Read service category metadata; surface an unconsumed provider cursor."""
    operation: Literal["list_categories"] = "list_categories"


class SetmoreListCategoryServicesConfig(_Bounded):
    """Read services under a selected category."""
    operation: Literal["list_category_services"] = "list_category_services"
    category_key: Key = Field(..., title="Category", json_schema_extra=_picker("category_key"))


class SetmoreListStaffConfig(_Bounded):
    """Read staff IDs and names, omitting contact details and internal notes."""
    operation: Literal["list_staff"] = "list_staff"


class SetmoreGetSlotsConfig(_Config):
    """Read available time slots; this POST never creates a booking."""
    operation: Literal["get_slots"] = "get_slots"
    service_key: Key = Field(..., title="Service", json_schema_extra=_picker("service_key"))
    staff_key: Key = Field(..., title="Staff", json_schema_extra=_picker("staff_key", ["service_key"]))
    selected_date: StrictStr = Field(..., pattern=r"^\d{2}/\d{2}/\d{4}$", description="DD/MM/YYYY; slots use this format, not appointment list dates.")
    off_hours: StrictBool = False
    double_booking: StrictBool = False
    slot_limit: Annotated[StrictInt, Field(ge=1, le=30)] = 30
    timezone: Optional[Annotated[StrictStr, Field(min_length=1, max_length=128)]] = Field(None, description="IANA time zone; omitted means the account's company time zone.")
    _selected = field_validator("selected_date")(lambda value: (_date(value, "%d/%m/%Y"), value)[1])

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        if value is not None:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                ZoneInfo(value)
            except (ValueError, ZoneInfoNotFoundError):
                raise ValueError("Supply an IANA time zone") from None
        return value


class SetmoreFindCustomersConfig(_Bounded):
    """Find customers by the required first name and optional email/phone."""
    operation: Literal["find_customers"] = "find_customers"
    firstname: Text = Field(..., description="Required by the documented customer search route.")
    email: Optional[Text] = None
    phone: Optional[Text] = None


class SetmoreCreateCustomerConfig(_Config):
    """Create a customer profile; this does not create an appointment."""
    operation: Literal["create_customer"] = "create_customer"
    first_name: Text
    last_name: Optional[Text] = None
    email_id: Optional[Text] = None
    country_code: Optional[Text] = None
    cell_phone: Optional[Text] = None


class SetmoreListAppointmentsConfig(_Config):
    """Read one cursor page of appointments without expanded customer data."""
    operation: Literal["list_appointments"] = "list_appointments"
    start_date: StrictStr = Field(..., pattern=r"^\d{2}-\d{2}-\d{4}$", description="DD-MM-YYYY.")
    end_date: StrictStr = Field(..., pattern=r"^\d{2}-\d{2}-\d{4}$", description="DD-MM-YYYY; at most 31 days in this node.")
    staff_key: Optional[Key] = Field(None, title="Staff", json_schema_extra=_picker("staff_key"))
    cursor: Optional[Cursor] = None

    @model_validator(mode="after")
    def range(self):
        delta = (_date(self.end_date, "%d-%m-%Y") - _date(self.start_date, "%d-%m-%Y")).days
        if not 0 <= delta <= 31:
            raise ValueError("Use an ordered date range of at most 31 days")
        return self


class SetmoreCreateAppointmentConfig(_Config):
    """Create a live appointment; account notification settings may notify people."""
    operation: Literal["create_appointment"] = "create_appointment"
    service_key: Key = Field(..., title="Service", json_schema_extra=_picker("service_key"))
    staff_key: Key = Field(..., title="Staff", json_schema_extra=_picker("staff_key", ["service_key"]))
    customer_key: Key = Field(..., description="An existing account customer key. Customer creation is a separate operation.")
    start_time: StrictStr = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$", description="UTC minute precision, YYYY-MM-DDTHH:mmZ.")
    end_time: StrictStr = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")
    label: Optional[Text] = None
    confirm_booking: StrictBool = Field(..., description="Confirm a live booking and possible account notifications. No sandbox or cancellation operation is provided.")

    @model_validator(mode="after")
    def booking(self):
        delta = (_date(self.end_time, "%Y-%m-%dT%H:%MZ") - _date(self.start_time, "%Y-%m-%dT%H:%MZ")).total_seconds()
        if self.confirm_booking is not True or not 0 < delta <= 86400:
            raise ValueError("Confirm the booking and use an ordered UTC interval of at most 24 hours")
        return self


class SetmoreUpdateAppointmentLabelConfig(_Config):
    """Update an appointment's ordinary internal label using the documented query."""
    operation: Literal["update_appointment_label"] = "update_appointment_label"
    appointment_key: Key
    label: Text


SetmoreConfig = Annotated[Union[SetmoreListServicesConfig, SetmoreListCategoriesConfig, SetmoreListCategoryServicesConfig, SetmoreListStaffConfig, SetmoreGetSlotsConfig, SetmoreFindCustomersConfig, SetmoreCreateCustomerConfig, SetmoreListAppointmentsConfig, SetmoreCreateAppointmentConfig, SetmoreUpdateAppointmentLabelConfig], Field(discriminator="operation")]


class SetmoreNodeConfig(NodeConfig):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    config: SetmoreConfig
    credentials: Optional[SetmoreRefreshTokenCredential] = None

_PRIVATE_REQUEST: ContextVar[bool] = ContextVar("setmore_private_request", default=False)


class _PrivateRequestLogFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_REQUEST.get()


for _logger in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "utils.ssrf"):
    logging.getLogger(_logger).addFilter(_PrivateRequestLogFilter())


class _AuthRefused(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Setmore returned duplicate JSON properties")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("Setmore returned non-finite metadata")


def _text(value, *, maximum=512):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Setmore returned invalid text metadata")
    return value


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("Setmore returned an invalid resource key")
    return value


FIELDS = {
    "services": ("service_name", "duration", "buffer_duration", "currency", "staff_keys"),
    "service_categories": ("categoryName", "categoryOrder", "serviceIdList", "createdDate", "deleteFlag"),
    "staffs": ("first_name", "last_name", "company_key", "contact_type"),
    "customer": ("first_name", "last_name", "company_key", "contact_type"),
    "appointments": ("start_time", "end_time", "duration", "staff_key", "service_key", "customer_key", "currency", "label"),
}


def _record(raw, resource, *, expected_key=None, staff_key=None, service_key=None, customer_key=None):
    if not isinstance(raw, dict):
        raise ValueError("Setmore returned invalid record metadata")
    key = _key(raw.get("key"))
    if expected_key is not None and key != expected_key:
        raise ValueError("Setmore returned a different record")
    for parent, expected in (("staff_key", staff_key), ("service_key", service_key), ("customer_key", customer_key)):
        if expected is not None and _key(raw.get(parent)) != expected:
            raise ValueError("Setmore returned a different booking association")
    result = {"id": key, "key": key}
    for name in FIELDS[resource]:
        value = raw.get(name)
        if value is None:
            continue
        if name in ("staff_keys", "serviceIdList"):
            if not isinstance(value, list) or len(value) > 1000:
                raise ValueError("Setmore returned an unbounded association list")
            value = [_key(item) for item in value]
            if len(value) != len(set(value)):
                raise ValueError("Setmore returned duplicate associations")
        elif name in ("duration", "buffer_duration", "categoryOrder", "createdDate"):
            if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
                raise ValueError("Setmore returned invalid numeric metadata")
        elif name == "deleteFlag":
            if type(value) is not bool:
                raise ValueError("Setmore returned invalid boolean metadata")
        elif name.endswith("_key"):
            value = _key(value)
        else:
            value = _text(value)
        result[name] = value
    return result


def _rows(data, name):
    rows = data.get(name)
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Setmore returned a missing or unbounded collection")
    result = [_record(row, name) for row in rows]
    if len(result) != len({row["key"] for row in result}):
        raise ValueError("Setmore returned duplicate resource keys")
    return result


def _page(rows, limit, *, cursor=None, continuation=False):
    if cursor is not None:
        cursor = _text(cursor, maximum=4096)
    # Appointment cursors skip an entire provider page. Keep all bounded rows
    # from a cursor page so local truncation cannot silently lose appointments.
    items = rows if continuation else rows[:limit]
    return {"items": items, "returned_count": len(items), "provider_count": len(rows),
            "truncated": len(items) != len(rows), "provider_cursor": cursor,
            "next_cursor": cursor if continuation else None, "continuation_supported": continuation}


class _Session:
    def __init__(self, credential):
        self.credential = credential
        self.access_token = None
        self.expires_at = 0.0

    async def _request(self, method, path, *, params=None, body=None, exchange=False):
        if exchange:
            if method != "GET" or path != "/api/v1/o/oauth2/token":
                raise ValueError("Unsupported Setmore token exchange")
            params = {"refreshToken": self.credential.refresh_token}
        else:
            allowed = {("GET", "/services"), ("GET", "/services/categories"), ("GET", "/staffs"),
                       ("POST", "/slots"), ("GET", "/customer"), ("POST", "/customer/create"),
                       ("GET", "/appointments"), ("POST", "/appointment/create")}
            if (method, path) not in allowed and not (method == "GET" and re.fullmatch(r"/services/categories/[A-Za-z0-9_-]{1,256}", path)) and not (method == "PUT" and re.fullmatch(r"/appointments/[A-Za-z0-9_-]{1,256}/label", path)):
                raise ValueError("Unsupported Setmore scheduling request")
            path = "/api/v1/bookingapi" + path
        if body is not None and len(json.dumps(body, allow_nan=False).encode()) > 16_384:
            raise ValueError("Setmore request exceeds the bounded input limit")
        private = _PRIVATE_REQUEST.set(True)
        try:
            headers = {"Accept": "application/json"}
            if not exchange:
                headers["Authorization"] = "Bearer " + self.access_token
            async with guarded_async_client( follow_redirects=False, trust_env=False, timeout=25.0) as client:
                async with client.stream(method, ORIGIN + path, headers=headers, params=params, **({"json": body} if body is not None else {})) as response:
                    if response.status_code in (401, 403):
                        raise _AuthRefused(f"Setmore token or access was rejected (HTTP {response.status_code})")
                    if response.status_code != 200:
                        raise ValueError(f"Setmore request did not complete (HTTP {response.status_code}); no automatic retry")
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Setmore returned an unsupported response format")
                    value = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(value) + len(chunk) > MAX_BYTES:
                            raise ValueError("Setmore response exceeds the bounded limit")
                        value.extend(chunk)
                    try:
                        raw = json.loads(value, object_pairs_hook=_unique, parse_constant=_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ValueError("Setmore returned invalid JSON metadata") from None
        except (httpx.HTTPError, SSRFError):
            raise ValueError("Setmore HTTPS request could not complete") from None
        finally:
            _PRIVATE_REQUEST.reset(private)
        if not isinstance(raw, dict):
            raise ValueError("Setmore returned an invalid response envelope")
        if raw.get("error") in ("unauthorized_request", "FORBIDDEN_ACCESS"):
            raise _AuthRefused("Setmore returned unauthorized or forbidden access")
        # Some documented validation errors set response=true. A data-free
        # response or any error is never counted as successful work/evidence.
        if raw.get("response") is not True or raw.get("error") is not None or not isinstance(raw.get("data"), dict):
            raise ValueError("Setmore returned a failed scheduling response")
        return raw["data"], raw

    async def request(self, method, path, **kwargs):
        if self.access_token is None or time.monotonic() >= self.expires_at:
            started = time.monotonic()
            data, _ = await self._request("GET", "/api/v1/o/oauth2/token", exchange=True)
            token = data.get("token")
            if not isinstance(token, dict) or not isinstance(token.get("token_type"), str) or token["token_type"].upper() != "BEARER" or type(token.get("expires_in")) is not int or not 1 <= token["expires_in"] <= 31_622_400:
                raise ValueError("Setmore returned an invalid token exchange")
            access = token.get("access_token")
            if not isinstance(access, str) or not 1 <= len(access) <= 8192 or not access.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in access) or is_placeholder(access) or is_url_shaped(access):
                raise ValueError("Setmore returned an invalid access token")
            self.access_token = access
            # A permanent refresh token is not rotated or persisted here.
            # Access tokens stay within this invocation and its original row.
            self.expires_at = started + max(0, token["expires_in"] - 30)
        data, raw = await self._request(method, path, **kwargs)
        encoded = json.dumps(data, ensure_ascii=False)
        if any(secret in encoded for secret in (self.credential.refresh_token, quote(self.credential.refresh_token, safe=""), self.access_token)):
            raise ValueError("Setmore returned credential material in metadata")
        return data, raw


class SetmoreNode(WorkflowNode):
    integration_type = "automation-setmore"
    connection_evidence = ConnectionEvidence(noun="services", operation="list_services", operation_arguments={"item_limit": 5}, label_keys=("service_name",), proves="account")

    @classmethod
    def get_config_model(cls):
        return SetmoreNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if raw is not None:
            _credential(raw)
        return super().parse_config(config_data)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in ("service_key", "staff_key", "category_key") or page_token is not None:
            raise ValueError("Unsupported Setmore picker or continuation")
        context = context or {}
        credential = _credential(credential_data)
        session = _Session(credential)
        resource = {"service_key": "services", "staff_key": "staffs", "category_key": "service_categories"}[field_name]
        eligible = None
        if field_name == "staff_key" and context.get("service_key"):
            selected = _key(context["service_key"])
            data, _ = await session.request("GET", "/services")
            matching = [row for row in _rows(data, "services") if row["key"] == selected]
            if len(matching) != 1 or "staff_keys" not in matching[0]:
                raise ValueError("Setmore service staff association is unavailable")
            eligible = matching[0]["staff_keys"]
        path = {"services": "/services", "staffs": "/staffs", "service_categories": "/services/categories"}[resource]
        data, raw = await session.request("GET", path)
        rows = _rows(data, resource)
        label = {"services": "service_name", "staffs": "first_name", "service_categories": "categoryName"}[resource]
        query = search.casefold() if isinstance(search, str) else ""
        options = []
        for row in rows:
            name = " ".join(filter(None, (row.get("first_name"), row.get("last_name")))) if resource == "staffs" else row.get(label)
            name = name or row["key"]
            if (eligible is None or row["key"] in eligible) and (not query or query in name.casefold()):
                options.append({"value": row["key"], "label": name})
        return {"options": options[:100], "next_page_token": None}

    async def execute(self, inputs):
        if not isinstance(self.config, SetmoreNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Setmore permanent refresh token")
        result = await self._execute(_Session(self.config.credentials), self.config.config)
        return {"status": "success", "data": result}

    async def _execute(self, session, config):
        op = config.operation
        if op in ("list_services", "list_categories", "list_category_services", "list_staff", "find_customers", "list_appointments"):
            name, path = {"list_services": ("services", "/services"), "list_categories": ("service_categories", "/services/categories"), "list_category_services": ("services", "/services/categories/" + quote(getattr(config, "category_key", ""), safe="")), "list_staff": ("staffs", "/staffs"), "find_customers": ("customer", "/customer"), "list_appointments": ("appointments", "/appointments")}[op]
            params = None
            if op == "find_customers":
                params = {key: getattr(config, key) for key in ("firstname", "email", "phone") if getattr(config, key) is not None}
            if op == "list_appointments":
                params = {"startDate": config.start_date, "endDate": config.end_date, "customerDetails": "false"}
                if config.staff_key:
                    params["staff_key"] = config.staff_key
                if config.cursor:
                    params["cursor"] = config.cursor
            data, raw = await session.request("GET", path, params=params)
            rows = _rows(data, name)
            if op == "list_appointments" and config.staff_key and any(row.get("staff_key") != config.staff_key for row in rows):
                raise ValueError("Setmore returned appointments for a different staff member")
            cursor = raw.get("cursor") if op == "list_categories" else data.get("cursor") if op in ("list_staff", "list_appointments") else None
            return _page(rows, getattr(config, "item_limit", 1000), cursor=cursor, continuation=op == "list_appointments")
        if op in ("get_slots", "create_appointment"):
            data, _ = await session.request("GET", "/services")
            matches = [row for row in _rows(data, "services") if row["key"] == config.service_key]
            if len(matches) != 1 or config.staff_key not in matches[0].get("staff_keys", []):
                raise ValueError("Selected staff is not associated with this Setmore service")
            data, _ = await session.request("GET", "/staffs")
            if not any(row["key"] == config.staff_key for row in _rows(data, "staffs")):
                raise ValueError("Selected staff is not present in the protected Setmore response")
            body = config.model_dump(exclude_none=True, exclude={"operation", "confirm_booking"})
            data, _ = await session.request("POST", "/slots" if op == "get_slots" else "/appointment/create", body=body)
            if op == "create_appointment":
                appointment = _record(data.get("appointment"), "appointments", staff_key=config.staff_key, service_key=config.service_key, customer_key=config.customer_key)
                if appointment.get("start_time") != config.start_time or appointment.get("end_time") != config.end_time:
                    raise ValueError("Setmore acknowledged a different booking interval")
                return {"appointment": appointment, "created": True, "readback_verified": False, "notifications_possible": True}
            slots = data.get("slots")
            expected_date = _date(config.selected_date, "%d/%m/%Y").strftime("%Y-%m-%d")
            if not isinstance(slots, dict) or any(date != expected_date for date in slots):
                raise ValueError("Setmore returned slots outside the selected date")
            values = slots.get(expected_date, [])
            if not isinstance(values, list) or len(values) > config.slot_limit or any(not isinstance(value, str) or not re.fullmatch(r"(?:[1-9]|1[0-2]):[0-5][0-9] (?:AM|PM)", value) for value in values) or len(values) != len(set(values)):
                raise ValueError("Setmore returned invalid or unbounded time slots")
            return {"date": expected_date, "slots": values, "timezone": config.timezone, "timezone_source": "requested" if config.timezone else "company", "booking_created": False}
        if op == "create_customer":
            data, _ = await session.request("POST", "/customer/create", body=config.model_dump(exclude_none=True, exclude={"operation"}))
            customer = _record(data.get("customer"), "customer")
            if customer.get("first_name") != config.first_name:
                raise ValueError("Setmore acknowledged a different customer name")
            return {"customer": customer, "created": True, "readback_verified": False}
        if op == "update_appointment_label":
            data, _ = await session.request("PUT", "/appointments/" + quote(config.appointment_key, safe="") + "/label", params={"label": config.label})
            appointment = _record(data.get("appointment"), "appointments", expected_key=config.appointment_key)
            if appointment.get("label") != config.label:
                raise ValueError("Setmore did not acknowledge the requested label")
            return {"appointment": appointment, "updated": True, "readback_verified": False}
        raise ValueError("Unsupported Setmore operation")
