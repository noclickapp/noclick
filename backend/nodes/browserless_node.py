"""Browserless REST automation, pinned to the provider's v2 API contract.

Authentication: https://docs.browserless.io/rest-apis/intro#authentication
Endpoint reference: https://docs.browserless.io/openapi.json
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class BrowserlessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Browserless API Token", json_schema_extra={
        "x-credential-url": "https://www.browserless.io/account",
        "x-credential-instructions": "Copy your API token from the Browserless account dashboard. Choose the region where your profiles and crawls are stored.",
    })
    credential_type: Literal["browserless_token"] = Field("browserless_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API Token", repr=False,
        json_schema_extra={"ui:widget": "password"})
    region: Literal["sfo", "lon", "ams"] = Field("sfo", title="Region", description="San Francisco (sfo), London (lon), or Amsterdam (ams).")

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if not value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the Browserless API token without a URL or prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    url: str = Field(..., title="Page URL", description="The HTTP or HTTPS page Browserless should visit.")
    wait_for_timeout: int | None = Field(None, ge=0, le=120000, title="Wait After Load (ms)")

    @field_validator("url")
    @classmethod
    def url_value(cls, value):
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("Enter an HTTP or HTTPS URL without embedded credentials")
        return value


class BrowserlessScreenshotConfig(_Page):
    """Capture a page as a PNG file."""
    operation: Literal["take_screenshot"] = "take_screenshot"
    full_page: bool = Field(True, title="Full Page")


class BrowserlessPdfConfig(_Page):
    """Render a page to a PDF file."""
    operation: Literal["generate_pdf"] = "generate_pdf"
    print_background: bool = Field(True, title="Print Background")
    landscape: bool = False


class BrowserlessContentConfig(_Page):
    """Read the fully rendered HTML of a page."""
    operation: Literal["get_content"] = "get_content"


class BrowserlessElement(_Input):
    selector: str = Field(..., min_length=1, title="CSS Selector")
    timeout: int | None = Field(None, ge=0, title="Selector Timeout (ms)")


class BrowserlessScrapeConfig(_Page):
    """Extract structured data using CSS selectors."""
    operation: Literal["scrape_elements"] = "scrape_elements"
    elements: list[BrowserlessElement] = Field(..., min_length=1, title="Elements")


class BrowserlessPerformanceConfig(_Input):
    """Run a Lighthouse performance audit."""
    operation: Literal["get_performance"] = "get_performance"
    url: str = Field(..., title="Page URL")
    _url = field_validator("url")(_Page.url_value.__func__)


class BrowserlessSearchConfig(_Input):
    """Search the web for matching pages."""
    operation: Literal["search"] = "search"
    query: str = Field(..., min_length=1, title="Search Query")
    limit: int = Field(10, ge=1, le=100, title="Result Limit")
    country: str | None = Field(None, pattern=r"^[a-zA-Z]{2}$", title="Country Code")


class BrowserlessMapConfig(_Input):
    """Discover links on a site and its sitemap."""
    operation: Literal["map_site"] = "map_site"
    url: str = Field(..., title="Site URL")
    limit: int = Field(100, ge=1, le=5000, title="Link Limit")
    sitemap: Literal["include", "only", "skip"] = "include"
    _url = field_validator("url")(_Page.url_value.__func__)


class BrowserlessListCrawlsConfig(_Input):
    """List the account's crawl jobs, one page at a time."""
    operation: Literal["list_crawls"] = "list_crawls"
    limit: int = Field(20, ge=1, le=100)
    cursor: str | None = Field(None, title="Next Cursor")
    status: Literal["in-progress", "completed", "failed", "cancelled"] | None = None


class BrowserlessStartCrawlConfig(_Input):
    """Start an asynchronous crawl of a website."""
    operation: Literal["start_crawl"] = "start_crawl"
    url: str = Field(..., title="Site URL")
    limit: int = Field(100, ge=1, le=10000, title="Page Limit")
    max_depth: int = Field(5, ge=0, le=100, title="Maximum Depth")
    _url = field_validator("url")(_Page.url_value.__func__)


class _Crawl(_Input):
    crawl_id: str = Field(..., min_length=1, max_length=256, title="Crawl ID")

    @field_validator("crawl_id")
    @classmethod
    def resource_segment(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter a resource name or ID without path traversal or controls")
        return value


class BrowserlessGetCrawlConfig(_Crawl):
    """Read crawl progress and the current results page."""
    operation: Literal["get_crawl"] = "get_crawl"
    skip: int = Field(0, ge=0, title="Pages to Skip")


class BrowserlessCancelCrawlConfig(_Crawl):
    """Cancel a running crawl job."""
    operation: Literal["cancel_crawl"] = "cancel_crawl"


class BrowserlessListProfilesConfig(_Input):
    """List the account's saved authentication profiles."""
    operation: Literal["list_profiles"] = "list_profiles"
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class _Profile(_Input):
    profile_name: str = Field(..., min_length=1, max_length=256, title="Profile Name")
    _name = field_validator("profile_name")(_Crawl.resource_segment.__func__)


class BrowserlessGetProfileConfig(_Profile):
    """Read a saved profile's metadata."""
    operation: Literal["get_profile"] = "get_profile"


class BrowserlessRenameProfileConfig(_Profile):
    """Rename a saved authentication profile."""
    operation: Literal["rename_profile"] = "rename_profile"
    new_name: str = Field(..., min_length=1, max_length=256, title="New Name")


class BrowserlessDeleteProfileConfig(_Profile):
    """Permanently delete a saved authentication profile."""
    operation: Literal["delete_profile"] = "delete_profile"


class BrowserlessCreateSessionConfig(_Input):
    """Create a persistent browser session for further automation."""
    operation: Literal["create_session"] = "create_session"
    ttl: int = Field(..., ge=0, title="Session Lifetime (ms)", description="Zero uses your plan's maximum retention.")
    stealth: bool = False
    profile: str | None = Field(None, title="Saved Profile Name")


BrowserlessConfig = Annotated[Union[
    BrowserlessScreenshotConfig, BrowserlessPdfConfig, BrowserlessContentConfig,
    BrowserlessScrapeConfig, BrowserlessPerformanceConfig, BrowserlessSearchConfig,
    BrowserlessMapConfig, BrowserlessListCrawlsConfig, BrowserlessStartCrawlConfig,
    BrowserlessGetCrawlConfig, BrowserlessCancelCrawlConfig, BrowserlessListProfilesConfig,
    BrowserlessGetProfileConfig, BrowserlessRenameProfileConfig, BrowserlessDeleteProfileConfig,
    BrowserlessCreateSessionConfig,
], Field(discriminator="operation")]


class BrowserlessFullConfig(NodeConfig[BrowserlessConfig, BrowserlessTokenCredential]):
    pass


class BrowserlessNode(WorkflowNode):
    integration_type = "automation-browserless"
    connection_evidence = ConnectionEvidence(operation="list_profiles", noun="saved browser profiles")

    @classmethod
    def get_config_model(cls):
        return BrowserlessFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Browserless API token")
        config = self.config.config
        op = config.operation
        params = {"token": credential.api_token}
        body = None
        method = "POST"
        if op in {"take_screenshot", "generate_pdf", "get_content", "scrape_elements"}:
            path = {"take_screenshot": "/screenshot", "generate_pdf": "/pdf",
                "get_content": "/chromium/content", "scrape_elements": "/chromium/scrape"}[op]
            body = {"url": config.url}
            if config.wait_for_timeout is not None:
                body["waitForTimeout"] = config.wait_for_timeout
            if op == "take_screenshot":
                body["options"] = {"type": "png", "fullPage": config.full_page, "encoding": "binary"}
            elif op == "generate_pdf":
                body["options"] = {"printBackground": config.print_background, "landscape": config.landscape}
            elif op == "scrape_elements":
                body["elements"] = [v.model_dump(exclude_none=True) for v in config.elements]
        elif op in {"get_performance", "search", "map_site", "start_crawl", "create_session"}:
            path = {"get_performance": "/chromium/performance", "search": "/search", "map_site": "/map",
                "start_crawl": "/crawl", "create_session": "/session"}[op]
            body = config.model_dump(exclude={"operation"}, exclude_none=True)
            if "max_depth" in body:
                body["maxDepth"] = body.pop("max_depth")
        elif op in {"list_profiles", "list_crawls"}:
            method = "GET"
            path = "/profiles" if op == "list_profiles" else "/crawl"
            params.update(config.model_dump(exclude={"operation"}, exclude_none=True))
        elif op in {"get_crawl", "cancel_crawl"}:
            method = "GET" if op == "get_crawl" else "DELETE"
            path = "/crawl/" + quote(config.crawl_id, safe="")
            if op == "get_crawl":
                params["skip"] = config.skip
        else:
            method = {"get_profile": "GET", "rename_profile": "PUT", "delete_profile": "DELETE"}[op]
            path = "/profile/" + quote(config.profile_name, safe="")
            if op == "rename_profile":
                body = {"name": config.new_name}
        url = "https://production-" + credential.region + ".browserless.io" + path
        try:
            async with guarded_async_client(timeout=180, follow_redirects=False) as client:
                response = await client.request(method, url, params=params,
                    headers={"Accept": "*/*"}, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Browserless request could not be completed") from None
        if not response.is_success:
            # Query-string authentication must never escape in HTTP exception URLs.
            detail = response.text.replace(credential.api_token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": detail or "Browserless request failed"}
        if op == "take_screenshot":
            return {"status": "success", "file": BinaryOutput(response.content, "image/png", "screenshot.png")}
        if op == "generate_pdf":
            return {"status": "success", "file": BinaryOutput(response.content, "application/pdf", "page.pdf")}
        if op == "get_content":
            return {"status": "success", "html": response.text}
        if not response.content:
            return {"status": "success"}
        return {"status": "success", "data": response.json()}
