"""Rollbar error monitoring, project, team, and deploy automation.

The account access token needs read/write scope. Project operations can use a
separate project read/write token. Reporting errors and deploys requires a
project ``post_server_item`` token, whose scope cannot be combined with read/write.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


API_BASE = "https://api.rollbar.com/api/1"


class RollbarAccessTokenCredential(BaseModel):
    """Account token plus optional project read/write and reporting tokens."""

    credential_type: Literal["rollbar_access_token"] = Field(
        "rollbar_access_token", json_schema_extra={"ui:hidden": True}
    )
    account_access_token: str = Field(
        ..., title="Account Access Token (read/write)",
        description="Account token with read and write scopes. Required for account, project, team, and user operations.",
        json_schema_extra={"ui:widget": "password"},
    )
    project_read_write_token: Optional[str] = Field(
        None, title="Project Access Token (read/write)",
        description="Project token with read and write scopes. Used for item, occurrence, environment, and deploy operations on its project; otherwise the account token and Project ID are used.",
        json_schema_extra={"ui:widget": "password"},
    )
    project_post_server_token: Optional[str] = Field(
        None, title="Project Post Server Item Token",
        description="Separate project token with post_server_item scope. Required to report messages and deploys.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(json_schema_extra={
        "title": "Rollbar Access Token",
        "x-credential-url": "https://rollbar.com/settings/accounts/",
        "x-help-text": "Create an account read/write token in Account Settings → Account Access Tokens. Add a project read/write token for project data and a separate post_server_item token for reporting from Project Settings → Access Tokens.",
    })


def _op(name: str, category: str, display: str) -> Any:
    return Field(name, title=display, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-display-name": display, "x-is-trigger": False,
    })


def _id(title: str) -> Any:
    return Field(..., title=title)


class RollbarListProjectsConfig(BaseModel):
    operation: Literal["list_projects"] = _op("list_projects", "Projects", "List Projects")


class RollbarGetProjectConfig(BaseModel):
    operation: Literal["get_project"] = _op("get_project", "Projects", "Get Project")
    project_id: int = _id("Project ID")


class RollbarCreateProjectConfig(BaseModel):
    operation: Literal["create_project"] = _op("create_project", "Projects", "Create Project")
    name: str = Field(..., min_length=1, max_length=32, title="Project Name", description="Starts with a letter; up to 32 characters.")
    source_project_id: Optional[int] = Field(None, title="Source Project ID", description="Copy settings from this project.")


class RollbarDeleteProjectConfig(BaseModel):
    operation: Literal["delete_project"] = _op("delete_project", "Projects", "Delete Project")
    project_id: int = _id("Project ID")


class RollbarListTeamsConfig(BaseModel):
    operation: Literal["list_teams"] = _op("list_teams", "Teams", "List Teams")


class RollbarGetTeamConfig(BaseModel):
    operation: Literal["get_team"] = _op("get_team", "Teams", "Get Team")
    team_id: int = _id("Team ID")


class RollbarCreateTeamConfig(BaseModel):
    operation: Literal["create_team"] = _op("create_team", "Teams", "Create Team")
    name: str = _id("Team Name")
    access_level: Literal["standard", "light", "view"] = Field("standard", title="Access Level")


class RollbarListTeamUsersConfig(BaseModel):
    operation: Literal["list_team_users"] = _op("list_team_users", "Teams", "List Team Users")
    team_id: int = _id("Team ID")
    page: int = Field(1, ge=1, title="Page")


class RollbarListProjectTeamsConfig(BaseModel):
    operation: Literal["list_project_teams"] = _op("list_project_teams", "Teams", "List Project Teams")
    project_id: int = _id("Project ID")


class RollbarAssignTeamProjectConfig(BaseModel):
    operation: Literal["assign_team_project"] = _op("assign_team_project", "Teams", "Assign Team to Project")
    team_id: int = _id("Team ID")
    project_id: int = _id("Project ID")


class RollbarListUsersConfig(BaseModel):
    operation: Literal["list_users"] = _op("list_users", "Users", "List Users")
    email: Optional[str] = Field(None, title="Email Filter")


class RollbarGetUserConfig(BaseModel):
    operation: Literal["get_user"] = _op("get_user", "Users", "Get User")
    user_id: int = _id("User ID")


class RollbarListItemsConfig(BaseModel):
    operation: Literal["list_items"] = _op("list_items", "Errors", "List Items")
    project_id: int = _id("Project ID")
    status: Optional[Literal["active", "resolved", "muted"]] = Field(None, title="Status")
    level: Optional[Literal["critical", "error", "warning", "info", "debug"]] = Field(None, title="Level")
    environment: Optional[str] = Field(None, title="Environment")
    query: Optional[str] = Field(None, title="Search Query")
    page: int = Field(1, ge=1, title="Page")


class RollbarGetItemConfig(BaseModel):
    operation: Literal["get_item"] = _op("get_item", "Errors", "Get Item")
    project_id: int = _id("Project ID")
    item_id: int = _id("Item ID")


class RollbarUpdateItemConfig(BaseModel):
    operation: Literal["update_item"] = _op("update_item", "Errors", "Update Item")
    project_id: int = _id("Project ID")
    item_id: int = _id("Item ID")
    status: Optional[Literal["active", "resolved", "muted"]] = Field(None, title="Status")
    title: Optional[str] = Field(None, title="Title")
    level: Optional[Literal["critical", "error", "warning", "info", "debug"]] = Field(None, title="Level")
    resolved_in_version: Optional[str] = Field(None, title="Resolved in Version")


class RollbarListItemEventsConfig(BaseModel):
    operation: Literal["list_item_events"] = _op("list_item_events", "Errors", "List Item Events")
    project_id: int = _id("Project ID")
    item_id: int = _id("Item ID")
    page: int = Field(1, ge=1, title="Page")
    limit: int = Field(20, ge=1, le=100, title="Limit")


class RollbarListOccurrencesConfig(BaseModel):
    operation: Literal["list_occurrences"] = _op("list_occurrences", "Occurrences", "List Occurrences")
    project_id: int = _id("Project ID")
    page: int = Field(1, ge=1, title="Page")
    limit: int = Field(20, ge=1, le=5000, title="Limit")
    last_id: Optional[int] = Field(None, title="Last ID", description="Cursor for pagination.")


class RollbarGetOccurrenceConfig(BaseModel):
    operation: Literal["get_occurrence"] = _op("get_occurrence", "Occurrences", "Get Occurrence")
    project_id: int = _id("Project ID")
    occurrence_id: int = _id("Occurrence ID")


class RollbarListEnvironmentsConfig(BaseModel):
    operation: Literal["list_environments"] = _op("list_environments", "Projects", "List Environments")
    project_id: int = _id("Project ID")
    page: int = Field(1, ge=1, title="Page")
    limit: int = Field(20, ge=1, le=100, title="Limit")


class RollbarTopActiveItemsConfig(BaseModel):
    operation: Literal["top_active_items"] = _op("top_active_items", "Errors", "Top Active Items")
    project_id: int = _id("Project ID")
    hours: int = Field(24, ge=1, title="Hours")
    environments: Optional[str] = Field(None, title="Environments", description="Comma-separated environment names.")


class RollbarListDeploysConfig(BaseModel):
    operation: Literal["list_deploys"] = _op("list_deploys", "Deploys", "List Deploys")
    project_id: int = _id("Project ID")
    page: int = Field(1, ge=1, title="Page")
    limit: int = Field(20, ge=1, le=100, title="Limit")


class RollbarGetDeployConfig(BaseModel):
    operation: Literal["get_deploy"] = _op("get_deploy", "Deploys", "Get Deploy")
    project_id: int = _id("Project ID")
    deploy_id: int = _id("Deploy ID")


class RollbarReportMessageConfig(BaseModel):
    operation: Literal["report_message"] = _op("report_message", "Reporting", "Report Message")
    environment: str = Field(..., title="Environment")
    message: str = Field(..., title="Message", json_schema_extra={"ui:widget": "textarea"})
    level: Literal["critical", "error", "warning", "info", "debug"] = Field("error", title="Level")
    platform: str = Field("python", title="Platform")


class RollbarReportDeployConfig(BaseModel):
    operation: Literal["report_deploy"] = _op("report_deploy", "Reporting", "Report Deploy")
    environment: str = Field(..., title="Environment")
    revision: str = Field(..., title="Revision")


RollbarConfig = Annotated[Union[
    RollbarListProjectsConfig, RollbarGetProjectConfig, RollbarCreateProjectConfig,
    RollbarDeleteProjectConfig, RollbarListTeamsConfig, RollbarGetTeamConfig,
    RollbarCreateTeamConfig, RollbarListTeamUsersConfig, RollbarListProjectTeamsConfig,
    RollbarAssignTeamProjectConfig, RollbarListUsersConfig, RollbarGetUserConfig,
    RollbarListItemsConfig, RollbarGetItemConfig, RollbarUpdateItemConfig,
    RollbarListItemEventsConfig, RollbarListOccurrencesConfig,
    RollbarGetOccurrenceConfig, RollbarListEnvironmentsConfig,
    RollbarTopActiveItemsConfig, RollbarListDeploysConfig, RollbarGetDeployConfig,
    RollbarReportMessageConfig, RollbarReportDeployConfig,
], Discriminator("operation")]


class RollbarNodeConfig(NodeConfig[RollbarConfig, RollbarAccessTokenCredential]):
    """Rollbar operation and credential."""


def _non_null(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None and value != ""}


def _operation_request(config: BaseModel) -> tuple[str, str, Dict[str, Any], Optional[Dict[str, Any]], bool]:
    """Resolve a validated operation to its HTTP request and token class."""
    op = config.operation
    values = config.model_dump(exclude={"operation"}, exclude_none=True)
    ids = {key: quote(str(value), safe="") for key, value in values.items() if key.endswith("_id")}
    project_id = values.get("project_id")
    params: Dict[str, Any] = {"project_id": project_id} if project_id is not None else {}
    body: Optional[Dict[str, Any]] = None
    post_token = False

    if op == "list_projects": method, path = "GET", "/projects"
    elif op == "get_project": method, path = "GET", f"/project/{ids['project_id']}"
    elif op == "create_project":
        method, path = "POST", "/projects"
        body = _non_null({"name": values["name"], "source_project_id": values.get("source_project_id")})
    elif op == "delete_project": method, path = "DELETE", f"/project/{ids['project_id']}"
    elif op == "list_teams": method, path = "GET", "/teams"
    elif op == "get_team": method, path = "GET", f"/team/{ids['team_id']}"
    elif op == "create_team":
        method, path = "POST", "/teams"
        body = {"name": values["name"], "access_level": values["access_level"]}
    elif op == "list_team_users": method, path = "GET", f"/team/{ids['team_id']}/users"
    elif op == "list_project_teams": method, path = "GET", f"/project/{ids['project_id']}/teams"
    elif op == "assign_team_project": method, path = "PUT", f"/team/{ids['team_id']}/project/{ids['project_id']}"
    elif op == "list_users": method, path = "GET", "/users"
    elif op == "get_user": method, path = "GET", f"/user/{ids['user_id']}"
    elif op == "list_items": method, path = "GET", "/items"
    elif op == "get_item": method, path = "GET", f"/item/{ids['item_id']}"
    elif op == "update_item":
        method, path = "PATCH", f"/item/{ids['item_id']}"
        body = _non_null({key: values.get(key) for key in ("status", "title", "level", "resolved_in_version")})
        if not body:
            raise ValueError("Set at least one item field to update")
    elif op == "list_item_events": method, path = "GET", f"/item/{ids['item_id']}/events"
    elif op == "list_occurrences": method, path = "GET", "/instances"
    elif op == "get_occurrence": method, path = "GET", f"/instance/{ids['occurrence_id']}"
    elif op == "list_environments": method, path = "GET", "/environments"
    elif op == "top_active_items": method, path = "GET", "/reports/top_active_items"
    elif op == "list_deploys": method, path = "GET", "/deploys"
    elif op == "get_deploy": method, path = "GET", f"/deploy/{ids['deploy_id']}"
    elif op == "report_message":
        method, path, post_token = "POST", "/item/", True
        body = {"data": {"environment": values["environment"], "body": {"message": {"body": values["message"]}},
                         "level": values["level"], "platform": values["platform"]}}
    elif op == "report_deploy":
        method, path, post_token = "POST", "/deploy", True
        body = {"environment": values["environment"], "revision": values["revision"]}
    else:
        raise ValueError(f"Unknown Rollbar operation: {op}")

    query_fields = ("page", "limit", "last_id", "status", "level", "environment", "query", "email", "hours", "environments")
    if method == "GET":
        params.update({key: values[key] for key in query_fields if key in values})
    return method, path, params, body, post_token


async def rollbar_request(config: BaseModel, credential: RollbarAccessTokenCredential) -> Dict[str, Any]:
    method, path, params, body, post_token = _operation_request(config)
    project_operations = {
        "list_items", "get_item", "update_item", "list_item_events",
        "list_occurrences", "get_occurrence", "list_environments",
        "top_active_items", "list_deploys", "get_deploy",
    }
    if post_token:
        token = credential.project_post_server_token
    elif config.operation in project_operations and credential.project_read_write_token:
        token = credential.project_read_write_token
    else:
        token = credential.account_access_token
    if not token:
        raise ValueError("A project post_server_item token is required for this reporting operation")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(
            method, f"{API_BASE}{path}", params=params,
            headers={"X-Rollbar-Access-Token": token}, json=body,
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Rollbar response")
    if payload.get("err") not in (None, 0):
        raise ValueError(f"Rollbar API error: {payload.get('message') or payload.get('err')}")
    return {"status": "success", "action": config.operation, "data": payload.get("result", payload)}


class RollbarNode(WorkflowNode):
    integration_type = "automation-rollbar"

    edit_examples = [
        "List active Rollbar errors in a project",
        "Resolve a Rollbar item after a deployment",
        "Report a Rollbar error message",
        "Create a Rollbar project and assign a team",
    ]
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects")

    @classmethod
    def get_config_model(cls):
        return RollbarNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.monotonic()
        if not isinstance(self.config, RollbarNodeConfig):
            raise ValueError("Valid Rollbar configuration is required")
        if not self.config.credentials:
            raise ValueError("Rollbar credentials are required")
        result = await rollbar_request(self.config.config, self.config.credentials)
        result["timing_ms"] = {"total": round((time.monotonic() - started) * 1000, 2)}
        return result
