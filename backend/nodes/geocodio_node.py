"""Geocodio v2.1: geocoding, distances and spreadsheet jobs.

Contract: https://api.geocod.io/openapi-spec.json (2.1.0).
Provider reference: https://www.geocod.io/docs/.
Each operation makes exactly one documented request; pages and jobs are explicit.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.geocod.io/v2.1"


class GeocodioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Geocodio API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dash.geocod.io/apikey/",
        "x-credential-instructions": "Create or copy an API key in your Geocodio dashboard. Paste the key here. Give it the permissions needed for your geocoding, distance or spreadsheet operations. NoClick checks the key by reading your uploaded spreadsheets.",
    })
    credential_type: Literal["geocodio_api_key"] = Field("geocodio_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the API key without a URL, header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


AppendField = Literal[
    'cd113',
    'cd114',
    'cd115',
    'cd116',
    'cd117',
    'cd118',
    'cd119',
    'cd120',
    'cd',
    'census2000',
    'census2010',
    'census2011',
    'census2012',
    'census2013',
    'census2014',
    'census2015',
    'census2016',
    'census2017',
    'census2018',
    'census2019',
    'census2020',
    'census2021',
    'census2022',
    'census2023',
    'census2024',
    'census2025',
    'census',
    'stateleg',
    'stateleg-next',
    'school',
    'ffiec',
    'zip4',
    'acs-demographics',
    'acs-demographics-block_group',
    'acs-demographics-tract',
    'acs-demographics-zcta',
    'acs-demographics-place',
    'acs-demographics-msa',
    'acs-demographics-county',
    'acs-demographics-county_subdivision',
    'acs-demographics-state',
    'acs-demographics-division',
    'acs-demographics-region',
    'acs-demographics-nation',
    'acs-economics',
    'acs-economics-block_group',
    'acs-economics-tract',
    'acs-economics-zcta',
    'acs-economics-place',
    'acs-economics-msa',
    'acs-economics-county',
    'acs-economics-county_subdivision',
    'acs-economics-state',
    'acs-economics-division',
    'acs-economics-region',
    'acs-economics-nation',
    'acs-families',
    'acs-families-block_group',
    'acs-families-tract',
    'acs-families-zcta',
    'acs-families-place',
    'acs-families-msa',
    'acs-families-county',
    'acs-families-county_subdivision',
    'acs-families-state',
    'acs-families-division',
    'acs-families-region',
    'acs-families-nation',
    'acs-housing',
    'acs-housing-block_group',
    'acs-housing-tract',
    'acs-housing-zcta',
    'acs-housing-place',
    'acs-housing-msa',
    'acs-housing-county',
    'acs-housing-county_subdivision',
    'acs-housing-state',
    'acs-housing-division',
    'acs-housing-region',
    'acs-housing-nation',
    'acs-social',
    'acs-social-block_group',
    'acs-social-tract',
    'acs-social-zcta',
    'acs-social-place',
    'acs-social-msa',
    'acs-social-county',
    'acs-social-county_subdivision',
    'acs-social-state',
    'acs-social-division',
    'acs-social-region',
    'acs-social-nation',
    'riding',
    'riding-next',
    'provriding',
    'provriding-next',
    'statcan',
    'uk-westminster',
    'uk-westminster-next',
    'uk-devolved',
    'uk-devolved-next',
    'uk-local',
    'uk-local-next',
    'uk-census',
    'au-census2021',
    'au-census',
    'au-demographics',
    'au-housing',
    'au-income',
    'au-federal-electorate',
    'au-federal-electorate-next',
    'au-state-electorate',
    'timezone',
    'gazetteer',
]


class _Appends(_Input):
    fields: list[AppendField] | None = Field(None, title="Data Appends", description="Optional data appends; each append adds billable lookups.")


class _GeocodeOptions(_Appends):
    limit: int | None = Field(None, ge=0, description="Maximum results per query. Zero means no limit.")
    country: str | None = Field(None, min_length=1, title="Default Country")
    destinations: list[str] | None = Field(None, max_length=100, description="Optional destination coordinates or addresses for distance appends.")
    distance_mode: Literal["driving", "straightline"] | None = None
    distance_units: Literal["miles", "km"] | None = None
    distance_max_results: int | None = Field(None, ge=1)
    distance_max_distance: float | None = Field(None, ge=0)
    distance_min_distance: float | None = Field(None, ge=0)
    distance_max_duration: int | None = Field(None, ge=0)
    distance_min_duration: int | None = Field(None, ge=0)
    distance_order_by: Literal["distance", "duration"] | None = None
    distance_sort_order: Literal["asc", "desc"] | None = None


class GeocodeAddress(_GeocodeOptions):
    """Find coordinates for a free-form address or separate address components."""
    operation: Literal["geocode_address"] = "geocode_address"
    q: str | None = Field(None, min_length=1, title="Address")
    street: str | None = None
    street2: str | None = None
    city: str | None = None
    county: str | None = None
    state_province: str | None = None
    postal_code: str | None = None
    format: Literal["simple"] | None = Field(None, title="Output Format")

    @model_validator(mode="after")
    def address(self):
        if not any((self.q, self.street, self.city, self.county, self.state_province, self.postal_code)):
            raise ValueError("Provide an address or address components")
        return self


class _Batch(_GeocodeOptions):
    queries: list[str] | dict[str, str] = Field(..., min_length=1, max_length=10000,
        description="JSON array of queries or an object mapping your identifiers to queries. Batch lookups including appends must total at most 10,000.")

    @model_validator(mode="after")
    def batch_size(self):
        if len(self.queries) * (1 + len(self.fields or [])) > 10000:
            raise ValueError("Batch exceeds 10,000 lookups including appends; split it or upload a spreadsheet")
        values = self.queries.values() if isinstance(self.queries, dict) else self.queries
        if any(not v.strip() for v in values):
            raise ValueError("Every batch query must be nonempty")
        return self


class BatchGeocode(_Batch):
    """Geocode multiple addresses, preserving array order or custom identifiers."""
    operation: Literal["batch_geocode"] = "batch_geocode"


class ReverseGeocode(_GeocodeOptions):
    """Find addresses or data appends for a latitude,longitude pair."""
    operation: Literal["reverse_geocode"] = "reverse_geocode"
    q: str = Field(..., min_length=1, title="Coordinates", description="Latitude,longitude, for example 38.9002898,-76.9990361.")
    skip_geocoding: bool = Field(False, description="Apply fields directly to coordinates instead of reverse geocoding; requires data appends.")

    @model_validator(mode="after")
    def appends_required(self):
        if self.skip_geocoding and not self.fields:
            raise ValueError("Skipping geocoding requires data appends")
        return self


class BatchReverseGeocode(_Batch):
    """Reverse geocode a JSON array or keyed object of latitude,longitude strings."""
    operation: Literal["batch_reverse_geocode"] = "batch_reverse_geocode"
    skip_geocoding: bool = Field(False, description="Apply data appends without reverse geocoding.")

    @model_validator(mode="after")
    def appends_required(self):
        if self.skip_geocoding and not self.fields:
            raise ValueError("Skipping geocoding requires data appends")
        return self


class ParseAddress(_Input):
    """Parse a street address into its components."""
    operation: Literal["parse_address"] = "parse_address"
    q: str = Field(..., min_length=1, title="Address")


class _DistanceOptions(_Input):
    mode: Literal["driving", "haversine", "straightline"] | None = None
    units: Literal["miles", "km"] | None = None
    max_results: int | None = Field(None, ge=1)
    max_distance: float | None = Field(None, ge=0)
    min_distance: float | None = Field(None, ge=0)
    max_duration: int | None = Field(None, ge=0)
    min_duration: int | None = Field(None, ge=0)
    order_by: Literal["distance", "duration"] | None = None
    sort_order: Literal["asc", "desc"] | None = None
    country: str | None = None


class CalculateDistance(_DistanceOptions):
    """Measure distance from an origin to up to 100 destinations."""
    operation: Literal["calculate_distance"] = "calculate_distance"
    origin: str = Field(..., min_length=1, description="Address or latitude,longitude[,your ID].")
    destinations: list[str] = Field(..., min_length=1, max_length=100)


class CalculateDistanceMatrix(_DistanceOptions):
    """Calculate a many-to-many matrix or one-to-one pairs."""
    operation: Literal["calculate_distance_matrix"] = "calculate_distance_matrix"
    origins: list[str] = Field(..., min_length=1, max_length=10000)
    destinations: list[str] = Field(..., min_length=1, max_length=10000)
    calculation_type: Literal["matrix", "pairs"] = "matrix"

    @model_validator(mode="after")
    def size(self):
        if self.calculation_type == "pairs":
            if len(self.origins) != len(self.destinations) or len(self.origins) > 2500:
                raise ValueError("Pairs need equal lists with at most 2,500 entries")
            if any(getattr(self, k) is not None for k in ("max_results", "max_distance", "min_distance", "max_duration", "min_duration")):
                raise ValueError("Distance filters are unavailable for pairs")
        elif len(self.origins) * len(self.destinations) > 10000:
            raise ValueError("Matrix exceeds 10,000 calculations")
        return self


class ListSpreadsheets(_Input):
    """Read one page of your uploaded spreadsheets."""
    operation: Literal["list_spreadsheets"] = "list_spreadsheets"
    page: int = Field(1, ge=1, description="Explicit provider page number; pagination metadata is returned unchanged.")


class UploadSpreadsheet(_Appends):
    """Upload inline CSV data and start a spreadsheet geocoding job."""
    operation: Literal["upload_spreadsheet"] = "upload_spreadsheet"
    file: str = Field(..., min_length=1, title="CSV Contents", json_schema_extra={"ui:widget": "textarea"})
    filename: str = Field(..., min_length=1, title="Filename", description="CSV filename, for example addresses.csv.")
    direction: Literal["forward", "reverse"] = "forward"
    format: str = Field(..., min_length=1, title="Column Template", description="Geocodio column template, for example {{A}} {{B}} {{C}}. Use {{A}},{{B}} for coordinates.")
    callback: str | None = Field(None, description="Optional HTTPS webhook URL notified when the job completes.", json_schema_extra={"format": "uri"})

    @field_validator("filename")
    @classmethod
    def csv_filename(cls, value):
        if not value.lower().endswith('.csv') or any(c in value for c in ('/', chr(92), chr(13), chr(10))):
            raise ValueError("Use a CSV filename without a path")
        return value


class _Spreadsheet(_Input):
    list_id: str = Field(..., min_length=1, max_length=128, title="List ID", description="ID returned by Upload Spreadsheet or List Spreadsheets.")

    @field_validator("list_id")
    @classmethod
    def identifier(cls, value):
        if not value.isascii() or not all(c.isalnum() or c in '_-' for c in value):
            raise ValueError("Use a single spreadsheet ID")
        return value


class GetSpreadsheet(_Spreadsheet):
    """Read a spreadsheet's processing state and progress."""
    operation: Literal["get_spreadsheet"] = "get_spreadsheet"


class DownloadSpreadsheet(_Spreadsheet):
    """Download a completed spreadsheet as a file; processing jobs must finish first."""
    operation: Literal["download_spreadsheet"] = "download_spreadsheet"


class DeleteSpreadsheet(_Spreadsheet):
    """Delete an uploaded spreadsheet and its results."""
    operation: Literal["delete_spreadsheet"] = "delete_spreadsheet"


GeocodioConfig = Annotated[Union[
    GeocodeAddress, BatchGeocode, ReverseGeocode, BatchReverseGeocode, ParseAddress,
    CalculateDistance, CalculateDistanceMatrix, ListSpreadsheets, UploadSpreadsheet,
    GetSpreadsheet, DownloadSpreadsheet, DeleteSpreadsheet,
], Field(discriminator="operation")]


class GeocodioFullConfig(NodeConfig[GeocodioConfig, GeocodioAPIKeyCredential]):
    pass


# Exactly one API operation per node operation. No hidden polling, retries or writes.
ROUTES = {
    "geocode_address": ("GET", "/geocode"),
    "batch_geocode": ("POST", "/geocode"),
    "reverse_geocode": ("GET", "/reverse"),
    "batch_reverse_geocode": ("POST", "/reverse"),
    "parse_address": ("GET", "/parse"),
    "calculate_distance": ("GET", "/distance"),
    "calculate_distance_matrix": ("POST", "/distance-matrix"),
    "list_spreadsheets": ("GET", "/lists"),
    "upload_spreadsheet": ("POST", "/lists"),
    "get_spreadsheet": ("GET", "/lists/{id}"),
    "download_spreadsheet": ("GET", "/lists/{id}/download"),
    "delete_spreadsheet": ("DELETE", "/lists/{id}"),
}


class GeocodioNode(WorkflowNode):
    integration_type = "automation-geocodio"
    connection_evidence = ConnectionEvidence(operation="list_spreadsheets", noun="spreadsheets", label_keys=("name", "filename", "id"))

    @classmethod
    def get_config_model(cls):
        return GeocodioFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Geocodio API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        data = config.model_dump(exclude_none=True, exclude={"operation"})
        if "list_id" in data:
            path = path.replace("{id}", quote(data.pop("list_id"), safe=""))
        params = {"api_key": self.config.credentials.api_key}
        body = None
        if config.operation == "calculate_distance_matrix":
            body = data
        elif config.operation == "upload_spreadsheet":
            fields = data.pop("fields", None)
            if fields:
                params["fields"] = ",".join(fields)
            body = data
        else:
            if "queries" in data:
                body = data.pop("queries")
            if "fields" in data:
                data["fields"] = ",".join(data["fields"])
            if "destinations" in data:
                data["destinations[]"] = data.pop("destinations")
            if "skip_geocoding" in data:
                if data.pop("skip_geocoding"):
                    data["skipGeocoding"] = "1"
            params.update(data)
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=660.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Geocodio request failed; inspect the provider before retrying a spreadsheet upload or deletion") from None
        if not 200 <= response.status_code < 300:
            try:
                payload = response.json()
                message = payload.get("error", payload.get("message", "Request rejected")) if isinstance(payload, dict) else "Request rejected"
            except ValueError:
                message = "Request rejected"
            raise ValueError(f"Geocodio HTTP {response.status_code}: {str(message).replace(key, '[redacted]')}") from None
        if config.operation == "download_spreadsheet":
            mime = response.headers.get("content-type", "text/csv").split(";")[0]
            extension = {"application/json": "json", "application/vnd.ms-excel": "xls",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx"}.get(mime, "csv")
            output = {"status": "success", "file": BinaryOutput(response.content, mime, f"geocodio-{config.list_id}.{extension}")}
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Geocodio returned invalid JSON") from None
            if not isinstance(payload, (dict, list)):
                raise ValueError("Geocodio returned an unexpected response")
            if isinstance(payload, dict) and payload.get("error"):
                raise ValueError(str(payload["error"]).replace(key, "[redacted]"))
            # Keep provider result envelopes, pagination and custom batch identifiers intact.
            output = {"status": "success", "data": payload}
        await self.emit(output)
        return output
