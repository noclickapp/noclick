"""Parseur API operations using a manually supplied account API key.

Contract: https://api.parseur.com/openapi.json, version 1.0.0.
Each operation issues exactly one request; paginated reads return one page.
"""
from typing import Annotated, Literal, Union, Optional
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.parseur.com"

class ParseurAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Parseur API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.parseur.com/account/api-keys",
        "x-credential-instructions": "Copy an API key from Parseur Account → API keys and paste the key alone. NoClick sends it as Authorization: Token to api.parseur.com. Connecting reads your mailboxes; write operations use the permissions of this key."})
    credential_type: Literal["parseur_api_key"] = Field("parseur_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key alone")
        return value

class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Page(Operation):
    page: int = Field(1, ge=1, description="Page number. Increment to read the next page.")
    page_size: int = Field(25, ge=1, le=100, description="Results per page; no automatic pagination.")
    search: Optional[str] = None

class ListMailboxesConfig(Page):
    """List mailboxes."""
    operation: Literal["list_mailboxes"] = Field("list_mailboxes", json_schema_extra={"ui:hidden": True})


class GetMailboxConfig(Operation):
    """Get mailbox."""
    operation: Literal["get_mailbox"] = Field("get_mailbox", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)


class CreateMailboxConfig(Operation):
    """Create mailbox."""
    operation: Literal["create_mailbox"] = Field("create_mailbox", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    email_prefix: Optional[str] = None
    process_attachments: Optional[bool] = None
    ai_instructions: Optional[str] = None


class UpdateMailboxConfig(Operation):
    """Update mailbox."""
    operation: Literal["update_mailbox"] = Field("update_mailbox", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1)
    email_prefix: Optional[str] = None
    process_attachments: Optional[bool] = None
    ai_instructions: Optional[str] = None


class DeleteMailboxConfig(Operation):
    """Delete mailbox."""
    operation: Literal["delete_mailbox"] = Field("delete_mailbox", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)


class CopyMailboxConfig(Operation):
    """Copy mailbox."""
    operation: Literal["copy_mailbox"] = Field("copy_mailbox", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)


class GetMailboxSchemaConfig(Operation):
    """Get mailbox schema."""
    operation: Literal["get_mailbox_schema"] = Field("get_mailbox_schema", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)


class ListDocumentsConfig(Page):
    """List documents."""
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)
    with_result: Optional[bool] = None


class GetDocumentConfig(Operation):
    """Get document."""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class DeleteDocumentConfig(Operation):
    """Delete document."""
    operation: Literal["delete_document"] = Field("delete_document", json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class GetDocumentLogsConfig(Page):
    """Get document logs."""
    operation: Literal["get_document_logs"] = Field("get_document_logs", json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class ReprocessDocumentConfig(Operation):
    """Reprocess document."""
    operation: Literal["reprocess_document"] = Field("reprocess_document", json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class SkipDocumentConfig(Operation):
    """Skip document."""
    operation: Literal["skip_document"] = Field("skip_document", json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class CopyDocumentConfig(Operation):
    """Copy document."""
    operation: Literal["copy_document"] = Field("copy_document", json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    target_mailbox_id: int = Field(..., ge=1)


class UploadEmailConfig(Operation):
    """Upload email."""
    operation: Literal["upload_email"] = Field("upload_email", json_schema_extra={"ui:hidden": True})
    subject: str
    sender: str = Field(..., description="From address, optionally with display name.")
    recipient: str = Field(..., description="Parseur mailbox email address.")
    body_plain: str
    body_html: Optional[str] = None


class ListTemplatesConfig(Operation):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)


class GetTemplateConfig(Operation):
    """Get template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1)


class DeleteTemplateConfig(Operation):
    """Delete template."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1)


class CopyTemplateConfig(Operation):
    """Copy template."""
    operation: Literal["copy_template"] = Field("copy_template", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1)
    target_mailbox_id: int = Field(..., ge=1)


class ListCustomDownloadsConfig(Operation):
    """List custom downloads."""
    operation: Literal["list_custom_downloads"] = Field("list_custom_downloads", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)


class CreateCustomDownloadConfig(Operation):
    """Create custom download."""
    operation: Literal["create_custom_download"] = Field("create_custom_download", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)
    name: str
    type: Literal["PARSER", "PARSER_FIELD"] = "PARSER"
    items: list[str] = Field(..., description="Field names included in the custom download.")
    parser_field_id: Optional[str] = None


class UpdateCustomDownloadConfig(Operation):
    """Update custom download."""
    operation: Literal["update_custom_download"] = Field("update_custom_download", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)
    download_id: int = Field(..., ge=1)
    name: str
    type: Literal["PARSER", "PARSER_FIELD"] = "PARSER"
    items: list[str] = Field(..., description="Field names included in the custom download.")
    parser_field_id: Optional[str] = None


class DeleteCustomDownloadConfig(Operation):
    """Delete custom download."""
    operation: Literal["delete_custom_download"] = Field("delete_custom_download", json_schema_extra={"ui:hidden": True})
    mailbox_id: int = Field(..., ge=1)
    download_id: int = Field(..., ge=1)


# Parseur's own MCP server: agents get its tools through a person's Parseur sign-in.
ParseurMcpCredential = mcp_credential("parseur", "https://api.parseur.com/mcp", app="Parseur")
ParseurCredential = Union[ParseurAPIKeyCredential, ParseurMcpCredential]


ParseurConfig = Annotated[Union[ListMailboxesConfig, GetMailboxConfig, CreateMailboxConfig, UpdateMailboxConfig, DeleteMailboxConfig, CopyMailboxConfig, GetMailboxSchemaConfig, ListDocumentsConfig, GetDocumentConfig, DeleteDocumentConfig, GetDocumentLogsConfig, ReprocessDocumentConfig, SkipDocumentConfig, CopyDocumentConfig, UploadEmailConfig, ListTemplatesConfig, GetTemplateConfig, DeleteTemplateConfig, CopyTemplateConfig, ListCustomDownloadsConfig, CreateCustomDownloadConfig, UpdateCustomDownloadConfig, DeleteCustomDownloadConfig], Field(discriminator="operation")]

class ParseurFullConfig(NodeConfig[ParseurConfig, ParseurCredential]):
    pass

ROUTES = {'list_mailboxes': ('GET', '/parser', []), 'get_mailbox': ('GET', '/parser/{mailbox_id}', []), 'create_mailbox': ('POST', '/parser', ['name', 'email_prefix', 'process_attachments', 'ai_instructions']), 'update_mailbox': ('PUT', '/parser/{mailbox_id}', ['name', 'email_prefix', 'process_attachments', 'ai_instructions']), 'delete_mailbox': ('DELETE', '/parser/{mailbox_id}', []), 'copy_mailbox': ('POST', '/parser/{mailbox_id}/copy', []), 'get_mailbox_schema': ('GET', '/parser/{mailbox_id}/schema', []), 'list_documents': ('GET', '/parser/{mailbox_id}/document_set', []), 'get_document': ('GET', '/document/{document_id}', []), 'delete_document': ('DELETE', '/document/{document_id}', []), 'get_document_logs': ('GET', '/document/{document_id}/log_set', []), 'reprocess_document': ('POST', '/document/{document_id}/process', []), 'skip_document': ('POST', '/document/{document_id}/skip', []), 'copy_document': ('POST', '/document/{document_id}/copy/{target_mailbox_id}', []), 'upload_email': ('POST', '/email', ['subject', 'sender', 'recipient', 'body_plain', 'body_html']), 'list_templates': ('GET', '/parser/{mailbox_id}/template_set', []), 'get_template': ('GET', '/template/{template_id}', []), 'delete_template': ('DELETE', '/template/{template_id}', []), 'copy_template': ('POST', '/template/{template_id}/copy/{target_mailbox_id}', []), 'list_custom_downloads': ('GET', '/parser/{mailbox_id}/export_config', []), 'create_custom_download': ('POST', '/parser/{mailbox_id}/export_config', ['name', 'type', 'items', 'parser_field_id']), 'update_custom_download': ('PATCH', '/parser/{mailbox_id}/export_config/{download_id}', ['name', 'type', 'items', 'parser_field_id']), 'delete_custom_download': ('DELETE', '/parser/{mailbox_id}/export_config/{download_id}', [])}

class ParseurNode(WorkflowNode):
    integration_type = "automation-parseur"
    credential_provider_labels = {"parseur": "Parseur Account"}
    connection_evidence = ConnectionEvidence(operation="list_mailboxes", noun="mailboxes")

    @classmethod
    def get_config_model(cls):
        return ParseurFullConfig

    @staticmethod
    def _guard_credential(config_data):
        credential = config_data.get("credentials")
        if credential is not None and (not isinstance(credential, dict) or
                credential.get("credential_type", "parseur_api_key") != "parseur_api_key"):
            raise ValueError("Attach a Parseur API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._guard_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._guard_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Parseur API key")
        config = self.config.config
        credential = self.config.credentials
        method, route, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for field in ("mailbox_id", "document_id", "template_id", "target_mailbox_id", "download_id"):
            if field in values:
                route = route.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()
                  if k in {"page", "page_size", "search", "with_result"}}
        body = {("from" if k == "sender" else k): values[k] for k in body_fields if k in values}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"Authorization": "Token " + credential.api_key, "Accept": "application/json"},
                    params=params or None, **({"json": body} if body_fields else {}))
        except httpx.RequestError:
            raise ValueError("Parseur request could not be confirmed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Parseur request failed (HTTP {response.status_code})")
        try:
            payload = response.json() if response.content else None
        except ValueError:
            raise ValueError("Parseur returned an invalid JSON response") from None
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items() if k not in {"secret", "api_key"}}
            return value
        output = {"data": redact(payload), "http_status": response.status_code}
        await self.emit(output)
        return output
