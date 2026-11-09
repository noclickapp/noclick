"""True List email verification and stored results (published API v0.3.0)."""
from __future__ import annotations

import csv
import io
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.truelist.io"


class TrueListAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="True List API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.truelist.io/settings/api-keys",
        "x-credential-instructions": "Generate an API key in True List account settings, then paste it here without the Bearer prefix. NoClick reads your account to check the connection without verifying emails.",
    })
    credential_type: Literal["true_list_api_token"] = Field("true_list_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a header prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetAccount(_Config):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})


class _Verification(_Config):
    validation_strategy: Literal["accurate", "fast", "thorough", "enhanced"] = "accurate"
    timeout: int = Field(30, ge=1, le=30, description="Seconds per address; timed-out results are unknown and not billed.")


class VerifyEmail(_Verification):
    operation: Literal["verify_email"] = Field("verify_email", title="Verify Email", description="Run complete verification, including SMTP. May consume verification credits.", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, description="One email address to verify.")

    @field_validator("email")
    @classmethod
    def single(cls, value):
        if any(c.isspace() for c in value):
            raise ValueError("Enter one address without whitespace")
        return value


class VerifyEmails(_Verification):
    operation: Literal["verify_emails"] = Field("verify_emails", title="Verify Up to Three Emails", description="Verify two or three addresses in one request, including SMTP. May consume verification credits.", json_schema_extra={"ui:hidden": True})
    emails: list[str] = Field(..., min_length=2, max_length=3)

    @field_validator("emails")
    @classmethod
    def addresses(cls, values):
        for value in values:
            if not value or any(c.isspace() for c in value):
                raise ValueError("Each item must be one nonempty address without whitespace")
        return values


class CheckEmail(VerifyEmail):
    operation: Literal["check_email"] = Field("check_email", title="Check Email Without SMTP", description="Fast syntax, MX, disposable and role checks; does not confirm mailbox deliverability.", json_schema_extra={"ui:hidden": True})


class CreateBatch(_Config):
    operation: Literal["create_batch"] = Field("create_batch", title="Create Verification Batch", description="Upload CSV rows for background verification. Poll Get Batch or supply a completion webhook. May consume verification credits.", json_schema_extra={"ui:hidden": True})
    rows: list[list[str]] = Field(..., min_length=2, description="At least two rows, each containing an email address; optional extra columns are preserved in annotated results.")
    filename: str = Field("truelist.csv", description="CSV filename, used as the batch name.")
    uuid: UUID | None = Field(None, description="Optional caller-assigned batch UUID.")
    webhook_url: str | None = Field(None, description="True List sends a completion POST with batch_id to this URL.")
    validation_strategy: Literal["accurate", "fast"] = "accurate"

    @field_validator("rows")
    @classmethod
    def email_rows(cls, rows):
        if any(not row or not any("@" in cell for cell in row) for row in rows):
            raise ValueError("Every CSV row must contain an email address")
        return rows

    @field_validator("filename")
    @classmethod
    def csv_filename(cls, value):
        if any(c in value for c in '/\\\r\n"') or not value.lower().endswith(".csv"):
            raise ValueError("Use a CSV filename without path separators")
        return value


class ListBatches(_Config):
    operation: Literal["list_batches"] = Field("list_batches", title="List Batches", json_schema_extra={"ui:hidden": True})


class _Batch(_Config):
    uuid: UUID = Field(..., description="Batch UUID returned by Create Batch or List Batches.")


class GetBatch(_Batch):
    operation: Literal["get_batch"] = Field("get_batch", title="Get Batch", description="Read progress, counts and CSV result URLs. Counts are final only when completed.", json_schema_extra={"ui:hidden": True})


class DeleteBatch(_Batch):
    operation: Literal["delete_batch"] = Field("delete_batch", title="Delete Batch", description="Delete a completed batch; the API rejects unfinished batches.", json_schema_extra={"ui:hidden": True})


class ListResults(_Config):
    operation: Literal["list_results"] = Field("list_results", title="List Email Results", json_schema_extra={"ui:hidden": True})
    batch_uuid: str | None = Field(None, description="Batch UUID; use none for results outside any batch.")
    email_state: Literal["ok", "risky", "invalid", "email_invalid", "unknown"] | None = None
    email_sub_state: Literal["email_ok", "accept_all", "is_disposable", "is_role", "failed_mx_check", "failed_smtp_check", "failed_no_mailbox", "failed_greylisted", "failed_syntax_check", "unknown_error", "timed_out"] | None = None
    email_address: str | None = Field(None, description="Return addresses starting with this value.")
    page: int = Field(1, ge=1)
    per_page: int = Field(10, ge=1, le=100, description="One page per execution; increment page to fetch subsequent results.")


class GetResult(_Config):
    operation: Literal["get_result"] = Field("get_result", title="Get Email Result", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description="Stored result ID returned by verification or List Email Results.")


TrueListConfig = Annotated[Union[GetAccount, VerifyEmail, VerifyEmails, CheckEmail, CreateBatch,
    ListBatches, GetBatch, DeleteBatch, ListResults, GetResult], Field(discriminator="operation")]


class TrueListFullConfig(NodeConfig[TrueListConfig, TrueListAPITokenCredential]):
    pass


ROUTES = {
    "get_account": ("GET", "/me"),
    "verify_email": ("POST", "/api/v1/verify_inline"),
    "verify_emails": ("POST", "/api/v1/verify_inline"),
    "check_email": ("POST", "/api/v1/verify_inline"),
    "create_batch": ("POST", "/api/v1/batches"),
    "list_batches": ("GET", "/api/v1/batches"),
    "get_batch": ("GET", "/api/v1/batches/{uuid}"),
    "delete_batch": ("DELETE", "/api/v1/batches/{uuid}"),
    "list_results": ("GET", "/api/v1/email_addresses"),
    "get_result": ("GET", "/api/v1/email_addresses/{id}"),
}


def _check_credential_family(config_data):
    credentials = config_data.get("credentials")
    if isinstance(credentials, dict) and "credential_type" in credentials and credentials["credential_type"] != "true_list_api_token":
        raise ValueError("Attach a True List API token credential")


class TrueListNode(WorkflowNode):
    integration_type = "automation-true-list"
    connection_evidence = ConnectionEvidence(identity_operation="get_account", noun="True List account")

    @classmethod
    def get_config_model(cls):
        return TrueListFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _check_credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _check_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a True List API token")
        token = self.config.credentials.api_token
        op = self.config.config
        method, path = ROUTES[op.operation]
        params, kwargs = {}, {}
        if isinstance(op, _Verification):
            params = {"email": " ".join(op.emails) if isinstance(op, VerifyEmails) else op.email,
                "timeout": op.timeout, "validation_strategy": op.validation_strategy}
            if isinstance(op, CheckEmail):
                params["checks"] = ["syntax", "mx", "disposable", "role"]
        elif isinstance(op, CreateBatch):
            output = io.StringIO(newline="")
            csv.writer(output).writerows(op.rows)
            kwargs["files"] = {"file": (op.filename, output.getvalue().encode("utf-8"), "text/csv")}
            kwargs["data"] = op.model_dump(mode="json", exclude={"operation", "rows", "filename"}, exclude_none=True)
        elif isinstance(op, _Batch):
            path = path.replace("{uuid}", str(op.uuid))
        elif isinstance(op, GetResult):
            path = path.replace("{id}", str(op.id))
        elif isinstance(op, ListResults):
            params = op.model_dump(exclude={"operation"}, exclude_none=True)
        async with guarded_async_client(timeout=100, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if response.is_redirect:
            raise ValueError("True List redirected the request")
        if "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError(f"Expected JSON from True List (HTTP {response.status_code})")
        body = response.json()
        if isinstance(body, dict) and (body.get("error") or (body.get("errors") and not isinstance(op, GetAccount))):
            message = str(body.get("error") or body["errors"]).replace(token, "[redacted]")
            raise ValueError(f"HTTP {response.status_code}: {message}")
        if not response.is_success:
            raise ValueError(f"True List request failed (HTTP {response.status_code})")
        if not isinstance(body, list if isinstance(op, ListBatches) else dict):
            raise ValueError("Unexpected True List response shape")
        if isinstance(op, GetAccount):
            # /me returns the active token and API-key metadata alongside identity.
            body = {key: body[key] for key in ("email", "name", "uuid", "last_login_at", "time_zone") if key in body}
            if not (body.get("name") or body.get("email")):
                raise ValueError("True List did not return an account identity")
            return {"status": "success", "operation": op.operation, **body}
        return {"status": "success", "operation": op.operation, "data": body}
