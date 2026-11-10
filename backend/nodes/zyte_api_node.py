"""Zyte API extraction presets. Each operation makes one POST /v1/extract.

Contract: https://docs.zyte.com/zyte-api/usage/reference.html
No account resources, webhook registration or timestamp-list API is published.
"""
from __future__ import annotations
import base64
import ipaddress
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

class ZyteApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zyte API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.zyte.com/o/zyte-api/api-access",
        "x-credential-instructions": "Copy your Zyte API key from API Access. Connecting makes one extraction request to example.com and may use API credit."})
    credential_type: Literal["zyte_api_key"] = Field("zyte_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", description="Paste the API key, without a Basic prefix or password.", repr=False, json_schema_extra={"ui:widget": "password"})

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _URLInput(_Input):
    url: str = Field(..., max_length=8192, title="Page URL", description="Absolute HTTP or HTTPS URL with a domain hostname.")

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        p = urlsplit(value)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or any(c.isspace() for c in value):
            raise ValueError("Use an absolute HTTP or HTTPS page URL")
        try:
            ipaddress.ip_address(p.hostname)
        except ValueError:
            return value
        raise ValueError("Zyte requires a domain hostname, not an IP address")

class CheckConnection(_Input):
    """Check that Zyte accepts the API key; this may consume extraction credit."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})

class GetHttpBody(_URLInput):
    """Request httpResponseBody from a page using the published extract endpoint."""
    operation: Literal["get_http_body"] = Field("get_http_body", json_schema_extra={"ui:hidden": True})

class GetHttpHeaders(_URLInput):
    """Request httpResponseHeaders from a page using the published extract endpoint."""
    operation: Literal["get_http_headers"] = Field("get_http_headers", json_schema_extra={"ui:hidden": True})

class GetBrowserHtml(_URLInput):
    """Request browserHtml from a page using the published extract endpoint."""
    operation: Literal["get_browser_html"] = Field("get_browser_html", json_schema_extra={"ui:hidden": True})

class GetScreenshot(_URLInput):
    """Request screenshot from a page using the published extract endpoint."""
    operation: Literal["get_screenshot"] = Field("get_screenshot", json_schema_extra={"ui:hidden": True})

class GetMarkdown(_URLInput):
    """Request markdown from a page using the published extract endpoint."""
    operation: Literal["get_markdown"] = Field("get_markdown", json_schema_extra={"ui:hidden": True})

class ExtractArticle(_URLInput):
    """Request article from a page using the published extract endpoint."""
    operation: Literal["extract_article"] = Field("extract_article", json_schema_extra={"ui:hidden": True})

class ExtractArticlelist(_URLInput):
    """Request articleList from a page using the published extract endpoint."""
    operation: Literal["extract_articleList"] = Field("extract_articleList", json_schema_extra={"ui:hidden": True})

class ExtractArticlenavigation(_URLInput):
    """Request articleNavigation from a page using the published extract endpoint."""
    operation: Literal["extract_articleNavigation"] = Field("extract_articleNavigation", json_schema_extra={"ui:hidden": True})

class ExtractForumthread(_URLInput):
    """Request forumThread from a page using the published extract endpoint."""
    operation: Literal["extract_forumThread"] = Field("extract_forumThread", json_schema_extra={"ui:hidden": True})

class ExtractJobposting(_URLInput):
    """Request jobPosting from a page using the published extract endpoint."""
    operation: Literal["extract_jobPosting"] = Field("extract_jobPosting", json_schema_extra={"ui:hidden": True})

class ExtractJobpostingnavigation(_URLInput):
    """Request jobPostingNavigation from a page using the published extract endpoint."""
    operation: Literal["extract_jobPostingNavigation"] = Field("extract_jobPostingNavigation", json_schema_extra={"ui:hidden": True})

class ExtractPagecontent(_URLInput):
    """Request pageContent from a page using the published extract endpoint."""
    operation: Literal["extract_pageContent"] = Field("extract_pageContent", json_schema_extra={"ui:hidden": True})

class ExtractProduct(_URLInput):
    """Request product from a page using the published extract endpoint."""
    operation: Literal["extract_product"] = Field("extract_product", json_schema_extra={"ui:hidden": True})

class ExtractProductlist(_URLInput):
    """Request productList from a page using the published extract endpoint."""
    operation: Literal["extract_productList"] = Field("extract_productList", json_schema_extra={"ui:hidden": True})

class ExtractProductnavigation(_URLInput):
    """Request productNavigation from a page using the published extract endpoint."""
    operation: Literal["extract_productNavigation"] = Field("extract_productNavigation", json_schema_extra={"ui:hidden": True})

class ExtractSerp(_URLInput):
    """Request serp from a page using the published extract endpoint."""
    operation: Literal["extract_serp"] = Field("extract_serp", json_schema_extra={"ui:hidden": True})

class SubmitHttpPost(_URLInput):
    """Submit text to a target website with POST and return its HTTP body. This can change the target website."""
    operation: Literal["submit_http_post"] = Field("submit_http_post", json_schema_extra={"ui:hidden": True, "x-method-kind": "write"})
    http_request_text: str = Field(..., title="Request Text", description="UTF-8 text sent to the target website as the POST body.")
    content_type: str = Field("application/json", title="Content Type", description="Content-Type header sent to the target website.")

ZyteConfig = Annotated[Union[CheckConnection, GetHttpBody, GetHttpHeaders, GetBrowserHtml, GetScreenshot, GetMarkdown, ExtractArticle, ExtractArticlelist, ExtractArticlenavigation, ExtractForumthread, ExtractJobposting, ExtractJobpostingnavigation, ExtractPagecontent, ExtractProduct, ExtractProductlist, ExtractProductnavigation, ExtractSerp, SubmitHttpPost], Field(discriminator="operation")]

class ZyteFullConfig(NodeConfig[ZyteConfig, ZyteApiKeyCredential]):
    pass

MODES = {'get_http_body': 'httpResponseBody', 'get_http_headers': 'httpResponseHeaders', 'get_browser_html': 'browserHtml', 'get_screenshot': 'screenshot', 'get_markdown': 'markdown', 'extract_article': 'article', 'extract_articleList': 'articleList', 'extract_articleNavigation': 'articleNavigation', 'extract_forumThread': 'forumThread', 'extract_jobPosting': 'jobPosting', 'extract_jobPostingNavigation': 'jobPostingNavigation', 'extract_pageContent': 'pageContent', 'extract_product': 'product', 'extract_productList': 'productList', 'extract_productNavigation': 'productNavigation', 'extract_serp': 'serp'}

class ZyteApiNode(WorkflowNode):
    integration_type = "automation-zyte-api"
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="Zyte API access", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return ZyteFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Zyte API key")
        if config.operation == "check_connection":
            body = {"url": "https://example.com", "httpResponseBody": True}
        elif config.operation == "submit_http_post":
            body = {"url": config.url, "httpResponseBody": True, "httpRequestMethod": "POST",
                    "httpRequestText": config.http_request_text,
                    "customHttpRequestHeaders": [{"name": "Content-Type", "value": config.content_type}]}
        else:
            body = {"url": config.url, MODES[config.operation]: True}
        auth = base64.b64encode((credential.api_key + ":").encode()).decode()
        async with guarded_async_client(timeout=190, trust_env=False, follow_redirects=False) as client:
            response = await client.request("POST", "https://api.zyte.com/v1/extract",
                headers={"Authorization": "Basic " + auth, "Accept": "application/json"}, json=body)
        if response.status_code != 200:
            detail = "Zyte API request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("detail"), str):
                    detail = error["detail"].replace(credential.api_key, "[redacted]").replace(auth, "[redacted]")
            except ValueError:
                pass
            raise ValueError(f"Zyte API HTTP {response.status_code}: {detail}")
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("url"), str):
            raise ValueError("Zyte API returned an invalid extraction response")
        return {"status": "success", "data": payload}
