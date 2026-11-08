"""Slite public API v1. One documented request per operation, without retries.

Contract: https://api.slite.com/openapi.json (version 1).
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.slite.com/v1"


class SliteAPICredential(BaseModel):
    model_config = ConfigDict(title="Slite API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api.slite.com/",
        "x-credential-instructions": "In Slite, open Settings > API and create an API key. Paste the key here. Read operations require read permission; changes require write permission. NoClick checks your signed-in user with /me."})
    credential_type: Literal["slite_api_key"] = Field("slite_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, value, info):
        if info.field_name in {"noteId", "userId", "groupId", "parentNoteId", "templateId", "ownerId"} and value is not None:
            if not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#\r\n"):
                raise ValueError("Use a single Slite resource ID")
        return value


class GetMe(_Operation):
    """Read the authenticated user's name, email and organization."""
    operation: Literal["get_me"] = "get_me"


class ListNotes(_Operation):
    """List one cursor page of notes; pass nextCursor to continue."""
    operation: Literal["list_notes"] = "list_notes"
    ownerId: str | None = None
    parentNoteId: str | None = None
    orderBy: Literal["lastEditedAt_DESC", "lastEditedAt_ASC", "listPosition_DESC", "listPosition_ASC"] | None = None
    cursor: str | None = None


class GetNote(_Operation):
    """Read a note and its content in the selected format."""
    operation: Literal["get_note"] = "get_note"
    noteId: str = Field(..., min_length=1)
    format: Literal["md", "html", "sliteml"] = "md"
    css: Literal["inline", "none"] | None = None
    compact: bool | None = None


class CreateNote(_Operation):
    """Create a note, optionally under a parent or from a template."""
    operation: Literal["create_note"] = "create_note"
    title: str = Field(..., min_length=1)
    parentNoteId: str | None = None
    templateId: str | None = None
    markdown: str | None = None
    html: str | None = None
    sliteml: str | None = None
    attributes: list[str | None] | None = None
    listPosition: Union[Literal["top", "bottom"], float, None] = None

    @model_validator(mode="after")
    def content_format(self):
        if sum(getattr(self, f) is not None for f in ("markdown", "html", "sliteml")) > 1:
            raise ValueError("Choose one content format")
        if isinstance(self.listPosition, float) and (self.listPosition <= 0 or not math.isfinite(self.listPosition)):
            raise ValueError("Position must be positive and finite")
        return self


class UpdateNote(_Operation):
    """Replace supplied note fields; omitted fields remain unchanged."""
    operation: Literal["update_note"] = "update_note"
    noteId: str = Field(..., min_length=1)
    title: str | None = None
    markdown: str | None = None
    html: str | None = None
    sliteml: str | None = None
    attributes: list[str | None] | None = None
    listPosition: Union[Literal["top", "bottom"], float, None] = None

    @model_validator(mode="after")
    def change(self):
        CreateNote.content_format(self)
        if not any(getattr(self, key) is not None for key in ("title", "markdown", "html", "sliteml", "attributes", "listPosition")):
            raise ValueError("Supply a field to update")
        return self


class DeleteNote(_Operation):
    """Delete a note and all its children. This cannot be undone by NoClick."""
    operation: Literal["delete_note"] = "delete_note"
    noteId: str = Field(..., min_length=1)


class ListChildren(DeleteNote):
    """List a page of direct children or a flattened subtree."""
    operation: Literal["list_children"] = "list_children"
    cursor: str | None = None
    orderBy: Literal["title", "listPosition", "lastEditedAt"] | None = None
    orderDirection: Literal["asc", "desc"] | None = None
    includeDescendants: bool | None = None


class VerifyNote(DeleteNote):
    """Verify a note until an ISO date, or indefinitely with no expiration."""
    operation: Literal["verify_note"] = "verify_note"
    until: datetime | None = None


class FlagOutdated(DeleteNote):
    """Mark a note outdated and include the reason."""
    operation: Literal["flag_outdated"] = "flag_outdated"
    reason: str = Field(..., min_length=1)


class SetArchived(DeleteNote):
    """Archive or unarchive a note."""
    operation: Literal["set_archived"] = "set_archived"
    archived: bool


class SetOwner(DeleteNote):
    """Set a user or group as the note's review owner."""
    operation: Literal["set_owner"] = "set_owner"
    userId: str | None = None
    groupId: str | None = None

    @model_validator(mode="after")
    def one_owner(self):
        if (self.userId is None) == (self.groupId is None):
            raise ValueError("Choose exactly one user or group owner")
        return self


class SearchNotes(_Operation):
    """Search a numbered page of note results."""
    operation: Literal["search_notes"] = "search_notes"
    query: str = ""
    parentNoteId: str | None = None
    depth: int | None = Field(None, ge=0)
    reviewState: Literal["Verified", "Outdated", "VerificationRequested", "VerificationExpired"] | None = None
    page: int = Field(0, ge=0)
    hitsPerPage: int = Field(20, ge=1, le=100)
    includeArchived: bool | None = None
    lastEditedAfter: datetime | None = None
    lastUpdatedAfter: datetime | None = None


class GetUser(_Operation):
    """Read one user by ID."""
    operation: Literal["get_user"] = "get_user"
    userId: str = Field(..., min_length=1)


class SearchUsers(_Operation):
    """Search users by email or display name, one cursor page at a time."""
    operation: Literal["search_users"] = "search_users"
    query: str
    includeArchived: bool | None = None
    cursor: str | None = None


class GetGroup(_Operation):
    """Read one group by ID."""
    operation: Literal["get_group"] = "get_group"
    groupId: str = Field(..., min_length=1)


class SearchGroups(_Operation):
    """Search groups by name, one cursor page at a time."""
    operation: Literal["search_groups"] = "search_groups"
    query: str
    cursor: str | None = None


SliteOperation = Annotated[Union[GetMe, ListNotes, GetNote, CreateNote, UpdateNote, DeleteNote, ListChildren, VerifyNote, FlagOutdated, SetArchived, SetOwner, SearchNotes, GetUser, SearchUsers, GetGroup, SearchGroups], Field(discriminator="operation")]


class SliteConfig(NodeConfig[SliteOperation, SliteAPICredential]):
    pass


# Each operation corresponds to exactly one public contract operation.
ROUTES = {
    "get_me": ("GET", "/me"), "list_notes": ("GET", "/notes"),
    "get_note": ("GET", "/notes/{noteId}"), "create_note": ("POST", "/notes"),
    "update_note": ("PUT", "/notes/{noteId}"), "delete_note": ("DELETE", "/notes/{noteId}"),
    "list_children": ("GET", "/notes/{noteId}/children"), "verify_note": ("PUT", "/notes/{noteId}/verify"),
    "flag_outdated": ("PUT", "/notes/{noteId}/flag-as-outdated"), "set_archived": ("PUT", "/notes/{noteId}/archived"),
    "set_owner": ("PUT", "/notes/{noteId}/owner"), "search_notes": ("GET", "/search-notes"),
    "get_user": ("GET", "/users/{userId}"), "search_users": ("GET", "/users"),
    "get_group": ("GET", "/groups/{groupId}"), "search_groups": ("GET", "/groups"),
}


class SliteNode(WorkflowNode):
    integration_type = "automation-slite"
    connection_evidence = ConnectionEvidence(noun="Slite account", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return SliteConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Slite API key")
        op = self.config.config
        method, route = ROUTES[op.operation]
        data = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in ("noteId", "userId", "groupId"):
            if "{" + name + "}" in route:
                route = route.replace("{" + name + "}", quote(data.pop(name), safe=""))
        if op.operation == "verify_note":
            data["until"] = op.model_dump(mode="json")["until"]
        if op.operation == "search_notes" and not data.get("query"):
            data.pop("query", None)
        token = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"params": {k: str(v).lower() if isinstance(v, bool) else v for k, v in data.items()}} if method == "GET" else {"json": data} if method != "DELETE" else {}))
        except Exception:
            raise ValueError("Slite request could not be completed; inspect writes before retrying") from None
        if response.status_code != (204 if method == "DELETE" else 200):
            # Preserve definitive provider rejections for the connection-evidence seam.
            message = response.text.replace(token, "[redacted]")[:1000] if response.status_code in {401, 403} else "Slite request was not confirmed"
            result = {"status": "error", "http_status": response.status_code, "message": message, "write_outcome": "unverified" if method != "GET" else None}
        elif method == "DELETE":
            result = {"status": "success", "http_status": 204, "deletion_acknowledged": True, "deleted_id": op.noteId}
        else:
            try:
                if len(response.content) > 10_000_000:
                    raise ValueError()
                body = response.json()
                if not isinstance(body, dict) or "error" in body or "errors" in body:
                    raise ValueError()
                if op.operation == "get_me" and not all(isinstance(body.get(k), str) and body[k] for k in ("displayName", "email", "organizationName", "organizationDomain")):
                    raise ValueError()
            except Exception:
                raise ValueError("Slite returned an unexpected response; inspect writes before retrying") from None
            result = {"status": "success", "http_status": 200, "data": body}
        await self.emit(result)
        return result
