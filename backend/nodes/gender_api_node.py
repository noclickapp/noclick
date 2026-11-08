"""Gender-API v2 name enrichment using the provider's pinned OpenAPI 2.1 contract.

Each action makes one request. Query POSTs consume credits but do not mutate
provider records. Account creation is deliberately outside this integration.
Contract: https://gender-api.com/openapi/openapi.yml
"""
from __future__ import annotations

import json
from ipaddress import ip_address
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

API_BASE = "https://gender-api.com/v2"
CREDENTIAL_TYPE = "gender_api_token"


class GenderApiTokenCredential(BaseModel):
    model_config = ConfigDict(title="Gender API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://gender-api.com/en/account/auth-tokens",
            "x-credential-instructions": "Open your Gender-API account's Auth Tokens page, create or copy an API token, and paste it here. NoClick uses it as a Bearer token. Connection checks read your account's usage statistics without spending query credits.",
        })
    credential_type: Literal["gender_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Localization(_Input):
    country: str | None = Field(None, pattern=r"^[A-Z]{2}$", description="Optional ISO 3166 alpha-2 country code, for example US.")
    locale: str | None = Field(None, max_length=50, description="Optional browser locale, for example en_US.")
    ip: str | None = Field(None, description="Optional IPv4 or IPv6 address for localization.")

    @field_validator("ip")
    @classmethod
    def valid_ip(cls, value):
        if value is not None:
            ip_address(value)
        return value


class _FirstName(_Localization):
    first_name: str = Field(..., min_length=1, max_length=50)


class _FullName(_Localization):
    full_name: str = Field(..., min_length=3, max_length=100)


class _Email(_Localization):
    email: str = Field(..., min_length=3, max_length=100)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if "@" not in value or any(c.isspace() for c in value):
            raise ValueError("Enter an email address")
        return value


class GenderByFirstName(_FirstName):
    """Query gender from one first name, optionally localized."""
    operation: Literal["query_first_name"] = Field("query_first_name", json_schema_extra={"ui:hidden": True})


class GenderByFullName(_FullName):
    """Split one full name and query gender."""
    operation: Literal["query_full_name"] = Field("query_full_name", json_schema_extra={"ui:hidden": True})


class GenderByEmail(_Email):
    """Extract a name from an email address and query gender."""
    operation: Literal["query_email"] = Field("query_email", json_schema_extra={"ui:hidden": True})


class _Batch(_Input):
    entries_json: str = Field(..., description="JSON array of query objects. Each can include country, locale, ip and an optional id of at most 50 characters. NoClick limits each batch to 100 entries; split larger lists.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class GenderBatchFirstNames(_Batch):
    """Query gender for multiple first names in a single request."""
    operation: Literal["query_first_names_batch"] = Field("query_first_names_batch", json_schema_extra={"ui:hidden": True})
    entries_json: str = Field(..., description='JSON array, for example [{"first_name":"sandra","country":"US","id":"1"}]. Up to 100 entries per call.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class GenderBatchFullNames(_Batch):
    """Split and query multiple full names in a single request."""
    operation: Literal["query_full_names_batch"] = Field("query_full_names_batch", json_schema_extra={"ui:hidden": True})
    entries_json: str = Field(..., description='JSON array, for example [{"full_name":"Sandra Miller","country":"US","id":"1"}]. Up to 100 entries per call.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class GenderBatchEmails(_Batch):
    """Extract names and query multiple email addresses in a single request."""
    operation: Literal["query_emails_batch"] = Field("query_emails_batch", json_schema_extra={"ui:hidden": True})
    entries_json: str = Field(..., description='JSON array, for example [{"email":"sandra.miller14@gmail.com","country":"US","id":"1"}]. Up to 100 entries per call.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class OriginByFirstName(_Input):
    """Query likely countries of origin and gender from a first name (two credits)."""
    operation: Literal["query_origin_first_name"] = Field("query_origin_first_name", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=50)


class OriginByFullName(_Input):
    """Query likely countries of origin and gender from a full name (two credits)."""
    operation: Literal["query_origin_full_name"] = Field("query_origin_full_name", json_schema_extra={"ui:hidden": True})
    full_name: str = Field(..., min_length=3, max_length=100)


class OriginByEmail(_Input):
    """Query likely countries of origin and gender from an email address (two credits)."""
    operation: Literal["query_origin_email"] = Field("query_origin_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, max_length=100)
    _valid_email = field_validator("email")(_Email.valid_email.__func__)


class GetStatistics(_Input):
    """Read this account's remaining credits, limit status and last month's usage (free)."""
    operation: Literal["get_statistics"] = Field("get_statistics", json_schema_extra={"ui:hidden": True})


GenderApiOperation = Annotated[Union[GenderByFirstName, GenderByFullName, GenderByEmail,
    GenderBatchFirstNames, GenderBatchFullNames, GenderBatchEmails,
    OriginByFirstName, OriginByFullName, OriginByEmail, GetStatistics], Field(discriminator="operation")]


class GenderApiConfig(NodeConfig[GenderApiOperation, GenderApiTokenCredential]):
    pass


# Fixed routes, not an arbitrary HTTP escape hatch. Multiple origin input forms
# each map to the same documented POST /country-of-origin operation.
ROUTES = {
    "query_first_name": "/gender/by-first-name",
    "query_full_name": "/gender/by-full-name",
    "query_email": "/gender/by-email-address",
    "query_first_names_batch": "/gender/by-first-name-multiple",
    "query_full_names_batch": "/gender/by-full-name-multiple",
    "query_emails_batch": "/gender/by-email-address-multiple",
    "query_origin_first_name": "/country-of-origin",
    "query_origin_full_name": "/country-of-origin",
    "query_origin_email": "/country-of-origin",
    "get_statistics": "/statistic",
}
BATCH_MODELS = {
    "query_first_names_batch": _FirstName,
    "query_full_names_batch": _FullName,
    "query_emails_batch": _Email,
}


def request_body(op):
    if op.operation == "get_statistics":
        return None
    if op.operation not in BATCH_MODELS:
        return op.model_dump(exclude={"operation"}, exclude_none=True)
    try:
        rows = json.loads(op.entries_json)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid JSON array of query objects") from None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("Provide between 1 and 100 query objects")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each query must be an object")
        row = row.copy()
        identifier = row.pop("id", None)
        if identifier is not None and (type(identifier) not in {str, int} or len(str(identifier)) > 50):
            raise ValueError("Batch id must be a string or integer of at most 50 characters")
        validated = BATCH_MODELS[op.operation].model_validate(row).model_dump(exclude_none=True)
        if identifier is not None:
            validated["id"] = identifier
        result.append(validated)
    return result


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k.replace(token, "[redacted]"): _redact(v, token) for k, v in value.items()}
    return value


class GenderApiNode(WorkflowNode):
    integration_type = "automation-gender-api"
    connection_evidence = ConnectionEvidence(operation="get_statistics", noun="account usage statistics",
        label_keys=("name",), proves="account")
    edit_examples = ["Enrich a new contact by full name", "Query a batch of email addresses", "Alert me when remaining query credits are low"]

    @classmethod
    def get_config_model(cls):
        return GenderApiConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Gender API token")
        op = self.config.config
        token = self.config.credentials.api_token
        body = request_body(op)
        kwargs = {"headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}}
        if body is not None:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET" if body is None else "POST", API_BASE + ROUTES[op.operation], **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "Gender-API request could not be completed; check before retrying a credit-consuming query."}
        if len(response.content) > 5_000_000 or "json" not in response.headers.get("content-type", "").lower():
            return {"status": "error", "status_code": response.status_code, "error": "Expected a bounded JSON response from Gender-API"}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "status_code": response.status_code, "error": "Gender-API returned invalid JSON"}
        payload = _redact(payload, token)
        if response.status_code != 200 or (isinstance(payload, dict) and ("error" in payload or "title" in payload)):
            result = {"status": "error", "status_code": response.status_code, "error": payload}
            if response.status_code == 429 and response.headers.get("retry-after"):
                result["retry_after"] = response.headers["retry-after"]
            return result
        if op.operation == "get_statistics":
            if not isinstance(payload, dict) or type(payload.get("remaining_credits")) is not int or type(payload.get("is_limit_reached")) is not bool:
                return {"status": "error", "error": "Gender-API statistics response was incomplete"}
            # The free authenticated read is account-specific, not an identity claim.
            return {"status": "success", "action": op.operation, "data": payload,
                "name": str(payload["remaining_credits"]) + " credits remaining",
                "items": [{"name": str(payload["remaining_credits"]) + " credits remaining"}], "status_code": 200}
        rows = payload if op.operation in BATCH_MODELS else [payload]
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or type(row.get("result_found")) is not bool for row in rows):
            return {"status": "error", "error": "Gender-API query response was incomplete"}
        if op.operation in BATCH_MODELS and len(rows) != len(body):
            return {"status": "error", "error": "Gender-API batch response did not include every query"}
        return {"status": "success", "action": op.operation, "data": payload, "status_code": 200}
