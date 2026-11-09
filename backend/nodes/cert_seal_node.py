"""Cert Seal workspace certificate automation, pinned to the published v1 API.

Each operation makes one request. Pagination cursors stay opaque; sending is
asynchronous and writes are never automatically retried.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://services.certseal.com/api/v1"
CREDENTIAL_TYPE = "cert_seal_api_key"


class CertSealAPIKey(BaseModel):
    model_config = ConfigDict(title="Cert Seal API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.certseal.com",
            "x-credential-instructions": "In Cert Seal, open API Keys and create a key for your workspace. Paste the key here without the Bearer prefix. The key is shown only once and is bound to that workspace.",
        })
    credential_type: Literal["cert_seal_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    cursor: str | None = Field(None, description="Opaque pagination.nextCursor from the previous page; omit for the first page.")
    limit: int = Field(25, ge=1, le=100)


class _Batch(_Input):
    batch_id: str = Field(..., min_length=1, title="Batch ID")


class _Recipient(_Batch):
    recipient_id: str = Field(..., min_length=1, title="Recipient ID")


class RecipientFields(_Input):
    name: str | None = None
    email: str | None = Field(None, json_schema_extra={"format": "email"})
    certificate_id: str | None = Field(None, serialization_alias="certificateId", description="Optional unique certificate code. Treat existing codes as opaque strings.")
    issue_date: date | None = Field(None, serialization_alias="issueDate")
    expiry_date: date | None = Field(None, serialization_alias="expiryDate")
    data: dict[str, str] = Field(default_factory=dict, description="Template variable names mapped to text values.")


class RecipientInput(RecipientFields):
    send: bool = Field(False, description="Also queue email. Requires an email template on the batch and sending configured by Cert Seal.")


class ListBatches(_Page):
    operation: Literal["list_batches"] = Field("list_batches", title="List Batches", json_schema_extra={"ui:hidden": True})
    status: Literal["active", "archived", "all"] = "active"


class CreateBatch(_Input):
    operation: Literal["create_batch"] = Field("create_batch", title="Create Batch", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1)
    design_id: str = Field(..., min_length=1, serialization_alias="designId")
    description: str | None = None
    email_template_id: str | None = Field(None, serialization_alias="emailTemplateId")
    course_name: str | None = Field(None, serialization_alias="courseName")
    issuer_name: str | None = Field(None, serialization_alias="issuerName")


class GetBatch(_Batch):
    operation: Literal["get_batch"] = Field("get_batch", title="Get Batch", json_schema_extra={"ui:hidden": True})


class ArchiveBatch(_Batch):
    operation: Literal["archive_batch"] = Field("archive_batch", title="Archive Batch", description="Freezes recipient writes until unarchived; existing certificates remain accessible.", json_schema_extra={"ui:hidden": True})


class UnarchiveBatch(_Batch):
    operation: Literal["unarchive_batch"] = Field("unarchive_batch", title="Unarchive Batch", json_schema_extra={"ui:hidden": True})


class ListRecipients(_Batch, _Page):
    operation: Literal["list_recipients"] = Field("list_recipients", title="List Recipients", json_schema_extra={"ui:hidden": True})
    email_status: Literal["pending", "queued", "sending", "sent", "failed"] | None = Field(None, serialization_alias="emailStatus")


class CreateRecipient(_Batch, RecipientInput):
    operation: Literal["create_recipient"] = Field("create_recipient", title="Issue Certificate", json_schema_extra={"ui:hidden": True})


class CreateRecipientsBulk(_Batch):
    operation: Literal["create_recipients_bulk"] = Field("create_recipients_bulk", title="Issue Certificates in Bulk", json_schema_extra={"ui:hidden": True})
    recipients: list[RecipientInput] = Field(..., min_length=1, max_length=100)
    send: bool = Field(False, description="Queue email for every recipient, subject to Cert Seal sending configuration.")


class GetRecipient(_Recipient):
    operation: Literal["get_recipient"] = Field("get_recipient", title="Get Recipient", json_schema_extra={"ui:hidden": True})


class UpdateRecipient(_Recipient, RecipientFields):
    operation: Literal["update_recipient"] = Field("update_recipient", title="Update Recipient", description="Only supplied fields change. Use null to clear an optional field.", json_schema_extra={"ui:hidden": True})


class DeleteRecipient(_Recipient):
    operation: Literal["delete_recipient"] = Field("delete_recipient", title="Delete Recipient", json_schema_extra={"ui:hidden": True})


class SendRecipient(_Recipient):
    operation: Literal["send_recipient"] = Field("send_recipient", title="Queue Certificate Email", description="Queues delivery asynchronously; requires a batch email template. Does not confirm delivery.", json_schema_extra={"ui:hidden": True})


class RevokeRecipient(_Recipient):
    operation: Literal["revoke_recipient"] = Field("revoke_recipient", title="Revoke Certificate", json_schema_extra={"ui:hidden": True})
    reason: str | None = Field(None, max_length=500, description="Workspace-only reason, hidden from public pages.")


class ReinstateRecipient(_Recipient):
    operation: Literal["reinstate_recipient"] = Field("reinstate_recipient", title="Reinstate Certificate", json_schema_extra={"ui:hidden": True})


class GetCertificateByCode(_Input):
    operation: Literal["get_certificate_by_code"] = Field("get_certificate_by_code", title="Look Up Certificate by Code", json_schema_extra={"ui:hidden": True})
    certificate_id: str = Field(..., min_length=1)


class GetCertificateByToken(_Input):
    operation: Literal["get_certificate_by_token"] = Field("get_certificate_by_token", title="Look Up Certificate by Share Token", json_schema_extra={"ui:hidden": True})
    share_token: str = Field(..., min_length=8)


class ListDesigns(_Page):
    operation: Literal["list_designs"] = Field("list_designs", title="List Designs", description="Designs are authored in the Cert Seal web app.", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListBatches, CreateBatch, GetBatch, ArchiveBatch,
    UnarchiveBatch, ListRecipients, CreateRecipient, CreateRecipientsBulk,
    GetRecipient, UpdateRecipient, DeleteRecipient, SendRecipient, RevokeRecipient,
    ReinstateRecipient, GetCertificateByCode, GetCertificateByToken, ListDesigns],
    Field(discriminator="operation")]


class CertSealConfig(NodeConfig[Operation, CertSealAPIKey]):
    pass


# method, path template, response envelope, documented HTTP success status
ROUTES = {
    "list_batches": ("GET", "/batches", "batches", 200),
    "create_batch": ("POST", "/batches", "batch", 201),
    "get_batch": ("GET", "/batches/{batch_id}", "batch", 200),
    "archive_batch": ("POST", "/batches/{batch_id}/archive", "batch", 200),
    "unarchive_batch": ("POST", "/batches/{batch_id}/unarchive", "batch", 200),
    "list_recipients": ("GET", "/batches/{batch_id}/recipients", "recipients", 200),
    "create_recipient": ("POST", "/batches/{batch_id}/recipients", "recipient", 201),
    "create_recipients_bulk": ("POST", "/batches/{batch_id}/recipients/bulk", "recipients", 201),
    "get_recipient": ("GET", "/batches/{batch_id}/recipients/{recipient_id}", "recipient", 200),
    "update_recipient": ("PATCH", "/batches/{batch_id}/recipients/{recipient_id}", "recipient", 200),
    "delete_recipient": ("DELETE", "/batches/{batch_id}/recipients/{recipient_id}", "ok", 200),
    "send_recipient": ("POST", "/batches/{batch_id}/recipients/{recipient_id}/send", "recipient", 202),
    "revoke_recipient": ("POST", "/batches/{batch_id}/recipients/{recipient_id}/revoke", "recipient", 200),
    "reinstate_recipient": ("POST", "/batches/{batch_id}/recipients/{recipient_id}/reinstate", "recipient", 200),
    "get_certificate_by_code": ("GET", "/certificates/{certificate_id}", None, 200),
    "get_certificate_by_token": ("GET", "/certificates/by-token/{share_token}", None, 200),
    "list_designs": ("GET", "/designs", "designs", 200),
}


def _segment(value):
    if value in {".", ".."} or any(ord(c) < 32 for c in value):
        raise ValueError("Use a Cert Seal resource identifier")
    return quote(value, safe="")


class CertSealNode(WorkflowNode):
    integration_type = "automation-cert-seal"
    connection_evidence = ConnectionEvidence(noun="certificate batches", operation="list_batches")

    @classmethod
    def get_config_model(cls):
        return CertSealConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Cert Seal API key")
        op = self.config.config
        method, template, envelope, expected = ROUTES[op.operation]
        path_fields = {key: _segment(getattr(op, key)) for key in
            ("batch_id", "recipient_id", "certificate_id", "share_token")
            if "{" + key + "}" in template}
        path = template.format(**path_fields)
        params, body = {}, None
        if isinstance(op, _Page):
            params = op.model_dump(mode="json", by_alias=True, exclude_none=True,
                exclude={"operation", "batch_id"})
        elif isinstance(op, (CreateBatch, CreateRecipient, CreateRecipientsBulk, UpdateRecipient, RevokeRecipient)):
            body = op.model_dump(mode="json", by_alias=True,
                exclude={"operation", "batch_id", "recipient_id"},
                exclude_unset=True,
                exclude_none=not isinstance(op, UpdateRecipient))
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.status_code != expected:
            message = "Cert Seal request failed (HTTP " + str(response.status_code) + ")"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except ValueError:
                pass
            message = message.replace(self.config.credentials.api_key, "[redacted]")
            # Preserve HTTP status for the shared connect evidence classifier,
            # with a JSON message so its renderer keeps the provider's words.
            raise ValueError(f"Cert Seal API error {response.status_code}: " + json.dumps({"message": message}))
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("Cert Seal returned an unexpected response")
        if envelope in {"batches", "recipients", "designs"}:
            if not isinstance(payload.get(envelope), list):
                raise ValueError("Cert Seal returned an unexpected list")
        elif envelope in {"batch", "recipient"}:
            if not isinstance(payload.get(envelope), dict):
                raise ValueError("Cert Seal returned an unexpected resource")
        elif envelope == "ok":
            if payload.get("ok") is not True:
                raise ValueError("Cert Seal did not acknowledge deletion")
        elif any(not isinstance(payload.get(k), dict) for k in ("recipient", "batch", "design", "variables")):
            raise ValueError("Cert Seal returned an unexpected certificate")
        return {"status": "success", **payload}
