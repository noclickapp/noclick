"""Hjarni REST v1 notes, folders and tags, using a manually supplied API token.

Contract: https://hjarni.com/openapi.json (1.0.0). Each operation makes one
request. Lists return one page; writes are never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://hjarni.com/api/v1"


class HjarniAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Hjarni API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://hjarni.com/docs/agent-tokens",
        "x-credential-instructions": "In Hjarni, open Settings > Connections and create an API token. Choose the folders and Read or Write access your workflow needs, then paste the token here without the Bearer prefix. NoClick checks the account with GET /me. Restricted tokens can access only their granted folders; some account-wide operations require full access.",
    })
    credential_type: Literal["hjarni_api_token"] = Field("hjarni_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if any(c.isspace() for c in value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(25, ge=1, le=100, title="Results per Page")


class _Note(_Input):
    note_id: int = Field(..., ge=1, title="Note ID", description="The numeric ID returned by List Notes or Create Note.")


class _Container(_Input):
    container_id: int = Field(..., ge=1, title="Folder ID", description="The numeric folder (container) ID returned by List Folders.")


class _Tag(_Input):
    tag_id: int = Field(..., ge=1, title="Tag ID", description="The numeric ID returned by List Tags.")


class GetMe(_Input):
    """Read the account identity and the token's access grants."""
    operation: Literal["get_me"] = "get_me"


class SearchNotes(_Page):
    """Search accessible notes across personal or team spaces."""
    operation: Literal["search_notes"] = "search_notes"
    q: str = Field(..., min_length=1, title="Search Query")
    search_scope: str = Field("all", pattern=r"^(personal|all|team:[0-9]+)$", title="Search Scope")
    exclude_body: bool = Field(False, title="Exclude Note Bodies")


class ListNotes(_Page):
    """List one page of accessible notes with optional filters."""
    operation: Literal["list_notes"] = "list_notes"
    scope: Literal["archived", "inbox", "favorited"] | None = None
    container_id: int | None = Field(None, ge=1, title="Folder ID")
    tag: str | None = Field(None, title="Tag Name")
    q: str | None = Field(None, title="Search Query")
    exclude_body: bool = Field(False, title="Exclude Note Bodies")


class GetNote(_Note):
    """Read one note including its Markdown body."""
    operation: Literal["get_note"] = "get_note"


class _NoteFields(_Input):
    body: str | None = Field(None, max_length=262144, title="Markdown Body", json_schema_extra={"ui:widget": "textarea"})
    summary: str | None = Field(None, title="Summary")
    source_url: str | None = Field(None, title="Source URL")
    container_id: int | None = Field(None, ge=1, title="Folder ID", description="Omit to leave the folder unchanged on update, or use the inbox on create.")
    position: int | None = None
    tag_list: str | None = Field(None, title="Tag Names", description="Comma-separated tags. On update this replaces all tags; use Clear Tags to remove every tag.")


class CreateNote(_NoteFields):
    """Create a Markdown note; omitted folder means inbox."""
    operation: Literal["create_note"] = "create_note"
    title: str = Field(..., min_length=1, max_length=500, title="Title")


class UpdateNote(_Note, _NoteFields):
    """Update only supplied note fields; optionally guard against concurrent edits."""
    operation: Literal["update_note"] = "update_note"
    title: str | None = Field(None, min_length=1, max_length=500, title="Title")
    expected_lock_version: int | None = Field(None, ge=0, description="Use lock_version from Get Note; stale writes return 409.")
    append_body: str | None = Field(None, max_length=262144, title="Append Markdown")
    clear_tags: bool = Field(False, title="Clear Tags")
    clear_body: bool = Field(False, title="Clear Body")

    @model_validator(mode="after")
    def body_mode(self):
        if sum([self.body is not None, self.append_body is not None, self.clear_body]) > 1:
            raise ValueError("Choose Replace Body, Append Markdown, or Clear Body")
        if self.clear_tags and self.tag_list is not None:
            raise ValueError("Choose Tag Names or Clear Tags")
        return self


class DeleteNote(_Note):
    """Move a note to Trash; does not permanently delete it."""
    operation: Literal["delete_note"] = "delete_note"


class ArchiveNote(_Note):
    """Archive a note."""
    operation: Literal["archive_note"] = "archive_note"


class UnarchiveNote(_Note):
    """Unarchive a note."""
    operation: Literal["unarchive_note"] = "unarchive_note"


class MoveNote(_Note):
    """Move a note to a folder, or to the inbox if Folder ID is omitted."""
    operation: Literal["move_note"] = "move_note"
    container_id: int | None = Field(None, ge=1, title="Destination Folder ID", description="Leave empty to move to the inbox.")


class FavoriteNote(_Note):
    """Favorite a note."""
    operation: Literal["favorite_note"] = "favorite_note"


class UnfavoriteNote(_Note):
    """Remove a note from favorites."""
    operation: Literal["unfavorite_note"] = "unfavorite_note"


class RestoreNote(_Note):
    """Restore a note from Trash."""
    operation: Literal["restore_note"] = "restore_note"


class ListContainers(_Page):
    """List one page of accessible folders."""
    operation: Literal["list_containers"] = Field("list_containers", title="List Folders")
    scope: Literal["all", "archived"] | None = None


class GetContainer(_Container):
    """Read one folder."""
    operation: Literal["get_container"] = Field("get_container", title="Get Folder")


class _ContainerFields(_Input):
    emoji: str | None = None
    description: str | None = None
    parent_id: int | None = Field(None, ge=1, title="Parent Folder ID")
    llm_instructions: str | None = Field(None, title="Folder AI Instructions", json_schema_extra={"ui:widget": "textarea"})
    position: int | None = None


class CreateContainer(_ContainerFields):
    """Create a folder with optional parent and AI instructions."""
    operation: Literal["create_container"] = Field("create_container", title="Create Folder")
    name: str = Field(..., min_length=1, title="Folder Name")


class UpdateContainer(_Container, _ContainerFields):
    """Update supplied folder fields. Root folders cannot be changed."""
    operation: Literal["update_container"] = Field("update_container", title="Update Folder")
    name: str | None = Field(None, min_length=1, title="Folder Name")


class DeleteContainer(_Container):
    """Move a folder and its contents to Trash."""
    operation: Literal["delete_container"] = Field("delete_container", title="Trash Folder")


class ListContainerNotes(_Container, _Page):
    """List one page of notes in a folder."""
    operation: Literal["list_container_notes"] = Field("list_container_notes", title="List Folder Notes")


class ListTags(_Page):
    """List one page of the account's tags."""
    operation: Literal["list_tags"] = "list_tags"


class GetTag(_Tag):
    """Read one tag."""
    operation: Literal["get_tag"] = "get_tag"


class CreateTag(_Input):
    """Create a tag."""
    operation: Literal["create_tag"] = "create_tag"
    name: str = Field(..., min_length=1, title="Tag Name")


class UpdateTag(_Tag):
    """Rename a tag."""
    operation: Literal["update_tag"] = "update_tag"
    name: str = Field(..., min_length=1, title="Tag Name")


class DeleteTag(_Tag):
    """Delete a tag, removing it from every note."""
    operation: Literal["delete_tag"] = "delete_tag"


class ListTagNotes(_Tag, _Page):
    """List one page of notes carrying a tag."""
    operation: Literal["list_tag_notes"] = "list_tag_notes"


Operation = Annotated[Union[GetMe, SearchNotes, ListNotes, GetNote, CreateNote, UpdateNote,
    DeleteNote, ArchiveNote, UnarchiveNote, MoveNote, FavoriteNote, UnfavoriteNote, RestoreNote,
    ListContainers, GetContainer, CreateContainer, UpdateContainer, DeleteContainer, ListContainerNotes,
    ListTags, GetTag, CreateTag, UpdateTag, DeleteTag, ListTagNotes], Field(discriminator="operation")]


class HjarniConfig(NodeConfig[Operation, HjarniAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Fixed routes and methods from the published v1 contract; no arbitrary URL input.
ROUTES = {
    "get_me": ("GET", "/me"),
    "search_notes": ("GET", "/search"),
    "list_notes": ("GET", "/notes"),
    "get_note": ("GET", "/notes/{note_id}"),
    "create_note": ("POST", "/notes"),
    "update_note": ("PATCH", "/notes/{note_id}"),
    "delete_note": ("DELETE", "/notes/{note_id}"),
    "archive_note": ("PATCH", "/notes/{note_id}/archive"),
    "unarchive_note": ("PATCH", "/notes/{note_id}/unarchive"),
    "move_note": ("PATCH", "/notes/{note_id}/move"),
    "favorite_note": ("PATCH", "/notes/{note_id}/favorite"),
    "unfavorite_note": ("PATCH", "/notes/{note_id}/unfavorite"),
    "restore_note": ("POST", "/notes/{note_id}/restore"),
    "list_containers": ("GET", "/containers"),
    "get_container": ("GET", "/containers/{container_id}"),
    "create_container": ("POST", "/containers"),
    "update_container": ("PATCH", "/containers/{container_id}"),
    "delete_container": ("DELETE", "/containers/{container_id}"),
    "list_container_notes": ("GET", "/containers/{container_id}/notes"),
    "list_tags": ("GET", "/tags"),
    "get_tag": ("GET", "/tags/{tag_id}"),
    "create_tag": ("POST", "/tags"),
    "update_tag": ("PATCH", "/tags/{tag_id}"),
    "delete_tag": ("DELETE", "/tags/{tag_id}"),
    "list_tag_notes": ("GET", "/tags/{tag_id}/notes"),
}


class HjarniNode(WorkflowNode):
    integration_type = "automation-hjarni"
    connection_evidence = ConnectionEvidence(noun="Hjarni account", identity_operation="get_me", identity_keys=("email_address", "email", "first_name"))

    @classmethod
    def get_config_model(cls):
        return HjarniConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Hjarni API token")
        cfg = self.config.config
        op = cfg.operation
        method, template = ROUTES[op]
        values = cfg.model_dump(exclude={"operation"}, exclude_none=True)
        path = template.format(**values)
        for field in ("note_id", "tag_id", "container_id"):
            if "{" + field + "}" in template:
                values.pop(field)
        params, body = None, None
        if method == "GET":
            params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        elif op in {"create_note", "update_note", "create_container", "update_container", "create_tag", "update_tag"}:
            if op == "update_note":
                clear_tags, clear_body = values.pop("clear_tags"), values.pop("clear_body")
                if clear_tags:
                    values["tag_list"] = ""
                if clear_body:
                    values["body"] = ""
            kind = op.split("_", 1)[1]
            body = {kind: values}
        elif op == "move_note":
            body = {"container_id": cfg.container_id}
        expected = 204 if method == "DELETE" else 201 if op.startswith("create_") else 200
        output = {"operation": op}
        token = self.config.credentials.api_token
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
            if response.status_code != expected:
                error = "Hjarni request failed"
                # Preserve definitive rejections for manual connect, without echoing a secret.
                if response.status_code in {401, 403}:
                    try:
                        raw = response.json()
                        message = raw.get("error") if isinstance(raw, dict) else None
                        if isinstance(message, str):
                            error = message.replace(token, "[redacted]")[:1000]
                    except ValueError:
                        pass
                return {**output, "status": "error", "http_status": response.status_code, "error": error,
                    **({"retry_after": response.headers.get("Retry-After")} if response.status_code == 429 else {})}
            if expected == 204:
                return {**output, "status": "success", "deleted": True}
            if len(response.content) > 10_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
                raise ValueError("Expected a bounded Hjarni JSON response")
            data = response.json()
            is_list = op.startswith("list_") or op == "search_notes"
            if is_list:
                if not isinstance(data, list) or any(not isinstance(item, dict) or type(item.get("id")) is not int for item in data):
                    raise ValueError("Expected a page of Hjarni records")
                pagination = {}
                for header, key in [("X-Total-Count", "total_count"), ("X-Page", "page"), ("X-Per-Page", "per_page")]:
                    raw = response.headers.get(header)
                    if raw is not None:
                        pagination[key] = int(raw)
                        if pagination[key] < (0 if key == "total_count" else 1):
                            raise ValueError("Invalid pagination header")
                total = pagination.get("total_count")
                page = pagination.get("page", cfg.page)
                per_page = pagination.get("per_page", cfg.per_page)
                next_page = page + 1 if total is not None and page * per_page < total else None
                return {**output, "status": "success", "items": data, "pagination": pagination, "next_page": next_page}
            if not isinstance(data, dict) or "error" in data or "errors" in data:
                raise ValueError("Expected a Hjarni record")
            if op == "get_me":
                user, account_token = data.get("user"), data.get("token")
                if (not isinstance(user, dict) or type(user.get("id")) is not int
                    or not isinstance(user.get("email_address"), str) or not user["email_address"]
                    or not isinstance(account_token, dict) or type(account_token.get("id")) is not int):
                    raise ValueError("Expected the Hjarni account and token")
            elif type(data.get("id")) is not int:
                raise ValueError("Expected a Hjarni record ID")
            return {**output, "status": "success", "data": data}
        except (httpx.HTTPError, SSRFError, ValueError):
            return {**output, "status": "error", "error": "Hjarni request could not be confirmed; inspect the account before retrying a write"}
