"""DigiCert Content Trust Manager, pinned published REST API v1.0.

Each operation sends one request. Lists return one page and retain provider
pagination. API keys use X-API-Key; CSC OAuth/signing endpoints are separate.
Reference: https://dev.digicert.com/content-trust-api/api-reference.html
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class DigicertAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Digicert API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dev.digicert.com/content-trust-api/api-reference.html",
            "x-credential-instructions": "In DigiCert ONE, open Admin Profile > API Tokens to create an API token, or Account Manager > Access > Service User to create a service user token (recommended). Paste the token ID and select your instance. Grant Content Trust Manager audit-log read access for connection verification and the permissions needed by your workflow operations.",
        },
    )
    credential_type: Literal["digicert_api_key"] = Field(
        "digicert_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )
    host: Literal[
        "one.digicert.com", "demo.one.digicert.com", "one.digicert.co.jp"
    ] = Field("one.digicert.com", title="DigiCert ONE instance")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token ID without header text or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator(
        "id",
        "validation_id",
        "user_id",
        "name",
        "account_id",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def path_values(cls, value, info):
        if (
            info.field_name in {"id", "validation_id", "user_id", "name", "account_id"}
            and value is not None
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 512
                or any(c in value for c in "/\\?#")
                or any(ord(c) < 32 for c in value)
                or value in {".", ".."}
            ):
                raise ValueError("Use a single DigiCert identifier")
        return value


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1, title="Account ID")
    name: str | None = None


class ListAuditLogs(_Input):
    """List audit logs using cursor pagination."""

    operation: Literal["list_audit_logs"] = Field(
        "list_audit_logs", json_schema_extra={"ui:hidden": True}
    )
    limit: int = Field(50, ge=1, le=1000)
    cursor_timestamp: str | None = Field(
        None,
        description="Use pagination.next_cursor_timestamp from the preceding page.",
    )
    cursor_id: str | None = Field(
        None, description="Use pagination.next_cursor_id from the preceding page."
    )
    direction: Literal["NEXT", "PREVIOUS"] = "NEXT"
    sort_order: Literal["ASC", "DESC"] = "DESC"
    account_id: str | None = None
    user_id: str | None = None
    resource_id: str | None = None
    start_date: str | None = Field(None, description="ISO 8601 date and time")
    end_date: str | None = Field(None, description="ISO 8601 date and time")
    status: Literal["SUCCESS", "FAILURE"] | None = None


class GetAuditLog(_Input):
    """Get audit log by ID."""

    operation: Literal["get_audit_log"] = Field(
        "get_audit_log", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., title="Audit log ID")
    account_id: str | None = None


class VerifyAuditLog(_Input):
    """Verify audit log."""

    operation: Literal["verify_audit_log"] = Field(
        "verify_audit_log", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., title="Audit log ID")


class ListValidations(_Input):
    """List validations, one offset page at a time."""

    operation: Literal["list_validations"] = Field(
        "list_validations", json_schema_extra={"ui:hidden": True}
    )
    account_id: str = Field(..., title="Account ID")

    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=100)
    email: str | None = None


class GetValidation(_Input):
    """Get validation by ID."""

    operation: Literal["get_validation"] = Field(
        "get_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: str = Field(..., title="Validation ID")
    account_id: str = Field(..., title="Account ID")


class GetUserValidations(_Input):
    """Get user validation details."""

    operation: Literal["get_user_validations"] = Field(
        "get_user_validations", json_schema_extra={"ui:hidden": True}
    )
    user_id: str = Field(..., title="User ID")
    account_id: str = Field(..., title="Account ID")


class RejectValidation(_Input):
    """Reject validation."""

    operation: Literal["reject_validation"] = Field(
        "reject_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: str = Field(..., title="Validation ID")
    account_id: str = Field(..., title="Account ID")
    reason: Literal[
        "TECH_PHOTO",
        "TECH_HOLOGRAM",
        "BAD_PHOTO_QUALITY",
        "ID_NOT_SUPPORTED",
        "USER_ID",
        "ID_DAMAGED",
        "ID_OTHER",
        "USER_WRONG_PERSON",
        "PHOTO_OTHER",
        "OTHER_ERROR",
        "WARNING_SOCIAL_ENGINEERING",
        "WARNING_ID_MANIPULATION",
        "FACE_COMPARISON_UNMATCHED",
        "WARNING_FAKE_ID",
        "WARNING_PHOTO",
        "WARNING_DESCRIPTION",
        "WARNING_USER_UNDERAGE",
        "WARNING_INCONSISTENT_DATA",
        "DOCUMENT_TAMPERED",
        "WARNING_FAKED_MANIPULATED_ID",
        "WARNING_FRAUD_OTHER",
        "WARNING_WRONG_CHECKSUM",
        "WARNING_IDENTITY_THEFT",
        "SECURITY_FEATURE_IDENTITY_FAKED",
        "LIVENESS_DETECTION_FAILED",
        "SECURITY_FEATURE_DIGITAL_IMAGE\\",
        "FRONT_DOCUMENT_DIGITAL_IMAGE",
        "BACK_DOCUMENT_DIGITAL_IMAGE",
        "FACE_COMPARISON_DIGITAL_IMAGE",
        "LIVENESS_LEFT_DIGITAL_IMAGE",
        "LIVENESS_RIGHT_DIGITAL_IMAGE",
    ] = Field(..., title="Rejection reason")


class RevalidateValidation(_Input):
    """Re-initiate validation."""

    operation: Literal["revalidate_validation"] = Field(
        "revalidate_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: str = Field(..., title="Validation ID")
    account_id: str = Field(..., title="Account ID")


class CancelValidation(_Input):
    """Cancel validation."""

    operation: Literal["cancel_validation"] = Field(
        "cancel_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: UUID = Field(..., title="Validation ID")
    account_id: UUID = Field(..., title="Account ID")


class RetryValidation(_Input):
    """Retries to create user and his first credential."""

    operation: Literal["retry_validation"] = Field(
        "retry_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: str = Field(..., title="Validation ID")


class EnableValidation(_Input):
    """Enable validation."""

    operation: Literal["enable_validation"] = Field(
        "enable_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: str = Field(..., title="Validation ID")
    account: Account = Field(
        ..., description="DigiCert ONE account owning this validation"
    )
    notes: str | None = Field(None, max_length=4000)


class DisableValidation(_Input):
    """Disable validation."""

    operation: Literal["disable_validation"] = Field(
        "disable_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: str = Field(..., title="Validation ID")
    account: Account = Field(
        ..., description="DigiCert ONE account owning this validation"
    )
    notes: str | None = Field(None, max_length=4000)


class InvalidateValidation(_Input):
    """Invalidate validation."""

    operation: Literal["invalidate_validation"] = Field(
        "invalidate_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: str = Field(..., title="Validation ID")
    account: Account = Field(
        ..., description="DigiCert ONE account owning this validation"
    )
    reason_code: Literal[
        "KEY_COMPROMISE", "AFFILIATION_CHANGED", "SUPERSEDED", "CESSATION_OF_OPERATION"
    ] = Field(..., title="Reason code")


class ApproveSelfenrolledUserValidation(_Input):
    """Approve self-enrolled user validation."""

    operation: Literal["approve_selfenrolled_user_validation"] = Field(
        "approve_selfenrolled_user_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: str = Field(..., title="Validation ID")


class RejectSelfenrolledUserValidation(_Input):
    """Reject self-enrolled user validation."""

    operation: Literal["reject_selfenrolled_user_validation"] = Field(
        "reject_selfenrolled_user_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: UUID = Field(..., title="Validation ID")
    reason: Literal[
        "VALIDATION_IN_PROCESS", "VALIDATION_COMPLETED", "UNDEFINED"
    ] = Field(..., title="Rejection reason")


class ApproveOrganizationValidation(_Input):
    """Approve organization details for a validation."""

    operation: Literal["approve_organization_validation"] = Field(
        "approve_organization_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: UUID = Field(..., title="Validation ID")


class RejectOrganizationValidation(_Input):
    """Reject organization details for a validation."""

    operation: Literal["reject_organization_validation"] = Field(
        "reject_organization_validation", json_schema_extra={"ui:hidden": True}
    )
    validation_id: UUID = Field(..., title="Validation ID")
    reason: Literal[
        "TECH_PHOTO",
        "TECH_HOLOGRAM",
        "BAD_PHOTO_QUALITY",
        "ID_NOT_SUPPORTED",
        "USER_ID",
        "ID_DAMAGED",
        "ID_OTHER",
        "USER_WRONG_PERSON",
        "PHOTO_OTHER",
        "OTHER_ERROR",
        "WARNING_SOCIAL_ENGINEERING",
        "WARNING_ID_MANIPULATION",
        "FACE_COMPARISON_UNMATCHED",
        "WARNING_FAKE_ID",
        "WARNING_PHOTO",
        "WARNING_DESCRIPTION",
        "WARNING_USER_UNDERAGE",
        "WARNING_INCONSISTENT_DATA",
        "DOCUMENT_TAMPERED",
        "WARNING_FAKED_MANIPULATED_ID",
        "WARNING_FRAUD_OTHER",
        "WARNING_WRONG_CHECKSUM",
        "WARNING_IDENTITY_THEFT",
        "SECURITY_FEATURE_IDENTITY_FAKED",
        "LIVENESS_DETECTION_FAILED",
        "SECURITY_FEATURE_DIGITAL_IMAGE\\",
        "FRONT_DOCUMENT_DIGITAL_IMAGE",
        "BACK_DOCUMENT_DIGITAL_IMAGE",
        "FACE_COMPARISON_DIGITAL_IMAGE",
        "LIVENESS_LEFT_DIGITAL_IMAGE",
        "LIVENESS_RIGHT_DIGITAL_IMAGE",
    ] = Field(..., title="Rejection reason")


class GetCredential(_Input):
    """Returns credential details by credential name."""

    operation: Literal["get_credential"] = Field(
        "get_credential", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., title="Credential name")
    user_id: str | None = None


class CancelCredential(_Input):
    """Cancel credential by credential name."""

    operation: Literal["cancel_credential"] = Field(
        "cancel_credential", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., title="Credential name")
    user_id: str | None = None
    notes: str = Field(..., min_length=1, max_length=4000, title="Cancellation notes")


class RevokeCredential(_Input):
    """Revoke credentials."""

    operation: Literal["revoke_credential"] = Field(
        "revoke_credential", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., title="Credential name")
    user_id: str = Field(..., title="Signer user ID")
    reason: Literal[
        "KEY_COMPROMISE", "AFFILIATION_CHANGED", "SUPERSEDED", "CESSATION_OF_OPERATION"
    ] = Field(..., title="Revocation reason")


DigicertOperation = Annotated[
    Union[
        ListAuditLogs,
        GetAuditLog,
        VerifyAuditLog,
        ListValidations,
        GetValidation,
        GetUserValidations,
        RejectValidation,
        RevalidateValidation,
        CancelValidation,
        RetryValidation,
        EnableValidation,
        DisableValidation,
        InvalidateValidation,
        ApproveSelfenrolledUserValidation,
        RejectSelfenrolledUserValidation,
        ApproveOrganizationValidation,
        RejectOrganizationValidation,
        GetCredential,
        CancelCredential,
        RevokeCredential,
    ],
    Field(discriminator="operation"),
]


class DigicertConfig(NodeConfig[DigicertOperation, DigicertAPIKeyCredential]):
    pass


# method, contract path, query fields, JSON body fields, path-field aliases
ROUTES = {
    "list_audit_logs": (
        "GET",
        "/api/v1/audit-log/cursor",
        (
            "limit",
            "cursor_timestamp",
            "cursor_id",
            "direction",
            "sort_order",
            "account_id",
            "user_id",
            "resource_id",
            "start_date",
            "end_date",
            "status",
        ),
        (),
        {},
    ),
    "get_audit_log": ("GET", "/api/v1/audit-log/{id}", ("account_id",), (), {}),
    "verify_audit_log": ("GET", "/api/v1/audit-log/{id}/verify", (), (), {}),
    "list_validations": (
        "GET",
        "/api/v1/validation",
        ("account_id", "offset", "limit", "email"),
        (),
        {},
    ),
    "get_validation": (
        "GET",
        "/api/v1/validation/{validationId}",
        ("account_id",),
        (),
        {"validationId": "validation_id"},
    ),
    "get_user_validations": (
        "GET",
        "/api/v1/validation/user/{userId}",
        ("account_id",),
        (),
        {"userId": "user_id"},
    ),
    "reject_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/reject",
        ("account_id",),
        ("reason",),
        {"validationId": "validation_id"},
    ),
    "revalidate_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/revalidate",
        ("account_id",),
        (),
        {"validationId": "validation_id"},
    ),
    "cancel_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/cancel",
        ("account_id",),
        (),
        {"validationId": "validation_id"},
    ),
    "retry_validation": (
        "POST",
        "/api/v1/validation/{validationId}/retry",
        (),
        (),
        {"validationId": "validation_id"},
    ),
    "enable_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/enable",
        (),
        ("account", "notes"),
        {"validationId": "validation_id"},
    ),
    "disable_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/disable",
        (),
        ("account", "notes"),
        {"validationId": "validation_id"},
    ),
    "invalidate_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/invalidate",
        (),
        ("account", "reason_code"),
        {"validationId": "validation_id"},
    ),
    "approve_selfenrolled_user_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/approve-selfenrolled-user",
        (),
        (),
        {"validationId": "validation_id"},
    ),
    "reject_selfenrolled_user_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/reject-selfenrolled-user",
        (),
        ("reason",),
        {"validationId": "validation_id"},
    ),
    "approve_organization_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/approve-organization",
        (),
        (),
        {"validationId": "validation_id"},
    ),
    "reject_organization_validation": (
        "PUT",
        "/api/v1/validation/{validationId}/reject-organization",
        (),
        ("reason",),
        {"validationId": "validation_id"},
    ),
    "get_credential": ("GET", "/api/v2/credential/{name}", ("user_id",), (), {}),
    "cancel_credential": (
        "PUT",
        "/api/v2/credential/{name}/cancel",
        ("user_id",),
        ("notes",),
        {},
    ),
    "revoke_credential": (
        "PUT",
        "/api/v1/credential/{name}/revoke",
        ("user_id",),
        ("reason",),
        {},
    ),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class DigicertNode(WorkflowNode):
    integration_type = "automation-digicert"
    connection_evidence = ConnectionEvidence(
        noun="Content Trust audit logs",
        operation="list_audit_logs",
        label_keys=("action", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return DigicertConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a DigiCert API key")
        op = self.config.config
        credential = self.config.credentials
        method, route, query_fields, body_fields, path_fields = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, mode="json")
        for key in ("id", "name", "validationId", "userId"):
            if "{" + key + "}" in route:
                route = route.replace(
                    "{" + key + "}", quote(values[path_fields.get(key, key)], safe="")
                )
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        url = "https://" + credential.host + "/documentmanager" + route
        try:
            async with guarded_async_client(
                timeout=30.0, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers={
                        "X-API-Key": credential.api_key,
                        "Accept": "application/json",
                    },
                    params=params,
                    **({"json": body} if body_fields else {}),
                )
        except httpx.RequestError:
            raise ValueError(
                "DigiCert request did not complete; verify the outcome before retrying a write"
            ) from None
        try:
            data = response.json() if response.content else None
        except ValueError:
            raise ValueError(
                "DigiCert returned an unexpected non-JSON response"
            ) from None
        if not 200 <= response.status_code < 300 or (
            isinstance(data, dict) and (data.get("error") or data.get("errors"))
        ):
            message = (
                (
                    data.get("error_description")
                    or data.get("message")
                    or data.get("error")
                    or data.get("errors")
                )
                if isinstance(data, dict)
                else None
            )
            output = {
                "status": "error",
                "status_code": response.status_code,
                "message": str(message or "DigiCert request rejected"),
                "data": data,
            }
        else:
            output = {
                "status": "success",
                "status_code": response.status_code,
                "data": data,
            }
        output = _redact(output, credential.api_key)
        await self.emit(output)
        return output
