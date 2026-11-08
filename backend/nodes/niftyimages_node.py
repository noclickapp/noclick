"""NiftyImages v2 image, map and store automation.

Contract: https://dev.niftyimages.com/openapi/v1.json, version 1.0.0.
Every operation issues exactly one request; cursor pages are returned separately.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://dev.niftyimages.com"


class NiftyimagesAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Niftyimages API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dev.niftyimages.com/docs/authentication",
            "x-credential-instructions": "Create an API key in NiftyImages and paste it here. NoClick sends it as a Bearer token to dev.niftyimages.com. Use a key with access to the stores and images you want to automate.",
        })
    credential_type: Literal["niftyimages_api_key"] = Field("niftyimages_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"store_id", "record_id", "location_id"}:
            if not value or value in {".", ".."} or any(ord(c) < 32 for c in value):
                raise ValueError("Use a nonempty resource ID without control characters or dot segments")
        return value


class _Page(_Input):
    limit: int = Field(25, ge=1, le=100, description="Maximum items on this page.")
    cursor: str | None = Field(None, description="Opaque nextCursor from the previous page. Keep all filters unchanged.")


class _Image(_Input):
    image_id: int = Field(..., ge=1, le=2147483647, description="Numeric NiftyImages image ID.")


class _Map(_Input):
    map_id: int = Field(..., ge=1, le=2147483647, description="Numeric map ID, from list_images with type=map.")


class _Store(_Input):
    store_id: str = Field(..., min_length=1, max_length=512, description="Store ID from list_stores.")


class _Record(_Store):
    record_id: str = Field(..., min_length=1, max_length=1024, description="Record ID returned by NiftyImages.")


class StoreProperty(_Input):
    name: str = Field(..., min_length=1)
    type: Literal["string", "number", "boolean", "datetime", "url_image", "url_link"]
    required: bool | None = None
    unique: bool | None = None
    description: str | None = None
    defaultValue: str | None = None
    dateInputFormat: str | None = None
    dateInputTimezone: str | None = None


class RecordFilter(_Input):
    field: str = Field(..., min_length=1, description="Store schema property name.")
    op: Literal["eq", "ne", "contains", "startsWith", "endsWith", "empty", "notEmpty", "gt", "gte", "lt", "lte", "on", "before", "after"]
    value: str | None = Field(None, description="Comparison text; boolean values use true/false and dates use ISO 8601.")


class NiftyimagesCheckConnectionConfig(_Input):
    """Read the account identity associated with this API key."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class NiftyimagesListImagesConfig(_Page):
    """List one page of account images."""
    operation: Literal["list_images"] = Field("list_images", json_schema_extra={"ui:hidden": True})
    type: str | None = Field(None, description="Image type, such as basic, countdown, canvas_timer or map.")
    status: Literal["active", "deleted", "all"] | None = None
    q: str | None = Field(None, description="Image name search.")


class NiftyimagesGetImageConfig(_Image):
    """Read image metadata and its rendered URL."""
    operation: Literal["get_image"] = Field("get_image", json_schema_extra={"ui:hidden": True})


class NiftyimagesRenameImageConfig(_Image):
    """Rename an image."""
    operation: Literal["rename_image"] = Field("rename_image", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=50)


class NiftyimagesDeleteImageConfig(_Image):
    """Soft-delete an image; the image stops serving content."""
    operation: Literal["delete_image"] = Field("delete_image", json_schema_extra={"ui:hidden": True})


class NiftyimagesRestoreImageConfig(_Image):
    """Restore a soft-deleted image to the root folder."""
    operation: Literal["restore_image"] = Field("restore_image", json_schema_extra={"ui:hidden": True})


class NiftyimagesLookupImageConfig(_Input):
    """Find an image by its production URL."""
    operation: Literal["lookup_image"] = Field("lookup_image", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description="Production NiftyImages URL or image path; query parameters are ignored.")


class NiftyimagesGetMapConfig(_Map):
    """Read map metadata and location counts."""
    operation: Literal["get_map"] = Field("get_map", json_schema_extra={"ui:hidden": True})


class NiftyimagesSearchLocationsConfig(_Map, _Page):
    """Search one page of map locations with one documented filter."""
    operation: Literal["search_locations"] = Field("search_locations", json_schema_extra={"ui:hidden": True})
    address: str | None = None
    uniqueId: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    radiusMiles: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def search_filter(self):
        coordinates = self.lat is not None or self.lng is not None
        if coordinates and (self.lat is None or self.lng is None):
            raise ValueError("Supply both latitude and longitude")
        if sum([self.address is not None, self.uniqueId is not None, coordinates]) != 1:
            raise ValueError("Supply exactly one filter: address, uniqueId, or lat and lng")
        if self.radiusMiles is not None and not coordinates:
            raise ValueError("A radius needs latitude and longitude")
        return self


class NiftyimagesAddLocationConfig(_Map):
    """Add an address for geocoding or a location with known coordinates."""
    operation: Literal["add_location"] = Field("add_location", json_schema_extra={"ui:hidden": True})
    address: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    uniqueId: str | None = None
    properties: list[str] | None = Field(None, description="Custom values in the map's positional field order.")

    @model_validator(mode="after")
    def location(self):
        if self.address:
            if self.latitude is not None or self.longitude is not None:
                raise ValueError("Supply an address or coordinates")
        elif self.latitude is None or self.longitude is None:
            raise ValueError("Supply an address or both coordinates")
        return self


class NiftyimagesGetLocationConfig(_Map):
    """Read one location within a map."""
    operation: Literal["get_location"] = Field("get_location", json_schema_extra={"ui:hidden": True})
    location_id: str = Field(..., min_length=1, max_length=1024)


class NiftyimagesDeleteLocationConfig(_Map):
    """Permanently delete one map location; unknown IDs are acknowledged too."""
    operation: Literal["delete_location"] = Field("delete_location", json_schema_extra={"ui:hidden": True})
    location_id: str = Field(..., min_length=1, max_length=1024)


class NiftyimagesListStoresConfig(_Page):
    """List one page of stores accessible to this key."""
    operation: Literal["list_stores"] = Field("list_stores", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, description="Store name search.")


class NiftyimagesGetStoreConfig(_Store):
    """Read store metadata and its property schema."""
    operation: Literal["get_store"] = Field("get_store", json_schema_extra={"ui:hidden": True})


class NiftyimagesCreateStoreConfig(_Input):
    """Create a store and its schema."""
    operation: Literal["create_store"] = Field("create_store", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    description: str | None = None
    recordTtl: int | None = Field(None, ge=-1, description="Default record lifetime in seconds; -1 means forever.")
    properties: list[StoreProperty] = Field(..., min_length=1, description="At least one schema property.")


class NiftyimagesDeleteStoreConfig(_Store):
    """Soft-delete a store; stored records remain until background cleanup."""
    operation: Literal["delete_store"] = Field("delete_store", json_schema_extra={"ui:hidden": True})


class NiftyimagesListRecordsConfig(_Store, _Page):
    """List one cursor page of store records."""
    operation: Literal["list_records"] = Field("list_records", json_schema_extra={"ui:hidden": True})
    sortBy: str | None = None
    sortDir: Literal["asc", "desc"] | None = None


class NiftyimagesAddRecordConfig(_Store):
    """Add one record using store property names as JSON keys."""
    operation: Literal["add_record"] = Field("add_record", json_schema_extra={"ui:hidden": True})
    record: dict[str, Any] = Field(..., description="JSON fields matching this store schema.")


class NiftyimagesGetRecordConfig(_Record):
    """Read one store record."""
    operation: Literal["get_record"] = Field("get_record", json_schema_extra={"ui:hidden": True})


class NiftyimagesPatchRecordConfig(_Record):
    """Partially update a record using JSON Merge Patch."""
    operation: Literal["patch_record"] = Field("patch_record", json_schema_extra={"ui:hidden": True})
    record: dict[str, Any] = Field(..., description="JSON Merge Patch: only changed fields; null unsets a field.")


class NiftyimagesDeleteRecordConfig(_Record):
    """Delete one record; unknown IDs are acknowledged too."""
    operation: Literal["delete_record"] = Field("delete_record", json_schema_extra={"ui:hidden": True})


class NiftyimagesBatchUpsertRecordsConfig(_Store):
    """Upsert up to 100 records with independent per-record results."""
    operation: Literal["batch_upsert_records"] = Field("batch_upsert_records", json_schema_extra={"ui:hidden": True})
    records: list[dict[str, Any]] = Field(..., min_length=1, max_length=100, description="Up to 100 records; inspect each returned status for partial failure.")


class NiftyimagesLookupRecordConfig(_Store):
    """Find a record by its unique-property values."""
    operation: Literal["lookup_record"] = Field("lookup_record", json_schema_extra={"ui:hidden": True})
    record: dict[str, Any] = Field(..., description="Unique property names and values used to compute the record ID.")


class NiftyimagesValidateRecordConfig(_Store):
    """Dry-run record validation without creating a record."""
    operation: Literal["validate_record"] = Field("validate_record", json_schema_extra={"ui:hidden": True})
    record: dict[str, Any] = Field(..., description="Candidate JSON fields to validate against the store schema without writing.")


class NiftyimagesSearchRecordsConfig(_Store):
    """Filter and sort up to 100 records; this endpoint does not return a cursor."""
    operation: Literal["search_records"] = Field("search_records", json_schema_extra={"ui:hidden": True})
    filters: list[RecordFilter] = Field(default_factory=list)
    match: Literal["all", "any"] = "all"
    sortBy: str | None = None
    sortDir: Literal["asc", "desc"] = "desc"
    limit: int = Field(25, ge=1, le=100)


NiftyimagesConfig = Annotated[Union[
    NiftyimagesCheckConnectionConfig,
    NiftyimagesListImagesConfig,
    NiftyimagesGetImageConfig,
    NiftyimagesRenameImageConfig,
    NiftyimagesDeleteImageConfig,
    NiftyimagesRestoreImageConfig,
    NiftyimagesLookupImageConfig,
    NiftyimagesGetMapConfig,
    NiftyimagesSearchLocationsConfig,
    NiftyimagesAddLocationConfig,
    NiftyimagesGetLocationConfig,
    NiftyimagesDeleteLocationConfig,
    NiftyimagesListStoresConfig,
    NiftyimagesGetStoreConfig,
    NiftyimagesCreateStoreConfig,
    NiftyimagesDeleteStoreConfig,
    NiftyimagesListRecordsConfig,
    NiftyimagesAddRecordConfig,
    NiftyimagesGetRecordConfig,
    NiftyimagesPatchRecordConfig,
    NiftyimagesDeleteRecordConfig,
    NiftyimagesBatchUpsertRecordsConfig,
    NiftyimagesLookupRecordConfig,
    NiftyimagesValidateRecordConfig,
    NiftyimagesSearchRecordsConfig
], Field(discriminator="operation")]


class NiftyimagesFullConfig(NodeConfig[NiftyimagesConfig, NiftyimagesAPIKeyCredential]):
    pass

# method, route, query fields, body fields (or dynamic record), success statuses.
ROUTES = {'check_connection': ('GET', '/v2/whoami', [], None, [200]),
 'list_images': ('GET', '/v2/images', ['limit', 'cursor', 'type', 'status', 'q'], None, [200]),
 'get_image': ('GET', '/v2/images/{image_id}', [], None, [200]),
 'rename_image': ('PATCH', '/v2/images/{image_id}', [], ['name'], [204]),
 'delete_image': ('DELETE', '/v2/images/{image_id}', [], None, [204]),
 'restore_image': ('POST', '/v2/images/{image_id}/restore', [], None, [204]),
 'lookup_image': ('POST', '/v2/images/lookup', [], ['url'], [200]),
 'get_map': ('GET', '/v2/maps/{map_id}', [], None, [200]),
 'search_locations': ('GET',
                      '/v2/maps/{map_id}/locations',
                      ['limit', 'cursor', 'address', 'uniqueId', 'lat', 'lng', 'radiusMiles'],
                      None,
                      [200]),
 'add_location': ('POST',
                  '/v2/maps/{map_id}/locations',
                  [],
                  ['address', 'latitude', 'longitude', 'uniqueId', 'properties'],
                  [201]),
 'get_location': ('GET', '/v2/maps/{map_id}/locations/{location_id}', [], None, [200]),
 'delete_location': ('DELETE', '/v2/maps/{map_id}/locations/{location_id}', [], None, [204]),
 'list_stores': ('GET', '/v2/stores', ['limit', 'cursor', 'q'], None, [200]),
 'get_store': ('GET', '/v2/stores/{store_id}', [], None, [200]),
 'create_store': ('POST',
                  '/v2/stores',
                  [],
                  ['name', 'description', 'recordTtl', 'properties'],
                  [201]),
 'delete_store': ('DELETE', '/v2/stores/{store_id}', [], None, [200]),
 'list_records': ('GET',
                  '/v2/stores/{store_id}/records',
                  ['limit', 'cursor', 'sortBy', 'sortDir'],
                  None,
                  [200]),
 'add_record': ('POST', '/v2/stores/{store_id}/records', [], 'record', [201]),
 'get_record': ('GET', '/v2/stores/{store_id}/records/{record_id}', [], None, [200]),
 'patch_record': ('PATCH', '/v2/stores/{store_id}/records/{record_id}', [], 'record', [200]),
 'delete_record': ('DELETE', '/v2/stores/{store_id}/records/{record_id}', [], None, [200]),
 'batch_upsert_records': ('POST', '/v2/stores/{store_id}/records/batch', [], ['records'], [200]),
 'lookup_record': ('POST', '/v2/stores/{store_id}/records/lookup', [], 'record', [200]),
 'validate_record': ('POST', '/v2/stores/{store_id}/records/validate', [], 'record', [200]),
 'search_records': ('POST',
                    '/v2/stores/{store_id}/records/search',
                    [],
                    ['filters', 'match', 'sortBy', 'sortDir', 'limit'],
                    [200])}


class NiftyimagesNode(WorkflowNode):
    integration_type = "automation-niftyimages"
    connection_evidence = ConnectionEvidence(
        noun="stores", operation="list_stores", identity_operation="check_connection",
        identity_keys=("email", "name", "apiKeyID"),
    )

    @classmethod
    def get_config_model(cls):
        return NiftyimagesFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a NiftyImages API key")
        cfg = self.config.config
        values = cfg.model_dump(mode="json")
        method, template, query_fields, body_fields, statuses = ROUTES[cfg.operation]
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items() if k.endswith("_id")})
        params = {k: values[k] for k in query_fields if values[k] is not None}
        body = values["record"] if body_fields == "record" else {k: values[k] for k in body_fields} if body_fields else None
        headers = {"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, headers=headers,
                    **({"json": body} if body is not None else {}))
            if response.status_code not in statuses:
                message = "NiftyImages did not confirm this operation"
                try:
                    problem = response.json()
                    if isinstance(problem, dict):
                        message = next((problem[k] for k in ("detail", "message", "title") if isinstance(problem.get(k), str) and problem[k]), message)
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code,
                    "error": message.replace(self.config.credentials.api_key, "[redacted]")}
            if response.status_code == 204:
                return {"status": "success", "http_status": 204, "acknowledged": True}
            data = response.json()
            if not isinstance(data, dict) or "error" in data or "errors" in data:
                raise ValueError("Unexpected NiftyImages response")
            result = {"status": "success", "http_status": response.status_code, "data": data}
            if cfg.operation in {"list_images", "list_stores", "list_records", "search_locations"}:
                if not isinstance(data.get("data"), list) or "nextCursor" not in data or not (data["nextCursor"] is None or isinstance(data["nextCursor"], str)):
                    raise ValueError("Unexpected cursor page")
                result.update(data=data["data"], next_cursor=data["nextCursor"], has_more=data["nextCursor"] is not None)
            # Never follow URLs or retry writes; retain per-record batch outcomes.
            return result
        except (httpx.HTTPError, ValueError, SSRFError):
            return {"status": "error", "error": "NiftyImages response could not be confirmed; inspect the resource before retrying a write"}
