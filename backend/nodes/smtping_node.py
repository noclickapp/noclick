"""SMTPing email verification API v1, https://smtping.com/docs.

Each operation performs one documented request. Submitted jobs are returned
immediately; poll and fetch their results with separate operations. No retries
are made automatically because submissions can consume account credits.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://api.smtping.com/api/v1"
CREDENTIAL_TYPE = "smtping_api_key"


class SmtpingApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Smtping API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.smtping.com",
            "x-credential-instructions": "In the Smtping dashboard, open API Keys and create a key. Copy the secret shown once. Paste only the key; NoClick sends it as X-API-Key. Keys share your account credits and rate limits.",
        },
    )
    credential_type: Literal["smtping_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


# SMTPing's own MCP server: agents get its tools through a person's SMTPing sign-in.
SmtpingMcpCredential = mcp_credential("smtping", "https://mcp.smtping.com/mcp", app="SMTPing")
SmtpingCredential = Union[SmtpingApiKeyCredential, SmtpingMcpCredential]


Email = Annotated[str, Field(min_length=3, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", json_schema_extra={"format": "email"})]
CheckType = Literal["spamtrap", "disposable", "spambot", "complainer"]


class _Email(_Input):
    email: Email = Field(..., title="Email Address")


class _Emails(_Input):
    emails: list[Email] = Field(..., title="Email Addresses", min_length=1, max_length=100000,
                              description="JSON list of addresses; up to 100,000 for an asynchronous job.")


class _Job(_Input):
    job_id: str = Field(..., title="Job ID", json_schema_extra={"format": "uuid"},
                        description="The jobId returned by the matching submit operation.")

    @field_validator("job_id")
    @classmethod
    def job(cls, value):
        try:
            return str(UUID(value))
        except (ValueError, AttributeError):
            raise ValueError("Use the UUID jobId returned by Smtping") from None


class _Check(_Input):
    check: CheckType = Field(..., title="Check", description="List to check: spamtrap, disposable, spambot or complainer.")


class VerifySingle(_Email):
    operation: Literal["verify_single"] = Field("verify_single", title="Verify Email", json_schema_extra={"ui:hidden": True})


class CreateBulkJob(_Emails):
    operation: Literal["create_bulk_job"] = Field("create_bulk_job", title="Submit Bulk Verification Job", json_schema_extra={"ui:hidden": True})


class GetBulkJob(_Job):
    operation: Literal["get_bulk_job"] = Field("get_bulk_job", title="Get Bulk Verification Progress", json_schema_extra={"ui:hidden": True})


class GetBulkJobResult(_Job):
    operation: Literal["get_bulk_job_result"] = Field("get_bulk_job_result", title="Get Bulk Verification Results", json_schema_extra={"ui:hidden": True})


class CheckOne(_Email, _Check):
    operation: Literal["check_one"] = Field("check_one", title="Check One Email", json_schema_extra={"ui:hidden": True})


class CheckBatch(_Emails, _Check):
    operation: Literal["check_batch"] = Field("check_batch", title="Check Email Batch", json_schema_extra={"ui:hidden": True})
    emails: list[Email] = Field(..., title="Email Addresses", min_length=1, max_length=1000, description="Synchronous batch: at most 1,000 addresses. Use a check job for larger lists.")


class CreateCheckJob(_Emails, _Check):
    operation: Literal["create_check_job"] = Field("create_check_job", title="Submit Email Check Job", json_schema_extra={"ui:hidden": True})


class GetCheckJob(_Job):
    operation: Literal["get_check_job"] = Field("get_check_job", title="Get Email Check Progress", json_schema_extra={"ui:hidden": True})


class GetCheckJobResult(_Job):
    operation: Literal["get_check_job_result"] = Field("get_check_job_result", title="Get Email Check Results", json_schema_extra={"ui:hidden": True})


class CheckFlags(_Email):
    operation: Literal["check_flags"] = Field("check_flags", title="Get All Email Flags", json_schema_extra={"ui:hidden": True})


class GetCredits(_Input):
    operation: Literal["get_credits"] = Field("get_credits", title="Get Credit Balance", json_schema_extra={"ui:hidden": True})


class GetUsage(_Input):
    operation: Literal["get_usage"] = Field("get_usage", title="Get Usage", json_schema_extra={"ui:hidden": True})


SmtpingOperation = Annotated[Union[VerifySingle, CreateBulkJob, GetBulkJob, GetBulkJobResult, CheckOne, CheckBatch, CreateCheckJob, GetCheckJob, GetCheckJobResult, CheckFlags, GetCredits, GetUsage], Field(discriminator="operation")]


class SmtpingConfig(NodeConfig[SmtpingOperation, SmtpingCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# One config operation maps to exactly one pinned OpenAPI operation.
ROUTES = {
    "verify_single": ("POST", "/verify/single", 200),
    "create_bulk_job": ("POST", "/verify/bulk", 202),
    "get_bulk_job": ("GET", "/verify/bulk/{job_id}", 200),
    "get_bulk_job_result": ("GET", "/verify/bulk/{job_id}/result", 200),
    "check_one": ("POST", "/checks/{check}", 200),
    "check_batch": ("POST", "/checks/{check}/batch", 200),
    "create_check_job": ("POST", "/checks/{check}/jobs", 202),
    "get_check_job": ("GET", "/checks/jobs/{job_id}", 200),
    "get_check_job_result": ("GET", "/checks/jobs/{job_id}/result", 200),
    "check_flags": ("POST", "/checks/flags", 200),
    "get_credits": ("GET", "/credits", 200),
    "get_usage": ("GET", "/usage", 200),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


class SmtpingNode(WorkflowNode):
    integration_type = "automation-smtping"
    credential_provider_labels = {"smtping": "SMTPing Account"}
    # The API exposes a balance, not an account name. Do not claim identity.
    connection_evidence = ConnectionEvidence(
        noun="credit balance", operation="get_credits", proves="reachability",
    )
    edit_examples = ["Verify an email address", "Submit a list for bulk verification", "Check for disposable emails", "Get my remaining credits"]

    @classmethod
    def get_config_model(cls):
        return SmtpingConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Smtping API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, template, expected = ROUTES[config.operation]
        route = template.format(**config.model_dump())
        body = ({"email": config.email} if isinstance(config, _Email) else
                {"emails": config.emails} if isinstance(config, _Emails) else None)
        headers = {"X-API-Key": secret, "Accept": "application/json"}
        try:
            async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False,
                                            timeout=httpx.Timeout(120.0)) as client:
                response = await client.request(method, BASE_URL + route, headers=headers,
                                                **({"json": body} if body is not None else {}))
            try:
                data = response.json()
            except (ValueError, json.JSONDecodeError):
                data = None
            if response.status_code != expected:
                message = data.get("error") if isinstance(data, dict) else None
                output = {"status": "error", "http_status": response.status_code,
                          "error": message if isinstance(message, str) else "Smtping returned an unexpected HTTP response"}
                if response.status_code == 429:
                    output["retry_after"] = response.headers.get("Retry-After")
                if response.status_code == 409:
                    output["pending"] = True
            elif not isinstance(data, (dict, list)) or (isinstance(data, dict) and "error" in data):
                output = {"status": "error", "error": "Smtping returned an unexpected JSON response"}
            elif config.operation in {"get_bulk_job_result", "get_check_job_result"} and not isinstance(data, list):
                output = {"status": "error", "error": "Smtping job results must be a JSON array"}
            elif config.operation not in {"get_bulk_job_result", "get_check_job_result"} and not isinstance(data, dict):
                output = {"status": "error", "error": "Smtping response must be a JSON object"}
            else:
                # Preserve provider status (Queued, Succeeded, valid, unknown, etc.)
                # under data; HTTP acceptance does not mean a job has completed.
                output = {"status": "success", "data": data}
        except (httpx.HTTPError, OSError, SSRFError):
            output = {"status": "error", "error": "Smtping request did not complete; inspect the account before retrying a submission"}
        output = _redact({"action": config.operation, **output}, secret)
        await self.emit(output)
        return output
