"""
Google Maps Platform automation node.

Provides workflow integration with the Google Maps Platform REST APIs for
operations including:
- Geocoding: forward geocode, reverse geocode, geocode v4 by place ID
- Places (New): text search, nearby search, place details, autocomplete, photo
- Routes: compute routes, compute route matrix
- Legacy routing: directions, distance matrix
- Address validation
- Time zone, elevation
- Roads: snap to roads, nearest roads
- Legacy places: autocomplete, find place from text
- Environment — Air Quality: current, forecast, history
- Environment — Pollen: daily forecast
- Environment — Weather: current, daily/hourly forecast, hourly history
- Environment — Solar: building insights, data layers
- Geolocation: estimate location from cell/WiFi/IP
- Aerial View: render video, look up video
- Places Aggregate (Area Insights): compute insights

Authentication: API key (Google Maps Platform). Legacy web services and the
environment GET APIs (Pollen, Weather, Solar) pass the key as a `?key=` query
parameter; Air Quality and Geolocation are POST with `?key=`. The newer
services (Places API New, Routes API, Geocoding v4, Aerial View, Area Insights)
pass it via the `X-Goog-Api-Key` header; Places New / Routes / Geocoding v4
additionally require a field mask via `X-Goog-FieldMask`.

API Base URLs (per-service host):
- Legacy web services: https://maps.googleapis.com/maps/api/*
- Places (New): https://places.googleapis.com/v1
- Routes: https://routes.googleapis.com
- Address Validation: https://addressvalidation.googleapis.com/v1
- Geocoding v4: https://geocode.googleapis.com/v4
- Roads: https://roads.googleapis.com/v1
- Air Quality: https://airquality.googleapis.com/v1
- Pollen: https://pollen.googleapis.com/v1
- Weather: https://weather.googleapis.com/v1
- Solar: https://solar.googleapis.com/v1
- Geolocation: https://www.googleapis.com/geolocation/v1
- Aerial View: https://aerialview.googleapis.com/v1
- Area Insights: https://areainsights.googleapis.com/v1

Documentation: https://developers.google.com/maps/documentation

The Maps web services do NOT expose a registerable webhook / subscription API,
so this node has no trigger — all operations are request/response.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

# Per-service hosts (the spec mandates exact, per-API base URLs).
MAPS_LEGACY_BASE = "https://maps.googleapis.com/maps/api"
PLACES_BASE = "https://places.googleapis.com/v1"
ROUTES_BASE = "https://routes.googleapis.com"
ADDRESS_VALIDATION_BASE = "https://addressvalidation.googleapis.com/v1"
GEOCODE_V4_BASE = "https://geocode.googleapis.com/v4"
ROADS_BASE = "https://roads.googleapis.com/v1"
AIR_QUALITY_BASE = "https://airquality.googleapis.com/v1"
POLLEN_BASE = "https://pollen.googleapis.com/v1"
WEATHER_BASE = "https://weather.googleapis.com/v1"
SOLAR_BASE = "https://solar.googleapis.com/v1"
GEOLOCATION_BASE = "https://www.googleapis.com/geolocation/v1"
AERIAL_VIEW_BASE = "https://aerialview.googleapis.com/v1"
AREA_INSIGHTS_BASE = "https://areainsights.googleapis.com/v1"


# ============================================================================
# Credential Schema
# ============================================================================


class GoogleMapsApiKeyCredential(BaseModel):
    """API key credential for Google Maps Platform."""

    credential_type: Literal["google_maps_api_key"] = Field(
        "google_maps_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description=(
            "Your Google Maps Platform API key from the Google Cloud Console "
            "(Credentials page). Billing must be enabled and the relevant APIs turned on."
        ),
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.cloud.google.com/google/maps-apis/credentials"
        }
    )


GoogleMapsCredential = GoogleMapsApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class GoogleMapsGeocodeConfig(BaseModel):
    """Forward geocode: convert an address into lat-lng coordinates and a place ID."""

    operation: Literal["geocode"] = Field(
        "geocode",
        json_schema_extra={
            "const": "geocode",
            "ui:hidden": True,
            "x-category": "Geocoding",
            "x-is-trigger": False,
            "x-display-name": "Geocode Address",
        },
        title="Geocode Address",
    )
    address: str = Field(
        ...,
        title="Address",
        description="Street address or place to geocode (e.g. 1600 Amphitheatre Pkwy, Mountain View, CA)",
    )
    region: Optional[str] = Field(
        None,
        title="Region Bias",
        description="ccTLD region code to bias results (e.g. us, uk)",
    )
    language: Optional[str] = Field(
        None, title="Language", description="Language for results (e.g. en, fr)"
    )


class GoogleMapsReverseGeocodeConfig(BaseModel):
    """Reverse geocode: convert lat-lng coordinates into a formatted address."""

    operation: Literal["reverse_geocode"] = Field(
        "reverse_geocode",
        json_schema_extra={
            "const": "reverse_geocode",
            "ui:hidden": True,
            "x-category": "Geocoding",
            "x-is-trigger": False,
            "x-display-name": "Reverse Geocode",
        },
        title="Reverse Geocode",
    )
    latlng: str = Field(
        ...,
        title="Coordinates",
        description="Latitude,longitude pair (note the order), e.g. 37.4224,-122.0841",
    )
    language: Optional[str] = Field(
        None, title="Language", description="Language for results (e.g. en, fr)"
    )


class GoogleMapsGeocodeV4Config(BaseModel):
    """Geocoding v4: resolve geographic info for a given place ID."""

    operation: Literal["geocode_v4_place"] = Field(
        "geocode_v4_place",
        json_schema_extra={
            "const": "geocode_v4_place",
            "ui:hidden": True,
            "x-category": "Geocoding",
            "x-is-trigger": False,
            "x-display-name": "Geocode Place ID (v4)",
        },
        title="Geocode Place ID (v4)",
    )
    place_id: str = Field(
        ..., title="Place ID", description="The place ID to resolve (e.g. ChIJ...)"
    )
    field_mask: str = Field(
        "*",
        title="Field Mask",
        description="Comma-separated response fields (X-Goog-FieldMask). Use * for all fields.",
    )


class GoogleMapsTextSearchConfig(BaseModel):
    """Places (New) text search: find places from a free-text query."""

    operation: Literal["text_search"] = Field(
        "text_search",
        json_schema_extra={
            "const": "text_search",
            "ui:hidden": True,
            "x-category": "Places",
            "x-is-trigger": False,
            "x-display-name": "Text Search",
        },
        title="Text Search",
    )
    text_query: str = Field(
        ..., title="Query", description='Free-text search query (e.g. "pizza in Sydney")'
    )
    field_mask: str = Field(
        "places.displayName,places.formattedAddress,places.id,places.location,places.rating",
        title="Field Mask",
        description="Comma-separated response fields (X-Goog-FieldMask). Required by the API.",
    )
    max_result_count: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of places to return (1-20)"
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for pagination"
    )


class GoogleMapsNearbySearchConfig(BaseModel):
    """Places (New) nearby search: find places within a circle around a location."""

    operation: Literal["nearby_search"] = Field(
        "nearby_search",
        json_schema_extra={
            "const": "nearby_search",
            "ui:hidden": True,
            "x-category": "Places",
            "x-is-trigger": False,
            "x-display-name": "Nearby Search",
        },
        title="Nearby Search",
    )
    latitude: str = Field(..., title="Latitude", description="Center latitude")
    longitude: str = Field(..., title="Longitude", description="Center longitude")
    radius: str = Field(
        "500", title="Radius (m)", description="Search radius in meters (max 50000)"
    )
    included_types: Optional[str] = Field(
        None,
        title="Included Types",
        description="Comma-separated place types to include (e.g. restaurant,cafe)",
    )
    field_mask: str = Field(
        "places.displayName,places.formattedAddress,places.id,places.location,places.types",
        title="Field Mask",
        description="Comma-separated response fields (X-Goog-FieldMask). Required by the API.",
    )
    max_result_count: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of places to return (1-20)"
    )


class GoogleMapsPlaceDetailsConfig(BaseModel):
    """Places (New) place details: full details for a place by ID."""

    operation: Literal["place_details"] = Field(
        "place_details",
        json_schema_extra={
            "const": "place_details",
            "ui:hidden": True,
            "x-category": "Places",
            "x-is-trigger": False,
            "x-display-name": "Place Details",
        },
        title="Place Details",
    )
    place_id: str = Field(
        ..., title="Place ID", description="The place ID to retrieve details for"
    )
    field_mask: str = Field(
        "id,displayName,formattedAddress,location,rating,nationalPhoneNumber,regularOpeningHours,websiteUri",
        title="Field Mask",
        description="Comma-separated response fields (X-Goog-FieldMask). Required by the API.",
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )


class GoogleMapsAutocompleteConfig(BaseModel):
    """Places (New) autocomplete: place/query predictions for a partial input."""

    operation: Literal["autocomplete"] = Field(
        "autocomplete",
        json_schema_extra={
            "const": "autocomplete",
            "ui:hidden": True,
            "x-category": "Places",
            "x-is-trigger": False,
            "x-display-name": "Place Autocomplete",
        },
        title="Place Autocomplete",
    )
    input_text: str = Field(
        ..., title="Input", description="Partial text to get predictions for"
    )
    field_mask: Optional[str] = Field(
        None,
        title="Field Mask",
        description="Optional X-Goog-FieldMask (autocomplete returns suggestions without one)",
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )
    region_code: Optional[str] = Field(
        None, title="Region", description="Region code to bias results (e.g. US)"
    )


class GoogleMapsPlacePhotoConfig(BaseModel):
    """Places (New) place photo: fetch metadata/redirect for a photo resource."""

    operation: Literal["place_photo"] = Field(
        "place_photo",
        json_schema_extra={
            "const": "place_photo",
            "ui:hidden": True,
            "x-category": "Places",
            "x-is-trigger": False,
            "x-display-name": "Place Photo",
        },
        title="Place Photo",
    )
    photo_name: str = Field(
        ...,
        title="Photo Resource Name",
        description="The photo resource name (e.g. places/PLACE_ID/photos/PHOTO_REF)",
    )
    max_width_px: Optional[str] = Field(
        "800", title="Max Width (px)", description="Maximum width of the returned image"
    )
    max_height_px: Optional[str] = Field(
        None, title="Max Height (px)", description="Maximum height of the returned image"
    )


class GoogleMapsComputeRoutesConfig(BaseModel):
    """Routes API: compute the primary route between origin and destination."""

    operation: Literal["compute_routes"] = Field(
        "compute_routes",
        json_schema_extra={
            "const": "compute_routes",
            "ui:hidden": True,
            "x-category": "Routes",
            "x-is-trigger": False,
            "x-display-name": "Compute Routes",
        },
        title="Compute Routes",
    )
    origin: str = Field(
        ...,
        title="Origin",
        description="Origin as 'lat,lng' coordinates or an address string",
    )
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination as 'lat,lng' coordinates or an address string",
    )
    travel_mode: str = Field(
        "DRIVE",
        title="Travel Mode",
        description="Travel mode",
        json_schema_extra={
            "enum": ["DRIVE", "BICYCLE", "WALK", "TWO_WHEELER", "TRANSIT"],
            "x-enum-searchable": True,
        },
    )
    routing_preference: Optional[str] = Field(
        None,
        title="Routing Preference",
        description="Routing preference (e.g. TRAFFIC_AWARE) — DRIVE/TWO_WHEELER only",
        json_schema_extra={
            "enum": ["", "TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"],
            "x-enum-searchable": True,
        },
    )
    field_mask: str = Field(
        "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
        title="Field Mask",
        description="Comma-separated response fields (X-Goog-FieldMask). Required by the API.",
    )


class GoogleMapsComputeRouteMatrixConfig(BaseModel):
    """Routes API: compute route info for every origin-destination combination."""

    operation: Literal["compute_route_matrix"] = Field(
        "compute_route_matrix",
        json_schema_extra={
            "const": "compute_route_matrix",
            "ui:hidden": True,
            "x-category": "Routes",
            "x-is-trigger": False,
            "x-display-name": "Compute Route Matrix",
        },
        title="Compute Route Matrix",
    )
    origins: str = Field(
        ...,
        title="Origins",
        description="Semicolon-separated origins, each 'lat,lng' or an address",
    )
    destinations: str = Field(
        ...,
        title="Destinations",
        description="Semicolon-separated destinations, each 'lat,lng' or an address",
    )
    travel_mode: str = Field(
        "DRIVE",
        title="Travel Mode",
        description="Travel mode",
        json_schema_extra={
            "enum": ["DRIVE", "BICYCLE", "WALK", "TWO_WHEELER", "TRANSIT"],
            "x-enum-searchable": True,
        },
    )
    field_mask: str = Field(
        "originIndex,destinationIndex,duration,distanceMeters,status,condition",
        title="Field Mask",
        description="Comma-separated response fields (X-Goog-FieldMask). Required by the API.",
    )


class GoogleMapsDirectionsConfig(BaseModel):
    """Legacy Directions: turn-by-turn directions between two points."""

    operation: Literal["directions"] = Field(
        "directions",
        json_schema_extra={
            "const": "directions",
            "ui:hidden": True,
            "x-category": "Legacy Routing",
            "x-is-trigger": False,
            "x-display-name": "Directions (Legacy)",
        },
        title="Directions (Legacy)",
    )
    origin: str = Field(
        ..., title="Origin", description="Origin as 'lat,lng' or an address string"
    )
    destination: str = Field(
        ..., title="Destination", description="Destination as 'lat,lng' or an address string"
    )
    mode: str = Field(
        "driving",
        title="Mode",
        description="Travel mode",
        json_schema_extra={
            "enum": ["driving", "walking", "bicycling", "transit"],
            "x-enum-searchable": True,
        },
    )
    waypoints: Optional[str] = Field(
        None, title="Waypoints", description="Pipe-separated intermediate waypoints"
    )


class GoogleMapsDistanceMatrixConfig(BaseModel):
    """Legacy Distance Matrix: travel distance/time between origins and destinations."""

    operation: Literal["distance_matrix"] = Field(
        "distance_matrix",
        json_schema_extra={
            "const": "distance_matrix",
            "ui:hidden": True,
            "x-category": "Legacy Routing",
            "x-is-trigger": False,
            "x-display-name": "Distance Matrix (Legacy)",
        },
        title="Distance Matrix (Legacy)",
    )
    origins: str = Field(
        ...,
        title="Origins",
        description="Pipe-separated origins, each 'lat,lng' or an address",
    )
    destinations: str = Field(
        ...,
        title="Destinations",
        description="Pipe-separated destinations, each 'lat,lng' or an address",
    )
    mode: str = Field(
        "driving",
        title="Mode",
        description="Travel mode",
        json_schema_extra={
            "enum": ["driving", "walking", "bicycling", "transit"],
            "x-enum-searchable": True,
        },
    )


class GoogleMapsValidateAddressConfig(BaseModel):
    """Address Validation: validate, correct, and standardize a postal address."""

    operation: Literal["validate_address"] = Field(
        "validate_address",
        json_schema_extra={
            "const": "validate_address",
            "ui:hidden": True,
            "x-category": "Address Validation",
            "x-is-trigger": False,
            "x-display-name": "Validate Address",
        },
        title="Validate Address",
    )
    address_lines: str = Field(
        ...,
        title="Address Lines",
        description="Address lines (street). For multiple lines, separate with newlines.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    region_code: Optional[str] = Field(
        None, title="Region Code", description="CLDR region/country code (e.g. US)"
    )
    locality: Optional[str] = Field(
        None, title="Locality", description="City / locality (optional)"
    )
    enable_usps_cass: str = Field(
        "false",
        title="Enable USPS CASS",
        description="Enable USPS CASS validation (US/PR only)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GoogleMapsTimeZoneConfig(BaseModel):
    """Time Zone: time zone for a location and timestamp."""

    operation: Literal["timezone"] = Field(
        "timezone",
        json_schema_extra={
            "const": "timezone",
            "ui:hidden": True,
            "x-category": "Utilities",
            "x-is-trigger": False,
            "x-display-name": "Time Zone",
        },
        title="Time Zone",
    )
    location: str = Field(
        ..., title="Location", description="Latitude,longitude pair, e.g. 37.4224,-122.0841"
    )
    timestamp: str = Field(
        "0",
        title="Timestamp",
        description="Unix timestamp (seconds since epoch) to resolve DST for. 0 = epoch.",
    )
    language: Optional[str] = Field(
        None, title="Language", description="Language for the time zone name (e.g. en)"
    )


class GoogleMapsElevationConfig(BaseModel):
    """Elevation: elevation (meters above sea level) for points."""

    operation: Literal["elevation"] = Field(
        "elevation",
        json_schema_extra={
            "const": "elevation",
            "ui:hidden": True,
            "x-category": "Utilities",
            "x-is-trigger": False,
            "x-display-name": "Elevation",
        },
        title="Elevation",
    )
    locations: str = Field(
        ...,
        title="Locations",
        description="Pipe-separated 'lat,lng' points, e.g. 39.7391,-104.9847|36.455,-116.866",
    )


class GoogleMapsSnapToRoadsConfig(BaseModel):
    """Roads: snap GPS points to the most likely road geometry."""

    operation: Literal["snap_to_roads"] = Field(
        "snap_to_roads",
        json_schema_extra={
            "const": "snap_to_roads",
            "ui:hidden": True,
            "x-category": "Roads",
            "x-is-trigger": False,
            "x-display-name": "Snap to Roads",
        },
        title="Snap to Roads",
    )
    path: str = Field(
        ...,
        title="Path",
        description="Pipe-separated 'lat,lng' points (up to 100), e.g. -35.27801,149.12958|-35.28032,149.12907",
    )
    interpolate: str = Field(
        "false",
        title="Interpolate",
        description="Interpolate the path to include all points forming the full road geometry",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GoogleMapsNearestRoadsConfig(BaseModel):
    """Roads: nearest road segment(s) to a set of coordinates."""

    operation: Literal["nearest_roads"] = Field(
        "nearest_roads",
        json_schema_extra={
            "const": "nearest_roads",
            "ui:hidden": True,
            "x-category": "Roads",
            "x-is-trigger": False,
            "x-display-name": "Nearest Roads",
        },
        title="Nearest Roads",
    )
    points: str = Field(
        ...,
        title="Points",
        description="Pipe-separated 'lat,lng' points (up to 100), e.g. 60.170880,24.942795|60.170879,24.942796",
    )


class GoogleMapsLegacyAutocompleteConfig(BaseModel):
    """Legacy Places autocomplete: typeahead predictions for a partial query."""

    operation: Literal["legacy_autocomplete"] = Field(
        "legacy_autocomplete",
        json_schema_extra={
            "const": "legacy_autocomplete",
            "ui:hidden": True,
            "x-category": "Legacy Places",
            "x-is-trigger": False,
            "x-display-name": "Autocomplete (Legacy)",
        },
        title="Autocomplete (Legacy)",
    )
    input_text: str = Field(
        ..., title="Input", description="Partial query string to get predictions for"
    )
    language: Optional[str] = Field(
        None, title="Language", description="Language for results (e.g. en)"
    )
    components: Optional[str] = Field(
        None,
        title="Components",
        description="Grouping of place restrictions (e.g. country:us)",
    )


class GoogleMapsFindPlaceConfig(BaseModel):
    """Legacy Places find place: single best-match place from text input."""

    operation: Literal["find_place"] = Field(
        "find_place",
        json_schema_extra={
            "const": "find_place",
            "ui:hidden": True,
            "x-category": "Legacy Places",
            "x-is-trigger": False,
            "x-display-name": "Find Place (Legacy)",
        },
        title="Find Place (Legacy)",
    )
    input_text: str = Field(
        ..., title="Input", description="Text or phone number to look up"
    )
    input_type: str = Field(
        "textquery",
        title="Input Type",
        description="The type of input provided",
        json_schema_extra={
            "enum": ["textquery", "phonenumber"],
            "x-enum-searchable": True,
        },
    )
    fields: Optional[str] = Field(
        None,
        title="Fields",
        description="Comma-separated fields to return (e.g. place_id,name,formatted_address)",
    )


# ============================================================================
# Environment: Air Quality
# ============================================================================


class GoogleMapsAirQualityCurrentConfig(BaseModel):
    """Air Quality: current air quality conditions for a location."""

    operation: Literal["air_quality_current"] = Field(
        "air_quality_current",
        json_schema_extra={
            "const": "air_quality_current",
            "ui:hidden": True,
            "x-category": "Air Quality",
            "x-is-trigger": False,
            "x-display-name": "Air Quality (Current)",
        },
        title="Air Quality (Current)",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    universal_aqi: str = Field(
        "true",
        title="Universal AQI",
        description="Include the Universal AQI (0-100) in the response",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    extra_computations: Optional[str] = Field(
        None,
        title="Extra Computations",
        description=(
            "Comma-separated extras: HEALTH_RECOMMENDATIONS, DOMINANT_POLLUTANT_CONCENTRATION, "
            "POLLUTANT_CONCENTRATION, LOCAL_AQI, POLLUTANT_ADDITIONAL_INFO"
        ),
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )


class GoogleMapsAirQualityForecastConfig(BaseModel):
    """Air Quality: hourly air quality forecast (up to 96 hours ahead)."""

    operation: Literal["air_quality_forecast"] = Field(
        "air_quality_forecast",
        json_schema_extra={
            "const": "air_quality_forecast",
            "ui:hidden": True,
            "x-category": "Air Quality",
            "x-is-trigger": False,
            "x-display-name": "Air Quality (Forecast)",
        },
        title="Air Quality (Forecast)",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    date_time: Optional[str] = Field(
        None,
        title="Date Time",
        description="RFC3339 timestamp for a single forecast hour (use this OR a period)",
    )
    start_time: Optional[str] = Field(
        None, title="Period Start", description="RFC3339 start of a forecast period"
    )
    end_time: Optional[str] = Field(
        None, title="Period End", description="RFC3339 end of a forecast period (inclusive)"
    )
    extra_computations: Optional[str] = Field(
        None,
        title="Extra Computations",
        description="Comma-separated extras (see Air Quality Current)",
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Number of hourly records per page (default 24)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for pagination"
    )

    # A single Date Time, or a full period (start + end).
    model_config = ConfigDict(
        json_schema_extra={
            "x-require-one-of": [[["date_time"], ["start_time", "end_time"]]]
        }
    )


class GoogleMapsAirQualityHistoryConfig(BaseModel):
    """Air Quality: historical hourly air quality (past 30 days)."""

    operation: Literal["air_quality_history"] = Field(
        "air_quality_history",
        json_schema_extra={
            "const": "air_quality_history",
            "ui:hidden": True,
            "x-category": "Air Quality",
            "x-is-trigger": False,
            "x-display-name": "Air Quality (History)",
        },
        title="Air Quality (History)",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    hours: Optional[str] = Field(
        None,
        title="Hours",
        description="Number of hours back from now (1-720). Use this OR a date/period.",
    )
    date_time: Optional[str] = Field(
        None, title="Date Time", description="RFC3339 timestamp for a single past hour"
    )
    start_time: Optional[str] = Field(
        None, title="Period Start", description="RFC3339 start of a history period"
    )
    end_time: Optional[str] = Field(
        None, title="Period End", description="RFC3339 end of a history period (inclusive)"
    )
    extra_computations: Optional[str] = Field(
        None, title="Extra Computations", description="Comma-separated extras"
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Records per page (default 72, max 168)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for pagination"
    )

    # Hours back, a single Date Time, or a full period (start + end).
    model_config = ConfigDict(
        json_schema_extra={
            "x-require-one-of": [
                [["hours"], ["date_time"], ["start_time", "end_time"]]
            ]
        }
    )


# ============================================================================
# Environment: Pollen
# ============================================================================


class GoogleMapsPollenForecastConfig(BaseModel):
    """Pollen: daily pollen forecast (up to 5 days) for a location."""

    operation: Literal["pollen_forecast"] = Field(
        "pollen_forecast",
        json_schema_extra={
            "const": "pollen_forecast",
            "ui:hidden": True,
            "x-category": "Pollen",
            "x-is-trigger": False,
            "x-display-name": "Pollen Forecast",
        },
        title="Pollen Forecast",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    days: str = Field(
        "1", title="Days", description="Number of forecast days (1-5)"
    )
    plants_description: str = Field(
        "true",
        title="Plant Descriptions",
        description="Include detailed per-plant information in the response",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Records per page (default/max 5)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for pagination"
    )


# ============================================================================
# Environment: Weather
# ============================================================================


class GoogleMapsWeatherCurrentConfig(BaseModel):
    """Weather: current weather conditions for a location."""

    operation: Literal["weather_current"] = Field(
        "weather_current",
        json_schema_extra={
            "const": "weather_current",
            "ui:hidden": True,
            "x-category": "Weather",
            "x-is-trigger": False,
            "x-display-name": "Weather (Current)",
        },
        title="Weather (Current)",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    units_system: Optional[str] = Field(
        None,
        title="Units System",
        description="Measurement units",
        json_schema_extra={
            "enum": ["", "METRIC", "IMPERIAL"],
            "x-enum-searchable": True,
        },
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )


class GoogleMapsWeatherForecastDaysConfig(BaseModel):
    """Weather: daily weather forecast (up to 10 days)."""

    operation: Literal["weather_forecast_days"] = Field(
        "weather_forecast_days",
        json_schema_extra={
            "const": "weather_forecast_days",
            "ui:hidden": True,
            "x-category": "Weather",
            "x-is-trigger": False,
            "x-display-name": "Weather (Daily Forecast)",
        },
        title="Weather (Daily Forecast)",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    days: Optional[str] = Field(
        None, title="Days", description="Number of forecast days (default/max 10)"
    )
    units_system: Optional[str] = Field(
        None,
        title="Units System",
        description="Measurement units",
        json_schema_extra={
            "enum": ["", "METRIC", "IMPERIAL"],
            "x-enum-searchable": True,
        },
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Records per page (default 5)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for pagination"
    )


class GoogleMapsWeatherForecastHoursConfig(BaseModel):
    """Weather: hourly weather forecast (up to 240 hours)."""

    operation: Literal["weather_forecast_hours"] = Field(
        "weather_forecast_hours",
        json_schema_extra={
            "const": "weather_forecast_hours",
            "ui:hidden": True,
            "x-category": "Weather",
            "x-is-trigger": False,
            "x-display-name": "Weather (Hourly Forecast)",
        },
        title="Weather (Hourly Forecast)",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    hours: Optional[str] = Field(
        None, title="Hours", description="Number of forecast hours (default/max 240)"
    )
    units_system: Optional[str] = Field(
        None,
        title="Units System",
        description="Measurement units",
        json_schema_extra={
            "enum": ["", "METRIC", "IMPERIAL"],
            "x-enum-searchable": True,
        },
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Records per page (default 24)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for pagination"
    )


class GoogleMapsWeatherHistoryHoursConfig(BaseModel):
    """Weather: historical hourly weather (past 24 hours)."""

    operation: Literal["weather_history_hours"] = Field(
        "weather_history_hours",
        json_schema_extra={
            "const": "weather_history_hours",
            "ui:hidden": True,
            "x-category": "Weather",
            "x-is-trigger": False,
            "x-display-name": "Weather (Hourly History)",
        },
        title="Weather (Hourly History)",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    hours: Optional[str] = Field(
        None, title="Hours", description="Number of past hours (default/max 24)"
    )
    units_system: Optional[str] = Field(
        None,
        title="Units System",
        description="Measurement units",
        json_schema_extra={
            "enum": ["", "METRIC", "IMPERIAL"],
            "x-enum-searchable": True,
        },
    )
    language_code: Optional[str] = Field(
        None, title="Language", description="Language code for results (e.g. en)"
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Records per page (default 24)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for pagination"
    )


# ============================================================================
# Environment: Solar
# ============================================================================


class GoogleMapsSolarBuildingInsightsConfig(BaseModel):
    """Solar: solar potential insights for the building closest to a location."""

    operation: Literal["solar_building_insights"] = Field(
        "solar_building_insights",
        json_schema_extra={
            "const": "solar_building_insights",
            "ui:hidden": True,
            "x-category": "Solar",
            "x-is-trigger": False,
            "x-display-name": "Solar Building Insights",
        },
        title="Solar Building Insights",
    )
    latitude: str = Field(..., title="Latitude", description="Location latitude")
    longitude: str = Field(..., title="Longitude", description="Location longitude")
    required_quality: Optional[str] = Field(
        None,
        title="Required Quality",
        description="Minimum acceptable imagery quality",
        json_schema_extra={
            "enum": ["", "HIGH", "MEDIUM", "LOW"],
            "x-enum-searchable": True,
        },
    )


class GoogleMapsSolarDataLayersConfig(BaseModel):
    """Solar: solar data layers (DSM, imagery, flux) around a location."""

    operation: Literal["solar_data_layers"] = Field(
        "solar_data_layers",
        json_schema_extra={
            "const": "solar_data_layers",
            "ui:hidden": True,
            "x-category": "Solar",
            "x-is-trigger": False,
            "x-display-name": "Solar Data Layers",
        },
        title="Solar Data Layers",
    )
    latitude: str = Field(..., title="Latitude", description="Center latitude")
    longitude: str = Field(..., title="Longitude", description="Center longitude")
    radius_meters: str = Field(
        "100", title="Radius (m)", description="Region radius in meters"
    )
    view: Optional[str] = Field(
        None,
        title="View",
        description="Which data subset to return",
        json_schema_extra={
            "enum": [
                "",
                "DSM_LAYER",
                "IMAGERY_LAYERS",
                "IMAGERY_AND_ANNUAL_FLUX_LAYERS",
                "IMAGERY_AND_ALL_FLUX_LAYERS",
                "FULL_LAYERS",
            ],
            "x-enum-searchable": True,
        },
    )
    required_quality: Optional[str] = Field(
        None,
        title="Required Quality",
        description="Minimum acceptable imagery quality",
        json_schema_extra={
            "enum": ["", "HIGH", "MEDIUM", "LOW"],
            "x-enum-searchable": True,
        },
    )
    pixel_size_meters: Optional[str] = Field(
        None,
        title="Pixel Size (m)",
        description="Meters per pixel (0.1, 0.25, 0.5, or 1.0)",
    )


# ============================================================================
# Geolocation
# ============================================================================


class GoogleMapsGeolocateConfig(BaseModel):
    """Geolocation: estimate a location from cell towers / WiFi / caller IP."""

    operation: Literal["geolocate"] = Field(
        "geolocate",
        json_schema_extra={
            "const": "geolocate",
            "ui:hidden": True,
            "x-category": "Geolocation",
            "x-is-trigger": False,
            "x-display-name": "Geolocate",
        },
        title="Geolocate",
    )
    consider_ip: str = Field(
        "true",
        title="Consider IP",
        description="Fall back to caller-IP geolocation when no signals are supplied",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    wifi_access_points: Optional[str] = Field(
        None,
        title="WiFi Access Points (JSON)",
        description='Optional JSON array of WiFi access points (e.g. [{"macAddress":"..."}])',
        json_schema_extra={"ui:widget": "textarea"},
    )
    cell_towers: Optional[str] = Field(
        None,
        title="Cell Towers (JSON)",
        description='Optional JSON array of cell towers (e.g. [{"cellId":..,"locationAreaCode":..}])',
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Aerial View
# ============================================================================


class GoogleMapsAerialRenderVideoConfig(BaseModel):
    """Aerial View: request rendering of an aerial video for an address (async)."""

    operation: Literal["aerial_render_video"] = Field(
        "aerial_render_video",
        json_schema_extra={
            "const": "aerial_render_video",
            "ui:hidden": True,
            "x-category": "Aerial View",
            "x-is-trigger": False,
            "x-display-name": "Render Aerial Video",
        },
        title="Render Aerial Video",
    )
    address: str = Field(
        ..., title="Address", description="A US postal address to render an aerial video for"
    )


class GoogleMapsAerialLookupVideoConfig(BaseModel):
    """Aerial View: look up a previously requested aerial video by ID or address."""

    operation: Literal["aerial_lookup_video"] = Field(
        "aerial_lookup_video",
        json_schema_extra={
            "const": "aerial_lookup_video",
            "ui:hidden": True,
            "x-category": "Aerial View",
            "x-is-trigger": False,
            "x-display-name": "Look Up Aerial Video",
        },
        title="Look Up Aerial Video",
    )
    video_id: Optional[str] = Field(
        None,
        title="Video ID",
        description="The video ID returned by Render Aerial Video. Provide this OR an Address (one required).",
    )
    address: Optional[str] = Field(
        None,
        title="Address",
        description="The US postal address used when rendering. Provide this OR a Video ID (one required).",
    )

    # At least one of (video_id) or (address) must be filled.
    model_config = ConfigDict(
        json_schema_extra={"x-require-one-of": [[["video_id"], ["address"]]]}
    )


# ============================================================================
# Places Aggregate (Area Insights)
# ============================================================================


class GoogleMapsComputeInsightsConfig(BaseModel):
    """Places Aggregate: count or list places matching a location + type filter."""

    operation: Literal["compute_insights"] = Field(
        "compute_insights",
        json_schema_extra={
            "const": "compute_insights",
            "ui:hidden": True,
            "x-category": "Places Insights",
            "x-is-trigger": False,
            "x-display-name": "Compute Insights",
        },
        title="Compute Insights",
    )
    insights: str = Field(
        "INSIGHT_COUNT",
        title="Insights",
        description="Comma-separated: INSIGHT_COUNT, INSIGHT_PLACES",
    )
    included_types: str = Field(
        ...,
        title="Included Types",
        description="Comma-separated place types to match (e.g. restaurant,cafe)",
    )
    region_place_id: Optional[str] = Field(
        None,
        title="Region Place ID",
        description=(
            "A place ID to use as the region filter (e.g. ChIJ...). Provide this OR a "
            "circle (latitude + longitude + radius) — one location filter is required."
        ),
    )
    latitude: Optional[str] = Field(
        None,
        title="Circle Latitude",
        description="Center latitude for a circle filter (requires longitude + radius).",
    )
    longitude: Optional[str] = Field(
        None,
        title="Circle Longitude",
        description="Center longitude for a circle filter (requires latitude + radius).",
    )
    radius: Optional[str] = Field(
        None,
        title="Circle Radius (m)",
        description="Circle radius in meters (requires latitude + longitude).",
    )
    excluded_types: Optional[str] = Field(
        None, title="Excluded Types", description="Comma-separated place types to exclude"
    )
    min_rating: Optional[str] = Field(
        None, title="Min Rating", description="Minimum average rating (1.0-5.0)"
    )
    max_rating: Optional[str] = Field(
        None, title="Max Rating", description="Maximum average rating (1.0-5.0)"
    )

    # Either a region place ID, or a full circle (lat + lng + radius).
    model_config = ConfigDict(
        json_schema_extra={
            "x-require-one-of": [
                [["region_place_id"], ["latitude", "longitude", "radius"]]
            ]
        }
    )


# ============================================================================
# Discriminated Union
# ============================================================================


GoogleMapsConfig = Annotated[
    Union[
        GoogleMapsGeocodeConfig,
        GoogleMapsReverseGeocodeConfig,
        GoogleMapsGeocodeV4Config,
        GoogleMapsTextSearchConfig,
        GoogleMapsNearbySearchConfig,
        GoogleMapsPlaceDetailsConfig,
        GoogleMapsAutocompleteConfig,
        GoogleMapsPlacePhotoConfig,
        GoogleMapsComputeRoutesConfig,
        GoogleMapsComputeRouteMatrixConfig,
        GoogleMapsDirectionsConfig,
        GoogleMapsDistanceMatrixConfig,
        GoogleMapsValidateAddressConfig,
        GoogleMapsTimeZoneConfig,
        GoogleMapsElevationConfig,
        GoogleMapsSnapToRoadsConfig,
        GoogleMapsNearestRoadsConfig,
        GoogleMapsLegacyAutocompleteConfig,
        GoogleMapsFindPlaceConfig,
        GoogleMapsAirQualityCurrentConfig,
        GoogleMapsAirQualityForecastConfig,
        GoogleMapsAirQualityHistoryConfig,
        GoogleMapsPollenForecastConfig,
        GoogleMapsWeatherCurrentConfig,
        GoogleMapsWeatherForecastDaysConfig,
        GoogleMapsWeatherForecastHoursConfig,
        GoogleMapsWeatherHistoryHoursConfig,
        GoogleMapsSolarBuildingInsightsConfig,
        GoogleMapsSolarDataLayersConfig,
        GoogleMapsGeolocateConfig,
        GoogleMapsAerialRenderVideoConfig,
        GoogleMapsAerialLookupVideoConfig,
        GoogleMapsComputeInsightsConfig,
    ],
    Discriminator("operation"),
]


class GoogleMapsNodeConfig(NodeConfig[GoogleMapsConfig, GoogleMapsCredential]):
    """Full configuration for the Google Maps node including credentials."""

    pass


# ============================================================================
# Request helper
# ============================================================================

# Legacy web services return a textual `status` in a 200 body; these are the
# values that indicate failure even though the HTTP status is 200.
_LEGACY_ERROR_STATUSES = {
    "ZERO_RESULTS",  # not an error per se, but surfaced so callers can branch
    "OVER_QUERY_LIMIT",
    "REQUEST_DENIED",
    "INVALID_REQUEST",
    "UNKNOWN_ERROR",
    "MAX_ELEMENTS_EXCEEDED",
    "MAX_WAYPOINTS_EXCEEDED",
    "MAX_ROUTE_LENGTH_EXCEEDED",
    "NOT_FOUND",
}
# A textual status that means hard failure (vs. a soft empty result).
_LEGACY_HARD_FAILURES = _LEGACY_ERROR_STATUSES - {"ZERO_RESULTS"}


def _clean(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not d:
        return None
    cleaned = {k: v for k, v in d.items() if v not in (None, "")}
    return cleaned or None


async def _maps_request(
    method: str,
    url: str,
    api_key: str,
    *,
    use_header_auth: bool,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    field_mask: Optional[str] = None,
    inspect_legacy_status: bool = False,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Google Maps request and return a structured result.

    Auth branches per the spec:
    - Legacy services (`use_header_auth=False`): key passed as `?key=` query param.
    - New services (`use_header_auth=True`): key passed via `X-Goog-Api-Key`
      header, plus a mandatory `X-Goog-FieldMask` header.

    Legacy services embed a textual `status` in a 200 body; when
    `inspect_legacy_status=True` we inspect it and surface hard failures.
    """
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    query = _clean(params) or {}

    if use_header_auth:
        headers["X-Goog-Api-Key"] = api_key
        if field_mask:
            headers["X-Goog-FieldMask"] = field_mask
    else:
        query = {**query, "key": api_key}

    body = _clean(json_body)

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=query, json=body
            )
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        error_obj = err.get("error")
                        if isinstance(error_obj, dict):
                            message = error_obj.get("message", str(err))
                        else:
                            message = err.get("error_message") or err.get("message") or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[GoogleMapsNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            try:
                data: Any = response.json()
            except Exception:
                data = {"raw": response.text}

            # Legacy web services return a 200 with a textual status field.
            if inspect_legacy_status and isinstance(data, dict):
                legacy_status = data.get("status")
                if legacy_status in _LEGACY_HARD_FAILURES:
                    message = data.get("error_message") or legacy_status
                    logger.error(
                        f"[GoogleMapsNode] Legacy status error ({action_name}): {message}"
                    )
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": message,
                        "status_code": response.status_code,
                        "google_status": legacy_status,
                        "timing_ms": {"api_request": api_ms},
                    }

            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }

        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[GoogleMapsNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _waypoint(value: str) -> Dict[str, Any]:
    """Build a Routes API waypoint from a 'lat,lng' string or a free-text address."""
    parts = value.split(",")
    if len(parts) == 2:
        try:
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
            return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}
        except ValueError:
            pass
    return {"address": value}


def _split_pipe(value: str) -> List[str]:
    return [p.strip() for p in value.split("|") if p.strip()]


def _split_semicolon(value: str) -> List[str]:
    return [p.strip() for p in value.split(";") if p.strip()]


def _csv(value: Optional[str]) -> Optional[List[str]]:
    """Parse a comma-separated string into a list, or None if empty."""
    if not value:
        return None
    items = [p.strip() for p in value.split(",") if p.strip()]
    return items or None


def _latlng_query(lat: str, lng: str) -> Dict[str, Any]:
    """Flat dotted query params for the GET-style environment APIs."""
    return {"location.latitude": lat, "location.longitude": lng}


# ============================================================================
# Node Implementation
# ============================================================================


class GoogleMapsNode(WorkflowNode):
    """Google Maps Platform automation node."""

    edit_examples = [
        "Geocode a street address into latitude and longitude",
        "Search for coffee shops near a set of coordinates",
        "Compute the driving route between two addresses with distance and time",
        "Reverse geocode a lat-lng pair into a formatted address",
        "Validate and standardize a postal address",
        "Get the current air quality and pollen forecast for a city",
        "Look up the current weather and 10-day forecast for a location",
        "Get solar potential insights for a building at given coordinates",
        "Count how many restaurants are within 200m of a point",
    ]

    @classmethod
    def get_config_model(cls):
        return GoogleMapsNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, GoogleMapsNodeConfig):
            raise ValueError("Valid configuration is required")

        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Google Maps API key.")
        api_key = credentials.api_key

        handlers = {
            "geocode": self._geocode,
            "reverse_geocode": self._reverse_geocode,
            "geocode_v4_place": self._geocode_v4_place,
            "text_search": self._text_search,
            "nearby_search": self._nearby_search,
            "place_details": self._place_details,
            "autocomplete": self._autocomplete,
            "place_photo": self._place_photo,
            "compute_routes": self._compute_routes,
            "compute_route_matrix": self._compute_route_matrix,
            "directions": self._directions,
            "distance_matrix": self._distance_matrix,
            "validate_address": self._validate_address,
            "timezone": self._timezone,
            "elevation": self._elevation,
            "snap_to_roads": self._snap_to_roads,
            "nearest_roads": self._nearest_roads,
            "legacy_autocomplete": self._legacy_autocomplete,
            "find_place": self._find_place,
            "air_quality_current": self._air_quality_current,
            "air_quality_forecast": self._air_quality_forecast,
            "air_quality_history": self._air_quality_history,
            "pollen_forecast": self._pollen_forecast,
            "weather_current": self._weather_current,
            "weather_forecast_days": self._weather_forecast_days,
            "weather_forecast_hours": self._weather_forecast_hours,
            "weather_history_hours": self._weather_history_hours,
            "solar_building_insights": self._solar_building_insights,
            "solar_data_layers": self._solar_data_layers,
            "geolocate": self._geolocate,
            "aerial_render_video": self._aerial_render_video,
            "aerial_lookup_video": self._aerial_lookup_video,
            "compute_insights": self._compute_insights,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Geocoding
    # ------------------------------------------------------------------
    async def _geocode(self, c: GoogleMapsGeocodeConfig, api_key: str) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{MAPS_LEGACY_BASE}/geocode/json",
            api_key,
            use_header_auth=False,
            params={"address": c.address, "region": c.region, "language": c.language},
            inspect_legacy_status=True,
            action_name="geocode",
        )

    async def _reverse_geocode(
        self, c: GoogleMapsReverseGeocodeConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{MAPS_LEGACY_BASE}/geocode/json",
            api_key,
            use_header_auth=False,
            params={"latlng": c.latlng, "language": c.language},
            inspect_legacy_status=True,
            action_name="reverse_geocode",
        )

    async def _geocode_v4_place(
        self, c: GoogleMapsGeocodeV4Config, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{GEOCODE_V4_BASE}/geocode/places/{c.place_id}",
            api_key,
            use_header_auth=True,
            field_mask=c.field_mask,
            action_name="geocode_v4_place",
        )

    # ------------------------------------------------------------------
    # Places (New)
    # ------------------------------------------------------------------
    async def _text_search(
        self, c: GoogleMapsTextSearchConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "textQuery": c.text_query,
            "languageCode": c.language_code,
            "pageToken": c.page_token,
        }
        if c.max_result_count:
            body["maxResultCount"] = int(c.max_result_count)
        return await _maps_request(
            "POST",
            f"{PLACES_BASE}/places:searchText",
            api_key,
            use_header_auth=True,
            json_body=body,
            field_mask=c.field_mask,
            action_name="text_search",
        )

    async def _nearby_search(
        self, c: GoogleMapsNearbySearchConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": float(c.latitude),
                        "longitude": float(c.longitude),
                    },
                    "radius": float(c.radius),
                }
            },
        }
        if c.included_types:
            body["includedTypes"] = [t.strip() for t in c.included_types.split(",") if t.strip()]
        if c.max_result_count:
            body["maxResultCount"] = int(c.max_result_count)
        return await _maps_request(
            "POST",
            f"{PLACES_BASE}/places:searchNearby",
            api_key,
            use_header_auth=True,
            json_body=body,
            field_mask=c.field_mask,
            action_name="nearby_search",
        )

    async def _place_details(
        self, c: GoogleMapsPlaceDetailsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{PLACES_BASE}/places/{c.place_id}",
            api_key,
            use_header_auth=True,
            params={"languageCode": c.language_code},
            field_mask=c.field_mask,
            action_name="place_details",
        )

    async def _autocomplete(
        self, c: GoogleMapsAutocompleteConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "input": c.input_text,
            "languageCode": c.language_code,
            "regionCode": c.region_code,
        }
        return await _maps_request(
            "POST",
            f"{PLACES_BASE}/places:autocomplete",
            api_key,
            use_header_auth=True,
            json_body=body,
            field_mask=c.field_mask,
            action_name="autocomplete",
        )

    async def _place_photo(
        self, c: GoogleMapsPlacePhotoConfig, api_key: str
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "maxWidthPx": c.max_width_px,
            "maxHeightPx": c.max_height_px,
            "skipHttpRedirect": "true",
        }
        return await _maps_request(
            "GET",
            f"{PLACES_BASE}/{c.photo_name}/media",
            api_key,
            use_header_auth=True,
            params=params,
            action_name="place_photo",
        )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    async def _compute_routes(
        self, c: GoogleMapsComputeRoutesConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "origin": _waypoint(c.origin),
            "destination": _waypoint(c.destination),
            "travelMode": c.travel_mode,
        }
        if c.routing_preference:
            body["routingPreference"] = c.routing_preference
        return await _maps_request(
            "POST",
            f"{ROUTES_BASE}/directions/v2:computeRoutes",
            api_key,
            use_header_auth=True,
            json_body=body,
            field_mask=c.field_mask,
            action_name="compute_routes",
        )

    async def _compute_route_matrix(
        self, c: GoogleMapsComputeRouteMatrixConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "origins": [{"waypoint": _waypoint(o)} for o in _split_semicolon(c.origins)],
            "destinations": [
                {"waypoint": _waypoint(d)} for d in _split_semicolon(c.destinations)
            ],
            "travelMode": c.travel_mode,
        }
        return await _maps_request(
            "POST",
            f"{ROUTES_BASE}/distanceMatrix/v2:computeRouteMatrix",
            api_key,
            use_header_auth=True,
            json_body=body,
            field_mask=c.field_mask,
            action_name="compute_route_matrix",
        )

    # ------------------------------------------------------------------
    # Legacy routing
    # ------------------------------------------------------------------
    async def _directions(
        self, c: GoogleMapsDirectionsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{MAPS_LEGACY_BASE}/directions/json",
            api_key,
            use_header_auth=False,
            params={
                "origin": c.origin,
                "destination": c.destination,
                "mode": c.mode,
                "waypoints": c.waypoints,
            },
            inspect_legacy_status=True,
            action_name="directions",
        )

    async def _distance_matrix(
        self, c: GoogleMapsDistanceMatrixConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{MAPS_LEGACY_BASE}/distancematrix/json",
            api_key,
            use_header_auth=False,
            params={
                "origins": c.origins,
                "destinations": c.destinations,
                "mode": c.mode,
            },
            inspect_legacy_status=True,
            action_name="distance_matrix",
        )

    # ------------------------------------------------------------------
    # Address validation
    # ------------------------------------------------------------------
    async def _validate_address(
        self, c: GoogleMapsValidateAddressConfig, api_key: str
    ) -> Dict[str, Any]:
        address: Dict[str, Any] = {
            "addressLines": [
                line.strip() for line in c.address_lines.splitlines() if line.strip()
            ],
        }
        if c.region_code:
            address["regionCode"] = c.region_code
        if c.locality:
            address["locality"] = c.locality
        body: Dict[str, Any] = {"address": address}
        if c.enable_usps_cass == "true":
            body["enableUspsCass"] = True
        return await _maps_request(
            "POST",
            f"{ADDRESS_VALIDATION_BASE}:validateAddress",
            api_key,
            use_header_auth=False,
            json_body=body,
            action_name="validate_address",
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    async def _timezone(self, c: GoogleMapsTimeZoneConfig, api_key: str) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{MAPS_LEGACY_BASE}/timezone/json",
            api_key,
            use_header_auth=False,
            params={
                "location": c.location,
                "timestamp": c.timestamp,
                "language": c.language,
            },
            inspect_legacy_status=True,
            action_name="timezone",
        )

    async def _elevation(self, c: GoogleMapsElevationConfig, api_key: str) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{MAPS_LEGACY_BASE}/elevation/json",
            api_key,
            use_header_auth=False,
            params={"locations": c.locations},
            inspect_legacy_status=True,
            action_name="elevation",
        )

    # ------------------------------------------------------------------
    # Roads
    # ------------------------------------------------------------------
    async def _snap_to_roads(
        self, c: GoogleMapsSnapToRoadsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{ROADS_BASE}/snapToRoads",
            api_key,
            use_header_auth=False,
            params={
                "path": "|".join(_split_pipe(c.path)),
                "interpolate": "true" if c.interpolate == "true" else "false",
            },
            action_name="snap_to_roads",
        )

    async def _nearest_roads(
        self, c: GoogleMapsNearestRoadsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{ROADS_BASE}/nearestRoads",
            api_key,
            use_header_auth=False,
            params={"points": "|".join(_split_pipe(c.points))},
            action_name="nearest_roads",
        )

    # ------------------------------------------------------------------
    # Legacy places
    # ------------------------------------------------------------------
    async def _legacy_autocomplete(
        self, c: GoogleMapsLegacyAutocompleteConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{MAPS_LEGACY_BASE}/place/autocomplete/json",
            api_key,
            use_header_auth=False,
            params={
                "input": c.input_text,
                "language": c.language,
                "components": c.components,
            },
            inspect_legacy_status=True,
            action_name="legacy_autocomplete",
        )

    async def _find_place(
        self, c: GoogleMapsFindPlaceConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "GET",
            f"{MAPS_LEGACY_BASE}/place/findplacefromtext/json",
            api_key,
            use_header_auth=False,
            params={
                "input": c.input_text,
                "inputtype": c.input_type,
                "fields": c.fields,
            },
            inspect_legacy_status=True,
            action_name="find_place",
        )

    # ------------------------------------------------------------------
    # Environment: Air Quality (POST + ?key=, lat/lng nested in body)
    # ------------------------------------------------------------------
    async def _air_quality_current(
        self, c: GoogleMapsAirQualityCurrentConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "location": {"latitude": float(c.latitude), "longitude": float(c.longitude)},
            "universalAqi": c.universal_aqi == "true",
            "languageCode": c.language_code,
        }
        extras = _csv(c.extra_computations)
        if extras:
            body["extraComputations"] = extras
        return await _maps_request(
            "POST",
            f"{AIR_QUALITY_BASE}/currentConditions:lookup",
            api_key,
            use_header_auth=False,
            json_body=body,
            action_name="air_quality_current",
        )

    async def _air_quality_forecast(
        self, c: GoogleMapsAirQualityForecastConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "location": {"latitude": float(c.latitude), "longitude": float(c.longitude)},
            "languageCode": c.language_code,
            "pageToken": c.page_token,
        }
        if c.date_time:
            body["dateTime"] = c.date_time
        elif c.start_time and c.end_time:
            body["period"] = {"startTime": c.start_time, "endTime": c.end_time}
        else:
            raise ValueError(
                "Air quality forecast requires a time: provide a Date Time, or both "
                "Period Start and Period End (RFC3339)."
            )
        extras = _csv(c.extra_computations)
        if extras:
            body["extraComputations"] = extras
        if c.page_size:
            body["pageSize"] = int(c.page_size)
        return await _maps_request(
            "POST",
            f"{AIR_QUALITY_BASE}/forecast:lookup",
            api_key,
            use_header_auth=False,
            json_body=body,
            action_name="air_quality_forecast",
        )

    async def _air_quality_history(
        self, c: GoogleMapsAirQualityHistoryConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "location": {"latitude": float(c.latitude), "longitude": float(c.longitude)},
            "languageCode": c.language_code,
            "pageToken": c.page_token,
        }
        if c.hours:
            body["hours"] = int(c.hours)
        elif c.date_time:
            body["dateTime"] = c.date_time
        elif c.start_time and c.end_time:
            body["period"] = {"startTime": c.start_time, "endTime": c.end_time}
        else:
            raise ValueError(
                "Air quality history requires a time: provide Hours, a Date Time, or both "
                "Period Start and Period End (RFC3339)."
            )
        extras = _csv(c.extra_computations)
        if extras:
            body["extraComputations"] = extras
        if c.page_size:
            body["pageSize"] = int(c.page_size)
        return await _maps_request(
            "POST",
            f"{AIR_QUALITY_BASE}/history:lookup",
            api_key,
            use_header_auth=False,
            json_body=body,
            action_name="air_quality_history",
        )

    # ------------------------------------------------------------------
    # Environment: Pollen (GET + ?key=, flat dotted query)
    # ------------------------------------------------------------------
    async def _pollen_forecast(
        self, c: GoogleMapsPollenForecastConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            **_latlng_query(c.latitude, c.longitude),
            "days": c.days,
            "plantsDescription": "true" if c.plants_description == "true" else "false",
            "languageCode": c.language_code,
            "pageSize": c.page_size,
            "pageToken": c.page_token,
        }
        return await _maps_request(
            "GET",
            f"{POLLEN_BASE}/forecast:lookup",
            api_key,
            use_header_auth=False,
            params=params,
            action_name="pollen_forecast",
        )

    # ------------------------------------------------------------------
    # Environment: Weather (GET + ?key=, flat dotted query)
    # ------------------------------------------------------------------
    async def _weather_current(
        self, c: GoogleMapsWeatherCurrentConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            **_latlng_query(c.latitude, c.longitude),
            "unitsSystem": c.units_system,
            "languageCode": c.language_code,
        }
        return await _maps_request(
            "GET",
            f"{WEATHER_BASE}/currentConditions:lookup",
            api_key,
            use_header_auth=False,
            params=params,
            action_name="weather_current",
        )

    async def _weather_forecast_days(
        self, c: GoogleMapsWeatherForecastDaysConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            **_latlng_query(c.latitude, c.longitude),
            "days": c.days,
            "unitsSystem": c.units_system,
            "languageCode": c.language_code,
            "pageSize": c.page_size,
            "pageToken": c.page_token,
        }
        return await _maps_request(
            "GET",
            f"{WEATHER_BASE}/forecast/days:lookup",
            api_key,
            use_header_auth=False,
            params=params,
            action_name="weather_forecast_days",
        )

    async def _weather_forecast_hours(
        self, c: GoogleMapsWeatherForecastHoursConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            **_latlng_query(c.latitude, c.longitude),
            "hours": c.hours,
            "unitsSystem": c.units_system,
            "languageCode": c.language_code,
            "pageSize": c.page_size,
            "pageToken": c.page_token,
        }
        return await _maps_request(
            "GET",
            f"{WEATHER_BASE}/forecast/hours:lookup",
            api_key,
            use_header_auth=False,
            params=params,
            action_name="weather_forecast_hours",
        )

    async def _weather_history_hours(
        self, c: GoogleMapsWeatherHistoryHoursConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            **_latlng_query(c.latitude, c.longitude),
            "hours": c.hours,
            "unitsSystem": c.units_system,
            "languageCode": c.language_code,
            "pageSize": c.page_size,
            "pageToken": c.page_token,
        }
        return await _maps_request(
            "GET",
            f"{WEATHER_BASE}/history/hours:lookup",
            api_key,
            use_header_auth=False,
            params=params,
            action_name="weather_history_hours",
        )

    # ------------------------------------------------------------------
    # Environment: Solar (GET + ?key=, flat dotted query)
    # ------------------------------------------------------------------
    async def _solar_building_insights(
        self, c: GoogleMapsSolarBuildingInsightsConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            **_latlng_query(c.latitude, c.longitude),
            "requiredQuality": c.required_quality,
        }
        return await _maps_request(
            "GET",
            f"{SOLAR_BASE}/buildingInsights:findClosest",
            api_key,
            use_header_auth=False,
            params=params,
            action_name="solar_building_insights",
        )

    async def _solar_data_layers(
        self, c: GoogleMapsSolarDataLayersConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            **_latlng_query(c.latitude, c.longitude),
            "radiusMeters": c.radius_meters,
            "view": c.view,
            "requiredQuality": c.required_quality,
            "pixelSizeMeters": c.pixel_size_meters,
        }
        return await _maps_request(
            "GET",
            f"{SOLAR_BASE}/dataLayers:get",
            api_key,
            use_header_auth=False,
            params=params,
            action_name="solar_data_layers",
        )

    # ------------------------------------------------------------------
    # Geolocation (POST + ?key=)
    # ------------------------------------------------------------------
    async def _geolocate(
        self, c: GoogleMapsGeolocateConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"considerIp": c.consider_ip == "true"}
        if c.wifi_access_points:
            try:
                body["wifiAccessPoints"] = json.loads(c.wifi_access_points)
            except json.JSONDecodeError as e:
                raise ValueError(f"WiFi Access Points must be valid JSON: {e}")
        if c.cell_towers:
            try:
                body["cellTowers"] = json.loads(c.cell_towers)
            except json.JSONDecodeError as e:
                raise ValueError(f"Cell Towers must be valid JSON: {e}")
        return await _maps_request(
            "POST",
            f"{GEOLOCATION_BASE}/geolocate",
            api_key,
            use_header_auth=False,
            json_body=body,
            action_name="geolocate",
        )

    # ------------------------------------------------------------------
    # Aerial View (X-Goog-Api-Key header)
    # ------------------------------------------------------------------
    async def _aerial_render_video(
        self, c: GoogleMapsAerialRenderVideoConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _maps_request(
            "POST",
            f"{AERIAL_VIEW_BASE}/videos:renderVideo",
            api_key,
            use_header_auth=True,
            json_body={"address": c.address},
            action_name="aerial_render_video",
        )

    async def _aerial_lookup_video(
        self, c: GoogleMapsAerialLookupVideoConfig, api_key: str
    ) -> Dict[str, Any]:
        if not c.video_id and not c.address:
            raise ValueError("Provide either a Video ID or an Address to look up.")
        return await _maps_request(
            "GET",
            f"{AERIAL_VIEW_BASE}/videos:lookupVideo",
            api_key,
            use_header_auth=True,
            params={"videoId": c.video_id, "address": c.address},
            action_name="aerial_lookup_video",
        )

    # ------------------------------------------------------------------
    # Places Aggregate (X-Goog-Api-Key header)
    # ------------------------------------------------------------------
    async def _compute_insights(
        self, c: GoogleMapsComputeInsightsConfig, api_key: str
    ) -> Dict[str, Any]:
        if c.region_place_id:
            location_filter: Dict[str, Any] = {
                "region": {"place": f"places/{c.region_place_id}"}
            }
        elif c.latitude and c.longitude and c.radius:
            location_filter = {
                "circle": {
                    "latLng": {
                        "latitude": float(c.latitude),
                        "longitude": float(c.longitude),
                    },
                    "radius": float(c.radius),
                }
            }
        else:
            raise ValueError(
                "Provide either a Region Place ID or a circle (latitude, longitude, radius)."
            )

        type_filter: Dict[str, Any] = {"includedTypes": _csv(c.included_types)}
        excluded = _csv(c.excluded_types)
        if excluded:
            type_filter["excludedTypes"] = excluded

        filter_obj: Dict[str, Any] = {
            "locationFilter": location_filter,
            "typeFilter": type_filter,
        }
        if c.min_rating or c.max_rating:
            rating: Dict[str, Any] = {}
            if c.min_rating:
                rating["minRating"] = float(c.min_rating)
            if c.max_rating:
                rating["maxRating"] = float(c.max_rating)
            filter_obj["ratingFilter"] = rating

        body = {"insights": _csv(c.insights), "filter": filter_obj}
        return await _maps_request(
            "POST",
            f"{AREA_INSIGHTS_BASE}:computeInsights",
            api_key,
            use_header_auth=True,
            json_body=body,
            action_name="compute_insights",
        )
