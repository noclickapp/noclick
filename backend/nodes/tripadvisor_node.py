"""Tripadvisor Terra API: fixed, one-request operations using a partner API key.

Contract: https://docs.terra.tripadvisor.com/openapi/{account,partner,feed}-api.yaml
Pages are explicit; the node never follows response links or downloads feed URLs.
Review-owner actions need a separate member OAuth token and are not exposed.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://terra.tripadvisor.com/api"
NODE_TYPE = "automation-tripadvisor"


class TripadvisorAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tripadvisor API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://terra.tripadvisor.com/",
            "x-credential-instructions": "Paste your Tripadvisor Terra partner API key. NoClick sends it as X-API-Key only to terra.tripadvisor.com. Your package determines access to content, feeds and allowlist management. Connecting reads the account's location allowlist; it does not prove write permission. Member OAuth review-owner actions are not included.",
        })
    credential_type: Literal["tripadvisor_api_key"] = Field("tripadvisor_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(char.isspace() for char in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="after")
    def documented_bounds(self):
        # The OpenAPI scalar types omit the mutually exclusive area strategies.
        # https://docs.terra.tripadvisor.com/reference/locationsnearbyget
        if self.operation in {"search_nearby_catalog", "search_nearby_locations"}:
            box = [self.sw_lat, self.sw_lon, self.ne_lat, self.ne_lon]
            if any(value is not None for value in box):
                if not all(value is not None for value in box) or any(
                    value is not None for value in [self.location_id, self.lat, self.lon, self.radius]
                ):
                    raise ValueError("Supply all four bounding-box corners, without a radius or center")
                try:
                    a, b, c, d = map(float, box)
                except ValueError:
                    raise ValueError("Bounding-box coordinates must be numbers") from None
                if not (-90 <= a < c <= 90 and -180 <= b <= 180 and -180 <= d <= 180):
                    raise ValueError("Use valid coordinates with southwest latitude below northeast latitude")
                if any(item.startswith("distance") for item in self.sort):
                    raise ValueError("Distance sorting requires a radius search")
            else:
                if self.location_id is not None:
                    if self.lat is not None or self.lon is not None:
                        raise ValueError("Use either a location ID or coordinates as the center")
                elif self.lat is None or self.lon is None:
                    raise ValueError("Supply a location ID or both latitude and longitude")
                if self.radius is None or not math.isfinite(self.radius) or self.radius > (8 if self.unit == "KM" else 5):
                    raise ValueError("Supply a radius up to 8 KM or 5 MI")
            if self.unit not in {"KM", "MI"}:
                raise ValueError("Unit must be KM or MI")
            if self.min_rating is not None:
                try:
                    rating = float(self.min_rating)
                except ValueError:
                    raise ValueError("Minimum rating must be from 1 to 5") from None
                if not 1 <= rating <= 5:
                    raise ValueError("Minimum rating must be from 1 to 5")
            if self.operation == "search_nearby_locations" and self.size * ((self.page or 1) - 1) > 40:
                raise ValueError("Nearby Location result offset cannot exceed 40")
        if self.operation in {"get_locations", "get_geos"}:
            if not self.id or len(set(self.id)) != len(self.id) or any(not 1 <= item <= 2147483647 for item in self.id):
                raise ValueError("Use unique positive int32 Tripadvisor IDs")
        return self


class TripadvisorListAllowlistConfig(_Input):
    """Get Location allowlist IDs."""
    operation: Literal["list_allowlist"] = Field("list_allowlist", json_schema_extra={"ui:hidden": True})
    size: int = Field(1000, ge=1, le=1000, description='maximum number of IDs to return (between 1 and 1000, defaults to 1000)')
    cursor: Optional[str] = Field(None, description='the <code>pagination.next_cursor</code> of the previous page; omit it to start from the beginning')

class TripadvisorUpdateAllowlistConfig(_Input):
    """Add, remove, or replace location IDs."""
    operation: Literal["update_allowlist"] = Field("update_allowlist", json_schema_extra={"ui:hidden": True})
    operation_type: Literal["APPEND", "DELETE", "OVERWRITE"] = Field(...,
        description="APPEND adds IDs; DELETE removes IDs; OVERWRITE replaces the complete allowlist, including clearing it with an empty list.")
    allowlist: list[int] = Field(..., max_length=10000, description="Unique Tripadvisor location IDs to apply. An empty OVERWRITE clears the account allowlist.")

    @field_validator("allowlist")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value) or any(not -2147483648 <= item <= 2147483647 for item in value):
            raise ValueError("Use unique int32 location IDs")
        return value

class TripadvisorSearchNearbyCatalogConfig(_Input):
    """Search Nearby Locations Catalog."""
    operation: Literal["search_nearby_catalog"] = Field("search_nearby_catalog", json_schema_extra={"ui:hidden": True})
    location_id: Optional[str] = Field(None, description='The ID of the Location to use as a reference for the radius-based search.\n <p>\n Required if `lat` or `lon` is not given.')
    lat: Optional[float] = Field(None, ge=-90, le=90, description='The latitude of the center point for the radius-based search.\n <p>\n Required if `location_id` not given.')
    lon: Optional[float] = Field(None, ge=-180, le=180, description='The longitude of the center point for the radius-based search.\n <p>\n Required if `location_id` not given.')
    radius: Optional[float] = Field(None, gt=0, description='The radius for the radius-based search.\n <p>\n Required if "Bounding Box" criteria is not given (`sw_lat`, `sw_lon`, `ne_lat`, `ne_lon`).')
    unit: str = Field('MI', description='Unit of length for distance. If none specified defaults to miles.')
    sw_lat: Optional[str] = Field(None, description='Bounding Box southwest latitude coordinate.\n <p>\n Required if `radius` is not given.')
    sw_lon: Optional[str] = Field(None, description='Bounding Box southwest longitude coordinate.\n <p>\n Required if `radius` is not given.')
    ne_lat: Optional[str] = Field(None, description='Bounding Box northeast latitude coordinate.\n <p>\n Required if `radius` is not given.')
    ne_lon: Optional[str] = Field(None, description='Bounding Box northeast longitude coordinate.\n <p>\n Required if `radius` is not given.')
    category: Optional[Literal['RESTAURANT', 'ATTRACTION', 'HOTEL']] = Field(None, description='Filter based on Tripadvisor’s top-level categories (eat & drink, accommodations, attractions).')
    min_rating: Optional[str] = Field(None, description='Filter by ratings with at least N bubbles (1.0-5.0).')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority order;\n                 falls back to the default locale when omitted')
    page: Optional[int] = Field(None, ge=1, description='Page index (1-based).')
    size: int = Field(20, ge=1, le=20, description='Page size.')
    sort: list[str] = Field(['rating,desc'], max_length=100, description='Sorting criteria in the format: property,(asc|desc). Multiple sort criteria are supported. Available sorting: `distance` (for radius-based search only), `rating`')

class TripadvisorSearchCatalogConfig(_Input):
    """Search Locations Catalog."""
    operation: Literal["search_catalog"] = Field("search_catalog", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=500, description='Text search query.')
    search_type: str = Field('NAME', description='Searching type.')
    country_code: Optional[str] = Field(None, pattern='^[A-Z]{2}$', description='Alpha-2 country code.')
    geo_name: Optional[str] = Field(None, description='City, Town, or Country Geo Name.')
    postal_code: Optional[str] = Field(None, description='Postal/zip code to further narrow results.\n <p>\n If both `geo_name` and `postal_code` are given, the `postal_code` takes precedence in case they do not resolve.')
    category: Optional[Literal['RESTAURANT', 'ATTRACTION', 'HOTEL']] = Field(None, description='Filter based on Tripadvisor’s top-level categories (eat & drink, accommodations, attractions).')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority order;\n               falls back to the default locale when omitted')
    page: Optional[int] = Field(None, ge=1, description='Page index (1-based).')
    size: int = Field(20, ge=1, le=20, description='Page size.')

class TripadvisorGetCatalogLocationConfig(_Input):
    """Get Catalog Location."""
    operation: Literal["get_catalog_location"] = Field("get_catalog_location", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='the Tripadvisor Location ID to retrieve')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority order;\n               falls back to the default locale when omitted')

    @field_validator("id")
    @classmethod
    def int32_id(cls, value):
        if not -2147483648 <= value <= 2147483647:
            raise ValueError("Use an int32 Tripadvisor ID")
        return value

class TripadvisorGetGeosConfig(_Input):
    """Multiple Geos Details."""
    operation: Literal["get_geos"] = Field("get_geos", json_schema_extra={"ui:hidden": True})
    id: list[int] = Field(..., max_length=100, description='the set of Tripadvisor Geo IDs to retrieve')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority order;\n               falls back to the default locale when omitted')

class TripadvisorGetGeoConfig(_Input):
    """Geo Details."""
    operation: Literal["get_geo"] = Field("get_geo", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='the Tripadvisor Geo ID to retrieve')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority order;\n               falls back to the default locale when omitted')

    @field_validator("id")
    @classmethod
    def int32_id(cls, value):
        if not -2147483648 <= value <= 2147483647:
            raise ValueError("Use an int32 Tripadvisor ID")
        return value

class TripadvisorGetLocationsConfig(_Input):
    """Multiple Locations Details."""
    operation: Literal["get_locations"] = Field("get_locations", json_schema_extra={"ui:hidden": True})
    id: list[int] = Field(..., max_length=100, description='the set of Tripadvisor Location IDs to retrieve')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority order;\n               falls back to the default locale when omitted')

class TripadvisorSearchNearbyLocationsConfig(_Input):
    """Search Nearby Locations."""
    operation: Literal["search_nearby_locations"] = Field("search_nearby_locations", json_schema_extra={"ui:hidden": True})
    location_id: Optional[str] = Field(None, description='The ID of the Location to use as a reference for the radius-based search.\n <p>\n Required if `lat` or `lon` is not given.')
    lat: Optional[float] = Field(None, ge=-90, le=90, description='The latitude of the center point for the radius-based search.\n <p>\n Required if `location_id` not given.')
    lon: Optional[float] = Field(None, ge=-180, le=180, description='The longitude of the center point for the radius-based search.\n <p>\n Required if `location_id` not given.')
    radius: Optional[float] = Field(None, gt=0, description='The radius for the radius-based search.\n <p>\n Required if "Bounding Box" criteria is not given (`sw_lat`, `sw_lon`, `ne_lat`, `ne_lon`).')
    unit: str = Field('MI', description='Unit of length for distance. If none specified defaults to miles.')
    sw_lat: Optional[str] = Field(None, description='Bounding Box southwest latitude coordinate.\n <p>\n Required if `radius` is not given.')
    sw_lon: Optional[str] = Field(None, description='Bounding Box southwest longitude coordinate.\n <p>\n Required if `radius` is not given.')
    ne_lat: Optional[str] = Field(None, description='Bounding Box northeast latitude coordinate.\n <p>\n Required if `radius` is not given.')
    ne_lon: Optional[str] = Field(None, description='Bounding Box northeast longitude coordinate.\n <p>\n Required if `radius` is not given.')
    category: Optional[Literal['RESTAURANT', 'ATTRACTION', 'HOTEL']] = Field(None, description='Filter based on Tripadvisor’s top-level categories (eat & drink, accommodations, attractions).')
    min_rating: Optional[str] = Field(None, description='Filter by ratings with at least N bubbles (1.0-5.0).')
    include_photo: bool = Field(False, description='when <code>true</code>, include a single representative photo for each Location')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority\n                     order; falls back to the default locale when omitted')
    page: Optional[int] = Field(None, ge=1, description='Page index (1-based).')
    size: int = Field(20, ge=1, le=20, description='Page size.')
    sort: list[str] = Field(['rating,desc'], max_length=100, description='Sorting criteria in the format: property,(asc|desc). Multiple sort criteria are supported. Available sorting: `distance` (for radius-based search only), `rating`')

class TripadvisorSearchLocationsConfig(_Input):
    """Search Locations."""
    operation: Literal["search_locations"] = Field("search_locations", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=500, description='Text search query.')
    search_type: str = Field('NAME', description='Searching type.')
    country_code: Optional[str] = Field(None, pattern='^[A-Z]{2}$', description='Alpha-2 country code.')
    geo_name: Optional[str] = Field(None, description='City, Town, or Country Geo Name.')
    postal_code: Optional[str] = Field(None, description='Postal/zip code to further narrow results.\n <p>\n If both `geo_name` and `postal_code` are given, the `postal_code` takes precedence in case they do not resolve.')
    category: Optional[Literal['RESTAURANT', 'ATTRACTION', 'HOTEL']] = Field(None, description='Filter based on Tripadvisor’s top-level categories (eat & drink, accommodations, attractions).')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority order;\n               falls back to the default locale when omitted')
    page: Optional[int] = Field(None, ge=1, description='Page index (1-based).')
    size: int = Field(20, ge=1, le=20, description='Page size.')

class TripadvisorGetLocationConfig(_Input):
    """Location Details."""
    operation: Literal["get_location"] = Field("get_location", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='the Tripadvisor Location ID to retrieve')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. names, descriptions), in priority order;\n               falls back to the default locale when omitted')

    @field_validator("id")
    @classmethod
    def int32_id(cls, value):
        if not -2147483648 <= value <= 2147483647:
            raise ValueError("Use an int32 Tripadvisor ID")
        return value

class TripadvisorListPhotosConfig(_Input):
    """Location Photos."""
    operation: Literal["list_photos"] = Field("list_photos", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='the Tripadvisor Location ID to retrieve photos for')
    locale: Optional[list[str]] = Field(None, max_length=100, description='preferred locales for localized fields (e.g. captions), in priority order; falls back\n                 to the default locale when omitted')
    page: Optional[int] = Field(None, ge=0, description='Page')
    size: Optional[int] = Field(None, ge=1, description='Size')
    sort: Optional[list[str]] = Field(None, max_length=100, description='Sort')

    @field_validator("id")
    @classmethod
    def int32_id(cls, value):
        if not -2147483648 <= value <= 2147483647:
            raise ValueError("Use an int32 Tripadvisor ID")
        return value

class TripadvisorListReviewsConfig(_Input):
    """Location Reviews."""
    operation: Literal["list_reviews"] = Field("list_reviews", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='the Tripadvisor Location ID to retrieve reviews for')
    rating_min: Optional[float] = Field(None, description='when set, only return reviews with an overall rating of at least this\n                               value')
    trip_type: Optional[str] = Field(None, description='when set, only return reviews tagged with this trip type (e.g. business,\n                               family, couples)')
    published_after_ts: Optional[date] = Field(None, description='when set, only return reviews published on or after this date\n                               (format: <code>YYYY-MM-DD</code>)')
    sort_by: Optional[Literal['MOST_RECENT', 'HIGHEST_RATED']] = Field(None, description='ordering to apply to the reviews (defaults to most recent)')
    published_after_review_id: Optional[str] = Field(None, description='cursor for keyset pagination; returns reviews published after the review\n                               with this ID')
    language: Optional[str] = Field(None, description='UGC language code (e.g. <code>en</code>, <code>fr</code>) or the special keyword\n                               <code>primary</code> to return reviews in their original written language.\n                               Defaults to <code>en</code> when absent.')
    page: Optional[int] = Field(None, description='Page index (1-based).')
    size: Optional[int] = Field(None, description='Page size.')

    @field_validator("id")
    @classmethod
    def int32_id(cls, value):
        if not -2147483648 <= value <= 2147483647:
            raise ValueError("Use an int32 Tripadvisor ID")
        return value

class TripadvisorListFeedFilesConfig(_Input):
    """List Files."""
    operation: Literal["list_feed_files"] = Field("list_feed_files", json_schema_extra={"ui:hidden": True})
    page: Optional[int] = Field(None, ge=0, description='Page')
    size: Optional[int] = Field(None, ge=1, description='Size')
    sort: Optional[list[str]] = Field(None, max_length=100, description='Sort')

class TripadvisorGetFeedFileUrlConfig(_Input):
    """Feed File URL."""
    operation: Literal["get_feed_file_url"] = Field("get_feed_file_url", json_schema_extra={"ui:hidden": True})
    filename: str = Field(..., description='name of the file to get download data for')

    @field_validator("filename")
    @classmethod
    def single_filename(cls, value):
        if value in {".", ".."} or not value or len(value) > 1024 or any(c in value for c in "/\\\r\n\x00"):
            raise ValueError("Use one feed filename from List Feed Files")
        return value


TripadvisorConfig = Annotated[Union[
    TripadvisorListAllowlistConfig,
    TripadvisorUpdateAllowlistConfig,
    TripadvisorSearchNearbyCatalogConfig,
    TripadvisorSearchCatalogConfig,
    TripadvisorGetCatalogLocationConfig,
    TripadvisorGetGeosConfig,
    TripadvisorGetGeoConfig,
    TripadvisorGetLocationsConfig,
    TripadvisorSearchNearbyLocationsConfig,
    TripadvisorSearchLocationsConfig,
    TripadvisorGetLocationConfig,
    TripadvisorListPhotosConfig,
    TripadvisorListReviewsConfig,
    TripadvisorListFeedFilesConfig,
    TripadvisorGetFeedFileUrlConfig
], Field(discriminator="operation")]


class TripadvisorFullConfig(NodeConfig[TripadvisorConfig, TripadvisorAPIKeyCredential]):
    pass


ROUTES = {'list_allowlist': ('GET', '/allowlist', [], ['size', 'cursor']),
 'update_allowlist': ('POST', '/allowlist', [], []),
 'search_nearby_catalog': ('GET',
                           '/catalog/locations/nearby',
                           [],
                           ['location_id',
                            'lat',
                            'lon',
                            'radius',
                            'unit',
                            'sw_lat',
                            'sw_lon',
                            'ne_lat',
                            'ne_lon',
                            'category',
                            'min_rating',
                            'locale',
                            'page',
                            'size',
                            'sort']),
 'search_catalog': ('GET',
                    '/catalog/locations/search',
                    [],
                    ['query',
                     'search_type',
                     'country_code',
                     'geo_name',
                     'postal_code',
                     'category',
                     'locale',
                     'page',
                     'size']),
 'get_catalog_location': ('GET', '/catalog/locations/{id}', ['id'], ['locale']),
 'get_geos': ('GET', '/geos', [], ['id', 'locale']),
 'get_geo': ('GET', '/geos/{id}', ['id'], ['locale']),
 'get_locations': ('GET', '/locations', [], ['id', 'locale']),
 'search_nearby_locations': ('GET',
                             '/locations/nearby',
                             [],
                             ['location_id',
                              'lat',
                              'lon',
                              'radius',
                              'unit',
                              'sw_lat',
                              'sw_lon',
                              'ne_lat',
                              'ne_lon',
                              'category',
                              'min_rating',
                              'include_photo',
                              'locale',
                              'page',
                              'size',
                              'sort']),
 'search_locations': ('GET',
                      '/locations/search',
                      [],
                      ['query',
                       'search_type',
                       'country_code',
                       'geo_name',
                       'postal_code',
                       'category',
                       'locale',
                       'page',
                       'size']),
 'get_location': ('GET', '/locations/{id}', ['id'], ['locale']),
 'list_photos': ('GET', '/locations/{id}/photos', ['id'], ['locale', 'page', 'size', 'sort']),
 'list_reviews': ('GET',
                  '/locations/{id}/reviews',
                  ['id'],
                  ['rating_min',
                   'trip_type',
                   'published_after_ts',
                   'sort_by',
                   'published_after_review_id',
                   'language',
                   'page',
                   'size']),
 'list_feed_files': ('GET', '/feeds/files/list', [], ['page', 'size', 'sort']),
 'get_feed_file_url': ('GET', '/feeds/json/{filename}', ['filename'], [])}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(secret, "[redacted]"): _redact(item, secret) for key, item in value.items()}
    return value


class TripadvisorNode(WorkflowNode):
    integration_type = "automation-tripadvisor"
    connection_evidence = ConnectionEvidence(
        noun="allowlisted Tripadvisor locations", operation="list_allowlist")

    @classmethod
    def get_config_model(cls):
        return TripadvisorFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Tripadvisor Terra API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path, path_fields, query_fields = ROUTES[config.operation]
        for name in path_fields:
            path = path.replace("{" + name + "}", quote(str(getattr(config, name)), safe=""))
        params = []
        for name in query_fields:
            value = getattr(config, name)
            if value is None:
                continue
            for item in value if isinstance(value, list) else [value]:
                params.append((name, str(item).lower() if isinstance(item, bool) else str(item)))
        body = {"operation_type": config.operation_type, "allowlist": config.allowlist} if config.operation == "update_allowlist" else None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"X-API-Key": secret, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Tripadvisor request did not complete; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            # The evidence seam needs the provider's verbatim rejection, with secrets removed.
            message = _redact(response.text[:2000], secret)
            raise ValueError(f"Tripadvisor HTTP {response.status_code}: {message}")
        if len(response.content) > 20_000_000:
            raise ValueError("Tripadvisor response exceeds the JSON size limit")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Tripadvisor returned invalid JSON") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("Tripadvisor returned an unexpected JSON envelope")
        output = {"status": "success", "operation": config.operation,
            "data": _redact(data, secret), "http_status": response.status_code}
        if config.operation == "list_allowlist":
            if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not isinstance(data.get("pagination"), dict):
                raise ValueError("Tripadvisor returned an invalid allowlist page")
            ids = data["data"]
            if any(type(item) is not int or not -2147483648 <= item <= 2147483647 for item in ids):
                raise ValueError("Tripadvisor returned invalid allowlist IDs")
            # Evidence consumes named rows, while Terra returns bare integer IDs.
            # Keep the complete provider page in data for cursor-based workflows.
            output["items"] = [{"id": str(item), "name": f"Tripadvisor location {item}"} for item in ids]
        await self.emit(output)
        return output
