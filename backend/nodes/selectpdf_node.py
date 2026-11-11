"""SelectPdf REST v2, pinned to https://selectpdf.com/api/selectpdf-swagger.json.

Each task makes one documented POST. PDF bytes use the shared BinaryOutput
resolver for workflow file storage and context-free results; async
submission returns a job ID for an explicit later read. No automatic retries of
billable conversions. No webhook or chronological list API is published.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://selectpdf.com"


def _url(value):
    if value is None:
        return value
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Use an absolute HTTP or HTTPS source URL without embedded credentials")
    return value


class SelectPdfAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SelectPdf API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://selectpdf.com/api/",
            "x-help-url": "https://selectpdf.com/html-to-pdf-api/",
            "x-credential-instructions": "Paste your SelectPdf license key from your API account. NoClick sends it as key in the HTTPS request body to selectpdf.com. Connection verification reads your subscription and conversion usage without generating a PDF.",
        })
    credential_type: Literal["selectpdf_api_key"] = Field("selectpdf_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the license key without spaces or a header prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Conversion(_Operation):
    page_size: Literal["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "Letter", "HalfLetter", "Ledger", "Legal"] = "A4"
    page_orientation: Literal["Portrait", "Landscape"] = "Portrait"
    engine: Literal["WebKit", "Restricted", "Blink", "Chromium"] = "Chromium"
    margin_top: int = Field(0, ge=0)
    margin_bottom: int = Field(0, ge=0)
    margin_left: int = Field(0, ge=0)
    margin_right: int = Field(0, ge=0)
    pdf_name: str | None = Field(None, title="PDF filename")
    doc_title: str | None = None
    doc_author: str | None = None
    page_numbers: StrictBool = False
    show_header: StrictBool = False
    header_html: str | None = None
    header_height: int | None = Field(None, ge=0)
    show_footer: StrictBool = False
    footer_html: str | None = None
    footer_height: int | None = Field(None, ge=0)
    pdf_bookmarks_selectors: str | None = None
    pdf_hide_elements: str | None = None
    pdf_web_elements_selectors: str | None = Field(None, description="CSS selectors whose bounding boxes can be retrieved for a completed async job.")
    min_load_time: int | None = Field(None, ge=0, description="Minimum page load time in seconds, for JavaScript content.")


class _UrlConversion(_Conversion):
    url: str = Field(..., min_length=1, json_schema_extra={"format": "uri"}, description="Public web page URL; SelectPdf fetches it.")
    _validate_url = field_validator("url")(_url)


class _HtmlConversion(_Conversion):
    html: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "html"})
    base_url: str | None = Field(None, json_schema_extra={"format": "uri"}, description="Base URL for resolving relative HTML assets.")
    _validate_base_url = field_validator("base_url")(_url)


class ConvertUrl(_UrlConversion):
    """Convert a web page to PDF bytes."""
    operation: Literal["convert_url"] = Field("convert_url", json_schema_extra={"ui:hidden": True, "x-display-name": "Convert URL to PDF"})


class ConvertHtml(_HtmlConversion):
    """Convert inline HTML to PDF bytes."""
    operation: Literal["convert_html"] = Field("convert_html", json_schema_extra={"ui:hidden": True, "x-display-name": "Convert HTML to PDF"})


class StartUrlConversion(_UrlConversion):
    """Submit a web page conversion and return its asynchronous job ID."""
    operation: Literal["start_url_conversion"] = Field("start_url_conversion", json_schema_extra={"ui:hidden": True})


class StartHtmlConversion(_HtmlConversion):
    """Submit an HTML conversion and return its asynchronous job ID."""
    operation: Literal["start_html_conversion"] = Field("start_html_conversion", json_schema_extra={"ui:hidden": True})


class MergeFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(..., min_length=1, json_schema_extra={"format": "uri"}, description="Public URL of an input PDF; SelectPdf downloads it.")
    user_password: str | None = Field(None, repr=False, json_schema_extra={"ui:widget": "password"})
    _validate_url = field_validator("url")(_url)


class _Merge(_Operation):
    input_files: list[MergeFile] = Field(..., min_length=2, max_length=100, description="PDF URL inputs in merge order.")
    pdf_name: str | None = None
    doc_title: str | None = None
    doc_author: str | None = None


class MergePdfs(_Merge):
    """Merge two or more PDF URLs and return PDF bytes."""
    operation: Literal["merge_pdfs"] = Field("merge_pdfs", json_schema_extra={"ui:hidden": True, "x-display-name": "Merge PDFs"})


class StartPdfMerge(_Merge):
    """Submit a PDF merge asynchronously."""
    operation: Literal["start_pdf_merge"] = Field("start_pdf_merge", json_schema_extra={"ui:hidden": True})


class _PdfText(_Operation):
    url: str = Field(..., min_length=1, json_schema_extra={"format": "uri"}, description="Public URL of the PDF to process.")
    start_page: int = Field(1, ge=1)
    end_page: int = Field(0, ge=0, description="0 means the last page.")
    user_password: str | None = Field(None, repr=False, json_schema_extra={"ui:widget": "password"})
    text_layout: Literal["Original", "Reading"] = "Original"
    _validate_url = field_validator("url")(_url)

    @model_validator(mode="after")
    def page_order(self):
        if self.end_page and self.end_page < self.start_page:
            raise ValueError("End page must be 0 or at least the start page")
        return self


class ExtractPdfText(_PdfText):
    """Extract PDF text in original or reading order."""
    operation: Literal["extract_pdf_text"] = Field("extract_pdf_text", json_schema_extra={"ui:hidden": True, "x-display-name": "Extract PDF text"})
    output_format: Literal["Text", "Html"] = "Text"


class StartPdfTextExtraction(_PdfText):
    """Submit PDF text extraction asynchronously."""
    operation: Literal["start_pdf_text_extraction"] = Field("start_pdf_text_extraction", json_schema_extra={"ui:hidden": True})
    output_format: Literal["Text", "Html"] = "Text"


class SearchPdf(_PdfText):
    """Find text and return matching page coordinates."""
    operation: Literal["search_pdf"] = Field("search_pdf", json_schema_extra={"ui:hidden": True, "x-display-name": "Search PDF"})
    search_text: str = Field(..., min_length=1)
    case_sensitive: StrictBool = False
    whole_words_only: StrictBool = False


class _Job(_Operation):
    job_id: str = Field(..., json_schema_extra={"format": "uuid"}, description="Job UUID from a previous asynchronous submission.")

    @field_validator("job_id")
    @classmethod
    def job_uuid(cls, value):
        try:
            return str(UUID(value))
        except ValueError:
            raise ValueError("Use the job UUID returned by SelectPdf") from None


class GetAsyncJob(_Job):
    """Read an async job once: processing, or its PDF/text/JSON result."""
    operation: Literal["get_async_job"] = Field("get_async_job", json_schema_extra={"ui:hidden": True})


class GetWebElements(_Job):
    """Read matched web elements from a completed async HTML conversion."""
    operation: Literal["get_web_elements"] = Field("get_web_elements", json_schema_extra={"ui:hidden": True})


class GetUsage(_Operation):
    """Read subscription and remaining credits, optionally with monthly history."""
    operation: Literal["get_usage"] = Field("get_usage", json_schema_extra={"ui:hidden": True})
    get_history: StrictBool = False


SelectPdfOperation = Annotated[Union[ConvertUrl, ConvertHtml, StartUrlConversion, StartHtmlConversion,
    MergePdfs, StartPdfMerge, ExtractPdfText, SearchPdf, StartPdfTextExtraction, GetAsyncJob,
    GetWebElements, GetUsage], Field(discriminator="operation")]


class SelectPdfNodeConfig(NodeConfig[SelectPdfOperation, SelectPdfAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class SelectPdfNode(WorkflowNode):
    integration_type = "automation-selectpdf"
    connection_evidence = ConnectionEvidence(noun="SelectPdf subscription usage", operation="get_usage", label_keys=("name", "subscription_type"))

    @classmethod
    def get_config_model(cls):
        return SelectPdfNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a SelectPdf API key")
        config = self.config.config
        key = self.config.credentials.api_key
        body = config.model_dump(exclude_none=True, exclude={"operation"})
        body["key"] = key
        is_async = config.operation.startswith("start_")
        if isinstance(config, _Conversion):
            path = "/api2/convert"
            body["async"] = is_async
        elif isinstance(config, _Merge):
            path = "/api2/pdfmerge"
            body["async"] = is_async
            body["input_files"] = [{**row, "file_type": 1, "idx": i} for i, row in enumerate(body["input_files"], 1)]
        elif isinstance(config, _PdfText):
            path = "/api2/pdftotext"
            body.update({"async": is_async, "action": "Search" if isinstance(config, SearchPdf) else "Convert"})
        elif isinstance(config, GetAsyncJob):
            path = "/api2/asyncjob"
        elif isinstance(config, GetWebElements):
            path = "/api2/webelements"
        else:
            path = "/api2/usage"
        # No redirects (credential body) and no retries (conversions consume credits).
        async with guarded_async_client(timeout=180, trust_env=False, follow_redirects=False) as client:
            response = await client.request("POST", BASE_URL + path, json=body)
        status = response.status_code
        if status not in {200, 202}:
            message = response.text[:2000]
            for secret in [key, getattr(config, "user_password", None), *[r.user_password for r in getattr(config, "input_files", [])]]:
                if secret:
                    message = message.replace(secret, "[redacted]")
            return {"status": "error", "http_status": status, "error": message or "SelectPdf request failed"}
        if status == 202:
            if not (is_async or isinstance(config, GetAsyncJob)):
                raise ValueError("SelectPdf unexpectedly returned an asynchronous job")
            job = response.headers.get("X-SelectPdf-Job-Id", getattr(config, "job_id", None))
            if not job:
                raise ValueError("SelectPdf accepted the job without a job ID; inspect before resubmitting")
            try:
                job = str(UUID(job))
            except ValueError:
                raise ValueError("SelectPdf returned an invalid job ID") from None
            return {"status": "processing", "http_status": status, "job_id": job}
        output = {"status": "success", "http_status": status}
        if isinstance(config, (GetUsage, GetWebElements, SearchPdf)):
            data = response.json()
            if isinstance(config, GetUsage):
                if not isinstance(data, dict) or not isinstance(data.get("status"), str) or not isinstance(data.get("subscription_type"), str):
                    raise ValueError("SelectPdf returned an invalid usage response")
                if data["status"] != "License key active.":
                    return {"status": "error", "http_status": status, "error": data["status"].replace(key, "[redacted]")}
                label = data["subscription_type"]
                if all(isinstance(data.get(field), int) for field in ("used", "limit", "available")):
                    label += f": {data['used']} of {data['limit']} credits used; {data['available']} available"
                return {**output, "data": data, "items": [{"name": label}]}
            elif not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("SelectPdf returned an invalid result list")
            return {**output, "data": data}
        media = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if isinstance(config, _PdfText):
            return {**output, "text": response.text}
        if isinstance(config, GetAsyncJob) and media == "application/json":
            return {**output, "data": response.json()}
        if isinstance(config, GetAsyncJob) and media in {"text/plain", "text/html"}:
            return {**output, "text": response.text}
        if not response.content.startswith(b"%PDF-"):
            raise ValueError("SelectPdf did not return PDF bytes")
        return {**output, "file": BinaryOutput(
            data=response.content, content_type="application/pdf",
            filename=getattr(config, "pdf_name", None) or "selectpdf.pdf",
        )}
