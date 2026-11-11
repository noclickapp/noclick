"""Doqs PDF filling and HTML rendering, using the published v1 OpenAPI.

https://api.doqs.dev/v1/openapi.json
Binary response contract: https://docs.doqs.dev/pdf-filling/fill-template
and https://docs.doqs.dev/pdf-generator/render. PDFs use BinaryOutput so the
executor stores them and returns usable file references. No additional download is made.
The four published operations provide no webhook registration, time filter,
or time ordering suitable for an incremental poll trigger.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://api.doqs.dev/v1"
ENDPOINTS = {
    "list_templates": ("GET", "/pdf-filling/templates"),
    "fill_template": ("POST", "/pdf-filling/templates/{id}/fill"),
    "render_pdf": ("POST", "/pdf-generator/render"),
    "list_submissions": ("GET", "/pdf-generator/submissions"),
}


class DoqsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Doqs API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.doqs.dev",
        "x-credential-instructions": "Paste an API key from your Doqs dashboard. NoClick reads your templates to check the connection. A development key watermarks filled PDFs; HTML rendering requires a live key.",
    })
    credential_type: Literal["doqs_api_key"] = Field("doqs_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})


def _operation(name: str, title: str):
    return Field(name, title=title, json_schema_extra={"ui:hidden": True, "x-display-name": title, "x-is-trigger": False})


class _Page(BaseModel):
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")
    offset: int = Field(0, ge=0, description="Number of results to skip. Increase by the page size to read the next page.")


class DoqsListTemplatesConfig(_Page):
    operation: Literal["list_templates"] = _operation("list_templates", "List Templates")


class DoqsListSubmissionsConfig(_Page):
    operation: Literal["list_submissions"] = _operation("list_submissions", "List Submissions")


class DoqsFillTemplateConfig(BaseModel):
    operation: Literal["fill_template"] = _operation("fill_template", "Fill PDF Template")
    template_id: str = Field(..., min_length=1, title="Template", json_schema_extra={"x-dynamic-options": {
        "field_name": "template_id", "allow_custom": True, "searchable": False, "placeholder": "Choose a template",
    }})
    data: str = Field("{}", title="Template Data", description="JSON object mapping the template's field names to values.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("data", mode="before")
    @classmethod
    def data_object(cls, value):
        if isinstance(value, dict):
            value = json.dumps(value, allow_nan=False)
        try:
            parsed = json.loads(value)
            json.dumps(parsed, allow_nan=False)
        except (ValueError, TypeError):
            raise ValueError("Template data must be a JSON object") from None
        if not isinstance(parsed, dict):
            raise ValueError("Template data must be a JSON object")
        return value


class DoqsRenderPDFConfig(BaseModel):
    operation: Literal["render_pdf"] = _operation("render_pdf", "Render HTML to PDF")
    template_html: str = Field(..., min_length=1, title="HTML Template", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "html"})
    header_template: str | None = Field(None, title="Header HTML", description="Set a top margin to leave space for the header.")
    footer_template: str | None = Field(None, title="Footer HTML", description="Set a bottom margin to leave space for the footer.")
    format: Literal["a0", "a1", "a2", "a3", "a4", "a5", "a6"] = Field("a4", title="Paper Size")
    orientation: Literal["landscape", "portrait"] = "portrait"
    scale: float = Field(1, ge=0.1, le=2, allow_inf_nan=False)
    margin_top: str | None = Field(None, description="CSS length, for example 10mm.")
    margin_bottom: str | None = Field(None, description="CSS length, for example 10mm.")
    margin_left: str | None = Field(None, description="CSS length, for example 10mm.")
    margin_right: str | None = Field(None, description="CSS length, for example 10mm.")
    presigned_upload_url: str | None = Field(None, min_length=1, max_length=2083, description="Presigned HTTPS upload URL. Doqs uploads the PDF to this destination; requires a paid plan.")
    presigned_upload_method: Literal["PUT", "POST"] = Field("PUT", title="Upload Method")

    @field_validator("presigned_upload_url")
    @classmethod
    def upload_url(cls, value):
        if value is not None:
            from urllib.parse import urlsplit
            url = urlsplit(value)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("Use a presigned HTTPS upload URL without user information")
        return value


DoqsOperation = Annotated[Union[DoqsListTemplatesConfig, DoqsFillTemplateConfig, DoqsRenderPDFConfig, DoqsListSubmissionsConfig], Field(discriminator="operation")]


class DoqsNodeConfig(NodeConfig[DoqsOperation, DoqsAPIKeyCredential]):
    pass


class DoqsNode(WorkflowNode):
    integration_type = "automation-doqs"
    connection_evidence = ConnectionEvidence(operation="list_templates", noun="PDF templates")

    @classmethod
    def get_config_model(cls):
        return DoqsNodeConfig

    @staticmethod
    async def _request(credential, operation, *, path=None, params=None, body=None):
        method, endpoint = ENDPOINTS[operation]
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
            return await client.request(method, API_BASE + (path or endpoint),
                headers={"x-api-key": credential.api_key, "Accept": "application/json" if method == "GET" else "application/pdf, application/json"},
                **({"params": params} if params is not None else {}),
                **({"json": body} if body is not None else {}))

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, DoqsNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Doqs API key")
        op, credential = self.config.config, self.config.credentials
        operation = op.operation
        path, params, body = None, None, None
        if isinstance(op, _Page):
            params = {"limit": op.limit, "offset": op.offset}
        elif isinstance(op, DoqsFillTemplateConfig):
            path = "/pdf-filling/templates/" + quote(op.template_id, safe="") + "/fill"
            body = {"data": json.loads(op.data)}
        elif isinstance(op, DoqsRenderPDFConfig):
            pdf = {"format": op.format, "orientation": op.orientation, "scale": op.scale}
            margin = {side: getattr(op, "margin_" + side) for side in ("top", "bottom", "left", "right") if getattr(op, "margin_" + side) is not None}
            if margin:
                pdf["margin"] = margin
            body = {"template_html": op.template_html, "pdf": pdf}
            for name in ("header_template", "footer_template"):
                if getattr(op, name) is not None:
                    body[name] = getattr(op, name)
            if op.presigned_upload_url:
                body["presigned_upload"] = {"url": op.presigned_upload_url, "method": op.presigned_upload_method}
        try:
            response = await self._request(credential, operation, path=path, params=params, body=body)
        except httpx.RequestError:
            # Unknown reachability must not accuse a manually pasted key.
            raise ValueError("Could not reach Doqs; request completion is unknown") from None
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                message = error.get("message") if isinstance(error, dict) else None
            except ValueError:
                message = None
            return {"status": "error", "operation": operation, "status_code": response.status_code,
                "error": (str(message) if message else f"Doqs request failed (HTTP {response.status_code})").replace(credential.api_key, "[redacted]")}
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        result = {"status": "success", "operation": operation, "status_code": response.status_code}
        if mime == "application/pdf" and operation in {"fill_template", "render_pdf"}:
            return {**result, "file": BinaryOutput(data=response.content, content_type=mime,
                    filename="filled-template.pdf" if operation == "fill_template" else "rendered.pdf"), "mime_type": mime,
                "submission_id": response.headers.get("x-submission-id")}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Doqs returned an unexpected response format") from None
        if isinstance(op, _Page) and (not isinstance(data, dict) or not isinstance(data.get("results"), list)):
            raise ValueError("Doqs returned an unexpected list response")
        return {**result, "data": data}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, *, page_token=None, search=None):
        if field_name != "template_id":
            return []
        credential = DoqsAPIKeyCredential.model_validate(credential_data)
        offset = int(page_token) if page_token is not None else 0
        page = DoqsListTemplatesConfig(offset=offset)
        config = DoqsNodeConfig(config=page, credentials=credential)
        node = cls(node_id="doqs-template-options", node_type=cls.integration_type, node_data={}, config=config)
        result = await node.execute({})
        if result["status"] != "success":
            raise ValueError(result["error"])
        rows = result["data"]["results"]
        return {"options": [{"value": row["id"], "label": row.get("name") or row["id"]} for row in rows],
            "next_page_token": str(offset + page.limit) if len(rows) == page.limit else None}
