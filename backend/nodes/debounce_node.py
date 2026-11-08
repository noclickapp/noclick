"""DeBounce API v1: one documented request per action, with pasted API keys.

Contract: https://developers.debounce.com/api-reference/openapi.json (1.0.0).
Validation presets enable the provider's documented optional query flags.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client


class DebounceAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Debounce API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.debounce.io/api",
        "x-credential-instructions": "Paste your DeBounce API key from API Settings. NoClick checks your account credit balance when you connect. Validation and bulk uploads consume provider credits; photo and enrichment actions cost extra credits when successful.",
    })
    credential_type: Literal["debounce_api_key"] = Field("debounce_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API Key", key=True)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Email(_Config):
    email: str = Field(..., title="Email Address", min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ValidateEmail(_Email):
    operation: Literal["validate_email"] = Field("validate_email", title="Validate Email", description="Validate one email address. Consumes validation credits.")
    photo: bool = Field(False, title="Include Profile Photo", description="One extra credit per successful photo.")
    append: bool = Field(False, title="Enrich Full Name and Avatar", description="20 extra credits per successful enrichment.")
    gsuite: bool = Field(False, title="Detect G Suite Accept-All")


class ValidateWithPhoto(_Email):
    operation: Literal["validate_with_photo"] = Field("validate_with_photo", title="Validate with Profile Photo", description="Validate an email and request its profile photo. One extra credit per successful photo.")


class ValidateWithEnrichment(_Email):
    operation: Literal["validate_with_enrichment"] = Field("validate_with_enrichment", title="Validate with Contact Enrichment", description="Validate an email and request full name and avatar. 20 extra credits per successful enrichment.")


class ValidateGSuite(_Email):
    operation: Literal["validate_gsuite"] = Field("validate_gsuite", title="Validate G Suite Accept-All", description="Validate an email with G Suite accept-all detection enabled.")


class ReverseEmail(_Email):
    operation: Literal["reverse_email_lookup"] = Field("reverse_email_lookup", title="Reverse Email Lookup", description="Look up additional data using the contract's reverse lookup endpoint.")


class UploadBulkList(_Config):
    operation: Literal["upload_bulk_list"] = Field("upload_bulk_list", title="Upload Bulk List", description="Start bulk validation from a direct HTTPS CSV/TXT URL on your server. Under 20 MB, at most 200,000 emails, one per line. Validation starts automatically; later jobs queue.")
    url: str = Field(..., title="Email List URL", max_length=8192, pattern=r"^https://[^\s/]+/[^\s]+\.(csv|txt)(\?[^\s]*)?$", json_schema_extra={"format": "uri"})

    @field_validator("url")
    @classmethod
    def direct_file(cls, value):
        p = urlsplit(value)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment or not p.path.lower().endswith((".csv", ".txt")):
            raise ValueError("Use a direct HTTPS CSV or TXT URL hosted on your server")
        return value


class CheckBulkStatus(_Config):
    operation: Literal["check_bulk_status"] = Field("check_bulk_status", title="Check Bulk Status", description="Read the status and result download link for an API-uploaded list.")
    list_id: str = Field(..., title="List ID", min_length=1, max_length=256)


class GetBalance(_Config):
    operation: Literal["get_balance"] = Field("get_balance", title="Get Account Balance", description="Read remaining account validation credits without spending credits.")


class GetUsage(_Config):
    operation: Literal["get_usage"] = Field("get_usage", title="Get Usage History")
    start: str = Field(..., title="Start Date (YY-MM-DD)", pattern=r"^\d{2}-\d{2}-\d{2}$")
    end: str = Field(..., title="End Date (YY-MM-DD)", pattern=r"^\d{2}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def dates(self):
        start, end = (datetime.strptime(s, "%y-%m-%d").date() for s in (self.start, self.end))
        if start < date(2020, 8, 14) or end < start or end > date.today():
            raise ValueError("Use an ordered range from 20-08-14 through today")
        return self


class CheckDisposable(_Config):
    operation: Literal["check_disposable_email"] = Field("check_disposable_email", title="Check Disposable Email", description="Check an email address or domain with the free disposable detector. No API key is sent to this endpoint.")
    email: str = Field(..., title="Email Address or Domain", min_length=1, max_length=320)


DebounceOperation = Annotated[ValidateEmail | ValidateWithPhoto | ValidateWithEnrichment | ValidateGSuite | ReverseEmail | UploadBulkList | CheckBulkStatus | GetBalance | GetUsage | CheckDisposable, Field(discriminator="operation")]


class DebounceFullConfig(NodeConfig):
    config: DebounceOperation
    credentials: DebounceAPIKeyCredential | None = None


# Each action maps to exactly one operation in the pinned provider contract.
ROUTES = {
    "validate_email": ("api", "/v1/"),
    "validate_with_photo": ("api", "/v1/"),
    "validate_with_enrichment": ("api", "/v1/"),
    "validate_gsuite": ("api", "/v1/"),
    "reverse_email_lookup": ("api", "/v1/reverse/"),
    "upload_bulk_list": ("bulk", "/v1/upload/"),
    "check_bulk_status": ("bulk", "/v1/status/"),
    "get_balance": ("api", "/v1/balance/"),
    "get_usage": ("api", "/v1/usage/"),
    "check_disposable_email": ("disposable", "/"),
}
PRESETS = {"validate_with_photo": "photo", "validate_with_enrichment": "append", "validate_gsuite": "gsuite"}


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k.lower() not in {"api", "api_key"}}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[redacted]")
    return value


class DebounceNode(WorkflowNode):
    integration_type = "automation-debounce"
    connection_evidence = ConnectionEvidence(noun="DeBounce account credit balance", operation="get_balance")

    @classmethod
    def get_config_model(cls):
        return DebounceFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        secret = credential.api_key if credential else ""
        if not secret and config.operation != "check_disposable_email":
            raise ValueError("Connect a DeBounce API key")
        host, path = ROUTES[config.operation]
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        if config.operation in PRESETS:
            params[PRESETS[config.operation]] = "true"
        if host != "disposable":
            params["api"] = secret
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", f"https://{host}.debounce.io{path}", params=params, headers={"Accept": "application/json"})
            if len(response.content) > 5_000_000:
                raise ValueError("DeBounce response exceeded the size limit")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("DeBounce returned an unexpected response")
            body = _redact(body, secret)
            nested = body.get("debounce", {})
            error = body.get("error") or (nested.get("error") if isinstance(nested, dict) else None)
            if error or body.get("success") in (0, "0", False):
                return {"status": "error", "http_status": response.status_code, "error": str(error or "DeBounce did not confirm the request")}
            if response.status_code != 200:
                return {"status": "error", "http_status": response.status_code, "error": "DeBounce request failed"}
            if config.operation == "get_balance":
                balance = body.get("balance")
                if isinstance(balance, bool) or not isinstance(balance, (int, str)) or not str(balance).isdigit():
                    raise ValueError("DeBounce returned an invalid account balance")
            elif host == "disposable":
                if body.get("disposable") not in ("true", "false", True, False):
                    raise ValueError("DeBounce returned an invalid disposable result")
            elif body.get("success") not in (1, "1", True):
                raise ValueError("DeBounce response did not confirm success")
            if config.operation == "upload_bulk_list":
                if not isinstance(nested, dict) or not isinstance(nested.get("list_id"), str) or not nested["list_id"]:
                    raise ValueError("DeBounce did not return a bulk list ID")
            result = {**body, "status": "success"}
            if config.operation == "get_balance":
                result["items"] = [{"name": f"{balance} validation credits remaining"}]
            return result
        except (httpx.HTTPError, SSRFError):
            # HTTP exception strings include the query URL, which contains the key.
            return {"status": "error", "error": "DeBounce request could not be completed"}
        except (ValueError, TypeError):
            return {"status": "error", "error": "DeBounce returned an unexpected response"}
