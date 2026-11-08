"""GIPHY v1 GIF and sticker discovery using a manually supplied API key.

The pinned 1.0 contract contains ten GET endpoints and no upload endpoint.
Public catalogue reads establish key reachability, never account ownership.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class GiphyApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="GIPHY API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.giphy.com/dashboard/",
            "x-credential-instructions": "Create an API app in the GIPHY developer dashboard and paste its API key. NoClick checks access to public trending GIFs; this verifies reachability, not your identity or account ownership.",
        })
    credential_type: Literal["giphy_api_key"] = Field("giphy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Operation):
    limit: int = Field(25, ge=1, le=50, description="Maximum results in this page. No automatic pagination.")
    offset: int = Field(0, ge=0, le=499, description="Result offset for this page.")
    rating: Literal["g", "pg", "pg-13", "r"] | None = None


class _Search(_Page):
    offset: int = Field(0, ge=0, le=4999, description="Search result offset for this page.")
    q: str = Field(..., min_length=1, max_length=50, title="Search query")
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$", description="Two-letter ISO 639-1 language code.")


class SearchGifs(_Search):
    """Search the public GIF catalogue."""
    operation: Literal["search_gifs"] = "search_gifs"


class TrendingGifs(_Page):
    """Read one page of trending GIFs."""
    operation: Literal["get_trending_gifs"] = "get_trending_gifs"


class _Translate(_Operation):
    s: str = Field(..., min_length=1, max_length=50, title="Phrase to translate")


class TranslateGif(_Translate):
    """Translate a phrase into one GIF."""
    operation: Literal["translate_gif"] = "translate_gif"


class _Random(_Operation):
    tag: str | None = Field(None, min_length=1, max_length=50)
    rating: Literal["g", "pg", "pg-13", "r"] | None = None


class RandomGif(_Random):
    """Get a random GIF, optionally filtered by tag and rating."""
    operation: Literal["random_gif"] = "random_gif"


class GetGif(_Operation):
    """Get a GIF by its GIPHY ID (IDs are strings in current provider docs)."""
    operation: Literal["get_gif"] = "get_gif"
    gif_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9]+$", title="GIF ID")


class GetGifs(_Operation):
    """Get several GIFs by comma-separated GIPHY IDs."""
    operation: Literal["get_gifs"] = "get_gifs"
    ids: str = Field(..., min_length=1, max_length=12900, pattern=r"^[A-Za-z0-9]+(?:,[A-Za-z0-9]+)*$", title="GIF IDs")

    @field_validator("ids")
    @classmethod
    def bounded_ids(cls, value):
        if len(value.split(",")) > 100 or any(len(part) > 128 for part in value.split(",")):
            raise ValueError("Supply at most 100 GIF IDs, each no longer than 128 characters")
        return value


class SearchStickers(_Search):
    """Search the public sticker catalogue."""
    operation: Literal["search_stickers"] = "search_stickers"


class TrendingStickers(_Page):
    """Read one page of trending stickers."""
    operation: Literal["get_trending_stickers"] = "get_trending_stickers"


class TranslateSticker(_Translate):
    """Translate a phrase into one sticker."""
    operation: Literal["translate_sticker"] = "translate_sticker"


class RandomSticker(_Random):
    """Get a random sticker, optionally filtered by tag and rating."""
    operation: Literal["random_sticker"] = "random_sticker"


GiphyOperation = Annotated[Union[SearchGifs, TrendingGifs, TranslateGif, RandomGif, GetGif,
    GetGifs, SearchStickers, TrendingStickers, TranslateSticker, RandomSticker], Field(discriminator="operation")]


class GiphyNodeConfig(NodeConfig[GiphyOperation, GiphyApiKeyCredential]):
    pass


ROUTES = {
    "search_gifs": "/gifs/search", "get_trending_gifs": "/gifs/trending",
    "translate_gif": "/gifs/translate", "random_gif": "/gifs/random",
    "get_gif": "/gifs/{gifId}", "get_gifs": "/gifs",
    "search_stickers": "/stickers/search", "get_trending_stickers": "/stickers/trending",
    "translate_sticker": "/stickers/translate", "random_sticker": "/stickers/random",
}
_LISTS = {"search_gifs", "get_trending_gifs", "get_gifs", "search_stickers", "get_trending_stickers"}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items() if k != "api_key"}
    return value


class GiphyNode(WorkflowNode):
    integration_type = "automation-giphy"
    connection_evidence = ConnectionEvidence(operation="get_trending_gifs", noun="public trending GIFs", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return GiphyNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a GIPHY API key")
        op = self.config.config
        key = self.config.credentials.api_key
        params = op.model_dump(exclude={"operation", "gif_id"}, exclude_none=True)
        params["api_key"] = key
        route = ROUTES[op.operation]
        if isinstance(op, GetGif):
            route = route.replace("{gifId}", quote(op.gif_id, safe=""))
        try:
            # A fixed provider origin and no redirects keep the query-string key
            # on api.giphy.com. Never include request URLs in errors or output.
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.get("https://api.giphy.com/v1" + route, params=params, headers={"Accept": "application/json"})
            try:
                body = response.json()
            except ValueError:
                body = None
            meta = body.get("meta") if isinstance(body, dict) else None
            provider_status = meta.get("status") if isinstance(meta, dict) else None
            if response.status_code != 200 or (provider_status is not None and provider_status != 200):
                message = meta.get("msg") if isinstance(meta, dict) else None
                return {"status": "error", "http_status": response.status_code,
                    "error": _redact(message, key) if isinstance(message, str) else "GIPHY did not confirm this read"}
            data = body.get("data") if isinstance(body, dict) else None
            expected = list if op.operation in _LISTS else dict
            if not isinstance(data, expected):
                raise ValueError("GIPHY returned an unexpected data envelope")
            output = {"status": "success", "operation": op.operation, "data": data,
                "identity_verified": False}
            for name in ("pagination", "meta"):
                if isinstance(body.get(name), dict):
                    output[name] = body[name]
            return _redact(output, key)
        except httpx.HTTPError:
            raise ValueError("The GIPHY request could not be completed") from None
