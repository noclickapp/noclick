"""DocsAutomator API v2 document, automation and signing operations.

Contract: https://docsautomator.co/docs/openapi.json (version 2.0).
Each operation sends one request. Async creation returns a job ID for explicit
polling; writes are never retried and signing list pagination stays explicit.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.docsautomator.co"


class DocsautomatorAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="DocsAutomator API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.docsautomator.co/settings/workspace/api",
            "x-credential-instructions": "Copy your API key from DocsAutomator workspace settings and paste it without the Bearer prefix. NoClick reads your automations to verify the connection.",
        })
    credential_type: Literal["docsautomator_api_key"] = Field("docsautomator_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API key", key=True)
        if not value.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Automation(_Input):
    automation_id: str = Field(..., min_length=1, title="Automation ID")


class _Session(_Input):
    session_id: str = Field(..., min_length=1, title="Signing session ID")


class Recipient(_Input):
    signer: int | None = Field(None, ge=1, description="Signer number; required for an automation with multiple signers.")
    email: str = Field(..., json_schema_extra={"format": "email"})
    name: str | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class CreateDocument(_Automation):
    """Generate a document using saved automation settings, including signing and delivery."""
    operation: Literal["create_document"] = "create_document"
    data: dict[str, Any] | None = Field(None, description="Template placeholder values; line_items_1 and children hold line items.")
    document_name: str | None = None
    async_mode: bool = Field(False, description="Queue generation and return jobId; poll Get Job Status separately.")
    webhook_params: dict[str, Any] | None = None
    existing_pdfs: list[str] | None = None
    doc_template_link: str | None = Field(None, json_schema_extra={"format": "uri"})
    word_template_link: str | None = Field(None, json_schema_extra={"format": "uri"})
    word_template_base64: str | None = Field(None, description="Base64 encoded .docx, at most 25 MB before encoding.")
    pdf_template_link: str | None = Field(None, json_schema_extra={"format": "uri"})
    pdf_template_base64: str | None = Field(None, description="Base64 encoded PDF, at most 25 MB before encoding.")
    recipients: list[Recipient] | None = Field(None, description="Per-document signer overrides; does not add signers to the automation.")

    @model_validator(mode="after")
    def exclusive_templates(self):
        for kind in ("word", "pdf"):
            if getattr(self, kind + "_template_link") and getattr(self, kind + "_template_base64"):
                raise ValueError("Send a template URL or base64 content, not both")
        return self


class GetJobStatus(_Input):
    operation: Literal["get_job_status"] = "get_job_status"
    job_id: str = Field(..., min_length=1)


class GetQueueStats(_Input):
    operation: Literal["get_queue_stats"] = "get_queue_stats"


class ListAutomations(_Input):
    operation: Literal["list_automations"] = "list_automations"


class GetAutomation(_Automation):
    operation: Literal["get_automation"] = "get_automation"


class CreateAutomation(_Input):
    operation: Literal["create_automation"] = "create_automation"
    title: str = Field(..., min_length=1)
    data_source_name: Literal["Airtable", "API", "ClickUp", "Glide", "Google Sheets", "Make", "n8n", "Noloco", "SmartSuite", "Zapier"] = Field(..., title="Data source")
    doc_template_link: str | None = Field(None, json_schema_extra={"format": "uri"})


class ImageOptions(_Input):
    quality: int | None = Field(None, ge=1, le=100)
    max_width: int | None = Field(None, ge=1)


class UpdateAutomation(_Automation):
    operation: Literal["update_automation"] = "update_automation"
    title: str | None = None
    doc_template_link: str | None = Field(None, json_schema_extra={"format": "uri"})
    new_document_name_field: str | None = None
    is_active: bool | None = None
    is_preview: bool | None = Field(None, description="False goes live; requires a confirmed account email. New automations start in preview mode.")
    save_google_doc: bool | None = None
    google_doc_destination_folder_url: str | None = Field(None, json_schema_extra={"format": "uri"})
    locale: str | None = None
    format_numbers_with_locale: bool | None = None
    pdf_expiration: Literal["never", "immediate", "oneday", "threedays", "oneweek", "twoweeks", "onemonth", "threemonths", "sixmonths", "oneyear"] | None = Field(None, description="PDF retention window; never retains PDFs until deleted.")
    image_options: ImageOptions | None = None


class DeleteAutomation(_Automation):
    """Delete the selected automation."""
    operation: Literal["delete_automation"] = "delete_automation"


class DuplicateAutomation(_Automation):
    operation: Literal["duplicate_automation"] = "duplicate_automation"


class ListPlaceholders(_Automation):
    operation: Literal["list_placeholders"] = "list_placeholders"


class DuplicateTemplate(_Automation):
    operation: Literal["duplicate_template"] = "duplicate_template"
    new_template_name: str | None = None


class SendTestEmail(_Automation):
    """Send a real test email to the specified recipient (provider rate limits apply)."""
    operation: Literal["send_test_email"] = "send_test_email"
    recipient: str = Field(..., json_schema_extra={"format": "email"})
    _email = field_validator("recipient")(Recipient.valid_email.__func__)


class ListSigningSessions(_Input):
    """Return one page; advance page using the returned pagination object."""
    operation: Literal["list_signing_sessions"] = "list_signing_sessions"
    status: Literal["pending", "in_progress", "completed", "declined", "cancelled"] | None = None
    email: str | None = Field(None, description="Partial signer email filter, case insensitive.")
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=250)


class GetSigningSession(_Session):
    operation: Literal["get_signing_session"] = "get_signing_session"


class GetSigningLinks(_Session):
    operation: Literal["get_signing_links"] = "get_signing_links"


class GetSigningAudit(_Session):
    operation: Literal["get_signing_audit"] = "get_signing_audit"


class CancelSigningSession(_Session):
    """Cancel the signing session."""
    operation: Literal["cancel_signing_session"] = "cancel_signing_session"
    reason: str | None = None


class ResendSigningInvite(_Session):
    """Send another invitation email to the selected existing signer."""
    operation: Literal["resend_signing_invite"] = "resend_signing_invite"
    signer_index: int = Field(..., ge=1, description="One-based signer number.")


# DocsAutomator's own MCP server: agents get its tools through a person's DocsAutomator sign-in.
DocsautomatorMcpCredential = mcp_credential("docsautomator", "https://mcp.docsautomator.co/mcp", app="DocsAutomator")
DocsautomatorCredential = Union[DocsautomatorAPIKeyCredential, DocsautomatorMcpCredential]


Operation = Annotated[Union[CreateDocument, GetJobStatus, GetQueueStats, ListAutomations,
    GetAutomation, CreateAutomation, UpdateAutomation, DeleteAutomation, DuplicateAutomation,
    ListPlaceholders, DuplicateTemplate, SendTestEmail, ListSigningSessions, GetSigningSession,
    GetSigningLinks, GetSigningAudit, CancelSigningSession, ResendSigningInvite], Field(discriminator="operation")]


class DocsautomatorFullConfig(NodeConfig[Operation, DocsautomatorCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# operation -> method, route, query field mapping. Other fields form the JSON body.
ROUTES = {
    "create_document": ("POST", "/createDocument", {}),
    "get_job_status": ("GET", "/job/{job_id}", {}),
    "get_queue_stats": ("GET", "/queue/stats", {}),
    "list_automations": ("GET", "/automations", {}),
    "get_automation": ("GET", "/automation", {"automation_id": "automationId"}),
    "create_automation": ("POST", "/createAutomation", {}),
    "update_automation": ("PUT", "/updateAutomation", {"automation_id": "docId"}),
    "delete_automation": ("DELETE", "/deleteAutomation", {"automation_id": "docId"}),
    "duplicate_automation": ("POST", "/duplicateAutomation", {"automation_id": "automationId"}),
    "list_placeholders": ("GET", "/listPlaceholdersV2", {"automation_id": "automationId"}),
    "duplicate_template": ("POST", "/duplicateGoogleDocTemplate", {"automation_id": "automationId", "new_template_name": "newTemplateName"}),
    "send_test_email": ("POST", "/sendTestEmail", {}),
    "list_signing_sessions": ("GET", "/esign/sessions", {"status": "status", "email": "email", "page": "page", "limit": "limit"}),
    "get_signing_session": ("GET", "/esign/sessions/{session_id}", {}),
    "get_signing_links": ("GET", "/esign/sessions/{session_id}/links", {}),
    "get_signing_audit": ("GET", "/esign/sessions/{session_id}/audit", {}),
    "cancel_signing_session": ("POST", "/esign/sessions/{session_id}/cancel", {}),
    "resend_signing_invite": ("POST", "/esign/sessions/{session_id}/resend/{signer_index}", {}),
}

BODY_FIELDS = {
    "automation_id": "automationId", "document_name": "documentName", "async_mode": "async",
    "webhook_params": "webhookParams", "existing_pdfs": "existingPdfs",
    "doc_template_link": "docTemplateLink", "word_template_link": "wordTemplateLink",
    "word_template_base64": "wordTemplateBase64", "pdf_template_link": "pdfTemplateLink",
    "pdf_template_base64": "pdfTemplateBase64", "data_source_name": "dataSourceName",
    "new_document_name_field": "newDocumentNameField", "is_active": "isActive",
    "is_preview": "isPreview", "save_google_doc": "saveGoogleDoc",
    "google_doc_destination_folder_url": "googleDocDestinationFolderUrl", "format_numbers_with_locale": "formatNumbersWithLocale",
    "pdf_expiration": "pdfExpiration", "image_options": "imageOptions",
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key.replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()}
    return value


class DocsautomatorNode(WorkflowNode):
    integration_type = "automation-docsautomator"
    credential_provider_labels = {"docsautomator": "DocsAutomator Account"}
    connection_evidence = ConnectionEvidence(noun="DocsAutomator automations", operation="list_automations", label_keys=("title", "_id"))

    @classmethod
    def get_config_model(cls):
        return DocsautomatorFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, DocsautomatorFullConfig) or not self.config.credentials:
            raise ValueError("Attach a DocsAutomator API key")
        config = self.config.config
        token = self.config.credentials.api_key
        method, template, query_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        # Explicit null is a documented retention value; preserve it for updates.
        if isinstance(config, UpdateAutomation) and "pdf_expiration" in config.model_fields_set:
            values["pdf_expiration"] = config.pdf_expiration
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{field: quote(str(values.pop(field)), safe="") for field in path_fields})
        params = {target: values.pop(source) for source, target in query_fields.items() if source in values}
        body = {BODY_FIELDS.get(key, key): value for key, value in values.items()}
        if "imageOptions" in body:
            body["imageOptions"] = {"maxWidth" if key == "max_width" else key: value for key, value in body["imageOptions"].items()}
        kwargs = {"params": params} if params else {}
        if method in {"POST", "PUT"} and (body or config.operation in {"update_automation", "cancel_signing_session"}):
            kwargs["json"] = body
        async with guarded_async_client(timeout=310 if config.operation == "create_document" else 30,
                trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if len(response.content) > 10_000_000:
            raise ValueError("DocsAutomator response exceeds the supported size")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from DocsAutomator")
        try:
            result = response.json()
        except ValueError:
            raise ValueError("DocsAutomator returned invalid JSON") from None
        if not isinstance(result, dict):
            raise ValueError("DocsAutomator returned an unexpected response envelope")
        if not 200 <= response.status_code < 300 or (result.get("error") and config.operation != "get_job_status") or result.get("errors") or result.get("success") is False:
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(result.get("error") or result.get("message") or result.get("errors") or "DocsAutomator rejected the request", token)}
        expected = {200, 202} if config.operation == "create_document" else {201} if config.operation == "create_automation" else {200}
        if response.status_code not in expected:
            raise ValueError("DocsAutomator did not confirm the operation")
        return _redact({"status": "success", "operation": config.operation, "http_status": response.status_code,
            "accepted": response.status_code == 202, "data": result}, token)
