"""GIPHY v1 GIF and sticker discovery using a manually supplied API key.

Ten catalogue reads and two recent-search poll triggers use only GET endpoints.
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
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


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


class _NewSearch(PollTriggerConfigBase):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-requires-webhook": True})
    q: str = Field(..., min_length=1, max_length=50, title="Search query",
        description="Watch this search, or use @username to watch a public verified channel.")
    lang: str | None = Field(None, pattern=r"^[a-z]{2}$", description="Two-letter ISO 639-1 language code.")
    rating: Literal["g", "pg", "pg-13", "r"] | None = None
    limit: int = Field(50, ge=1, le=50, title="Recent results per poll",
        description="Check this many most recent matches. Existing matches are baselined when armed. Matches that leave this window between polls can be missed; narrow the query or shorten the schedule.")


class OnNewGif(_NewSearch):
    """Watch recent GIF search results for new matches."""
    operation: Literal["on_new_gif"] = Field("on_new_gif", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New GIF",
    })


class OnNewSticker(_NewSearch):
    """Watch recent sticker search results for new matches."""
    operation: Literal["on_new_sticker"] = Field("on_new_sticker", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Sticker",
    })


GiphyOperation = Annotated[Union[SearchGifs, TrendingGifs, TranslateGif, RandomGif, GetGif,
    GetGifs, SearchStickers, TrendingStickers, TranslateSticker, RandomSticker,
    OnNewGif, OnNewSticker], Field(discriminator="operation")]


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


class GiphyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-giphy"
    connection_evidence = ConnectionEvidence(operation="get_trending_gifs", noun="public trending GIFs", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return GiphyNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_gif", "on_new_sticker"}:
            return output.get("status") == "success" and bool(output.get("new_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") not in {"on_new_gif", "on_new_sticker"}:
            return super().resolve_agent_event(output)
        items = output.get("data")
        if not isinstance(items, list) or not items:
            return None
        noun = "GIF" if output["operation"] == "on_new_gif" else "sticker"
        lines = [f"GIPHY: {len(items)} new {noun} match(es) for {str(output.get('query', ''))[:50]!r}."]
        for item in items[:10]:
            who = f" by @{str(item['username'])[:100]}" if item.get("username") else ""
            lines.append(f"- {str(item.get('title') or noun)[:200]}{who} (id {item['id']})")
            if item.get("url"):
                lines.append(f"  {str(item['url'])[:500]}")
        if len(items) > 10:
            lines.append(f"- and {len(items) - 10} more matches")
        return {"text": "\n".join(lines), "conversation_key": None, "title": f"New GIPHY {noun} matches"}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a GIPHY API key")
        op = self.config.config
        key = self.config.credentials.api_key
        polling = isinstance(op, _NewSearch)
        if polling:
            # GIPHY's official JS SDK SearchOptions documents sort=recent:
            # https://github.com/Giphy/giphy-js/blob/ea20a90638b4ff01255582dcf8aab5dcf209f750/packages/fetch-api/src/option-types.ts
            params = {name: getattr(op, name) for name in ("q", "lang", "rating", "limit")
                      if getattr(op, name) is not None}
            params.update(sort="recent", offset=0)
            route = "/gifs/search" if isinstance(op, OnNewGif) else "/stickers/search"
        else:
            params = op.model_dump(exclude={"operation", "gif_id"}, exclude_none=True)
            route = ROUTES[op.operation]
        params["api_key"] = key
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
            expected = list if polling or op.operation in _LISTS else dict
            if not isinstance(data, expected):
                raise ValueError("GIPHY returned an unexpected data envelope")
            output = {"status": "success", "operation": op.operation, "data": data,
                "identity_verified": False}
            for name in ("pagination", "meta"):
                if isinstance(body.get(name), dict):
                    output[name] = body[name]
            output = _redact(output, key)
            if polling:
                items = output["data"]
                if any(not isinstance(item, dict) or isinstance(item.get("id"), bool)
                       or not isinstance(item.get("id"), (str, int)) or not str(item["id"])
                       for item in items):
                    raise ValueError("GIPHY returned a search result without a valid ID")
                # The shared poll family owns baseline, scope and persistent dedup.
                output["data"] = await self._filter_unseen(items, lambda item: str(item["id"]))
                output.update(new_count=len(output["data"]), query=op.q)
            return output
        except httpx.HTTPError:
            raise ValueError("The GIPHY request could not be completed") from None
