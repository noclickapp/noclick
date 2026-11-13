"""Emailvalidation v1: all seven published operations, using header API-key auth.

Contract: https://emailvalidation.io/docs/openapi.yaml (version 1).
Single checks and bulk submissions can consume quota; no automatic retries.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.emailvalidation.io"


class EmailvalidationAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Emailvalidation API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.emailvalidation.io/",
            "x-credential-instructions": "Copy your API key from the Emailvalidation dashboard. NoClick sends it in the apikey header. Connection checks read your account status and quota without consuming validation credits.",
        })
    credential_type: Literal["emailvalidation_api_key"] = Field("emailvalidation_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ValidateEmail(_Input):
    """Validate one address; definitive results consume one request of quota."""
    operation: Literal["validate_email"] = Field("validate_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, description="Email address to validate.")
    catch_all: Literal["0", "1"] = Field("0", description="1 enables paid-plan catch-all detection; 0 leaves it disabled.")
    timeout: int = Field(30, ge=3, le=60, description="Provider check timeout in seconds.")


class CreateBulkJob(_Input):
    """Submit addresses for asynchronous verification; charged when accepted."""
    operation: Literal["create_bulk_job"] = Field("create_bulk_job", json_schema_extra={"ui:hidden": True})
    emails: list[Annotated[str, Field(max_length=1000)]] = Field(..., min_length=1, max_length=100000,
        description="Addresses in input order. Invalid addresses and empty strings are allowed and reported as invalid_format. Maximum combined size 25 MB; sandbox keys allow 1,000 rows.")
    webhook_url: str | None = Field(None, max_length=2048,
        description="Optional public HTTPS callback URL. Save the returned webhook_secret to verify webhook signatures.")
    catch_all: StrictBool = Field(False, description="Enable paid-plan catch-all detection for the list.")

    @field_validator("webhook_url")
    @classmethod
    def webhook(cls, value):
        if value is not None:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError("Use a public HTTPS webhook URL without credentials")
        return value

    @model_validator(mode="after")
    def size(self):
        if sum(len(item.encode("utf-8")) for item in self.emails) > 25_600 * 1024:
            raise ValueError("The combined address strings must not exceed 25 MB")
        return self


class ListBulkJobs(_Input):
    """Read one page; pass next_before to the following request."""
    operation: Literal["list_bulk_jobs"] = Field("list_bulk_jobs", json_schema_extra={"ui:hidden": True})
    limit: int = Field(25, ge=1, le=100)
    before: str | None = Field(None, pattern=r"^[0-9]{1,20}$", description="Last job ID from the previous page.")


class _Job(_Input):
    job_id: str = Field(..., pattern=r"^[0-9]{1,20}$", description="Bulk job ID returned by submission or listing.")


class GetBulkJob(_Job):
    """Read status and progress; poll about once per minute until completed."""
    operation: Literal["get_bulk_job"] = Field("get_bulk_job", json_schema_extra={"ui:hidden": True})


class DeleteBulkJob(_Job):
    """Permanently delete a job, its input list and its stored results."""
    operation: Literal["delete_bulk_job"] = Field("delete_bulk_job", json_schema_extra={"ui:hidden": True})


class GetBulkJobResults(_Job):
    """Download completed results as JSON or a CSV file. Pending jobs return 409."""
    operation: Literal["get_bulk_job_results"] = Field("get_bulk_job_results", json_schema_extra={"ui:hidden": True})
    format: Literal["json", "csv"] = Field("json", description="JSON preserves per-row results; CSV returns a file.")


class GetAccountStatus(_Input):
    """Read the authenticated account ID, plan and quota without consuming credits."""
    operation: Literal["get_account_status"] = Field("get_account_status", json_schema_extra={"ui:hidden": True})


# emailvalidation.io's own MCP server: agents get its tools through a person's emailvalidation.io sign-in.
EmailvalidationMcpCredential = mcp_credential("emailvalidation", "https://api.emailvalidation.io/mcp", app="emailvalidation.io")
EmailvalidationCredential = Union[EmailvalidationAPIKeyCredential, EmailvalidationMcpCredential]


EmailvalidationConfig = Annotated[Union[ValidateEmail, CreateBulkJob, ListBulkJobs, GetBulkJob,
    DeleteBulkJob, GetBulkJobResults, GetAccountStatus], Field(discriminator="operation")]


class EmailvalidationFullConfig(NodeConfig[EmailvalidationConfig, EmailvalidationCredential]):
    pass


class EmailvalidationNode(WorkflowNode):
    integration_type = "automation-emailvalidation"
    credential_provider_labels = {"emailvalidation": "emailvalidation.io Account"}
    connection_evidence = ConnectionEvidence(noun="Emailvalidation account", identity_operation="get_account_status",
        identity_keys=("account_id_str", "account_id"))

    @classmethod
    def get_config_model(cls):
        return EmailvalidationFullConfig

    async def execute(self, inputs):
        cfg = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Attach an Emailvalidation API key")
        method, path, params, body = "GET", "/v1/status", {}, None
        csv = isinstance(cfg, GetBulkJobResults) and cfg.format == "csv"
        if isinstance(cfg, ValidateEmail):
            path = "/v1/info"
            params = cfg.model_dump(exclude={"operation"})
        elif isinstance(cfg, CreateBulkJob):
            method, path = "POST", "/v1/bulk"
            body = cfg.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(cfg, ListBulkJobs):
            path = "/v1/bulk"
            params = cfg.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(cfg, _Job):
            path = "/v1/bulk/" + cfg.job_id
            if isinstance(cfg, DeleteBulkJob):
                method = "DELETE"
            elif isinstance(cfg, GetBulkJobResults):
                path += "/results"
                params = {"format": cfg.format}
        # Timeout is longer than the provider's longest single-address check.
        async with guarded_async_client(timeout=70, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"apikey": credential.api_key, "Accept": "text/csv" if csv else "application/json"},
                **({"json": body} if body is not None else {}))
        expected_status = 201 if isinstance(cfg, CreateBulkJob) else 200
        if response.status_code != expected_status:
            try:
                error_body = response.json()
                message = error_body.get("message") or error_body.get("error", {}).get("message")
            except (ValueError, AttributeError):
                message = None
            message = message if isinstance(message, str) else f"Emailvalidation returned HTTP {response.status_code}"
            return {"status": "error", "http_status": response.status_code,
                "error": message.replace(credential.api_key, "[redacted]")}
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if csv:
            if mime != "text/csv":
                raise ValueError("Emailvalidation did not return CSV results")
            return {"status": "success", "job_id": cfg.job_id,
                "file": BinaryOutput(data=response.content, content_type="text/csv", filename=f"emailvalidation-{cfg.job_id}.csv")}
        if mime != "application/json":
            raise ValueError("Emailvalidation did not return JSON")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Emailvalidation returned an unexpected response")
        # Bulk job objects legitimately have error: null or a failed-job reason.
        if isinstance(data.get("error"), dict) or (data.get("message") and "job_id" not in data):
            message = data.get("message") or data["error"].get("message") or "Emailvalidation rejected the request"
            return {"status": "error", "error": str(message).replace(credential.api_key, "[redacted]")}
        if isinstance(cfg, DeleteBulkJob) and (data.get("deleted") is not True or data.get("job_id") != cfg.job_id):
            raise ValueError("Emailvalidation did not confirm deletion of the selected job")
        result = {"status": "success", "data": data}
        if isinstance(cfg, ListBulkJobs):
            rows = data.get("data")
            if not isinstance(rows, list) or type(data.get("has_more")) is not bool:
                raise ValueError("Emailvalidation returned an invalid bulk-job page")
            if data["has_more"] and (not rows or not isinstance(rows[-1].get("job_id"), str)):
                raise ValueError("Emailvalidation omitted the next bulk-job cursor")
            result["next_before"] = rows[-1]["job_id"] if data["has_more"] else None
        return result
