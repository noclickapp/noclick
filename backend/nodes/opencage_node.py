"""OpenCage v1 read workflows; one documented GET per operation.

Pinned contract: https://opencagedata.com/openapi.yaml, version 1.1.0.
There are no writes or account identity endpoint. Evidence consumes one query
and proves key acceptance only. Boolean flags follow official docs (1/0).
"""
from __future__ import annotations
import re
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.opencagedata.com/geocode/v1"


class OpenCageAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="OpenCage API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://opencagedata.com/dashboard#geocoding",
            "x-credential-instructions": "Paste your geocoding API key from the Geocoding tab of your OpenCage dashboard. Connection testing uses one geocoding request and proves key acceptance, not account identity. Geosearch keys are separate and cannot be used here."})
    credential_type: Literal["opencage_api_key"] = Field("opencage_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=512, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without spaces or a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Options(_Input):
    language: str | None = Field(None, max_length=100, description="IETF language tag, such as de or pt-BR, or native.")
    limit: int = Field(10, ge=1, le=100, description="Maximum results; OpenCage may return fewer. There is no pagination.")
    abbrv: StrictBool = Field(False, description="Abbreviate the formatted address.")
    no_annotations: StrictBool = Field(False, description="Omit location annotations.")
    no_dedupe: StrictBool = Field(False, description="Keep duplicate results.")
    no_record: StrictBool = Field(False, description="Ask OpenCage not to log the query.")


class _Forward(_Options):
    q: str = Field(..., min_length=2, description="Address, place name or LOCODE: prefixed UN/LOCODE.")
    bounds: str | None = Field(None, description="min longitude,min latitude,max longitude,max latitude.")
    countrycode: str | None = Field(None, pattern=r"^[a-z]{2}(,[a-z]{2})*$", description="Lowercase ISO alpha-2 codes, comma separated.")
    proximity: str | None = Field(None, description="Latitude,longitude used to bias results, not restrict them.")

    @field_validator("q")
    @classmethod
    def nonblank_query(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Provide an address or place with at least two characters")
        return value

    @field_validator("bounds")
    @classmethod
    def validate_bounds(cls, value):
        if value is None:
            return value
        try:
            west, south, east, north = map(float, value.split(","))
            if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
                raise ValueError()
        except ValueError:
            raise ValueError("Use west,south,east,north coordinates within geographic ranges") from None
        return value

    @field_validator("proximity")
    @classmethod
    def validate_proximity(cls, value):
        if value is None:
            return value
        if not re.fullmatch(r"-?[0-9]{1,2}(\.[0-9]+)?,\s*-?[0-9]{1,3}(\.[0-9]+)?", value):
            raise ValueError("Use decimal latitude,longitude")
        lat, lng = map(float, value.split(","))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("Proximity coordinates are out of range")
        return value


class _Reverse(_Options):
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    address_only: StrictBool = Field(False, description="Exclude point-of-interest names from formatted addresses.")
    roadinfo: StrictBool = Field(False, description="Find the nearest road and include available road annotations.")


class Geocode(_Forward):
    """Geocode an address or place to coordinates and annotations (GET /json)."""
    operation: Literal["geocode"] = "geocode"


class ReverseGeocode(_Reverse):
    """Convert coordinates to an address and annotations (GET /json)."""
    operation: Literal["reverse_geocode"] = "reverse_geocode"


class GeocodeInBounds(_Forward):
    """Restrict a forward search to a bounding box (GET /json)."""
    operation: Literal["geocode_in_bounds"] = "geocode_in_bounds"
    bounds: str = Field(..., description="min longitude,min latitude,max longitude,max latitude.")


class GeocodeInCountry(_Forward):
    """Restrict a forward search to countries (GET /json)."""
    operation: Literal["geocode_in_country"] = "geocode_in_country"
    countrycode: str = Field(..., pattern=r"^[a-z]{2}(,[a-z]{2})*$")


class GeocodeNear(_Forward):
    """Bias a forward search toward coordinates (GET /json)."""
    operation: Literal["geocode_near"] = "geocode_near"
    proximity: str = Field(..., description="Latitude,longitude; biases without restricting results.")


class ReverseAddress(_Reverse):
    """Get address-only formatting without point-of-interest names (GET /json)."""
    operation: Literal["reverse_address"] = "reverse_address"
    address_only: Literal[True] = True


class ReverseRoad(_Reverse):
    """Find the nearest road and available road information (GET /json)."""
    operation: Literal["reverse_road"] = "reverse_road"
    roadinfo: Literal[True] = True


class GeocodeGeoJSON(_Forward):
    """Geocode a place into a GeoJSON FeatureCollection (GET /geojson)."""
    operation: Literal["geocode_geojson"] = "geocode_geojson"


class ReverseGeoJSON(_Reverse):
    """Reverse geocode coordinates into GeoJSON (GET /geojson)."""
    operation: Literal["reverse_geojson"] = "reverse_geojson"


class CheckConnection(_Input):
    """Check API-key acceptance with one geocoding query (GET /json)."""
    operation: Literal["check_connection"] = "check_connection"


class GetHealth(_Input):
    """Read unauthenticated health; does not validate the key (GET /ping)."""
    operation: Literal["get_health"] = "get_health"


OpenCageConfig = Annotated[Union[Geocode, ReverseGeocode, GeocodeInBounds,
    GeocodeInCountry, GeocodeNear, ReverseAddress, ReverseRoad, GeocodeGeoJSON,
    ReverseGeoJSON, CheckConnection, GetHealth], Field(discriminator="operation")]


class OpenCageFullConfig(NodeConfig[OpenCageConfig, OpenCageAPIKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items() if k not in {"key", "api_key", "request"}}
    return value


class OpenCageNode(WorkflowNode):
    integration_type = "automation-opencage"
    connection_evidence = ConnectionEvidence(noun="OpenCage geocoding", operation="check_connection", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return OpenCageFullConfig

    async def execute(self, inputs):
        cfg = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect an OpenCage API key")
        key = credential.api_key
        operation = cfg.operation
        path = "/geojson" if isinstance(cfg, (GeocodeGeoJSON, ReverseGeoJSON)) else "/json"
        params = {}
        if isinstance(cfg, GetHealth):
            path = "/ping"
        else:
            params["key"] = key
            if isinstance(cfg, CheckConnection):
                params.update(q="Berlin, Germany", limit=1, no_annotations="1")
            else:
                params.update(cfg.model_dump(exclude_none=True, exclude={"operation", "latitude", "longitude"}))
                if isinstance(cfg, _Reverse):
                    params["q"] = f"{cfg.latitude},{cfg.longitude}"
                params = {k: ("1" if v else "0") if isinstance(v, bool) else v for k, v in params.items()}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get(BASE_URL + path, params=params)
            if response.status_code != 200:
                message = "OpenCage request failed"
                try:
                    status = response.json().get("status", {})
                    if isinstance(status, dict) and isinstance(status.get("message"), str):
                        message = status["message"]
                except (ValueError, AttributeError):
                    pass
                return {"status": "error", "http_status": response.status_code, "error": _redact(message, key)}
            if isinstance(cfg, GetHealth):
                if response.text.strip() != "pong":
                    raise ValueError("Unexpected OpenCage health response")
                return {"status": "success", "data": "pong", "key_verified": False}
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("status"), dict):
                raise ValueError("Unexpected OpenCage response envelope")
            status = body["status"]
            if status.get("code") != 200:
                return {"status": "error", "http_status": 200, "error": _redact(str(status.get("message", "OpenCage refused the query")), key)}
            rows = body.get("features" if path == "/geojson" else "results")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Unexpected OpenCage results")
            if path == "/geojson" and body.get("type") != "FeatureCollection":
                raise ValueError("Unexpected OpenCage GeoJSON type")
            return {"status": "success", "operation": operation, "data": _redact(body, key)}
        except httpx.RequestError:
            return {"status": "error", "error": "OpenCage request could not be completed"}
