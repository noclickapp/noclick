"""Hive REST API v2, pinned to the provider's 2.0.0 contract.

Actions issue one request and expose pagination for the caller. Scheduled
triggers page through a bounded workspace scope before detecting changed records.
"""
from __future__ import annotations
import hashlib
import json
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://app.hive.com/api/v2"

class HiveAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hive API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://help.hive.com/en/articles/5407965-getting-started-with-the-hive-api",
        "x-credential-instructions": "In Hive, open your avatar, My profile, then API info. Paste your API key. Requests run with the key owner's permissions."})
    credential_type: Literal["hive_api_key"] = Field("hive_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not value.strip() or len(value) > 256 or any(c in value for c in "/\\?#%") or any(ord(c) < 33 for c in value):
                raise ValueError("Use a single Hive resource ID")
        return value

class _Page(_Input):
    first: int = Field(25, ge=1, le=200, description="Page size. Pass endCursor back as after for the next page.")
    after: str | None = Field(None, max_length=8192, description="Opaque endCursor from the previous page.")

class _Workspace(_Input):
    workspace_id: str = Field(..., min_length=1, description="Hive workspace ID from API info or list workspaces.")

class _WorkspacePage(_Page, _Workspace):
    pass

class _Action(_Input):
    action_id: str = Field(..., min_length=1, description="Hive action ID.")

class _ActionPage(_Page, _Action):
    pass

class _Project(_Input):
    project_id: str = Field(..., min_length=1, description="Hive project ID.")

class HiveListWorkspacesConfig(_Page):
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})

class HiveListProjectsConfig(_Input):
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})

class HiveListWorkspaceProjectsConfig(_WorkspacePage):
    operation: Literal["list_workspace_projects"] = Field("list_workspace_projects", json_schema_extra={"ui:hidden": True})

class HiveGetProjectConfig(_Project):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})

class HiveDeleteProjectConfig(_Project):
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})

class HiveListActionsConfig(_WorkspacePage):
    operation: Literal["list_actions"] = Field("list_actions", json_schema_extra={"ui:hidden": True})

class HiveSearchActionsConfig(_Workspace):
    operation: Literal["search_actions"] = Field("search_actions", json_schema_extra={"ui:hidden": True})
    search_term: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(20, ge=1, le=200)
    skip: int = Field(0, ge=0)
    project_id: str | None = None

class HiveGetActionConfig(_Action):
    operation: Literal["get_action"] = Field("get_action", json_schema_extra={"ui:hidden": True})

class HiveCreateActionConfig(_Input):
    operation: Literal["create_action"] = Field("create_action", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=10000)
    workspace: str | None = None
    project_id: str | None = None
    description: str | None = Field(None, max_length=100000)
    assignees: list[str] | None = Field(None, max_length=1000)

class HiveUpdateActionConfig(_Action):
    operation: Literal["update_action"] = Field("update_action", json_schema_extra={"ui:hidden": True})
    title: str | None = Field(None, min_length=1, max_length=10000)
    status: str | None = None
    description: str | None = Field(None, max_length=100000)
    assignees: list[str] | None = Field(None, max_length=1000)
    project_id: str | None = None

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, k) is not None for k in ("title", "status", "description", "assignees", "project_id")):
            raise ValueError("Supply at least one action field to update")
        return self

class HiveDeleteActionConfig(_Action):
    operation: Literal["delete_action"] = Field("delete_action", json_schema_extra={"ui:hidden": True})

class HiveListCommentsConfig(_ActionPage):
    operation: Literal["list_comments"] = Field("list_comments", json_schema_extra={"ui:hidden": True})

class HiveCreateCommentConfig(_Action):
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, max_length=100000, description="Comment text posted to the action.")

class HiveListSubactionsConfig(_ActionPage):
    operation: Literal["list_subactions"] = Field("list_subactions", json_schema_extra={"ui:hidden": True})

class HiveListActionHistoryConfig(_ActionPage):
    operation: Literal["list_action_history"] = Field("list_action_history", json_schema_extra={"ui:hidden": True})

class HiveListLabelsConfig(_WorkspacePage):
    operation: Literal["list_labels"] = Field("list_labels", json_schema_extra={"ui:hidden": True})

class HiveCreateLabelConfig(_Workspace):
    operation: Literal["create_label"] = Field("create_label", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    color: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$", description="Hex color such as #3390dc.")
    parent: str | None = None

class HiveListMembersConfig(_WorkspacePage):
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"ui:hidden": True})

class HiveOnActionChangedConfig(PollTriggerConfigBase, _Workspace):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_new_or_updated_action"] = Field("on_new_or_updated_action", title="On New or Updated Action",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
                           "x-display-name": "On New or Updated Action"})
    project_id: str | None = Field(None, title="Project ID", description="Optionally watch actions in one project.")


class HiveOnProjectChangedConfig(PollTriggerConfigBase, _Workspace):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_new_or_updated_project"] = Field("on_new_or_updated_project", title="On New or Updated Project",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
                           "x-display-name": "On New or Updated Project"})


# Hive's own MCP server: agents get its tools through a person's Hive sign-in.
HiveMcpCredential = mcp_credential("hive", "https://hive-mind.hive.com/mcp", app="Hive")
HiveCredential = Union[HiveAPIKeyCredential, HiveMcpCredential]


HiveConfig = Annotated[Union[HiveOnActionChangedConfig, HiveOnProjectChangedConfig, HiveListWorkspacesConfig, HiveListProjectsConfig, HiveListWorkspaceProjectsConfig, HiveGetProjectConfig, HiveDeleteProjectConfig, HiveListActionsConfig, HiveSearchActionsConfig, HiveGetActionConfig, HiveCreateActionConfig, HiveUpdateActionConfig, HiveDeleteActionConfig, HiveListCommentsConfig, HiveCreateCommentConfig, HiveListSubactionsConfig, HiveListActionHistoryConfig, HiveListLabelsConfig, HiveCreateLabelConfig, HiveListMembersConfig], Field(discriminator="operation")]

class HiveFullConfig(NodeConfig[HiveConfig, HiveCredential]):
    pass

ROUTES = {'list_workspaces': ('GET', '/workspaces', 'page'),
 'list_projects': ('GET', '/projects', 'array'),
 'list_workspace_projects': ('GET', '/workspaces/{workspace_id}/projects', 'page'),
 'get_project': ('GET', '/projects/{project_id}', 'object'),
 'delete_project': ('DELETE', '/projects/{project_id}', 'object'),
 'list_actions': ('GET', '/workspaces/{workspace_id}/actions', 'page'),
 'search_actions': ('GET', '/workspaces/{workspace_id}/actions/search', 'array'),
 'get_action': ('GET', '/actions/{action_id}', 'object'),
 'create_action': ('POST', '/actions', 'object'),
 'update_action': ('PUT', '/actions/{action_id}', 'object'),
 'delete_action': ('DELETE', '/actions/{action_id}', 'object'),
 'list_comments': ('GET', '/actions/{action_id}/comments', 'page'),
 'create_comment': ('POST', '/actions/{action_id}/comments', 'object'),
 'list_subactions': ('GET', '/actions/{action_id}/subactions', 'page'),
 'list_action_history': ('GET', '/actions/{action_id}/action-history', 'page'),
 'list_labels': ('GET', '/workspaces/{workspace_id}/labels', 'page'),
 'create_label': ('POST', '/workspaces/{workspace_id}/labels', 'object'),
 'list_members': ('GET', '/workspaces/{workspace_id}/users', 'page')}

class HiveNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-hive"
    credential_provider_labels = {"hive": "Hive Account"}
    connection_evidence = ConnectionEvidence(noun="Hive workspaces", operation="list_workspaces")

    @classmethod
    def get_config_model(cls):
        return HiveFullConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_or_updated_action", "on_new_or_updated_project"}:
            return bool(output.get("new_or_updated_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "new_or_updated_count" not in output:
            return super().resolve_agent_event(output)
        items = output.get("items")
        if not items:
            return None
        # ConnectionResponse deliberately leaves node fields open. Preserve the
        # entire resource, including its IDs/content, without guessing its shape.
        text = (f"Hive: {len(items)} new or updated {output['resource']} record(s) "
                f"in workspace {output['workspace_id']}.\n"
                + json.dumps(items, ensure_ascii=False, indent=2))
        return {"text": text, "conversation_key": None}

    async def _poll_changes(self, config):
        resource = "action" if isinstance(config, HiveOnActionChangedConfig) else "project"
        path = f"/workspaces/{quote(config.workspace_id, safe='')}/{resource}s"
        params = {"first": 200, "sortBy": "modifiedAt desc"}
        if isinstance(config, HiveOnActionChangedConfig) and config.project_id:
            params["projectId"] = config.project_id
        items, cursors = [], set()
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            for _ in range(10):
                response = await client.request("GET", BASE + path, params=params,
                    headers={"api_key": self.config.credentials.api_key, "Accept": "application/json"})
                if response.status_code >= 300:
                    raise ValueError("Hive polling request failed")
                if "json" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Expected a JSON response")
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("edges"), list) or not isinstance(body.get("pageInfo"), dict):
                    raise ValueError("Expected a Hive cursor page")
                for edge in body["edges"]:
                    if not isinstance(edge, dict) or not isinstance(edge.get("node"), dict):
                        raise ValueError("Expected Hive resource edges")
                    items.append(edge["node"])
                page = body["pageInfo"]
                if not page.get("hasNextPage"):
                    break
                cursor = page.get("endCursor")
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise ValueError("Hive returned an invalid pagination cursor")
                cursors.add(cursor)
                params["after"] = cursor
            else:
                raise ValueError("Hive scope exceeds 2,000 records; narrow the watched workspace or project")
        # A content fingerprint detects creations and edits without assuming an
        # undocumented resource ID/timestamp field in the open node schema.
        fresh = await self._filter_unseen(items, lambda item: hashlib.sha256(
            json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
        return {"status": "success", "items": fresh, "new_or_updated_count": len(fresh),
                "resource": resource, "workspace_id": config.workspace_id}

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Hive API key")
        config = self.config.config
        if isinstance(config, (HiveOnActionChangedConfig, HiveOnProjectChangedConfig)):
            try:
                return await self._poll_changes(config)
            except (httpx.HTTPError, SSRFError):
                return {"status": "error", "error": "Hive polling request could not be completed"}
            except (ValueError, TypeError) as exc:
                return {"status": "error", "error": str(exc) if "scope exceeds" in str(exc) else "Hive returned an invalid polling response"}
        method, path, kind = ROUTES[config.operation]
        data = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("workspace_id", "action_id", "project_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(data.pop(field), safe=""))
        mapped = {"project_id": "projectId", "search_term": "searchTerm"}
        data = {mapped.get(k, k): v for k, v in data.items()}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"api_key": self.config.credentials.api_key, "Accept": "application/json"},
                    **({"params": data} if method == "GET" else {"json": data} if method in {"POST", "PUT"} else {}))
            if response.status_code >= 300:
                try:
                    message = response.json().get("message", "Hive request failed")
                except (ValueError, AttributeError):
                    message = "Hive returned an unexpected error response"
                message = str(message).replace(self.config.credentials.api_key, "[redacted]")[:2000]
                return {"status": "error", "error": message, "http_status": response.status_code}
            if "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected a JSON response")
            body = response.json()
            if isinstance(body, dict) and body.get("error"):
                return {"status": "error", "error": str(body.get("message", "Hive request failed")).replace(self.config.credentials.api_key, "[redacted]")[:2000]}
            if kind == "page":
                if not isinstance(body, dict) or not isinstance(body.get("edges"), list) or not isinstance(body.get("pageInfo"), dict):
                    raise ValueError("Expected a Hive cursor page")
                if any(not isinstance(edge, dict) or not isinstance(edge.get("node"), dict) for edge in body["edges"]):
                    raise ValueError("Expected Hive resource edges")
                page = body["pageInfo"]
                return {"status": "success", "items": [edge["node"] for edge in body["edges"]],
                    "page_info": page, "next_cursor": page.get("endCursor") if page.get("hasNextPage") else None}
            if kind == "array":
                if not isinstance(body, list) or any(not isinstance(item, dict) for item in body):
                    raise ValueError("Expected a Hive resource list")
                return {"status": "success", "items": body}
            if not isinstance(body, dict):
                raise ValueError("Expected a Hive resource or confirmation")
            return {"status": "success", "data": body}
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "Hive request could not be completed"}
        except (ValueError, TypeError):
            return {"status": "error", "error": "Hive returned an unexpected JSON response"}
