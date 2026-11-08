"""Ideal Postcodes v1: fixed contract operations with pasted API credentials.

Contract: https://api.apis.guru/v2/specs/ideal-postcodes.co.uk/3.7.0/openapi.json
Management auth: https://docs.ideal-postcodes.co.uk/docs/api/key-details
Configuration writes: https://docs.ideal-postcodes.co.uk/docs/api/list-configs
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://api.ideal-postcodes.co.uk/v1"


class IdealpostcodesAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Ideal Postcodes API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://account.ideal-postcodes.co.uk/",
            "x-credential-instructions": "Paste your API key from the Ideal Postcodes dashboard. For private key details and configuration management, also paste your management key (formerly user token) from your account. Lookup operations can consume paid credits. Configuration updates replace the saved payload; deletion is permanent.",
        })
    credential_type: Literal["idealpostcodes_api_key"] = Field("idealpostcodes_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    user_token: str | None = Field(None, min_length=1, max_length=4096, title="Management key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "user_token", mode="before")
    @classmethod
    def secret(cls, value, info):
        if value is None and info.field_name == "user_token":
            return None
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() or c in '\"\\' for c in value):
            raise ValueError("Paste the key without quotes, whitespace or an authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @model_validator(mode="after")
    def safe_segments_and_dates(self):
        for name in ("address", "postcode", "udprn", "umprn", "config_name"):
            value = getattr(self, name, None)
            if value is not None and (value in {".", ".."} or any(ord(c) < 32 for c in value)):
                raise ValueError("Use a valid provider identifier")
        start, end = getattr(self, "start", None), getattr(self, "end", None)
        if start is not None and end is not None and not 0 <= end - start <= 90 * 86400000:
            raise ValueError("Usage interval must be ordered and at most 90 days")
        return self


class SearchAddresses(_Input):
    operation: Literal["search_addresses"] = Field("search_addresses", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(10, ge=1, le=100)
    page: int = Field(0, ge=0)


class AutocompleteAddresses(_Input):
    operation: Literal["autocomplete_addresses"] = Field("autocomplete_addresses", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(10, ge=1, le=100)
    context: str | None = None


class ResolveAddressGBR(_Input):
    operation: Literal["resolve_address_gbr"] = Field("resolve_address_gbr", json_schema_extra={"ui:hidden": True})
    address: str = Field(..., min_length=1, max_length=512)


class ResolveAddressUSA(_Input):
    operation: Literal["resolve_address_usa"] = Field("resolve_address_usa", json_schema_extra={"ui:hidden": True})
    address: str = Field(..., min_length=1, max_length=512)


class CleanseAddress(_Input):
    operation: Literal["cleanse_address"] = Field("cleanse_address", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=1000)


class ValidateEmail(_Input):
    operation: Literal["validate_email"] = Field("validate_email", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=320)


class ValidatePhone(_Input):
    operation: Literal["validate_phone"] = Field("validate_phone", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=100)


class LookupPostcode(_Input):
    operation: Literal["lookup_postcode"] = Field("lookup_postcode", json_schema_extra={"ui:hidden": True})
    postcode: str = Field(..., min_length=1, max_length=16)
    page: int = Field(0, ge=0)
    filter: str | None = None


class GetUDPRN(_Input):
    operation: Literal["get_udprn"] = Field("get_udprn", json_schema_extra={"ui:hidden": True})
    udprn: str = Field(..., min_length=1, max_length=32)
    filter: str | None = None


class GetUMPRN(_Input):
    operation: Literal["get_umprn"] = Field("get_umprn", json_schema_extra={"ui:hidden": True})
    umprn: str = Field(..., min_length=1, max_length=32)
    filter: str | None = None


class GetKeyAvailability(_Input):
    operation: Literal["get_key_availability"] = Field("get_key_availability", json_schema_extra={"ui:hidden": True})


class GetKeyDetails(_Input):
    operation: Literal["get_key_details"] = Field("get_key_details", json_schema_extra={"ui:hidden": True})


class GetKeyUsage(_Input):
    operation: Literal["get_key_usage"] = Field("get_key_usage", json_schema_extra={"ui:hidden": True})
    start: int | None = Field(None, ge=0, description="Unix timestamp in milliseconds; maximum interval 90 days.")
    end: int | None = Field(None, ge=0)
    tags: str | None = None


class ListConfigs(_Input):
    operation: Literal["list_configs"] = Field("list_configs", json_schema_extra={"ui:hidden": True})


class GetConfig(_Input):
    operation: Literal["get_config"] = Field("get_config", json_schema_extra={"ui:hidden": True})
    config_name: str = Field(..., min_length=1, max_length=32)


class CreateConfig(_Input):
    operation: Literal["create_config"] = Field("create_config", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=32)
    payload: str = Field(..., max_length=4096, description="Serialised configuration payload. Replaces the complete payload.")


class UpdateConfig(_Input):
    operation: Literal["update_config"] = Field("update_config", json_schema_extra={"ui:hidden": True})
    config_name: str = Field(..., min_length=1, max_length=32)
    payload: str = Field(..., max_length=4096, description="Serialised replacement payload.")


class DeleteConfig(_Input):
    operation: Literal["delete_config"] = Field("delete_config", json_schema_extra={"ui:hidden": True})
    config_name: str = Field(..., min_length=1, max_length=32)


IdealpostcodesConfig = Annotated[Union[SearchAddresses, AutocompleteAddresses, ResolveAddressGBR, ResolveAddressUSA, CleanseAddress, ValidateEmail, ValidatePhone, LookupPostcode, GetUDPRN, GetUMPRN, GetKeyAvailability, GetKeyDetails, GetKeyUsage, ListConfigs, GetConfig, CreateConfig, UpdateConfig, DeleteConfig], Field(discriminator="operation")]


class IdealpostcodesFullConfig(NodeConfig[IdealpostcodesConfig, IdealpostcodesAPIKeyCredential]):
    pass


ROUTES = {
    'search_addresses': ('GET', '/addresses'),
    'autocomplete_addresses': ('GET', '/autocomplete/addresses'),
    'resolve_address_gbr': ('GET', '/autocomplete/addresses/{address}/gbr'),
    'resolve_address_usa': ('GET', '/autocomplete/addresses/{address}/usa'),
    'cleanse_address': ('POST', '/cleanse/addresses'),
    'validate_email': ('GET', '/emails'),
    'validate_phone': ('GET', '/phone_numbers'),
    'lookup_postcode': ('GET', '/postcodes/{postcode}'),
    'get_udprn': ('GET', '/udprn/{udprn}'),
    'get_umprn': ('GET', '/umprn/{umprn}'),
    'get_key_availability': ('GET', '/keys/{key}'),
    'get_key_details': ('GET', '/keys/{key}/details'),
    'get_key_usage': ('GET', '/keys/{key}/usage'),
    'list_configs': ('GET', '/keys/{key}/configs'),
    'get_config': ('GET', '/keys/{key}/configs/{config}'),
    'create_config': ('POST', '/keys/{key}/configs'),
    'update_config': ('POST', '/keys/{key}/configs/{config}'),
    'delete_config': ('DELETE', '/keys/{key}/configs/{config}'),
}


def _redact(value, credential):
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items() if k not in {"api_key", "user_token"}}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, str):
        for secret in (credential.api_key, credential.user_token):
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class IdealpostcodesNode(WorkflowNode):
    integration_type = "automation-idealpostcodes"
    connection_evidence = ConnectionEvidence(noun="Ideal Postcodes key details", identity_operation="get_key_details")

    @classmethod
    def get_config_model(cls):
        return IdealpostcodesFullConfig

    async def execute(self, inputs):
        op = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Ideal Postcodes API key")
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        segments = {"key": credential.api_key}
        for field in ("address", "postcode", "udprn", "umprn"):
            if field in values:
                segments[field] = values.pop(field)
        if "config_name" in values:
            segments["config"] = values.pop("config_name")
        for name, value in segments.items():
            path = path.replace("{" + name + "}", quote(value, safe=""))
        body = values if method == "POST" else None
        params = {} if method == "POST" else values
        if not path.startswith("/keys/"):
            params["api_key"] = credential.api_key
        # v3.7.0 describes user_token as a query parameter. Send it only on
        # management routes, never with paid address, email or phone queries.
        if credential.user_token and (op.operation in {"get_key_details", "get_key_usage", "list_configs", "create_config", "update_config", "delete_config"}):
            params["user_token"] = credential.user_token
        output = {"operation": op.operation}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Accept": "application/json"}, **({"json": body} if body is not None else {}))
            output["http_status"] = response.status_code
            if len(response.content) > 5_000_000:
                raise ValueError("Ideal Postcodes response exceeds the size limit")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected an Ideal Postcodes response object")
            if response.status_code != 200 or data.get("code") != 2000:
                message = data.get("message")
                return {**output, "status": "error", "error": _redact(message, credential) if isinstance(message, str) else "Ideal Postcodes did not confirm the request"}
            if "result" not in data:
                raise ValueError("Ideal Postcodes response has no result")
            return {**output, "status": "success", "result": _redact(data["result"], credential),
                "code": data["code"], "message": _redact(data.get("message"), credential)}
        except (ValueError, httpx.HTTPError, SSRFError):
            return {**output, "status": "error", "error": "Ideal Postcodes request could not be confirmed; inspect configuration writes before retrying"}
