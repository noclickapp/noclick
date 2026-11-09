"""Turbot Pipes v0 organization workspace automation, pinned to API 1.25.2.

Each action makes one documented request. Lists expose the provider cursor so
workflows can explicitly fetch another page; mutations are never retried.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://pipes.turbot.com/api/v0"
FAMILY = "turbot_pipes_api_token"


class TurbotPipesAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Turbot Pipes API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://turbot.com/pipes/docs/accounts/developer/advanced#tokens",
            "x-credential-instructions": "In Turbot Pipes, open Your Profile → Advanced → Credentials & Access and click New Token. Paste the token without the Bearer prefix. The token must have access to the organization workspaces you choose. NoClick checks your own workspace list; this does not prove permission to write every resource.",
        })
    credential_type: Literal["turbot_pipes_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(25, ge=1, le=100, description="Items per page. This action returns one page only.")
    next_token: str | None = Field(None, max_length=8192, description="Copy next_token from the preceding page using the same account and filters.")


class _Org(_Input):
    org_handle: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,37}[a-z0-9]$", title="Organization Handle")


class _Workspace(_Org):
    workspace_handle: str = Field(..., pattern=r"^[a-z0-9]{1,23}$", title="Workspace Handle")


class _Connection(_Workspace):
    connection_handle: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,37}[a-z0-9]?$", title="Connection Handle")


class _Snapshot(_Workspace):
    snapshot_id: str = Field(..., pattern=r"^snap_[0-9a-v]{20}_[0-9a-z]{19,26}$", title="Snapshot ID")


class _Schema(_Workspace):
    schema_name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,37}[a-z0-9]?$", title="Schema Name")


class _WorkspaceSettings(_Input):
    desired_state: Literal["enabled", "disabled"] | None = None
    instance_type: Literal["db1.shared", "db1.small", "db1.medium"] | None = None
    db_volume_size_bytes: int | None = Field(None, ge=1)


class GetActor(_Input):
    """Read the identity represented by this token."""
    operation: Literal["get_actor"] = "get_actor"


class ListWorkspaces(_Page):
    """List workspaces accessible to this actor across identities."""
    operation: Literal["list_workspaces"] = "list_workspaces"


class ListOrganizations(_Page):
    operation: Literal["list_organizations"] = "list_organizations"


class ListOrgWorkspaces(_Org, _Page):
    operation: Literal["list_org_workspaces"] = "list_org_workspaces"


class GetWorkspace(_Workspace):
    operation: Literal["get_workspace"] = "get_workspace"


class CreateWorkspace(_Org, _WorkspaceSettings):
    """Provision an organization workspace; provider compute/storage charges may apply."""
    operation: Literal["create_workspace"] = "create_workspace"
    handle: str = Field(..., pattern=r"^[a-z0-9]{1,23}$", title="New Workspace Handle")


class UpdateWorkspace(_Workspace, _WorkspaceSettings):
    """Change workspace capacity or enabled state; provider charges may change."""
    operation: Literal["update_workspace"] = "update_workspace"

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in _WorkspaceSettings.model_fields):
            raise ValueError("Choose at least one workspace setting to update")
        return self


class ListConnections(_Workspace, _Page):
    operation: Literal["list_connections"] = "list_connections"


class GetConnection(_Connection):
    operation: Literal["get_connection"] = "get_connection"


class CreateConnection(_Workspace):
    """Create a plugin connection; its configuration is omitted from output."""
    operation: Literal["create_connection"] = "create_connection"
    handle: str = Field(..., max_length=39, pattern=r"^[a-z](?:[a-z0-9]|_[a-z0-9])*$")
    plugin: str = Field(..., min_length=1, max_length=256, description="Plugin name, for example aws.")
    plugin_config_json: str = Field("{}", max_length=100000, title="Plugin Configuration (JSON)",
        description="Plugin-specific configuration object. Store sensitive values in workflow secrets.",
        json_schema_extra={"ui:widget": "code_editor"})

    @field_validator("plugin_config_json")
    @classmethod
    def object_json(cls, value):
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError()
        except (ValueError, RecursionError):
            raise ValueError("Plugin configuration must be a JSON object") from None
        return value


class DeleteConnection(_Connection):
    """Delete this workspace connection."""
    operation: Literal["delete_connection"] = "delete_connection"


class QueryWorkspace(_Workspace):
    """Run SQL against the workspace and return JSON results, including partial results."""
    operation: Literal["query_workspace"] = "query_workspace"
    sql: str = Field(..., min_length=1, max_length=100000, title="SQL", json_schema_extra={"ui:widget": "code_editor"})


class ListSnapshots(_Workspace, _Page):
    operation: Literal["list_snapshots"] = "list_snapshots"
    where: str | None = Field(None, max_length=10000, description="Pipes query filter, for example dashboard_name='aws_insights.dashboard.aws_account_report'.")


class GetSnapshot(_Snapshot):
    operation: Literal["get_snapshot"] = "get_snapshot"


class UpdateSnapshot(_Snapshot):
    operation: Literal["update_snapshot"] = "update_snapshot"
    title: str | None = Field(None, min_length=1, max_length=1000)
    visibility: Literal["workspace", "anyone_with_link"] | None = Field(None,
        description="anyone_with_link makes the snapshot accessible to anyone holding its link.")

    @model_validator(mode="after")
    def changes(self):
        if self.title is None and self.visibility is None:
            raise ValueError("Provide a title or visibility to update")
        return self


class DeleteSnapshot(_Snapshot):
    operation: Literal["delete_snapshot"] = "delete_snapshot"


class ListSchemas(_Workspace, _Page):
    operation: Literal["list_schemas"] = "list_schemas"


class GetSchema(_Schema):
    operation: Literal["get_schema"] = "get_schema"


class ListTables(_Schema):
    operation: Literal["list_tables"] = "list_tables"


class GetTable(_Schema):
    operation: Literal["get_table"] = "get_table"
    table_name: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


TurbotPipesConfig = Annotated[Union[
    GetActor, ListWorkspaces, ListOrganizations, ListOrgWorkspaces, GetWorkspace,
    CreateWorkspace, UpdateWorkspace, ListConnections, GetConnection,
    CreateConnection, DeleteConnection, QueryWorkspace, ListSnapshots,
    GetSnapshot, UpdateSnapshot, DeleteSnapshot, ListSchemas, GetSchema,
    ListTables, GetTable,
], Field(discriminator="operation")]


class TurbotPipesNodeConfig(NodeConfig[TurbotPipesConfig, TurbotPipesAPITokenCredential]):
    pass


def _redact(value, token):
    # Connection configuration and embedded user tokens never belong in output.
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()
                if k.lower() not in {"config", "tokens", "token", "api_token", "access_token", "refresh_token", "password", "secret"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value


class TurbotPipesNode(WorkflowNode):
    integration_type = "automation-turbot-pipes"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces",
        identity_operation="get_actor", label_keys=("handle", "display_name", "id"))

    @classmethod
    def get_config_model(cls):
        return TurbotPipesNodeConfig

    @staticmethod
    def _request_parts(op):
        """Bind each operation to exactly one published endpoint."""
        action = op.operation
        actor = {"get_actor": "/actor", "list_workspaces": "/actor/workspace", "list_organizations": "/actor/org"}
        method, body, params = "GET", None, {}
        if action in actor:
            path = actor[action]
        else:
            path = "/org/" + quote(op.org_handle, safe="") + "/workspace"
            if action not in {"list_org_workspaces", "create_workspace"}:
                path += "/" + quote(op.workspace_handle, safe="")
            if "connection" in action:
                path += "/connection"
                if action in {"get_connection", "delete_connection"}:
                    path += "/" + quote(op.connection_handle, safe="")
            elif "snapshot" in action:
                path += "/snapshot"
                if action != "list_snapshots":
                    path += "/" + quote(op.snapshot_id, safe="")
            elif action == "query_workspace":
                path += "/query"
                params = {"sql": op.sql}
            elif action in {"list_schemas", "get_schema", "list_tables", "get_table"}:
                path += "/schema"
                if action != "list_schemas":
                    path += "/" + quote(op.schema_name, safe="")
                if action in {"list_tables", "get_table"}:
                    path += "/table"
                if action == "get_table":
                    path += "/" + quote(op.table_name, safe="")
        if action.startswith("list_") and hasattr(op, "limit"):
            params = {"limit": op.limit}
            if op.next_token:
                params["next_token"] = op.next_token
            if getattr(op, "where", None):
                params["where"] = op.where
        if action in {"create_workspace", "update_workspace"}:
            method = "POST" if action == "create_workspace" else "PATCH"
            body = {k: getattr(op, k) for k in _WorkspaceSettings.model_fields if getattr(op, k) is not None}
            if action == "create_workspace":
                body["handle"] = op.handle
        elif action == "create_connection":
            method = "POST"
            body = {"handle": op.handle, "plugin": op.plugin, "config": json.loads(op.plugin_config_json)}
        elif action == "update_snapshot":
            method = "PATCH"
            body = {k: getattr(op, k) for k in ("title", "visibility") if getattr(op, k) is not None}
        elif action.startswith("delete_"):
            method = "DELETE"
        return method, path, params, body

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Turbot Pipes API token")
        op, token = self.config.config, self.config.credentials.api_token
        method, path, params, body = self._request_parts(op)
        writing = method != "GET"
        try:
            async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=60) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        except (httpx.HTTPError, OSError):
            output = {"status": "error", "message": "Turbot Pipes request could not be completed",
                      "write_outcome": "unknown" if writing else None}
        else:
            if not 200 <= response.status_code < 300:
                try:
                    error = response.json()
                    message = error.get("detail") or error.get("title") if isinstance(error, dict) else None
                except ValueError:
                    message = None
                output = {"status": "error", "http_status": response.status_code, "status_code": response.status_code,
                    "message": message if isinstance(message, str) else "Turbot Pipes returned HTTP " + str(response.status_code),
                    "write_outcome": "unknown" if writing and response.status_code >= 500 else None}
            else:
                output = self._output(op, response, writing)
        output = _redact(output, token)
        await self.emit(output)
        return output

    @staticmethod
    def _output(op, response, writing):
        common = {"status": "success", "operation": op.operation, "http_status": response.status_code}
        if response.status_code == 204 and op.operation.startswith("delete_"):
            return {**common, "deletion_acknowledged": True}
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            if isinstance(data.get("status"), int) and data["status"] >= 400:
                return {"status": "error", "http_status": response.status_code,
                        "message": data.get("detail") or data.get("title") or "Turbot Pipes reported an API error",
                        "write_outcome": "unknown" if writing else None}
            if op.operation.startswith("list_"):
                items = data.get("items")
                if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                    raise ValueError()
                cursor = data.get("next_token") or None
                if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 8192):
                    raise ValueError()
                return {**common, "items": items, "next_token": cursor, "has_more": cursor is not None}
            if op.operation == "get_actor":
                if not isinstance(data.get("id"), str) or not isinstance(data.get("handle"), str):
                    raise ValueError()
                data = {k: data[k] for k in ("id", "handle", "display_name", "type") if k in data}
            return {**common, "data": data, "partial": response.status_code == 206,
                    **({"deletion_acknowledged": True} if op.operation.startswith("delete_") else {})}
        except (ValueError, RecursionError):
            return {"status": "error", "http_status": response.status_code,
                    "message": "Turbot Pipes returned an unexpected JSON response",
                    "write_outcome": "unknown" if writing else None}
