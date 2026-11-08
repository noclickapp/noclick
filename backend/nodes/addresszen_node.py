"""Addresszen v1 lookups and key management, pinned to OpenAPI 4.2.0.

Each operation makes one documented request. Lists return one provider page;
mutations are never automatically retried.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.addresszen.com/v1"


class AddresszenAPIKeysCredential(BaseModel):
    model_config = ConfigDict(title="Addresszen API Keys", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://addresszen.com/account",
            "x-credential-instructions": "Paste your API key and management key from your Addresszen account, without a Bearer prefix. The API key authorizes address, place, email and phone lookups. The management key authorizes key details, usage, licensees and configuration changes. Connecting reads the selected key's details.",
        })
    credential_type: Literal["addresszen_api_keys"] = Field("addresszen_api_keys", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})
    management_key: str = Field(..., title="Management key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "management_key", mode="before")
    @classmethod
    def secret(cls, value, info):
        if not isinstance(value, str):
            raise ValueError("Paste the key as text")
        value = clean_secret(value, field_name=info.field_name.replace("_", " "), key=True)
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetKeyDetails(_Input):
    operation: Literal["get_key_details"] = "get_key_details"


class _Limit(_Input):
    limit: int | None = Field(..., ge=0, description="Set null to disable the limit.")


class UpdateKeyDetails(_Input):
    """Update only supplied settings on the API key."""
    operation: Literal["update_key_details"] = "update_key_details"
    name: str | None = Field(None, max_length=32, pattern=r"^(\w|\s){0,32}$")
    daily_limit: _Limit | None = None
    monthly_limit: _Limit | None = None
    individual_limit: _Limit | None = None
    allowed_urls: list[Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\s]+$")]] | None = Field(None, max_length=10)
    redact_days: int | None = Field(None, ge=0, le=1095)

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True, exclude={"operation"}):
            raise ValueError("Supply at least one key setting to update")
        return self


class GetKeyUsage(_Input):
    operation: Literal["get_key_usage"] = "get_key_usage"
    start: int | None = Field(None, ge=0, description="Inclusive Unix timestamp in milliseconds.")
    end: int | None = Field(None, ge=0, description="Exclusive Unix timestamp in milliseconds.")
    tags: str | None = Field(None, max_length=1000)
    licensee: str | None = Field(None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def interval(self):
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("End must be after start")
        return self


class VerifyAddress(_Input):
    operation: Literal["verify_address"] = "verify_address"
    query: str = Field(..., min_length=1, max_length=2000)
    zip_code: str | None = Field(None, max_length=32)
    city: str | None = Field(None, max_length=256)
    state: str | None = Field(None, max_length=256)
    context: str | None = Field(None, max_length=16, description="Country context, for example usa.")
    tags: str | None = Field(None, max_length=1000)


class FindAddress(_Input):
    operation: Literal["find_address"] = "find_address"
    query: str = Field(..., min_length=1, max_length=150)
    context: str | None = Field(None, max_length=16)
    limit: int = Field(10, ge=1, le=100)
    postal_code: str | None = Field(None, max_length=32)
    city: str | None = Field(None, max_length=256)
    state: str | None = Field(None, max_length=256)
    state_code: str | None = Field(None, max_length=32)
    bias_lonlat: str | None = Field(None, max_length=100)
    is_pobox: Literal["true", "false"] | None = None
    is_business: Literal["true", "false"] | None = None


class RetrieveAddress(_Input):
    operation: Literal["retrieve_address"] = "retrieve_address"
    address: str = Field(..., min_length=1, max_length=1000, description="Opaque address ID returned by Find Address; US retrieval endpoint.")
    filter: str | None = Field(None, max_length=1000, description="Comma separated response fields.")
    tags: str | None = Field(None, max_length=1000)


class FindPlace(_Input):
    operation: Literal["find_place"] = "find_place"
    query: str = Field(..., min_length=1, max_length=1000)
    country_iso: str | None = Field(None, max_length=16)
    bias_country_iso: str | None = Field(None, max_length=16)
    bias_lonlat: str | None = Field(None, max_length=100)


class ResolvePlace(_Input):
    operation: Literal["resolve_place"] = "resolve_place"
    place: str = Field(..., min_length=1, max_length=1000, description="Opaque place ID returned by Find Place.")
    tags: str | None = Field(None, max_length=1000)


class ListLicensees(_Input):
    """Return one page, preserving hasMore and licensee IDs for continuation."""
    operation: Literal["list_licensees"] = "list_licensees"
    starting_after: int | None = Field(None, ge=0, description="Pagination cursor as specified by OpenAPI 4.2.0.")
    limit: int = Field(10, ge=1, le=100)
    query: str | None = Field(None, max_length=1000)


class _LicenseeID(_Input):
    licensee: str = Field(..., min_length=1, max_length=256, description="Licensee key (sl_...), not its immutable ID.")


class GetLicensee(_LicenseeID):
    operation: Literal["get_licensee"] = "get_licensee"


class DeleteLicensee(_LicenseeID):
    """Cancel the selected licensee's access to this API key."""
    operation: Literal["delete_licensee"] = "delete_licensee"


class _LicenseeBody(_Input):
    name: str | None = Field(None, min_length=1, max_length=1000)
    address: str | None = Field(None, max_length=2000)
    postcode: str | None = Field(None, max_length=64)
    whitelist: list[Annotated[str, Field(min_length=1, max_length=256)]] | None = Field(None, max_length=100)
    daily: _Limit | None = None

    @model_validator(mode="after")
    def changes(self):
        values = self.model_dump(exclude_none=True, exclude={"operation", "licensee"})
        if not values:
            raise ValueError("Supply at least one licensee field")
        return self


class CreateLicensee(_LicenseeBody):
    operation: Literal["create_licensee"] = "create_licensee"
    name: str = Field(..., min_length=1, max_length=1000)


class UpdateLicensee(_LicenseeBody, _LicenseeID):
    operation: Literal["update_licensee"] = "update_licensee"


class ListConfigs(_Input):
    operation: Literal["list_configs"] = "list_configs"


class _ConfigID(_Input):
    config_name: str = Field(..., min_length=1, max_length=32, description="Name of the stored configuration.")


class GetConfig(_ConfigID):
    operation: Literal["get_config"] = "get_config"


class DeleteConfig(_ConfigID):
    operation: Literal["delete_config"] = "delete_config"


class CreateConfig(_Input):
    operation: Literal["create_config"] = "create_config"
    name: str = Field(..., min_length=1, max_length=32)
    payload: str = Field(..., min_length=1, max_length=65536, description="Serialized configuration, for example a JSON string. Sent as a string, not a nested object.")


class UpdateConfig(_ConfigID):
    operation: Literal["update_config"] = "update_config"
    payload: str = Field(..., min_length=1, max_length=65536, description="Serialized replacement configuration.")


class ValidateEmail(_Input):
    operation: Literal["validate_email"] = "validate_email"
    query: str = Field(..., min_length=3, max_length=254, description="Email address to validate.")
    tags: str | None = Field(None, max_length=1000)


class ValidatePhoneNumber(_Input):
    operation: Literal["validate_phone_number"] = "validate_phone_number"
    query: str = Field(..., min_length=1, max_length=64, description="Phone number including its country code.")
    current_carrier: Literal["true"] | None = None
    tags: str | None = Field(None, max_length=1000)


AddresszenConfig = Annotated[Union[
    GetKeyDetails, UpdateKeyDetails, GetKeyUsage, VerifyAddress, FindAddress,
    RetrieveAddress, FindPlace, ResolvePlace, ListLicensees, CreateLicensee,
    GetLicensee, UpdateLicensee, DeleteLicensee, ListConfigs, CreateConfig,
    GetConfig, UpdateConfig, DeleteConfig, ValidateEmail, ValidatePhoneNumber,
], Field(discriminator="operation")]


class AddresszenFullConfig(NodeConfig[AddresszenConfig, AddresszenAPIKeysCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Exactly one published operation per node action. Management credentials stay
# in the Authorization header; the selected API key identifies its own resource.
ROUTES = {
    "get_key_details": ("GET", "/keys/{key}/details"),
    "update_key_details": ("PUT", "/keys/{key}/details"),
    "get_key_usage": ("GET", "/keys/{key}/usage"),
    "verify_address": ("POST", "/verify/addresses"),
    "find_address": ("GET", "/autocomplete/addresses"),
    "retrieve_address": ("GET", "/autocomplete/addresses/{address}/usa"),
    "find_place": ("GET", "/places"),
    "resolve_place": ("GET", "/places/{place}"),
    "list_licensees": ("GET", "/keys/{key}/licensees"),
    "create_licensee": ("POST", "/keys/{key}/licensees"),
    "get_licensee": ("GET", "/keys/{key}/licensees/{licensee}"),
    "update_licensee": ("POST", "/keys/{key}/licensees/{licensee}"),
    "delete_licensee": ("DELETE", "/keys/{key}/licensees/{licensee}"),
    "list_configs": ("GET", "/keys/{key}/configs"),
    "create_config": ("POST", "/keys/{key}/configs"),
    "get_config": ("GET", "/keys/{key}/configs/{config_name}"),
    "update_config": ("POST", "/keys/{key}/configs/{config_name}"),
    "delete_config": ("DELETE", "/keys/{key}/configs/{config_name}"),
    "validate_email": ("GET", "/emails"),
    "validate_phone_number": ("GET", "/phone_numbers"),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


def _segment(value):
    if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use an Addresszen resource identifier")
    return quote(value, safe="")


class AddresszenNode(WorkflowNode):
    integration_type = "automation-addresszen"
    connection_evidence = ConnectionEvidence(noun="Addresszen API key", identity_operation="get_key_details")

    @classmethod
    def get_config_model(cls):
        return AddresszenFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, AddresszenFullConfig) or not self.config.credentials:
            raise ValueError("Attach your Addresszen API and management keys")
        config, credential = self.config.config, self.config.credentials
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        # Preserve explicit null limits: null disables a provider rate limit.
        for field in ("daily_limit", "monthly_limit", "individual_limit", "daily"):
            setting = getattr(config, field, None)
            if setting is not None:
                values[field] = setting.model_dump()
        method, template = ROUTES[config.operation]
        management = template.startswith("/keys/")
        path_values = {"key": credential.api_key}
        for field in re.findall(r"\{(\w+)\}", template):
            if field != "key":
                path_values[field] = values.pop(field)
        path = template.format(**{field: _segment(value) for field, value in path_values.items()})
        params, body = {}, None
        if method == "GET":
            params = values
        elif method in {"POST", "PUT"}:
            body = values
        if config.operation == "verify_address":
            params = {key: body.pop(key) for key in ("tags", "context") if key in body}
        token = credential.management_key if management else credential.api_key
        secrets = (credential.management_key, credential.api_key,
            quote(credential.management_key, safe=""), quote(credential.api_key, safe=""))
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            # Transport exceptions include the URL, which contains the API key
            # for management reads. A failed mutation may already have applied.
            raise ValueError("Addresszen request could not be completed; inspect provider state before retrying a write") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Addresszen response exceeds the size limit")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from Addresszen")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Addresszen returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("Addresszen returned an unexpected response envelope")
        if response.status_code != 200 or payload.get("code") != 2000:
            message = payload.get("message") or "Addresszen did not confirm the request"
            return _redact({"status": "error", "http_status": response.status_code,
                "code": payload.get("code"), "error": message}, secrets)
        if "result" not in payload:
            raise ValueError("Addresszen did not return an operation result")
        return _redact({"status": "success", "operation": config.operation,
            "http_status": response.status_code, "code": payload["code"],
            "data": payload["result"]}, secrets)
