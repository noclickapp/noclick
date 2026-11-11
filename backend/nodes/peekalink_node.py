"""Peekalink link previews, against the published 1.0.0 OpenAPI contract.

The provider exposes one POST read, not separate operations for each media type.
Docs: https://docs.peekalink.io/quickstart
Contract: https://api.peekalink.io/mintlify
"""
from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class PeekalinkAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Peekalink API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.peekalink.io/app/dashboard",
            "x-credential-instructions": "Copy your API key from the Peekalink dashboard and paste it here without the Bearer prefix. NoClick sends it to api.peekalink.io. Connecting requests one example link preview and uses your request quota; it verifies API access, not account identity.",
        },
    )
    credential_type: Literal["peekalink_api_key"] = Field("peekalink_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class PeekalinkGetLinkPreviewConfig(BaseModel):
    """Get metadata, images and platform-specific content for one URL."""
    model_config = ConfigDict(hide_input_in_errors=True)
    operation: Literal["get_link_preview"] = Field("get_link_preview", json_schema_extra={"ui:hidden": True, "x-keywords": ["URL metadata", "unfurl link", "YouTube", "social preview"]})
    link: str = Field(..., min_length=1, title="Link URL", json_schema_extra={"format": "uri"})
    accept_language: str | None = Field(None, title="Preferred language", description="Optional Accept-Language header, such as en-US.")
    source: Literal["API", "WEB"] = Field("API", title="Request source")
    forceNewSnapshot: Literal["true", "false"] | None = Field(None, title="Force new snapshot", description="Enterprise integration debugging only; Peekalink already keeps previews fresh.")
    forceNewSnapshotRecursive: Literal["true", "false"] | None = Field(None, title="Force recursive snapshot", description="Enterprise integration debugging only.")

    @field_validator("link")
    @classmethod
    def link_url(cls, value):
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() or ord(c) < 32 for c in value):
                raise ValueError()
            parsed.port
        except ValueError:
            raise ValueError("Use a complete HTTP or HTTPS link without embedded credentials") from None
        return value

    @field_validator("accept_language")
    @classmethod
    def language_header(cls, value):
        if value is not None and (not value or any(ord(c) < 32 or ord(c) > 126 for c in value)):
            raise ValueError("Use a valid Accept-Language header without control characters")
        return value


class PeekalinkNodeConfig(NodeConfig[PeekalinkGetLinkPreviewConfig, PeekalinkAPIKeyCredential]):
    pass


class PeekalinkNode(WorkflowNode):
    integration_type = "automation-peekalink"
    connection_evidence = ConnectionEvidence(
        noun="link previews", operation="get_link_preview", proves="reachability",
        operation_arguments={"link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    @classmethod
    def get_config_model(cls):
        return PeekalinkNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Peekalink API key")
        config = self.config.config
        body = config.model_dump(exclude_none=True, exclude={"operation", "accept_language"})
        headers = {"Authorization": f"Bearer {credential.api_key}", "Accept": "application/json"}
        if config.accept_language is not None:
            headers["Accept-Language"] = config.accept_language
        async with guarded_async_client(timeout=90, follow_redirects=False, trust_env=False) as client:
            response = await client.request("POST", "https://api.peekalink.io/", headers=headers, json=body)
        if not response.is_success:
            try:
                error = response.json()
                message = error.get("message") or error.get("error") if isinstance(error, dict) else None
            except ValueError:
                message = None
            message = str(message or "Request was not accepted").replace(credential.api_key, "[redacted]")[:500]
            raise httpx.HTTPStatusError(f"Peekalink HTTP {response.status_code}: {message}", request=response.request, response=response)
        data = response.json()
        if not isinstance(data, dict) or type(data.get("ok")) is not bool:
            raise ValueError("Peekalink returned an unexpected preview response")
        # A Link with ok=false describes an unavailable target; retain it. An
        # APIErrorResponseBody is a failed API request, even if sent with HTTP 200.
        if data.get("ok") is False and (data.get("error") or data.get("message")):
            message = str(data.get("message") or data["error"]).replace(credential.api_key, "[redacted]")[:500]
            return {"status": "error", "success": False, "status_code": data.get("status"), "error": message}
        return {"status": "success", "data": data}
