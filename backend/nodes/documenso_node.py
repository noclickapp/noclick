"""Documenso V2 envelope workflows.

The V2 envelope API is the current API for both documents and templates. Creating
an envelope always leaves a draft; only the separate distribute operation sends
signing invitations. API reference: https://openapi.documenso.com/reference
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)
API_BASE = "https://app.documenso.com/api/v2"
MAX_PDF_BYTES = 20 * 1024 * 1024


class DocumensoAPIKeyCredential(BaseModel):
    """Team API token from Documenso Team Settings → API Tokens."""

    credential_type: Literal["documenso_api_key"] = Field(
        "documenso_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="Team API Token",
        description="The complete token beginning with api_",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(title="Documenso API Key", json_schema_extra={
        "x-credential-url": "https://app.documenso.com",
    })


OP_DESCRIPTIONS = {
    "list_envelopes": "List documents and templates with status and folder filters.",
    "get_envelope": "Get one envelope with its recipients, fields and PDF items.",
    "create_envelope": "Upload a PDF and create an unsent document or template draft.",
    "use_template": "Create an unsent document draft from a template envelope.",
    "update_envelope": "Update the title, external ID or email settings of a draft.",
    "delete_envelope": "Delete an envelope that has not been completed.",
    "distribute_envelope": "Send a prepared draft to its recipients for signing.",
    "cancel_envelope": "Cancel a pending envelope and stop the signing process.",
    "get_audit_log": "Read the envelope's signing audit trail.",
    "get_recipient": "Read a recipient and their signing status.",
    "add_recipients": "Add one or more recipients to a draft envelope.",
    "update_recipients": "Update recipient details before signing is complete.",
    "delete_recipient": "Remove a recipient from an envelope.",
    "get_field": "Read one signature or form field.",
    "add_fields": "Place signature or form fields on a draft PDF.",
    "update_fields": "Move or change fields on a draft PDF.",
    "delete_field": "Remove one field from an envelope.",
    "list_folders": "List document folders in the connected team.",
    "create_folder": "Create a document or template folder.",
    "update_folder": "Rename, move or pin a folder.",
    "delete_folder": "Delete a folder by ID.",
    "add_envelope_item": "Attach another PDF to a draft envelope.",
    "delete_envelope_item": "Remove a PDF item from a draft envelope.",
    "download_envelope_item": "Retrieve the signed, pending or original PDF of an envelope item.",
}


def _op(name: str, label: str, category: str, *, creates: bool = False) -> Any:
    extra: Dict[str, Any] = {
        "const": name,
        "ui:hidden": True,
        "x-category": category,
        "x-is-trigger": False,
        "x-display-name": label,
    }
    if creates:
        extra.update({"x-creates-resource": True, "x-resource-type": "documenso_envelope"})
    return Field(name, title=label, description=OP_DESCRIPTIONS[name], json_schema_extra=extra)


ENVELOPE_PICKER = {
    "x-dynamic-options": {
        "field_name": "envelope_id",
        "placeholder": "Select an envelope...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste envelope ID",
    },
    "x-resource-type": "documenso_envelope",
}


class ListEnvelopes(BaseModel):
    operation: Literal["list_envelopes"] = _op("list_envelopes", "List Envelopes", "Envelopes")
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(20, ge=1, le=100, title="Per Page")
    envelope_type: Optional[Literal["DOCUMENT", "TEMPLATE"]] = Field(None, title="Type")
    status: Optional[Literal["DRAFT", "PENDING", "COMPLETED", "REJECTED", "CANCELLED"]] = Field(None, title="Status")
    folder_id: Optional[str] = Field(None, title="Folder ID")


class GetEnvelope(BaseModel):
    operation: Literal["get_envelope"] = _op("get_envelope", "Get Envelope", "Envelopes")
    envelope_id: str = Field(..., title="Envelope", json_schema_extra=ENVELOPE_PICKER)


class CreateEnvelope(BaseModel):
    operation: Literal["create_envelope"] = _op("create_envelope", "Create Draft Envelope", "Envelopes", creates=True)
    envelope_type: Literal["DOCUMENT", "TEMPLATE"] = Field("DOCUMENT", title="Type")
    title: str = Field(..., min_length=1, title="Title")
    pdf_url: Optional[str] = Field(None, title="PDF URL", description="Public HTTPS URL to a PDF (max 20 MB)")
    pdf_base64: Optional[str] = Field(None, title="PDF Base64", description="Base64-encoded PDF; use this or PDF URL", json_schema_extra={"ui:widget": "textarea"})
    filename: str = Field("document.pdf", title="Filename")
    external_id: Optional[str] = Field(None, title="External ID")
    folder_id: Optional[str] = Field(None, title="Folder ID")
    recipients_json: Optional[str] = Field(None, title="Recipients JSON", description="Optional array of recipients and positioned fields in the V2 format", json_schema_extra={"ui:widget": "textarea"})


class UseTemplate(BaseModel):
    operation: Literal["use_template"] = _op("use_template", "Create Draft from Template", "Templates", creates=True)
    envelope_id: str = Field(..., title="Template Envelope ID", json_schema_extra=ENVELOPE_PICKER)
    external_id: Optional[str] = Field(None, title="External ID")
    recipients_json: Optional[str] = Field(None, title="Recipient Overrides JSON", description="Optional array with template recipient id, email and name", json_schema_extra={"ui:widget": "textarea"})
    prefill_fields_json: Optional[str] = Field(None, title="Prefill Fields JSON", json_schema_extra={"ui:widget": "textarea"})


class UpdateEnvelope(BaseModel):
    operation: Literal["update_envelope"] = _op("update_envelope", "Update Draft Envelope", "Envelopes")
    envelope_id: str = Field(..., title="Envelope", json_schema_extra=ENVELOPE_PICKER)
    title: Optional[str] = Field(None, title="New Title")
    external_id: Optional[str] = Field(None, title="New External ID")
    subject: Optional[str] = Field(None, title="Email Subject")
    message: Optional[str] = Field(None, title="Email Message", json_schema_extra={"ui:widget": "textarea"})


class DeleteEnvelope(BaseModel):
    operation: Literal["delete_envelope"] = _op("delete_envelope", "Delete Envelope", "Envelopes")
    envelope_id: str = Field(..., title="Envelope", json_schema_extra=ENVELOPE_PICKER)


class DistributeEnvelope(BaseModel):
    operation: Literal["distribute_envelope"] = _op("distribute_envelope", "Send for Signing", "Signing")
    envelope_id: str = Field(..., title="Draft Envelope", json_schema_extra=ENVELOPE_PICKER)
    subject: Optional[str] = Field(None, title="Email Subject")
    message: Optional[str] = Field(None, title="Email Message", json_schema_extra={"ui:widget": "textarea"})


class CancelEnvelope(BaseModel):
    operation: Literal["cancel_envelope"] = _op("cancel_envelope", "Cancel Pending Envelope", "Signing")
    envelope_id: str = Field(..., title="Envelope", json_schema_extra=ENVELOPE_PICKER)
    reason: Optional[str] = Field(None, title="Reason")


class GetAuditLog(BaseModel):
    operation: Literal["get_audit_log"] = _op("get_audit_log", "Get Audit Log", "Signing")
    envelope_id: str = Field(..., title="Envelope", json_schema_extra=ENVELOPE_PICKER)


class GetRecipient(BaseModel):
    operation: Literal["get_recipient"] = _op("get_recipient", "Get Recipient", "Recipients")
    recipient_id: int = Field(..., ge=1, title="Recipient ID")


class AddRecipients(BaseModel):
    operation: Literal["add_recipients"] = _op("add_recipients", "Add Recipients", "Recipients")
    envelope_id: str = Field(..., title="Draft Envelope", json_schema_extra=ENVELOPE_PICKER)
    recipients_json: str = Field(..., title="Recipients JSON", description='Array of {"email", "name", "role"}; optional signingOrder', json_schema_extra={"ui:widget": "textarea"})


class UpdateRecipients(BaseModel):
    operation: Literal["update_recipients"] = _op("update_recipients", "Update Recipients", "Recipients")
    envelope_id: str = Field(..., title="Draft Envelope", json_schema_extra=ENVELOPE_PICKER)
    recipients_json: str = Field(..., title="Recipients JSON", description="Array with recipient id and fields to update", json_schema_extra={"ui:widget": "textarea"})


class DeleteRecipient(BaseModel):
    operation: Literal["delete_recipient"] = _op("delete_recipient", "Delete Recipient", "Recipients")
    recipient_id: int = Field(..., ge=1, title="Recipient ID")


class GetField(BaseModel):
    operation: Literal["get_field"] = _op("get_field", "Get Field", "Fields")
    field_id: int = Field(..., ge=1, title="Field ID")


class AddFields(BaseModel):
    operation: Literal["add_fields"] = _op("add_fields", "Add Fields", "Fields")
    envelope_id: str = Field(..., title="Draft Envelope", json_schema_extra=ENVELOPE_PICKER)
    fields_json: str = Field(..., title="Fields JSON", description='Array of fields with type, recipientId, page, positionX/Y, width and height', json_schema_extra={"ui:widget": "textarea"})


class UpdateFields(BaseModel):
    operation: Literal["update_fields"] = _op("update_fields", "Update Fields", "Fields")
    envelope_id: str = Field(..., title="Draft Envelope", json_schema_extra=ENVELOPE_PICKER)
    fields_json: str = Field(..., title="Fields JSON", description="Array with field id and values to update", json_schema_extra={"ui:widget": "textarea"})


class DeleteField(BaseModel):
    operation: Literal["delete_field"] = _op("delete_field", "Delete Field", "Fields")
    field_id: int = Field(..., ge=1, title="Field ID")


class ListFolders(BaseModel):
    operation: Literal["list_folders"] = _op("list_folders", "List Folders", "Folders")


class CreateFolder(BaseModel):
    operation: Literal["create_folder"] = _op("create_folder", "Create Folder", "Folders")
    name: str = Field(..., min_length=2, max_length=100, title="Name")
    parent_id: Optional[str] = Field(None, title="Parent Folder ID")
    folder_type: Literal["DOCUMENT", "TEMPLATE"] = Field("DOCUMENT", title="Type")


class UpdateFolder(BaseModel):
    operation: Literal["update_folder"] = _op("update_folder", "Update Folder", "Folders")
    folder_id: str = Field(..., title="Folder ID")
    name: Optional[str] = Field(None, min_length=2, max_length=100, title="New Name")
    parent_id: Optional[str] = Field(None, title="New Parent Folder ID")
    pinned: Optional[bool] = Field(None, title="Pinned")


class DeleteFolder(BaseModel):
    operation: Literal["delete_folder"] = _op("delete_folder", "Delete Folder", "Folders")
    folder_id: str = Field(..., title="Folder ID")


class AddEnvelopeItem(BaseModel):
    operation: Literal["add_envelope_item"] = _op("add_envelope_item", "Add PDF to Draft", "PDFs")
    envelope_id: str = Field(..., title="Draft Envelope", json_schema_extra=ENVELOPE_PICKER)
    pdf_url: Optional[str] = Field(None, title="PDF URL", description="Public HTTPS URL to a PDF (max 20 MB)")
    pdf_base64: Optional[str] = Field(None, title="PDF Base64", json_schema_extra={"ui:widget": "textarea"})
    filename: str = Field("document.pdf", title="Filename")


class DeleteEnvelopeItem(BaseModel):
    operation: Literal["delete_envelope_item"] = _op("delete_envelope_item", "Remove PDF from Draft", "PDFs")
    envelope_id: str = Field(..., title="Draft Envelope", json_schema_extra=ENVELOPE_PICKER)
    envelope_item_id: str = Field(..., title="PDF Item ID")


class DownloadEnvelopeItem(BaseModel):
    operation: Literal["download_envelope_item"] = _op("download_envelope_item", "Download PDF", "PDFs")
    envelope_item_id: str = Field(..., title="PDF Item ID", description="Find the ID in Get Envelope → envelopeItems")
    version: Literal["signed", "pending", "original"] = Field("signed", title="Version", description="Signed is available once the envelope is completed")


DocumensoConfig = Annotated[
    Union[
        ListEnvelopes, GetEnvelope, CreateEnvelope, UseTemplate, UpdateEnvelope,
        DeleteEnvelope, DistributeEnvelope, CancelEnvelope, GetAuditLog,
        GetRecipient, AddRecipients, UpdateRecipients, DeleteRecipient,
        GetField, AddFields, UpdateFields, DeleteField, ListFolders,
        CreateFolder, UpdateFolder, DeleteFolder, AddEnvelopeItem,
        DeleteEnvelopeItem, DownloadEnvelopeItem,
    ],
    Discriminator("operation"),
]


class DocumensoNodeConfig(NodeConfig[DocumensoConfig, DocumensoAPIKeyCredential]):
    pass


def _json_array(raw: Optional[str], label: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a JSON array of objects")
    return value


def _pdf_bytes(raw: str) -> bytes:
    try:
        content = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("PDF Base64 is invalid") from exc
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 20 MB limit")
    if not content.startswith(b"%PDF-"):
        raise ValueError("The supplied file is not a PDF")
    return content


def _envelope_id(value: str) -> str:
    if not re.fullmatch(r"envelope_[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid envelope ID")
    return value


async def _download_pdf(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("PDF URL must use HTTPS")
    async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            return await _bounded_pdf(response)


async def _bounded_pdf(response: httpx.Response) -> bytes:
    content = bytearray()
    async for chunk in response.aiter_bytes():
        if len(content) + len(chunk) > MAX_PDF_BYTES:
            raise ValueError("PDF exceeds the 20 MB limit")
        content.extend(chunk)
    if not content.startswith(b"%PDF-"):
        raise ValueError("The response is not a PDF")
    return bytes(content)


async def _pdf_source(pdf_base64: Optional[str], pdf_url: Optional[str]) -> bytes:
    if bool(pdf_base64) == bool(pdf_url):
        raise ValueError("Provide exactly one of PDF Base64 or PDF URL")
    return _pdf_bytes(pdf_base64) if pdf_base64 else await _download_pdf(pdf_url)


def _item_id(value: str) -> str:
    if not re.fullmatch(r"envelope_item_[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid envelope item ID")
    return value


async def _download_item(api_key: str, item_id: str, version: str) -> BinaryOutput:
    """Return PDF bytes; never forward the API key to a redirect destination."""
    path = f"/envelope/item/{_item_id(item_id)}/download"
    filename = f"{item_id}_{version}.pdf"
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
        async with client.stream("GET", f"{API_BASE}{path}", headers={"Authorization": api_key}, params={"version": version}) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Documenso PDF redirect has no location")
                download_url = urljoin(str(response.url), location)
            elif response.status_code >= 400:
                raise ValueError(f"Documenso API returned HTTP {response.status_code}")
            else:
                pdf = await _bounded_pdf(response)
                return BinaryOutput(data=pdf, content_type="application/pdf", filename=filename)

    # Signed storage URLs are untrusted input. The SSRF guard validates their
    # destination; this second request deliberately contains no API token.
    if not download_url.startswith("https://"):
        raise ValueError("Documenso PDF redirect must use HTTPS")
    async with guarded_async_client(timeout=60.0, follow_redirects=False) as client:
        async with client.stream("GET", download_url) as response:
            response.raise_for_status()
            pdf = await _bounded_pdf(response)
    return BinaryOutput(data=pdf, content_type="application/pdf", filename=filename)


async def _request(
    api_key: str, method: str, path: str, *, params: Optional[dict[str, Any]] = None,
    body: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None,
    pdf: Optional[bytes] = None, filename: str = "document.pdf",
) -> Any:
    headers = {"Authorization": api_key}
    kwargs: dict[str, Any] = {}
    if params is not None:
        kwargs["params"] = {key: value for key, value in params.items() if value is not None}
    if payload is not None:
        # multipart field payload is JSON text, matching Documenso's V2 examples.
        parts = [("payload", (None, json.dumps(payload)))]
        if pdf is not None:
            parts.append(("files", (filename, pdf, "application/pdf")))
        kwargs["files"] = parts
    elif body is not None:
        kwargs["json"] = body
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
    if response.status_code >= 400:
        raise ValueError(f"Documenso API returned HTTP {response.status_code}")
    if not response.content:
        return {"success": True}
    return response.json()


class DocumensoNode(WorkflowNode):
    """Create, prepare, send and track Documenso signature envelopes."""

    integration_type = "automation-documenso"

    edit_examples = [
        "List draft envelopes in my Documenso team",
        "Create a draft signature envelope from this PDF",
        "Add a signer and a signature field to the draft envelope",
        "Send this prepared envelope for signing",
        "Check the envelope status and audit log",
    ]
    connection_evidence = ConnectionEvidence(
        field="envelope_id", noun="envelopes", operation="list_envelopes",
    )

    @classmethod
    def get_config_model(cls):
        return DocumensoNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None, page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "envelope_id":
            return {"options": []}
        api_key = credential_data.get("api_key")
        if not api_key:
            return {"options": []}
        result = await _request(api_key, "GET", "/envelope", params={
            "perPage": 100, "page": int(page_token or 1),
        })
        rows = result.get("data", [])
        if search:
            rows = [row for row in rows if search.lower() in str(row.get("title", "")).lower()]
        return {
            "options": [{"value": row["id"], "label": row.get("title") or row["id"]} for row in rows if row.get("id")],
            "next_page_token": str(result["currentPage"] + 1) if result.get("currentPage", 1) < result.get("totalPages", 1) else None,
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not isinstance(config, DocumensoNodeConfig):
            raise ValueError("Documenso configuration is required")
        if not config.credentials or not config.credentials.api_key:
            raise ValueError("Connect a Documenso team API token")
        api_key = config.credentials.api_key
        op = config.config
        name = op.operation

        if isinstance(op, ListEnvelopes):
            data = await _request(api_key, "GET", "/envelope", params={
                "page": op.page, "perPage": op.per_page, "type": op.envelope_type,
                "status": op.status, "folderId": op.folder_id,
            })
        elif isinstance(op, GetEnvelope):
            data = await _request(api_key, "GET", f"/envelope/{_envelope_id(op.envelope_id)}")
        elif isinstance(op, CreateEnvelope):
            pdf = await _pdf_source(op.pdf_base64, op.pdf_url)
            payload: dict[str, Any] = {"type": op.envelope_type, "title": op.title}
            if op.external_id:
                payload["externalId"] = op.external_id
            if op.folder_id:
                payload["folderId"] = op.folder_id
            if op.recipients_json:
                payload["recipients"] = _json_array(op.recipients_json, "Recipients JSON")
            data = await _request(api_key, "POST", "/envelope/create", payload=payload, pdf=pdf, filename=op.filename)
        elif isinstance(op, UseTemplate):
            payload = {"envelopeId": op.envelope_id, "distributeDocument": False}
            if op.external_id:
                payload["externalId"] = op.external_id
            if op.recipients_json:
                payload["recipients"] = _json_array(op.recipients_json, "Recipient Overrides JSON")
            if op.prefill_fields_json:
                payload["prefillFields"] = _json_array(op.prefill_fields_json, "Prefill Fields JSON")
            data = await _request(api_key, "POST", "/envelope/use", payload=payload)
        elif isinstance(op, UpdateEnvelope):
            fields = {"title": op.title, "externalId": op.external_id}
            meta = {"subject": op.subject, "message": op.message}
            body = {"envelopeId": op.envelope_id}
            if any(value is not None for value in fields.values()):
                body["data"] = {key: value for key, value in fields.items() if value is not None}
            if any(value is not None for value in meta.values()):
                body["meta"] = {key: value for key, value in meta.items() if value is not None}
            if len(body) == 1:
                raise ValueError("Provide at least one value to update")
            data = await _request(api_key, "POST", "/envelope/update", body=body)
        elif isinstance(op, DeleteEnvelope):
            data = await _request(api_key, "POST", "/envelope/delete", body={"envelopeId": op.envelope_id})
        elif isinstance(op, DistributeEnvelope):
            body = {"envelopeId": op.envelope_id}
            meta = {"subject": op.subject, "message": op.message}
            if any(value is not None for value in meta.values()):
                body["meta"] = {key: value for key, value in meta.items() if value is not None}
            data = await _request(api_key, "POST", "/envelope/distribute", body=body)
        elif isinstance(op, CancelEnvelope):
            data = await _request(api_key, "POST", "/envelope/cancel", body={"envelopeId": op.envelope_id, **({"reason": op.reason} if op.reason else {})})
        elif isinstance(op, GetAuditLog):
            data = await _request(api_key, "GET", f"/envelope/{_envelope_id(op.envelope_id)}/audit-log")
        elif isinstance(op, GetRecipient):
            data = await _request(api_key, "GET", f"/envelope/recipient/{op.recipient_id}")
        elif isinstance(op, AddRecipients):
            data = await _request(api_key, "POST", "/envelope/recipient/create-many", body={"envelopeId": op.envelope_id, "data": _json_array(op.recipients_json, "Recipients JSON")})
        elif isinstance(op, UpdateRecipients):
            data = await _request(api_key, "POST", "/envelope/recipient/update-many", body={"envelopeId": op.envelope_id, "data": _json_array(op.recipients_json, "Recipients JSON")})
        elif isinstance(op, DeleteRecipient):
            data = await _request(api_key, "POST", "/envelope/recipient/delete", body={"recipientId": op.recipient_id})
        elif isinstance(op, GetField):
            data = await _request(api_key, "GET", f"/envelope/field/{op.field_id}")
        elif isinstance(op, AddFields):
            data = await _request(api_key, "POST", "/envelope/field/create-many", body={"envelopeId": op.envelope_id, "data": _json_array(op.fields_json, "Fields JSON")})
        elif isinstance(op, UpdateFields):
            data = await _request(api_key, "POST", "/envelope/field/update-many", body={"envelopeId": op.envelope_id, "data": _json_array(op.fields_json, "Fields JSON")})
        elif isinstance(op, DeleteField):
            data = await _request(api_key, "POST", "/envelope/field/delete", body={"fieldId": op.field_id})
        elif isinstance(op, ListFolders):
            data = await _request(api_key, "GET", "/folder")
        elif isinstance(op, CreateFolder):
            data = await _request(api_key, "POST", "/folder/create", body={
                "name": op.name, "type": op.folder_type,
                **({"parentId": op.parent_id} if op.parent_id else {}),
            })
        elif isinstance(op, UpdateFolder):
            fields = {"name": op.name, "parentId": op.parent_id, "pinned": op.pinned}
            fields = {key: value for key, value in fields.items() if value is not None}
            if not fields:
                raise ValueError("Provide at least one folder value to update")
            data = await _request(api_key, "POST", "/folder/update", body={"folderId": op.folder_id, "data": fields})
        elif isinstance(op, DeleteFolder):
            data = await _request(api_key, "POST", "/folder/delete", body={"folderId": op.folder_id})
        elif isinstance(op, AddEnvelopeItem):
            pdf = await _pdf_source(op.pdf_base64, op.pdf_url)
            data = await _request(api_key, "POST", "/envelope/item/create-many", payload={"envelopeId": op.envelope_id}, pdf=pdf, filename=op.filename)
        elif isinstance(op, DeleteEnvelopeItem):
            data = await _request(api_key, "POST", "/envelope/item/delete", body={
                "envelopeId": op.envelope_id, "envelopeItemId": _item_id(op.envelope_item_id),
            })
        elif isinstance(op, DownloadEnvelopeItem):
            data = await _download_item(api_key, op.envelope_item_id, op.version)
        else:
            raise ValueError(f"Unsupported Documenso operation: {name}")
        return {"status": "success", "action": name, "data": data}
