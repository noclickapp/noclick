"""RentCast v1 property data, valuations, listings and market statistics.

Contract: https://developers.rentcast.io/openapi/rentcast-api.json (1.0).
All ten published operations are reads; each execution makes one request.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.rentcast.io/v1"
PROPERTY_TYPES = Literal["Single Family", "Condo", "Townhouse", "Manufactured", "Multi-Family", "Apartment", "Land"]
RENTAL_TYPES = Literal["Single Family", "Condo", "Townhouse", "Manufactured", "Multi-Family", "Apartment"]
ROUTES = {
    "search_properties": "/properties",
    "list_random_properties": "/properties/random",
    "get_property": "/properties/{id}",
    "get_value_estimate": "/avm/value",
    "get_rent_estimate": "/avm/rent/long-term",
    "search_sale_listings": "/listings/sale",
    "get_sale_listing": "/listings/sale/{id}",
    "search_rental_listings": "/listings/rental/long-term",
    "get_rental_listing": "/listings/rental/long-term/{id}",
    "get_market_statistics": "/markets",
}
WIRE_NAMES = {
    "zip_code": "zipCode", "property_type": "propertyType", "square_footage": "squareFootage",
    "lot_size": "lotSize", "year_built": "yearBuilt", "sale_date_range": "saleDateRange",
    "include_total_count": "includeTotalCount", "days_old": "daysOld", "max_radius": "maxRadius",
    "comp_count": "compCount", "lookup_subject_attributes": "lookupSubjectAttributes",
    "data_type": "dataType", "history_range": "historyRange",
}


class RentCastAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Rentcast API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.rentcast.io/app/api",
        "x-credential-instructions": "Paste an API key from the RentCast API dashboard. Requests use X-Api-Key. Connecting reads one random property and counts toward your API usage; it proves key acceptance, not account ownership.",
    })
    credential_type: Literal["rentcast_api_key"] = Field("rentcast_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API Key", key=True)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Location(_Config):
    address: str | None = Field(None, title="Address", min_length=1, max_length=1000)
    latitude: float | None = Field(None, title="Latitude", ge=-90, le=90)
    longitude: float | None = Field(None, title="Longitude", ge=-180, le=180)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Supply both latitude and longitude")
        return self


class _Search(_Location):
    city: str | None = Field(None, title="City", min_length=1, max_length=200, description="Case-sensitive city name; combine with a state.")
    state: str | None = Field(None, title="State", pattern=r"^[A-Z]{2}$")
    zip_code: str | None = Field(None, title="ZIP Code", pattern=r"^\d{5}$")
    radius: float | None = Field(None, title="Radius (Miles)", gt=0, le=100)
    bedrooms: str | None = Field(None, title="Bedrooms Filter", max_length=200, description="A number, range or comma-separated values, for example 2:4.")
    bathrooms: str | None = Field(None, title="Bathrooms Filter", max_length=200)
    square_footage: str | None = Field(None, title="Living Area Filter", max_length=200)
    lot_size: str | None = Field(None, title="Lot Size Filter", max_length=200)
    year_built: str | None = Field(None, title="Year Built Filter", max_length=200)
    limit: int = Field(50, title="Page Size", ge=1, le=500)
    offset: int = Field(0, title="Offset", ge=0, description="Index of the first result. Keep the same filters when requesting another page.")
    include_total_count: bool = Field(False, title="Include Total Count")

    @model_validator(mode="after")
    def search_area(self):
        if self.city and not self.state:
            raise ValueError("A city search also needs its state")
        if self.latitude is not None and self.radius is None:
            raise ValueError("A coordinate search also needs a radius")
        if self.radius is not None and not (self.address or self.latitude is not None):
            raise ValueError("A radius needs an address or coordinate pair")
        if not (self.address or self.state or self.zip_code or self.latitude is not None):
            raise ValueError("Supply an address, state, ZIP code or coordinates with radius")
        return self


class SearchProperties(_Search):
    operation: Literal["search_properties"] = Field("search_properties", title="Search Property Records", json_schema_extra={"ui:hidden": True})
    property_type: PROPERTY_TYPES | None = Field(None, title="Property Type")
    sale_date_range: str | None = Field(None, title="Days Since Sale Filter", max_length=200)


class ListRandomProperties(_Config):
    operation: Literal["list_random_properties"] = Field("list_random_properties", title="List Random Property Records", json_schema_extra={"ui:hidden": True})
    limit: int = Field(1, title="Number of Records", ge=1, le=500)


class _Record(_Config):
    property_id: str = Field(..., title="Property or Listing ID", min_length=1, max_length=1000,
                             description="Copy the exact id returned by RentCast, including hyphens and commas.")

    @field_validator("property_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or c in "/\\?#" for c in value):
            raise ValueError("Use a single RentCast record ID")
        return value


class GetProperty(_Record):
    operation: Literal["get_property"] = Field("get_property", title="Get Property Record", json_schema_extra={"ui:hidden": True})


class _Estimate(_Location):
    bedrooms: float | None = Field(None, title="Bedrooms", ge=0)
    bathrooms: float | None = Field(None, title="Bathrooms", ge=0)
    square_footage: float | None = Field(None, title="Living Area (Square Feet)", gt=0)
    max_radius: float | None = Field(None, title="Maximum Comparable Radius (Miles)", gt=0)
    days_old: int | None = Field(None, title="Maximum Comparable Age (Days)", ge=1)
    comp_count: int = Field(15, title="Comparable Count", ge=5, le=25)
    lookup_subject_attributes: bool = Field(True, title="Look Up Subject Attributes")

    @model_validator(mode="after")
    def subject(self):
        if not self.address and self.latitude is None:
            raise ValueError("Supply the subject address or latitude and longitude")
        return self


class GetValueEstimate(_Estimate):
    operation: Literal["get_value_estimate"] = Field("get_value_estimate", title="Get Property Value Estimate", json_schema_extra={"ui:hidden": True})
    property_type: PROPERTY_TYPES | None = Field(None, title="Property Type")


class GetRentEstimate(_Estimate):
    operation: Literal["get_rent_estimate"] = Field("get_rent_estimate", title="Get Long-Term Rent Estimate", json_schema_extra={"ui:hidden": True})
    property_type: RENTAL_TYPES | None = Field(None, title="Property Type")


class _Listings(_Search):
    status: Literal["Active", "Inactive"] | None = Field(None, title="Listing Status", description="RentCast defaults to Active when omitted.")
    price: str | None = Field(None, title="Price Filter", max_length=200)
    days_old: str | None = Field(None, title="Days on Market Filter", max_length=200)


class SearchSaleListings(_Listings):
    operation: Literal["search_sale_listings"] = Field("search_sale_listings", title="Search Sale Listings", json_schema_extra={"ui:hidden": True})
    property_type: PROPERTY_TYPES | None = Field(None, title="Property Type")


class GetSaleListing(_Record):
    operation: Literal["get_sale_listing"] = Field("get_sale_listing", title="Get Sale Listing", json_schema_extra={"ui:hidden": True})


class SearchRentalListings(_Listings):
    operation: Literal["search_rental_listings"] = Field("search_rental_listings", title="Search Long-Term Rental Listings", json_schema_extra={"ui:hidden": True})
    property_type: RENTAL_TYPES | None = Field(None, title="Property Type")


class GetRentalListing(_Record):
    operation: Literal["get_rental_listing"] = Field("get_rental_listing", title="Get Long-Term Rental Listing", json_schema_extra={"ui:hidden": True})


class GetMarketStatistics(_Config):
    operation: Literal["get_market_statistics"] = Field("get_market_statistics", title="Get ZIP Code Market Statistics", json_schema_extra={"ui:hidden": True})
    zip_code: str = Field(..., title="ZIP Code", pattern=r"^\d{5}$")
    data_type: Literal["All", "Sale", "Rental"] = Field("All", title="Market Data Type")
    history_range: int = Field(12, title="History (Months)", ge=1, description="Number of historical months to include.")


RentCastConfig = Annotated[Union[SearchProperties, ListRandomProperties, GetProperty, GetValueEstimate,
    GetRentEstimate, SearchSaleListings, GetSaleListing, SearchRentalListings, GetRentalListing,
    GetMarketStatistics], Field(discriminator="operation")]


class RentCastFullConfig(NodeConfig[RentCastConfig, RentCastAPIKeyCredential]):
    pass


class RentCastNode(WorkflowNode):
    integration_type = "automation-rentcast"
    credential_provider_labels = {"rentcast": "RentCast"}
    connection_evidence = ConnectionEvidence(
        noun="RentCast property records", operation="list_random_properties", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return RentCastFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a RentCast API key")
        config = self.config.config
        path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if isinstance(config, _Record):
            path = path.replace("{id}", quote(values.pop("property_id"), safe=""))
        params = {WIRE_NAMES.get(k, k): (str(v).lower() if isinstance(v, bool) else v)
                  for k, v in values.items()}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.get(BASE_URL + path, params=params,
                headers={"X-Api-Key": self.config.credentials.api_key, "Accept": "application/json"})
        if response.status_code != 200:
            message = f"RentCast returned HTTP {response.status_code}"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message += ": " + error["message"].replace(self.config.credentials.api_key, "[redacted]")[:1000]
            except ValueError:
                pass
            raise ValueError(message)
        body = response.json()
        result = {"status": "success", "operation": config.operation}
        if isinstance(config, (_Search, ListRandomProperties)):
            if not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
                raise ValueError("Expected a RentCast record array")
            result.update(items=body, count=len(body))
            if isinstance(config, _Search):
                result.update(offset=config.offset,
                    next_offset=config.offset + len(body) if len(body) == config.limit else None)
                if config.include_total_count:
                    count = response.headers.get("X-Total-Count")
                    if count is not None:
                        result["total_count"] = int(count)
        else:
            if not isinstance(body, dict) or "error" in body:
                raise ValueError("Expected a RentCast record object")
            if isinstance(config, _Record) and body.get("id") != config.property_id:
                raise ValueError("RentCast returned a different record ID")
            result["data"] = body
        return result
