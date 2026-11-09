"""Snyk V1 organization, project and issue automation with pasted API tokens.

Each operation sends one documented request. Retired V1 project listing is
intentionally absent; callers supply project IDs from Snyk.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.snyk.io/api/v1"
CREDENTIAL_TYPE = "snyk_api_token"


class SnykAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Snyk API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.snyk.io/account",
            "x-credential-instructions": "Paste an existing Snyk API token for the US API (api.snyk.io), without the token prefix. API access requires an eligible Snyk plan. Use a service account token for ongoing automation; its permissions control which organizations and actions are available. Get a personal API token from Account settings, or a service account token from your organization administrator.",
        })
    credential_type: Literal["snyk_api_token"] = Field("snyk_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API token, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Organization(_Input):
    org_id: str = Field(..., min_length=1, max_length=200, title="Organization ID",
        description="Organization UUID from Snyk or List organizations.")

    @field_validator("org_id", "project_id", "issue_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#%") or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Use a single Snyk ID without URL components")
        return value


class _Project(_Organization):
    project_id: str = Field(..., min_length=1, max_length=200, title="Project ID",
        description="Project UUID from the Snyk project URL or REST API.")


class _Issue(_Project):
    issue_id: str = Field(..., min_length=1, max_length=300, title="Issue ID",
        description="Snyk vulnerability or license issue ID, for example npm:qs:20140806-1.")


class _Tag(_Project):
    key: str = Field(..., min_length=1, max_length=30, pattern=r"^[A-Za-z0-9_-]+$", title="Tag key")
    value: str = Field(..., min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$", title="Tag value")


class IssueFilters(_Input):
    severities: list[Literal["critical", "high", "medium", "low"]] | None = None
    types: list[Literal["vuln", "license"]] | None = None
    ignored: bool | None = None
    patched: bool | None = None


class GetCurrentUser(_Input):
    """Read the token owner details."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class ListOrganizations(_Input):
    """List organizations accessible to this token."""
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})


class GetOrganizationSettings(_Organization):
    """Read organization settings."""
    operation: Literal["get_organization_settings"] = Field("get_organization_settings", json_schema_extra={"ui:hidden": True})


class ListOrganizationMembers(_Organization):
    """List organization members."""
    operation: Literal["list_organization_members"] = Field("list_organization_members", json_schema_extra={"ui:hidden": True})
    include_group_admins: bool = Field(False, description="Include group administrators with access to the organization.")


class ListIntegrations(_Organization):
    """List configured source integrations. Requires organization admin access."""
    operation: Literal["list_integrations"] = Field("list_integrations", json_schema_extra={"ui:hidden": True})


class GetProject(_Project):
    """Retrieve a project and its issue counts."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class UpdateProject(_Project):
    """Change the monitored branch or project owner."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    branch: str | None = Field(None, min_length=1, max_length=500)
    owner_id: str | None = Field(None, min_length=1, max_length=200, description="User ID of a member of this organization.")

    @model_validator(mode="after")
    def changed_field(self):
        if self.branch is None and self.owner_id is None:
            raise ValueError("Supply a branch or owner ID to update")
        return self


class ActivateProject(_Project):
    """Activate project monitoring."""
    operation: Literal["activate_project"] = Field("activate_project", json_schema_extra={"ui:hidden": True})


class DeactivateProject(_Project):
    """Deactivate project monitoring."""
    operation: Literal["deactivate_project"] = Field("deactivate_project", json_schema_extra={"ui:hidden": True})


class DeleteProject(_Project):
    """Permanently delete the selected project."""
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})


class ListIssues(_Project):
    """List aggregated vulnerability and license issues."""
    operation: Literal["list_issues"] = Field("list_issues", json_schema_extra={"ui:hidden": True})
    include_description: bool = False
    include_introduced_through: bool = False
    filters: IssueFilters | None = None


class GetDependencyGraph(_Project):
    """Retrieve the project dependency graph."""
    operation: Literal["get_dependency_graph"] = Field("get_dependency_graph", json_schema_extra={"ui:hidden": True})


class ListIgnores(_Project):
    """List project ignore rules."""
    operation: Literal["list_ignores"] = Field("list_ignores", json_schema_extra={"ui:hidden": True})


class GetIgnore(_Issue):
    """Retrieve ignore rules for one issue."""
    operation: Literal["get_ignore"] = Field("get_ignore", json_schema_extra={"ui:hidden": True})


class AddIgnore(_Issue):
    """Add an ignore rule for an issue."""
    operation: Literal["add_ignore"] = Field("add_ignore", json_schema_extra={"ui:hidden": True})
    reason_type: Literal["not-vulnerable", "wont-fix", "temporary-ignore"] = Field(..., title="Reason type")
    disregard_if_fixable: bool = Field(False, description="Only ignore when no upgrade or patch is available.")
    reason: str | None = Field(None, max_length=10000)
    expires: str | None = Field(None, description="ISO 8601 timestamp when the ignore expires.")
    ignore_path: str | None = Field(None, max_length=5000, description="Dependency path to ignore. Omit for all paths (*).")


class DeleteIgnore(_Issue):
    """Delete all ignore rules for the selected issue."""
    operation: Literal["delete_ignore"] = Field("delete_ignore", json_schema_extra={"ui:hidden": True})


class AddProjectTag(_Tag):
    """Apply a tag to the project."""
    operation: Literal["add_project_tag"] = Field("add_project_tag", json_schema_extra={"ui:hidden": True})


class RemoveProjectTag(_Tag):
    """Remove a tag from the project."""
    operation: Literal["remove_project_tag"] = Field("remove_project_tag", json_schema_extra={"ui:hidden": True})


class GetProjectSettings(_Project):
    """Read project-specific settings."""
    operation: Literal["get_project_settings"] = Field("get_project_settings", json_schema_extra={"ui:hidden": True})


class ResetProjectSettings(_Project):
    """Remove project-specific settings and inherit integration settings."""
    operation: Literal["reset_project_settings"] = Field("reset_project_settings", json_schema_extra={"ui:hidden": True})


SnykOperation = Annotated[Union[
    GetCurrentUser,
    ListOrganizations,
    GetOrganizationSettings,
    ListOrganizationMembers,
    ListIntegrations,
    GetProject,
    UpdateProject,
    ActivateProject,
    DeactivateProject,
    DeleteProject,
    ListIssues,
    GetDependencyGraph,
    ListIgnores,
    GetIgnore,
    AddIgnore,
    DeleteIgnore,
    AddProjectTag,
    RemoveProjectTag,
    GetProjectSettings,
    ResetProjectSettings
], Field(discriminator="operation")]


class SnykNodeConfig(NodeConfig[SnykOperation, SnykAPITokenCredential]):
    pass


# Fixed routes are the operation-to-contract mapping; no caller-supplied URLs.
ROUTES = {
    "get_current_user": ("GET", "/user/me"),
    "list_organizations": ("GET", "/orgs"),
    "get_organization_settings": ("GET", "/org/{org_id}/settings"),
    "list_organization_members": ("GET", "/org/{org_id}/members"),
    "list_integrations": ("GET", "/org/{org_id}/integrations"),
    "get_project": ("GET", "/org/{org_id}/project/{project_id}"),
    "update_project": ("PUT", "/org/{org_id}/project/{project_id}"),
    "activate_project": ("POST", "/org/{org_id}/project/{project_id}/activate"),
    "deactivate_project": ("POST", "/org/{org_id}/project/{project_id}/deactivate"),
    "delete_project": ("DELETE", "/org/{org_id}/project/{project_id}"),
    "list_issues": ("POST", "/org/{org_id}/project/{project_id}/aggregated-issues"),
    "get_dependency_graph": ("GET", "/org/{org_id}/project/{project_id}/dep-graph"),
    "list_ignores": ("GET", "/org/{org_id}/project/{project_id}/ignores"),
    "get_ignore": ("GET", "/org/{org_id}/project/{project_id}/ignore/{issue_id}"),
    "add_ignore": ("POST", "/org/{org_id}/project/{project_id}/ignore/{issue_id}"),
    "delete_ignore": ("DELETE", "/org/{org_id}/project/{project_id}/ignore/{issue_id}"),
    "add_project_tag": ("POST", "/org/{org_id}/project/{project_id}/tags"),
    "remove_project_tag": ("POST", "/org/{org_id}/project/{project_id}/tags/remove"),
    "get_project_settings": ("GET", "/org/{org_id}/project/{project_id}/settings"),
    "reset_project_settings": ("DELETE", "/org/{org_id}/project/{project_id}/settings"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()}
    return value


class SnykNode(WorkflowNode):
    integration_type = "automation-snyk"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_organizations")

    @classmethod
    def get_config_model(cls):
        return SnykNodeConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Snyk API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path = template.format(**{name: quote(values[name], safe="") for name in ("org_id", "project_id", "issue_id") if name in values})
        params, body = {}, None
        if isinstance(op, ListOrganizationMembers):
            params["includeGroupAdmins"] = str(op.include_group_admins).lower()
        elif isinstance(op, UpdateProject):
            body = {}
            if op.branch is not None:
                body["branch"] = op.branch
            if op.owner_id is not None:
                body["owner"] = {"id": op.owner_id}
        elif isinstance(op, ListIssues):
            body = {"includeDescription": op.include_description, "includeIntroducedThrough": op.include_introduced_through}
            if op.filters is not None:
                body["filters"] = op.filters.model_dump(exclude_none=True)
        elif isinstance(op, AddIgnore):
            body = {"reasonType": op.reason_type, "disregardIfFixable": op.disregard_if_fixable}
            for source, target in (("reason", "reason"), ("expires", "expires"), ("ignore_path", "ignorePath")):
                if getattr(op, source) is not None:
                    body[target] = getattr(op, source)
        elif isinstance(op, (AddProjectTag, RemoveProjectTag)):
            body = {"key": op.key, "value": op.value}
        headers = {"Authorization": "token " + token, "Accept": "application/json"}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, params=params,
                **({"json": body} if body is not None else {}))
        status = response.status_code
        if not 200 <= status < 300:
            # Retain the provider's rejection for the shared connect verdict.
            message = response.text[:2000].replace(token, "[redacted]")
            return {"status": "error", "http_status": status, "error": f"Snyk HTTP {status}: {message}"}
        if not response.content:
            # V1 mutations document an empty 200 acknowledgement.
            if method in {"GET"} or isinstance(op, ListIssues):
                raise ValueError("Snyk returned an empty read response")
            data = None
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Snyk response exceeds 10 MB")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime != "application/json" and not mime.endswith("+json"):
                raise ValueError("Snyk returned a non-JSON response")
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Snyk returned an unexpected JSON response")
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("errorRef")):
                return {"status": "error", "http_status": status, "error": _redact(data, token)}
            if isinstance(op, ListOrganizations) and (not isinstance(data, dict) or not isinstance(data.get("orgs"), list)):
                raise ValueError("Snyk did not return an organization list")
        return {"status": "success", "operation": op.operation, "http_status": status, "data": _redact(data, token)}
