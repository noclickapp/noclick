"""TemplateFox v1: generate documents and images, manage versions and read account usage.

Contract: https://api.templatefox.com/openapi.json (0.0.0).
Delivery is URL-only; NoClick never downloads or embeds generated files.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.templatefox.com"


class TemplatefoxAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="TemplateFox API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.templatefox.com/",
            "x-credential-instructions": "Copy your API key from the TemplateFox dashboard API Keys section. Paste the key alone. NoClick sends it in x-api-key and checks your account email and credits.",
        },
    )
    credential_type: Literal["templatefox_api_key"] = Field(
        "templatefox_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value) or value.lower().startswith("bearer "):
            raise ValueError("Paste the API key alone, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Path(_Input):
    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"template_id", "job_id"} and (
            not value
            or value in {".", ".."}
            or any(c in value for c in "/\\?#")
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Use a single TemplateFox resource ID")
        return value


class Modification(_Input):
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name of the layer to modify (set via the editor's Layers panel). Matched against the element's `data-layer-name`, falling back to its `id`.",
    )
    text: str | None = Field(
        None,
        max_length=10000,
        description="Replace the element's text content. Rendered as literal text (HTML and `{{ }}` are not interpreted).",
    )
    image_url: str | None = Field(
        None,
        max_length=2000,
        pattern="^https?://",
        description="Set the image source. For an `<img>` element this sets `src`; for any other element it sets a `background-image`.",
    )
    color: str | None = Field(
        None,
        max_length=100,
        description="CSS color applied to the element's text (`color`).",
    )
    background: str | None = Field(
        None,
        max_length=100,
        description="CSS color applied to the element's background (`background-color`).",
    )
    hidden: bool | None = Field(
        None, description="Hide (`true`) or show (`false`) the element."
    )


class PdfInput(_Input):
    pdf_url: str | None = Field(
        None, description="Public HTTPS URL to download the PDF from"
    )
    pdf_base64: str | None = Field(
        None, description="PDF file encoded as a base64 string"
    )

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.pdf_url) == bool(self.pdf_base64):
            raise ValueError("Provide exactly one PDF URL or base64 input")
        if self.pdf_url and not self.pdf_url.startswith("https://"):
            raise ValueError("PDF URL must use public HTTPS")
        return self


class CreatePdfConfig(_Path):
    "Generate PDF from template"

    operation: Literal["create_pdf"] = Field(
        "create_pdf", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(
        ...,
        min_length=12,
        max_length=12,
        description="Template short ID (12 characters)",
    )
    data: dict[str, Any] = Field(
        ...,
        description="Key-value data to render in the template. Keys must match template variables.",
    )
    export_type: Literal["url"] = Field(
        "url", description="Return a signed PDF URL; binary delivery is not exposed."
    )
    expiration: int = Field(
        86400,
        ge=60.0,
        le=604800.0,
        description="URL expiration in seconds. Min: 60 (1 min), Max: 604800 (7 days). Only applies to `url` export type.",
    )
    filename: str | None = Field(
        None,
        max_length=100,
        pattern="^[a-zA-Z0-9_\\-\\.]+$",
        description="Custom filename for the PDF (without .pdf extension). If not provided, defaults to 'document'. Only applies to `url` export type.",
    )
    store_s3: bool = Field(
        False, description="Upload to your configured S3 bucket instead of CDN"
    )
    s3_filepath: str | None = Field(
        None,
        max_length=500,
        pattern="^[a-zA-Z0-9_\\-\\./]+$",
        description="Custom path prefix in your S3 bucket. Uses default prefix if not provided.",
    )
    s3_bucket: str | None = Field(
        None,
        min_length=3,
        max_length=63,
        pattern="^[a-z0-9][a-z0-9.\\-]*[a-z0-9]$",
        description="Override the default bucket configured in your S3 integration.",
    )
    pdf_variant: Literal["pdf/a-1b", "pdf/a-2b", "pdf/a-3b"] | None = Field(
        None,
        description="Generate a standards-compliant PDF variant. Use `pdf/a-2b` for archival compliance (most common). Use `pdf/a-3b` if you need file attachments (e.g. Factur-X, ZUGFeRD). When not set, a standard PDF is generated.",
    )
    version: str | None = Field(
        None,
        max_length=50,
        description="Optional version tag (e.g. `prod`) or version number (e.g. `3`). When omitted, uses the current draft.",
    )


class CreateImageConfig(_Path):
    "Generate image from template"

    operation: Literal["create_image"] = Field(
        "create_image", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(
        ...,
        min_length=12,
        max_length=12,
        description="Template short ID (12 characters)",
    )
    modifications: list[Modification] | None = Field(
        None,
        max_length=100,
        description="Modify template elements by their layer name (set in the editor's Layers panel). Each item targets a layer and can set its text, image, colors, or visibility. Unknown layer names are skipped and reported in the response `warnings`.",
    )
    data: dict[str, Any] | None = Field(
        None,
        description="Optional key-value data merged into `{{ }}` template variables. For most image templates, prefer `modifications` instead.",
    )
    format: Literal["png", "jpeg", "webp"] = Field(
        "png", description="Output image format: `png` (default), `jpeg` or `webp`."
    )
    width: int | None = Field(
        None,
        ge=100.0,
        le=4000.0,
        description="Output width in pixels (height follows the template aspect ratio). Defaults to the template's native pixel width.",
    )
    quality: int = Field(
        85,
        ge=1.0,
        le=100.0,
        description="Compression quality for `jpeg`/`webp` (1-100). Ignored for `png`.",
    )
    export_type: Literal["url"] = Field(
        "url", description="Return a signed image URL; binary delivery is not exposed."
    )
    expiration: int = Field(
        86400,
        ge=60.0,
        le=604800.0,
        description="URL expiration in seconds. Min: 60 (1 min), Max: 604800 (7 days). Only applies to `url` export type.",
    )
    filename: str | None = Field(
        None,
        max_length=100,
        pattern="^[a-zA-Z0-9_\\-\\.]+$",
        description="Custom filename (without extension). If not provided, defaults to 'document'. Only applies to `url` export type.",
    )
    store_s3: bool = Field(
        False, description="Upload to your configured S3 bucket instead of CDN"
    )
    s3_filepath: str | None = Field(
        None,
        max_length=500,
        pattern="^[a-zA-Z0-9_\\-\\./]+$",
        description="Custom path prefix in your S3 bucket. Uses default prefix if not provided.",
    )
    s3_bucket: str | None = Field(
        None,
        min_length=3,
        max_length=63,
        pattern="^[a-z0-9][a-z0-9.\\-]*[a-z0-9]$",
        description="Override the default bucket configured in your S3 integration.",
    )
    version: str | None = Field(
        None,
        max_length=50,
        description="Optional version tag (e.g. `prod`) or version number (e.g. `3`). When omitted, uses the current draft.",
    )


class CreatePdfAsyncConfig(_Path):
    "Generate PDF asynchronously"

    operation: Literal["create_pdf_async"] = Field(
        "create_pdf_async", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(
        ...,
        min_length=12,
        max_length=12,
        description="Template short ID (12 characters)",
    )
    data: dict[str, Any] = Field(
        ..., description="Key-value data to render in the template."
    )
    export_type: Literal["url"] = Field(
        "url", description="Export format. Currently only `url` is supported for async."
    )
    expiration: int = Field(
        86400,
        ge=60.0,
        le=604800.0,
        description="URL expiration in seconds (60-604800). Default: 86400 (24 hours).",
    )
    filename: str | None = Field(
        None,
        max_length=100,
        pattern="^[a-zA-Z0-9_\\-\\.]+$",
        description="Custom filename for the PDF (without .pdf extension).",
    )
    store_s3: bool = Field(
        False, description="Upload to your configured S3 bucket instead of CDN."
    )
    s3_filepath: str | None = Field(
        None,
        max_length=500,
        pattern="^[a-zA-Z0-9_\\-\\./]+$",
        description="Custom path prefix in your S3 bucket.",
    )
    s3_bucket: str | None = Field(
        None,
        min_length=3,
        max_length=63,
        pattern="^[a-z0-9][a-z0-9.\\-]*[a-z0-9]$",
        description="Override the default bucket configured in your S3 integration.",
    )
    webhook_url: str | None = Field(
        None,
        min_length=1,
        max_length=2083,
        pattern="^https://",
        description="URL to receive POST notification when job completes or fails. Must be a public HTTPS URL.",
    )
    webhook_secret: str | None = Field(
        None,
        min_length=16,
        max_length=256,
        description="Secret for HMAC-SHA256 signing of webhook payloads (min 16 chars).",
        json_schema_extra={"ui:widget": "password"},
    )
    pdf_variant: Literal["pdf/a-1b", "pdf/a-2b", "pdf/a-3b"] | None = Field(
        None,
        description="Generate a standards-compliant PDF variant. Use `pdf/a-3b` for archival compliance (most common). Use `pdf/a-3b` if you need file attachments (e.g. Factur-X). When not set, a standard PDF is generated.",
    )
    version: str | None = Field(
        None,
        max_length=50,
        description="Optional version tag (e.g. `prod`) or version number (e.g. `3`). When omitted, uses the template's default version if set, otherwise the current draft.",
    )


class GetPdfJobConfig(_Path):
    "Get PDF job status"

    operation: Literal["get_pdf_job"] = Field(
        "get_pdf_job", json_schema_extra={"ui:hidden": True}
    )
    job_id: str = Field(
        ..., description="Async job ID (UUID returned by the create-async endpoint)"
    )


class ListPdfJobsConfig(_Path):
    "List PDF jobs"

    operation: Literal["list_pdf_jobs"] = Field(
        "list_pdf_jobs", json_schema_extra={"ui:hidden": True}
    )
    limit: int = Field(20, description="Maximum number of results to return")
    offset: int = Field(0, description="Number of results to skip (for pagination)")
    status: Literal["pending", "processing", "completed", "failed"] | None = Field(
        None, description="Filter jobs by status"
    )


class MergePdfConfig(_Path):
    "Merge PDFs"

    operation: Literal["merge_pdf"] = Field(
        "merge_pdf", json_schema_extra={"ui:hidden": True}
    )
    export_type: Literal["url"] = Field(
        "url", description="Return a signed PDF URL; binary delivery is not exposed."
    )
    expiration: int = Field(
        86400,
        ge=60.0,
        le=604800.0,
        description="URL expiration in seconds. Min 60, max 604800. Only applies to `url` export type.",
    )
    filename: str | None = Field(
        None,
        max_length=100,
        pattern="^[a-zA-Z0-9_\\-\\.]+$",
        description="Custom filename (without `.pdf`). Defaults to a generic name.",
    )
    pdfs: list[PdfInput] = Field(
        ...,
        min_length=2,
        description="Ordered list of PDFs to merge. Each entry has either `pdf_url` or `pdf_base64`. Minimum 2.",
    )


class ExtractPdfPagesConfig(_Path):
    "Extract pages from a PDF"

    operation: Literal["extract_pdf_pages"] = Field(
        "extract_pdf_pages", json_schema_extra={"ui:hidden": True}
    )
    export_type: Literal["url"] = Field(
        "url", description="Return a signed PDF URL; binary delivery is not exposed."
    )
    expiration: int = Field(
        86400,
        ge=60.0,
        le=604800.0,
        description="URL expiration in seconds. Min 60, max 604800. Only applies to `url` export type.",
    )
    filename: str | None = Field(
        None,
        max_length=100,
        pattern="^[a-zA-Z0-9_\\-\\.]+$",
        description="Custom filename (without `.pdf`). Defaults to a generic name.",
    )
    pdf_url: str | None = Field(
        None, description="Public HTTPS URL to download the PDF from"
    )
    pdf_base64: str | None = Field(
        None, description="PDF file encoded as a base64 string"
    )
    pages: str = Field(
        ...,
        description="1-indexed page selection. Supports ranges and singles separated by commas, e.g. `1-3, 5, 7-9`. Order is preserved (`5,1,3` outputs those 3 pages in that order).",
    )

    @model_validator(mode="after")
    def source_and_selection(self):
        PdfInput(pdf_url=self.pdf_url, pdf_base64=self.pdf_base64)
        return self


class RotatePdfConfig(_Path):
    "Rotate pages of a PDF"

    operation: Literal["rotate_pdf"] = Field(
        "rotate_pdf", json_schema_extra={"ui:hidden": True}
    )
    export_type: Literal["url"] = Field(
        "url", description="Return a signed PDF URL; binary delivery is not exposed."
    )
    expiration: int = Field(
        86400,
        ge=60.0,
        le=604800.0,
        description="URL expiration in seconds. Min 60, max 604800. Only applies to `url` export type.",
    )
    filename: str | None = Field(
        None,
        max_length=100,
        pattern="^[a-zA-Z0-9_\\-\\.]+$",
        description="Custom filename (without `.pdf`). Defaults to a generic name.",
    )
    pdf_url: str | None = Field(
        None, description="Public HTTPS URL to download the PDF from"
    )
    pdf_base64: str | None = Field(
        None, description="PDF file encoded as a base64 string"
    )
    rotation: int | None = Field(
        None,
        description="Rotation in degrees applied to every page. Must be 0, 90, 180 or 270. Cumulative with the page's existing rotation.",
    )
    page_rotations: dict[str, int] | None = Field(
        None,
        description="1-indexed map of page number to rotation in degrees (0/90/180/270). Cumulative with the page's existing rotation. Use this OR `rotation`, not both.",
    )

    @model_validator(mode="after")
    def source_and_selection(self):
        PdfInput(pdf_url=self.pdf_url, pdf_base64=self.pdf_base64)
        if (self.rotation is None) == (self.page_rotations is None):
            raise ValueError("Choose rotation or per-page rotations")
        values = (
            [self.rotation]
            if self.rotation is not None
            else list(self.page_rotations.values())
        )
        if not values or any(v not in {0, 90, 180, 270} for v in values):
            raise ValueError("Rotation must be 0, 90, 180 or 270 degrees")
        if self.page_rotations and any(
            not k.isdigit() or int(k) < 1 for k in self.page_rotations
        ):
            raise ValueError("Page numbers start at 1")
        return self


class ListTemplatesConfig(_Path):
    "List templates"

    operation: Literal["list_templates"] = Field(
        "list_templates", json_schema_extra={"ui:hidden": True}
    )
    kind: str | None = Field(
        None,
        pattern="^(pdf|image)$",
        description="Filter by product kind: `pdf` or `image`",
    )


class GetTemplateFieldsConfig(_Path):
    "Get template fields"

    operation: Literal["get_template_fields"] = Field(
        "get_template_fields", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(..., description="Template short ID (12 characters)")


class GetTemplateLayersConfig(_Path):
    "Get template layers"

    operation: Literal["get_template_layers"] = Field(
        "get_template_layers", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(..., description="Template short ID (12 characters)")


class ListTemplateVersionsConfig(_Path):
    "List template versions"

    operation: Literal["list_template_versions"] = Field(
        "list_template_versions", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(..., description="Template short ID (12 characters)")


class CreateTemplateVersionConfig(_Path):
    "Create a version snapshot"

    operation: Literal["create_template_version"] = Field(
        "create_template_version", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(..., description="Template short ID (12 characters)")
    tag: str = Field(
        ...,
        min_length=2,
        max_length=50,
        pattern="^[a-z0-9][a-z0-9_-]{0,48}[a-z0-9]$",
        description="Version tag (e.g. 'prod', 'staging', 'v1'). Lowercase alphanumeric with hyphens/underscores, 2-50 chars.",
    )
    description: str | None = Field(
        None, max_length=500, description="Optional description for this version"
    )


class DeleteTemplateVersionConfig(_Path):
    "Delete a version"

    operation: Literal["delete_template_version"] = Field(
        "delete_template_version", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(..., description="Template short ID")
    version_number: int = Field(..., description="Version number to delete")


class UpdateTemplateVersionConfig(_Path):
    "Update a version"

    operation: Literal["update_template_version"] = Field(
        "update_template_version", json_schema_extra={"ui:hidden": True}
    )
    template_id: str = Field(..., description="Template short ID")
    version_number: int = Field(..., description="Version number to update")
    tag: str | None = Field(
        None, max_length=50, pattern="^[a-z0-9][a-z0-9_-]{0,48}[a-z0-9]$"
    )
    description: str | None = Field(None, max_length=500)

    @field_validator("tag", "description", mode="before")
    @classmethod
    def clear_value(cls, value):
        # The workflow factory represents explicit null string inputs as empty strings.
        return None if value == "" else value


class GetAccountConfig(_Path):
    "Get account info"

    operation: Literal["get_account"] = Field(
        "get_account", json_schema_extra={"ui:hidden": True}
    )


class ListTransactionsConfig(_Path):
    "List transactions"

    operation: Literal["list_transactions"] = Field(
        "list_transactions", json_schema_extra={"ui:hidden": True}
    )
    limit: int = Field(300, ge=1, le=1000, description="Number of records to return")
    offset: int = Field(0, ge=0, description="Number of records to skip")


TemplatefoxConfig = Annotated[
    Union[
        CreatePdfConfig,
        CreateImageConfig,
        CreatePdfAsyncConfig,
        GetPdfJobConfig,
        ListPdfJobsConfig,
        MergePdfConfig,
        ExtractPdfPagesConfig,
        RotatePdfConfig,
        ListTemplatesConfig,
        GetTemplateFieldsConfig,
        GetTemplateLayersConfig,
        ListTemplateVersionsConfig,
        CreateTemplateVersionConfig,
        DeleteTemplateVersionConfig,
        UpdateTemplateVersionConfig,
        GetAccountConfig,
        ListTransactionsConfig,
    ],
    Field(discriminator="operation"),
]


class TemplatefoxNodeConfig(NodeConfig[TemplatefoxConfig, TemplatefoxAPIKeyCredential]):
    pass


ROUTES = {
    "create_pdf": ("POST", "/v1/pdf/create", []),
    "create_image": ("POST", "/v1/image/create", []),
    "create_pdf_async": ("POST", "/v1/pdf/create-async", []),
    "get_pdf_job": ("GET", "/v1/pdf/jobs/{job_id}", []),
    "list_pdf_jobs": ("GET", "/v1/pdf/jobs", ["limit", "offset", "status"]),
    "merge_pdf": ("POST", "/v1/pdf-tools/merge", []),
    "extract_pdf_pages": ("POST", "/v1/pdf-tools/extract-pages", []),
    "rotate_pdf": ("POST", "/v1/pdf-tools/rotate", []),
    "list_templates": ("GET", "/v1/templates", ["kind"]),
    "get_template_fields": ("GET", "/v1/templates/{template_id}/fields", []),
    "get_template_layers": ("GET", "/v1/templates/{template_id}/layers", []),
    "list_template_versions": ("GET", "/v1/templates/{template_id}/versions", []),
    "create_template_version": ("POST", "/v1/templates/{template_id}/versions", []),
    "delete_template_version": (
        "DELETE",
        "/v1/templates/{template_id}/versions/{version_number}",
        [],
    ),
    "update_template_version": (
        "PATCH",
        "/v1/templates/{template_id}/versions/{version_number}",
        [],
    ),
    "get_account": ("GET", "/v1/account", []),
    "list_transactions": ("GET", "/v1/account/transactions", ["limit", "offset"]),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    return value


class TemplatefoxNode(WorkflowNode):
    integration_type = "automation-templatefox"
    connection_evidence = ConnectionEvidence(
        noun="TemplateFox account", operation="get_account", label_keys=("email",)
    )

    @classmethod
    def get_config_model(cls):
        return TemplatefoxNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a TemplateFox API key")
        op = self.config.config
        key = self.config.credentials.api_key
        secrets = [key, getattr(op, "webhook_secret", None)]
        method, path, query_fields = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        # PATCH distinguishes omitted properties from explicit null (clear a field).
        if method == "PATCH":
            values = op.model_dump(exclude={"operation"}, exclude_unset=True)
        for name in ("template_id", "job_id", "version_number"):
            if "{" + name + "}" in path:
                path = path.replace(
                    "{" + name + "}", quote(str(values.pop(name)), safe="")
                )
        params = {name: values.pop(name) for name in query_fields if name in values}
        try:
            async with httpx.AsyncClient(
                timeout=120.0, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + path,
                    headers={"x-api-key": key, "Accept": "application/json"},
                    params=params or None,
                    json=values if method in {"POST", "PATCH"} else None,
                )
            if not 200 <= response.status_code < 300:
                try:
                    detail = response.json()
                except ValueError:
                    detail = "TemplateFox returned an HTTP error"
                result = {
                    "status": "error",
                    "http_status": response.status_code,
                    "message": _redact(str(detail), secrets),
                }
            else:
                data = response.json()
                if op.operation != "delete_template_version" and not isinstance(
                    data, (dict, list)
                ):
                    raise ValueError("Expected a TemplateFox JSON object or array")
                if op.operation == "get_account" and (
                    not isinstance(data, dict) or type(data.get("credits")) is not int
                ):
                    raise ValueError("Account credit balance is missing")
                if isinstance(data, dict) and (
                    data.get("success") is False
                    or data.get("error")
                    or data.get("detail")
                ):
                    result = {"status": "error", "message": _redact(str(data), secrets)}
                else:
                    result = {"status": "success", "data": _redact(data, secrets)}
        except httpx.RequestError:
            result = {
                "status": "error",
                "message": "TemplateFox request could not be confirmed; inspect the provider before retrying a write",
            }
        except ValueError:
            result = {
                "status": "error",
                "message": "TemplateFox returned an unexpected response; inspect the provider before retrying a write",
            }
        await self.emit(result)
        return result
