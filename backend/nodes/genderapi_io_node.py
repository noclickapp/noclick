"""GenderAPI.io V2: fixed endpoints, pasted API keys and explicit billing metadata.

Contract: https://api.genderapi.io/api/v2/openapi.json (2.0.0).
Inference is not verified personal identity. Every prediction, including a retry,
is independently billable; this node never retries or follows redirects.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.genderapi.io"
CREDENTIAL_TYPE = "genderapi_io_api_key"
COUNTRIES = frozenset(['AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AO', 'AQ', 'AR', 'AS', 'AT', 'AU', 'AW', 'AX', 'AZ', 'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ', 'BR', 'BS', 'BT', 'BV', 'BW', 'BY', 'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK', 'CL', 'CM', 'CN', 'CO', 'CR', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DE', 'DJ', 'DK', 'DM', 'DO', 'DZ', 'EC', 'EE', 'EG', 'EH', 'ER', 'ES', 'ET', 'FI', 'FJ', 'FK', 'FM', 'FO', 'FR', 'GA', 'GB', 'GD', 'GE', 'GF', 'GG', 'GH', 'GI', 'GL', 'GM', 'GN', 'GP', 'GQ', 'GR', 'GS', 'GT', 'GU', 'GW', 'GY', 'HK', 'HM', 'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IM', 'IN', 'IO', 'IQ', 'IR', 'IS', 'IT', 'JE', 'JM', 'JO', 'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN', 'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LI', 'LK', 'LR', 'LS', 'LT', 'LU', 'LV', 'LY', 'MA', 'MC', 'MD', 'ME', 'MF', 'MG', 'MH', 'MK', 'ML', 'MM', 'MN', 'MO', 'MP', 'MQ', 'MR', 'MS', 'MT', 'MU', 'MV', 'MW', 'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI', 'NL', 'NO', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG', 'PH', 'PK', 'PL', 'PM', 'PN', 'PR', 'PS', 'PT', 'PW', 'PY', 'QA', 'RE', 'RO', 'RS', 'RU', 'RW', 'SA', 'SB', 'SC', 'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL', 'SM', 'SN', 'SO', 'SR', 'SS', 'ST', 'SV', 'SX', 'SY', 'SZ', 'TC', 'TD', 'TF', 'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TR', 'TT', 'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VE', 'VG', 'VI', 'VN', 'VU', 'WF', 'WS', 'YE', 'YT', 'ZA', 'ZM', 'ZW'])


class GenderapiIoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="GenderAPI.io API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.genderapi.io/",
            "x-credential-instructions": "Paste your existing GenderAPI.io API key. V1 and V2 share the same credits. NoClick checks the free usage endpoint and requires API-key access: an invalid key can otherwise fall back to the IP trial. Predictions cost credits, including unknown results and repeated requests.",
        })
    credential_type: Literal["genderapi_io_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Country(_Input):
    country: str | None = Field(None, description="Optional uppercase ISO 3166-1 alpha-2 country code.")

    @field_validator("country")
    @classmethod
    def country_code(cls, value):
        if value is not None and value not in COUNTRIES:
            raise ValueError("Use an uppercase ISO 3166-1 alpha-2 country code")
        return value


class PredictionOptions(_Input):
    ai_mode: Literal["off", "fallback", "always"] | None = Field(None,
        description="Omit for provider default: fallback for singles, off for batches. Always costs 2 credits; fallback costs 1.")


class PredictionItem(_Country):
    type: Literal["name", "email", "username"]
    value: str = Field(..., min_length=1, max_length=254,
        description="Name, email address or username. Estimates are not verified identity.")
    id: str | None = Field(None, min_length=1, max_length=64)
    forceToGenderize: StrictBool | None = Field(None,
        description="Try dataset first, then nickname AI when unresolved (2 credits total). Cannot combine with AI off or always.")
    options: PredictionOptions | None = None

    @field_validator("value")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use nonblank text without control characters")
        return value

    @model_validator(mode="after")
    def check_options(self):
        if self.forceToGenderize and self.options and self.options.ai_mode in {"off", "always"}:
            raise ValueError("forceToGenderize requires AI fallback or omitted AI mode")
        if self.type == "email" and (self.value.count("@") != 1 or any(c.isspace() for c in self.value) or not all(self.value.split("@"))):
            raise ValueError("Use a valid email address")
        return self


class PredictName(PredictionItem):
    """Estimate gender from a first or full name (billable)."""
    operation: Literal["predict_name"] = "predict_name"
    type: Literal["name"] = Field("name", json_schema_extra={"ui:hidden": True})


class PredictEmail(PredictionItem):
    """Estimate gender from a name signal in an email address (billable)."""
    operation: Literal["predict_email"] = "predict_email"
    type: Literal["email"] = Field("email", json_schema_extra={"ui:hidden": True})


class PredictUsername(PredictionItem):
    """Estimate gender from a username or nickname (billable)."""
    operation: Literal["predict_username"] = "predict_username"
    type: Literal["username"] = Field("username", json_schema_extra={"ui:hidden": True})


class PredictGenderGet(_Country):
    """Estimate gender using the documented GET query interface (billable)."""
    operation: Literal["predict_gender_get"] = "predict_gender_get"
    type: Literal["name", "email", "username"] = "name"
    value: str = Field(..., min_length=1, max_length=254)
    forceToGenderize: StrictBool | None = None
    ai_mode: Literal["off", "fallback", "always"] | None = None

    @model_validator(mode="after")
    def validate_prediction(self):
        PredictionItem(type=self.type, value=self.value, country=self.country,
            forceToGenderize=self.forceToGenderize, options=PredictionOptions(ai_mode=self.ai_mode))
        return self


class PredictBatch(_Input):
    """Submit 1–50 mixed inputs; preserve ordered successes, unknowns and item errors."""
    operation: Literal["predict_batch"] = "predict_batch"
    items: list[PredictionItem] = Field(..., min_length=1, max_length=50,
        description="Batch defaults to dataset only. Every retry is a new billable operation.")

    @field_validator("items")
    @classmethod
    def unique_ids(cls, values):
        ids = [v.id for v in values if v.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Batch item IDs must be unique")
        return values


class ValidatePhone(_Country):
    """Check phone structure and formatting (1 credit), not subscriber existence."""
    operation: Literal["validate_phone"] = "validate_phone"
    number: str = Field(..., min_length=3, max_length=32, pattern=r"^\+?[0-9 ()-]+$")

    @model_validator(mode="after")
    def national_country(self):
        if not self.number.startswith("+") and self.country is None:
            raise ValueError("Supply country for a national phone number")
        return self


class GetUsage(_Input):
    """Read account or trial credits without spending credits; reports access mode."""
    operation: Literal["get_usage"] = "get_usage"
    verify_api_key: StrictBool = Field(False,
        description="Require account-key access; IP-trial fallback is rejected. Used automatically when connecting.")


class GetCapabilities(_Input):
    """Read public capabilities and current limits, free of charge."""
    operation: Literal["get_capabilities"] = "get_capabilities"


class GetErrorCatalog(_Input):
    """Read public machine-readable error and recovery guidance."""
    operation: Literal["get_error_catalog"] = "get_error_catalog"


class GetOpenapi(_Input):
    """Read the provider's current published OpenAPI contract."""
    operation: Literal["get_openapi"] = "get_openapi"


GenderapiIoOperation = Annotated[Union[PredictName, PredictEmail, PredictUsername,
    PredictGenderGet, PredictBatch, ValidatePhone, GetUsage, GetCapabilities,
    GetErrorCatalog, GetOpenapi], Field(discriminator="operation")]


class GenderapiIoConfig(NodeConfig[GenderapiIoOperation, GenderapiIoAPIKeyCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class GenderapiIoNode(WorkflowNode):
    integration_type = "automation-genderapi-io"
    connection_evidence = ConnectionEvidence(noun="GenderAPI.io API-key access", operation="get_usage",
        operation_arguments={"verify_api_key": True}, proves="reachability")

    @classmethod
    def get_config_model(cls):
        return GenderapiIoConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a GenderAPI.io API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path, body, params = "GET", "/api/v2", None, None
        if isinstance(op, (PredictName, PredictEmail, PredictUsername)):
            method, path = "POST", "/api/v2/gender"
            body = op.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(op, PredictGenderGet):
            path = "/api/v2/gender"
            params = {k: str(v).lower() if isinstance(v, bool) else v
                for k, v in op.model_dump(exclude={"operation"}, exclude_none=True).items()}
        elif isinstance(op, PredictBatch):
            method, path = "POST", "/api/v2/gender/batch"
            body = {"items": [v.model_dump(exclude_none=True) for v in op.items]}
        elif isinstance(op, ValidatePhone):
            method, path = "POST", "/api/v2/phone/validate"
            body = op.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(op, GetUsage):
            path = "/api/v2/usage"
        elif isinstance(op, GetErrorCatalog):
            path = "/api/v2/errors"
        elif isinstance(op, GetOpenapi):
            path = "/api/v2/openapi.json"
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("GenderAPI.io request outcome is unknown; inspect billing before retrying") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("GenderAPI.io returned a non-JSON response; inspect billing before retrying") from None
        if not isinstance(payload, dict):
            raise ValueError("GenderAPI.io returned an unexpected response shape")
        if not 200 <= response.status_code < 300 or "error" in payload:
            output = {"status": "error", "success": False, "status_code": response.status_code,
                "error": payload.get("detail") or payload.get("title") or payload.get("error") or "GenderAPI.io request failed",
                "response": payload}
        else:
            meta = payload.get("meta", {})
            access = meta.get("access", {}) if isinstance(meta, dict) else {}
            mode = access.get("mode") if isinstance(access, dict) else None
            if isinstance(op, GetUsage) and op.verify_api_key and mode != "api_key":
                if mode in {"ip_trial", "unauthenticated"}:
                    output = {"status": "error", "success": False,
                        "error": "API-key authentication failed: " + (access.get("reason") or "api_key_invalid"), "access_mode": mode}
                else:
                    raise ValueError("GenderAPI.io omitted account-key access evidence")
            else:
                if isinstance(op, (GetUsage, PredictName, PredictEmail, PredictUsername, PredictGenderGet, PredictBatch, ValidatePhone)):
                    if "data" not in payload or not isinstance(payload.get("meta"), dict):
                        raise ValueError("GenderAPI.io omitted data or metadata")
                if isinstance(op, PredictBatch) and not isinstance(payload.get("data"), list):
                    raise ValueError("GenderAPI.io returned a malformed batch result")
                output = {"status": "success", "success": True, "response": payload,
                    "access_mode": mode, "api_key_verified": mode == "api_key"}
                if "data" in payload:
                    output["data"] = payload["data"]
                if "meta" in payload:
                    output["meta"] = meta
                if isinstance(op, PredictBatch):
                    output["has_item_errors"] = any("error" in item for item in payload["data"] if isinstance(item, dict))
        output = _redact(output, secret)
        await self.emit(output)
        return output
