"""Carbone Cloud v5: one request per published HTTP operation.

Contract: https://carbone.io/file/carbone.OpenAPI.yml (V5.15.0).
Retrieving a render is single-use: Carbone deletes its stored copy.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

API_BASE = "https://api.carbone.io"
ENDPOINTS = {
    "upload_template": ("POST", "/template"),
    "update_template": ("PATCH", "/template/{template_id}"),
    "download_template": ("GET", "/template/{template_id}"),
    "delete_template": ("DELETE", "/template/{template_id}"),
    "list_templates": ("GET", "/templates"),
    "list_categories": ("GET", "/templates/categories"),
    "list_tags": ("GET", "/templates/tags"),
    "convert_document": ("POST", "/render/template"),
    "generate_document": ("POST", "/render/{template_id}"),
    "download_document": ("GET", "/render/{render_id}"),
    "get_status": ("GET", "/status"),
}
Identifier = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")]


class CarboneAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Carbone API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://account.carbone.io",
            "x-credential-instructions": "Copy your API token from your Carbone account home page and paste it here without the Bearer prefix. Test tokens generate watermarked PDFs only; production tokens support other formats and consume your Carbone credits. NoClick checks access by listing your templates.",
        })
    credential_type: Literal["carbone_api_token"] = Field("carbone_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or value.lower().startswith("bearer "):
            raise ValueError("Paste only the Carbone API token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Metadata(_Input):
    name: str | None = Field(None, max_length=200)
    comment: str | None = Field(None, max_length=200)
    category: str | None = Field(None, max_length=200)
    tags: list[str] | None = Field(None, description="Template tags, at most 100 characters in total. Use [] to clear tags.")
    expireAt: int | None = Field(None, ge=0, le=9007199254740991, description="Expiration as UTC Unix seconds; 0 means never expires.")
    deployedAt: int | None = Field(None, ge=0, le=9007199254740991, description="Deployment as UTC Unix seconds. Use 42000000000 to deploy now.")

    @field_validator("tags")
    @classmethod
    def tags_length(cls, value):
        if value is not None and sum(len(tag) for tag in value) > 100:
            raise ValueError("Template tags must total at most 100 characters")
        return value


class CarboneUploadTemplate(_Metadata):
    """Upload a base64 template, optionally adding a version and metadata."""
    operation: Literal["upload_template"] = "upload_template"
    template: str = Field(..., min_length=1, description="Base64-encoded template file contents.", json_schema_extra={"format": "byte", "contentMediaType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"})
    id: Identifier | None = Field(None, description="Existing Template ID to add a version to; not a Version ID.")
    versioning: bool = Field(False, description="Enable template version history.")
    origin: Literal[0, 1, 2, 3, 4] | None = None


class CarboneUpdateTemplate(_Metadata):
    """Patch template metadata; omitted fields remain unchanged."""
    operation: Literal["update_template"] = "update_template"
    template_id: Identifier = Field(..., description="Template ID or Version ID to update.")
    id: Identifier | None = Field(None, description="Move this version to this destination Template ID, if supplied.")

    @model_validator(mode="after")
    def has_metadata(self):
        if not self.model_dump(exclude={"operation", "template_id"}, exclude_none=True):
            raise ValueError("Provide at least one template metadata field")
        return self


class CarboneDownloadTemplate(_Input):
    """Download the original template file or a specific version."""
    operation: Literal["download_template"] = "download_template"
    template_id: Identifier


class CarboneDeleteTemplate(_Input):
    """Delete a template or version from Carbone storage."""
    operation: Literal["delete_template"] = "delete_template"
    template_id: Identifier


class CarboneListTemplates(_Input):
    """List one page of account templates; pass nextCursor as cursor to continue."""
    operation: Literal["list_templates"] = "list_templates"
    id: Identifier | None = Field(None, description="Filter by Template ID.")
    versionId: Identifier | None = Field(None, description="Filter by Version ID.")
    category: str | None = Field(None, max_length=200)
    origin: Literal[0, 1, 2, 3, 4] | None = None
    includeVersions: bool = False
    search: str | None = Field(None, max_length=200)
    limit: int = Field(100, ge=1, le=100)
    cursor: str | None = Field(None, max_length=4096)


class CarboneListCategories(_Input):
    """List categories used by this account's templates."""
    operation: Literal["list_categories"] = "list_categories"


class CarboneListTags(_Input):
    """List tags used by this account's templates."""
    operation: Literal["list_tags"] = "list_tags"


class _Render(_Input):
    data: dict[str, Any] | list[Any] | None = Field(None, description="Dataset merged into the template. Omit for conversion only; {} runs templating with empty data.")
    convertTo: str | None = Field(None, min_length=1, description="Output format, for example pdf, docx, xlsx, html, csv, png or webp. Omit to retain the template format.")
    converter: Literal["L", "O", "C", "I"] | None = Field(None, description="L: LibreOffice; O: OnlyOffice; C: Chromium; I: Carbone ICE.")
    download: bool = Field(False, description="Return the file directly; otherwise return a renderId for Download Document.")
    timezone: str | None = None
    lang: str | None = None
    reportName: str | None = Field(None, description="Output filename without extension; supports Carbone tags.")
    complement: dict[str, Any] | None = None
    translations: dict[str, Any] | None = None
    enum: dict[str, Any] | None = None
    variableStr: str | None = None
    currencySource: str | None = None
    currencyTarget: str | None = None
    currencyRates: dict[str, float] | None = None
    hardRefresh: bool | None = None
    failOn: list[Literal["IMAGE_URL_ERROR"]] | None = None


class CarboneGenerateDocument(_Render):
    """Merge JSON data into a stored template and generate a document."""
    operation: Literal["generate_document"] = "generate_document"
    template_id: Identifier

    @field_validator("template_id")
    @classmethod
    def stored_template(cls, value):
        if value == "template":
            raise ValueError("Choose a stored Template ID or use Convert Document for inline templates")
        return value


class CarboneConvertDocument(_Render):
    """Convert a base64 source document, with optional templating data."""
    operation: Literal["convert_document"] = "convert_document"
    template: str = Field(..., min_length=1, description="Base64-encoded source document contents.", json_schema_extra={"format": "byte", "contentMediaType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"})
    convertTo: str = Field("pdf", description="Target format, for example pdf, docx, html, csv or png.")


class CarboneDownloadDocument(_Input):
    """Download a generated document once. Carbone deletes its stored copy after retrieval."""
    operation: Literal["download_document"] = "download_document"
    render_id: Identifier = Field(..., description="renderId returned by Generate Document or Convert Document; single use.")
    download: bool = Field(True, description="Request attachment Content-Disposition.")


class CarboneGetStatus(_Input):
    """Read public API health and version; this does not verify your token."""
    operation: Literal["get_status"] = "get_status"


# Carbone's own MCP server: agents get its tools through a person's Carbone sign-in.
CarboneMcpCredential = mcp_credential("carbone", "https://mcp.carbone.io", app="Carbone")
CarboneCredential = Union[CarboneAPITokenCredential, CarboneMcpCredential]


CarboneConfig = Annotated[Union[
    CarboneUploadTemplate, CarboneUpdateTemplate, CarboneDownloadTemplate,
    CarboneDeleteTemplate, CarboneListTemplates, CarboneListCategories,
    CarboneListTags, CarboneGenerateDocument, CarboneConvertDocument,
    CarboneDownloadDocument, CarboneGetStatus,
], Field(discriminator="operation")]


class CarboneNodeConfig(NodeConfig[CarboneConfig, CarboneCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


def _filename(response, default):
    match = re.search(r'filename="?([^";\r\n]+)', response.headers.get("content-disposition", ""))
    name = match.group(1) if match else default
    return name.replace("\\", "/").split("/")[-1][:200] or default


class CarboneNode(WorkflowNode):
    integration_type = "automation-carbone"
    credential_provider_labels = {"carbone": "Carbone Account"}
    connection_evidence = ConnectionEvidence(noun="templates", operation="list_templates", label_keys=("name", "id", "versionId"))

    @classmethod
    def get_config_model(cls):
        return CarboneNodeConfig

    async def execute(self, inputs):
        config = self.config
        if not isinstance(config, CarboneNodeConfig) or not config.credentials:
            raise ValueError("Connect a Carbone API token")
        op = config.config
        token = config.credentials.api_token
        method, path = ENDPOINTS[op.operation]
        for field in ("template_id", "render_id"):
            if hasattr(op, field):
                path = path.replace("{" + field + "}", quote(getattr(op, field), safe=""))
        payload = op.model_dump(exclude={"operation", "template_id", "render_id", "download"}, exclude_none=True)
        params = payload if op.operation == "list_templates" else {}
        if hasattr(op, "download"):
            params["download"] = str(op.download).lower()
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        body = payload if method in {"POST", "PATCH"} else None
        if body is not None and "template" in body:
            body["template"] = body.pop("template")
        headers = {"carbone-version": "5"}
        if op.operation not in {"download_document", "get_status"}:
            headers["Authorization"] = "Bearer " + token
        binary = op.operation in {"download_template", "download_document"} or (isinstance(op, _Render) and op.download)
        headers["Accept"] = "*/*" if binary else "application/json"
        try:
            async with httpx.AsyncClient(timeout=65.0, follow_redirects=False) as client:
                response = await client.request(method, API_BASE + path, params=params, headers=headers,
                    **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            # Writes and single-use downloads must not be retried automatically.
            return {"status": "error", "action": op.operation, "error": "Carbone request did not complete; inspect the outcome before retrying", "outcome_verified": False}
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        result = None
        if "json" in content_type or not binary:
            try:
                result = response.json()
            except ValueError:
                raise ValueError("Carbone returned an unexpected non-JSON response") from None
        if not 200 <= response.status_code < 300 or (isinstance(result, dict) and result.get("success") is False):
            message = (result.get("error") or result.get("message")) if isinstance(result, dict) else None
            return {"status": "error", "action": op.operation, "status_code": response.status_code,
                "error": _redact(str(message or f"Carbone request failed (HTTP {response.status_code})"), token)}
        if binary:
            if isinstance(result, dict):
                raise ValueError("Carbone returned JSON instead of the requested file")
            return {"status": "success", "action": op.operation,
                "file": BinaryOutput(data=response.content, content_type=content_type,
                    filename=_filename(response, "template" if op.operation == "download_template" else "report")),
                "status_code": response.status_code}
        if not isinstance(result, dict) or result.get("success") is not True:
            raise ValueError("Carbone returned an unexpected success envelope")
        if op.operation in {"list_templates", "list_categories", "list_tags"} and not isinstance(result.get("data"), list):
            raise ValueError("Carbone returned an unexpected list response")
        if isinstance(op, _Render) and (not isinstance(result.get("data"), dict) or not isinstance(result["data"].get("renderId"), str)):
            raise ValueError("Carbone returned no render ID")
        # Preserve provider names, including hasMore and nextCursor, without inventing pagination.
        return {**_redact(result, token), "status": "success", "action": op.operation, "status_code": response.status_code}
