"""DocRaptor document generation and lifecycle operations (published API v2)."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.docraptor.com"
TYPE = "docraptor_api_key"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _identifier(value):
    import re
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("Paste a single DocRaptor document ID")
    return value


class DocraptorAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Docraptor API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docraptor.com/dashboard",
            "x-credential-instructions": "Paste your API key and the status_id of an existing asynchronous document in your account. NoClick reads its status to check the connection without generating or downloading a document. Replace the status ID if the provider removes that document under your retention policy.",
        })
    credential_type: Literal["docraptor_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    status_id: str = Field(..., title="Existing Document Status ID", description="The status_id returned by an earlier asynchronous document request. Used only for the connection read.")
    _status = field_validator("status_id")(_identifier)

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste the API key without a Basic header or colon")
        return value


class PrinceOptions(_Input):
    media: Literal["print", "screen"] | None = None
    baseurl: str | None = None
    javascript: bool | None = None
    no_network: bool | None = None
    pdf_title: str | None = None
    page_margin: str | None = None
    profile: str | None = None
    pdf_forms: bool | None = None


class _Document(_Input):
    name: str = Field(..., min_length=1, max_length=200, description="Name shown in your document log.")
    document_content: str | None = Field(None, min_length=1, description="HTML for PDF or XML for Excel. Supply this or Document URL.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "html"})
    document_url: str | None = Field(None, description="URL DocRaptor will fetch instead of inline content.")
    test: bool = Field(True, description="Free test document: watermarked PDFs, truncated Excel, limited hosted retention. Set false for production generation.")
    javascript: bool = False
    pipeline: str | None = None
    strict: Literal["none", "html"] | None = None
    ignore_resource_errors: bool | None = None
    ignore_console_messages: bool | None = None
    tag: str | None = None
    referrer: str | None = None
    prince_options: PrinceOptions | None = None

    @model_validator(mode="after")
    def content_source(self):
        if bool(self.document_content) == bool(self.document_url):
            raise ValueError("Supply exactly one of Document Content or Document URL")
        return self


class CreatePDFConfig(_Document):
    """Convert HTML or a web page to a PDF file."""
    operation: Literal["create_pdf"] = "create_pdf"


class CreateXLSConfig(_Document):
    """Convert spreadsheet XML to an XLS file."""
    operation: Literal["create_xls"] = "create_xls"


class CreateXLSXConfig(_Document):
    """Convert spreadsheet XML to an XLSX file."""
    operation: Literal["create_xlsx"] = "create_xlsx"


class _TypedDocument(_Document):
    document_type: Literal["pdf", "xls", "xlsx"] = "pdf"


class _HostedDocument(_TypedDocument):
    hosted_download_limit: int | None = Field(None, ge=1)
    hosted_expires_at: str | None = Field(None, description="ISO 8601 expiration time, e.g. 2030-01-23T08:02:30-05:00.")


class CreateHostedDocumentConfig(_HostedDocument):
    """Create a hosted document and return its download URL (paid add-on)."""
    operation: Literal["create_hosted_document"] = "create_hosted_document"


class CreateAsyncDocumentConfig(_TypedDocument):
    """Queue a document and return its status ID without polling."""
    operation: Literal["create_async_document"] = "create_async_document"
    callback_url: str | None = Field(None, description="DocRaptor POSTs here on successful completion; failures require a status read.")


class CreateHostedAsyncDocumentConfig(_HostedDocument):
    """Queue a hosted document (paid add-on) and return its status ID."""
    operation: Literal["create_hosted_async_document"] = "create_hosted_async_document"
    callback_url: str | None = None


class GetDocumentStatusConfig(_Input):
    """Read the status, download metadata or failure of an asynchronous job."""
    operation: Literal["get_document_status"] = "get_document_status"
    status_id: str
    _status = field_validator("status_id")(_identifier)


class DownloadDocumentConfig(_Input):
    """Download a completed file by download_id; consumes a provider download."""
    operation: Literal["download_document"] = "download_document"
    download_id: str
    _download = field_validator("download_id")(_identifier)


class ExpireDocumentConfig(_Input):
    """Expire a hosted document so its public download link stops working."""
    operation: Literal["expire_document"] = "expire_document"
    download_id: str
    _download = field_validator("download_id")(_identifier)


class CheckConnectionConfig(_Input):
    """Read the credential's existing document status without creating a file."""
    operation: Literal["check_connection"] = "check_connection"


DocraptorConfig = Annotated[Union[
    CreatePDFConfig, CreateXLSConfig, CreateXLSXConfig, CreateHostedDocumentConfig,
    CreateAsyncDocumentConfig, CreateHostedAsyncDocumentConfig, GetDocumentStatusConfig,
    DownloadDocumentConfig, ExpireDocumentConfig, CheckConnectionConfig,
], Field(discriminator="operation")]


class DocraptorFullConfig(NodeConfig[DocraptorConfig, DocraptorAPIKeyCredential]):
    pass


class DocraptorNode(WorkflowNode):
    integration_type = "automation-docraptor"
    connection_evidence = ConnectionEvidence(noun="document status", operation="check_connection",
        label_keys=("status", "message", "download_id"))

    @classmethod
    def get_config_model(cls):
        return DocraptorFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a DocRaptor API key")
        op = config.operation
        method, path, body = "GET", "", None
        if isinstance(config, _Document):
            method = "POST"
            path = {"create_pdf": "/docs", "create_xls": "/docs", "create_xlsx": "/docs",
                "create_hosted_document": "/hosted_docs", "create_async_document": "/async_docs",
                "create_hosted_async_document": "/hosted_async_docs"}[op]
            body = config.model_dump(exclude={"operation"}, exclude_none=True)
            if op in {"create_pdf", "create_xls", "create_xlsx"}:
                body["document_type"] = op.removeprefix("create_")
        elif op in {"check_connection", "get_document_status"}:
            identifier = credential.status_id if op == "check_connection" else config.status_id
            path = "/status/" + quote(_identifier(identifier), safe="")
        elif op == "download_document":
            path = "/download/" + quote(config.download_id, safe="")
        elif op == "expire_document":
            method, path = "PATCH", "/expire/" + quote(config.download_id, safe="")
        async with guarded_async_client(timeout=90, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, json=body,
                auth=httpx.BasicAuth(credential.api_key, ""))
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                "error": response.text[:2000].replace(credential.api_key, "[redacted]") or "DocRaptor request failed"}
        if op == "expire_document":
            return {"status": "success", "expired": True, "download_id": config.download_id}
        if op in {"create_pdf", "create_xls", "create_xlsx", "download_document"}:
            ext = op.removeprefix("create_") if op.startswith("create_") else "bin"
            mime = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
            return {"status": "success", "file": BinaryOutput(response.content, mime, "document." + ext)}
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected a DocRaptor JSON object")
        return {"status": "success", "data": payload}
