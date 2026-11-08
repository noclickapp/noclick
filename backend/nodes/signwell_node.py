"""SignWell v1 document automation using a user-supplied API key.

Contract: https://developers.signwell.com/openapi/resources-and-endpoints.json
Each operation makes exactly one published API request. Pagination is explicit;
write acknowledgements do not assert delivery or completed signatures.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://www.signwell.com"


class SignwellAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Signwell API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.signwell.com/app/api/",
            "x-credential-instructions": "Copy your API key from SignWell's API settings and paste it here. NoClick sends it in the X-Api-Key header to www.signwell.com. Your key can access and change documents in its account.",
        })
    credential_type: Literal["signwell_api_key"] = Field("signwell_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FileInput(Input):
    name: str = Field(..., min_length=1)
    file_url: str = Field(..., json_schema_extra={"format": "uri"}, description="Public URL SignWell will fetch. Upload a supported document file.")

    @field_validator("file_url")
    @classmethod
    def url(cls, value):
        if not re.match(r"^https?://[^/\s]+", value):
            raise ValueError("Use a public HTTP or HTTPS file URL")
        return value


class Recipient(Input):
    id: str = Field(..., min_length=1)
    name: str | None = None
    email: str = Field(..., json_schema_extra={"format": "email"})
    subject: str | None = None
    message: str | None = None


class TemplateRecipient(Recipient):
    placeholder_name: str = Field(..., min_length=1)


class Placeholder(Input):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    preassigned_recipient_name: str | None = None
    preassigned_recipient_email: str | None = Field(None, json_schema_extra={"format": "email"})


class DocumentField(Input):
    x: float
    y: float
    page: int = Field(..., ge=1)
    recipient_id: str
    type: Literal["signature", "initials", "date", "text", "checkbox"]
    required: bool | None = None
    width: float | None = None
    height: float | None = None
    value: str | bool | float | None = None
    api_id: str | None = None


class TemplateField(Input):
    x: float
    y: float
    page: int = Field(..., ge=1)
    placeholder_id: str
    type: Literal["signature", "initials", "date", "text", "checkbox"]
    required: bool | None = None
    width: float | None = None
    height: float | None = None
    value: str | bool | float | None = None
    api_id: str | None = None


class DocumentOptions(Input):
    name: str | None = None
    subject: str | None = None
    message: str | None = None
    expires_in: int | None = Field(None, ge=1)
    reminders: bool | None = None
    apply_signing_order: bool | None = None
    api_application_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    metadata: dict[str, str] | None = None


class DocumentId(Input):
    document_id: str = Field(..., json_schema_extra={"format": "uuid"}, description="Document ID returned by SignWell.")


class TemplateId(Input):
    template_id: str = Field(..., json_schema_extra={"format": "uuid"})


class ApplicationId(Input):
    application_id: str = Field(..., json_schema_extra={"format": "uuid"})


class WebhookId(Input):
    webhook_id: str = Field(..., json_schema_extra={"format": "uuid"})


class BulkSendId(Input):
    bulk_send_id: str = Field(..., json_schema_extra={"format": "uuid"})


class CreateDocument(DocumentOptions):
    files: list[FileInput] = Field(..., min_length=1)
    recipients: list[Recipient] = Field(..., min_length=1)
    draft: bool = Field(True, description="Keep a draft until Send Document. Set false to send immediately.")
    test_mode: bool | None = None
    with_signature_page: bool | None = None
    text_tags: bool | None = None
    fields: list[list[DocumentField]] | None = None



class FromTemplate(DocumentOptions, TemplateId):
    recipients: list[TemplateRecipient] = Field(..., min_length=1)
    draft: bool = True
    test_mode: bool | None = None


class SendDocument(DocumentOptions, DocumentId):
    """Send an existing draft; the response acknowledges the request, not delivery."""


class RecipientUpdate(Input):
    id: str = Field(..., min_length=1)
    name: str
    email: str = Field(..., json_schema_extra={"format": "email"})
    subject: str | None = None
    message: str | None = None


class UpdateRecipients(DocumentId):
    recipients: list[RecipientUpdate] = Field(..., min_length=1)


class PasscodeDelivery(Input):
    enabled: bool | None = None
    methods: list[Literal["email"]] | None = None
    expire_after_access: bool | None = None


class AuthenticationRecipient(Input):
    id: str = Field(..., min_length=1)
    passcode: str | None = Field(None, json_schema_extra={"ui:widget": "password"})
    passcode_delivery: PasscodeDelivery | None = None


class UpdateAuthentication(DocumentId):
    recipients: list[AuthenticationRecipient] = Field(..., min_length=1)


class ReminderRecipient(Input):
    name: str | None = None
    email: str | None = Field(None, json_schema_extra={"format": "email"})


class Reminder(DocumentId):
    recipients: list[ReminderRecipient] | None = None


class CreateTemplate(DocumentOptions):
    files: list[FileInput] = Field(..., min_length=1)
    placeholders: list[Placeholder] = Field(..., min_length=1)
    draft: bool = True
    text_tags: bool | None = None
    fields: list[list[TemplateField]] | None = None


class UpdateTemplate(DocumentOptions, TemplateId):
    draft: bool | None = None


class CreateWebhook(Input):
    callback_url: str = Field(..., json_schema_extra={"format": "uri"})
    api_application_id: str | None = Field(None, json_schema_extra={"format": "uuid"})


class Pagination(Input):
    limit: int = Field(10, ge=1, le=50)
    page: int = Field(1, ge=1, description="Fetch one page; use next_page from the returned data.")


class ListBulk(Pagination):
    user_email: str | None = Field(None, json_schema_extra={"format": "email"})
    api_application_id: str | None = Field(None, json_schema_extra={"format": "uuid"})


class BulkDocuments(Pagination, BulkSendId):
    pass


class SignwellGetMeConfig(Input):
    """Get credentials."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class SignwellGetAccountConfig(Input):
    """Get Account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class SignwellCreateDocumentConfig(CreateDocument):
    """Create Document."""
    operation: Literal["create_document"] = Field("create_document", json_schema_extra={"ui:hidden": True})


class SignwellGetDocumentConfig(DocumentId):
    """Get Document."""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})


class SignwellDeleteDocumentConfig(DocumentId):
    """Delete Document."""
    operation: Literal["delete_document"] = Field("delete_document", json_schema_extra={"ui:hidden": True})


class SignwellCreateDocumentFromTemplateConfig(FromTemplate):
    """Create Document from Template."""
    operation: Literal["create_document_from_template"] = Field("create_document_from_template", json_schema_extra={"ui:hidden": True})


class SignwellSendDocumentConfig(SendDocument):
    """Update and Send Document."""
    operation: Literal["send_document"] = Field("send_document", json_schema_extra={"ui:hidden": True})


class SignwellUpdateRecipientsConfig(UpdateRecipients):
    """Update Recipients."""
    operation: Literal["update_recipients"] = Field("update_recipients", json_schema_extra={"ui:hidden": True})


class SignwellUpdateAuthenticationConfig(UpdateAuthentication):
    """Update Authentication."""
    operation: Literal["update_authentication"] = Field("update_authentication", json_schema_extra={"ui:hidden": True})


class SignwellSendReminderConfig(Reminder):
    """Send Reminder."""
    operation: Literal["send_reminder"] = Field("send_reminder", json_schema_extra={"ui:hidden": True})


class SignwellGetCompletedPdfUrlConfig(DocumentId):
    """Completed PDF."""
    operation: Literal["get_completed_pdf_url"] = Field("get_completed_pdf_url", json_schema_extra={"ui:hidden": True})


class SignwellCreateTemplateConfig(CreateTemplate):
    """Create Template."""
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})


class SignwellGetTemplateConfig(TemplateId):
    """Get Template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})


class SignwellUpdateTemplateConfig(UpdateTemplate):
    """Update Template."""
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"ui:hidden": True})


class SignwellDeleteTemplateConfig(TemplateId):
    """Delete Template."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})


class SignwellGetApiApplicationConfig(ApplicationId):
    """Get API Application."""
    operation: Literal["get_api_application"] = Field("get_api_application", json_schema_extra={"ui:hidden": True})


class SignwellListWebhooksConfig(Input):
    """List Webhooks."""
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"ui:hidden": True})


class SignwellCreateWebhookConfig(CreateWebhook):
    """Create Webhook."""
    operation: Literal["create_webhook"] = Field("create_webhook", json_schema_extra={"ui:hidden": True})


class SignwellDeleteWebhookConfig(WebhookId):
    """Delete Webhook."""
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"ui:hidden": True})


class SignwellGetBulkSendConfig(BulkSendId):
    """Get Bulk Send."""
    operation: Literal["get_bulk_send"] = Field("get_bulk_send", json_schema_extra={"ui:hidden": True})


class SignwellListBulkSendsConfig(ListBulk):
    """List Bulk Sendings."""
    operation: Literal["list_bulk_sends"] = Field("list_bulk_sends", json_schema_extra={"ui:hidden": True})


class SignwellGetBulkSendDocumentsConfig(BulkDocuments):
    """Get Bulk Send Documents."""
    operation: Literal["get_bulk_send_documents"] = Field("get_bulk_send_documents", json_schema_extra={"ui:hidden": True})


SignwellConfig = Annotated[Union[
    SignwellGetMeConfig,
    SignwellGetAccountConfig,
    SignwellCreateDocumentConfig,
    SignwellGetDocumentConfig,
    SignwellDeleteDocumentConfig,
    SignwellCreateDocumentFromTemplateConfig,
    SignwellSendDocumentConfig,
    SignwellUpdateRecipientsConfig,
    SignwellUpdateAuthenticationConfig,
    SignwellSendReminderConfig,
    SignwellGetCompletedPdfUrlConfig,
    SignwellCreateTemplateConfig,
    SignwellGetTemplateConfig,
    SignwellUpdateTemplateConfig,
    SignwellDeleteTemplateConfig,
    SignwellGetApiApplicationConfig,
    SignwellListWebhooksConfig,
    SignwellCreateWebhookConfig,
    SignwellDeleteWebhookConfig,
    SignwellGetBulkSendConfig,
    SignwellListBulkSendsConfig,
    SignwellGetBulkSendDocumentsConfig
], Field(discriminator="operation")]


class SignwellFullConfig(NodeConfig[SignwellConfig, SignwellAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {'get_me': ('GET', '/api/v1/me'), 'get_account': ('GET', '/api/v1/account'), 'create_document': ('POST', '/api/v1/documents'), 'get_document': ('GET', '/api/v1/documents/{id}'), 'delete_document': ('DELETE', '/api/v1/documents/{id}'), 'create_document_from_template': ('POST', '/api/v1/document_templates/documents'), 'send_document': ('POST', '/api/v1/documents/{id}/send'), 'update_recipients': ('PATCH', '/api/v1/documents/{id}/recipients'), 'update_authentication': ('PATCH', '/api/v1/documents/{id}/authentication'), 'send_reminder': ('POST', '/api/v1/documents/{id}/remind'), 'get_completed_pdf_url': ('GET', '/api/v1/documents/{id}/completed_pdf'), 'create_template': ('POST', '/api/v1/document_templates'), 'get_template': ('GET', '/api/v1/document_templates/{id}'), 'update_template': ('PUT', '/api/v1/document_templates/{id}'), 'delete_template': ('DELETE', '/api/v1/document_templates/{id}'), 'get_api_application': ('GET', '/api/v1/api_applications/{id}'), 'list_webhooks': ('GET', '/api/v1/hooks'), 'create_webhook': ('POST', '/api/v1/hooks'), 'delete_webhook': ('DELETE', '/api/v1/hooks/{id}'), 'get_bulk_send': ('GET', '/api/v1/bulk_sends/{id}'), 'list_bulk_sends': ('GET', '/api/v1/bulk_sends'), 'get_bulk_send_documents': ('GET', '/api/v1/bulk_sends/{id}/documents')}

IDENTIFIERS = {"/api/v1/documents/{id}": "document_id", "/api/v1/document_templates/{id}": "template_id",
    "/api/v1/api_applications/{id}": "application_id", "/api/v1/hooks/{id}": "webhook_id",
    "/api/v1/bulk_sends/{id}": "bulk_send_id"}


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()
                if k.lower() not in {"api_key", "passcode", "access_token", "refresh_token"}}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class SignwellNode(WorkflowNode):
    integration_type = "automation-signwell"
    connection_evidence = ConnectionEvidence(noun="SignWell account", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return SignwellFullConfig

    async def execute(self, context):
        op = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SignWell API key")
        method, path = OPERATIONS[op.operation]
        payload = op.model_dump(exclude={"operation"}, exclude_none=True)
        for prefix, field in IDENTIFIERS.items():
            if path.startswith(prefix):
                identifier = payload.pop(field)
                if not identifier or len(identifier) > 200 or any(c in identifier for c in "/?#\\") or identifier in {".", ".."}:
                    raise ValueError("Use one SignWell resource ID")
                path = path.replace("{id}", quote(identifier, safe=""))
                break
        params = payload if method == "GET" else None
        if op.operation == "get_completed_pdf_url":
            params = {"url_only": "true"}
        body = payload if method in {"POST", "PUT", "PATCH"} else None
        passcodes = [r.passcode for r in getattr(op, "recipients", []) or [] if isinstance(r, AuthenticationRecipient) and r.passcode]
        secrets = [credential.api_key, *passcodes]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"X-Api-Key": credential.api_key, "Accept": "application/json"},
                    params=params, json=body)
        except httpx.HTTPError:
            raise ValueError("SignWell request failed; check the document before retrying a write") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the common connection-evidence seam.
            message = "SignWell request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:1000]
            except (ValueError, TypeError):
                pass
            result = {"status": "error", "http_status": response.status_code,
                "message": _redact(message, secrets)}
        elif response.status_code == 204 or (method == "DELETE" and not response.content):
            result = {"status": "success", "http_status": response.status_code,
                "deletion_acknowledged": True}
        else:
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime != "application/json" or len(response.content) > 10_000_000:
                raise ValueError("Expected bounded JSON from SignWell")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("SignWell returned invalid JSON") from None
            if not isinstance(data, (dict, list)) or (isinstance(data, dict) and ("errors" in data or "error" in data)):
                raise ValueError("SignWell returned an unexpected response")
            expected_type = list if op.operation == "list_webhooks" else dict
            if not isinstance(data, expected_type):
                raise ValueError("SignWell returned an unexpected response shape")
            if op.operation == "get_me":
                user = data.get("user") if isinstance(data, dict) else None
                if not isinstance(user, dict) or not user.get("id") or not user.get("email"):
                    raise ValueError("SignWell account identity is unavailable")
                data = {"id": data.get("id"), "name": user.get("name") or user["email"],
                    "email": user["email"], "account": data.get("account"), "role": data.get("role")}
            result = {"status": "success", "http_status": response.status_code, "data": _redact(data, secrets)}
            if method != "GET":
                result["request_acknowledged"] = True
        await self.emit(result)
        return result
