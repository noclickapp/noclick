"""Instapaper v2 bookmark operations, using a personal bearer token.

Published contract: https://www.instapaper.com/api/2/openapi.json (version 2).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://www.instapaper.com/api/2"


class InstapaperTokenCredential(BaseModel):
    model_config = ConfigDict(title="Instapaper Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.instapaper.com/developers/applications",
            "x-credential-instructions": "Generate a personal access token on Instapaper's Applications page and paste it here. Use your own account's token. Article content access by non-personal applications also requires an Instaparser API key; leave that field empty for personal use.",
        })
    credential_type: Literal["instapaper_access_token"] = Field("instapaper_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})
    instaparser_api_key: str | None = Field(None, title="Instaparser API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", "instaparser_api_key", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BookmarkInput(Input):
    bookmark_id: int = Field(..., gt=0, description="Instapaper bookmark ID.")


class ListBookmarks(Input):
    """Read one page of account bookmarks, optionally changed since a timestamp."""
    operation: Literal["list_bookmarks"] = "list_bookmarks"
    section: Literal["home", "archive", "liked", "folder", "tag"] = "home"
    folder_id: int | None = None
    tag: str | None = None
    limit: int = Field(25, ge=1, le=500)
    offset: int = Field(0, ge=0)
    since: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def filters(self):
        if self.folder_id is not None and self.tag is not None:
            raise ValueError("Cannot specify both folder_id and tag")
        if self.since is None:
            if self.section == "folder" and self.folder_id is None:
                raise ValueError("folder_id is required for section folder")
            if self.section == "tag" and not self.tag:
                raise ValueError("tag is required for section tag")
        return self


class TagName(Input):
    name: str = Field(..., min_length=1)


class CreateBookmark(Input):
    """Save a URL or supplied private article content."""
    operation: Literal["create_bookmark"] = "create_bookmark"
    url: str | None = None
    title: str | None = None
    description: str | None = None
    folder_id: int | None = None
    archived: bool = False
    canonicalize: bool = True
    tags: list[TagName] = Field(default_factory=list)
    content: str | None = None
    private_source: str | None = None

    @model_validator(mode="after")
    def source(self):
        if self.private_source:
            if not self.content:
                raise ValueError("Private bookmarks require content")
        elif not self.url:
            raise ValueError("Provide a URL or private_source and content")
        if self.url:
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Use an absolute HTTP or HTTPS article URL")
        return self


class Progress(Input):
    percentage: float = Field(..., ge=0, le=1, allow_inf_nan=False)
    timestamp: int = Field(..., ge=1)


class UpdateBookmark(BookmarkInput):
    """Update title, description or timestamped reading progress."""
    operation: Literal["update_bookmark"] = "update_bookmark"
    title: str | None = None
    description: str | None = None
    progress: Progress | None = None


class DeleteBookmark(BookmarkInput):
    """Permanently delete the selected bookmark."""
    operation: Literal["delete_bookmark"] = "delete_bookmark"


class MoveBookmark(BookmarkInput):
    """Move to home, archive, or a folder ID written as a string."""
    operation: Literal["move_bookmark"] = "move_bookmark"
    section: str = Field(..., pattern=r"^(archive|home|[0-9]+)$", description="archive, home, or a folder ID such as 12345.")


class LikeBookmark(BookmarkInput):
    """Like the selected bookmark."""
    operation: Literal["like_bookmark"] = "like_bookmark"


class UnlikeBookmark(BookmarkInput):
    """Remove the selected bookmark's like."""
    operation: Literal["unlike_bookmark"] = "unlike_bookmark"


class TagReference(Input):
    id: int | None = None
    name: str | None = None

    @model_validator(mode="after")
    def reference(self):
        if self.id is None and not self.name:
            raise ValueError("Provide a tag ID or name")
        return self


class TagId(Input):
    id: int


class UpdateBookmarkTags(BookmarkInput):
    """Add tags by ID or name and remove tags by ID."""
    operation: Literal["update_bookmark_tags"] = "update_bookmark_tags"
    add_tags: list[TagReference] = Field(default_factory=list)
    remove_tags: list[TagId] = Field(default_factory=list)

    @model_validator(mode="after")
    def tags(self):
        if not self.add_tags and not self.remove_tags:
            raise ValueError("Provide add_tags or remove_tags")
        return self


class GetBookmarkContent(BookmarkInput):
    """Retrieve parsed article HTML and metadata."""
    operation: Literal["get_bookmark_content"] = "get_bookmark_content"
    use_cache: Literal["0", "1"] | None = None
    force: Literal["1"] | None = None


class ParseBookmarkContent(BookmarkInput):
    """Parse a bookmark, optionally using supplied article HTML."""
    operation: Literal["parse_bookmark_content"] = "parse_bookmark_content"
    use_cache: bool = True
    force: bool = False
    content: str | None = None


InstapaperConfig = Annotated[Union[ListBookmarks, CreateBookmark, UpdateBookmark, DeleteBookmark,
    MoveBookmark, LikeBookmark, UnlikeBookmark, UpdateBookmarkTags, GetBookmarkContent,
    ParseBookmarkContent], Field(discriminator="operation")]


class InstapaperFullConfig(NodeConfig[InstapaperConfig, InstapaperTokenCredential]):
    pass


# Each operation maps to exactly one published v2 method and path.
ROUTES = {
    "list_bookmarks": ("GET", "/bookmarks"),
    "create_bookmark": ("POST", "/bookmarks"),
    "update_bookmark": ("POST", "/bookmarks/{bookmark_id}"),
    "delete_bookmark": ("DELETE", "/bookmarks/{bookmark_id}"),
    "move_bookmark": ("POST", "/bookmarks/{bookmark_id}/move"),
    "like_bookmark": ("POST", "/bookmarks/{bookmark_id}/like"),
    "unlike_bookmark": ("DELETE", "/bookmarks/{bookmark_id}/like"),
    "update_bookmark_tags": ("POST", "/bookmarks/{bookmark_id}/tags"),
    "get_bookmark_content": ("GET", "/bookmarks/{bookmark_id}/parse"),
    "parse_bookmark_content": ("POST", "/bookmarks/{bookmark_id}/parse"),
}


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.access_token, credential.instaparser_api_key):
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {key: _redact(item, credential) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    return value


class InstapaperNode(WorkflowNode):
    integration_type = "automation-instapaper"
    connection_evidence = ConnectionEvidence(operation="list_bookmarks", noun="bookmarks")

    @classmethod
    def get_config_model(cls):
        return InstapaperFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Instapaper access token")
        config, credential = self.config.config, self.config.credentials
        action = config.operation
        method, path = ROUTES[action]
        path = path.format(bookmark_id=getattr(config, "bookmark_id", None))
        payload = config.model_dump(exclude={"operation", "bookmark_id"}, exclude_none=True)
        if action == "list_bookmarks" and "since" not in payload:
            if config.folder_id is not None:
                payload["section"] = "folder"
            elif config.tag is not None:
                payload["section"] = "tag"
        if action in {"get_bookmark_content", "parse_bookmark_content"} and credential.instaparser_api_key:
            payload["instaparser_api_key"] = credential.instaparser_api_key
        kwargs = {"params": payload} if method == "GET" else {"json": payload} if action in {
            "create_bookmark", "update_bookmark", "move_bookmark", "update_bookmark_tags", "parse_bookmark_content"} else {}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = "Instapaper request failed"
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(str(message), credential)}
        if action == "delete_bookmark":
            return {"status": "success", "bookmark_id": config.bookmark_id, "deleted": True}
        if len(response.content) > 10_000_000:
            raise ValueError("Instapaper response exceeds the size limit")
        body = response.json()
        if not isinstance(body, dict) or "error" in body:
            raise ValueError("Instapaper returned an invalid response")
        if action == "list_bookmarks":
            if not isinstance(body.get("bookmarks"), list) or type(body.get("total")) is not int:
                raise ValueError("Instapaper bookmark page is incomplete")
            count = len(body["bookmarks"])
            if config.since is not None:
                if not isinstance(body.get("deleted_ids"), list):
                    raise ValueError("Instapaper sync page lacks deleted_ids")
                count += len(body["deleted_ids"])
            next_offset = config.offset + count
            has_more = count >= config.limit if config.since is not None else next_offset < body["total"] and count > 0
            body = {**body, "next_offset": next_offset if has_more else None}
        elif action in {"get_bookmark_content", "parse_bookmark_content"}:
            if not isinstance(body.get("metadata"), dict) or not isinstance(body.get("content"), dict):
                raise ValueError("Instapaper parsed article is incomplete")
        elif action == "update_bookmark_tags":
            if not isinstance(body.get("tags"), list) or not isinstance(body.get("created_tags"), list):
                raise ValueError("Instapaper tag response is incomplete")
        elif type(body.get("id")) is not int:
            raise ValueError("Instapaper bookmark response is incomplete")
        return _redact({"status": "success", **body}, credential)
