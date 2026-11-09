"""Parsera API-key operations against the published v1 contract.

Each action performs one request; asynchronous actions return their task/run
identifier for a separate status operation rather than polling or retrying writes.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.parsera.org"


class ParseraAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Parsera API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://parsera.org/docs/quickstart",
            "x-credential-instructions": "Paste your Parsera API key from the dashboard. NoClick verifies it by listing your scrapers.",
        })
    credential_type: Literal["parsera_api_key"] = Field("parsera_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("scraper_id", "task_id", "run_id", "template_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
            raise ValueError("Use a single Parsera resource identifier")
        return value


class Attribute(_Input):
    name: str
    description: str = ""
    type: Literal["string", "integer", "number", "bool", "list", "object", "any", "image"] = "any"


class AttributeData(_Input):
    description: str = ""
    type: Literal["string", "integer", "number", "bool", "list", "object", "any"] = "any"


Attributes = dict[str, AttributeData] | dict[str, str] | list[Attribute]


class _Extraction(_Input):
    attributes: Attributes = Field(..., description="Fields to extract: a name-to-description object, typed field object, or list of attributes.")
    prompt: str = ""
    mode: Literal["standard", "code"] = "standard"
    enable_pagination: bool = False
    max_pages: int = Field(2, ge=1)
    source: str = "api"


class _Website(_Input):
    url: str = Field(..., min_length=1, description="Webpage URL to extract through Parsera.")
    proxy_country: str | None = None
    cookies: list[dict] | None = None


class Extract(_Extraction, _Website):
    """Extract structured fields from a webpage synchronously."""
    operation: Literal["extract"] = Field("extract", json_schema_extra={"ui:hidden": True})


class Parse(_Extraction):
    """Extract structured fields from supplied text or HTML."""
    operation: Literal["parse"] = Field("parse", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "textarea"})


class ExtractMarkdown(_Website):
    """Fetch webpage content as Markdown."""
    operation: Literal["extract_markdown"] = Field("extract_markdown", json_schema_extra={"ui:hidden": True})


class ExtractAsync(_Extraction, _Website):
    """Start an asynchronous structured extraction; poll its task separately."""
    operation: Literal["extract_async"] = Field("extract_async", json_schema_extra={"ui:hidden": True})
    callback_url: str | None = Field(None, description="Optional webhook URL Parsera calls when the task finishes.")


class _AgentInput(_Input):
    url: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    attributes: list[Attribute] | None = None


class AgentExtract(_AgentInput):
    """Start one-shot agent extraction without creating a reusable scraper."""
    operation: Literal["agent_extract"] = Field("agent_extract", json_schema_extra={"ui:hidden": True})
    callback_url: str | None = None
    source: str = "api"


class GenerateAgentScraper(_AgentInput):
    """Build a reusable agentic scraper, optionally using an existing template."""
    operation: Literal["generate_agent_scraper"] = Field("generate_agent_scraper", json_schema_extra={"ui:hidden": True})
    template_id: str | None = None


class _Run(_Input):
    template_id: str = Field(..., description="ID of the reusable scraper to run.")
    url: str | list[str] | None = None
    proxy_country: str | None = None
    cookies: list[dict] | None = None
    source: str = "api"
    parameters: dict | None = None


class RunScraper(_Run):
    """Run a reusable scraper and wait for its result in this API call."""
    operation: Literal["run_scraper"] = Field("run_scraper", json_schema_extra={"ui:hidden": True})
    pagination_detection_url: str | None = None


class RunScraperAsync(_Run):
    """Start a reusable scraper run and return immediately with its run ID."""
    operation: Literal["run_scraper_async"] = Field("run_scraper_async", json_schema_extra={"ui:hidden": True})
    max_pages: int | None = Field(None, ge=1)
    callback_url: str | None = None


class GetExtractionStatus(_Input):
    """Get extraction status using the published Parsera endpoint."""
    operation: Literal["get_extraction_status"] = Field("get_extraction_status", json_schema_extra={"ui:hidden": True})
    task_id: str


class CreateClassicScraper(_Input):
    """Create classic scraper using the published Parsera endpoint."""
    operation: Literal["create_classic_scraper"] = Field("create_classic_scraper", json_schema_extra={"ui:hidden": True})


class GetClassicScraper(_Input):
    """Get classic scraper using the published Parsera endpoint."""
    operation: Literal["get_classic_scraper"] = Field("get_classic_scraper", json_schema_extra={"ui:hidden": True})
    scraper_id: str


class DeleteClassicScraper(_Input):
    """Delete classic scraper using the published Parsera endpoint."""
    operation: Literal["delete_classic_scraper"] = Field("delete_classic_scraper", json_schema_extra={"ui:hidden": True})
    scraper_id: str


class GetAgentExtractionStatus(_Input):
    """Get agent extraction status using the published Parsera endpoint."""
    operation: Literal["get_agent_extraction_status"] = Field("get_agent_extraction_status", json_schema_extra={"ui:hidden": True})
    task_id: str


class StopAgentExtraction(_Input):
    """Stop agent extraction using the published Parsera endpoint."""
    operation: Literal["stop_agent_extraction"] = Field("stop_agent_extraction", json_schema_extra={"ui:hidden": True})
    task_id: str


class CreateAgentScraper(_Input):
    """Create agent scraper using the published Parsera endpoint."""
    operation: Literal["create_agent_scraper"] = Field("create_agent_scraper", json_schema_extra={"ui:hidden": True})


class GetAgentScraper(_Input):
    """Get agent scraper using the published Parsera endpoint."""
    operation: Literal["get_agent_scraper"] = Field("get_agent_scraper", json_schema_extra={"ui:hidden": True})
    scraper_id: str


class DeleteAgentScraper(_Input):
    """Delete agent scraper using the published Parsera endpoint."""
    operation: Literal["delete_agent_scraper"] = Field("delete_agent_scraper", json_schema_extra={"ui:hidden": True})
    scraper_id: str


class ListScrapers(_Input):
    """List scrapers using the published Parsera endpoint."""
    operation: Literal["list_scrapers"] = Field("list_scrapers", json_schema_extra={"ui:hidden": True})


class GetScraperRunStatus(_Input):
    """Get scraper run status using the published Parsera endpoint."""
    operation: Literal["get_scraper_run_status"] = Field("get_scraper_run_status", json_schema_extra={"ui:hidden": True})
    run_id: str


ParseraConfig = Annotated[Union[
    Extract, Parse, ExtractMarkdown, ExtractAsync, GetExtractionStatus, CreateClassicScraper, GetClassicScraper, DeleteClassicScraper, AgentExtract, GetAgentExtractionStatus, StopAgentExtraction, CreateAgentScraper, GenerateAgentScraper, GetAgentScraper, DeleteAgentScraper, ListScrapers, RunScraper, RunScraperAsync, GetScraperRunStatus
], Field(discriminator="operation")]


class ParseraNodeConfig(NodeConfig[ParseraConfig, ParseraAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "extract": ("POST", "/v1/extractor/extract", None),
    "parse": ("POST", "/v1/extractor/parse", None),
    "extract_markdown": ("POST", "/v1/extractor/extract_markdown", None),
    "extract_async": ("POST", "/v1/extractor/extract_async", None),
    "get_extraction_status": ("GET", "/v1/extractor/extract_async/{task_id}", 'task_id'),
    "create_classic_scraper": ("POST", "/v1/extractor/new", None),
    "get_classic_scraper": ("GET", "/v1/extractor/{scraper_id}", 'scraper_id'),
    "delete_classic_scraper": ("DELETE", "/v1/extractor/{scraper_id}", 'scraper_id'),
    "agent_extract": ("POST", "/v1/agent/extract", None),
    "get_agent_extraction_status": ("GET", "/v1/agent/extract/{task_id}", 'task_id'),
    "stop_agent_extraction": ("POST", "/v1/agent/extract/{task_id}/stop", 'task_id'),
    "create_agent_scraper": ("POST", "/v1/agent/new", None),
    "generate_agent_scraper": ("POST", "/v1/agent/generate", None),
    "get_agent_scraper": ("GET", "/v1/agent/{scraper_id}", 'scraper_id'),
    "delete_agent_scraper": ("DELETE", "/v1/agent/{scraper_id}", 'scraper_id'),
    "list_scrapers": ("GET", "/v1/scrapers", None),
    "run_scraper": ("POST", "/v1/scrapers/run", None),
    "run_scraper_async": ("POST", "/v1/scrapers/run_async", None),
    "get_scraper_run_status": ("GET", "/v1/scrapers/run_async/{run_id}", 'run_id'),
}


class ParseraNode(WorkflowNode):
    integration_type = "automation-parsera"
    connection_evidence = ConnectionEvidence(noun="scrapers", operation="list_scrapers")

    @classmethod
    def get_config_model(cls):
        return ParseraNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Parsera API key")
        op = self.config.config
        method, path, parameter = ROUTES[op.operation]
        if parameter:
            path = path.format(**{parameter: getattr(op, parameter)})
        body = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        # No arbitrary route, method, headers or extra wire parameters are accepted.
        kwargs = {"json": body} if method == "POST" and body and parameter is None else {}
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=180, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"X-API-KEY": key, "Accept": "application/json"}, **kwargs)
            if not 200 <= response.status_code < 300:
                # Preserve provider rejection text for the manual-connect verdict,
                # but never propagate a reflected key into node output or logs.
                message = response.text[:2000].replace(key, "[redacted]")
                output = {"status": "error", "http_status": response.status_code,
                          "message": message or "Parsera request failed"}
            else:
                data = response.json()
                if op.operation == "list_scrapers" and (
                    not isinstance(data, list) or any(
                        not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("id", "name", "type"))
                        or row["type"] not in {"extractor", "agentic"} for row in data
                    )
                ):
                    raise ValueError("Parsera returned an invalid scraper list")
                output = {"status": "success", "http_status": response.status_code, "data": data}
        except httpx.RequestError:
            # Writes are never retried: a transport failure may happen after acceptance.
            output = {"status": "error", "message": "Parsera request could not be confirmed; inspect task or scraper state before retrying a write"}
        except (ValueError, UnicodeError):
            output = {"status": "error", "message": "Parsera returned an invalid JSON response"}
        output = _redact(output, key)
        await self.emit(output)
        return output


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value
