"""Wistia Data API, pinned to the published 2026-09 contract.

Each operation performs one request. Lists return one explicit page; URL imports
only acknowledge a queued background job, and deletes acknowledge the API response.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.wistia.com/modern"
API_VERSION = "2026-09"
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=255)]


class WistiaAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Wistia API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.wistia.com/docs/making-api-requests",
            "x-credential-instructions": "Paste a Wistia API token from Account Settings > API. Reads need Read all data (or Read all folder and media data for media/folders); writes and URL imports need Read, update & delete anything. Use a permanent account token for the account connection check. NoClick sends it only to api.wistia.com as a Bearer token.",
        })
    credential_type: Literal["wistia_api_token"] = Field("wistia_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
                           json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetAccount(Input):
    """Get the current account's name, URL and record counts."""
    operation: Literal["get_account"] = "get_account"


class GetToken(Input):
    """Inspect the current token's permissions without returning its secret value."""
    operation: Literal["get_token"] = "get_token"


class Page(Input):
    page: int = Field(1, ge=1, le=1000000, description="Explicit page number. Lists return one page only.")
    per_page: int = Field(25, ge=1, le=100)


class ListMedia(Page):
    """List or find media by exact name, folder, type or archive status."""
    operation: Literal["list_media"] = "list_media"
    folder_id: Identifier | None = Field(None, description="Folder hashed ID.")
    name: str | None = Field(None, max_length=255)
    type: Literal["Video", "Audio", "Image", "PdfDocument", "MicrosoftOfficeDocument", "Swf", "UnknownType"] | None = None
    archived: bool | None = None
    sort_by: Literal["name", "created", "updated", "position"] | None = None
    sort_direction: Literal[0, 1] | None = None


class Media(Input):
    media_id: Identifier = Field(..., description="Wistia media hashed ID, not its numeric ID.")


class GetMedia(Media):
    """Fetch a media's metadata and processing status."""
    operation: Literal["get_media"] = "get_media"


class UpdateMedia(Media):
    """Update media metadata. Supplied tags replace all existing tags."""
    operation: Literal["update_media"] = "update_media"
    name: Name | None = None
    description: str | None = Field(None, max_length=50000)
    tags: list[Annotated[str, Field(min_length=1, max_length=50)]] | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, key) is None for key in ("name", "description", "tags")):
            raise ValueError("Supply a name, description or replacement tags")
        return self


class DeleteMedia(Media):
    """Move a media to Recently Deleted; this does not prove permanent purging."""
    operation: Literal["delete_media"] = "delete_media"


class CopyMedia(Media):
    """Copy media and assets. Wistia may fall back to the original folder if the target is invalid."""
    operation: Literal["copy_media"] = "copy_media"
    folder_id: int | None = Field(None, ge=1, description="Destination numeric folder ID; omitted uses source folder.")


class GetMediaStats(Media):
    """Read aggregated embed statistics for a media."""
    operation: Literal["get_media_stats"] = "get_media_stats"


class ImportMedia(Input):
    """Queue a media import from a publicly accessible URL; poll the returned job separately."""
    operation: Literal["import_media"] = "import_media"
    url: str = Field(..., max_length=4096, description="Public HTTPS media file URL. Wistia fetches the file.")
    folder_id: Identifier | None = Field(None, description="Destination folder hashed ID; omitted creates a new folder.")

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment or any(c.isspace() for c in value):
            raise ValueError("Use a public HTTPS URL without userinfo or a fragment")
        return value


class GetJob(Input):
    """Read the status of a background import or other asynchronous job."""
    operation: Literal["get_job"] = "get_job"
    job_id: Identifier = Field(..., description="Prefer the job's hashed_id returned by import_media.")


class ListFolders(Page):
    """List folders in the connected account."""
    operation: Literal["list_folders"] = "list_folders"


class Folder(Input):
    folder_id: Identifier = Field(..., description="Wistia folder hashed ID.")


class GetFolder(Folder):
    """Read a folder and its media link without following the link."""
    operation: Literal["get_folder"] = "get_folder"


class CreateFolder(Input):
    """Create a private folder with anonymous uploads and downloads disabled."""
    operation: Literal["create_folder"] = "create_folder"
    name: Name
    description: str | None = Field(None, max_length=50000)


class UpdateFolder(Folder):
    """Update a folder name or description without changing its sharing settings."""
    operation: Literal["update_folder"] = "update_folder"
    name: Name | None = None
    description: str | None = Field(None, max_length=50000)

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.description is None:
            raise ValueError("Supply a name or description")
        return self


class DeleteFolder(Folder):
    """Delete a folder AND all media inside it."""
    operation: Literal["delete_folder"] = "delete_folder"


class ListTags(Page):
    """List account tags and their usage counts."""
    operation: Literal["list_tags"] = "list_tags"


class CreateTag(Input):
    """Create a tag; Wistia lowercases and normalizes whitespace in the name."""
    operation: Literal["create_tag"] = "create_tag"
    name: str = Field(..., min_length=1, max_length=50)


class DeleteTag(Input):
    """Delete an account tag by its name."""
    operation: Literal["delete_tag"] = "delete_tag"
    name: str = Field(..., min_length=1, max_length=50)


class ListCaptions(Media):
    """List the caption tracks on a media."""
    operation: Literal["list_captions"] = "list_captions"


class CreateCaptions(Media):
    """Create captions from SRT text; omit language to let Wistia detect it."""
    operation: Literal["create_captions"] = "create_captions"
    caption_file: str = Field(..., min_length=1, max_length=1000000, description="SRT file contents, not a file path or URL.")
    language: str | None = Field(None, pattern=r"^[a-z]{3}$", description="ISO-639-2 three-letter language code.")


WistiaConfig = Annotated[Union[GetAccount, GetToken, ListMedia, GetMedia, UpdateMedia,
    DeleteMedia, CopyMedia, GetMediaStats, ImportMedia, GetJob, ListFolders,
    GetFolder, CreateFolder, UpdateFolder, DeleteFolder, ListTags, CreateTag,
    DeleteTag, ListCaptions, CreateCaptions], Field(discriminator="operation")]


class WistiaFullConfig(NodeConfig[WistiaConfig, WistiaAPITokenCredential]):
    pass


# method, contract path, path field, body fields. Query fields are explicit below.
ROUTES = {
    "get_account": ("GET", "/account", None, ()),
    "get_token": ("GET", "/token", None, ()),
    "list_media": ("GET", "/medias", None, ()),
    "get_media": ("GET", "/medias/{mediaHashedId}", "media_id", ()),
    "update_media": ("PUT", "/medias/{mediaHashedId}", "media_id", ("name", "description", "tags")),
    "delete_media": ("DELETE", "/medias/{mediaHashedId}", "media_id", ()),
    "copy_media": ("POST", "/medias/{mediaHashedId}/copy", "media_id", ("folder_id",)),
    "get_media_stats": ("GET", "/medias/{mediaHashedId}/stats", "media_id", ()),
    "import_media": ("POST", "/medias/import_url", None, ("url", "folder_id")),
    "get_job": ("GET", "/background_job_status/{backgroundJobStatusId}", "job_id", ()),
    "list_folders": ("GET", "/folders", None, ()),
    "get_folder": ("GET", "/folders/{id}", "folder_id", ()),
    "create_folder": ("POST", "/folders", None, ("name", "description")),
    "update_folder": ("PUT", "/folders/{id}", "folder_id", ("name", "description")),
    "delete_folder": ("DELETE", "/folders/{id}", "folder_id", ()),
    "list_tags": ("GET", "/tags", None, ()),
    "create_tag": ("POST", "/tags", None, ("name",)),
    "delete_tag": ("DELETE", "/tags/{name}", "name", ()),
    "list_captions": ("GET", "/medias/{mediaHashedId}/captions", "media_id", ()),
    "create_captions": ("POST", "/medias/{mediaHashedId}/captions", "media_id", ("caption_file", "language")),
}
PAGED = {"list_media", "list_folders", "list_tags"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class WistiaNode(WorkflowNode):
    integration_type = "automation-wistia"
    connection_evidence = ConnectionEvidence(noun="Wistia media", operation="list_media", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return WistiaFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wistia API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path, path_field, body_fields = ROUTES[op.operation]
        if path_field:
            path = re.sub(r"\{[^}]+\}", lambda _: quote(str(getattr(op, path_field)), safe=""), path)
        params = {}
        if op.operation in PAGED:
            params = {"page": op.page, "per_page": op.per_page}
        if op.operation == "list_media":
            for field in ("folder_id", "name", "type", "archived", "sort_by", "sort_direction"):
                value = getattr(op, field)
                if value is not None:
                    params[field] = str(value).lower() if isinstance(value, bool) else value
        body = {field: getattr(op, field) for field in body_fields if getattr(op, field) is not None}
        if op.operation == "create_folder":
            body.update(public=False, anonymousCanUpload=False, anonymousCanDownload=False)
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json", "X-Wistia-API-Version": API_VERSION}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, headers=headers, params=params,
                                                **({"json": body} if method in {"POST", "PUT"} else {}))
        except httpx.RequestError:
            raise ValueError("Wistia request did not complete; inspect write outcomes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the manual connection seam.
            message = _redact(response.text[:2000], token)
            output = {"status": "error", "http_status": response.status_code,
                      "message": message or "Wistia request was rejected"}
        else:
            if op.operation in {"delete_tag", "create_captions"} and not response.content:
                data = None
            else:
                if len(response.content) > 10000000 or "json" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Expected bounded JSON from Wistia; inspect write outcomes before retrying")
                try:
                    data = response.json()
                except ValueError:
                    raise ValueError("Wistia returned invalid JSON; inspect write outcomes before retrying") from None
                is_list = op.operation in PAGED or op.operation == "list_captions"
                if not isinstance(data, list if is_list else dict) or (isinstance(data, dict) and ("error" in data or "errors" in data)):
                    raise ValueError("Wistia response shape was not confirmed; inspect write outcomes before retrying")
            if isinstance(data, list) and any(not isinstance(row, dict) for row in data):
                raise ValueError("Wistia list contains an invalid record")
            if op.operation == "get_account" and (type(data.get("id")) is not int or not isinstance(data.get("name"), str) or not data["name"]):
                raise ValueError("Wistia account identity was not confirmed")
            output = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": data}
            if op.operation in PAGED:
                more = len(data) >= op.per_page
                output.update(page=op.page, per_page=op.per_page, next_page=op.page + 1 if more else None,
                              has_more=more, pagination_note="A full page may have more results; fetch next_page to confirm.")
            if op.operation == "import_media":
                output["import_completed"] = False
            if method == "DELETE":
                output["deletion_acknowledged"] = True
        output = _redact(output, token)
        await self.emit(output)
        return output
