"""HERE Tracking operations, pinned to the provider's 2.1.191 OpenAPI contract.

Use an existing user bearer token. Device-token signing and token issuance are
outside this integration; a device token cannot access these user endpoints.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://tracking.api.here.com"
DOCS = "https://developer.here.com/documentation/tracking/swagger/swagger.json"
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
LOCATION_PATTERN = r"^LOC-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class HereUserTokenCredential(BaseModel):
    model_config = ConfigDict(title="HERE Tracking User Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS,
            "x-credential-instructions": "Paste an existing HERE Tracking user access token obtained with /users/v2/login or /users/v2/tokenExchange. Use a user token, not an API key or a device token. Tokens expire; replace the token when it expires. For membership in multiple projects, enter the project ID. NoClick checks the project's claimed devices.",
        })
    credential_type: Literal["here_user_token"] = Field("here_user_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192,
        json_schema_extra={"ui:widget": "password"})
    project_id: Optional[str] = Field(None, title="Project ID", min_length=1, max_length=50,
        description="Optional for a single project; required by HERE when your user belongs to multiple projects.")

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="User access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the user token, without the Bearer prefix")
        return value


class Point(Closed):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class Floor(Closed):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    level: Optional[float] = Field(None, ge=-999, le=999)


class CircleDefinition(Closed):
    center: Point
    radius: float = Field(..., ge=0, description="Radius in metres")
    floor: Optional[Floor] = None


class PolygonDefinition(Closed):
    points: list[Point] = Field(..., min_length=3, max_length=10)
    floor: Optional[Floor] = None


class POILocation(Closed):
    address: Optional[str] = Field(None, min_length=1, max_length=255)
    country: Optional[str] = Field(None, min_length=1, max_length=255)
    position: Optional[Point] = None
    room: Optional[str] = Field(None, min_length=1, max_length=100)


class POIDefinition(Closed):
    floor: Optional[Floor] = None
    location: Optional[POILocation] = None


class Named(Closed):
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=1000)


class CircleGeofence(Named):
    type: Literal["circle"]
    definition: CircleDefinition


class PolygonGeofence(Named):
    type: Literal["polygon"]
    definition: PolygonDefinition


class POIGeofence(Named):
    type: Literal["poi"]
    definition: Optional[POIDefinition] = None


Geofence = Annotated[Union[CircleGeofence, PolygonGeofence, POIGeofence], Field(discriminator="type")]


class Address(Closed):
    street: Optional[str] = None
    city: Optional[str] = None
    postalCode: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None


class LocationBody(Closed):
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=1000)
    location: Optional[Point] = None
    geofenceId: Optional[str] = Field(None, pattern="^" + UUID_PATTERN + "$")
    address: Optional[Address] = None
    externalLocationId: Optional[str] = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def coordinates_or_geofence(self):
        if self.location is None and self.geofenceId is None:
            raise ValueError("Provide location coordinates or a geofenceId")
        return self


class DurationThreshold(Closed):
    durationS: int = Field(..., ge=0, le=2147483647)


class StockThreshold(Closed):
    minVolume: Optional[int] = Field(None, ge=0)
    maxVolume: Optional[int] = Field(None, ge=0)


class ScheduleThreshold(Closed):
    before: Optional[int] = Field(None, ge=0, le=2147483647)
    after: Optional[int] = Field(None, ge=0, le=2147483647)


class DurationRule(Named):
    type: Literal["utilization", "detention", "dwelling"]
    threshold: DurationThreshold


class StockRule(Named):
    type: Literal["stock"]
    geofenceId: str = Field(..., pattern="^" + UUID_PATTERN + "$")
    threshold: StockThreshold


class OnlineRule(Named):
    type: Literal["online"]


class ShipmentScheduleRule(Named):
    type: Literal["shipmentSchedule"]
    threshold: ScheduleThreshold


Rule = Annotated[Union[DurationRule, StockRule, OnlineRule, ShipmentScheduleRule], Field(discriminator="type")]


class Page(Closed):
    page_token: Optional[str] = Field(None, max_length=8192, description="Opaque next_page_token returned by the previous call; leave empty for the first page.")
    page_size: int = Field(100, ge=1, le=100)


class Device(Closed):
    tracking_id: str = Field(..., min_length=1, max_length=50, description="Physical tracking ID or virtual device external ID.")
    app_id: Optional[str] = Field(None, min_length=8, description="Application ID, needed when using a virtual device external ID.")

    @field_validator("tracking_id")
    @classmethod
    def safe_id(cls, value):
        if value in {".", ".."} or re.search(r"[/%?#\x00-\x20\x7f]", value):
            raise ValueError("Use a tracking ID, not a URL or path")
        return value


class GeofenceID(Closed):
    geofence_id: str = Field(..., pattern="^" + UUID_PATTERN + "$", description="Geofence UUID")


class LocationID(Closed):
    location_id: str = Field(..., pattern=LOCATION_PATTERN)


class RuleID(Closed):
    rule_id: str = Field(..., pattern="^" + UUID_PATTERN + "$", description="Rule UUID")


class ListDevices(Page):
    """List devices claimed by the selected project."""
    operation: Literal["list_devices"] = "list_devices"


class ListShadows(Page):
    """List the latest device states in the selected project."""
    operation: Literal["list_shadows"] = "list_shadows"
    sort: Optional[str] = Field(None, pattern=r"^(trackingId|reported.timestamp|desired.timestamp):(asc|desc)$")


class GetShadow(Device):
    """Get a device's desired and reported state."""
    operation: Literal["get_shadow"] = "get_shadow"


class GetTraces(Device, Page):
    """Read one page of historical device positions and telemetry."""
    operation: Literal["get_traces"] = "get_traces"
    before: Optional[float] = Field(None, ge=1, description="Unix timestamp in milliseconds")
    after: Optional[float] = Field(None, ge=0, description="Unix timestamp in milliseconds")
    outliers: Optional[bool] = None
    smooth: Optional[bool] = None
    mode: Optional[Literal["unknown", "normal", "flight", "transport", "sleep"]] = None

    @model_validator(mode="after")
    def time_order(self):
        if self.before is not None and self.after is not None and self.before <= self.after:
            raise ValueError("before must be later than after")
        return self


class ListGeofences(Page):
    """List geofences in the selected project."""
    operation: Literal["list_geofences"] = "list_geofences"


class GetGeofence(GeofenceID):
    operation: Literal["get_geofence"] = "get_geofence"


class CreateGeofence(Closed):
    """Create a circle, polygon or POI geofence."""
    operation: Literal["create_geofence"] = "create_geofence"
    geofence: Geofence


class UpdateGeofence(GeofenceID):
    """Replace a geofence definition."""
    operation: Literal["update_geofence"] = "update_geofence"
    geofence: Geofence


class DeleteGeofence(GeofenceID):
    operation: Literal["delete_geofence"] = "delete_geofence"


class ListLocations(Page):
    """List locations in the selected project."""
    operation: Literal["list_locations"] = "list_locations"
    name: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    geofence_id: Optional[str] = Field(None, pattern="^" + UUID_PATTERN + "$")


class GetLocation(LocationID):
    operation: Literal["get_location"] = "get_location"


class CreateLocation(Closed):
    operation: Literal["create_location"] = "create_location"
    location: LocationBody


class UpdateLocation(LocationID):
    """Replace a location, specifying coordinates or a geofence."""
    operation: Literal["update_location"] = "update_location"
    location: LocationBody


class DeleteLocation(LocationID):
    operation: Literal["delete_location"] = "delete_location"


class ListRules(Page):
    operation: Literal["list_rules"] = "list_rules"


class GetRule(RuleID):
    operation: Literal["get_rule"] = "get_rule"


class CreateRule(Closed):
    """Create a dwelling, detention, utilization, stock, online or shipment schedule rule."""
    operation: Literal["create_rule"] = "create_rule"
    rule: Rule


class UpdateRule(RuleID):
    """Replace an existing rule."""
    operation: Literal["update_rule"] = "update_rule"
    rule: Rule


class DeleteRule(RuleID):
    operation: Literal["delete_rule"] = "delete_rule"


class GetDeviceMetadata(Device):
    operation: Literal["get_device_metadata"] = "get_device_metadata"


class SetDeviceMetadata(Device):
    """Create or replace the device's metadata object (at most 1 KB)."""
    operation: Literal["set_device_metadata"] = "set_device_metadata"
    metadata: dict[str, Any] = Field(..., json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})

    @field_validator("metadata")
    @classmethod
    def size(cls, value):
        if len(json.dumps(value, separators=(",", ":"), allow_nan=False).encode()) > 1000:
            raise ValueError("Metadata must fit in 1000 bytes of JSON")
        return value


Operation = Annotated[Union[ListDevices, ListShadows, GetShadow, GetTraces,
    ListGeofences, GetGeofence, CreateGeofence, UpdateGeofence, DeleteGeofence,
    ListLocations, GetLocation, CreateLocation, UpdateLocation, DeleteLocation,
    ListRules, GetRule, CreateRule, UpdateRule, DeleteRule, GetDeviceMetadata,
    SetDeviceMetadata], Field(discriminator="operation")]


class HereConfig(NodeConfig[Operation, HereUserTokenCredential]):
    pass


# Each operation maps to exactly one published method/path. Only collection
# routes explicitly declaring projectId receive that query parameter.
ROUTES = {
    "list_devices": ("GET", "/users/v2/devices"),
    "list_shadows": ("GET", "/shadows/v4"),
    "get_shadow": ("GET", "/shadows/v2/{trackingId}"),
    "get_traces": ("GET", "/traces/v2/{trackingId}"),
    "list_geofences": ("GET", "/geofences/v2"),
    "get_geofence": ("GET", "/geofences/v2/{geofenceId}"),
    "create_geofence": ("POST", "/geofences/v2"),
    "update_geofence": ("PUT", "/geofences/v2/{geofenceId}"),
    "delete_geofence": ("DELETE", "/geofences/v2/{geofenceId}"),
    "list_locations": ("GET", "/locations/v4"),
    "get_location": ("GET", "/locations/v4/{locationId}"),
    "create_location": ("POST", "/locations/v4"),
    "update_location": ("PUT", "/locations/v4/{locationId}"),
    "delete_location": ("DELETE", "/locations/v4/{locationId}"),
    "list_rules": ("GET", "/rules/v4"),
    "get_rule": ("GET", "/rules/v4/{ruleId}"),
    "create_rule": ("POST", "/rules/v4"),
    "update_rule": ("PUT", "/rules/v4/{ruleId}"),
    "delete_rule": ("DELETE", "/rules/v4/{ruleId}"),
    "get_device_metadata": ("GET", "/metadata/v2/devices/{trackingId}"),
    "set_device_metadata": ("PUT", "/metadata/v2/devices/{trackingId}"),
}
PAGE_KEYS = {"list_devices": ("data", "count", "pageToken"),
    "get_traces": ("data", "count", "pageToken"),
    "list_geofences": ("data", "count", "pageToken"),
    "list_shadows": ("items", "limit", "nextPageToken"),
    "list_locations": ("items", "limit", "nextPageToken"),
    "list_rules": ("items", "limit", "nextPageToken")}


def redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [redact(v, token) for v in value]
    if isinstance(value, dict):
        return {redact(k, token): redact(v, token) for k, v in value.items()}
    return value


class HereNode(WorkflowNode):
    integration_type = "automation-here"
    connection_evidence = ConnectionEvidence(noun="claimed devices", operation="list_devices",
        label_keys=("trackingId", "externalId", "id"))

    @classmethod
    def get_config_model(cls):
        return HereConfig

    async def execute(self, inputs):
        config = self.config.config
        auth = self.config.credentials
        if not auth:
            raise ValueError("Connect a HERE Tracking user token")
        operation = config.operation
        method, route = ROUTES[operation]
        for field, parameter in (("tracking_id", "trackingId"), ("geofence_id", "geofenceId"),
                ("location_id", "locationId"), ("rule_id", "ruleId")):
            if "{" + parameter + "}" in route:
                route = route.replace("{" + parameter + "}", quote(getattr(config, field), safe=""))
        params = {}
        if "{" not in ROUTES[operation][1] and auth.project_id:
            params["projectId"] = auth.project_id
        if isinstance(config, Device) and config.app_id:
            params["appId"] = config.app_id
        if operation in PAGE_KEYS:
            params[PAGE_KEYS[operation][1]] = config.page_size
            if config.page_token:
                params["pageToken"] = config.page_token
        for field in ("before", "after", "outliers", "smooth", "mode", "sort", "name", "city", "country"):
            value = getattr(config, field, None)
            if value is not None:
                params[field] = str(value).lower() if isinstance(value, bool) else value
        if operation == "list_locations" and config.geofence_id:
            params["geofenceId"] = config.geofence_id
        body = None
        if operation.startswith(("create_", "update_")):
            field = operation.split("_", 1)[1]
            body = getattr(config, field).model_dump(exclude_none=True)
        elif operation == "set_device_metadata":
            body = config.metadata
        headers = {"Authorization": "Bearer " + auth.access_token, "Accept": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + route, params=params, headers=headers,
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = "HERE rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("message") or error.get("error") or message
            except ValueError:
                pass
            raise ValueError(redact(f"HERE HTTP {response.status_code}: {str(message)[:2000]}", auth.access_token))
        output = {"operation": operation, "status": "success", "http_status": response.status_code}
        if response.status_code == 204:
            return {**output, "acknowledged": True}
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("HERE returned a non-JSON response")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("HERE returned invalid JSON") from None
        if not isinstance(data, dict) or data.get("error"):
            raise ValueError("HERE returned an invalid response or an error envelope")
        data = redact(data, auth.access_token)
        if operation in PAGE_KEYS:
            key, _, cursor_key = PAGE_KEYS[operation]
            items = data.get(key)
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("HERE returned an invalid resource page")
            cursor = data.get(cursor_key)
            if cursor is not None and not isinstance(cursor, str):
                raise ValueError("HERE returned an invalid pagination token")
            if cursor and cursor == config.page_token:
                raise ValueError("HERE returned a non-advancing pagination token")
            return {**output, "items": items, "next_page_token": cursor or None,
                "count": data.get("count", len(items))}
        required = {"get_geofence": ("id", "geofence"), "update_geofence": ("id", "geofence"),
            "create_geofence": ("id",), "get_location": ("locationId",),
            "update_location": ("locationId",), "create_location": ("locationId",),
            "get_rule": ("ruleId", "rule"), "update_rule": ("ruleId", "rule"),
            "create_rule": ("ruleId",), "get_device_metadata": ("id", "data"),
            "set_device_metadata": ("id", "data")}.get(operation, ())
        if any(key not in data for key in required):
            raise ValueError("HERE returned an incomplete resource response")
        return {**output, "data": data}
