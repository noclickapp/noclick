"""Numverify's two published read endpoints, using a pasted access key.

Contract: https://api.swaggerhub.com/apis/apilayer-863/numverify-api/1.0.0/swagger.json
Docs: https://docs.apilayer.com/numverify/docs/api-documentation
No mutation, webhook registration, or time-filtered listing is documented.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://apilayer.net/api"
CREDENTIAL_TYPE = "numverify_api_key"


class NumverifyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="numverify API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://numverify.com/dashboard",
            "x-credential-instructions": "Paste your numverify API access key from the dashboard. NoClick sends it to apilayer.net over HTTPS. Your plan must support HTTPS. The connection check reads supported countries and proves key reachability, not account identity.",
        })
    credential_type: Literal["numverify_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API access key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password", "ui:help": "Copy the access key only, without access_key= or a URL."})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API access key")
        if any(c.isspace() for c in value) or any(c in value for c in "?&=\r\n"):
            raise ValueError("Paste only the API access key")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ValidatePhoneNumber(_Operation):
    """Validate a phone number and look up its country, carrier and line type."""
    operation: Literal["validate_phone_number"] = Field("validate_phone_number", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., min_length=1, max_length=64, title="Phone number",
        description="International number such as 14158586273, or a national number with Country code. Separators may be included.")
    country_code: str | None = Field(None, min_length=2, max_length=2, title="Country code",
        description="Two-letter country code for national numbers, for example US. Omit for international numbers.")

    @field_validator("number", mode="before")
    @classmethod
    def phone(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9() .-]+", value.strip()) or not any(c.isdigit() for c in value):
            raise ValueError("Enter a phone number containing digits and optional separators")
        return value.strip()

    @field_validator("country_code", mode="before")
    @classmethod
    def country(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{2}", value.strip()):
            raise ValueError("Use a two-letter country code")
        return value.strip().upper()

    @model_validator(mode="after")
    def international_country(self):
        if self.number.startswith("+") and self.country_code:
            raise ValueError("Omit Country code for an international number")
        return self


class ListSupportedCountries(_Operation):
    """List supported countries and their international dialling codes."""
    operation: Literal["list_supported_countries"] = Field("list_supported_countries", json_schema_extra={"ui:hidden": True})


NumverifyConfig = Annotated[Union[ValidatePhoneNumber, ListSupportedCountries], Field(discriminator="operation")]


class NumverifyFullConfig(NodeConfig[NumverifyConfig, NumverifyAPIKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _redact(item, key) for name, item in value.items() if name != "access_key"}
    return value


class NumverifyNode(WorkflowNode):
    integration_type = "automation-numverify"
    connection_evidence = ConnectionEvidence(noun="numverify supported countries", operation="list_supported_countries", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return NumverifyFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a numverify API access key")
        config = self.config.config
        params = {"access_key": credential.api_key}
        path = "/countries"
        if isinstance(config, ValidatePhoneNumber):
            path = "/validate"
            params["number"] = config.number
            if config.country_code:
                params["country_code"] = config.country_code
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE_URL + path, params=params, headers={"Accept": "application/json"})
        except (httpx.HTTPError, SSRFError):
            # Transport exceptions include the request URL, which contains the key.
            return {"status": "error", "error": "numverify request could not be completed"}
        status = response.status_code
        try:
            if len(response.content) > 2_000_000:
                raise ValueError()
            payload = response.json()
        except ValueError:
            return {"status": "error", "http_status": status, "error": "numverify returned an invalid JSON response"}
        if not isinstance(payload, dict):
            return {"status": "error", "http_status": status, "error": "numverify returned an unexpected response"}
        if not 200 <= status < 300 or payload.get("success") is False or "error" in payload:
            error = payload.get("error")
            if isinstance(error, dict):
                error = error.get("info") or error.get("type")
            message = error if isinstance(error, str) and error else "numverify did not confirm this read"
            return {"status": "error", "http_status": status, "error": _redact(message, credential.api_key)}
        if isinstance(config, ValidatePhoneNumber):
            if type(payload.get("valid")) is not bool:
                return {"status": "error", "http_status": status, "error": "numverify validation response is missing a validity flag"}
            # Invalid numbers legitimately omit carrier, country and other fields.
            result = {key: payload[key] for key in ("valid", "number", "local_format", "international_format", "country_prefix", "country_code", "country_name", "location", "carrier", "line_type") if key in payload}
        else:
            if not payload or any(not re.fullmatch(r"[A-Z]{2}", key) or not isinstance(value, dict) or not isinstance(value.get("country_name"), str) or not isinstance(value.get("dialling_code"), str) for key, value in payload.items()):
                return {"status": "error", "http_status": status, "error": "numverify returned an unexpected countries response"}
            result = {"countries": {key: {"country_name": value["country_name"], "dialling_code": value["dialling_code"]} for key, value in payload.items()}}
        return {**_redact(result, credential.api_key), "status": "success", "http_status": status}
