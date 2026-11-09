"""APITemplate.io v2: one published API request per operation.

Generated documents are returned as provider URLs using export_type=json.
Lists fetch one explicit offset page; writes are never retried automatically.
Contract: https://apitemplate.io/apiv2/
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

CREDENTIAL = "apitemplateio_api_key"
BASES = {
    "singapore": "https://rest.apitemplate.io",
    "australia": "https://rest-au.apitemplate.io",
    "europe": "https://rest-de.apitemplate.io",
    "us": "https://rest-us.apitemplate.io",
}
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class APITemplateIOApiKey(BaseModel):
    model_config = ConfigDict(title="APITemplate.io API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.apitemplate.io/",
            "x-credential-instructions": "Copy your API key from the APITemplate.io web console. Paste the key without a header prefix, and choose your processing region. NoClick checks your account's templates using X-API-KEY."})
    credential_type: Literal["apitemplateio_api_key"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})
    region: Literal["singapore", "australia", "europe", "us"] = Field("singapore", title="Processing region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


def _object(value):
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError("Enter a JSON object") from None
    if not isinstance(data, dict):
        raise ValueError("Enter a JSON object")
    return value


def _url(value):
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Use an HTTP or HTTPS URL accessible to APITemplate.io")
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Template(Input):
    template_id: str = Field(..., min_length=1, max_length=256, title="Template ID")


class Page(Input):
    limit: int = Field(100, ge=1, le=100, description="One page only. Increase offset by the number of returned records for another page.")
    offset: int = Field(0, ge=0)


class FileOptions(Input):
    expiration: int = Field(60, ge=0, le=10080, description="File lifetime in minutes; 0 stores permanently.")
    cloud_storage: Literal[0, 1] = Field(1, description="Store on provider CDN (1), or use configured post actions (0).")
    meta: str | None = Field(None, max_length=1000, description="External reference for list objects.")


class PdfOptions(FileOptions):
    filename: str | None = Field(None, max_length=256, description="Custom filename ending in .pdf.")
    output_format: Literal["pdf", "html"] = "pdf"


class CreatePdf(Template, PdfOptions):
    operation: Literal["create_pdf"] = Field("create_pdf", title="Create PDF", json_schema_extra={"ui:hidden": True})
    data: str = Field(..., max_length=2_000_000, description="Template JSON data object.", json_schema_extra=JSON_EDITOR)
    _data = field_validator("data")(_object)


class CreateImage(Template, FileOptions):
    operation: Literal["create_image"] = Field("create_image", title="Create Image", json_schema_extra={"ui:hidden": True})
    data: str = Field(..., max_length=2_000_000, description='JSON object with an overrides array of named template layers.', json_schema_extra=JSON_EDITOR)
    output_image_type: Literal["jpegOnly", "pngOnly", "all"] = "all"
    _data = field_validator("data")(_object)


class HtmlSettings(PdfOptions):
    settings: str | None = Field(None, max_length=100_000, description="PDF generation settings JSON object (paper_size, margins, header/footer).", json_schema_extra=JSON_EDITOR)
    _settings = field_validator("settings")(lambda v: _object(v) if v is not None else v)


class CreatePdfFromHtml(HtmlSettings):
    operation: Literal["create_pdf_from_html"] = Field("create_pdf_from_html", title="Create PDF from HTML", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, max_length=2_000_000, description="HTML body, optionally with Jinja2 variables.")
    css: str | None = Field(None, max_length=100_000, description="CSS including style tags.")
    data: str | None = Field(None, max_length=2_000_000, description="JSON object of template variables.", json_schema_extra=JSON_EDITOR)
    _data = field_validator("data")(lambda v: _object(v) if v is not None else v)


class CreatePdfFromUrl(HtmlSettings):
    operation: Literal["create_pdf_from_url"] = Field("create_pdf_from_url", title="Create PDF from URL", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description="Page URL to render.")
    _url = field_validator("url")(_url)


class ListObjects(Page):
    operation: Literal["list_objects"] = Field("list_objects", title="List Generated Objects", json_schema_extra={"ui:hidden": True})
    template_id: str | None = None
    transaction_type: Literal["PDF", "JPEG", "MERGE"] | None = None


class DeleteObject(Input):
    operation: Literal["delete_object"] = Field("delete_object", title="Delete Generated Object", description="Deletes a generated file using the provider's documented GET endpoint.", json_schema_extra={"ui:hidden": True})
    transaction_ref: str = Field(..., min_length=1, max_length=256)


class ListTemplates(Page):
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})
    format: Literal["PDF", "JPEG"] | None = None
    template_id: str | None = None
    group_name: str | None = None
    with_layer_info: Literal["0", "1"] = "0"


class GetTemplate(Template):
    operation: Literal["get_template"] = Field("get_template", title="Get PDF Template", json_schema_extra={"ui:hidden": True})


class UpdateTemplate(Template):
    operation: Literal["update_template"] = Field("update_template", title="Update PDF Template", json_schema_extra={"ui:hidden": True})
    body: str | None = Field(None, max_length=2_000_000, description="Replacement HTML body.")
    css: str | None = Field(None, max_length=100_000, description="Replacement CSS.")

    @model_validator(mode="after")
    def change(self):
        if self.body is None and self.css is None:
            raise ValueError("Supply a template body or CSS to update")
        return self


class MergePdfs(FileOptions):
    operation: Literal["merge_pdfs"] = Field("merge_pdfs", title="Merge PDFs", json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., min_length=2, max_length=100, description="PDF URLs in merge order.")
    _urls = field_validator("urls")(lambda values: [_url(v) for v in values])


Operation = Annotated[Union[CreatePdf, CreateImage, CreatePdfFromHtml, CreatePdfFromUrl,
    ListObjects, DeleteObject, ListTemplates, GetTemplate, UpdateTemplate, MergePdfs], Field(discriminator="operation")]


class APITemplateIOConfig(NodeConfig[Operation, APITemplateIOApiKey]):
    pass


def request_parts(op):
    action = op.operation
    values = op.model_dump(exclude_none=True, exclude={"operation"})
    path = "/v2/" + action.replace("_", "-")
    if action in {"list_objects", "list_templates", "get_template", "delete_object"}:
        return "GET", path, {k: str(v) for k, v in values.items()}, None
    if action == "update_template":
        return "POST", path, {}, values
    if action == "merge_pdfs":
        return "POST", path, {"meta": values.pop("meta")} if "meta" in values else {}, {**values, "export_type": "json"}
    if action in {"create_pdf", "create_image"}:
        body = json.loads(values.pop("data"))
    else:
        body = {k: values.pop(k) for k in ("body", "css", "data", "settings", "url") if k in values}
        for k in ("data", "settings"):
            if k in body:
                body[k] = json.loads(body[k])
    if action != "create_image":
        values["export_type"] = "json"
    return "POST", path, {k: str(v) for k, v in values.items()}, body


class APITemplateIONode(WorkflowNode):
    integration_type = "automation-apitemplateio"
    connection_evidence = ConnectionEvidence(noun="templates", operation="list_templates", label_keys=("name", "template_id"))
    edit_examples = ["Create a PDF from this template", "Generate a social image", "Merge these PDFs"]

    @classmethod
    def get_config_model(cls):
        return APITemplateIOConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an APITemplate.io API key")
        credential, op = self.config.credentials, self.config.config
        method, path, params, body = request_parts(op)
        headers = {"X-API-KEY": credential.api_key, "Accept": "application/json"}
        async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(60.0)) as client:
            response = await client.request(method, BASES[credential.region] + path, headers=headers, params=params,
                **({"json": body} if body is not None else {}))
        try:
            result = response.json()
        except ValueError:
            raise ValueError("APITemplate.io returned a non-JSON response; inspect before retrying a write") from None
        if not isinstance(result, dict):
            raise ValueError("APITemplate.io returned an unexpected response")
        if not response.is_success or result.get("status") != "success":
            message = str(result.get("message") or result.get("error") or "APITemplate.io did not confirm success")
            raise ValueError(message.replace(credential.api_key, "[redacted]")[:2000])
        output = {"operation": op.operation, **result}
        if op.operation in {"list_templates", "list_objects"}:
            key = "templates" if op.operation == "list_templates" else "objects"
            if not isinstance(result.get(key), list):
                raise ValueError("APITemplate.io returned an incomplete list")
            output.update(items=result[key], offset=op.offset, limit=op.limit)
        await self.emit(output)
        return output
