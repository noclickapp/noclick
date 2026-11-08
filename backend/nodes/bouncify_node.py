"""All seven Bouncify v1 operations, with pasted query API-key authentication.

Bulk paths and JSON payloads follow the provider's published code examples;
its OpenAPI incorrectly omits job path templates and models RAW_BODY wrappers.
Verification can consume credits. Requests are never automatically retried.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.bouncify.io/v1"


class BouncifyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bouncify API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.bouncify.io/",
            "x-credential-instructions": "Paste your API key from the Bouncify dashboard. NoClick sends it as the apikey query parameter to api.bouncify.io. The connection check reads your credit balance without verifying an email or consuming verification credits.",
        })
    credential_type: Literal["bouncify_api_key"] = Field("bouncify_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class VerifyEmail(_Input):
    """Verify one address; this can consume verification credits."""
    operation: Literal["verify_email"] = Field("verify_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, max_length=1000, description="Email address to verify.",
        json_schema_extra={"format": "email"})
    timeout: int = Field(180000, ge=30000, le=180000, description="Provider verification timeout in milliseconds.")


class EmailRow(BaseModel):
    """An email plus optional columns retained in the downloaded CSV."""
    model_config = ConfigDict(extra="allow")
    email: str = Field(..., min_length=1, max_length=1000, json_schema_extra={"format": "email"})


class CreateBulkJob(_Input):
    """Upload an array of email objects; auto verification can consume credits."""
    operation: Literal["create_bulk_job"] = Field("create_bulk_job", json_schema_extra={"ui:hidden": True})
    emails: list[EmailRow] = Field(..., min_length=1, max_length=500000,
        description="Email objects, optionally with extra columns such as firstname and lastname. Maximum payload 10 MB.")
    auto_verify: StrictBool = Field(False, description="Start verification immediately after the list is prepared.")

    @model_validator(mode="after")
    def size(self):
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode("utf-8")) > 10_000_000:
            raise ValueError("The email list must not exceed 10 MB")
        return self


class _Job(_Input):
    job_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,128}$", description="job_id returned when the list was uploaded.")


class GetBulkJob(_Job):
    """Read preparation/verification status and result counts for one list."""
    operation: Literal["get_bulk_job"] = Field("get_bulk_job", json_schema_extra={"ui:hidden": True})


class StartBulkJob(_Job):
    """Start a ready list once; verification cannot be paused or restarted."""
    operation: Literal["start_bulk_job"] = Field("start_bulk_job", json_schema_extra={"ui:hidden": True})


class DeleteBulkJob(_Job):
    """Request list deletion. The acknowledgement does not prove completed deletion."""
    operation: Literal["delete_bulk_job"] = Field("delete_bulk_job", json_schema_extra={"ui:hidden": True})


class DownloadBulkResults(_Job):
    """Download a completed list as CSV, optionally selecting result types."""
    operation: Literal["download_bulk_results"] = Field("download_bulk_results", json_schema_extra={"ui:hidden": True})
    filter_results: list[Literal["deliverable", "undeliverable", "accept_all", "unknown"]] = Field(
        default_factory=lambda: ["deliverable", "undeliverable", "accept_all", "unknown"], min_length=1, max_length=4)


class GetCreditBalance(_Input):
    """Read the authenticated account's remaining verification credits."""
    operation: Literal["get_credit_balance"] = Field("get_credit_balance", json_schema_extra={"ui:hidden": True})


BouncifyConfig = Annotated[Union[VerifyEmail, CreateBulkJob, GetBulkJob, StartBulkJob,
    DeleteBulkJob, DownloadBulkResults, GetCreditBalance], Field(discriminator="operation")]


class BouncifyFullConfig(NodeConfig[BouncifyConfig, BouncifyAPIKeyCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class BouncifyNode(WorkflowNode):
    integration_type = "automation-bouncify"
    connection_evidence = ConnectionEvidence(noun="Bouncify credit balance", operation="get_credit_balance",
        proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BouncifyFullConfig

    async def execute(self, inputs):
        cfg, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Attach a Bouncify API key")
        method, path, body = "GET", "/info", None
        params = {"apikey": credential.api_key}
        if isinstance(cfg, VerifyEmail):
            path = "/verify"
            params.update(email=cfg.email, timeout=cfg.timeout)
        elif isinstance(cfg, CreateBulkJob):
            method, path = "POST", "/bulk"
            body = {"emails": [row.model_dump() for row in cfg.emails],
                "auto_verify": "true" if cfg.auto_verify else "false"}
        elif isinstance(cfg, DownloadBulkResults):
            method, path = "POST", "/download"
            params["jobId"] = cfg.job_id
            body = {"filterResult": cfg.filter_results}
        elif isinstance(cfg, _Job):
            path = "/bulk/" + cfg.job_id
            if isinstance(cfg, StartBulkJob):
                method, body = "PATCH", {"action": "start"}
            elif isinstance(cfg, DeleteBulkJob):
                method = "DELETE"
        try:
            async with guarded_async_client(timeout=190, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Accept": "text/plain" if isinstance(cfg, DownloadBulkResults) else "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            # Query credentials must never escape through httpx's URL-bearing errors.
            raise ValueError("Bouncify request failed; inspect the job before retrying a write") from None
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        data = None
        if mime == "application/json":
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Bouncify returned invalid JSON") from None
        if response.status_code != 200 or isinstance(data, dict) and data.get("success") is False:
            message = (data.get("message") or data.get("result") or data.get("error")) if isinstance(data, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(message if isinstance(message, str) else f"Bouncify returned HTTP {response.status_code}", credential.api_key)}
        if isinstance(cfg, DownloadBulkResults):
            if mime not in {"text/plain", "text/csv"} or not response.content:
                raise ValueError("Bouncify did not return CSV results")
            return {"status": "success", "job_id": cfg.job_id,
                "file": BinaryOutput(response.content, "text/csv", f"bouncify-{cfg.job_id}.csv")}
        if not isinstance(data, dict) or data.get("success") is not True:
            raise ValueError("Bouncify did not confirm success")
        if isinstance(cfg, GetCreditBalance):
            credits = data.get("credits_info", {}).get("credits_remaining") if isinstance(data.get("credits_info"), dict) else None
            if type(credits) is not int or credits < 0:
                raise ValueError("Bouncify omitted the account credit balance")
        elif isinstance(cfg, VerifyEmail):
            if not isinstance(data.get("result"), str) or not isinstance(data.get("email"), str):
                raise ValueError("Bouncify omitted the email verification result")
        else:
            if not isinstance(data.get("job_id"), str) or not data["job_id"]:
                raise ValueError("Bouncify omitted the job ID")
            if isinstance(cfg, _Job) and data["job_id"] != cfg.job_id:
                raise ValueError("Bouncify returned a different job")
            if isinstance(cfg, GetBulkJob) and not isinstance(data.get("status"), str):
                raise ValueError("Bouncify omitted the job status")
        result = {"status": "success", "data": _redact(data, credential.api_key)}
        if isinstance(cfg, DeleteBulkJob):
            result.update(deletion_acknowledged=True, deletion_completed=False)
        return result
