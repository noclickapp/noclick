"""WebScraping.AI 3.2.2: ten published GET endpoints, one request per action.

Contract: https://webscraping.ai/openapi.yml
Credential and query encoding: https://webscraping.ai/docs
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, quote_plus, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.webscraping.ai"
ROUTES = {
    "ask_question": "/ai/question", "extract_fields": "/ai/fields",
    "get_html": "/html", "get_text": "/text", "get_selected_html": "/selected",
    "get_multiple_selected_html": "/selected-multiple", "search": "/serp",
    "list_search_locations": "/serp/locations", "get_structured_data": "/data",
    "get_account": "/account",
}


class WebscrapingAiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="WebScraping.AI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://webscraping.ai/dashboard",
            "x-credential-instructions": "Copy your API key from the WebScraping.AI dashboard and paste it here. NoClick sends it to api.webscraping.ai as the api_key query parameter. Connecting reads your account credit quota; scraping and search actions consume provider credits.",
            "x-help-url": "https://webscraping.ai/docs#authentication",
        })
    credential_type: Literal["webscraping_ai_api_key"] = Field("webscraping_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    url: str = Field(..., min_length=1, max_length=8192, title="Page URL")
    timeout: Optional[int] = Field(None, ge=1, le=25000, description="Page retrieval timeout in milliseconds.")
    js_timeout: Optional[int] = Field(None, ge=1, le=20000, description="JavaScript rendering timeout in milliseconds.")
    wait_for: Optional[str] = Field(None, max_length=2000, description="CSS selector to wait for.")
    device: Optional[Literal["desktop", "mobile", "tablet"]] = None

    @field_validator("url")
    @classmethod
    def page_url(cls, value):
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
        except ValueError:
            raise ValueError("Provide an HTTP or HTTPS page URL without embedded credentials") from None
        return value


class _Scrape(_Page):
    js: Optional[bool] = Field(None, description="Render JavaScript (provider default: enabled).")
    proxy: Optional[Literal["datacenter", "residential", "stealth", "auto"]] = None
    country: Optional[Literal["us", "gb", "de", "it", "fr", "ca", "es", "ru", "jp", "kr", "in", "hk", "tr"]] = None
    error_on_404: Optional[bool] = None
    error_on_redirect: Optional[bool] = None
    headers_json: Optional[str] = Field(None, title="Target headers (JSON)", description='JSON object of target-page headers, for example {"Accept-Language":"en"}.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("headers_json")
    @classmethod
    def headers(cls, value):
        if value is not None:
            _string_map(value, "Target headers")
        return value


def _string_map(value, label):
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, dict) or not parsed or len(parsed) > 100 or any(
            not isinstance(k, str) or not k or len(k) > 256 or any(c in k for c in "[]\r\n") or
            not isinstance(v, str) or len(v) > 8192 or "\r" in v or "\n" in v for k, v in parsed.items()
        ):
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise ValueError(label + " must be a nonempty JSON object of string values") from None


class AskQuestion(_Scrape):
    """Ask an LLM a question about one page; returns the answer text."""
    operation: Literal["ask_question"] = "ask_question"
    question: str = Field(..., min_length=1, max_length=10000)


class ExtractFields(_Scrape):
    """Extract named fields and descriptions using an LLM; missing values are null."""
    operation: Literal["extract_fields"] = "extract_fields"
    fields_json: str = Field(..., title="Fields to extract (JSON)", description='Map field names to descriptions, for example {"title":"Product title","price":"Current price with currency"}.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("fields_json")
    @classmethod
    def fields(cls, value):
        _string_map(value, "Fields to extract")
        return value


class GetHTML(_Scrape):
    """Retrieve page HTML or the result of a supplied JavaScript expression."""
    operation: Literal["get_html"] = "get_html"
    js_script: Optional[str] = Field(None, max_length=20000, description="Script evaluated on the target page; its last expression is the result. A top-level return is invalid.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "javascript"})
    return_script_result: Optional[bool] = None


class GetText(_Scrape):
    """Retrieve clean Markdown, optionally wrapped as JSON or XML."""
    operation: Literal["get_text"] = "get_text"
    text_format: Literal["plain", "xml", "json"] = "plain"
    return_links: Optional[bool] = Field(None, description="Include links when text_format is json.")


class GetSelectedHTML(_Scrape):
    """Retrieve the HTML of the first matching CSS selector."""
    operation: Literal["get_selected_html"] = "get_selected_html"
    selector: str = Field(..., min_length=1, max_length=2000)


class GetMultipleSelectedHTML(_Scrape):
    """Retrieve one array of matched HTML fragments per CSS selector, in order."""
    operation: Literal["get_multiple_selected_html"] = "get_multiple_selected_html"
    selectors: list[str] = Field(..., min_length=1, max_length=100, description="CSS selectors in request order.")

    @field_validator("selectors")
    @classmethod
    def css(cls, values):
        if any(not value.strip() or len(value) > 2000 for value in values):
            raise ValueError("Each selector must be nonempty and at most 2000 characters")
        return values


class Search(_Input):
    """Search Google; choose explicit pages and use pagination.next for another call."""
    operation: Literal["search"] = "search"
    q: str = Field(..., min_length=1, max_length=10000, title="Search query")
    gl: Optional[str] = Field(None, description="Country code, e.g. us.")
    hl: Optional[str] = Field(None, description="Language code, e.g. en.")
    page: int = Field(1, ge=1, le=100)
    pages: int = Field(1, ge=1, le=5, description="Results pages to fetch; each returned page consumes credits.")
    location: Optional[str] = Field(None, description="Canonical location name or ID returned by List Search Locations.")
    uule: Optional[str] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    radius: Optional[int] = Field(None, ge=1, le=1000)


class ListSearchLocations(_Input):
    """Look up supported SERP locations; this static catalogue is not account evidence."""
    operation: Literal["list_search_locations"] = "list_search_locations"
    q: Optional[str] = Field(None, description="Location search, e.g. Austin.")
    limit: int = Field(10, ge=1, le=10)


class GetStructuredData(_Page):
    """Parse structured page data; parse_failed and not_found are charged responses."""
    operation: Literal["get_structured_data"] = "get_structured_data"
    country: Optional[str] = Field(None, description="Country code; provider default is us.")
    transcript: Optional[bool] = None
    transcript_language: Optional[str] = None


class GetAccount(_Input):
    """Read this key's account email (when returned), credit quota and concurrency."""
    operation: Literal["get_account"] = "get_account"


WebscrapingAiConfig = Annotated[Union[AskQuestion, ExtractFields, GetHTML, GetText,
    GetSelectedHTML, GetMultipleSelectedHTML, Search, ListSearchLocations,
    GetStructuredData, GetAccount], Field(discriminator="operation")]


class WebscrapingAiFullConfig(NodeConfig[WebscrapingAiConfig, WebscrapingAiAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class WebscrapingAiNode(WorkflowNode):
    integration_type = "automation-webscraping-ai"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account", identity_keys=("email",))

    @classmethod
    def get_config_model(cls):
        return WebscrapingAiFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a WebScraping.AI API key")
        config = self.config.config
        key = self.config.credentials.api_key
        params = [("api_key", key)]
        for name, value in config.model_dump(exclude_none=True, exclude={"operation"}).items():
            if name in {"headers_json", "fields_json"}:
                prefix = "headers" if name == "headers_json" else "fields"
                params.extend((prefix + "[" + k + "]", v) for k, v in _string_map(value, prefix).items())
            elif isinstance(value, list):
                params.extend((name, item) for item in value)
            else:
                params.append((name, "true" if value is True else "false" if value is False else str(value)))
        try:
            async with guarded_async_client(timeout=65, trust_env=False, follow_redirects=False) as client:
                response = await client.request("GET", BASE + ROUTES[config.operation], params=params,
                    headers={"Accept": "application/json" if config.operation in {"extract_fields", "get_multiple_selected_html", "search", "list_search_locations", "get_structured_data", "get_account"} else "*/*"})
            if response.status_code != 200:
                error = {"status": "error", "http_status": response.status_code, "error": "WebScraping.AI did not complete the request"}
                try:
                    body = response.json()
                    if isinstance(body, dict):
                        if isinstance(body.get("message"), str): error["error"] = _redact(body["message"][:4000], key)
                        for field in ("error_code", "retry_after"):
                            if isinstance(body.get(field), (str, int)): error[field] = _redact(body[field], key)
                except ValueError:
                    pass
                return error
            if len(response.content) > 10_000_000:
                raise ValueError("WebScraping.AI response exceeds 10 MB")
            json_ops = {"extract_fields", "get_multiple_selected_html", "search", "list_search_locations", "get_structured_data", "get_account"}
            if config.operation in json_ops:
                data = response.json()
                _check_response(config.operation, data)
            elif response.headers.get("content-type", "").split(";", 1)[0].strip() == "application/json":
                data = response.json()
            else:
                data = response.text
            return {"status": "success", "operation": config.operation, "data": _redact(data, key)}
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "WebScraping.AI could not be reached; try again later"}
        except (ValueError, TypeError):
            return {"status": "error", "error": "WebScraping.AI returned an unexpected response"}


def _redact(value, key):
    if isinstance(value, str):
        for secret in {key, quote(key, safe=""), quote_plus(key)}:
            value = value.replace(secret, "[redacted]")
    elif isinstance(value, list):
        return [_redact(item, key) for item in value]
    elif isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


def _check_response(operation, data):
    if operation == "get_multiple_selected_html":
        valid = isinstance(data, list) and all(isinstance(row, list) and all(isinstance(item, str) for item in row) for row in data)
    elif operation == "list_search_locations":
        valid = isinstance(data, list) and all(isinstance(row, dict) for row in data)
    else:
        valid = isinstance(data, dict) and not any(field in data for field in ("error", "error_code", "message"))
        if valid and operation == "get_account":
            valid = any(field in data for field in ("email", "remaining_api_calls", "remaining_monthly_credits", "remaining_payg_credits", "remaining_total_credits", "resets_at", "remaining_concurrency"))
        if valid and operation == "extract_fields":
            valid = isinstance(data.get("result"), dict)
    if not valid:
        raise ValueError("Unexpected WebScraping.AI response shape")
