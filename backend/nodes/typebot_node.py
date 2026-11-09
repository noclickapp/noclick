"""Typebot builder API v1: personal-token workspace, bot, result and folder automation.

Contract: apps/docs/openapi/builder.json in baptisteArno/typebot.io (1.0.0).
Each exposed operation issues exactly one request; result pagination is explicit.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://app.typebot.com/api"


class TypebotAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Typebot API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.typebot.io/api-reference/authentication",
            "x-credential-instructions": "In Typebot, open Settings & Members > My account > API tokens and create a token. Paste it here without the Bearer prefix. NoClick uses the hosted Typebot builder API.",
        })
    credential_type: Literal["typebot_api_token"] = Field("typebot_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not value.strip() or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value) or value in {".", ".."}:
                raise ValueError("Paste a single Typebot resource ID")
        return value


class _Workspace(_Input):
    workspace_id: str = Field(..., min_length=1, description="Settings & Members > Workspace > Settings > workspace ID.")


class _Bot(_Input):
    typebot_id: str = Field(..., min_length=1, description="Builder typebot ID from the editor URL, not its public chat ID.")


class _Result(_Bot):
    result_id: str = Field(..., min_length=1)


class _Folder(_Workspace):
    folder_id: str = Field(..., min_length=1)


TimeFilter = Literal["today", "last7Days", "last30Days", "monthToDate", "lastMonth", "yearToDate", "allTime"]


class _TimeFilter(_Bot):
    time_filter: TimeFilter = "last7Days"
    time_zone: str | None = Field(None, description="IANA time zone, for example Europe/Paris.")


class TypebotListWorkspaces(_Input):
    """List workspaces."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})


class TypebotCreateWorkspace(_Input):
    """Create workspace."""
    operation: Literal["create_workspace"] = Field("create_workspace", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    icon: str | None = None


class TypebotGetWorkspace(_Workspace):
    """Get workspace."""
    operation: Literal["get_workspace"] = Field("get_workspace", json_schema_extra={"ui:hidden": True})


class TypebotUpdateWorkspace(_Workspace):
    """Update workspace."""
    operation: Literal["update_workspace"] = Field("update_workspace", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    icon: str | None = None


class TypebotListMembers(_Workspace):
    """List workspace members."""
    operation: Literal["list_workspace_members"] = Field("list_workspace_members", json_schema_extra={"ui:hidden": True})


class TypebotListInvitations(_Workspace):
    """List workspace invitations."""
    operation: Literal["list_workspace_invitations"] = Field("list_workspace_invitations", json_schema_extra={"ui:hidden": True})


class TypebotListTypebots(_Workspace):
    """List typebots."""
    operation: Literal["list_typebots"] = Field("list_typebots", json_schema_extra={"ui:hidden": True})
    folder_id: str | None = None


class TypebotGetTypebot(_Bot):
    """Get typebot."""
    operation: Literal["get_typebot"] = Field("get_typebot", json_schema_extra={"ui:hidden": True})


class TypebotCreateTypebot(_Workspace):
    """Create typebot."""
    operation: Literal["create_typebot"] = Field("create_typebot", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    folder_id: str | None = None


class TypebotUpdateTypebot(_Bot):
    """Update typebot."""
    operation: Literal["update_typebot"] = Field("update_typebot", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description="Rename the bot without replacing its flow.")


class TypebotDeleteTypebot(_Bot):
    """Delete typebot."""
    operation: Literal["delete_typebot"] = Field("delete_typebot", json_schema_extra={"ui:hidden": True})


class TypebotPublishTypebot(_Bot):
    """Publish typebot."""
    operation: Literal["publish_typebot"] = Field("publish_typebot", json_schema_extra={"ui:hidden": True})


class TypebotUnpublishTypebot(_Bot):
    """Unpublish typebot."""
    operation: Literal["unpublish_typebot"] = Field("unpublish_typebot", json_schema_extra={"ui:hidden": True})


class TypebotGetPublishedTypebot(_Bot):
    """Get published typebot."""
    operation: Literal["get_published_typebot"] = Field("get_published_typebot", json_schema_extra={"ui:hidden": True})


class TypebotListResults(_TimeFilter):
    """List results."""
    operation: Literal["list_results"] = Field("list_results", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=500, description="One page only; pass nextCursor back as cursor.")
    cursor: int | None = Field(None, description="Numeric nextCursor returned by the previous page.")


class TypebotGetResult(_Result):
    """Get result."""
    operation: Literal["get_result"] = Field("get_result", json_schema_extra={"ui:hidden": True})


class TypebotGetTranscript(_Result):
    """Get result transcript."""
    operation: Literal["get_result_transcript"] = Field("get_result_transcript", json_schema_extra={"ui:hidden": True})


class TypebotListLogs(_Result):
    """List result logs."""
    operation: Literal["list_result_logs"] = Field("list_result_logs", json_schema_extra={"ui:hidden": True})


class TypebotGetStats(_TimeFilter):
    """Get analytics stats."""
    operation: Literal["get_analytics_stats"] = Field("get_analytics_stats", json_schema_extra={"ui:hidden": True})


class TypebotGetInDepthAnalytics(_TimeFilter):
    """Get in depth analytics."""
    operation: Literal["get_in_depth_analytics"] = Field("get_in_depth_analytics", json_schema_extra={"ui:hidden": True})


class TypebotListFolders(_Workspace):
    """List folders."""
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"ui:hidden": True})
    parent_folder_id: str | None = None


class TypebotGetFolder(_Folder):
    """Get folder."""
    operation: Literal["get_folder"] = Field("get_folder", json_schema_extra={"ui:hidden": True})


class TypebotCreateFolder(_Workspace):
    """Create folder."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    parent_folder_id: str | None = None


class TypebotUpdateFolder(_Folder):
    """Update folder."""
    operation: Literal["update_folder"] = Field("update_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class TypebotDeleteFolder(_Folder):
    """Delete folder."""
    operation: Literal["delete_folder"] = Field("delete_folder", json_schema_extra={"ui:hidden": True})


TypebotConfig = Annotated[Union[
    TypebotListWorkspaces,
    TypebotCreateWorkspace,
    TypebotGetWorkspace,
    TypebotUpdateWorkspace,
    TypebotListMembers,
    TypebotListInvitations,
    TypebotListTypebots,
    TypebotGetTypebot,
    TypebotCreateTypebot,
    TypebotUpdateTypebot,
    TypebotDeleteTypebot,
    TypebotPublishTypebot,
    TypebotUnpublishTypebot,
    TypebotGetPublishedTypebot,
    TypebotListResults,
    TypebotGetResult,
    TypebotGetTranscript,
    TypebotListLogs,
    TypebotGetStats,
    TypebotGetInDepthAnalytics,
    TypebotListFolders,
    TypebotGetFolder,
    TypebotCreateFolder,
    TypebotUpdateFolder,
    TypebotDeleteFolder,
], Field(discriminator="operation")]


class TypebotFullConfig(NodeConfig[TypebotConfig, TypebotAPITokenCredential]):
    pass


OPERATIONS = {
    'list_workspaces': ('GET', '/v1/workspaces', {}, None, {'workspaces': 'list'}),
    'create_workspace': ('POST', '/v1/workspaces', {}, {'name': 'name', 'icon': 'icon'}, {'workspace': 'dict'}),
    'get_workspace': ('GET', '/v1/workspaces/{workspace_id}', {}, None, {'workspace': 'dict'}),
    'update_workspace': ('PATCH', '/v1/workspaces/{workspace_id}', {}, {'name': 'name', 'icon': 'icon'}, {'workspace': 'dict'}),
    'list_workspace_members': ('GET', '/v1/workspaces/{workspace_id}/members', {}, None, {'members': 'list'}),
    'list_workspace_invitations': ('GET', '/v1/workspaces/{workspace_id}/invitations', {}, None, {'invitations': 'list'}),
    'list_typebots': ('GET', '/v1/typebots', {'workspace_id': 'workspaceId', 'folder_id': 'folderId'}, None, {'typebots': 'list'}),
    'get_typebot': ('GET', '/v1/typebots/{typebot_id}', {}, None, {'typebot': 'dict'}),
    'create_typebot': ('POST', '/v1/typebots', {}, 'create_typebot', {'typebot': 'dict'}),
    'update_typebot': ('PATCH', '/v1/typebots/{typebot_id}', {}, 'update_typebot', {'typebot': 'dict'}),
    'delete_typebot': ('DELETE', '/v1/typebots/{typebot_id}', {}, None, {'message': 'str'}),
    'publish_typebot': ('POST', '/v1/typebots/{typebot_id}/publish', {}, None, {'message': 'str'}),
    'unpublish_typebot': ('POST', '/v1/typebots/{typebot_id}/unpublish', {}, None, {'message': 'str'}),
    'get_published_typebot': ('GET', '/v1/typebots/{typebot_id}/publishedTypebot', {}, None, {}),
    'list_results': ('GET', '/v1/typebots/{typebot_id}/results', {'limit': 'limit', 'cursor': 'cursor', 'time_filter': 'timeFilter', 'time_zone': 'timeZone'}, None, {'results': 'list'}),
    'get_result': ('GET', '/v1/typebots/{typebot_id}/results/{result_id}', {}, None, {'result': 'dict'}),
    'get_result_transcript': ('GET', '/v1/typebots/{typebot_id}/results/{result_id}/transcript', {}, None, {'transcript': 'list'}),
    'list_result_logs': ('GET', '/v1/typebots/{typebot_id}/results/{result_id}/logs', {}, None, {'logs': 'list'}),
    'get_analytics_stats': ('GET', '/v1/typebots/{typebot_id}/analytics/stats', {'time_filter': 'timeFilter', 'time_zone': 'timeZone'}, None, {'stats': 'dict'}),
    'get_in_depth_analytics': ('GET', '/v1/typebots/{typebot_id}/analytics/inDepthData', {'time_filter': 'timeFilter', 'time_zone': 'timeZone'}, None, {'totalAnswers': 'list', 'offDefaultPathVisitedEdges': 'list'}),
    'list_folders': ('GET', '/v1/folders', {'workspace_id': 'workspaceId', 'parent_folder_id': 'parentFolderId'}, None, {'folders': 'list'}),
    'get_folder': ('GET', '/v1/folders/{folder_id}', {'workspace_id': 'workspaceId'}, None, {'folder': 'dict'}),
    'create_folder': ('POST', '/v1/folders', {}, {'workspace_id': 'workspaceId', 'name': 'folderName', 'parent_folder_id': 'parentFolderId'}, {'folder': 'dict'}),
    'update_folder': ('PATCH', '/v1/folders/{folder_id}', {}, 'update_folder', {'folder': 'dict'}),
    'delete_folder': ('DELETE', '/v1/folders/{folder_id}', {}, {'workspace_id': 'workspaceId'}, {'folder': 'dict'}),
}


class TypebotNode(WorkflowNode):
    integration_type = "automation-typebot"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces")

    @classmethod
    def get_config_model(cls):
        return TypebotFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Typebot API token")
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        method, template, query_fields, body_fields, expected = OPERATIONS[config.operation]
        path = template.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {target: values[source] for source, target in query_fields.items() if source in values}
        body = None
        if isinstance(body_fields, dict):
            body = {target: values[source] for source, target in body_fields.items() if source in values}
        elif body_fields == "create_typebot":
            body = {"workspaceId": config.workspace_id, "typebot": {"name": config.name}}
            if config.folder_id is not None:
                body["typebot"]["folderId"] = config.folder_id
        elif body_fields == "update_typebot":
            body = {"typebot": {"name": config.name}}
        elif body_fields == "update_folder":
            body = {"workspaceId": config.workspace_id, "folder": {"name": config.name}}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "Typebot request did not complete; check the provider before retrying writes."}
        if not 200 <= response.status_code < 300:
            # Preserve definitive rejection text for connection evidence, redacting the secret.
            message = response.text.replace(credential.api_token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": message or "Typebot rejected the request"}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "error": "Typebot returned a non-JSON response"}
        types = {"dict": dict, "list": list, "str": str}
        if not isinstance(payload, dict) or any(not isinstance(payload.get(key), types[kind]) for key, kind in expected.items()):
            return {"status": "error", "error": "Typebot returned an unexpected response shape"}
        if "message" in expected and payload["message"] != "success":
            return {"status": "error", "error": "Typebot did not acknowledge the operation"}
        if config.operation == "get_published_typebot" and ("publishedTypebot" not in payload or (payload["publishedTypebot"] is not None and not isinstance(payload["publishedTypebot"], dict))):
            return {"status": "error", "error": "Typebot returned an unexpected published bot shape"}
        return {**payload, "status": "success"}
