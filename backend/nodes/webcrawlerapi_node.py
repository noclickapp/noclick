"""Webcrawlerapi crawling, extraction, agents, and website-change feeds.

Each operation makes one request to the provider's published Swagger 2.0 contract:
https://api.webcrawlerapi.com/swagger/doc.json. API keys stay on that fixed origin.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.webcrawlerapi.com"


def _operation(name: str, category: str, label: str):
    return Field(name, title=label, json_schema_extra={
        "ui:hidden": True, "x-display-name": label, "x-category": category,
        "x-is-trigger": False,
    })


def _url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Use an HTTP or HTTPS URL without embedded credentials")
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Use a URL without whitespace")
    return value


class WebcrawlerapiApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Webcrawlerapi API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dash.webcrawlerapi.com/",
            "x-credential-instructions": "Paste your Webcrawlerapi API key from the dashboard's API key section. NoClick sends it as a Bearer token to api.webcrawlerapi.com. Crawls, scrapes, agents and feed runs use your provider credits.",
        })
    credential_type: Literal["webcrawlerapi_api_key"] = Field(
        "webcrawlerapi_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the key alone without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("response_schema", "output_schema", mode="before", check_fields=False)
    @classmethod
    def json_object(cls, value):
        if value is None:
            return value
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except (ValueError, TypeError):
            raise ValueError("Provide a JSON schema object") from None
        if not isinstance(parsed, dict):
            raise ValueError("Provide a JSON schema object")
        return json.dumps(parsed)



class _URLInput(_Input):
    url: str = Field(..., min_length=1, max_length=8192, title="Website URL")

    @field_validator("url")
    @classmethod
    def website(cls, value):
        return _url(value)


class _CrawlOptions(_URLInput):
    items_limit: int = Field(10, ge=1, title="Page limit")
    max_depth: int | None = Field(None, ge=0, title="Maximum crawl depth")
    main_content_only: bool | None = Field(None, title="Extract main content only")
    respect_robots_txt: bool | None = Field(None, title="Respect robots.txt")
    whitelist_regexp: str | None = Field(None, title="Include URL pattern")
    blacklist_regexp: str | None = Field(None, title="Exclude URL pattern")
    webhook_url: str | None = Field(None, title="Completion webhook URL")

    @field_validator("webhook_url")
    @classmethod
    def webhook(cls, value):
        return _url(value) if value is not None else value


class _OutputFormats(_Input):
    output_formats: str = Field("markdown", title="Output formats",
        description="Comma-separated formats: markdown, cleaned, html, links.")

    @field_validator("output_formats")
    @classmethod
    def formats(cls, value):
        formats = [v.strip() for v in value.split(",")]
        if not formats or any(v not in {"markdown", "cleaned", "html", "links"} for v in formats):
            raise ValueError("Choose markdown, cleaned, html or links, separated by commas")
        return ",".join(dict.fromkeys(formats))


class WebcrawlerapiCheckConnectionConfig(_Input):
    operation: Literal["check_connection"] = _operation("check_connection", "Account", "Check Connection")


class WebcrawlerapiExtractMarkdownConfig(_URLInput):
    operation: Literal["extract_markdown"] = _operation("extract_markdown", "Extraction", "Extract Clean Markdown")


class WebcrawlerapiCreateCrawlConfig(_CrawlOptions, _OutputFormats):
    operation: Literal["create_crawl"] = _operation("create_crawl", "Crawls", "Create Crawl")
    max_age: int | None = Field(None, ge=0, title="Maximum cache age (seconds)")


class _JobInput(_Input):
    job_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", title="Job ID")


class WebcrawlerapiGetJobConfig(_JobInput):
    operation: Literal["get_job"] = _operation("get_job", "Crawls", "Get Crawl Job")


class WebcrawlerapiCancelJobConfig(_JobInput):
    operation: Literal["cancel_job"] = _operation("cancel_job", "Crawls", "Cancel Crawl Job")


class WebcrawlerapiGetJobUrlsConfig(_JobInput):
    operation: Literal["get_job_urls"] = _operation("get_job_urls", "Crawls", "Get Discovered URLs")


class WebcrawlerapiResendJobWebhookConfig(_JobInput):
    operation: Literal["resend_job_webhook"] = _operation("resend_job_webhook", "Crawls", "Resend Crawl Webhook")


class WebcrawlerapiCreateScrapeConfig(_URLInput, _OutputFormats):
    """Always enqueue asynchronously; retrieve the result with Get Scrape."""
    operation: Literal["create_scrape"] = _operation("create_scrape", "Extraction", "Create Async Scrape")
    main_content_only: bool | None = Field(None, title="Extract main content only")
    respect_robots_txt: bool | None = Field(None, title="Respect robots.txt")
    max_age: int | None = Field(None, ge=0, title="Maximum cache age (seconds)")
    clean_selectors: str | None = Field(None, title="CSS selectors to remove")
    prompt: str | None = Field(None, title="Extraction prompt")
    response_schema: str | None = Field(None, title="Response JSON schema", json_schema_extra={"ui:widget": "textarea"})


class WebcrawlerapiGetScrapeConfig(_Input):
    operation: Literal["get_scrape"] = _operation("get_scrape", "Extraction", "Get Scrape Result")
    scrape_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", title="Scrape ID")


class WebcrawlerapiRunAgentConfig(_Input):
    operation: Literal["run_agent"] = _operation("run_agent", "Agents", "Run Crawling Agent")
    prompt: str = Field(..., min_length=1, title="Task", json_schema_extra={"ui:widget": "textarea"})
    max_spend_usd: float = Field(..., gt=0, title="Maximum spend (USD)")
    urls: str | None = Field(None, title="Seed URLs", description="One HTTP or HTTPS URL per line.",
        json_schema_extra={"ui:widget": "textarea"})
    seed_urls_only: bool | None = Field(None, title="Use only seed URLs")
    output_schema: str | None = Field(None, title="Output JSON schema", json_schema_extra={"ui:widget": "textarea"})
    model: str | None = Field(None, title="Model")
    max_age: int | None = Field(None, ge=0, title="Maximum cache age (seconds)")

    @field_validator("urls")
    @classmethod
    def seed_urls(cls, value):
        if value is None:
            return value
        urls = [line.strip() for line in value.splitlines() if line.strip()]
        if not urls:
            raise ValueError("Provide at least one seed URL or leave the field empty")
        return "\n".join(_url(v) for v in urls)


class WebcrawlerapiGetAgentJobConfig(_Input):
    operation: Literal["get_agent_job"] = _operation("get_agent_job", "Agents", "Get Agent Job")
    agent_job_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", title="Agent job ID")


class WebcrawlerapiListAgentJobsConfig(_Input):
    operation: Literal["list_agent_jobs"] = _operation("list_agent_jobs", "Agents", "List Agent Jobs")
    limit: int = Field(20, ge=1, title="Page size")
    offset: int = Field(0, ge=0, title="Offset", description="Read one page; advance the offset to fetch more jobs.")


class WebcrawlerapiCreateFeedConfig(_CrawlOptions):
    operation: Literal["create_feed"] = _operation("create_feed", "Feeds", "Create Website Feed")
    name: str | None = Field(None, title="Feed name")
    output_format: Literal["markdown", "cleaned", "html"] = Field("markdown", title="Output format")
    include_errors: bool | None = Field(None, title="Include errored pages")


class _FeedInput(_Input):
    feed_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", title="Feed ID")


class WebcrawlerapiGetFeedConfig(_FeedInput):
    operation: Literal["get_feed"] = _operation("get_feed", "Feeds", "Get Feed")


class WebcrawlerapiDeleteFeedConfig(_FeedInput):
    operation: Literal["delete_feed"] = _operation("delete_feed", "Feeds", "Delete Feed Permanently")


class _FeedPage(_FeedInput):
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(20, ge=1, le=1000, title="Page size", description="Read one page; increment Page to fetch more entries.")


class WebcrawlerapiGetFeedJsonConfig(_FeedPage):
    operation: Literal["get_feed_json"] = _operation("get_feed_json", "Feeds", "Get JSON Feed Page")


class WebcrawlerapiPauseFeedConfig(_FeedInput):
    operation: Literal["pause_feed"] = _operation("pause_feed", "Feeds", "Pause Feed")


class WebcrawlerapiResumeFeedConfig(_FeedInput):
    operation: Literal["resume_feed"] = _operation("resume_feed", "Feeds", "Resume Feed")


class WebcrawlerapiRunFeedConfig(_FeedInput):
    operation: Literal["run_feed"] = _operation("run_feed", "Feeds", "Run Feed Now")


class WebcrawlerapiResendFeedWebhookConfig(_FeedInput):
    operation: Literal["resend_feed_webhook"] = _operation("resend_feed_webhook", "Feeds", "Resend Feed Webhook")


class WebcrawlerapiListFeedsConfig(_Input):
    operation: Literal["list_feeds"] = _operation("list_feeds", "Feeds", "List Feeds")


class WebcrawlerapiGetUsageConfig(_Input):
    operation: Literal["get_usage"] = _operation("get_usage", "Account", "Get Organization Usage")
    from_date: date | None = Field(None, title="From date", description="YYYY-MM-DD")
    to_date: date | None = Field(None, title="To date", description="YYYY-MM-DD")
    include_daily: bool | None = Field(None, title="Include daily breakdown")

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("To date must be on or after From date")
        return self


WebcrawlerapiConfig = Annotated[Union[
    WebcrawlerapiCheckConnectionConfig, WebcrawlerapiExtractMarkdownConfig,
    WebcrawlerapiCreateCrawlConfig, WebcrawlerapiGetJobConfig,
    WebcrawlerapiCancelJobConfig,
    WebcrawlerapiGetJobUrlsConfig, WebcrawlerapiResendJobWebhookConfig,
    WebcrawlerapiCreateScrapeConfig, WebcrawlerapiGetScrapeConfig,
    WebcrawlerapiRunAgentConfig, WebcrawlerapiGetAgentJobConfig,
    WebcrawlerapiListAgentJobsConfig, WebcrawlerapiCreateFeedConfig,
    WebcrawlerapiGetFeedConfig, WebcrawlerapiDeleteFeedConfig,
    WebcrawlerapiGetFeedJsonConfig,
    WebcrawlerapiPauseFeedConfig, WebcrawlerapiResumeFeedConfig,
    WebcrawlerapiRunFeedConfig, WebcrawlerapiResendFeedWebhookConfig,
    WebcrawlerapiListFeedsConfig, WebcrawlerapiGetUsageConfig,
], Field(discriminator="operation")]


class WebcrawlerapiFullConfig(NodeConfig[WebcrawlerapiConfig, WebcrawlerapiApiKeyCredential]):
    pass


# Route, verb, and response kind are intentionally fixed per operation. No generic
# URL or verb option can forward an attached credential elsewhere.
ROUTES = {
    "check_connection": ("GET", "/v1/auth", "json"),
    "extract_markdown": ("POST", "/markdown", "json"),
    "create_crawl": ("POST", "/v1/crawl", "json"),
    "get_job": ("GET", "/v1/job/{job_id}", "json"),
    "cancel_job": ("PUT", "/v1/job/{job_id}/cancel", "json"),
    "get_job_urls": ("GET", "/v1/job/{job_id}/urls", "json"),
    "resend_job_webhook": ("POST", "/v1/job/{job_id}/webhook/resend", "json"),
    "create_scrape": ("POST", "/v2/scrape", "json"),
    "get_scrape": ("GET", "/v2/scrape/{scrape_id}", "json"),
    "run_agent": ("POST", "/v1/agent", "json"),
    "get_agent_job": ("GET", "/v1/agent/job/{agent_job_id}", "json"),
    "list_agent_jobs": ("GET", "/v1/agent/jobs", "json"),
    "create_feed": ("POST", "/v2/feed", "json"),
    "get_feed": ("GET", "/v2/feed/{feed_id}", "json"),
    "delete_feed": ("DELETE", "/v2/feed/{feed_id}", "json"),
    "get_feed_json": ("GET", "/v2/feed/{feed_id}/json", "json"),
    "pause_feed": ("PUT", "/v2/feed/{feed_id}/pause", "json"),
    "resume_feed": ("PUT", "/v2/feed/{feed_id}/resume", "json"),
    "run_feed": ("PUT", "/v2/feed/{feed_id}/run", "json"),
    "resend_feed_webhook": ("POST", "/v2/feed/{feed_id}/webhook/resend", "json"),
    "list_feeds": ("GET", "/v2/feeds", "json"),
    "get_usage": ("GET", "/v2/organization/usage", "json"),
}


class WebcrawlerapiNode(WorkflowNode):
    integration_type = "automation-webcrawlerapi"
    connection_evidence = ConnectionEvidence(
        noun="Webcrawlerapi organization", identity_operation="check_connection")

    @classmethod
    def get_config_model(cls):
        return WebcrawlerapiFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Webcrawlerapi API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, _ = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in ("job_id", "scrape_id", "agent_job_id", "feed_id"):
            if field in values:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        if "output_formats" in values:
            values["output_formats"] = values["output_formats"].split(",")
        for field in ("response_schema", "output_schema"):
            if field in values:
                values[field] = json.loads(values[field])
        if op.operation == "run_agent" and "urls" in values:
            values["urls"] = values["urls"].splitlines()
        if op.operation == "get_usage":
            for field, target in (("from_date", "from"), ("to_date", "to")):
                if field in values:
                    values[target] = values.pop(field)
        query = {"async": "true"} if op.operation == "create_scrape" else {}
        kwargs = {"json": values} if method == "POST" and values else {}
        if method == "GET":
            query.update({k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()})
        try:
            async with guarded_async_client(timeout=120, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + key,
                        "Accept": "application/json"},
                    params=query, **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "Webcrawlerapi request could not be completed"}
        if len(response.content) > 20_000_000:
            raise ValueError("Webcrawlerapi response exceeds 20 MB")
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            body = None
        if not 200 <= response.status_code < 300:
            message = (body.get("error_message") or body.get("error") or body.get("message")) if isinstance(body, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": str(message or "Webcrawlerapi request failed").replace(key, "[redacted]")}
        if isinstance(body, dict) and (body.get("error") or body.get("error_code") or (
                body.get("success") is False and op.operation in {"extract_markdown", "get_scrape", "create_scrape", "resend_job_webhook", "resend_feed_webhook"})):
            return {"status": "error", "error": str(body.get("error_message") or body.get("error") or body.get("error_code") or body.get("message") or "Webcrawlerapi reported failure").replace(key, "[redacted]")}
        if not isinstance(body, dict):
            raise ValueError("Webcrawlerapi returned an invalid JSON object")
        if op.operation == "check_connection" and (not isinstance(body.get("email"), str) or not body["email"].strip()):
            raise ValueError("Webcrawlerapi authentication response lacks organization email")
        return {"status": "success", "data": body}
