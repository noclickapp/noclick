"""parcelLab v4 Enhanced: scoped order, return, Promise, PUDO and survey workflows."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

FAMILY = "parcellab_api_token"
HOSTS = {"global": "https://api.parcellab.com", "eu": "https://api.eu.parcellab.com", "us": "https://api.us.parcellab.com"}
ORDERS = "/v4/track/orders/"
RETURNS = "/v4/returns/return-registrations/"
CONFIGS = "/v4/returns/returns-configurations/"
TEMPLATES = "/v4/returns/document-templates/"
MAX_BYTES = 2_000_000


class ParcelLabError(ValueError):
    def __init__(self, message, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code, self.retry_after = status_code, retry_after


def text(value, maximum=255):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter a nonempty value without edge whitespace or control characters")
    return value


def uuid_value(value):
    try:
        return str(UUID(text(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Enter a valid resource UUID") from None


def positive_id(value):
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or value < 1 or value > 2**63 - 1:
        raise ValueError("Enter a positive resource ID")
    return value


def order_identifier(value):
    value = text(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value) or value.startswith("info"):
        raise ValueError("Enter an external order identifier using letters, numbers, underscores or hyphens")
    return value


def token_parts(value):
    try:
        raw = base64.b64decode(text(value, 8192), validate=True).decode("ascii")
        account, secret = raw.split(":", 1)
        if not account.isascii() or not account.isdecimal() or not secret or any(ord(c) < 33 or ord(c) > 126 for c in secret):
            raise ValueError
        return positive_id(account), secret
    except (ValueError, UnicodeError):
        raise ValueError("Paste the already base64-encoded account API token from parcelLab") from None


def guard(data, stored=False):
    if not isinstance(data, dict) or ((stored or "credential_type" in data) and data.get("credential_type") != FAMILY):
        raise ValueError("Select a native parcelLab account API token")


class ParcelLabAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="parcelLab API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.parcellab.com/service/account/apitoken/",
            "x-credential-instructions": "Paste the complete already base64-encoded account token. No Bearer prefix, extra encoding, account ID or JWT is needed. Required permissions depend on the selected API feature."})
    credential_type: Literal["parcellab_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Encoded API Token", json_schema_extra={"ui:widget": "password"})
    region: Literal["global", "eu", "us"] = Field("global", title="API Region")

    @field_validator("api_token", mode="before")
    @classmethod
    def validate_token(cls, value):
        token_parts(value)
        return value


def credential(data):
    guard(data)
    try:
        return ParcelLabAPITokenCredential.model_validate(data).model_dump(mode="json")
    except Exception:
        raise ValueError("Check the native parcelLab encoded account API token and region") from None


def picker(field, label):
    return {"x-dynamic-options": {"field_name": field, "placeholder": label, "searchable": True, "allow_custom": True}}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("order_number", "client_key", "external_reference", "reference", "search", "language",
        "courier", "tracking_number", "warehouse", "service_level", "reference_id", mode="before", check_fields=False)
    @classmethod
    def validate_text(cls, value):
        return text(value) if value is not None else value

    @field_validator("tags", mode="before", check_fields=False)
    @classmethod
    def validate_tags(cls, value):
        if not isinstance(value, list):
            raise ValueError("Enter a list of tags")
        return [text(tag) for tag in value]


class ListOrders(Config):
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"x-display-name": "List Orders"})
    order_number: str | None = None
    external_reference: str | None = None
    page_token: str | None = Field(None, description="Use only the next_page_token from this same filtered operation")


class Order(Config):
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"x-display-name": "Get Order Metadata"})
    order_id: str = Field(..., title="External Order ID", json_schema_extra=picker("order_id", "Select an order"))
    _id = field_validator("order_id", mode="before")(order_identifier)


class OrderStatus(Config):
    operation: Literal["get_order_status"] = Field("get_order_status", json_schema_extra={"x-display-name": "Get Order Delivery Status"})
    order_number: str
    client_key: str | None = None
    language: str = "en"


class TrackingStatus(Config):
    operation: Literal["get_tracking_status"] = Field("get_tracking_status", json_schema_extra={"x-display-name": "Get Tracking Delivery Status"})
    tracking_number: str
    courier: str
    language: str = "en"


class CreateOrder(Config):
    operation: Literal["create_order"] = Field("create_order", json_schema_extra={"x-display-name": "Create Order"})
    order_number: str
    destination_country_iso3: str = Field(..., pattern="^[A-Z]{3}$")
    recipient_email: str = Field("_unset", description="Use _unset when no recipient email is available; this is an actual order record")
    client_key: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    confirm_order_write: Literal[True] = Field(..., title="Confirm Order Creation", description="Creates an order and may affect configured customer workflows; no live mutation is performed while editing")

    @field_validator("recipient_email")
    @classmethod
    def email(cls, value):
        if value != "_unset" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter an email address or _unset")
        return value


class UpdateTags(Order):
    operation: Literal["update_order_tags"] = Field("update_order_tags", json_schema_extra={"x-display-name": "Update Order Tags"})
    tags: list[str] = Field(..., max_length=50, description="Replaces the order tag list")
    confirm_order_write: Literal[True] = Field(..., title="Confirm Order Update")


class AddTracking(Order):
    operation: Literal["add_tracking"] = Field("add_tracking", json_schema_extra={"x-display-name": "Add or Update Order Tracking"})
    courier: str
    tracking_number: str
    notifications_inactive: bool = Field(True, description="Requests notification suppression for this tracking; actual configured effects require verification")
    confirm_order_write: Literal[True] = Field(..., title="Confirm Tracking Update", description="Registers or updates tracking and may activate configured shipment workflows")


class Page(Config):
    page_size: int = Field(50, ge=1, le=100)
    page_token: str | None = None


class ListConfigurations(Page):
    operation: Literal["list_return_configurations"] = Field("list_return_configurations", json_schema_extra={"x-display-name": "List Return Configurations"})


class ReturnConfiguration(Config):
    operation: Literal["get_return_configuration"] = Field("get_return_configuration", json_schema_extra={"x-display-name": "Get Return Configuration"})
    configuration_id: int = Field(..., json_schema_extra=picker("configuration_id", "Select a return configuration"))
    _id = field_validator("configuration_id", mode="before")(positive_id)


class ListTemplates(Page):
    operation: Literal["list_return_document_templates"] = Field("list_return_document_templates", json_schema_extra={"x-display-name": "List Return Document Templates"})


class ListReturns(Page):
    operation: Literal["list_returns"] = Field("list_returns", json_schema_extra={"x-display-name": "List Return Registrations"})
    reference: str | None = None
    search: str | None = None
    return_status: Literal["approved", "cancelled", "closed", "created", "invalid", "pending_approval", "pending_label", "pending_payment", "processing_failed", "rejected", "submitted"] | None = None


class Return(Config):
    operation: Literal["get_return"] = Field("get_return", json_schema_extra={"x-display-name": "Get Return Registration Metadata"})
    return_id: str = Field(..., title="Return UUID", json_schema_extra={"format": "uuid", **picker("return_id", "Select a return")})
    _uuid = field_validator("return_id", mode="before")(uuid_value)


class ReturnStatus(Return):
    operation: Literal["get_return_status"] = Field("get_return_status", json_schema_extra={"x-display-name": "Get Return Status"})


class PredictDelivery(Config):
    operation: Literal["predict_delivery"] = Field("predict_delivery", json_schema_extra={"x-display-name": "Predict Delivery Date"})
    destination_country_iso3: str = Field(..., pattern="^[A-Z]{3}$")
    destination_postal_code: str | None = Field(None, max_length=10)
    courier: str | None = None
    warehouse: str | None = None
    service_level: str | None = None
    calibration: Literal["conservative", "balanced", "aggressive"] = "balanced"


class FindPlaces(Config):
    operation: Literal["find_pudo_locations"] = Field("find_pudo_locations", json_schema_extra={"x-display-name": "Find Pickup or Drop-Off Locations"})
    courier: str
    country_iso3: str = Field(..., pattern="^[A-Z]{3}$")
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    max_distance: float = Field(20, gt=0, le=1000, allow_inf_nan=False)
    distance_unit: Literal["km", "mi"] = "km"
    criterion: Literal["dropoff_location", "collection_point"] = "collection_point"
    limit: int = Field(10, ge=1, le=20)


class Place(Config):
    operation: Literal["get_pudo_location"] = Field("get_pudo_location", json_schema_extra={"x-display-name": "Get Pickup or Drop-Off Location"})
    place_id: str = Field(..., json_schema_extra={"format": "uuid"})
    _uuid = field_validator("place_id", mode="before")(uuid_value)


class Survey(Config):
    operation: Literal["get_survey"] = Field("get_survey", json_schema_extra={"x-display-name": "Get Survey Metadata"})
    survey_id: str = Field(..., json_schema_extra={"format": "uuid"})
    _uuid = field_validator("survey_id", mode="before")(uuid_value)


class SubmitSurvey(Survey):
    operation: Literal["submit_survey_response"] = Field("submit_survey_response", json_schema_extra={"x-display-name": "Submit Survey Response"})
    reference_id: str
    reference_type: Literal["tracking", "return_registration"]
    answers: dict = Field(..., description="Survey question data; writes a customer response", json_schema_extra={"ui:widget": "json"})
    is_complete: bool = True
    confirm_survey_write: Literal[True] = Field(..., title="Confirm Survey Response")

    @field_validator("answers")
    @classmethod
    def bounded_answers(cls, value):
        if len(json.dumps(value, allow_nan=False)) > 16384 or any(not isinstance(key, str) or key.lower() in {"authorization", "api_token", "password", "secret"} for key in value):
            raise ValueError("Enter a bounded survey answer object without credential fields")
        return value


Operation = Annotated[Union[ListOrders, Order, OrderStatus, TrackingStatus, CreateOrder, UpdateTags,
    AddTracking, ListConfigurations, ReturnConfiguration, ListTemplates, ListReturns, Return,
    ReturnStatus, PredictDelivery, FindPlaces, Place, Survey, SubmitSurvey], Field(discriminator="operation")]


class ParcelLabNodeConfig(NodeConfig[Operation, ParcelLabAPITokenCredential]):
    pass


class CurrentCredential(dict):
    def __init__(self, data, reload=None, credential_id=None):
        super().__init__(data)
        self.reload = reload
        self.credential_id = credential_id


async def freshen(data, **kwargs):
    initial = credential(data)
    credential_id = kwargs.get("credential_id")
    if not credential_id:
        return CurrentCredential(initial)
    if not kwargs.get("user_id"):
        raise ParcelLabError("Current credential access requires an authenticated actor")

    async def reload():
        # Use staging's shared access and workflow-owner fallback policy.
        from nodes.core.run_op import resolve_operation_credential
        current = await resolve_operation_credential(
            credential_id, kwargs["user_id"], kwargs.get("pool"),
            kwargs.get("organization_id"), kwargs.get("workflow_id"),
        )
        return credential(current)

    current = await reload()
    if current != initial:
        raise ParcelLabError("Current parcelLab connection changed; retry with the current connection")
    return CurrentCredential(current, reload, credential_id)


async def request(data, method, route, *, params=None, body=None, statuses=(200,), allow_list=False):
    reload = getattr(data, "reload", None)
    if reload:
        current = await reload()
        if any(current.get(k) != data.get(k) for k in ("credential_type", "api_token", "region")):
            raise ParcelLabError("Current parcelLab connection changed; retry with the current connection")
    guard(data, stored=True)
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=30) as client:
            reply = await client.request(method, HOSTS[data["region"]] + route, params=params, json=body,
                headers={"Authorization": "Parcellab-API-Token " + data["api_token"], "Accept": "application/json"})
    except httpx.RequestError:
        raise ParcelLabError("parcelLab could not be reached; the request is unverified") from None
    if reply.status_code not in statuses:
        descriptions = {400: "request was invalid", 401: "account API token was rejected", 403: "permission was denied", 404: "resource was not found", 429: "rate limit was reached"}
        delay = reply.headers.get("Retry-After")
        retry_after = int(delay) if delay and delay.isascii() and delay.isdecimal() and len(delay) <= 8 else None
        raise ParcelLabError(f"parcelLab HTTP {reply.status_code}: {descriptions.get(reply.status_code, 'response was not accepted')}", reply.status_code, retry_after)
    if len(reply.content) > MAX_BYTES:
        raise ParcelLabError("parcelLab response exceeds the supported size")
    try:
        payload = reply.json()
    except ValueError:
        raise ParcelLabError("parcelLab returned unreadable JSON") from None
    if not isinstance(payload, list if allow_list else dict) or (isinstance(payload, dict) and ("errors" in payload or payload.get("type") in {"client_error", "server_error"})):
        raise ParcelLabError("parcelLab returned an invalid response")
    return payload


def scalar(value, data):
    if isinstance(value, str):
        if len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value) or data["api_token"] in value or token_parts(data["api_token"])[1] in value:
            raise ParcelLabError("parcelLab metadata contains unreadable or protected data")
    elif value is not None and type(value) not in {int, float, bool}:
        raise ParcelLabError("parcelLab returned unreadable metadata")
    elif type(value) is float and not math.isfinite(value):
        raise ParcelLabError("parcelLab returned nonfinite metadata")
    return value


def metadata(row, data, keys):
    if not isinstance(row, dict):
        raise ParcelLabError("parcelLab returned unreadable resource metadata")
    result = {}
    booleans = {"has_multiple_shipments", "cancellable", "closable", "is_delayed", "is_exception", "is_return", "is_in_service", "has_details", "archived", "isEditable", "labels_available", "retention_offer_applied", "is_forgotten", "has_failed_attempt", "is_returned"}
    integers = {"item_count", "min", "max", "likely"}
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if (key in booleans and type(value) is not bool) or (key in integers and (type(value) is not int or value < 0)):
            raise ParcelLabError("parcelLab returned unreadable metadata types")
        result[key] = scalar(value, data)
    return result


def owned(row, data):
    if not isinstance(row, dict) or type(row.get("account")) is not int or row["account"] != token_parts(data["api_token"])[0]:
        raise ParcelLabError("parcelLab returned a resource outside the token's account")


def order_result(row, data):
    owned(row, data)
    identity = order_identifier(row.get("external_id"))
    text(row.get("order_number"))
    return {**metadata(row, data, ("order_number", "external_reference", "client_key", "destination_country_iso3", "order_date", "order_status", "has_multiple_shipments")), "external_id": identity}


def return_result(row, data):
    owned(row, data)
    identity = uuid_value(row.get("external_id"))
    return {**metadata(row, data, ("reference", "external_reference", "display_name", "sequence_number", "status", "cancellable", "closable", "item_count", "created_at", "submitted_at", "updated_at")), "external_id": identity}


def configuration_result(row, data):
    owned(row, data)
    identity = positive_id(row.get("id"))
    text(row.get("code"))
    if row.get("client") is not None:
        positive_id(row["client"])
    return {**metadata(row, data, ("code", "client")), "id": identity}


def template_result(row, data):
    owned(row, data)
    return {**metadata(row, data, ("key", "client_key", "identifier")), "id": positive_id(row.get("id"))}


def bound_token(data, route, query, position, scope_extra=None):
    cid = getattr(data, "credential_id", None)
    scope = hashlib.sha256(json.dumps([data["api_token"], data["region"], cid, route, query, scope_extra], sort_keys=True).encode()).hexdigest()
    return base64.urlsafe_b64encode(json.dumps({"scope": scope, "position": position}, sort_keys=True).encode()).decode()


async def collection(data, route, query, page_token, mapper, *, cursor=False, scope_extra=None):
    base_query = dict(query)
    position_key = "cursor" if cursor else "offset"
    if page_token:
        try:
            decoded = json.loads(base64.b64decode(text(page_token, 16384), altchars=b"-_", validate=True))
            expected = json.loads(base64.urlsafe_b64decode(bound_token(data, route, base_query, None, scope_extra)))
            if not isinstance(decoded, dict) or decoded.get("scope") != expected["scope"]:
                raise ValueError
            position = decoded["position"]
            if cursor:
                text(position, 4096)
            elif type(position) is not int or position < 0:
                raise ValueError
            query[position_key] = position
        except (ValueError, TypeError, KeyError):
            raise ParcelLabError("Page token does not match this current connection and filter") from None
    payload = await request(data, "GET", route, params=query)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list) or len(payload["results"]) > 1000:
        raise ParcelLabError("parcelLab returned an unreadable resource page")
    rows = [mapper(row, data) for row in payload["results"]]
    ids = [row.get("external_id", row.get("id")) for row in rows]
    if len(ids) != len(set(ids)):
        raise ParcelLabError("parcelLab returned duplicate resource identifiers")
    result = {"items": rows, "next_page_token": None}
    if "count" in payload:
        if type(payload["count"]) is not int or payload["count"] < len(rows):
            raise ParcelLabError("parcelLab returned unreadable resource counts")
        result["count"] = payload["count"]
    if payload.get("next"):
        link = urlsplit(text(payload["next"], 16384))
        host = urlsplit(HOSTS[data["region"]])
        next_query = parse_qs(link.query, keep_blank_values=True)
        allowed = set(base_query) | {position_key}
        if (link.scheme != "https" or link.netloc != host.netloc or link.path != route or link.fragment
                or set(next_query) - allowed or any(len(v) != 1 for v in next_query.values())
                or any(next_query.get(k) != [str(v)] for k, v in base_query.items()) or not rows):
            raise ParcelLabError("parcelLab returned an unsafe or inconsistent next page")
        position = next_query.get(position_key, [None])[0]
        if cursor:
            text(position, 4096)
        else:
            if not isinstance(position, str) or not position.isascii() or not position.isdecimal():
                raise ParcelLabError("parcelLab returned an unreadable page offset")
            position = int(position)
        if position == query.get(position_key) or (not cursor and position <= query.get("offset", -1)):
            raise ParcelLabError("parcelLab returned a repeated next page")
        result["next_page_token"] = bound_token(data, route, base_query, position, scope_extra)
    return result


def delivery_status(payload, data):
    if not isinstance(payload, dict) or not isinstance(payload.get("trackings"), list) or len(payload["trackings"]) > 1000:
        raise ParcelLabError("parcelLab returned unreadable delivery status")
    result = metadata(payload, data, ("order_number", "client_key", "order_date", "destination_country_iso3"))
    text(payload.get("order_number"))
    result["trackings"] = []
    for row in payload["trackings"]:
        if not isinstance(row, dict):
            raise ParcelLabError("parcelLab returned unreadable tracking metadata")
        text(row.get("tracking_number"))
        item = metadata(row, data, ("tracking_number", "is_delayed", "is_exception", "is_return", "announced_delivery_date", "announced_delivery_date_min"))
        if "last_delivery_status" in row:
            item["last_delivery_status"] = metadata(row["last_delivery_status"], data, ("step", "status_code", "status_text", "lifecycle_status", "exception_type", "event_timestamp"))
        if "reporting_info" not in row or not isinstance(row["reporting_info"], dict):
            raise ParcelLabError("parcelLab returned unreadable delivery reporting")
        item["reporting_info"] = metadata(row["reporting_info"], data, ("is_forgotten", "is_delayed", "has_failed_attempt", "is_returned", "in_transit_date", "pickup_date", "delivery_date", "returned_date"))
        result["trackings"].append(item)
    return result


def place_result(row, data):
    if not isinstance(row, dict):
        raise ParcelLabError("parcelLab returned unreadable PUDO metadata")
    text(row.get("name"))
    text(row.get("courier"))
    text(row.get("country_iso3"), 3)
    result = metadata(row, data, ("name", "courier", "country_iso3", "place_type", "distance", "is_in_service", "has_details", "external_reference"))
    result["external_id"] = uuid_value(row["external_id"]) if row.get("external_id") else None
    result["location"] = metadata(row.get("location"), data, ("latitude", "longitude"))
    if any(type(result["location"].get(k)) not in {int, float} or not -bound <= result["location"][k] <= bound
            for k, bound in (("latitude", 90), ("longitude", 180))):
        raise ParcelLabError("parcelLab returned unreadable PUDO coordinates")
    result["address"] = metadata(row.get("location_address"), data, ("address_line", "postal_code", "city", "country_iso3"))
    return result


class ParcelLabNode(WorkflowNode):
    integration_type = "automation-parcellab"
    connection_evidence = ConnectionEvidence(operation="list_orders", noun="orders", label_keys=("order_number",), proves="account")
    workflow_credential_refresh = True
    edit_examples = ["Read delivery status for an order", "Update order tags", "Predict delivery dates", "Read return status"]

    @classmethod
    def get_config_model(cls):
        return ParcelLabNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            raise ConfigValidationError("Select a native parcelLab account API token") from None
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            return {"valid": False, "errors": ["Select a native parcelLab account API token"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    def _extract_actionable_validation_error(cls, error, config_data):
        return "Check the native parcelLab credential and operation fields"

    @classmethod
    async def validate_credential(cls, credential_data):
        try:
            data = await freshen(credential_data)
            await collection(data, ORDERS, {}, None, order_result, cursor=True)
            return {"valid": True}
        except ParcelLabError as exc:
            return {"valid": False if exc.status_code in {401, 403} else None, "error": str(exc)}
        except (ValueError, TypeError, KeyError):
            return {"valid": False, "error": "Check the native parcelLab account API token"}

    @classmethod
    async def validate_credential_access(cls, credential_data):
        return await cls.validate_credential(credential_data)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"order_id", "return_id", "configuration_id"}:
            raise ValueError("Unknown parcelLab resource picker")
        data = credential_data if isinstance(credential_data, CurrentCredential) else await freshen(credential_data)
        query = {}
        if field_name == "order_id":
            route, mapper, cursor = ORDERS, order_result, True
            if search:
                query["order_number"] = text(search)
        elif field_name == "return_id":
            route, mapper, cursor = RETURNS, return_result, True
            query["limit"] = 50
            if search:
                query["search"] = text(search)
        else:
            route, mapper, cursor = CONFIGS, configuration_result, False
            query["limit"] = 50
        page = await collection(data, route, query, page_token, mapper, cursor=cursor, scope_extra={"field_name": field_name, "search": search})
        rows = page["items"]
        if field_name == "configuration_id" and search:
            rows = [row for row in rows if search.casefold() in row["code"].casefold()]
        return {"options": [{"value": str(row.get("external_id", row.get("id"))), "label": row.get("order_number", row.get("reference", row.get("code"))) or str(row.get("external_id", row.get("id")))} for row in rows], "next_page_token": page["next_page_token"]}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a native parcelLab API token")
        config = self.config.config
        try:
            nested = self.node_data.get("config") or {}
            cid = self.node_data.get("credential_id")
            if isinstance(nested, dict) and nested.get("credential_id"):
                if cid and cid != nested["credential_id"]:
                    raise ParcelLabError("parcelLab credential selection is ambiguous")
                cid = nested["credential_id"]
            data = await freshen(self.config.credentials.model_dump(mode="json"), credential_id=cid,
                pool=self.node_data.get("_approval_pool"), user_id=self.user_id,
                organization_id=self.organization_id, workflow_id=self.workflow_id)
            result = await self._operation(data, config)
            return {"status": "success", "action": config.operation, "data": result}
        except ParcelLabError as exc:
            return {"status": "error", "action": config.operation, "error": str(exc), "status_code": exc.status_code, "retry_after": exc.retry_after}
        except (ValueError, TypeError, KeyError):
            return {"status": "error", "action": config.operation, "error": "parcelLab credential or response could not be validated"}

    async def _operation(self, data, config):
        op = config.operation
        account = token_parts(data["api_token"])[0]
        if op in {"list_orders", "list_return_configurations", "list_return_document_templates", "list_returns"}:
            route, mapper, cursor = {"list_orders": (ORDERS, order_result, True), "list_return_configurations": (CONFIGS, configuration_result, False), "list_return_document_templates": (TEMPLATES, template_result, False), "list_returns": (RETURNS, return_result, True)}[op]
            query = {} if op == "list_orders" else {"limit": config.page_size}
            for key in ("order_number", "external_reference", "reference", "search"):
                if getattr(config, key, None):
                    query[key] = text(getattr(config, key))
            if getattr(config, "return_status", None):
                query["status"] = config.return_status
            return await collection(data, route, query, config.page_token, mapper, cursor=cursor)
        if op in {"get_order", "update_order_tags", "add_tracking"}:
            row = order_result(await request(data, "GET", ORDERS + config.order_id + "/"), data)
            if row["external_id"] != config.order_id:
                raise ParcelLabError("parcelLab returned a different order")
            if op == "get_order":
                return row
            body = {"account": account, "order_number": row["order_number"]}
            if row.get("client_key"):
                body["client_key"] = row["client_key"]
            if op == "update_order_tags":
                body["tags"] = [text(tag) for tag in config.tags]
            else:
                body["mutations"] = [{"type": "add_tracking", "tracking": {"courier": text(config.courier), "tracking_number": text(config.tracking_number), "notifications_inactive": config.notifications_inactive}}]
            payload = await request(data, "PUT", ORDERS, body=body, statuses=(200, 201))
            updated = order_result(payload, data)
            if updated["external_id"] != config.order_id:
                raise ParcelLabError("parcelLab returned a different updated order")
            if op == "add_tracking":
                mutations = payload.get("mutations")
                if (not isinstance(mutations, list) or len(mutations) != 1 or not isinstance(mutations[0], dict)
                        or mutations[0].get("type") != "add_tracking" or not isinstance(mutations[0].get("result"), dict)
                        or mutations[0]["result"].get("success") is not True):
                    raise ParcelLabError("parcelLab accepted the order request but did not confirm the tracking mutation")
            return {"order": updated, "write_acknowledged": True, "verified_readback": None}
        if op == "create_order":
            body = {"account": account, "order_number": text(config.order_number), "destination_country_iso3": config.destination_country_iso3, "recipient_email": config.recipient_email, "tags": [text(tag) for tag in config.tags]}
            if config.client_key:
                body["client_key"] = text(config.client_key)
            row = order_result(await request(data, "POST", ORDERS, body=body, statuses=(201,)), data)
            if row["order_number"] != config.order_number:
                raise ParcelLabError("parcelLab returned a different created order")
            return {"order": row, "created": True, "verified_readback": None}
        if op in {"get_order_status", "get_tracking_status"}:
            query = {"account": account, "lang": text(config.language, 5)}
            if op == "get_order_status":
                query["order_number"] = text(config.order_number)
                if config.client_key:
                    query["client_key"] = text(config.client_key)
            else:
                query.update(courier=text(config.courier), tracking_number=text(config.tracking_number), single_tracking="true")
            result = delivery_status(await request(data, "GET", ORDERS + "info/", params=query), data)
            if op == "get_order_status" and result["order_number"] != config.order_number:
                raise ParcelLabError("parcelLab returned a different order status")
            if op == "get_tracking_status" and (not result["trackings"] or any(row["tracking_number"] != config.tracking_number for row in result["trackings"])):
                raise ParcelLabError("parcelLab returned a different tracking status")
            return result
        if op == "get_return_configuration":
            result = configuration_result(await request(data, "GET", CONFIGS + str(config.configuration_id) + "/"), data)
            if result["id"] != config.configuration_id:
                raise ParcelLabError("parcelLab returned a different return configuration")
            return result
        if op in {"get_return", "get_return_status"}:
            row = return_result(await request(data, "GET", RETURNS + config.return_id + "/"), data)
            if row["external_id"] != config.return_id:
                raise ParcelLabError("parcelLab returned a different return registration")
            if op == "get_return":
                return row
            payload = await request(data, "GET", RETURNS + config.return_id + "/status/")
            if payload.get("return_status") not in {"cancelled", "complete", "in_transit", "invalid", "label_ready", "pending_approval", "pending_label", "processing_failed", "received", "registered", "rejected", "retention"} or any(type(payload.get(k)) is not bool for k in ("labels_available", "cancellable", "retention_offer_applied")):
                raise ParcelLabError("parcelLab returned unreadable return status")
            return {"return_id": config.return_id, **metadata(payload, data, ("return_status", "labels_available", "cancellable", "retention_offer_applied"))}
        if op == "predict_delivery":
            query = {"account": account, "destination_country_iso3": config.destination_country_iso3, "calibration": config.calibration}
            for key in ("destination_postal_code", "courier", "warehouse", "service_level"):
                if getattr(config, key):
                    query[key] = text(getattr(config, key))
            payload = await request(data, "GET", "/v4/promise/prediction/predict/", params=query)
            if type(payload.get("success")) is not bool or not isinstance(payload.get("prediction"), list) or len(payload["prediction"]) > 100:
                raise ParcelLabError("parcelLab returned unreadable delivery predictions")
            text(payload.get("request_id"))
            if payload["success"] is not True:
                raise ParcelLabError("parcelLab did not confirm a successful delivery prediction")
            rows = []
            for row in payload["prediction"]:
                if not isinstance(row, dict):
                    raise ParcelLabError("parcelLab returned unreadable delivery predictions")
                for key in ("id", "warehouse", "courier", "courier_name"):
                    text(row.get(key))
                if row.get("global_courier_service_level") not in {"standard", "unused", "express", "expedited", "unknown"}:
                    raise ParcelLabError("parcelLab returned unreadable courier service levels")
                details = row.get("prediction")
                if (not isinstance(details, dict) or any(type(details.get(k)) is not int for k in ("min", "max", "likely", "cutoff"))
                        or any(details[k] < 0 for k in ("min", "max", "likely"))):
                    raise ParcelLabError("parcelLab returned unreadable delivery prediction details")
                for key in ("send_date", "earliest_date", "latest_date", "most_likely_date"):
                    text(details.get(key))
                item = metadata(row, data, ("id", "warehouse", "courier", "courier_name", "global_courier_service_level"))
                item["prediction"] = metadata(details, data, ("min", "max", "likely", "send_date", "earliest_date", "latest_date", "most_likely_date", "cutoff"))
                rows.append(item)
            return {"request_id": scalar(payload.get("request_id"), data), "success": payload["success"], "predictions": rows}
        if op == "find_pudo_locations":
            body = {"account": account, "country_iso3": config.country_iso3, "location": {"type": "Point", "latitude": config.latitude, "longitude": config.longitude}, "lookups": [{"courier": text(config.courier), "criteria": [config.criterion], "max_distance": config.max_distance, "unit": config.distance_unit, "limit": config.limit}]}
            rows = await request(data, "POST", "/v4/track/place-info/lookup/", body=body, allow_list=True)
            if not isinstance(rows, list) or len(rows) > config.limit:
                raise ParcelLabError("parcelLab returned unreadable PUDO locations")
            return {"items": [place_result(row, data) for row in rows]}
        if op == "get_pudo_location":
            row = place_result(await request(data, "GET", "/v4/track/place-info/" + config.place_id + "/"), data)
            if row["external_id"] is not None and row["external_id"] != config.place_id:
                raise ParcelLabError("parcelLab returned a different PUDO location")
            return {"requested_place_id": config.place_id, **row}
        if op in {"get_survey", "submit_survey_response"}:
            route = "/v4/survey/survey/" + config.survey_id + "/"
            payload = await request(data, "GET", route)
            if uuid_value(payload.get("id")) != config.survey_id:
                raise ParcelLabError("parcelLab returned a different or unreadable survey")
            text(payload.get("name"))
            if op == "get_survey":
                return {"id": config.survey_id, **metadata(payload, data, ("name", "status", "archived", "type", "isEditable"))}
            payload = await request(data, "POST", route + "answer/", body={"reference_id": text(config.reference_id), "reference_type": config.reference_type, "data": config.answers, "is_complete": config.is_complete})
            if not isinstance(payload.get("detail"), str) or not payload["detail"] or ("isComplete" in payload and type(payload["isComplete"]) is not bool):
                raise ParcelLabError("parcelLab did not return a survey response acknowledgement")
            return {"survey_id": config.survey_id, "accepted": True, "is_complete": payload.get("isComplete"), "verified_readback": None}
        raise ValueError("Unsupported native parcelLab operation")
