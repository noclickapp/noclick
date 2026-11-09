"""Conductor cloud workspace and coding-session operations using a pasted API key.

Each action makes one documented API request. Writes are never retried; queued
messages and asynchronous cancellations retain the provider's acknowledgment.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.conductor.build"


class ConductorAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Conductor API Key",
        json_schema_extra={
            "x-credential-url": "https://app.conductor.build/home/api-keys",
            "x-credential-instructions": "Create a user API key in Conductor, then paste it here without the Bearer prefix. Your Conductor account needs access to cloud workspaces and the projects you automate. NoClick checks the account with GET /me; individual project and write permissions may differ.",
        })
    credential_type: Literal["conductor_api_key"] = Field("conductor_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Conductor API key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            if value in {".", ".."} or any(ord(c) < 33 or c in "/\\?#%" for c in value):
                raise ValueError("Use a single Conductor resource ID")
        return value


class _Page(_Input):
    limit: int = Field(50, ge=1, le=200, description="Number of records in this page. NoClick returns one page per run.")
    offset: int = Field(0, ge=0, le=10000000, description="Use next_offset from the previous page.")


class ConductorGetIdentityConfig(_Input):
    """GET /me."""
    operation: Literal["get_identity"] = Field("get_identity", json_schema_extra={"ui:hidden": True})


class ConductorListProjectsConfig(_Page):
    """GET /v0/projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class ConductorGetProjectConfig(_Input):
    """GET /v0/projects/{project_id}."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., min_length=1, max_length=256)


class ConductorListProjectWorkspacesConfig(_Page):
    """GET /v0/projects/{project_id}/workspaces."""
    operation: Literal["list_project_workspaces"] = Field("list_project_workspaces", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., min_length=1, max_length=256)


class ConductorListWorkspacesConfig(_Page):
    """GET /v0/workspaces."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})
    creator: str | None = Field(None, min_length=1, max_length=1000)
    state: str | None = Field(None, min_length=1, max_length=1000)
    repo: str | None = Field(None, min_length=1, max_length=1000)
    name: str | None = Field(None, min_length=1, max_length=1000)
    include_archived: bool | None = None


class ConductorCreateWorkspaceConfig(_Input):
    """POST /v0/workspaces."""
    operation: Literal["create_workspace"] = Field("create_workspace", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., min_length=1, max_length=256)
    name: str | None = Field(None, min_length=1, max_length=500)
    message: str | None = Field(None, min_length=1, max_length=100000, description="Optional initial prompt. Inspect initialMessage before resending.")


class ConductorGetWorkspaceConfig(_Input):
    """GET /v0/workspaces/{workspace_id}."""
    operation: Literal["get_workspace"] = Field("get_workspace", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=256)


class ConductorRenameWorkspaceConfig(_Input):
    """POST /v0/workspaces/{workspace_id}/rename."""
    operation: Literal["rename_workspace"] = Field("rename_workspace", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=500)


class ConductorArchiveWorkspaceConfig(_Input):
    """POST /v0/workspaces/{workspace_id}/archive."""
    operation: Literal["archive_workspace"] = Field("archive_workspace", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=256)


class ConductorUnarchiveWorkspaceConfig(_Input):
    """POST /v0/workspaces/{workspace_id}/unarchive."""
    operation: Literal["unarchive_workspace"] = Field("unarchive_workspace", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=256)


class ConductorSleepWorkspaceConfig(_Input):
    """POST /v0/workspaces/{workspace_id}/sleep."""
    operation: Literal["sleep_workspace"] = Field("sleep_workspace", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=256)


class ConductorListSessionsConfig(_Page):
    """GET /v0/workspaces/{workspace_id}/sessions."""
    operation: Literal["list_sessions"] = Field("list_sessions", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=256)
    include_archived: bool | None = None


class ConductorCreateSessionConfig(_Input):
    """POST /v0/sessions."""
    operation: Literal["create_session"] = Field("create_session", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=256)
    agent: Literal["claude", "codex", "cursor", "acp"] = Field(..., description="Agent must already have credentials connected in Conductor; its default model is used.")
    name: str | None = Field(None, min_length=1, max_length=500)
    session_id: str | None = Field(None, min_length=1, max_length=256, description="Stable session ID for deduplicating a retried create.")
    message_id: UUID | None = Field(None, description="UUID for deduplicating an explicitly retried message. Reuse the same ID and text.")
    message: str | None = Field(None, min_length=1, max_length=100000, description="Optional initial prompt. Inspect initialMessage before resending.")


class ConductorGetSessionConfig(_Input):
    """GET /v0/sessions/{session_id}."""
    operation: Literal["get_session"] = Field("get_session", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., min_length=1, max_length=256)


class ConductorRenameSessionConfig(_Input):
    """POST /v0/sessions/{session_id}/rename."""
    operation: Literal["rename_session"] = Field("rename_session", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=500)


class ConductorArchiveSessionConfig(_Input):
    """POST /v0/sessions/{session_id}/archive."""
    operation: Literal["archive_session"] = Field("archive_session", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., min_length=1, max_length=256)


class ConductorUnarchiveSessionConfig(_Input):
    """POST /v0/sessions/{session_id}/unarchive."""
    operation: Literal["unarchive_session"] = Field("unarchive_session", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., min_length=1, max_length=256)


class ConductorListMessagesConfig(_Page):
    """GET /v0/sessions/{session_id}/messages."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., min_length=1, max_length=256)
    after: str | None = Field(None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def polling(self):
        if self.after is not None and self.offset != 0:
            raise ValueError("Use after or offset, not both")
        return self


class ConductorSendMessageConfig(_Input):
    """POST /v0/sessions/{session_id}/messages."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=100000, description="Prompt sent to the coding agent; may be queued while the workspace starts.")
    message_id: UUID | None = Field(None, description="UUID for deduplicating an explicitly retried message. Reuse the same ID and text.")


class ConductorGetMessageConfig(_Input):
    """GET /v0/messages/{message_id}."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})
    message_id: str = Field(..., min_length=1, max_length=256)


class ConductorGetWorkspaceStatusConfig(_Input):
    """GET /v0/workspaces/{workspace_id}/status."""
    operation: Literal["get_workspace_status"] = Field("get_workspace_status", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, max_length=256)


class ConductorGetSessionStatusConfig(_Input):
    """GET /v0/sessions/{session_id}/status."""
    operation: Literal["get_session_status"] = Field("get_session_status", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., min_length=1, max_length=256)


class ConductorCancelSessionConfig(_Input):
    """POST /v0/sessions/{session_id}/cancel."""
    operation: Literal["cancel_session"] = Field("cancel_session", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., min_length=1, max_length=256)


class ConductorListFavoriteModelsConfig(_Input):
    """GET /v0/favorite-models."""
    operation: Literal["list_favorite_models"] = Field("list_favorite_models", json_schema_extra={"ui:hidden": True})


ConductorConfig = Annotated[Union[
    ConductorGetIdentityConfig,
    ConductorListProjectsConfig,
    ConductorGetProjectConfig,
    ConductorListProjectWorkspacesConfig,
    ConductorListWorkspacesConfig,
    ConductorCreateWorkspaceConfig,
    ConductorGetWorkspaceConfig,
    ConductorRenameWorkspaceConfig,
    ConductorArchiveWorkspaceConfig,
    ConductorUnarchiveWorkspaceConfig,
    ConductorSleepWorkspaceConfig,
    ConductorListSessionsConfig,
    ConductorCreateSessionConfig,
    ConductorGetSessionConfig,
    ConductorRenameSessionConfig,
    ConductorArchiveSessionConfig,
    ConductorUnarchiveSessionConfig,
    ConductorListMessagesConfig,
    ConductorSendMessageConfig,
    ConductorGetMessageConfig,
    ConductorGetWorkspaceStatusConfig,
    ConductorGetSessionStatusConfig,
    ConductorCancelSessionConfig,
    ConductorListFavoriteModelsConfig
], Field(discriminator="operation")]


class ConductorFullConfig(NodeConfig[ConductorConfig, ConductorAPIKeyCredential]):
    pass


ROUTES = {'get_identity': ('GET', '/me'),
 'list_projects': ('GET', '/v0/projects'),
 'get_project': ('GET', '/v0/projects/{project_id}'),
 'list_project_workspaces': ('GET', '/v0/projects/{project_id}/workspaces'),
 'list_workspaces': ('GET', '/v0/workspaces'),
 'create_workspace': ('POST', '/v0/workspaces'),
 'get_workspace': ('GET', '/v0/workspaces/{workspace_id}'),
 'rename_workspace': ('POST', '/v0/workspaces/{workspace_id}/rename'),
 'archive_workspace': ('POST', '/v0/workspaces/{workspace_id}/archive'),
 'unarchive_workspace': ('POST', '/v0/workspaces/{workspace_id}/unarchive'),
 'sleep_workspace': ('POST', '/v0/workspaces/{workspace_id}/sleep'),
 'list_sessions': ('GET', '/v0/workspaces/{workspace_id}/sessions'),
 'create_session': ('POST', '/v0/sessions'),
 'get_session': ('GET', '/v0/sessions/{session_id}'),
 'rename_session': ('POST', '/v0/sessions/{session_id}/rename'),
 'archive_session': ('POST', '/v0/sessions/{session_id}/archive'),
 'unarchive_session': ('POST', '/v0/sessions/{session_id}/unarchive'),
 'list_messages': ('GET', '/v0/sessions/{session_id}/messages'),
 'send_message': ('POST', '/v0/sessions/{session_id}/messages'),
 'get_message': ('GET', '/v0/messages/{message_id}'),
 'get_workspace_status': ('GET', '/v0/workspaces/{workspace_id}/status'),
 'get_session_status': ('GET', '/v0/sessions/{session_id}/status'),
 'cancel_session': ('POST', '/v0/sessions/{session_id}/cancel'),
 'list_favorite_models': ('GET', '/v0/favorite-models')}
WIRE_FIELDS = {"project_id": "projectId", "workspace_id": "workspaceId", "session_id": "sessionId", "message_id": "messageId", "include_archived": "includeArchived"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class ConductorNode(WorkflowNode):
    integration_type = "automation-conductor"
    connection_evidence = ConnectionEvidence(
        noun="Conductor account", identity_operation="get_identity",
        identity_keys=("name", "email", "organizationName", "userId"),
    )

    @classmethod
    def get_config_model(cls):
        return ConductorFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Conductor API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in list(values):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(values.pop(name), safe=""))
        if config.operation == "list_messages" and values.get("after") is not None:
            values.pop("offset", None)
        wire = {WIRE_FIELDS.get(key, key): value for key, value in values.items()}
        kwargs = {"params": wire} if method == "GET" else {"json": wire} if wire else {}
        output = {"operation": config.operation}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers={
                    "Authorization": "Bearer " + secret, "Accept": "application/json",
                    "User-Agent": "NoClick-Conductor/1.0",
                }, **kwargs)
            if len(response.content) > 5000000:
                raise ValueError("Conductor response exceeded the size limit")
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime != "application/json":
                raise ValueError("Conductor returned a non-JSON response")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Conductor returned an unexpected JSON envelope")
            if not 200 <= response.status_code < 300:
                result = {**output, "status": "error", "status_code": response.status_code,
                    "error": body.get("userMessage") or body.get("message") or "Conductor request rejected",
                    "write_outcome": "unknown" if method != "GET" and response.status_code >= 500 else None}
            else:
                if config.operation == "get_identity" and (not isinstance(body.get("userId"), str) or not body["userId"] or not isinstance(body.get("authMethod"), str)):
                    raise ValueError("Conductor identity response was incomplete")
                page = {}
                if isinstance(config, _Page):
                    if not isinstance(body.get("data"), list) or type(body.get("hasMore")) is not bool or type(body.get("offset")) not in {int, float}:
                        raise ValueError("Conductor pagination response was incomplete")
                    page = {"has_more": body["hasMore"], "next_offset": body["offset"] + len(body["data"]) if body["hasMore"] else None}
                result = {**output, "status": "success", "status_code": response.status_code, "data": body, **page}
        except (ValueError, SSRFError, httpx.HTTPError):
            result = {**output, "status": "error", "error": "Conductor response could not be confirmed",
                "write_outcome": "unknown" if method != "GET" else None}
        result = _redact(result, secret)
        await self.emit(result)
        return result
