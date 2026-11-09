"""PostalDataPI's six published postal-code operations, pinned to OpenAPI 1.0.0.

The provider authenticates JSON bodies, despite its OpenAPI header placeholder.
All operations query data and consume the provider's per-record query credit.
"""
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://postaldatapi.com"
ROUTES = {
    "lookup_postal_code": "/api/lookup",
    "validate_postal_code": "/api/validate",
    "validate_bulk_postal_codes": "/api/validate-bulk",
    "search_by_city": "/api/city",
    "get_postal_code_metadata": "/api/metacode",
    "get_postal_code_metadata_legacy": "/api/metazip",
}


class PostalDataApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Postal Data Api API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-url": "https://postaldatapi.com/login",
        "x-credential-instructions": "Sign in to PostalDataPI, open API Keys, create a key and paste it here. Connecting performs one postal-code query and consumes one query credit; it verifies key acceptance, not account identity.",
    })
    credential_type: Literal["postal_data_api_key"] = Field("postal_data_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API Key")


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _PostalCode(_Input):
    zipcode: str = Field(..., min_length=1, description="Postal code as text, preserving leading zeros; for example 90210 or SW1A.")
    country: str = Field("US", pattern="^[A-Z]{2}$", description="ISO 3166-1 alpha-2 country code.")


class LookupPostalCode(_PostalCode):
    """Get the city, state and coordinates for a postal code."""
    operation: Literal["lookup_postal_code"] = "lookup_postal_code"


class ValidatePostalCode(_PostalCode):
    """Check whether a postal code exists; valid=false is a successful response."""
    operation: Literal["validate_postal_code"] = "validate_postal_code"


class GetPostalCodeMetadata(_PostalCode):
    """Get all country-specific metadata using the recommended metacode endpoint."""
    operation: Literal["get_postal_code_metadata"] = "get_postal_code_metadata"


class GetPostalCodeMetadataLegacy(_PostalCode):
    """Query the deprecated metazip alias; prefer Get Postal Code Metadata for new workflows."""
    operation: Literal["get_postal_code_metadata_legacy"] = "get_postal_code_metadata_legacy"


class PostalCodeRecord(_Input):
    postalCode: str = Field(..., min_length=1, title="Postal Code")
    countryCode: str = Field(..., min_length=2, max_length=2, title="Country Code")


class ValidateBulkPostalCodes(_Input):
    """Validate 1–1,000 records in input order, including mixed countries."""
    operation: Literal["validate_bulk_postal_codes"] = "validate_bulk_postal_codes"
    records: list[PostalCodeRecord] = Field(..., min_length=1, max_length=1000, description="Each record has postalCode and countryCode. Each record consumes one query credit.")


class SearchByCity(_Input):
    """Find postal codes by city; US queries require state or ST."""
    operation: Literal["search_by_city"] = "search_by_city"
    city: str = Field(..., min_length=1)
    country: str = Field("US", pattern="^[A-Z]{2}$")
    state: str | None = Field(None, min_length=1, description="Full state/region name. Required for US unless ST is supplied.")
    ST: str | None = Field(None, min_length=1, title="State Abbreviation", description="State abbreviation, for example CA.")

    @model_validator(mode="after")
    def us_state(self):
        if self.country == "US" and not (self.state or self.ST):
            raise ValueError("US city searches require state or ST")
        return self


PostalDataApiConfig = Annotated[Union[LookupPostalCode, ValidatePostalCode, ValidateBulkPostalCodes,
    SearchByCity, GetPostalCodeMetadata, GetPostalCodeMetadataLegacy], Field(discriminator="operation")]


class PostalDataApiFullConfig(NodeConfig[PostalDataApiConfig, PostalDataApiKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(key, "[redacted]"): _redact(v, key) for k, v in value.items() if k.lower() not in {"apikey", "api_key"}}
    return value


def _valid_response(operation, data):
    if operation == "lookup_postal_code":
        return isinstance(data.get("city"), str)
    if operation == "validate_postal_code":
        return type(data.get("valid")) is bool
    if operation == "validate_bulk_postal_codes":
        rows = data.get("results")
        return isinstance(rows, list) and all(isinstance(row, dict) and type(row.get("valid")) is bool for row in rows)
    if operation == "search_by_city":
        codes = data.get("zipcodes")
        return isinstance(codes, list) and all(isinstance(code, str) for code in codes)
    return isinstance(data.get("meta"), dict)


class PostalDataApiNode(WorkflowNode):
    integration_type = "automation-postal-data-api"
    connection_evidence = ConnectionEvidence(
        noun="postal-code query", operation="lookup_postal_code",
        operation_arguments={"zipcode": "90210", "country": "US"}, proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return PostalDataApiFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Postal Data Api API key")
        key = self.config.credentials.api_key
        op = self.config.config
        body = {**op.model_dump(exclude={"operation"}, exclude_none=True), "apiKey": key}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.post(BASE + ROUTES[op.operation], json=body)
        except httpx.HTTPError:
            # Queries consume credits; never retry automatically after a timeout.
            result = {"status": "error", "success": False, "message": "PostalDataPI query could not be confirmed; inspect usage before retrying"}
        else:
            try:
                data = response.json()
            except ValueError:
                data = None
            if not isinstance(data, dict):
                result = {"status": "error", "success": False, "http_status": response.status_code, "message": "PostalDataPI returned an unexpected response"}
            elif not response.is_success or data.get("error"):
                result = {"status": "error", "success": False, "http_status": response.status_code,
                          "message": data.get("error") or "PostalDataPI rejected the query", "data": data}
            elif not _valid_response(op.operation, data):
                result = {"status": "error", "success": False, "http_status": response.status_code, "message": "PostalDataPI returned an unexpected response"}
            else:
                result = {"status": "success", "success": True, "http_status": response.status_code, "data": data}
        result = _redact(result, key)
        await self.emit(result)
        return result
