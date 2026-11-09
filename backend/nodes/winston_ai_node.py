"""Winston AI v2 analysis API and a non-billable MCP credential probe.

Analysis operations consume the caller's credits. Connection evidence only lists
MCP tools, as documented at https://docs.gowinston.ai/api-reference/mcp-server;
it establishes key acceptance, not account identity or available credit balance.
"""
from __future__ import annotations

import ipaddress
import json
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.gowinston.ai"
CREDENTIAL_TYPE = "winston_ai_api_key"


class WinstonAIApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Winston AI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dev.gowinston.ai",
            "x-credential-instructions": "Create an API token in the Winston AI developer dashboard and paste it here. Analysis actions consume your Winston credits. The connection check only lists MCP tools to verify key acceptance; it does not run an analysis or identify your account.",
        })
    credential_type: Literal["winston_ai_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


def _public_url(value):
    if not isinstance(value, str):
        raise ValueError("Supply a public HTTP or HTTPS URL")
    try:
        u = urlsplit(value)
        host = u.hostname
        if u.scheme not in {"http", "https"} or not host or u.username is not None or u.password is not None or u.fragment or any(c.isspace() for c in value):
            raise ValueError()
        if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local")) or "." not in host:
            raise ValueError()
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not ip.is_global:
                raise ValueError()
        u.port
    except ValueError:
        raise ValueError("Supply a public HTTP or HTTPS URL without credentials or a fragment") from None
    return value


class _TextOptions(_Input):
    language: str = Field("auto", pattern=r"^(auto|[a-z]{2})$", description="Supported two-letter language code, or auto.")
    version: str = Field("latest", description="Winston text detection model version, e.g. 5.2 or latest.")
    sentences: bool = Field(True, description="Include sentence-level scores.")


class DetectTextConfig(_TextOptions):
    """Detect AI-generated text. Consumes one credit per word."""
    operation: Literal["detect_ai_text"] = "detect_ai_text"
    text: str = Field(..., min_length=300, max_length=150000, description="Text to analyze; 600+ characters recommended.")


class DetectFileConfig(_TextOptions):
    """Detect AI-generated content in a public PDF, DOC or DOCX."""
    operation: Literal["detect_ai_file"] = "detect_ai_file"
    file_url: str = Field(..., title="File URL", description="Public PDF, DOC or DOCX URL.", json_schema_extra={"format": "uri"})
    _url = field_validator("file_url", mode="before")(_public_url)


class DetectWebsiteConfig(_TextOptions):
    """Detect AI-generated content on a public webpage."""
    operation: Literal["detect_ai_website"] = "detect_ai_website"
    website: str = Field(..., title="Website URL", json_schema_extra={"format": "uri"})
    _url = field_validator("website", mode="before")(_public_url)


class _PlagiarismOptions(_Input):
    language: str = Field("auto", pattern=r"^(auto|[a-z]{2})$")
    country: str = Field("us", pattern=r"^[a-z]{2}$")
    excluded_sources: list[str] = Field(default_factory=list, description="Case-sensitive domains or URLs to exclude.")


class PlagiarismTextConfig(_PlagiarismOptions):
    """Check text for plagiarism. Consumes two credits per word."""
    operation: Literal["check_plagiarism_text"] = "check_plagiarism_text"
    text: str = Field(..., min_length=100, max_length=120000)


class PlagiarismFileConfig(_PlagiarismOptions):
    """Check a public PDF, DOC or DOCX for plagiarism."""
    operation: Literal["check_plagiarism_file"] = "check_plagiarism_file"
    file_url: str = Field(..., title="File URL", json_schema_extra={"format": "uri"})
    _url = field_validator("file_url", mode="before")(_public_url)


class PlagiarismWebsiteConfig(_PlagiarismOptions):
    """Check a public webpage for plagiarism."""
    operation: Literal["check_plagiarism_website"] = "check_plagiarism_website"
    website: str = Field(..., title="Website URL", json_schema_extra={"format": "uri"})
    _url = field_validator("website", mode="before")(_public_url)


class FactCheckConfig(_Input):
    """Fact-check text against trusted sources. Consumes two credits per word."""
    operation: Literal["fact_check_text"] = "fact_check_text"
    text: str = Field(..., min_length=300, max_length=10000)
    language: str = Field("auto", pattern=r"^(auto|[a-z]{2})$")


class ImageURLConfig(_Input):
    """Detect AI-generated images from a public URL. Costs 300 credits."""
    operation: Literal["detect_ai_image_url"] = "detect_ai_image_url"
    url: str = Field(..., description="Public JPG, JPEG, PNG or WEBP, at least 256 by 256 pixels.", json_schema_extra={"format": "uri"})
    version: str = Field("latest", description="Image model version, e.g. 5 or latest.")
    _url = field_validator("url", mode="before")(_public_url)


class ImageDataConfig(_Input):
    """Detect AI-generated images from existing encoded image data. Costs 300 credits."""
    operation: Literal["detect_ai_image_data"] = "detect_ai_image_data"
    image: str = Field(..., min_length=1, description="Base64 image or data:image/...;base64,... supplied by your workflow. Original file about 4 MB or less.")
    version: str = Field("latest")


class AdvancedImageConfig(_Input):
    """Run forensic analysis on a public image. Costs 500 credits."""
    operation: Literal["analyze_image_forensics"] = "analyze_image_forensics"
    image_url: str = Field(..., title="Image URL", json_schema_extra={"format": "uri"})
    _url = field_validator("image_url", mode="before")(_public_url)


class CompareTextConfig(_Input):
    """Compare two texts. Costs half the total word count in credits."""
    operation: Literal["compare_texts"] = "compare_texts"
    first_text: str = Field(..., min_length=1, max_length=120000)
    second_text: str = Field(..., min_length=1, max_length=120000)


class CheckConnectionConfig(_Input):
    """List MCP tools without invoking them or spending analysis credits."""
    operation: Literal["check_connection"] = "check_connection"


WinstonAIConfig = Annotated[Union[DetectTextConfig, DetectFileConfig, DetectWebsiteConfig,
    PlagiarismTextConfig, PlagiarismFileConfig, PlagiarismWebsiteConfig, FactCheckConfig,
    ImageURLConfig, ImageDataConfig, AdvancedImageConfig, CompareTextConfig, CheckConnectionConfig],
    Field(discriminator="operation")]


class WinstonAIFullConfig(NodeConfig[WinstonAIConfig, WinstonAIApiKeyCredential]):
    pass


ROUTES = {
    "detect_ai_text": "/v2/ai-content-detection",
    "detect_ai_file": "/v2/ai-content-detection",
    "detect_ai_website": "/v2/ai-content-detection",
    "check_plagiarism_text": "/v2/plagiarism",
    "check_plagiarism_file": "/v2/plagiarism",
    "check_plagiarism_website": "/v2/plagiarism",
    "fact_check_text": "/v2/fact-checker",
    "detect_ai_image_url": "/v2/image-detection",
    "detect_ai_image_data": "/v2/image-detection",
    "analyze_image_forensics": "/v2/advanced-image-detection",
    "compare_texts": "/v2/text-compare",
    "check_connection": "/mcp/v1",
}


class WinstonAINode(WorkflowNode):
    integration_type = "automation-winston-ai"
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="Winston AI API tools", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return WinstonAIFullConfig

    async def execute(self, inputs):
        config = self.config
        if not isinstance(config, WinstonAIFullConfig) or config.credentials is None:
            raise ValueError("A Winston AI API key is required")
        operation = config.config.operation
        probe = operation == "check_connection"
        payload = ({"jsonrpc": "2.0", "method": "tools/list", "id": 1} if probe else
            config.config.model_dump(exclude={"operation"}, exclude_none=True))
        if "file_url" in payload:
            payload["file"] = payload.pop("file_url")
        # A single request, no automatic retries: retrying analyses can double-charge.
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request("POST", BASE + ROUTES[operation], json=payload, headers={
                "Authorization": "Bearer " + config.credentials.api_key,
                "Accept": "application/json, text/event-stream" if probe else "application/json",
            })
        if not 200 <= response.status_code < 300:
            message = "Winston AI request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("description") or error.get("error") or message)
            except (ValueError, TypeError):
                pass
            # Don't return the request, headers, encoded bodies or a reflected secret.
            message = message.replace(config.credentials.api_key, "[redacted]")
            raise ValueError(f"Winston AI HTTP {response.status_code}: {message[:1000]}")
        if probe and response.headers.get("content-type", "").startswith("text/event-stream"):
            messages = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
            body = next((m for m in messages if isinstance(m, dict) and m.get("id") == 1), None)
        else:
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a Winston AI JSON object")
        if body.get("error"):
            raise ValueError(str(body.get("description") or body["error"]).replace(config.credentials.api_key, "[redacted]")[:1000])
        if probe:
            result = body.get("result")
            if body.get("jsonrpc") != "2.0" or body.get("id") != 1 or not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise ValueError("Winston AI did not return an MCP tool list")
            tools = result["tools"]
            if not tools or any(not isinstance(t, dict) or not isinstance(t.get("name"), str) for t in tools):
                raise ValueError("Winston AI returned an invalid MCP tool list")
            return {"key_accepted": True, "tools": [{"name": t["name"]} for t in tools], "account_identity_verified": False}
        return body
