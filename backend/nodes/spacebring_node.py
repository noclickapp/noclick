"""Native Spacebring customer network, space and booking metadata workflows.

Customer Basic credentials bind to one existing network. Metadata edits use
documented restricted bodies and verified readbacks; no billing or access edits.
"""
import base64
import hashlib
import json
import math
import re
from datetime import datetime, timedelta
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

ORIGIN = "https://api.spacebring.com"
MAX_BODY = 512 * 1024
RESOURCE_TYPES = {"dedicatedDesk", "equipment", "hotDesk", "office", "parkingLot", "room", "station", "conferenceRoom", "eventSpace", "meetingRoom", "phoneBooth", "studio"}
PATHS = {
    "GET": re.compile(r"/(?:networks/v1|locations/v1(?:/[0-9a-f-]{36})?|resources/v1(?:/[0-9a-f-]{36})?|community/memberships/v1(?:/[0-9a-f-]{36})?|resources/bookings/v1(?:/[A-Za-z0-9%_.:-]+)?)"),
    "PATCH": re.compile(r"/(?:resources/v1/[0-9a-f-]{36}|resources/bookings/v1/[A-Za-z0-9%_.:-]+)"),
    "POST": re.compile(r"/resources/v1/[0-9a-f-]{36}/availability"),
}


class SpacebringAPIError(RuntimeError):
    def __init__(self, message, *, status=None, provider_type=None, uncertain=False):
        super().__init__(message)
        self.http_status = status
        self.provider_type = provider_type
        self.uncertain = uncertain


def identifier(value):
    if not isinstance(value, str):
        raise ValueError("Use a Spacebring UUID from the selected network.")
    try:
        result = str(UUID(value))
    except Exception:
        raise ValueError("Use a Spacebring UUID from the selected network.") from None
    if value.lower() != result:
        raise ValueError("Use the canonical hyphenated Spacebring UUID.")
    return result


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("Use an ISO timestamp with an explicit timezone.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        raise ValueError("Use a valid ISO timestamp with an explicit timezone.") from None
    if parsed.tzinfo is None:
        raise ValueError("Use a timestamp with an explicit timezone.")
    return value


def booking_identifier(value):
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("Use the selected booking ID or documented occurrence ID.")
    parts = value.split("_", 1)
    result = identifier(parts[0])
    if len(parts) == 2:
        date = parts[1]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except Exception:
                raise ValueError("The booking occurrence date is invalid.") from None
        else:
            timestamp(date)
        result += "_" + date
    return result


def path_id(value, *, booking=False):
    return quote(booking_identifier(value) if booking else identifier(value), safe="")


def text(value, maximum=4096):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError("Spacebring returned invalid selected text metadata.")
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate Spacebring JSON field.")
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError("Non-finite Spacebring JSON number.")


def _bounded(value, depth=0):
    if depth > 14:
        raise ValueError("Spacebring response nesting exceeds the local limit.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Spacebring returned an unbounded JSON number.")
    if isinstance(value, (dict, list)):
        if len(value) > 1000:
            raise ValueError("Spacebring response container exceeds the local limit.")
        for child in value.values() if isinstance(value, dict) else value:
            _bounded(child, depth + 1)


def parse_json(payload):
    if not payload or len(payload) > MAX_BODY:
        raise ValueError("Spacebring returned an empty or oversized response.")
    try:
        value = json.loads(payload, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except Exception:
        raise ValueError("Spacebring returned invalid JSON.") from None
    if not isinstance(value, dict):
        raise ValueError("Spacebring returned an invalid response envelope.")
    _bounded(value)
    return value


def safe_selected(result, data):
    secrets = (data["client_id"], data["client_secret"], base64.b64encode((data["client_id"] + ":" + data["client_secret"]).encode()).decode())
    def visit(value):
        if isinstance(value, str):
            if any(secret and (secret in value or json.dumps(secret)[1:-1] in value) for secret in secrets):
                raise ValueError("The selected Spacebring result contains credential material.")
        elif isinstance(value, dict):
            for key, child in value.items():
                visit(key)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(result)
    return result


def scope(data, purpose, filters):
    return hashlib.sha256(json.dumps({"network": data["network_id"], "client": data["client_id"], "grant": hashlib.sha256(data["client_secret"].encode()).hexdigest(), "purpose": purpose, "filters": filters}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cursor(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or "://" in value or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("Spacebring returned an invalid opaque continuation cursor.")
    return value


def encode_page(native, binding):
    if native is None:
        return None
    value = json.dumps({"v": 1, "scope": binding, "cursor": cursor(native)}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def decode_page(token, binding):
    if token is None:
        return None
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 8192 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError()
        row = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True), object_pairs_hook=_pairs)
        if set(row) != {"v", "scope", "cursor"} or type(row["v"]) is not int or row["v"] != 1 or row["scope"] != binding:
            raise ValueError()
        return cursor(row["cursor"])
    except Exception:
        raise ValueError("This continuation belongs to a different Spacebring credential, parent or query. Start from the first page.") from None


async def request(data, method, path, *, params=None, body=None, expected=200, mutation=False):
    if method not in PATHS or not PATHS[method].fullmatch(path):
        raise ValueError("Unsupported native Spacebring operation.")
    encoded = json.dumps(body, allow_nan=False, separators=(",", ":")).encode() if body is not None else None
    if encoded is not None and len(encoded) > 16384:
        raise ValueError("The Spacebring request exceeds the local metadata limit.")
    headers = {"Accept": "application/json", "spacebring-network-id": data["network_id"]}
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, ORIGIN + path, params=params, content=encoded,
                    headers=headers, auth=httpx.BasicAuth(data["client_id"], data["client_secret"])) as response:
                status = response.status_code
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise SpacebringAPIError("Spacebring response exceeds the local limit.", status=status, uncertain=mutation)
                    chunks.append(chunk)
                payload = b"".join(chunks)
                if status != expected:
                    kind = None
                    if payload:
                        try:
                            error = parse_json(payload).get("type")
                            if isinstance(error, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", error) and all(secret not in error for secret in (data["client_id"], data["client_secret"])):
                                kind = error
                        except ValueError:
                            pass
                    raise SpacebringAPIError(f"Spacebring rejected the request or returned an unexpected HTTP status (HTTP {status}).", status=status, provider_type=kind,
                        uncertain=mutation and (status >= 500 or status in {200, 201, 202, 204, 429}))
                if expected == 204:
                    if payload:
                        raise SpacebringAPIError("Spacebring returned content for a no-content acknowledgement.", status=status, uncertain=mutation)
                    return {}
                if "application/json" not in response.headers.get("content-type", "").lower():
                    raise SpacebringAPIError("Spacebring returned an unexpected content type.", status=status, uncertain=mutation)
                try:
                    return parse_json(payload)
                except ValueError:
                    raise SpacebringAPIError("Spacebring returned an invalid bounded JSON result.", status=status, uncertain=mutation) from None
    except httpx.HTTPError:
        raise SpacebringAPIError("The Spacebring result could not be verified; do not replay a metadata write without reading it back.", uncertain=mutation) from None


def selected(row, kind, *, data, target=None, location=None, resource=None):
    if not isinstance(row, dict):
        raise ValueError("Spacebring returned an invalid selected object.")
    row_id = booking_identifier(row.get("id")) if kind == "booking" else identifier(row.get("id"))
    if target is not None and row_id != target:
        raise ValueError("Spacebring returned a different object than the selected ID.")
    result = {"id": row_id}
    if kind in {"location", "resource"}:
        if identifier(row.get("networkRef")) != data["network_id"]:
            raise ValueError("Spacebring returned an object from a different network.")
        result["networkRef"] = data["network_id"]
    if kind in {"resource", "membership"}:
        parent = identifier(row.get("locationRef"))
        if parent != location:
            raise ValueError("Spacebring returned an object from a different location.")
        result["locationRef"] = parent
    if kind == "booking":
        parent = identifier(row.get("resourceRef"))
        if parent != resource:
            raise ValueError("Spacebring returned a booking for a different resource.")
        result["resourceRef"] = parent
        for key in ("startDate", "endDate", "createDate"):
            result[key] = timestamp(row.get(key))
        if datetime.fromisoformat(result["endDate"].replace("Z", "+00:00")) <= datetime.fromisoformat(result["startDate"].replace("Z", "+00:00")):
            raise ValueError("Spacebring returned an invalid booking interval.")
        if not isinstance(row.get("attendees"), list):
            raise ValueError("Spacebring returned an invalid booking attendee envelope.")
    fields = {"network": ("title",), "location": ("title", "description", "timezoneId", "createDate"),
        "resource": ("title", "description", "type", "createDate"), "membership": ("type", "status", "createDate", "userRef", "companyRef"),
        "booking": ("title", "memo", "updateDate", "deleteDate")}[kind]
    for key in fields:
        if key not in row or row[key] is None:
            continue
        value = row[key]
        if key.endswith("Ref"):
            value = identifier(value)
        elif key.endswith("Date"):
            value = timestamp(value)
        else:
            value = text(value)
        result[key] = value
    if kind in {"network", "location", "resource"} and not result.get("title"):
        raise ValueError("Spacebring omitted the selected object's title.")
    if kind == "resource" and result.get("type") not in RESOURCE_TYPES:
        raise ValueError("Spacebring returned an unknown resource type.")
    if kind == "membership" and (result.get("type") not in {"member", "nonmember"} or result.get("status") not in {None, "requested", "approved"}):
        raise ValueError("Spacebring returned invalid membership metadata.")
    return safe_selected(result, data)


def page(body, key, kind, *, data, limit, binding=None, location=None, resource=None):
    rows = body.get(key)
    if not isinstance(rows, list) or len(rows) > (limit if binding else 1000):
        raise ValueError("Spacebring returned an invalid or oversized selected collection.")
    items = [selected(row, kind, data=data, location=location, resource=resource) for row in rows]
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("Spacebring returned duplicate object IDs in one page.")
    native = body.get("nextPageToken")
    if "nextPageToken" in body and (native is None or native == ""):
        raise ValueError("Spacebring returned an invalid continuation field; absence means no more pages.")
    if not binding and native is not None:
        raise ValueError("Continuation is not documented for this selected unpaged endpoint.")
    result = {"items": items[:limit], "next_page_token": encode_page(native, binding), "has_more": native is not None,
        "truncated": len(items) > limit, "network_id": data["network_id"]}
    return safe_selected(result, data)



class SpacebringBasicCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Spacebring Customer Basic Auth", json_schema_extra={
        "x-credential-url": "https://www.spacebring.com/docs/developer/api/authentication",
        "x-credential-instructions": "The Spacebring app owner retrieves the customer Client ID and Client Secret from the selected network's Settings > Developers. Supply that network's UUID. Native customer Basic authentication is separate from partner OAuth registration. Connection checks the returned network ID and title; it does not identify a human owner or prove write entitlement.",
    })
    credential_type: Literal["spacebring_basic"] = Field("spacebring_basic", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, max_length=256, title="Customer Client ID", json_schema_extra={"ui:widget": "password"})
    client_secret: str = Field(..., min_length=1, max_length=4096, title="Customer Client Secret", json_schema_extra={"ui:widget": "password"})
    network_id: str = Field(..., title="Network ID", description="Canonical UUID of the existing network belonging to these customer credentials.")

    @field_validator("network_id")
    @classmethod
    def network(cls, value):
        return identifier(value)

    @field_validator("client_id", "client_secret")
    @classmethod
    def issued_value(cls, value, info):
        if any(ord(c) < 33 or ord(c) > 126 for c in value) or "://" in value or (info.field_name == "client_id" and ":" in value):
            raise ValueError("Supply the issued customer credential without URLs, spaces or control characters.")
        return value


def credential_shape(data):
    try:
        return SpacebringBasicCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("The Spacebring customer credential is invalid.") from None


def op(name, label, category):
    return Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def dynamic(name, parents=None):
    options = {"field_name": name, "searchable": True, "allow_custom": True}
    if parents:
        options["depends_on"] = parents
    return {"x-dynamic-options": options}


class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetNetwork(OperationConfig):
    operation: Literal["get_network"] = op("get_network", "Get Connected Network", "Network")


class ListLocations(OperationConfig):
    operation: Literal["list_locations"] = op("list_locations", "List Locations", "Locations")
    limit: int = Field(100, ge=1, le=100, strict=True, description="Local output cap; the published locations endpoint has no continuation contract.")


class LocationTarget(OperationConfig):
    location_id: str = Field(..., title="Location", json_schema_extra=dynamic("location_id"))

    @field_validator("location_id")
    @classmethod
    def identifier(cls, value):
        return identifier(value)


class GetLocation(LocationTarget):
    operation: Literal["get_location"] = op("get_location", "Get Location Metadata", "Locations")


class Pagination(OperationConfig):
    limit: int = Field(25, ge=1, le=100, strict=True, title="Page Size")
    page_token: str | None = Field(None, max_length=8192, title="Continuation", description="Use this node's next_page_token with the identical credential, parents, filters and page size. Raw URLs and provider cursors are not accepted here.")


class ListResources(LocationTarget, Pagination):
    operation: Literal["list_resources"] = op("list_resources", "List Resource Metadata", "Resources")


class ResourceTarget(LocationTarget):
    resource_id: str = Field(..., title="Resource", json_schema_extra=dynamic("resource_id", ["location_id"]))

    @field_validator("resource_id")
    @classmethod
    def identifier(cls, value):
        return identifier(value)


class GetResource(ResourceTarget):
    operation: Literal["get_resource"] = op("get_resource", "Get Resource Metadata", "Resources")


class UpdateResourceMetadata(ResourceTarget):
    operation: Literal["update_resource_metadata"] = op("update_resource_metadata", "Update Resource Title or Description", "Resources")
    title: str | None = Field(None, min_length=1, max_length=256, title="New Title")
    description: str | None = Field(None, max_length=4096, title="New Description", json_schema_extra={"ui:widget": "textarea"})

    @model_validator(mode="after")
    def metadata(self):
        if self.title is None and self.description is None:
            raise ValueError("Supply a resource title or description to update.")
        for value in (self.title, self.description):
            if value is not None:
                text(value)
        return self


class TimeWindow(OperationConfig):
    start_time: str = Field(..., title="Start Time", description="ISO timestamp with Z or explicit UTC offset.")
    end_time: str = Field(..., title="End Time")

    @model_validator(mode="after")
    def interval(self):
        timestamp(self.start_time)
        timestamp(self.end_time)
        start = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
        if not timedelta(0) < end - start <= timedelta(days=31):
            raise ValueError("Use an ordered, timezone-aware interval of at most 31 days.")
        return self


class CheckResourceAvailability(ResourceTarget, TimeWindow):
    operation: Literal["check_resource_availability"] = op("check_resource_availability", "Check Resource Availability", "Resources")
    quantity: int = Field(1, ge=1, le=1000, strict=True, title="Seats to Check", description="Read-only availability check. No booking or payment is created.")


class ListBookings(ResourceTarget, TimeWindow, Pagination):
    operation: Literal["list_bookings"] = op("list_bookings", "List Resource Booking Metadata", "Bookings")


class BookingTarget(ResourceTarget):
    booking_id: str = Field(..., title="Booking", json_schema_extra=dynamic("booking_id", ["location_id", "resource_id"]))

    @field_validator("booking_id")
    @classmethod
    def identifier(cls, value):
        return booking_identifier(value)


class GetBooking(BookingTarget):
    operation: Literal["get_booking"] = op("get_booking", "Get Booking Metadata", "Bookings")


class UpdateBookingMetadata(BookingTarget):
    operation: Literal["update_booking_metadata"] = op("update_booking_metadata", "Update Booking Title or Memo", "Bookings")
    title: str | None = Field(None, max_length=256, title="New Booking Title")
    memo: str | None = Field(None, max_length=4096, title="New Internal Memo", json_schema_extra={"ui:widget": "textarea"})

    @model_validator(mode="after")
    def metadata(self):
        if self.title is None and self.memo is None:
            raise ValueError("Supply a booking title or memo to update.")
        for value in (self.title, self.memo):
            if value is not None:
                text(value)
        return self


class ListMemberships(LocationTarget, Pagination):
    operation: Literal["list_memberships"] = op("list_memberships", "List Membership Metadata", "Members")
    membership_type: Literal["member", "nonmember"] | None = Field(None, title="Membership Type")


class GetMembership(LocationTarget):
    operation: Literal["get_membership"] = op("get_membership", "Get Membership Metadata", "Members")
    membership_id: str = Field(..., title="Membership", json_schema_extra=dynamic("membership_id", ["location_id"]))

    @field_validator("membership_id")
    @classmethod
    def identifier(cls, value):
        return identifier(value)


SpacebringConfig = Annotated[Union[GetNetwork, ListLocations, GetLocation, ListResources, GetResource, UpdateResourceMetadata,
    CheckResourceAvailability, ListBookings, GetBooking, UpdateBookingMetadata, ListMemberships, GetMembership], Field(discriminator="operation")]


class SpacebringFullConfig(NodeConfig):
    model_config = ConfigDict(hide_input_in_errors=True)
    credentials: SpacebringBasicCredential | None = None
    config: SpacebringConfig


async def get_network(data):
    body = await request(data, "GET", "/networks/v1")
    rows = body.get("networks")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Spacebring returned an invalid bounded network collection.")
    selected_rows = [selected(row, "network", data=data) for row in rows]
    matches = [row for row in selected_rows if row["id"] == data["network_id"]]
    if len(matches) != 1:
        raise ValueError("The configured Spacebring network was not uniquely returned for this customer credential.")
    return matches[0]


async def get_location(data, location):
    body = await request(data, "GET", "/locations/v1/" + path_id(location))
    return selected(body.get("location"), "location", data=data, target=location)


async def get_resource(data, location, resource):
    body = await request(data, "GET", "/resources/v1/" + path_id(resource))
    return selected(body.get("resource"), "resource", data=data, target=resource, location=location)


async def get_booking(data, location, resource, booking):
    body = await request(data, "GET", "/resources/bookings/v1/" + path_id(booking, booking=True))
    return selected(body.get("booking"), "booking", data=data, target=booking, location=location, resource=resource)


async def collection(data, *, purpose, path, key, kind, filters, limit, token, location=None, resource=None):
    params = {**filters, "limit": limit}
    binding = scope(data, purpose, params)
    native = decode_page(token, binding)
    if native is not None:
        params["nextPageToken"] = native
    body = await request(data, "GET", path, params=params)
    result = page(body, key, kind, data=data, limit=limit, binding=binding, location=location, resource=resource)
    if native is not None and body.get("nextPageToken") == native:
        raise ValueError("Spacebring repeated its continuation cursor; further paging is refused.")
    return result


class SpacebringNode(WorkflowNode):
    integration_type = "automation-spacebring"
    connection_evidence = ConnectionEvidence(identity_operation="get_network", noun="network", proves="account", identity_keys=("title",))

    @classmethod
    def get_config_model(cls):
        return SpacebringFullConfig

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            network = await get_network(credential_shape(credential_data))
            return {"valid": True, "proves": "account", "account_label": network["title"]}
        except SpacebringAPIError as exc:
            return {"valid": False if exc.http_status in {401, 403} else None,
                    "error": str(exc), "status_code": exc.http_status}
        except ValueError:
            return {"valid": None, "error": "The Spacebring network could not be verified."}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"location_id", "resource_id", "booking_id", "membership_id"}:
            return {"options": [], "next_page_token": None}
        credential_data = credential_shape(credential_data)
        context = context or {}
        token = page_token if page_token is not None else context.get("page_token")
        search = search if search is not None else context.get("search") or ""
        if not isinstance(search, str) or len(search) > 100:
            raise ValueError("Use a bounded current-page metadata search.")
        if field_name == "location_id":
            if token is not None:
                raise ValueError("The locations picker has no documented continuation contract.")
            body = await request(credential_data, "GET", "/locations/v1")
            result = page(body, "locations", "location", data=credential_data, limit=100)
        else:
            location = identifier(context.get("location_id"))
            await get_location(credential_data, location)
            filters = {"locationRef": location}
            resource = None
            if field_name == "resource_id":
                path, key, kind = "/resources/v1", "resources", "resource"
            elif field_name == "membership_id":
                path, key, kind = "/community/memberships/v1", "memberships", "membership"
            else:
                resource = identifier(context.get("resource_id"))
                await get_resource(credential_data, location, resource)
                filters["resourceRef"] = resource
                path, key, kind = "/resources/bookings/v1", "bookings", "booking"
            result = await collection(credential_data, purpose="picker-" + field_name, path=path, key=key, kind=kind,
                filters=filters, limit=50, token=token, location=location, resource=resource)
        options = [{"value": row["id"], "label": row.get("title") or row["id"]} for row in result["items"]
            if not search or search.casefold() in (row.get("title") or row["id"]).casefold()]
        return {"options": options, "next_page_token": result["next_page_token"], "truncated": result["truncated"], "search_scope": "current bounded metadata page"}

    async def execute(self, inputs):
        acknowledged = False
        target_id = None
        try:
            if not isinstance(self.config, SpacebringFullConfig) or self.config.credentials is None:
                raise ValueError("Select the Spacebring customer credential and native operation.")
            config = self.config.config
            # Staging resolves the current saved credential and admits this call
            # at the shared run boundary; customer Basic credentials do not refresh.
            data = credential_shape(self.config.credentials.model_dump())
            if isinstance(config, GetNetwork):
                result = {"network": await get_network(data)}
            elif isinstance(config, ListLocations):
                result = page(await request(data, "GET", "/locations/v1"), "locations", "location", data=data, limit=config.limit)
            else:
                location = config.location_id
                selected_location = await get_location(data, location)
                if isinstance(config, GetLocation):
                    result = {"location": selected_location}
                elif isinstance(config, ListResources):
                    result = await collection(data, purpose=config.operation, path="/resources/v1", key="resources", kind="resource",
                        filters={"locationRef": location}, limit=config.limit, token=config.page_token, location=location)
                elif isinstance(config, ListMemberships):
                    filters = {"locationRef": location}
                    if config.membership_type:
                        filters["types"] = config.membership_type
                    result = await collection(data, purpose=config.operation, path="/community/memberships/v1", key="memberships", kind="membership",
                        filters=filters, limit=config.limit, token=config.page_token, location=location)
                elif isinstance(config, GetMembership):
                    body = await request(data, "GET", "/community/memberships/v1/" + path_id(config.membership_id))
                    result = {"membership": selected(body.get("membership"), "membership", data=data, target=config.membership_id, location=location)}
                else:
                    resource = config.resource_id
                    selected_resource = await get_resource(data, location, resource)
                    if isinstance(config, GetResource):
                        result = {"resource": selected_resource}
                    elif isinstance(config, UpdateResourceMetadata):
                        updates = {key: value for key, value in (("title", config.title), ("description", config.description)) if value is not None}
                        await request(data, "PATCH", "/resources/v1/" + path_id(resource), body={"resource": updates}, expected=204, mutation=True)
                        acknowledged, target_id = True, resource
                        row = await get_resource(data, location, resource)
                        if any(row.get(key) != value for key, value in updates.items()):
                            raise ValueError("The acknowledged resource metadata did not match its readback.")
                        result = {"resource": row, "readback_verified": True}
                    elif isinstance(config, CheckResourceAvailability):
                        body = await request(data, "POST", "/resources/v1/" + path_id(resource) + "/availability",
                            body={"startDate": config.start_time, "endDate": config.end_time, "quantity": config.quantity})
                        if type(body.get("available")) is not bool:
                            raise ValueError("Spacebring omitted a boolean resource availability result.")
                        result = {"resource_id": resource, "location_id": location, "available": body["available"]}
                        if body["available"] is False:
                            reason = body.get("reason")
                            if not isinstance(reason, dict) or not isinstance(reason.get("code"), str) or not isinstance(reason.get("message"), str):
                                raise ValueError("Spacebring omitted the unavailable-slot reason.")
                            result["reason_code"] = text(reason["code"], 100)
                    elif isinstance(config, ListBookings):
                        result = await collection(data, purpose=config.operation, path="/resources/bookings/v1", key="bookings", kind="booking",
                            filters={"locationRef": location, "resourceRef": resource, "startDate[gte]": config.start_time, "startDate[lt]": config.end_time},
                            limit=config.limit, token=config.page_token, location=location, resource=resource)
                    elif isinstance(config, (GetBooking, UpdateBookingMetadata)):
                        row = await get_booking(data, location, resource, config.booking_id)
                        if isinstance(config, UpdateBookingMetadata):
                            updates = {key: value for key, value in (("title", config.title), ("memo", config.memo)) if value is not None}
                            body = await request(data, "PATCH", "/resources/bookings/v1/" + path_id(config.booking_id, booking=True),
                                body={"booking": {**updates, "sendUpdates": "none"}, "updateRepeatingScope": "singleOccurrence"}, mutation=True)
                            acknowledged, target_id = True, config.booking_id
                            selected(body.get("booking"), "booking", data=data, target=config.booking_id, location=location, resource=resource)
                            row = await get_booking(data, location, resource, config.booking_id)
                            if any(row.get(key) != value for key, value in updates.items()):
                                raise ValueError("The acknowledged booking metadata did not match its readback.")
                        result = {"booking": row, "readback_verified": True} if acknowledged else {"booking": row}
                    else:
                        raise ValueError("Unsupported native Spacebring metadata operation.")
            return {"status": "success", "operation": config.operation, "data": safe_selected(result, data)}
        except Exception as exc:
            message = "The metadata write was acknowledged but its readback is unverified; inspect the selected object before retrying." if acknowledged else (
                str(exc) if isinstance(exc, (ValueError, SpacebringAPIError)) else "The native Spacebring result could not be verified.")
            return {"status": "error", "error": message, "status_code": getattr(exc, "http_status", None),
                "provider_type": getattr(exc, "provider_type", None), "write_outcome_uncertain": acknowledged or bool(getattr(exc, "uncertain", False)),
                "acknowledged_object_id": target_id}
