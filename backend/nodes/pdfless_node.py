"""Pdfless v1: the three operations published in the provider's Swagger contract.

API and authentication: https://docs.pdfless.com/authentication
PDF request/response: https://docs.pdfless.com/pdfs
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.pdfless.com/v1"


class PdflessAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Pdfless API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.pdfless.com/",
            "x-credential-instructions": "Copy the API key from Workspace settings → API credentials. NoClick sends it in the apikey header to api.pdfless.com.",
            "x-help-url": "https://docs.pdfless.com/authentication",
        },
    )
    credential_type: Literal["pdfless_api_key"] = Field("pdfless_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PdflessGetWorkspaceConfig(_Operation):
    """Read the connected workspace's name, status and PDF quota."""
    operation: Literal["get_workspace"] = Field("get_workspace", json_schema_extra={"ui:hidden": True})


class PdflessListDocumentTemplatesConfig(_Operation):
    """List one page of document templates in the current workspace."""
    operation: Literal["list_document_templates"] = Field("list_document_templates", json_schema_extra={"ui:hidden": True})
    workspace_id: int | None = Field(None, ge=1, le=2147483647, title="Workspace ID", description="Optional WorkspaceId filter; omit for the connected workspace.")
    page: int | None = Field(None, ge=1, le=2147483647, title="Page", description="Optional Page query parameter. Omit to use the provider's default.")
    page_size: int | None = Field(None, ge=1, le=2147483647, title="Page size", description="Optional PageSize query parameter. Returns one page only.")


class PdflessGeneratePDFConfig(_Operation):
    """Generate a PDF from a template and JSON data; returns its temporary download URL."""
    operation: Literal["generate_pdf"] = Field("generate_pdf", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., title="Template ID", description="UUID of the Pdfless template.")
    payload: str = Field("{}", title="Payload JSON", description="JSON data used by the template.",
                         json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    workspace_id: int | None = Field(None, ge=1, le=2147483647, title="Workspace ID")
    reference_id: str | None = Field(None, title="Reference ID")
    encryption_user_password: str | None = Field(None, title="Document password", repr=False, json_schema_extra={"ui:widget": "password"})
    encryption_owner_password: str | None = Field(None, title="Permissions password", repr=False, json_schema_extra={"ui:widget": "password"})
    encryption_allow_printing: StrictBool | None = None
    encryption_allow_modifying: StrictBool | None = None
    encryption_allow_modify_annotations: StrictBool | None = None
    encryption_allow_content_copying: StrictBool | None = None
    encryption_allow_screenreaders: StrictBool | None = None
    encryption_allow_form_filling: StrictBool | None = None
    encryption_allow_document_assembly: StrictBool | None = None

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, value):
        try:
            return str(UUID(value))
        except ValueError:
            raise ValueError("Use the template UUID from Pdfless") from None

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value):
        try:
            json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, TypeError):
            raise ValueError("Payload must be valid JSON") from None
        return value


PdflessOperation = Annotated[Union[PdflessGetWorkspaceConfig, PdflessListDocumentTemplatesConfig,
                                  PdflessGeneratePDFConfig], Field(discriminator="operation")]


class PdflessNodeConfig(NodeConfig[PdflessOperation, PdflessAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class PdflessNode(WorkflowNode):
    integration_type = "automation-pdfless"
    connection_evidence = ConnectionEvidence(noun="workspace", identity_operation="get_workspace")

    @classmethod
    def get_config_model(cls):
        return PdflessNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Pdfless API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path, params, body = "GET", "/workspaces", {}, None
        if isinstance(config, PdflessListDocumentTemplatesConfig):
            path = "/document-templates"
            params = {remote: getattr(config, local) for local, remote in
                      (("workspace_id", "WorkspaceId"), ("page", "Page"), ("page_size", "PageSize"))
                      if getattr(config, local) is not None}
        elif isinstance(config, PdflessGeneratePDFConfig):
            method, path = "POST", "/pdfs"
            body = config.model_dump(exclude_none=True, exclude={"operation", "workspace_id", "payload"})
            body["payload"] = json.loads(config.payload)
            if config.workspace_id is not None:
                body["workspaceId"] = config.workspace_id
        # Never retry generation: a timeout may follow a completed, billable PDF.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                                            headers={"apikey": key, "Accept": "application/json"})
        if response.status_code != 200:
            message = "Pdfless request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except ValueError:
                pass
            # Preserve the provider's rejection text, with supplied secrets redacted.
            for secret in (key, getattr(config, "encryption_user_password", None), getattr(config, "encryption_owner_password", None)):
                if secret:
                    message = message.replace(secret, "[redacted]")
            return {"status": "error", "error": message, "http_status": response.status_code}
        result = response.json()
        if isinstance(result, dict) and (result.get("error_code") or result.get("status") in {"error", "failed"}):
            raise ValueError("Pdfless returned an error response")
        if isinstance(config, PdflessListDocumentTemplatesConfig):
            if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
                raise ValueError("Pdfless returned an invalid template list")
            return {"status": "success", "items": result}
        if not isinstance(result, dict):
            raise ValueError("Pdfless returned an invalid response")
        if isinstance(config, PdflessGeneratePDFConfig):
            if not isinstance(result.get("data"), dict):
                raise ValueError("Pdfless did not return the generated PDF")
            return {"status": "success", "data": result["data"]}
        return {"status": "success", "data": result}
