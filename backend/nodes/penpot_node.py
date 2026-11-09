"""Penpot 2.19 RPC methods using a personal access token.

Contract: https://design.penpot.app/api/main/doc/openapi.json
Authentication: https://help.penpot.app/technical-guide/integration/
All operations perform exactly one RPC call; writes are never retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://design.penpot.app/api/main/methods"


class PenpotTokenCredential(BaseModel):
    model_config = ConfigDict(title="Penpot Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://design.penpot.app/#/settings/access-tokens",
            "x-credential-instructions": "In Penpot, open Your account > Integrations > Personal access tokens. Create a token, choose its expiration, and paste the token here. It gives access to your account until it expires or you delete it."
        })
    credential_type: Literal["penpot_token"] = Field("penpot_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Personal access token", min_length=1, max_length=8192, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token alone, without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class PenpotGetProfile(_Input):
    """Get profile."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})


class PenpotGetTeams(_Input):
    """Get teams."""
    operation: Literal["get_teams"] = Field("get_teams", json_schema_extra={"ui:hidden": True})


class PenpotGetTeam(_Input):
    """Get a team by its ID or by a file it contains."""
    operation: Literal["get_team"] = Field("get_team", json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, title="Team ID (UUID)")
    file_id: UUID | None = Field(None, alias="fileId", title="File ID (UUID)")

    @model_validator(mode="after")
    def selector(self):
        if self.id is None and self.file_id is None:
            raise ValueError("Supply a team ID or file ID")
        return self


class PenpotGetProjects(_Input):
    """Get projects."""
    operation: Literal["get_projects"] = Field("get_projects", json_schema_extra={"ui:hidden": True})
    team_id: UUID = Field(..., alias='teamId', title='Team id (UUID)')


class PenpotGetProject(_Input):
    """Get project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title='Id (UUID)')


class PenpotCreateProject(_Input):
    """Create project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    team_id: UUID = Field(..., alias='teamId', title='Team id (UUID)')
    name: str = Field(..., title='Name', min_length=1, max_length=250)


class PenpotRenameProject(_Input):
    """Rename project."""
    operation: Literal["rename_project"] = Field("rename_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name', min_length=1, max_length=250)
    id: UUID = Field(..., title='Id (UUID)')


class PenpotDeleteProject(_Input):
    """Delete project."""
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title='Id (UUID)')


class PenpotGetProjectFiles(_Input):
    """Get all files for the specified project."""
    operation: Literal["get_project_files"] = Field("get_project_files", json_schema_extra={"ui:hidden": True})
    project_id: UUID = Field(..., alias='projectId', title='Project id (UUID)')


class PenpotGetFile(_Input):
    """Retrieve a file by its ID. Only authenticated users."""
    operation: Literal["get_file"] = Field("get_file", json_schema_extra={"ui:hidden": True})
    features: list[str] | None = Field(None, title='Features', description="Optional Penpot feature flags; leave unset to use the server defaults.")
    id: UUID = Field(..., title='Id (UUID)')


class PenpotCreateFile(_Input):
    """Create file."""
    operation: Literal["create_file"] = Field("create_file", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name', max_length=250)
    project_id: UUID = Field(..., alias='projectId', title='Project id (UUID)')
    is_shared: StrictBool | None = Field(None, alias='isShared', title='Is shared')
    features: list[str] | None = Field(None, title='Features', description="Optional Penpot feature flags; leave unset to use the server defaults.")


class PenpotRenameFile(_Input):
    """Rename file."""
    operation: Literal["rename_file"] = Field("rename_file", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name', min_length=1, max_length=250)
    id: UUID = Field(..., title='Id (UUID)')


class PenpotDeleteFile(_Input):
    """Delete file."""
    operation: Literal["delete_file"] = Field("delete_file", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title='Id (UUID)')


class PenpotDuplicateFile(_Input):
    """Duplicate a single file in the same team."""
    operation: Literal["duplicate_file"] = Field("duplicate_file", json_schema_extra={"ui:hidden": True})
    file_id: UUID = Field(..., alias='fileId', title='File id (UUID)')
    name: str | None = Field(None, title='Name', max_length=250)


class PenpotGetFileLibraries(_Input):
    """Get libraries used by the specified file."""
    operation: Literal["get_file_libraries"] = Field("get_file_libraries", json_schema_extra={"ui:hidden": True})
    file_id: UUID = Field(..., alias='fileId', title='File id (UUID)')


class PenpotLinkFileToLibrary(_Input):
    """Link a file to a library. Returns the recursive list of libraries used by that library"""
    operation: Literal["link_file_to_library"] = Field("link_file_to_library", json_schema_extra={"ui:hidden": True})
    file_id: UUID = Field(..., alias='fileId', title='File id (UUID)')
    library_id: UUID = Field(..., alias='libraryId', title='Library id (UUID)')


class PenpotUnlinkFileFromLibrary(_Input):
    """Unlink file from library."""
    operation: Literal["unlink_file_from_library"] = Field("unlink_file_from_library", json_schema_extra={"ui:hidden": True})
    file_id: UUID = Field(..., alias='fileId', title='File id (UUID)')
    library_id: UUID = Field(..., alias='libraryId', title='Library id (UUID)')


class PenpotSearchFiles(_Input):
    """Search files."""
    operation: Literal["search_files"] = Field("search_files", json_schema_extra={"ui:hidden": True})
    team_id: UUID = Field(..., alias='teamId', title='Team id (UUID)')
    search_term: str | None = Field(None, alias='searchTerm', title='Search term', max_length=250)


class PenpotGetTeamMembers(_Input):
    """Get team members."""
    operation: Literal["get_team_members"] = Field("get_team_members", json_schema_extra={"ui:hidden": True})
    team_id: UUID = Field(..., alias='teamId', title='Team id (UUID)')


class PenpotSetFileShared(_Input):
    """Set file shared."""
    operation: Literal["set_file_shared"] = Field("set_file_shared", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title='Id (UUID)')
    is_shared: StrictBool = Field(..., alias='isShared', title='Is shared')


PenpotOperation = Annotated[Union[
    PenpotGetProfile,
    PenpotGetTeams,
    PenpotGetTeam,
    PenpotGetProjects,
    PenpotGetProject,
    PenpotCreateProject,
    PenpotRenameProject,
    PenpotDeleteProject,
    PenpotGetProjectFiles,
    PenpotGetFile,
    PenpotCreateFile,
    PenpotRenameFile,
    PenpotDeleteFile,
    PenpotDuplicateFile,
    PenpotGetFileLibraries,
    PenpotLinkFileToLibrary,
    PenpotUnlinkFileFromLibrary,
    PenpotSearchFiles,
    PenpotGetTeamMembers,
    PenpotSetFileShared
], Field(discriminator="operation")]


class PenpotConfig(NodeConfig[PenpotOperation, PenpotTokenCredential]):
    model_config = ConfigDict(title="Penpot Configuration", hide_input_in_errors=True)


class PenpotNode(WorkflowNode):
    integration_type = "automation-penpot"
    connection_evidence = ConnectionEvidence(noun="teams", operation="get_teams", identity_operation="get_profile",
        identity_keys=("fullname", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return PenpotConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Penpot personal access token")
        config = self.config.config
        body = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        token = self.config.credentials.access_token
        # The operation discriminator is a closed union; no user-controlled route.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request("POST", BASE + "/" + config.operation.replace("_", "-"),
                headers={"Authorization": "Token " + token, "Accept": "application/json"}, json=body)
        if not 200 <= response.status_code < 300:
            # Provider error payloads contain its message, never request headers.
            message = "Penpot request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("hint") or error.get("message") or error.get("code") or message)
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message.replace(token, "[redacted]")[:1000]}
        if response.status_code == 204 or not response.content:
            return {"status": "success", "data": None}
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json":
            raise ValueError("Penpot returned an unexpected content type; expected JSON")
        data = response.json()
        if isinstance(data, dict) and (data.get("type") in {"validation", "authentication", "authorization", "internal"} or "error" in data):
            return {"status": "error", "error": str(data.get("hint") or data.get("message") or data.get("error") or "Penpot rejected the request").replace(token, "[redacted]")[:1000]}
        # Keep the provider's object/list/null shape, including file design data.
        return {"status": "success", "data": data}
