"""DocuGenerate API 1.9.1 template and document operations."""
from __future__ import annotations

import base64
import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.docugenerate.com"


class DocugenerateAPIKey(BaseModel):
    model_config = ConfigDict(title="Docugenerate API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.docugenerate.com/settings/developers",
            "x-credential-instructions": "Copy your API key from Settings → Developers in DocuGenerate. Paste the key alone; NoClick sends it in the Authorization header.",
        })
    credential_type: Literal["docugenerate_api_key"] = Field("docugenerate_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key alone, without a header prefix")
        return value


def _operation(name, label):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label})


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _TemplateID(_Input):
    template_id: str = Field(..., min_length=1, description="DocuGenerate template ID.")


class _DocumentID(_Input):
    document_id: str = Field(..., min_length=1, description="DocuGenerate document ID.")


class _TemplateFields(_Input):
    name: str | None = Field(None, description="Display name of the template.")
    region: Literal["us", "eu", "uk", "au"] | None = Field(None, description="Storage region. Omit to retain the provider default or existing region.")
    enhanced_syntax: StrictBool | None = Field(None, description="Enable nested properties and logical or mathematical operators.")
    versioning_enabled: StrictBool | None = Field(None, description="Preserve previous file versions; requires a Premium or Business plan.")


class _Upload(_Input):
    file_base64: str | None = Field(None, title="Template File (Base64)",
        description="Base64-encoded DOCX, DOC, ODT, RTF, TXT or SQL template, up to 20 MB.",
        json_schema_extra={"contentEncoding": "base64", "contentMediaType": "text/plain"})
    file_name: str = Field("template.txt", description="Original filename including its extension.")

    @field_validator("file_base64")
    @classmethod
    def file_bytes(cls, value):
        if value is not None:
            try:
                content = base64.b64decode(value, validate=True)
            except (ValueError, base64.binascii.Error):
                raise ValueError("Template file must be valid Base64") from None
            if not content or len(content) > 20 * 1024 * 1024:
                raise ValueError("Template file must contain between 1 byte and 20 MB")
        return value


class CreateTemplate(_TemplateFields, _Upload):
    operation: Literal["create_template"] = _operation("create_template", "Create Template")
    file_base64: str = Field(..., title="Template File (Base64)",
        description="Base64-encoded DOCX, DOC, ODT, RTF, TXT or SQL template, up to 20 MB.",
        json_schema_extra={"contentEncoding": "base64", "contentMediaType": "text/plain"})


class ListTemplates(_Input):
    operation: Literal["list_templates"] = _operation("list_templates", "List Templates")
    folder: list[str] | None = Field(None, max_length=100,
        description="Ordered folder names, from root to leaf. Omit to list all templates.",
        json_schema_extra={"ui:widget": "list"})


class GetTemplate(_TemplateID):
    operation: Literal["get_template"] = _operation("get_template", "Get Template")


class UpdateTemplate(_TemplateFields, _Upload, _TemplateID):
    operation: Literal["update_template"] = _operation("update_template", "Update Template")

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in ("name", "region", "enhanced_syntax", "versioning_enabled", "file_base64")):
            raise ValueError("Provide a template file or a field to update")
        return self


class DeleteTemplate(_TemplateID):
    operation: Literal["delete_template"] = _operation("delete_template", "Delete Template")


class GenerateDocument(_TemplateID):
    operation: Literal["generate_document"] = _operation("generate_document", "Generate Document")
    data: str = Field("{}", title="Data JSON",
        description="One JSON object or an array of objects. Keys match the template's merge tags.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    name: str | None = Field(None, description="Document display name.")
    output_name: str | None = Field(None, description="Output filename without extension.")
    output_format: Literal[".docx", ".doc", ".odt", ".txt", ".html", ".png", ".pdf", ".pdf/a-1b", ".pdf/a-2b", ".pdf/a-3b"] | None = None
    output_quality: int | None = Field(None, ge=1, le=100)
    single_file: StrictBool | None = Field(None, description="Combine multiple data records into one file; false creates a ZIP archive.")
    page_break: StrictBool | None = Field(None, description="Add page breaks between records when combining documents.")
    merge_with: list[AnyUrl] | None = Field(None, description="PDF URL(s) or data URI(s) to append to PDF output.",
        json_schema_extra={"ui:widget": "list"})
    attach: list[AnyUrl] | None = Field(None, description="File URL(s) or data URI(s) to attach to PDF output.",
        json_schema_extra={"ui:widget": "list"})

    @field_validator("data", mode="before")
    @classmethod
    def json_data(cls, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise ValueError("Data JSON must be a JSON object or an array of objects") from None
        if not isinstance(value, dict) and not (isinstance(value, list) and all(isinstance(item, dict) for item in value)):
            raise ValueError("Data JSON must be a JSON object or an array of objects")
        return json.dumps(value)


class ListDocuments(_TemplateID):
    operation: Literal["list_documents"] = _operation("list_documents", "List Documents")


class GetDocument(_DocumentID):
    operation: Literal["get_document"] = _operation("get_document", "Get Document")


class UpdateDocument(_DocumentID):
    operation: Literal["update_document"] = _operation("update_document", "Rename Document")
    name: str = Field(..., min_length=1)


class DeleteDocument(_DocumentID):
    operation: Literal["delete_document"] = _operation("delete_document", "Delete Document")


DocugenerateConfig = Annotated[Union[
    CreateTemplate, ListTemplates, GetTemplate, UpdateTemplate, DeleteTemplate,
    GenerateDocument, ListDocuments, GetDocument, UpdateDocument, DeleteDocument,
], Field(discriminator="operation")]


class DocugenerateNodeConfig(NodeConfig[DocugenerateConfig, DocugenerateAPIKey]):
    pass


ROUTES = {
    "create_template": ("POST", "/v1/template"),
    "list_templates": ("GET", "/v1/template"),
    "get_template": ("GET", "/v1/template/{id}"),
    "update_template": ("PUT", "/v1/template/{id}"),
    "delete_template": ("DELETE", "/v1/template/{id}"),
    "generate_document": ("POST", "/v1/document"),
    "list_documents": ("GET", "/v1/document"),
    "get_document": ("GET", "/v1/document/{id}"),
    "update_document": ("PUT", "/v1/document/{id}"),
    "delete_document": ("DELETE", "/v1/document/{id}"),
}


class DocugenerateNode(WorkflowNode):
    integration_type = "automation-docugenerate"
    connection_evidence = ConnectionEvidence(operation="list_templates", noun="templates")
    edit_examples = ["Generate a PDF invoice from a template", "List my document templates", "Rename a generated document"]

    @classmethod
    def get_config_model(cls):
        return DocugenerateNodeConfig

    async def execute(self, inputs):
        if not isinstance(self.config, DocugenerateNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a DocuGenerate API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            identifier = values.pop("template_id" if "template" in config.operation else "document_id")
            path = path.replace("{id}", quote(identifier, safe=""))
        kwargs = {}
        if method == "GET":
            kwargs["params"] = values
        elif config.operation in {"create_template", "update_template"}:
            encoded = values.pop("file_base64", None)
            filename = values.pop("file_name")
            # File tuples force multipart even for metadata-only updates.
            parts = [(key, (None, json.dumps(value) if isinstance(value, bool) else value)) for key, value in values.items()]
            if encoded is not None:
                parts.append(("file", (filename, base64.b64decode(encoded, validate=True), "application/octet-stream")))
            kwargs["files"] = parts
        elif method != "DELETE":
            if config.operation == "generate_document":
                values["data"] = json.loads(values["data"])
            kwargs["json"] = values
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": self.config.credentials.api_key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            message = response.text.replace(self.config.credentials.api_key, "[redacted]")[:2000]
            raise ValueError(f"DocuGenerate HTTP {response.status_code}: {message}")
        if method == "DELETE":
            output = {"status": "success", "operation": config.operation, "deleted": True}
        else:
            body = response.json()
            expected = list if config.operation.startswith("list_") else dict
            if not isinstance(body, expected):
                raise ValueError("DocuGenerate returned an unexpected JSON response")
            output = {"status": "success", "operation": config.operation, "data": body}
        await self.emit(output)
        return output
