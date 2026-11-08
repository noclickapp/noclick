"""HackMD v1 personal/team notes, folders and account reads.

Contract: https://api.hackmd.io/v1/docs/swagger.json (1.0.0).
Authentication: https://hackmd.io/@docs/api-authorization.
Each operation makes exactly one request; accepted updates are not read back.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.hackmd.io/v1"


class HackMDTokenCredential(BaseModel):
    model_config = ConfigDict(title="HackMD API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://hackmd.io/settings#api",
            "x-credential-instructions": "In HackMD, open My account > Settings > API, create an API token, and paste the copied token here. NoClick sends it as a Bearer token to api.hackmd.io. Your notes verify the connection; an empty account is verified by reading its current profile.",
        })
    credential_type: Literal["hackmd_api_token"] = Field("hackmd_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", repr=False,
        description="Paste the API token without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste an API token without spaces or a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("note_id", "folder_id", "team_path", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value) or len(value) > 256:
            raise ValueError("Paste a HackMD identifier, not a URL or path")
        return value


class _NoteWrite(_Input):
    title: str | None = Field(None, max_length=10000)
    content: str | None = Field(None, max_length=1000000, description="Markdown content; an update replaces the note content.")
    description: str | None = Field(None, max_length=100000)
    tags: list[str] | None = None
    read_permission: Literal["owner", "signed_in", "guest"] | None = Field(None, description="Omit to use HackMD's default or retain the current permission.")
    write_permission: Literal["owner", "signed_in", "guest"] | None = Field(None, description="Omit to use HackMD's default or retain the current permission.")
    parent_folder_id: str | None = Field(None, description="Destination folder ID; omit to retain the current location.")
    permalink: str | None = None


class _FolderWrite(_Input):
    name: str | None = Field(None, max_length=10000)
    description: str | None = Field(None, max_length=100000)
    parent_folder_id: str | None = None
    icon: str | None = Field(None, description="Emoji unified codepoint, for example 1F525.")
    color: str | None = Field(None, description="Hexadecimal color, for example #FF6B6B.")


class GetMe(_Input):
    """Get me using the corresponding HackMD v1 endpoint."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class ListNotes(_Input):
    """List notes using the corresponding HackMD v1 endpoint."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})


class GetNote(_Input):
    """Get note using the corresponding HackMD v1 endpoint."""
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})
    note_id: str


class CreateNote(_NoteWrite):
    """Create note using the corresponding HackMD v1 endpoint."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})


class UpdateNote(_NoteWrite):
    """Update note using the corresponding HackMD v1 endpoint."""
    operation: Literal["update_note"] = Field("update_note", json_schema_extra={"ui:hidden": True})
    note_id: str


class DeleteNote(_Input):
    """Delete note using the corresponding HackMD v1 endpoint."""
    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra={"ui:hidden": True})
    note_id: str


class ListTeams(_Input):
    """List teams using the corresponding HackMD v1 endpoint."""
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True})


class ListTeamNotes(_Input):
    """List team notes using the corresponding HackMD v1 endpoint."""
    operation: Literal["list_team_notes"] = Field("list_team_notes", json_schema_extra={"ui:hidden": True})
    team_path: str


class GetTeamNote(_Input):
    """Get team note using the corresponding HackMD v1 endpoint."""
    operation: Literal["get_team_note"] = Field("get_team_note", json_schema_extra={"ui:hidden": True})
    team_path: str
    note_id: str


class CreateTeamNote(_NoteWrite):
    """Create team note using the corresponding HackMD v1 endpoint."""
    operation: Literal["create_team_note"] = Field("create_team_note", json_schema_extra={"ui:hidden": True})
    team_path: str


class UpdateTeamNote(_NoteWrite):
    """Update team note using the corresponding HackMD v1 endpoint."""
    operation: Literal["update_team_note"] = Field("update_team_note", json_schema_extra={"ui:hidden": True})
    team_path: str
    note_id: str


class DeleteTeamNote(_Input):
    """Delete team note using the corresponding HackMD v1 endpoint."""
    operation: Literal["delete_team_note"] = Field("delete_team_note", json_schema_extra={"ui:hidden": True})
    team_path: str
    note_id: str


class GetHistory(_Input):
    """Get history using the corresponding HackMD v1 endpoint."""
    operation: Literal["get_history"] = Field("get_history", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000)


class ListFolders(_Input):
    """List folders using the corresponding HackMD v1 endpoint."""
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"ui:hidden": True})


class GetFolder(_Input):
    """Get folder using the corresponding HackMD v1 endpoint."""
    operation: Literal["get_folder"] = Field("get_folder", json_schema_extra={"ui:hidden": True})
    folder_id: str


class CreateFolder(_FolderWrite):
    """Create folder using the corresponding HackMD v1 endpoint."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=10000)


class UpdateFolder(_FolderWrite):
    """Update folder using the corresponding HackMD v1 endpoint."""
    operation: Literal["update_folder"] = Field("update_folder", json_schema_extra={"ui:hidden": True})
    folder_id: str


class DeleteFolder(_Input):
    """Delete folder using the corresponding HackMD v1 endpoint."""
    operation: Literal["delete_folder"] = Field("delete_folder", json_schema_extra={"ui:hidden": True})
    folder_id: str


class ListTrash(_Input):
    """List trash using the corresponding HackMD v1 endpoint."""
    operation: Literal["list_trash"] = Field("list_trash", json_schema_extra={"ui:hidden": True})


class RestoreNote(_Input):
    """Restore note using the corresponding HackMD v1 endpoint."""
    operation: Literal["restore_note"] = Field("restore_note", json_schema_extra={"ui:hidden": True})
    note_id: str


HackMDOperation = Annotated[Union[
    GetMe, ListNotes, GetNote, CreateNote, UpdateNote, DeleteNote, ListTeams, ListTeamNotes, GetTeamNote, CreateTeamNote, UpdateTeamNote, DeleteTeamNote, GetHistory, ListFolders, GetFolder, CreateFolder, UpdateFolder, DeleteFolder, ListTrash, RestoreNote
], Field(discriminator="operation")]


class HackMDFullConfig(NodeConfig[HackMDOperation, HackMDTokenCredential]):
    pass


ROUTES = {
    "get_me": ("GET", "/me", 200),
    "list_notes": ("GET", "/notes", 200),
    "get_note": ("GET", "/notes/{note_id}", 200),
    "create_note": ("POST", "/notes", 201),
    "update_note": ("PATCH", "/notes/{note_id}", 202),
    "delete_note": ("DELETE", "/notes/{note_id}", 204),
    "list_teams": ("GET", "/teams", 200),
    "list_team_notes": ("GET", "/teams/{team_path}/notes", 200),
    "get_team_note": ("GET", "/teams/{team_path}/notes/{note_id}", 200),
    "create_team_note": ("POST", "/teams/{team_path}/notes", 201),
    "update_team_note": ("PATCH", "/teams/{team_path}/notes/{note_id}", 202),
    "delete_team_note": ("DELETE", "/teams/{team_path}/notes/{note_id}", 204),
    "get_history": ("GET", "/history", 200),
    "list_folders": ("GET", "/folders", 200),
    "get_folder": ("GET", "/folders/{folder_id}", 200),
    "create_folder": ("POST", "/folders", 201),
    "update_folder": ("PATCH", "/folders/{folder_id}", 202),
    "delete_folder": ("DELETE", "/folders/{folder_id}", 204),
    "list_trash": ("GET", "/trash", 200),
    "restore_note": ("PUT", "/trash/{note_id}/restore", 204),
}
BODY_NAMES = {"read_permission": "readPermission", "write_permission": "writePermission", "parent_folder_id": "parentFolderId"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class HackMDNode(WorkflowNode):
    integration_type = "automation-hackmd"
    connection_evidence = ConnectionEvidence(noun="HackMD notes", operation="list_notes", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return HackMDFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a HackMD API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, route, expected = ROUTES[op.operation]
        fields = op.model_dump(exclude_none=True, exclude={"operation"})
        for name in ("note_id", "folder_id", "team_path"):
            if name in fields:
                route = route.replace("{" + name + "}", quote(fields.pop(name), safe=""))
        kwargs = {}
        if op.operation == "get_history":
            kwargs["params"] = fields
        elif method in {"POST", "PATCH"}:
            kwargs["json"] = {BODY_NAMES.get(name, name): value for name, value in fields.items()}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + route,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        status = response.status_code
        if status != expected:
            # 207 is partial success: retain the documented note/error pair, but
            # do not label it as a fully successful create or retry the write.
            if status == 207 and op.operation in {"create_note", "create_team_note"}:
                result = {"status": "partial", "success": False, "http_status": status, "data": response.json()}
            else:
                message = response.text[:4000]
                result = {"status": "error", "success": False, "http_status": status,
                    "message": message or "HackMD request was not accepted"}
        elif status in {202, 204}:
            result = {"status": "success", "success": True, "http_status": status,
                "accepted": status == 202, "acknowledged": status == 204}
        else:
            if len(response.content) > 10000000:
                raise ValueError("HackMD response exceeds the supported size")
            data = response.json()
            array_response = op.operation in {"list_notes", "list_teams", "list_team_notes", "list_folders", "list_trash", "get_history"}
            if not isinstance(data, list if array_response else dict):
                raise ValueError("Unexpected HackMD response shape")
            if not array_response and (not isinstance(data.get("id"), str) or not data.get("id")):
                raise ValueError("HackMD response did not identify the resource")
            result = {"status": "success", "success": True, "http_status": status, "data": data}
        result = _redact(result, token)
        await self.emit(result)
        return result
