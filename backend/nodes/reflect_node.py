"""Reflect's complete public API, pinned to OpenAPI 0.1.0.

Notes are end-to-end encrypted: the public API creates notes and appends daily
notes, but cannot read note content. Personal access tokens are generated at
https://reflect.app/developer/oauth as documented in the contract introduction.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.reflect import REFLECT_SCOPES
from utils.ssrf import guarded_async_client


class ReflectAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Reflect Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://reflect.app/developer/oauth",
        "x-help-url": "https://reflect.app/openapi.json",
        "x-credential-instructions": "Create credentials at Reflect's developer OAuth page and generate an access token there. Select read:graph and write:graph to use all operations. Paste the token alone. NoClick sends it as a Bearer token to reflect.app only.",
    })
    credential_type: Literal["reflect_access_token"] = Field("reflect_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, repr=False, title="Access Token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Reflect access token")
        value = clean_secret(value, field_name="Access token")
        if any(ord(c) <= 32 or ord(c) >= 127 for c in value):
            raise ValueError("Paste the token alone without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ReflectListGraphsConfig(_Input):
    """List all graphs available to the connected account (read:graph)."""
    operation: Literal["list_graphs"] = Field("list_graphs", json_schema_extra={"ui:hidden": True})


class ReflectGetCurrentUserConfig(_Input):
    """Get the connected user's identity (read:graph and write:graph)."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class _Graph(_Input):
    graph_id: str = Field(..., min_length=1, description="Graph ID from List Graphs.")

    @field_validator("graph_id")
    @classmethod
    def graph(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
            raise ValueError("Use a single Reflect graph ID")
        return value


class ReflectListBooksConfig(_Graph):
    """List books and their notes/highlights (read:graph and write:graph)."""
    operation: Literal["list_books"] = Field("list_books", json_schema_extra={"ui:hidden": True})


class ReflectListLinksConfig(_Graph):
    """List bookmarked links and highlights (read:graph)."""
    operation: Literal["list_links"] = Field("list_links", json_schema_extra={"ui:hidden": True})


class ReflectCreateLinkConfig(_Graph):
    """Create a bookmarked link (read:graph and write:graph)."""
    operation: Literal["create_link"] = Field("create_link", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description="URL to bookmark; sent as data, never fetched by NoClick.")
    title: str | None = None
    description: str | None = None
    highlights: list[str] | None = None
    id: str | None = Field(None, description="Optional link identifier, as supported by the Link request schema.")
    updated_at: str | None = Field(None, description="Optional ISO 8601 date-time.", json_schema_extra={"format": "date-time"})


class ReflectAppendDailyNoteConfig(_Graph):
    """Append text to a daily note's list (write:graph); this never replaces content."""
    operation: Literal["append_daily_note"] = Field("append_daily_note", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., description="Text to append to the daily note.")
    transform_type: Literal["list-append"] = Field("list-append", description="Reflect currently supports only list-append.")
    date: str | None = Field(None, description="Daily note date in YYYY-MM-DD format; omit for today.", json_schema_extra={"format": "date"})
    list_name: str | None = Field(None, description="List name; use [[List Name]] to backlink.")

    @field_validator("date")
    @classmethod
    def note_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


class ReflectCreateNoteConfig(_Graph):
    """Create a note from Markdown (write:graph); encrypted contents cannot be read back."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    subject: str
    content_markdown: str
    pinned: bool = False


ReflectOperation = Annotated[Union[ReflectListGraphsConfig, ReflectGetCurrentUserConfig,
    ReflectListBooksConfig, ReflectListLinksConfig, ReflectCreateLinkConfig,
    ReflectAppendDailyNoteConfig, ReflectCreateNoteConfig], Field(discriminator="operation")]


class ReflectNodeConfig(NodeConfig[ReflectOperation, ReflectAccessTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "list_graphs": ("GET", "/graphs"),
    "get_current_user": ("GET", "/users/me"),
    "list_books": ("GET", "/graphs/{graph_id}/books"),
    "list_links": ("GET", "/graphs/{graph_id}/links"),
    "create_link": ("POST", "/graphs/{graph_id}/links"),
    "append_daily_note": ("PUT", "/graphs/{graph_id}/daily-notes"),
    "create_note": ("POST", "/graphs/{graph_id}/notes"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class ReflectNode(WorkflowNode):
    integration_type = "automation-reflect"
    scope_registry = REFLECT_SCOPES
    connection_evidence = ConnectionEvidence(noun="graphs", operation="list_graphs")
    edit_examples = ["Save this article to Reflect", "Append today's meeting summary", "Create a Reflect note"]

    @classmethod
    def get_config_model(cls):
        return ReflectNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Reflect access token")
        op = self.config.config
        token = self.config.credentials.access_token
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        values.pop("operation")
        if "{graph_id}" in path:
            path = path.replace("{graph_id}", quote(values.pop("graph_id"), safe=""))
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://reflect.app/api" + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": values} if method != "GET" else {}))
        except httpx.HTTPError:
            raise ValueError("Reflect request did not complete; inspect before retrying a write") from None
        if response.status_code != 200:
            raise ValueError(_redact(f"Reflect HTTP {response.status_code}: {response.text[:2000]}", token))
        try:
            result = response.json()
        except ValueError:
            raise ValueError("Reflect returned invalid JSON") from None
        listing = op.operation in {"list_graphs", "list_books", "list_links"}
        if not isinstance(result, list if listing else dict):
            raise ValueError("Reflect returned an unexpected response shape")
        if not listing and (result.get("error") or result.get("errors")):
            raise ValueError(_redact("Reflect rejected the request: " + str(result), token))
        if op.operation == "append_daily_note" and result.get("success") is not True:
            raise ValueError("Reflect did not confirm the append; inspect before retrying")
        output = _redact({"status": "success", "data": result}, token)
        await self.emit(output)
        return output
