"""PDF.co document automation, pinned to the provider's OpenAPI v1.0.

Docs/spec: https://developer.pdf.co/openapi.json
Authentication: a pasted API key, sent only in the x-api-key header.
Each operation makes one documented API call. Async submissions return jobId;
use Get Job Status to check completion. PDF.co output links expire (normally
60 minutes); download/store the result in a later workflow step.
PDF.co supports per-job callbacks, not an account event subscription; this node
provides explicit polling and does not register a webhook trigger.
"""
from __future__ import annotations

import time
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://api.pdf.co"


class PDFCoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="PDF.co API Key", json_schema_extra={
        "x-credential-url": "https://app.pdf.co/account",
        "x-credential-instructions": "Copy your API key from the PDF.co dashboard and paste it here. NoClick checks your remaining account credits when you connect.",
    })
    credential_type: Literal["pdfco_api_key"] = Field("pdfco_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False,
        description="Your PDF.co API key from the dashboard.", json_schema_extra={"ui:widget": "password"})


class _Source(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    url: str = Field(..., min_length=1, title="Source URL", description="Direct file URL accessible to PDF.co, or a PDF.co filetoken:// link. The source is fetched by PDF.co.")


class _FileJob(_Source):
    name: str | None = Field(None, title="Output File Name")
    async_mode: bool = Field(False, alias="async", title="Run Asynchronously", description="Return a jobId instead of waiting for the result. Check it using Get Job Status.")
    expiration: int | None = Field(None, ge=1, title="Link Expiration (minutes)", description="Output links are temporary. Maximum expiration depends on your PDF.co plan.")


class _PDFJob(_FileJob):
    password: str | None = Field(None, title="PDF Password", json_schema_extra={"ui:widget": "password"})


class _Extract(_PDFJob):
    pages: str | None = Field(None, title="Pages", description="Zero-based page ranges, for example 0,2,5-10. Omit to process all pages.")
    lang: str = Field("eng", pattern=r"^[a-z]{3}(\+[a-z]{3})*$", title="OCR Languages", description="Three-letter OCR language codes, for example eng or eng+deu.")


class _InlineExtract(_Extract):
    inline: bool = Field(True, title="Return Inline Content", description="Return extracted content in body instead of only a temporary download URL.")


class PDFCoGetAccountBalanceConfig(BaseModel):
    """Get Account Balance. GET /v1/account/credit/balance

    https://developer.pdf.co/api/account-balance-info
    """
    operation: Literal["get_account_balance"] = Field("get_account_balance", title="Get Account Balance", json_schema_extra={"const": "get_account_balance", "ui:hidden": True, "x-display-name": "Get Account Balance", "x-category": "Account", "x-is-trigger": False})


class PDFCoListParserTemplatesConfig(BaseModel):
    """List Parser Templates. GET /v1/pdf/documentparser/templates

    https://developer.pdf.co/api/documentparser/templates
    """
    operation: Literal["list_parser_templates"] = Field("list_parser_templates", title="List Parser Templates", json_schema_extra={"const": "list_parser_templates", "ui:hidden": True, "x-display-name": "List Parser Templates", "x-category": "Extraction", "x-is-trigger": False})


class PDFCoParseDocumentConfig(_PDFJob):
    """Parse Document. POST /v1/pdf/documentparser

    https://developer.pdf.co/api/documentparser/parser
    """
    operation: Literal["parse_document"] = Field("parse_document", title="Parse Document", json_schema_extra={"const": "parse_document", "ui:hidden": True, "x-display-name": "Parse Document", "x-category": "Extraction", "x-is-trigger": False})
    template_id: int = Field(..., alias="templateid", title="Parser Template ID", description="An ID returned by List Parser Templates.")
    output_format: Literal["JSON", "YAML", "XML", "CSV"] = Field("JSON", alias="outputformat", title="Output Format")
    inline: bool = Field(True, title="Return Inline Content")
    pages: str | None = Field(None, title="Pages", description="Zero-based page ranges. Omit to process all pages.")


class PDFCoParseInvoiceConfig(_Source):
    """Parse Invoice with AI. POST /v1/ai-invoice-parser

    https://developer.pdf.co/api/ai-invoice-parser
    """
    operation: Literal["parse_invoice"] = Field("parse_invoice", title="Parse Invoice with AI", json_schema_extra={"const": "parse_invoice", "ui:hidden": True, "x-display-name": "Parse Invoice with AI", "x-category": "Extraction", "x-is-trigger": False})
    custom_fields: str | None = Field(None, alias="customfield", title="Custom Fields", description="Additional camelCase field names to extract, as documented by PDF.co.")
    callback: str | None = Field(None, title="Callback URL", description="Optional HTTPS URL to receive completion. Otherwise use Get Job Status with the returned jobId.")


class PDFCoPdfToTextConfig(_InlineExtract):
    """PDF to Text. POST /v1/pdf/convert/to/text

    https://developer.pdf.co/api/pdf-to-text/basic
    """
    operation: Literal["pdf_to_text"] = Field("pdf_to_text", title="PDF to Text", json_schema_extra={"const": "pdf_to_text", "ui:hidden": True, "x-display-name": "PDF to Text", "x-category": "Extraction", "x-is-trigger": False})


class PDFCoPdfToCsvConfig(_InlineExtract):
    """PDF to CSV. POST /v1/pdf/convert/to/csv

    https://developer.pdf.co/api/pdf-to-csv
    """
    operation: Literal["pdf_to_csv"] = Field("pdf_to_csv", title="PDF to CSV", json_schema_extra={"const": "pdf_to_csv", "ui:hidden": True, "x-display-name": "PDF to CSV", "x-category": "Extraction", "x-is-trigger": False})


class PDFCoPdfToXlsxConfig(_Extract):
    """PDF to Excel. POST /v1/pdf/convert/to/xlsx

    https://developer.pdf.co/api/pdf-to-excel/xlsx
    """
    operation: Literal["pdf_to_xlsx"] = Field("pdf_to_xlsx", title="PDF to Excel", json_schema_extra={"const": "pdf_to_xlsx", "ui:hidden": True, "x-display-name": "PDF to Excel", "x-category": "Extraction", "x-is-trigger": False})


class PDFCoPdfToJsonConfig(_InlineExtract):
    """PDF to JSON. POST /v1/pdf/convert/to/json2

    https://developer.pdf.co/api/pdf-to-json/basic
    """
    operation: Literal["pdf_to_json"] = Field("pdf_to_json", title="PDF to JSON", json_schema_extra={"const": "pdf_to_json", "ui:hidden": True, "x-display-name": "PDF to JSON", "x-category": "Extraction", "x-is-trigger": False})


class PDFCoUrlToPdfConfig(_FileJob):
    """Web Page to PDF. POST /v1/pdf/convert/from/url

    https://developer.pdf.co/api/pdf-from-url
    """
    operation: Literal["url_to_pdf"] = Field("url_to_pdf", title="Web Page to PDF", json_schema_extra={"const": "url_to_pdf", "ui:hidden": True, "x-display-name": "Web Page to PDF", "x-category": "PDF", "x-is-trigger": False})
    margins: str | None = Field(None, title="Margins", description="CSS margins, for example 5mm.")
    papersize: str | None = Field(None, title="Paper Size", description="For example Letter or A4.")
    orientation: Literal["Portrait", "Landscape"] | None = Field(None, title="Orientation")
    printbackground: bool | None = Field(None, title="Print Background")


class PDFCoDocumentToPdfConfig(_FileJob):
    """Document to PDF. POST /v1/pdf/convert/from/doc

    https://developer.pdf.co/api/pdf-from-document/doc
    """
    operation: Literal["document_to_pdf"] = Field("document_to_pdf", title="Document to PDF", json_schema_extra={"const": "document_to_pdf", "ui:hidden": True, "x-display-name": "Document to PDF", "x-category": "PDF", "x-is-trigger": False})


class PDFCoImagesToPdfConfig(_FileJob):
    """Images to PDF. POST /v1/pdf/convert/from/image

    https://developer.pdf.co/api/pdf-from-image
    """
    operation: Literal["images_to_pdf"] = Field("images_to_pdf", title="Images to PDF", json_schema_extra={"const": "images_to_pdf", "ui:hidden": True, "x-display-name": "Images to PDF", "x-category": "PDF", "x-is-trigger": False})
    url: str = Field(..., min_length=1, title="Image URLs", description="One or more direct JPG, PNG or TIFF URLs, separated by commas.")


class PDFCoMergePdfConfig(_FileJob):
    """Merge PDF. POST /v1/pdf/merge

    https://developer.pdf.co/api/merge/pdf
    """
    operation: Literal["merge_pdf"] = Field("merge_pdf", title="Merge PDF", json_schema_extra={"const": "merge_pdf", "ui:hidden": True, "x-display-name": "Merge PDF", "x-category": "PDF", "x-is-trigger": False})
    url: str = Field(..., min_length=1, title="PDF URLs", description="Direct PDF URLs separated by commas, in merge order.")


class PDFCoSplitPdfConfig(_PDFJob):
    """Split PDF. POST /v1/pdf/split

    https://developer.pdf.co/api/pdf-split/by-pages
    """
    operation: Literal["split_pdf"] = Field("split_pdf", title="Split PDF", json_schema_extra={"const": "split_pdf", "ui:hidden": True, "x-display-name": "Split PDF", "x-category": "PDF", "x-is-trigger": False})
    pages: str = Field(..., min_length=1, title="Page Groups", description="One-based ranges separated by commas, for example 1-2,3-. Each group becomes a separate PDF.")


class PDFCoGetPdfInfoConfig(_Source):
    """Get PDF Info. POST /v1/pdf/info

    https://developer.pdf.co/api/pdf-info-reader
    """
    operation: Literal["get_pdf_info"] = Field("get_pdf_info", title="Get PDF Info", json_schema_extra={"const": "get_pdf_info", "ui:hidden": True, "x-display-name": "Get PDF Info", "x-category": "Extraction", "x-is-trigger": False})
    async_mode: bool = Field(False, alias="async", title="Run Asynchronously")
    password: str | None = Field(None, title="PDF Password", json_schema_extra={"ui:widget": "password"})


class PDFCoGetFormFieldsConfig(_Source):
    """Get Form Fields. POST /v1/pdf/info/fields

    https://developer.pdf.co/api/forms/info-reader
    """
    operation: Literal["get_form_fields"] = Field("get_form_fields", title="Get Form Fields", json_schema_extra={"const": "get_form_fields", "ui:hidden": True, "x-display-name": "Get Form Fields", "x-category": "Extraction", "x-is-trigger": False})
    async_mode: bool = Field(False, alias="async", title="Run Asynchronously")
    password: str | None = Field(None, title="PDF Password", json_schema_extra={"ui:widget": "password"})


class PDFCoAddTextConfig(_PDFJob):
    """Add Text to PDF. POST /v1/pdf/edit/add

    https://developer.pdf.co/api/pdf-add
    """
    operation: Literal["add_text"] = Field("add_text", title="Add Text to PDF", json_schema_extra={"const": "add_text", "ui:hidden": True, "x-display-name": "Add Text to PDF", "x-category": "PDF", "x-is-trigger": False})
    annotations_string: str = Field(..., alias="annotationsString", min_length=1, title="Text Annotations", description="Semicolon-separated x;y;pages;text;fontsize;fontname;fontcolor;link;transparent values. Separate multiple annotations with |. Pages start at zero.", json_schema_extra={"ui:widget": "textarea"})


class PDFCoGetJobStatusConfig(BaseModel):
    """Get Job Status. POST /v1/job/check

    https://developer.pdf.co/api/job-check
    """
    operation: Literal["get_job_status"] = Field("get_job_status", title="Get Job Status", json_schema_extra={"const": "get_job_status", "ui:hidden": True, "x-display-name": "Get Job Status", "x-category": "Account", "x-is-trigger": False})
    jobid: str = Field(..., min_length=1, title="Job ID", description="The jobId returned by an asynchronous PDF.co operation. Only working jobs should be polled again.")


class PDFCoMakeSearchableConfig(_Extract):
    """Make PDF Searchable. POST /v1/pdf/makesearchable

    https://developer.pdf.co/api/pdf-change-text-searchable/searchable
    """
    operation: Literal["make_searchable"] = Field("make_searchable", title="Make PDF Searchable", json_schema_extra={"const": "make_searchable", "ui:hidden": True, "x-display-name": "Make PDF Searchable", "x-category": "PDF", "x-is-trigger": False})


class PDFCoCompressPdfConfig(_PDFJob):
    """Compress PDF. POST /v2/pdf/compress

    https://developer.pdf.co/api/pdf-compress
    """
    operation: Literal["compress_pdf"] = Field("compress_pdf", title="Compress PDF", json_schema_extra={"const": "compress_pdf", "ui:hidden": True, "x-display-name": "Compress PDF", "x-category": "PDF", "x-is-trigger": False})
    compression_level: Literal["low", "medium", "high", "aggressive"] = Field("medium", alias="compressionLevel", title="Compression Level")
    color_quality: int | None = Field(None, alias="colorQuality", ge=1, le=100, title="Image Quality", description="JPEG image quality, from 1 (smallest) to 100 (highest quality).")


class PDFCoUploadFileFromUrlConfig(_Source):
    """Upload File from URL. POST /v1/file/upload/url

    https://developer.pdf.co/api/file-upload/upload-url-post
    """
    operation: Literal["upload_file_from_url"] = Field("upload_file_from_url", title="Upload File from URL", json_schema_extra={"const": "upload_file_from_url", "ui:hidden": True, "x-display-name": "Upload File from URL", "x-category": "Account", "x-is-trigger": False})
    name: str | None = Field(None, title="File Name")


PDFCoConfig = Annotated[Union[
    PDFCoGetAccountBalanceConfig,
    PDFCoListParserTemplatesConfig,
    PDFCoParseDocumentConfig,
    PDFCoParseInvoiceConfig,
    PDFCoPdfToTextConfig,
    PDFCoPdfToCsvConfig,
    PDFCoPdfToXlsxConfig,
    PDFCoPdfToJsonConfig,
    PDFCoUrlToPdfConfig,
    PDFCoDocumentToPdfConfig,
    PDFCoImagesToPdfConfig,
    PDFCoMergePdfConfig,
    PDFCoSplitPdfConfig,
    PDFCoGetPdfInfoConfig,
    PDFCoGetFormFieldsConfig,
    PDFCoAddTextConfig,
    PDFCoGetJobStatusConfig,
    PDFCoMakeSearchableConfig,
    PDFCoCompressPdfConfig,
    PDFCoUploadFileFromUrlConfig,
], Discriminator("operation")]


class PDFCoNodeConfig(NodeConfig[PDFCoConfig, PDFCoAPIKeyCredential]):
    model_config = ConfigDict(title="PDF.co Node Configuration")


ENDPOINTS: dict[str, tuple[str, str]] = {
    "get_account_balance": ("GET", "/v1/account/credit/balance"),
    "list_parser_templates": ("GET", "/v1/pdf/documentparser/templates"),
    "parse_document": ("POST", "/v1/pdf/documentparser"),
    "parse_invoice": ("POST", "/v1/ai-invoice-parser"),
    "pdf_to_text": ("POST", "/v1/pdf/convert/to/text"),
    "pdf_to_csv": ("POST", "/v1/pdf/convert/to/csv"),
    "pdf_to_xlsx": ("POST", "/v1/pdf/convert/to/xlsx"),
    "pdf_to_json": ("POST", "/v1/pdf/convert/to/json2"),
    "url_to_pdf": ("POST", "/v1/pdf/convert/from/url"),
    "document_to_pdf": ("POST", "/v1/pdf/convert/from/doc"),
    "images_to_pdf": ("POST", "/v1/pdf/convert/from/image"),
    "merge_pdf": ("POST", "/v1/pdf/merge"),
    "split_pdf": ("POST", "/v1/pdf/split"),
    "get_pdf_info": ("POST", "/v1/pdf/info"),
    "get_form_fields": ("POST", "/v1/pdf/info/fields"),
    "add_text": ("POST", "/v1/pdf/edit/add"),
    "get_job_status": ("POST", "/v1/job/check"),
    "make_searchable": ("POST", "/v1/pdf/makesearchable"),
    "compress_pdf": ("POST", "/v2/pdf/compress"),
    "upload_file_from_url": ("POST", "/v1/file/upload/url"),
}


class PDFCoNode(WorkflowNode):
    integration_type = "automation-pdfco"
    credential_provider_labels = {"pdfco": "Pdfco Account"}
    connection_evidence = ConnectionEvidence(
        identity_operation="get_account_balance", noun="remaining credits",
        identity_keys=("remainingCredits",),
    )
    edit_examples = ["Extract invoice data with PDF.co", "Convert a PDF to an Excel spreadsheet", "Merge two PDFs", "Generate a PDF from a web page"]

    @classmethod
    def get_config_model(cls):
        return PDFCoNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        config = self.config
        if not isinstance(config, PDFCoNodeConfig):
            raise ValueError("PDF.co configuration is required")
        if not config.credentials:
            raise ValueError("Connect a PDF.co API key in the credentials tab")
        operation = config.config.operation
        method, path = ENDPOINTS[operation]
        body = config.config.model_dump(by_alias=True, exclude={"operation"}, exclude_none=True)
        start = time.perf_counter()

        def result_error(message: str, status_code: int) -> dict[str, Any]:
            return {"status": "error", "action": operation, "error": message,
                    "status_code": status_code,
                    "timing_ms": {"api_request": round((time.perf_counter() - start) * 1000, 2)}}

        try:
            # Fixed provider host; input document URLs are sent to PDF.co in the
            # JSON body. Never follow an API redirect carrying the account key.
            async with httpx.AsyncClient(timeout=65.0, follow_redirects=False) as client:
                response = await client.request(
                    method, API_BASE + path,
                    headers={"x-api-key": config.credentials.api_key, "Accept": "application/json"},
                    **({"json": body} if method != "GET" else {}),
                )
        except httpx.TimeoutException:
            return result_error("PDF.co request timed out. Use asynchronous mode for large documents.", 408)
        except httpx.RequestError:
            return result_error("Could not reach the PDF.co API", 502)
        try:
            data = response.json()
        except ValueError:
            return result_error("PDF.co returned a non-JSON response", response.status_code)
        if not isinstance(data, dict) or not data:
            return result_error("PDF.co returned an unexpected response", response.status_code)
        status = data.get("status")
        failed_status = (isinstance(status, (int, float)) and status >= 400) or status in ("error", "failed", "aborted")
        if not 200 <= response.status_code < 300 or data.get("error") or failed_status:
            # Keep the provider's rejection text so manual connect can explain
            # an invalid key. Redact a provider echo of the actual credential.
            message = data.get("message") or data.get("error") or f"PDF.co request failed (HTTP {response.status_code})"
            message = str(message).replace(config.credentials.api_key, "[redacted]")
            code = data.get("errorCode", status)
            if isinstance(code, bool) or not isinstance(code, int) or code < 400:
                code = response.status_code if response.status_code >= 400 else 400
            return result_error(message, code)
        if operation == "get_account_balance":
            credits = data.get("remainingCredits")
            if isinstance(credits, bool) or not isinstance(credits, (int, float)):
                # A shape surprise cannot prove or reject a credential. The
                # shared connect seam treats this exception as unverified.
                raise ValueError("PDF.co returned an unexpected account balance response")
        return {"status": "success", "action": operation, "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": round((time.perf_counter() - start) * 1000, 2)}}
