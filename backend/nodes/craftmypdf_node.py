"""CraftMyPDF v1 document generation, PDF editing and template management.

Each operation makes one documented request. Generated files remain provider
URLs; async generation reports acceptance without claiming completion.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

DOCS = "https://craftmypdf.com/docs/"
CREDENTIAL = "craftmypdf_api_key"
BASES = {
    "singapore": "https://api.craftmypdf.com/v1",
    "europe": "https://api-de.craftmypdf.com/v1",
    "us": "https://api-us.craftmypdf.com/v1",
    "australia": "https://api-au.craftmypdf.com/v1",
}


class CraftmypdfApiKey(BaseModel):
    model_config = ConfigDict(title="CraftMyPDF API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.craftmypdf.com/",
            "x-credential-instructions": "In CraftMyPDF, open API Integration and copy your API key. Paste the key here and select your account's processing region. NoClick sends it in the X-API-KEY header and checks your account information."})
    credential_type: Literal["craftmypdf_api_key"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    region: Literal["singapore", "europe", "us", "australia"] = Field("singapore", title="Processing region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without spaces or a header prefix")
        return value


def _url(value):
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Use a public HTTP or HTTPS URL accessible to CraftMyPDF")
    return value


def _json(value):
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError("Enter valid JSON data") from None
    if not isinstance(parsed, (dict, list)):
        raise ValueError("Enter a JSON object or array")
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Template(Input):
    template_id: str = Field(..., min_length=1, max_length=256, title="Template ID")


class Page(Input):
    limit: int = Field(100, ge=1, le=300, description="Records in this page. Increase offset to fetch subsequent pages.")
    offset: int = Field(0, ge=0)


class FileOptions(Input):
    expiration: int = Field(60, ge=1, le=10080, description="Generated file lifetime in minutes.")
    output_file: str | None = Field(None, min_length=1, max_length=256)
    cloud_storage: Literal[0, 1] = Field(1, description="1 stores on CraftMyPDF CDN; 0 uses your configured post actions.")


class Generate(Template):
    data: str = Field(..., min_length=2, max_length=2_000_000, description="JSON object or array as a string. Use template sample data as a starting point.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    version: str | None = Field(None, min_length=1, description="Template version; omit for latest.")
    expiration: int = Field(60, ge=1, le=10080)
    cloud_storage: Literal[0, 1] = 1
    _data = field_validator("data")(_json)


class CreatePdf(Generate):
    operation: Literal["create_pdf"] = Field("create_pdf", title="Create PDF", json_schema_extra={"ui:hidden": True})
    output_file: str | None = Field(None, min_length=1, max_length=256)
    pdf_version: Literal["1.4", "1.7", "Auto"] | None = None


class CreatePdfAsync(Generate):
    operation: Literal["create_pdf_async"] = Field("create_pdf_async", title="Create PDF Asynchronously", description="Queues generation; the file is delivered to your webhook after this operation returns.", json_schema_extra={"ui:hidden": True})
    webhook_url: str = Field(..., min_length=1, description="Callback endpoint receiving CraftMyPDF's GET request after generation.")
    _webhook = field_validator("webhook_url")(_url)


class CreateImage(Generate):
    operation: Literal["create_image"] = Field("create_image", title="Create Image", json_schema_extra={"ui:hidden": True})
    output_type: Literal["jpeg", "png"] = "jpeg"
    output_file: str | None = Field(None, min_length=1, max_length=256)


class ListTemplates(Page):
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})
    group_name: str | None = Field(None, max_length=256)


class ListTemplateVersions(Template):
    operation: Literal["list_template_versions"] = Field("list_template_versions", title="List Template Versions", json_schema_extra={"ui:hidden": True})


class RetainTemplateVersions(Template):
    operation: Literal["retain_template_versions"] = Field("retain_template_versions", title="Retain Template Versions", json_schema_extra={"ui:hidden": True})
    versions: list[int] = Field(..., min_length=1, max_length=100)
    keep: bool = Field(..., description="Keep selected versions when true; release retention when false.")


class DuplicateTemplate(Template):
    operation: Literal["duplicate_template"] = Field("duplicate_template", title="Duplicate Template", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=256)
    version: str | None = None
    group_name: str | None = Field(None, max_length=256)


class UpdateTemplate(Template):
    operation: Literal["update_template"] = Field("update_template", title="Update Template", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=256)
    sample_json: str | None = Field(None, description="Sample JSON data, sent as the API's json field.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    body: str | None = Field(None, min_length=1, max_length=2_000_000, description="Template body. Only change this if you understand the template format.")
    _sample = field_validator("sample_json")(lambda v: _json(v) if v is not None else v)

    @model_validator(mode="after")
    def changes(self):
        if all(v is None for v in (self.name, self.sample_json, self.body)):
            raise ValueError("Supply a name, sample JSON or template body to update")
        return self


class GetTemplate(Template):
    operation: Literal["get_template"] = Field("get_template", title="Get Template", json_schema_extra={"ui:hidden": True})
    version: str | None = None


class DeleteTemplate(Template):
    operation: Literal["delete_template"] = Field("delete_template", title="Delete Template", description="Permanently deletes the selected template using the provider's GET endpoint.", json_schema_extra={"ui:hidden": True})


class QueryTemplateUsage(Input):
    operation: Literal["query_template_usage"] = Field("query_template_usage", title="Query Template Usage", json_schema_extra={"ui:hidden": True})
    template_ids: str = Field(..., min_length=1, description="Comma-separated template IDs.")
    start_date: str | None = Field(None, description="ISO 8601 UTC timestamp, for example 2025-01-30T00:00:00Z.")
    end_date: str | None = Field(None, description="ISO 8601 UTC timestamp.")


    @field_validator("start_date", "end_date")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 timestamp with a timezone") from None
        return value


class CreateEditorSession(Template):
    operation: Literal["create_editor_session"] = Field("create_editor_session", title="Create Editor Session", description="Creates an expiring editor access URL. Anyone holding the returned URL can use the granted editor capabilities.", json_schema_extra={"ui:hidden": True})
    expiration: int = Field(60, ge=1, description="Editor session lifetime in minutes.")
    canSave: bool = False
    canCreatePDF: bool = False
    canViewSettings: bool = False
    canPreview: bool = True
    canEditJSON: bool = False


class DeactivateEditorSession(Input):
    operation: Literal["deactivate_editor_session"] = Field("deactivate_editor_session", title="Deactivate Editor Session", json_schema_extra={"ui:hidden": True})
    token_uuid: str = Field(..., min_length=1, max_length=256)


class ListTransactions(Page):
    operation: Literal["list_transactions"] = Field("list_transactions", title="List Transactions", json_schema_extra={"ui:hidden": True})


class GetAccountInfo(Input):
    operation: Literal["get_account_info"] = Field("get_account_info", title="Get Account Information", json_schema_extra={"ui:hidden": True})


class MergePdfs(FileOptions):
    operation: Literal["merge_pdfs"] = Field("merge_pdfs", title="Merge PDFs", json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., min_length=2, max_length=100, description="Public PDF URLs in merge order.")
    _urls = field_validator("urls")(lambda values: [_url(v) for v in values])


class SourcePdf(FileOptions):
    url: str = Field(..., min_length=1, description="Public PDF URL accessible to CraftMyPDF.")
    _source = field_validator("url")(_url)


class TextSetting(Input):
    page_selector: str = Field(..., min_length=1)
    text: str
    position: Literal["top-left", "top-center", "top-right", "middle-left", "center", "middle-right", "bottom-left", "bottom-center", "bottom-right"]
    offset_x: float | None = None
    offset_y: float | None = None
    font_size: float | None = Field(None, gt=0)
    hex_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    opacity: float | None = Field(None, ge=0, le=1)
    rotation: float | None = None


class AddTextToPdf(SourcePdf):
    operation: Literal["add_text_to_pdf"] = Field("add_text_to_pdf", title="Add Text to PDF", json_schema_extra={"ui:hidden": True})
    textSettings: list[TextSetting] = Field(..., min_length=1, max_length=100)


class PdfField(Input):
    id: str = Field(..., min_length=1)
    value: str
    readOnly: bool | None = None
    fontSize: int | None = Field(None, gt=0)


class UpdatePdfFields(SourcePdf):
    operation: Literal["update_pdf_fields"] = Field("update_pdf_fields", title="Update PDF Form Fields", json_schema_extra={"ui:hidden": True})
    fields: list[PdfField] = Field(..., min_length=1, max_length=500)


class GetPdfInfo(Input):
    operation: Literal["get_pdf_info"] = Field("get_pdf_info", title="Get PDF Information", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1)
    _source = field_validator("url")(_url)


class AddWatermark(SourcePdf):
    operation: Literal["add_watermark"] = Field("add_watermark", title="Add Watermark", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1)
    font_size: int | None = Field(None, gt=0)
    rotation: int | None = None
    hex_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


Operation = Annotated[Union[CreatePdf, CreatePdfAsync, CreateImage, ListTemplates,
    ListTemplateVersions, RetainTemplateVersions, DuplicateTemplate, UpdateTemplate,
    GetTemplate, DeleteTemplate, QueryTemplateUsage, CreateEditorSession,
    DeactivateEditorSession, ListTransactions, GetAccountInfo, MergePdfs,
    AddTextToPdf, UpdatePdfFields, GetPdfInfo, AddWatermark], Field(discriminator="operation")]


class CraftmypdfConfig(NodeConfig[Operation, CraftmypdfApiKey]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "create_pdf": ("POST", "/create"),
    "create_pdf_async": ("POST", "/create-async"),
    "create_image": ("POST", "/create-image"),
    "list_templates": ("GET", "/list-templates"),
    "list_template_versions": ("GET", "/list-template-versions"),
    "retain_template_versions": ("POST", "/retain-template-versions"),
    "duplicate_template": ("POST", "/new-template-from"),
    "update_template": ("POST", "/update-template"),
    "get_template": ("GET", "/get-template"),
    "delete_template": ("GET", "/delete-template"),
    "query_template_usage": ("GET", "/query-template-usage"),
    "create_editor_session": ("POST", "/create-editor-session"),
    "deactivate_editor_session": ("POST", "/deactivate-editor-session"),
    "list_transactions": ("GET", "/list-transactions"),
    "get_account_info": ("GET", "/get-account-info"),
    "merge_pdfs": ("POST", "/merge-pdfs"),
    "add_text_to_pdf": ("POST", "/add-text-to-pdf"),
    "update_pdf_fields": ("POST", "/update-pdf-fields"),
    "get_pdf_info": ("GET", "/get-pdf-info"),
    "add_watermark": ("POST", "/add-watermark"),
}


class CraftmypdfNode(WorkflowNode):
    integration_type = "automation-craftmypdf"
    connection_evidence = ConnectionEvidence(noun="CraftMyPDF account", identity_operation="get_account_info", identity_keys=("username",))

    @classmethod
    def get_config_model(cls):
        return CraftmypdfConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != CREDENTIAL:
            raise ValueError("Choose a CraftMyPDF API key credential")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Attach a CraftMyPDF API key credential")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        if config.operation == "update_template" and "sample_json" in values:
            values["json"] = values.pop("sample_json")
        if config.operation in {"create_pdf", "create_image"}:
            values["export_type"] = "json"
        kwargs = {"params": values} if method == "GET" else {"json": values}
        # The provider explicitly documents a required empty JSON body here.
        if config.operation == "get_account_info":
            kwargs = {"json": {}}
        try:
            async with guarded_async_client(timeout=110, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASES[credential.region] + path,
                    headers={"X-API-KEY": credential.api_key, "Accept": "application/json", "Content-Type": "application/json"}, **kwargs)
        except (httpx.HTTPError, SSRFError, OSError):
            raise ValueError("CraftMyPDF request did not complete; check transaction history before retrying a write") from None
        if len(response.content) > 4_000_000:
            raise ValueError("CraftMyPDF response exceeds the supported size")
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            raise ValueError("CraftMyPDF returned an unexpected response format") from None
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("status") != "success":
            message = payload.get("message") if isinstance(payload, dict) else None
            if isinstance(message, str):
                message = message.replace(credential.api_key, "[redacted]")[:1000]
                raise ValueError(f"CraftMyPDF HTTP {response.status_code}: {message}")
            raise ValueError(f"CraftMyPDF request was not confirmed (HTTP {response.status_code})")
        if config.operation == "get_account_info" and not isinstance(payload.get("username"), str):
            raise ValueError("CraftMyPDF account response is missing the username")
        required = {
            "create_pdf": ("file", str), "create_image": ("file", str),
            "merge_pdfs": ("file", str), "add_text_to_pdf": ("file", str),
            "update_pdf_fields": ("file", str), "add_watermark": ("file", str),
            "list_templates": ("templates", list), "list_template_versions": ("versions", list),
            "retain_template_versions": ("versions", list), "duplicate_template": ("template_id", str),
            "query_template_usage": ("results", list), "list_transactions": ("transactions", list),
            "get_template": ("body", str), "create_editor_session": ("url", str),
            "create_pdf_async": ("transaction_ref", str), "get_pdf_info": ("totalPages", int),
        }.get(config.operation)
        if required and (not isinstance(payload.get(required[0]), required[1]) or isinstance(payload.get(required[0]), bool)):
            raise ValueError("CraftMyPDF response is missing the documented result")
        if config.operation == "create_pdf_async" and payload.get("is_async") is not True:
            raise ValueError("CraftMyPDF did not confirm asynchronous acceptance")
        return payload
