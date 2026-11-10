"""GeoDataSource lookups using the provider's pasted API key.

Only the three published read endpoints are exposed. The provider has no
webhook registration or timestamp-filtered list API for workflow triggers.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.geodatasource.com"


class GeoDataSourceAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="GeoDataSource API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.geodatasource.com/web-service",
            "x-credential-instructions": "Paste your GeoDataSource API key from your account. Location Search and Neighboring Countries are separate services; the key needs access to the service you use. NoClick sends it only to api.geodatasource.com. Connecting performs one nearest-city lookup and uses a lookup credit; it verifies key reachability, not account identity.",
        },
    )
    credential_type: Literal["geodatasource_api_key"] = Field("geodatasource_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your GeoDataSource API key")
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or a header prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Coordinates(_Operation):
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False, description="Latitude in decimal degrees, for example 37.3861.")
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False, description="Longitude in decimal degrees, for example -122.084.")

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def not_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError("Use a latitude or longitude number")
        return value


class GetNearestCityConfig(_Coordinates):
    """Find the nearest city and its location, currency, time zone and distance."""
    operation: Literal["get_nearest_city"] = Field("get_nearest_city", title="Get Nearest City", json_schema_extra={"ui:hidden": True})


class ListNearbyCitiesConfig(_Coordinates):
    """Find cities within the provider's fixed 20 km search radius."""
    operation: Literal["list_nearby_cities"] = Field("list_nearby_cities", title="List Nearby Cities", json_schema_extra={"ui:hidden": True})


class ListNeighboringCountriesConfig(_Operation):
    """List countries sharing a land border with a two-letter country code."""
    operation: Literal["list_neighboring_countries"] = Field("list_neighboring_countries", title="List Neighboring Countries", json_schema_extra={"ui:hidden": True})
    country_code: str = Field(..., pattern=r"^[A-Z]{2}$", title="Country code", description="Two-letter ISO country code, for example US.")

    @field_validator("country_code", mode="before")
    @classmethod
    def country(cls, value):
        if isinstance(value, str):
            value = value.strip().upper()
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError("Use a two-letter country code such as US")
        return value


GeoDataSourceConfig = Annotated[Union[GetNearestCityConfig, ListNearbyCitiesConfig, ListNeighboringCountriesConfig], Field(discriminator="operation")]


class GeoDataSourceNodeConfig(NodeConfig[GeoDataSourceConfig, GeoDataSourceAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


def _check_payload(data, operation):
    if operation == "get_nearest_city":
        rows = [data]
    else:
        if not isinstance(data, list):
            raise ValueError("GeoDataSource returned an unexpected list response")
        rows = data
    fields = ("country_code", "country_name") if operation == "list_neighboring_countries" else ("country", "region", "city")
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(field), str) for field in fields):
            raise ValueError("GeoDataSource returned an unexpected location response")
    return data


class GeoDataSourceNode(WorkflowNode):
    integration_type = "automation-geodatasource"
    connection_evidence = ConnectionEvidence(
        noun="GeoDataSource location lookup", operation="get_nearest_city",
        operation_arguments={"latitude": 37.3861, "longitude": -122.084},
        label_keys=("city", "country"), proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return GeoDataSourceNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a GeoDataSource API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        params = {"key": secret, "format": "json"}
        if isinstance(op, ListNeighboringCountriesConfig):
            # The pinned SwaggerHub contract misspells this as neighbouring.
            # Official docs and all their code samples use neighboring-countries:
            # https://www.geodatasource.com/web-service/neighboring-countries
            path = "/neighboring-countries"
            params["country_code"] = op.country_code
        else:
            path = "/city" if isinstance(op, GetNearestCityConfig) else "/cities"
            params.update(lat=op.latitude, lng=op.longitude)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request("GET", BASE_URL + path, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("GeoDataSource lookup could not be completed") from None
        # Never expose an HTTP exception's URL: the API key is a query parameter.
        try:
            data = response.json()
        except ValueError:
            raise ValueError("GeoDataSource returned an unreadable JSON response") from None
        if isinstance(data, dict) and "error" in data:
            error = data["error"]
            if not isinstance(error, dict) or not isinstance(error.get("error_message"), str):
                raise ValueError("GeoDataSource returned an unexpected error response")
            output = {"status": "error", "success": False, "error": error["error_message"], "error_code": error.get("error_code"), "http_status": response.status_code}
        elif response.status_code != 200:
            output = {"status": "error", "success": False, "error": "GeoDataSource rejected the lookup", "http_status": response.status_code}
        else:
            output = {"status": "success", "success": True, "data": _check_payload(data, op.operation)}
        output = _redact(output, secret)
        await self.emit(output)
        return output
