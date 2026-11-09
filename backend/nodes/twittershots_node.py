"""TwitterShots v0.9.1 screenshot and authenticated quota operations.

Contract: https://twittershots.com/openapi.yaml. These are the two operations
published in the pinned contract; no additional rendering parameters or APIs
are inferred from other versions of the service.
"""
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class TwittershotsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Twittershots API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://twittershots.com/settings/keys",
            "x-credential-instructions": "Paste your TwitterShots API key from Account Settings. NoClick sends it in the X-API-KEY header to api.twittershots.com. Connecting reads your remaining quota; it does not generate a screenshot or identify your Twitter/X account.",
        },
    )
    credential_type: Literal["twittershots_api_key"] = Field(
        "twittershots_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key",
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetTweetScreenshot(_Input):
    """Generate a public tweet screenshot as a file or temporary hosted URL."""
    operation: Literal["get_tweet_screenshot"] = Field(
        "get_tweet_screenshot", json_schema_extra={"ui:hidden": True})
    tweet_id: str = Field(...,
                          pattern=r"^(?:[0-9]{1,32}|https://(?:www\.)?(?:x|twitter)\.com/(?:[A-Za-z0-9_]+|i/web)/status/[0-9]{1,32}/?(?:\?[^#\s]*)?(?:#[^\s]*)?)$",
                          max_length=2048, title="Tweet ID or URL",
                          description="Paste the numeric status ID or an HTTPS Twitter/X status URL.",
                          examples=["1981415642981888505"])
    format: Literal["svg", "png", "html"] = Field("svg", title="Output format")
    theme: Literal["light", "dark"] = Field("light", title="Theme")
    return_type: Literal["buffer", "url"] = Field(
        "buffer", title="Return type",
        description="buffer returns a file. url returns a temporary hosted URL that may be removed by TwitterShots; save the file for permanent storage.")

    @field_validator("tweet_id", mode="before")
    @classmethod
    def status_id(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste a numeric tweet ID or Twitter/X status URL")
        value = value.strip()
        if value.startswith("https://"):
            url = urlsplit(value)
            match = re.fullmatch(r"/(?:[A-Za-z0-9_]+|i/web)/status/([0-9]{1,32})/?", url.path)
            if (url.netloc not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
                    or not match):
                raise ValueError("Use a Twitter/X status URL")
            value = match[1]
        return value


class GetAPIUsage(_Input):
    """Read the remaining requests and total quota for the supplied API key."""
    operation: Literal["get_api_usage"] = Field(
        "get_api_usage", json_schema_extra={"ui:hidden": True})


TwittershotsOperation = Annotated[Union[GetTweetScreenshot, GetAPIUsage], Field(discriminator="operation")]


class TwittershotsNodeConfig(NodeConfig[TwittershotsOperation, TwittershotsAPIKeyCredential]):
    pass


class TwittershotsNode(WorkflowNode):
    integration_type = "automation-twittershots"
    # Quota is specific to the key but does not establish a named identity.
    connection_evidence = ConnectionEvidence(
        noun="TwitterShots API quota", operation="get_api_usage", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return TwittershotsNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a TwitterShots API key")
        config = self.config.config
        key = self.config.credentials.api_key
        screenshot = isinstance(config, GetTweetScreenshot)
        path = "/api/v1/screenshot/" + config.tweet_id if screenshot else "/api/v1/usage"
        params = {"format": config.format, "theme": config.theme, "returnType": config.return_type} if screenshot else {}
        accept = "application/json" if not screenshot or config.return_type == "url" else "image/svg+xml,image/png,text/html"
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(
                    "GET", "https://api.twittershots.com" + path,
                    headers={"X-API-KEY": key, "Accept": accept}, params=params)
        except httpx.HTTPError:
            raise ValueError("TwitterShots request could not be confirmed") from None

        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if response.status_code != 200:
            # Preserve provider rejection text for connect, with the secret removed.
            message = f"TwitterShots returned HTTP {response.status_code}"
            if mime == "application/json":
                try:
                    body = response.json()
                    detail = body.get("message") or body.get("error") if isinstance(body, dict) else None
                    if isinstance(detail, str):
                        message = detail.replace(key, "[redacted]")[:2000]
                except ValueError:
                    pass
            elif mime == "text/plain":
                message = response.text.replace(key, "[redacted]")[:2000] or message
            output = {"status": "error", "http_status": response.status_code, "message": message}
        elif screenshot and config.return_type == "buffer":
            extensions = {"image/png": "png", "image/svg+xml": "svg", "text/html": "html"}
            if mime not in extensions or not response.content:
                raise ValueError("TwitterShots did not return a screenshot file")
            output = {"status": "success", "file": BinaryOutput(
                response.content, mime, f"tweet-{config.tweet_id}.{extensions[mime]}")}
        else:
            if mime != "application/json":
                raise ValueError("TwitterShots did not return JSON")
            try:
                body = response.json()
            except ValueError:
                raise ValueError("TwitterShots returned invalid JSON") from None
            if not isinstance(body, dict) or "error" in body:
                raise ValueError("TwitterShots did not confirm the requested result")
            if screenshot:
                url = body.get("url")
                if not isinstance(url, str) or urlsplit(url).scheme != "https" or not urlsplit(url).netloc:
                    raise ValueError("TwitterShots omitted a hosted screenshot URL")
                data = {name: body[name] for name in ("url", "format", "tweetId") if name in body}
            else:
                if any(type(body.get(name)) is not int for name in ("remaining", "limit")):
                    raise ValueError("TwitterShots omitted the API quota")
                data = {name: body[name] for name in ("remaining", "limit")}
            output = {"status": "success", "data": data}
        for header, field in (("X-Quota-Remaining", "quota_remaining"), ("X-Quota-Limit", "quota_limit")):
            value = response.headers.get(header, "")
            if re.fullmatch(r"[0-9]{1,12}", value):
                output[field] = int(value)
        await self.emit(output)
        return output
