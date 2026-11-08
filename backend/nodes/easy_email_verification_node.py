"""Easy Email Verification API v1.2.0.

Contract: https://www.easyemailverification.com/openapi.json
The published API has eight operations; every one is exposed exactly once.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.easyemailverification.com/v1"


class EasyEmailVerificationAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Easy Email Verification API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.easyemailverification.com/apisettings",
            "x-credential-instructions": "Create an API key in API Settings and paste it here. Use a server API key, not a domain-restricted widget key. NoClick sends it in X-API-Key. The connection check reads your remaining credits without consuming any.",
        })
    credential_type: Literal["easy_email_verification_api_key"] = Field(
        "easy_email_verification_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste an API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerifyEmail(_Input):
    """Verify one address; unknown is inconclusive, not deliverable. May consume a credit."""
    operation: Literal["verify_email"] = "verify_email"
    email: str = Field(..., min_length=1, title="Email Address", description="Address to verify, including any plus tag.")


class VerifyBatch(_Input):
    """Verify up to 50 addresses; each conclusive result consumes a credit."""
    operation: Literal["verify_batch"] = "verify_batch"
    emails: list[str] = Field(..., min_length=1, max_length=50, title="Email Addresses")


class UploadBulkFile(_Input):
    """Start bulk verification by uploading a TXT or CSV list; consumes credits."""
    operation: Literal["upload_bulk_file"] = "upload_bulk_file"
    filename: str = Field("emails.txt", title="File Name", pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(txt|csv)$", max_length=128)
    file_content: str = Field(..., min_length=1, title="File Content",
        description="TXT or CSV content with one email address per line. Maximum UTF-8 size is 16 MB.",
        json_schema_extra={"ui:widget": "textarea"})

    @field_validator("file_content")
    @classmethod
    def size(cls, value):
        if len(value.encode("utf-8")) > 16_000_000:
            raise ValueError("File exceeds 16 MB")
        return value


class ListBulkJobs(_Input):
    """List verification jobs belonging to the API key's account."""
    operation: Literal["list_bulk_jobs"] = "list_bulk_jobs"


class _Job(_Input):
    job_id: str = Field(..., min_length=1, max_length=256, title="Job ID",
        description="The list_id returned when the file was uploaded.", pattern=r"^[A-Za-z0-9_-]+$")


class GetBulkJob(_Job):
    """Read a bulk job's status, progress and available counters."""
    operation: Literal["get_bulk_job"] = "get_bulk_job"


class DownloadBulkResults(_Job):
    """Download a completed job's CSV results as a file. Results expire after 30 days."""
    operation: Literal["download_bulk_results"] = "download_bulk_results"


class DeleteBulkJob(_Job):
    """Permanently delete a bulk job and its results."""
    operation: Literal["delete_bulk_job"] = "delete_bulk_job"


class GetCredits(_Input):
    """Read account credits without consuming any credits."""
    operation: Literal["get_credits"] = "get_credits"


Operation = Annotated[Union[VerifyEmail, VerifyBatch, UploadBulkFile, ListBulkJobs,
    GetBulkJob, DownloadBulkResults, DeleteBulkJob, GetCredits], Field(discriminator="operation")]


class EasyEmailVerificationConfig(NodeConfig[Operation, EasyEmailVerificationAPIKeyCredential]):
    pass


def _verification(body):
    if not isinstance(body, dict) or body.get("success") is not True:
        raise ValueError("Easy Email Verification did not confirm verification")
    if body.get("result") not in {"valid", "invalid", "unknown"} or not isinstance(body.get("safe_to_send"), bool):
        raise ValueError("Unexpected Easy Email Verification result")
    # Preserve the provider's result and reason; success is processing, not deliverability.
    return body


class EasyEmailVerificationNode(WorkflowNode):
    integration_type = "automation-easy-email-verification"
    connection_evidence = ConnectionEvidence(operation="get_credits", noun="account credit balance")

    @classmethod
    def get_config_model(cls):
        return EasyEmailVerificationConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Easy Email Verification API key")
        config = self.config.config
        credential = self.config.credentials
        action = config.operation
        method, path, kwargs = "GET", "/credits", {}
        if action == "verify_email":
            path, kwargs = "/verify", {"params": {"email": config.email}}
        elif action == "verify_batch":
            method, path, kwargs = "POST", "/verify", {"json": {"emails": config.emails}}
        elif action == "upload_bulk_file":
            method, path = "POST", "/bulk/upload"
            mime = "text/csv" if config.filename.endswith(".csv") else "text/plain"
            kwargs = {"files": {"file": (config.filename, config.file_content.encode("utf-8"), mime)}}
        elif action == "list_bulk_jobs":
            path = "/bulk/status"
        elif action == "get_bulk_job":
            path = "/bulk/status/" + quote(config.job_id, safe="")
        elif action == "download_bulk_results":
            path = "/bulk/download/" + quote(config.job_id, safe="")
        elif action == "delete_bulk_job":
            method, path = "DELETE", "/bulk/" + quote(config.job_id, safe="")
        headers = {"X-API-Key": credential.api_key,
            "Accept": "text/plain" if action == "download_bulk_results" else "application/json"}
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, headers=headers, **kwargs)
        except httpx.RequestError:
            raise ValueError("Easy Email Verification could not be reached; check job status before retrying a write") from None
        if response.status_code != 200:
            message = "Easy Email Verification request failed"
            try:
                error = response.json()
                if isinstance(error, list) and error:
                    error = error[0]
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(credential.api_key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "success": False, "http_status": response.status_code,
                "message": message, "operation": action}
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if action == "download_bulk_results":
            if mime not in {"text/plain", "text/csv", "application/octet-stream"}:
                raise ValueError("Expected CSV results from Easy Email Verification")
            return {"status": "success", "operation": action,
                "file": BinaryOutput(response.content, "text/csv", "results.csv")}
        if mime != "application/json":
            raise ValueError("Expected JSON from Easy Email Verification")
        body = response.json()
        if action == "verify_email":
            _verification(body)
        elif action == "verify_batch":
            if not isinstance(body, list) or len(body) != len(config.emails):
                raise ValueError("Expected one verification result per address")
            for result in body:
                _verification(result)
        else:
            if not isinstance(body, dict) or body.get("status") == "error" or body.get("success") is False:
                raise ValueError("Easy Email Verification did not confirm the request")
            if action == "get_credits":
                if body.get("success") is not True or any(type(body.get(k)) is not int for k in
                    ("credits_remaining", "subscription_remaining", "persistent_remaining", "subscription_credits")):
                    raise ValueError("Unexpected Easy Email Verification credit balance")
            elif action == "list_bulk_jobs":
                if body.get("status") != "ok" or not isinstance(body.get("lists"), list):
                    raise ValueError("Unexpected Easy Email Verification job list")
            elif action == "upload_bulk_file" and (body.get("status") != "accepted" or not body.get("list_id")):
                raise ValueError("Easy Email Verification did not accept the upload")
            elif action == "delete_bulk_job" and (body.get("status") != "deleted" or body.get("list_id") != config.job_id):
                raise ValueError("Easy Email Verification did not confirm job deletion")
            elif action == "get_bulk_job" and (body.get("list_id") != config.job_id or "progress" not in body):
                raise ValueError("Unexpected Easy Email Verification job status")
        return {"status": "success", "operation": action, "data": body}
