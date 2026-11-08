"""DeployHQ API v1 projects, deployments and repository reads.

Contract: https://api.deployhq.com/docs.json. Lists return one provider page;
queue/abort/retry/delete results are acknowledgements, not completion claims.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client


class DeployHQAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="DeployHQ API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.deployhq.com/support/api",
        "x-credential-instructions": "In your DeployHQ account, open Settings → Developers and copy your API key. Enter your account subdomain and the email address you use to sign in. NoClick sends email and API key using HTTP Basic authentication to that account's deployhq.com host.",
    })
    credential_type: Literal["deployhq_api_key"] = Field("deployhq_api_key", json_schema_extra={"ui:hidden": True})
    account: str = Field(..., title="Account subdomain", description="The account part of https://account.deployhq.com; enter the subdomain only.", pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    email: str = Field(..., title="Email address", min_length=3, max_length=254)
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s:@]+@[^\s@]+\.[^\s@]+", value) or not value.isascii():
            raise ValueError("Enter your DeployHQ sign-in email address")
        return value

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("project_id", "deployment_id", "server_id", "schedule_id", "team_id", check_fields=False)
    @classmethod
    def resource_id(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
            raise ValueError("Enter a DeployHQ identifier or project permalink")
        return value


def _operation(name, category):
    return Field(name, title=name.replace("_", " ").title(), json_schema_extra={
        "ui:hidden": True, "x-category": category, "x-display-name": name.replace("_", " ").title(), "x-is-trigger": False,
    })


class _Project(_Input):
    project_id: str = Field(..., title="Project ID or permalink", min_length=1)


class _Deployment(_Project):
    deployment_id: str = Field(..., title="Deployment identifier", min_length=1)


class _Server(_Project):
    server_id: str = Field(..., title="Server identifier", min_length=1)


class _Schedule(_Project):
    schedule_id: str = Field(..., title="Scheduled deployment identifier", min_length=1)


class _Team(_Input):
    team_id: str = Field(..., title="Team identifier", min_length=1)


class _Branch(_Project):
    branch: str = Field(..., title="Branch", min_length=1, max_length=1000)


class ListProjects(_Input):
    operation: Literal["list_projects"] = _operation("list_projects", "Projects")


class GetProject(_Project):
    operation: Literal["get_project"] = _operation("get_project", "Projects")


class CreateProject(_Input):
    operation: Literal["create_project"] = _operation("create_project", "Projects")
    name: str = Field(..., min_length=1, max_length=255, title="Project name")
    keypair_identifier: str | None = None
    zone_id: str | None = None
    template_id: str | None = None


class UpdateProject(_Project):
    operation: Literal["update_project"] = _operation("update_project", "Projects")
    name: str = Field(..., min_length=1, max_length=255, title="Project name")
    zone_id: str | None = None
    permalink: str | None = None
    folder: str | None = None


class DeleteProject(_Project):
    operation: Literal["delete_project"] = _operation("delete_project", "Projects")


class ListDeployments(_Project):
    operation: Literal["list_deployments"] = _operation("list_deployments", "Deployments")
    page: int = Field(1, ge=1, description="Page number; use pagination.total_pages from the response.")
    per_page: int = Field(10, ge=1, le=100)
    to: str | None = Field(None, description="Filter by parent server or group identifier.")
    currently_running: bool = Field(False, description="Only return running deployments.")


class CreateDeployment(_Project):
    operation: Literal["create_deployment"] = _operation("create_deployment", "Deployments")
    branch: str = Field(..., min_length=1, max_length=1000)
    parent_identifier: str = Field(..., min_length=1, description="Target server or server group identifier.")
    end_revision: str = Field(..., min_length=1, description="Commit reference to deploy.")
    start_revision: str | None = None
    mode: Literal["queue", "preview"] = Field("queue", description="Queue executes a deployment; preview only generates the changes.")
    copy_config_files: bool = True
    run_build_commands: bool = True
    use_build_cache: bool = True
    skip_if_not_changes: bool = False


class GetDeployment(_Deployment):
    operation: Literal["get_deployment"] = _operation("get_deployment", "Deployments")


class AbortDeployment(_Deployment):
    operation: Literal["abort_deployment"] = _operation("abort_deployment", "Deployments")


class RetryDeployment(_Deployment):
    operation: Literal["retry_deployment"] = _operation("retry_deployment", "Deployments")


class ListServers(_Project):
    operation: Literal["list_servers"] = _operation("list_servers", "Servers")


class GetServer(_Server):
    operation: Literal["get_server"] = _operation("get_server", "Servers")


class ListServerGroups(_Project):
    operation: Literal["list_server_groups"] = _operation("list_server_groups", "Servers")


class GetRepository(_Project):
    operation: Literal["get_repository"] = _operation("get_repository", "Repository")


class ListBranches(_Project):
    operation: Literal["list_branches"] = _operation("list_branches", "Repository")


class GetLatestRevision(_Branch):
    operation: Literal["get_latest_revision"] = _operation("get_latest_revision", "Repository")


class ListRecentCommits(_Branch):
    operation: Literal["list_recent_commits"] = _operation("list_recent_commits", "Repository")


class ListScheduledDeployments(_Project):
    operation: Literal["list_scheduled_deployments"] = _operation("list_scheduled_deployments", "Schedules")


class GetScheduledDeployment(_Schedule):
    operation: Literal["get_scheduled_deployment"] = _operation("get_scheduled_deployment", "Schedules")


class CancelScheduledDeployment(_Schedule):
    operation: Literal["cancel_scheduled_deployment"] = _operation("cancel_scheduled_deployment", "Schedules")


class ListTeams(_Input):
    operation: Literal["list_teams"] = _operation("list_teams", "Teams")


class GetTeam(_Team):
    operation: Literal["get_team"] = _operation("get_team", "Teams")


DeployHQOperation = Annotated[Union[
    ListProjects, GetProject, CreateProject, UpdateProject, DeleteProject, ListDeployments, CreateDeployment, GetDeployment, AbortDeployment, RetryDeployment, ListServers, GetServer, ListServerGroups, GetRepository, ListBranches, GetLatestRevision, ListRecentCommits, ListScheduledDeployments, GetScheduledDeployment, CancelScheduledDeployment, ListTeams, GetTeam
], Field(discriminator="operation")]


class DeployHQNodeConfig(NodeConfig[DeployHQOperation, DeployHQAPIKeyCredential]):
    pass


DEPLOYHQ_OPERATIONS = {
    "list_projects": ("GET", "/projects"),
    "get_project": ("GET", "/projects/{project_id}"),
    "create_project": ("POST", "/projects"),
    "update_project": ("PATCH", "/projects/{project_id}"),
    "delete_project": ("DELETE", "/projects/{project_id}"),
    "list_deployments": ("GET", "/projects/{project_id}/deployments"),
    "create_deployment": ("POST", "/projects/{project_id}/deployments"),
    "get_deployment": ("GET", "/projects/{project_id}/deployments/{deployment_id}"),
    "abort_deployment": ("POST", "/projects/{project_id}/deployments/{deployment_id}/abort"),
    "retry_deployment": ("POST", "/projects/{project_id}/deployments/{deployment_id}/retry"),
    "list_servers": ("GET", "/projects/{project_id}/servers"),
    "get_server": ("GET", "/projects/{project_id}/servers/{server_id}"),
    "list_server_groups": ("GET", "/projects/{project_id}/server_groups"),
    "get_repository": ("GET", "/projects/{project_id}/repository"),
    "list_branches": ("GET", "/projects/{project_id}/repository/branches"),
    "get_latest_revision": ("GET", "/projects/{project_id}/repository/latest_revision"),
    "list_recent_commits": ("GET", "/projects/{project_id}/repository/recent_commits"),
    "list_scheduled_deployments": ("GET", "/projects/{project_id}/scheduled_deployments"),
    "get_scheduled_deployment": ("GET", "/projects/{project_id}/scheduled_deployments/{schedule_id}"),
    "cancel_scheduled_deployment": ("DELETE", "/projects/{project_id}/scheduled_deployments/{schedule_id}"),
    "list_teams": ("GET", "/teams"),
    "get_team": ("GET", "/teams/{team_id}"),
}


class DeployHQNode(WorkflowNode):
    integration_type = "automation-deployhq"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects", label_keys=("name", "permalink", "identifier"))

    @classmethod
    def get_config_model(cls):
        return DeployHQNodeConfig

    async def execute(self, inputs):
        if not isinstance(self.config, DeployHQNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a DeployHQ API key")
        credential = self.config.credentials
        config = self.config.config
        operation = config.operation
        method, path = DEPLOYHQ_OPERATIONS[operation]
        values = config.model_dump(exclude_none=True)
        for field in ("project_id", "deployment_id", "server_id", "schedule_id", "team_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        values.pop("operation")
        params = {}
        body = None
        if operation == "list_deployments":
            params = {k: v for k, v in values.items() if k != "currently_running"}
            if config.currently_running:
                params["currently_running"] = "1"
        elif operation in {"get_latest_revision", "list_recent_commits"}:
            params = {"branch": config.branch}
        elif operation in {"create_project", "update_project"}:
            body = {"project": values}
        elif operation == "create_deployment":
            body = {"deployment": values}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = httpx.BasicAuth(credential.email, credential.api_key)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, f"https://{credential.account}.deployhq.com" + path,
                    headers=headers, auth=auth, params=params or None, **({"json": body} if body is not None else {}))
        except (httpx.RequestError, SSRFError):
            return {"status": "error", "action": operation, "error": "DeployHQ request did not complete; inspect the provider before retrying a write"}
        code = response.status_code
        if not 200 <= code < 300:
            try:
                error = response.json()
            except ValueError:
                error = None
            message = error.get("error") or error.get("message") or error.get("hint") if isinstance(error, dict) else None
            message = str(message or f"DeployHQ returned HTTP {code}")
            for secret in (credential.api_key, auth._auth_header):
                message = message.replace(secret, "[redacted]")
            return {"status": "error", "action": operation, "error": message[:2000], "status_code": code}
        try:
            if len(response.content) > 5_000_000:
                raise ValueError("Response too large")
            if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("Expected JSON")
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Expected a JSON object or list")
            if isinstance(data, dict) and (data.get("error") or data.get("error_code")):
                raise ValueError("Provider error envelope")
            if operation in {"list_projects", "list_servers", "list_server_groups", "list_scheduled_deployments", "list_teams"}:
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError("Expected a list of resources")
            elif operation == "list_deployments":
                if not isinstance(data, dict) or not isinstance(data.get("records"), list) or not isinstance(data.get("pagination"), dict):
                    raise ValueError("Expected deployment records and pagination")
        except ValueError:
            return {"status": "error", "action": operation, "error": "DeployHQ returned an unexpected JSON response", "status_code": code}
        return {"status": "success", "action": operation, "data": data, "status_code": code}
