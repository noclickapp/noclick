"""Geoapify location workflows using the provider's published OpenAPI contracts.

Each operation performs one request. Batch submissions return pending jobs;
call the matching get operation later. No automatic polling or retries of writes.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from ipaddress import ip_address
from datetime import datetime
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-geoapify"
BASE_URL = "https://api.geoapify.com"

Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Position = tuple[Longitude, Latitude]
GeometryID = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Text = Annotated[str, Field(min_length=1, max_length=2048)]
FilterRule = Annotated[str, Field(pattern=r"^(rect|circle|countrycode|place):.+", max_length=2048)]
BiasRule = Annotated[str, Field(pattern=r"^(proximity|rect|circle|countrycode):.+", max_length=2048)]
RouteAvoid = Annotated[str, Field(pattern=r"^(tolls|ferries|highways|green_zones|transfers|location|polygon|country_codes)(:.*)?$", max_length=2048)]
IsolineAvoid = Annotated[str, Field(pattern=r"^(tolls|ferries|highways|green_zones|transfers|location|location_lonlat|location_latlon|polygon|polygon_lonlat|polygon_latlon|country_codes)(:.*)?$", max_length=2048)]
Mode = Literal["walk", "hike", "scooter", "motorcycle", "drive", "light_truck",
    "bicycle", "mountain_bike", "road_bike", "bus", "medium_truck", "truck",
    "truck_dangerous_goods", "heavy_truck", "long_truck"]


class GeoapifyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Geoapify API Key",
        json_schema_extra={
            "x-credential-url": "https://myprojects.geoapify.com/",
            "x-credential-instructions": "Open your project in Geoapify MyProjects, select API Keys, and paste an API key. Allow NoClick's server requests in any key restrictions. NoClick sends it only to api.geoapify.com in the x-api-key header. Connecting uses one IP Geolocation credit and proves key acceptance, not account identity.",
        })
    credential_type: Literal["geoapify_api_key"] = Field("geoapify_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Coordinates(Input):
    lat: Latitude
    lon: Longitude


class GeocodeAddress(Input):
    """Find coordinates and address metadata from a free-text address."""
    operation: Literal["geocode_address"] = "geocode_address"
    text: Text
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")
    limit: int = Field(5, ge=1, le=100)
    filter: list[FilterRule] | None = Field(None, max_length=20, description="Provider filters, for example countrycode:de or circle:lon,lat,radius.")
    bias: list[BiasRule] | None = Field(None, max_length=20, description="Provider bias rules, for example proximity:lon,lat.")


class ReverseGeocode(Coordinates):
    """Find an address at latitude and longitude."""
    operation: Literal["reverse_geocode"] = "reverse_geocode"
    limit: int = Field(1, ge=1, le=100)
    type: Literal["country", "state", "city", "postcode", "street", "amenity", "locality", "building"] | None = None
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")


class AutocompleteAddress(Input):
    """Complete a partial address query."""
    operation: Literal["autocomplete_address"] = "autocomplete_address"
    text: Text
    limit: int = Field(5, ge=1, le=100)
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")
    filter: list[FilterRule] | None = Field(None, max_length=20)
    bias: list[BiasRule] | None = Field(None, max_length=20)


class GetIPLocation(Input):
    """Locate an IP; omitting it locates NoClick's outbound server address."""
    operation: Literal["get_ip_location"] = "get_ip_location"
    ip: str | None = None
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")

    @field_validator("ip")
    @classmethod
    def address(cls, value):
        return str(ip_address(value)) if value is not None else None


class SearchPlaces(Input):
    """Search place categories in a spatial filter; use offset for the next page."""
    operation: Literal["search_places"] = "search_places"
    categories: list[Text] = Field(..., min_length=1, max_length=100,
        description="Geoapify category keys, for example catering.restaurant or commercial.supermarket.")
    filter: Text = Field(..., description="Provider spatial filter, for example circle:13.405,52.52,1000.")
    conditions: list[Text] | None = Field(None, min_length=1, max_length=100)
    bias: Text | None = None
    name: Text | None = None
    limit: int = Field(20, ge=1, le=500)
    offset: int = Field(0, ge=0)
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")


class GetPlaceDetails(Input):
    """Read details for a place ID returned by geocoding or places search."""
    operation: Literal["get_place_details"] = "get_place_details"
    id: str = Field(..., min_length=3, max_length=2048)
    features: list[Literal["details", "building", "radius_100", "radius_500", "radius_1000", "walk_5", "walk_10", "walk_15", "walk_30", "drive_5", "drive_10", "drive_15"]] | None = Field(None, min_length=1, max_length=30,
        description="Documented feature IDs, such as details, building or radius_500.")
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")


class CalculateRoute(Input):
    """Calculate directions; waypoints use latitude,longitude order."""
    operation: Literal["calculate_route"] = "calculate_route"
    waypoints: list[Annotated[str, Field(pattern=r"^-?(?:90(?:\.0+)?|[0-8]?\d(?:\.\d+)?),-?(?:180(?:\.0+)?|(?:1[0-7]\d|[0-9]?\d)(?:\.\d+)?)$")]] = Field(..., min_length=2, max_length=1000)
    mode: Mode = "drive"
    units: Literal["metric", "imperial"] = "metric"
    type: Literal["balanced", "short", "less_maneuvers"] = "balanced"
    avoid: list[RouteAvoid] | None = Field(None, max_length=100)
    details: list[Literal["instruction_details", "route_details", "elevation", "admin_areas", "polyline5", "polyline6"]] | None = None
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")


class CalculateIsoline(Coordinates):
    """Calculate time or distance reachability areas."""
    operation: Literal["calculate_isoline"] = "calculate_isoline"
    range: list[Annotated[float, Field(ge=1, allow_inf_nan=False)]] = Field(..., min_length=1, max_length=10)
    type: Literal["time", "distance"] = "time"
    mode: Mode = "drive"
    units: Literal["metric", "imperial"] = "metric"
    avoid: list[IsolineAvoid] | None = Field(None, max_length=100)


class MatrixLocation(Input):
    location: Position = Field(..., description="Longitude, latitude.")


class CalculateRouteMatrix(Input):
    """Calculate travel distances and times between sources and targets."""
    operation: Literal["calculate_route_matrix"] = "calculate_route_matrix"
    mode: Mode = "drive"
    sources: list[MatrixLocation] = Field(..., min_length=1, max_length=1000)
    targets: list[MatrixLocation] = Field(..., min_length=1, max_length=1000)
    units: Literal["metric", "imperial"] = "metric"
    type: Literal["balanced", "short", "less_maneuvers"] = "balanced"
    traffic: Literal["free_flow", "approximated"] = "free_flow"


class GetElevations(Input):
    """Get terrain elevations for ordered longitude,latitude locations."""
    operation: Literal["get_elevations"] = "get_elevations"
    locations: list[Position | Coordinates] = Field(..., min_length=1, max_length=1000)
    units: Literal["metric", "imperial"] = "metric"
    includeDistance: bool = False


class GetTimezone(Coordinates):
    """Read timezone and UTC offset, optionally at an RFC3339 instant."""
    operation: Literal["get_timezone"] = "get_timezone"
    at: str | None = Field(None, description="RFC3339 date and time, for example 2026-03-29T01:30:00Z.")


    @field_validator("at")
    @classmethod
    def instant(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None or "T" not in value:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an RFC3339 instant with a timezone offset") from None
        return value


class SearchPostcodes(Input):
    """Find a postcode and its boundary within a country."""
    operation: Literal["search_postcodes"] = "search_postcodes"
    postcode: Text
    countrycode: str = Field(..., pattern=r"^[a-z]{2}$")
    geometry: Literal["point", "original"] = "point"


class ListPostcodes(Input):
    """List postcodes matching text; request subsequent pages with offset."""
    operation: Literal["list_postcodes"] = "list_postcodes"
    text: Text
    countrycode: str = Field(..., pattern=r"^[a-z]{2}$")
    limit: int = Field(5, ge=1, le=500)
    offset: int = Field(0, ge=0)
    geometry: Literal["point", "original"] = "point"


class GetBoundaries(Coordinates):
    """Find the administrative or postal boundaries containing coordinates."""
    operation: Literal["get_boundaries"] = "get_boundaries"
    boundaries: list[Literal["administrative", "postal_code", "political", "low_emission_zone", "timezone"]] | None = Field(None, min_length=1, max_length=10)
    geometry: Literal["point", "geometry_1000", "geometry_5000", "geometry_10000"] = "point"


class Point(Input):
    type: Literal["Point"] = "Point"
    coordinates: Position


class LineString(Input):
    type: Literal["LineString"] = "LineString"
    coordinates: list[Position] = Field(..., min_length=2)


class Polygon(Input):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Position]] = Field(..., min_length=1)

    @field_validator("coordinates")
    @classmethod
    def rings(cls, value):
        if any(len(ring) < 4 or ring[0] != ring[-1] for ring in value):
            raise ValueError("Polygon rings need four or more positions and must be closed")
        return value


GeoGeometry = Annotated[Union[Point, LineString, Polygon], Field(discriminator="type")]


class GeoFeature(Input):
    type: Literal["Feature"] = "Feature"
    geometry: GeoGeometry
    properties: dict = Field(default_factory=dict)


class GeoCollection(Input):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoFeature] = Field(..., max_length=1000)


class StoreGeometry(Input):
    """Store a Point, LineString, Polygon, Feature or FeatureCollection."""
    operation: Literal["store_geometry"] = "store_geometry"
    geojson: Union[GeoGeometry, GeoFeature, GeoCollection]


class CalculateGeometry(Input):
    """Union or intersect two or more stored geometry or isoline IDs."""
    operation: Literal["calculate_geometry"] = "calculate_geometry"
    id: list[GeometryID] = Field(..., min_length=2, max_length=100)
    geometry_operation: Literal["union", "intersection"] = Field(..., description="Sent as the provider's operation query parameter.")


class SubmitBatchGeocode(Input):
    """Submit up to 1000 addresses; save the job ID and poll explicitly later."""
    operation: Literal["submit_batch_geocode"] = "submit_batch_geocode"
    addresses: list[Text] = Field(..., min_length=1, max_length=1000)
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")


class GetBatchGeocode(Input):
    """Read a forward batch job, preserving pending or completed results."""
    operation: Literal["get_batch_geocode"] = "get_batch_geocode"
    id: GeometryID


class SubmitBatchReverseGeocode(Input):
    """Submit longitude,latitude positions or lat/lon objects for batch lookup."""
    operation: Literal["submit_batch_reverse_geocode"] = "submit_batch_reverse_geocode"
    locations: list[Position | Coordinates] = Field(..., min_length=1, max_length=1000)
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$")


class GetBatchReverseGeocode(Input):
    """Read a reverse batch job, preserving pending or completed results."""
    operation: Literal["get_batch_reverse_geocode"] = "get_batch_reverse_geocode"
    id: GeometryID


GeoapifyConfig = Annotated[Union[
    GeocodeAddress, ReverseGeocode, AutocompleteAddress, GetIPLocation, SearchPlaces,
    GetPlaceDetails, CalculateRoute, CalculateIsoline, CalculateRouteMatrix, GetElevations,
    GetTimezone, SearchPostcodes, ListPostcodes, GetBoundaries, StoreGeometry,
    CalculateGeometry, SubmitBatchGeocode, GetBatchGeocode,
    SubmitBatchReverseGeocode, GetBatchReverseGeocode,
], Field(discriminator="operation")]


class GeoapifyFullConfig(NodeConfig[GeoapifyConfig, GeoapifyAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# METHOD + absolute API path, one published operation per NoClick operation.
OPERATIONS = {
    "geocode_address": ("GET", "/v1/geocode/search"),
    "reverse_geocode": ("GET", "/v1/geocode/reverse"),
    "autocomplete_address": ("GET", "/v1/geocode/autocomplete"),
    "get_ip_location": ("GET", "/v1/ipinfo"),
    "search_places": ("GET", "/v2/places"),
    "get_place_details": ("GET", "/v2/place-details"),
    "calculate_route": ("GET", "/v1/routing"),
    "calculate_isoline": ("GET", "/v1/isoline"),
    "calculate_route_matrix": ("POST", "/v1/routematrix"),
    "get_elevations": ("POST", "/v1/geodata/elevation"),
    "get_timezone": ("GET", "/v1/timezone"),
    "search_postcodes": ("GET", "/v1/postcode/search"),
    "list_postcodes": ("GET", "/v1/postcode/list"),
    "get_boundaries": ("GET", "/v1/boundaries/part-of"),
    "store_geometry": ("POST", "/v1/geometry"),
    "calculate_geometry": ("GET", "/v1/geometry"),
    "submit_batch_geocode": ("POST", "/v1/batch/geocode/search"),
    "get_batch_geocode": ("GET", "/v1/batch/geocode/search"),
    "submit_batch_reverse_geocode": ("POST", "/v1/batch/geocode/reverse"),
    "get_batch_reverse_geocode": ("GET", "/v1/batch/geocode/reverse"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(key, "[redacted]"): _redact(v, key) for k, v in value.items()}
    return value


class GeoapifyNode(WorkflowNode):
    integration_type = "automation-geoapify"
    connection_evidence = ConnectionEvidence(
        operation="get_ip_location", noun="Geoapify API", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return GeoapifyFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, GeoapifyFullConfig) or self.config.credentials is None:
            raise ValueError("Connect a Geoapify API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        params = []
        body = None
        if config.operation == "store_geometry":
            body = values["geojson"]
        elif config.operation.startswith("submit_batch_"):
            body = values.pop("addresses" if config.operation == "submit_batch_geocode" else "locations")
        elif method == "POST":
            body, values = values, {}
        if config.operation == "calculate_geometry":
            values["operation"] = values.pop("geometry_operation")
        for name, value in values.items() if method == "GET" or config.operation.startswith("submit_batch_") else []:
            if isinstance(value, list):
                # OpenAPI form/explode and pipeDelimited differ by endpoint.
                repeated = (config.operation == "calculate_geometry" and name == "id") or (config.operation == "calculate_isoline" and name == "avoid")
                if repeated:
                    params.extend((name, str(item)) for item in value)
                else:
                    separator = "|" if name in {"filter", "bias", "waypoints", "avoid", "features"} else ","
                    params.append((name, separator.join(str(item) for item in value)))
            else:
                params.append((name, str(value).lower() if isinstance(value, bool) else str(value)))
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    params=params, headers={"x-api-key": key, "Accept": "application/json, application/geo+json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Geoapify request could not be completed") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Geoapify response exceeds 10 MB")
        if response.status_code not in ({200, 202} if "batch" in config.operation else {200}):
            message = "Request was not accepted"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(key, "[redacted]")[:1000]
            except ValueError:
                pass
            raise ValueError(f"Geoapify HTTP {response.status_code}: {message}")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {"application/json", "application/geo+json"}:
            raise ValueError("Geoapify did not return JSON")
        data = response.json()
        if not isinstance(data, (dict, list)) or (isinstance(data, dict) and (data.get("error") or (isinstance(data.get("statusCode"), int) and data["statusCode"] >= 400))):
            raise ValueError("Geoapify did not confirm the request")
        if response.status_code == 202 and not (isinstance(data, dict) and data.get("status") == "pending" and data.get("id")):
            raise ValueError("Geoapify pending response has no job ID")
        if config.operation == "get_ip_location":
            try:
                ip_address(data["ip"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("Geoapify IP response has no valid IP address") from None
        # Native JSON preserves empty results, GeoJSON attribution, offsets and job
        # status without inventing completion or following a returned polling URL.
        return {"status": "success", "operation": config.operation,
            "http_status": response.status_code, "data": _redact(data, key)}
