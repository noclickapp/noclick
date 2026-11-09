"""RiteKit API v1.0.0: hashtag research, post enrichment and link/image creation.

Official contract: https://raw.githubusercontent.com/RiteKit/api-docs/master/apiary.apib
Client IDs are private credentials and are sent only to the fixed API origin.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class RitekitClientIdCredential(BaseModel):
    model_config = ConfigDict(title="RiteKit Client ID", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://ritekit.com/developer/dashboard/",
        "x-credential-instructions": "Create a token in the RiteKit developer dashboard, then paste its Client ID. RiteKit supports using this private value directly without OAuth. Keep it secret; NoClick sends it as the client_id query parameter to api.ritekit.com.",
    })
    credential_type: Literal["ritekit_client_id"] = Field("ritekit_client_id", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, max_length=4096, title="Client ID", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("client_id", mode="before")
    @classmethod
    def private_client_id(cls, value):
        value = clean_secret(value, field_name="Client ID")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the Client ID without a prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class AutoEmojify(_Input):
    """Auto-Emojify."""
    operation: Literal["auto_emojify"] = Field("auto_emojify", title="Auto-Emojify", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., description='Text of the post', min_length=1, max_length=10000)


class SuggestEmojis(_Input):
    """Emoji Suggestions."""
    operation: Literal["suggest_emojis"] = Field("suggest_emojis", title="Emoji Suggestions", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., description='Text of the post', min_length=1, max_length=10000)


class CreateQuoteImage(_Input):
    """Text to Image."""
    operation: Literal["create_quote_image"] = Field("create_quote_image", title="Text to Image", json_schema_extra={"ui:hidden": True})
    quote: str = Field(..., description='Text of the quote', min_length=1, max_length=10000)
    author: str = Field(..., description='Name of the author/source', min_length=1, max_length=10000)
    fontSize: int = Field(..., description='Font size for the quote (author font size is calculated automatically)')
    quoteFont: str = Field(..., description='Font-family used for quote text', min_length=1, max_length=10000)
    quoteFontColor: str = Field(..., description='Font color of the quote text', min_length=1, max_length=10000)
    authorFont: str = Field(..., description='Font-family used for author name', min_length=1, max_length=10000)
    authorFontColor: str = Field(..., description='Font color of the author', min_length=1, max_length=10000)
    enableHighlight: int = Field(..., description='Enable highlight on quote text')
    highlightColor: str = Field(..., description='Color used for highlight', min_length=1, max_length=10000)
    bgType: str = Field(..., description='Background type (gradient/solid)', min_length=1, max_length=10000)
    backgroundColor: str = Field(..., description='Background color for solid background type', min_length=1, max_length=10000)
    gradientType: str = Field(..., description='Type of gradient background (linear/radial)', min_length=1, max_length=10000)
    gradientColor1: str = Field(..., description='First color for gradient background type', min_length=1, max_length=10000)
    gradientColor2: str = Field(..., description='Second color for gradient background type', min_length=1, max_length=10000)
    brandLogo: str = Field(..., description='URL of the brand logo', min_length=1, max_length=10000)
    animation: str = Field(..., description='Animation type: none, rays, glint, circle', min_length=1, max_length=10000)
    showQuoteMark: int | None = Field(None, description='showing/hiding quote mark')


class ListCtas(_Input):
    """List of CTAs."""
    operation: Literal["list_ctas"] = Field("list_ctas", title="List of CTAs", json_schema_extra={"ui:hidden": True})


class ShortenLink(_Input):
    """Shorten Link."""
    operation: Literal["shorten_link"] = Field("shorten_link", title="Shorten Link", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='URL', min_length=1, max_length=10000)
    cta: int = Field(..., description='cta id')


class GetTrendingHashtags(_Input):
    """Trending Hashtags."""
    operation: Literal["get_trending_hashtags"] = Field("get_trending_hashtags", title="Trending Hashtags", json_schema_extra={"ui:hidden": True})
    green: bool | None = Field(None, description='Restrict results only to green hashtags. Hides overused (red) hashtags.')
    latin: bool | None = Field(None, description='Restrict results only to hashtags with latin characters')


class AutoHashtag(_Input):
    """Auto-Hashtag."""
    operation: Literal["auto_hashtag"] = Field("auto_hashtag", title="Auto-Hashtag", json_schema_extra={"ui:hidden": True})
    post: str = Field(..., description='Text of the post', min_length=1, max_length=10000)
    maxHashtags: int | None = Field(None, description='Max number of hashtags.')
    hashtagPosition: str | None = Field(None, description='Position of hashtags: end => at the end, auto => anywhere', min_length=1, max_length=10000)


class SuggestHashtags(_Input):
    """Hashtag Suggestions."""
    operation: Literal["suggest_hashtags"] = Field("suggest_hashtags", title="Hashtag Suggestions", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., description='Topic', min_length=1, max_length=10000)


class GetHashtagHistory(_Input):
    """Hashtag History."""
    operation: Literal["get_hashtag_history"] = Field("get_hashtag_history", title="Hashtag History", json_schema_extra={"ui:hidden": True})
    hashtag: str = Field(..., description='Hashtag without # mark', min_length=1, max_length=10000)


class GetHashtagStats(_Input):
    """Hashtag Stats."""
    operation: Literal["get_hashtag_stats"] = Field("get_hashtag_stats", title="Hashtag Stats", json_schema_extra={"ui:hidden": True})
    tags: list[str] = Field(..., description='Hashtag(s) without # mark', min_length=1, max_length=100)


class CleanInstagramHashtags(_Input):
    """Hashtags cleaner."""
    operation: Literal["clean_instagram_hashtags"] = Field("clean_instagram_hashtags", title="Hashtags cleaner", json_schema_extra={"ui:hidden": True})
    post: str = Field(..., description='post', min_length=1, max_length=10000)

Operation = Annotated[Union[AutoEmojify, SuggestEmojis, CreateQuoteImage, ListCtas, ShortenLink, GetTrendingHashtags, AutoHashtag, SuggestHashtags, GetHashtagHistory, GetHashtagStats, CleanInstagramHashtags], Field(discriminator="operation")]


ROUTES = {'auto_emojify': '/v1/emoji/auto-emojify', 'suggest_emojis': '/v1/emoji/suggestions', 'create_quote_image': '/v1/images/quote', 'list_ctas': '/v1/link/cta', 'shorten_link': '/v1/link/short-link', 'get_trending_hashtags': '/v1/search/trending', 'auto_hashtag': '/v1/stats/auto-hashtag', 'suggest_hashtags': '/v1/stats/hashtag-suggestions', 'get_hashtag_history': '/v1/stats/history/{hashtag}', 'get_hashtag_stats': '/v1/stats/multiple-hashtags', 'clean_instagram_hashtags': '/v2/instagram/hashtags-cleaner'}


class RitekitNodeConfig(NodeConfig[Operation, RitekitClientIdCredential]):
    pass


class RitekitNode(WorkflowNode):
    integration_type = "automation-ritekit"
    connection_evidence = ConnectionEvidence(noun="RiteKit calls to action", operation="list_ctas")

    @classmethod
    def get_config_model(cls):
        return RitekitNodeConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a RiteKit Client ID")
        config = self.config.config
        path = ROUTES[config.operation]
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        if "{hashtag}" in path:
            hashtag = params.pop("hashtag")
            path = path.replace("{hashtag}", quote(hashtag, safe=""))
        if "tags" in params:
            params["tags"] = ",".join(params["tags"])
        params["client_id"] = credential.client_id
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request("GET", "https://api.ritekit.com" + path,
                    params=params, headers={"Accept": "application/json"})
        except (httpx.HTTPError, OSError):
            raise ValueError("RiteKit request did not complete") from None
        if response.status_code != 200:
            # Query authentication must never appear in an HTTP exception URL.
            raise ValueError(f"RiteKit rejected the request (HTTP {response.status_code})")
        if len(response.content) > 5_000_000:
            raise ValueError("RiteKit response exceeds the supported size")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("RiteKit returned an invalid JSON response") from None
        if not isinstance(data, dict) or data.get("result") is not True:
            message = data.get("message") if isinstance(data, dict) else None
            if isinstance(message, str) and message:
                raise ValueError(message.replace(credential.client_id, "[redacted]"))
            raise ValueError("RiteKit did not confirm the request")
        if config.operation == "list_ctas" and not isinstance(data.get("list"), list):
            raise ValueError("RiteKit did not return a CTA list")
        return {"status": "success", "data": data}
