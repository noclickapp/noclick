"""SwaggerHub Registry API 1.0.66: APIs, versions, domains and projects.

Contract: https://api.swaggerhub.com/apis/swagger-hub/registry-api/1.0.66
Each operation makes one request; list operations return one page.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class SwaggerHubAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Swaggerhub API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.swaggerhub.com/settings/apiKey",
            "x-credential-instructions": "Paste your SwaggerHub API key from account settings. The key is sent in the Authorization header to api.swaggerhub.com. Project access is checked when connecting; organization permissions control writes.",
        })
    credential_type: Literal["swaggerhub_api_key"] = Field("swaggerhub_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(0, ge=0, description="Zero-based page index. Request the next page explicitly.")
    limit: int = Field(10, ge=1, le=100)
    order: Literal["ASC", "DESC"] = "ASC"


class _Owner(_Input):
    owner: str = Field(..., min_length=1, description="Case-sensitive SwaggerHub username or organization name.")


class _API(_Owner):
    api: str = Field(..., min_length=1, description="Case-sensitive API name.")


class _Version(_API):
    version: str = Field(..., min_length=1, description="API version identifier.")


class ListProjects(_Page):
    operation: Literal["list_projects"] = "list_projects"
    name_only: bool = Field(False, description="Exclude APIs and domains from each project.")
    sort: Literal["NAME", "OWNER"] = "NAME"


class ListOrganizationProjects(_Page, _Owner):
    operation: Literal["list_organization_projects"] = "list_organization_projects"
    name_only: bool = False


class _Project(_Owner):
    project_id: str = Field(..., min_length=1, description="Case-sensitive project name, not a numeric ID.")


class GetProject(_Project):
    operation: Literal["get_project"] = "get_project"


class _ProjectData(_Input):
    name: str = Field(..., min_length=1, description="Project name.")
    description: str = ""
    apis: list[str] = Field(default_factory=list, description="API names belonging to this organization.")
    domains: list[str] = Field(default_factory=list, description="Domain names belonging to this organization.")


class CreateProject(_Owner, _ProjectData):
    operation: Literal["create_project"] = "create_project"


class UpdateProject(_Project, _ProjectData):
    """Replace project data. Omitted description, APIs and domains become empty."""
    operation: Literal["update_project"] = "update_project"


class DeleteProject(_Project):
    operation: Literal["delete_project"] = "delete_project"


class SearchDefinitions(_Page):
    operation: Literal["search_definitions"] = "search_definitions"
    query: str | None = None
    owner: str | None = None
    spec_type: Literal["API", "DOMAIN", "TEMPLATE", "ANY"] = "ANY"
    visibility: Literal["PUBLIC", "PRIVATE", "ANY"] = "ANY"
    state: Literal["ALL", "PUBLISHED", "UNPUBLISHED"] = "ALL"
    sort: Literal["NAME", "UPDATED", "CREATED", "OWNER", "BEST_MATCH", "TITLE"] = "NAME"


class ListOwnerAPIs(_Page, _Owner):
    operation: Literal["list_owner_apis"] = "list_owner_apis"
    sort: Literal["NAME", "UPDATED", "CREATED", "OWNER", "BEST_MATCH", "TITLE"] = "NAME"


class ListAPIVersions(_API):
    operation: Literal["list_api_versions"] = "list_api_versions"


class GetAPIDefinition(_Version):
    operation: Literal["get_api_definition"] = "get_api_definition"
    resolved: bool = False
    flatten: bool = False


class CloneAPIVersion(_Version):
    operation: Literal["clone_api_version"] = "clone_api_version"
    new_version: str = Field(..., min_length=1)
    private: bool = Field(..., description="Make the new version private.")


class DeleteAPIVersion(_Version):
    operation: Literal["delete_api_version"] = "delete_api_version"


class RenameAPI(_API):
    operation: Literal["rename_api"] = "rename_api"
    new_name: str = Field(..., min_length=3, max_length=60)


class GetDefaultAPIVersion(_API):
    operation: Literal["get_default_api_version"] = "get_default_api_version"


class SetDefaultAPIVersion(_API):
    operation: Literal["set_default_api_version"] = "set_default_api_version"
    version: str = Field(..., min_length=1)


class GetAPILifecycle(_Version):
    operation: Literal["get_api_lifecycle"] = "get_api_lifecycle"


class SetAPILifecycle(_Version):
    operation: Literal["set_api_lifecycle"] = "set_api_lifecycle"
    published: bool = Field(..., description="Publish this version, or return it to draft.")
    force: bool = Field(False, description="Allow publishing with references to unpublished domains.")


class GetAPIVisibility(_Version):
    operation: Literal["get_api_visibility"] = "get_api_visibility"


class SetAPIVisibility(_Version):
    operation: Literal["set_api_visibility"] = "set_api_visibility"
    private: bool = Field(..., description="True makes this version private; false makes it public.")


class ListOwnerDomains(_Page, _Owner):
    operation: Literal["list_owner_domains"] = "list_owner_domains"
    sort: Literal["NAME", "UPDATED", "CREATED", "OWNER", "BEST_MATCH", "TITLE"] = "NAME"


class GetDomainDefinition(_Owner):
    operation: Literal["get_domain_definition"] = "get_domain_definition"
    domain: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)


SwaggerHubOperation = Annotated[Union[
    ListProjects, ListOrganizationProjects, GetProject, CreateProject, UpdateProject,
    DeleteProject, SearchDefinitions, ListOwnerAPIs, ListAPIVersions,
    GetAPIDefinition, CloneAPIVersion, DeleteAPIVersion, RenameAPI,
    GetDefaultAPIVersion, SetDefaultAPIVersion, GetAPILifecycle, SetAPILifecycle,
    GetAPIVisibility, SetAPIVisibility, ListOwnerDomains, GetDomainDefinition,
], Field(discriminator="operation")]


class SwaggerHubConfig(NodeConfig[SwaggerHubOperation, SwaggerHubAPIKeyCredential]):
    pass


# One fixed route and verb per user operation, from Registry API 1.0.66.
ROUTES = {
    "list_projects": ("GET", "/projects"),
    "list_organization_projects": ("GET", "/projects/{owner}"),
    "get_project": ("GET", "/projects/{owner}/{project_id}"),
    "create_project": ("POST", "/projects/{owner}"),
    "update_project": ("PUT", "/projects/{owner}/{project_id}"),
    "delete_project": ("DELETE", "/projects/{owner}/{project_id}"),
    "search_definitions": ("GET", "/specs"),
    "list_owner_apis": ("GET", "/apis/{owner}"),
    "list_api_versions": ("GET", "/apis/{owner}/{api}"),
    "get_api_definition": ("GET", "/apis/{owner}/{api}/{version}/swagger.json"),
    "clone_api_version": ("POST", "/apis/{owner}/{api}/{version}/clone"),
    "delete_api_version": ("DELETE", "/apis/{owner}/{api}/{version}"),
    "rename_api": ("POST", "/apis/{owner}/{api}/rename"),
    "get_default_api_version": ("GET", "/apis/{owner}/{api}/settings/default"),
    "set_default_api_version": ("PUT", "/apis/{owner}/{api}/settings/default"),
    "get_api_lifecycle": ("GET", "/apis/{owner}/{api}/{version}/settings/lifecycle"),
    "set_api_lifecycle": ("PUT", "/apis/{owner}/{api}/{version}/settings/lifecycle"),
    "get_api_visibility": ("GET", "/apis/{owner}/{api}/{version}/settings/private"),
    "set_api_visibility": ("PUT", "/apis/{owner}/{api}/{version}/settings/private"),
    "list_owner_domains": ("GET", "/domains/{owner}"),
    "get_domain_definition": ("GET", "/domains/{owner}/{domain}/{version}/domain.json"),
}


class SwaggerHubNode(WorkflowNode):
    integration_type = "automation-swaggerhub"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="SwaggerHub projects")

    @classmethod
    def get_config_model(cls):
        return SwaggerHubConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SwaggerHub API key")
        op = self.config.config
        values = op.model_dump(exclude_none=True)
        action = op.operation
        method, template = ROUTES[action]
        # Reject dot segments; all other path components are percent-encoded.
        for field in ("owner", "api", "project_id", "domain", "version"):
            if "{" + field + "}" in template and values[field] in {".", ".."}:
                raise ValueError("Use a resource name, not a dot path segment")
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        params, body = {}, None
        if isinstance(op, _Page):
            params = {k: values[k] for k in ("page", "limit", "order")}
            if "sort" in values:
                params["sort"] = values["sort"]
        if isinstance(op, (ListProjects, ListOrganizationProjects)):
            params["nameOnly"] = op.name_only
        if isinstance(op, SearchDefinitions):
            params.update({k: values[k] for k in ("owner", "query", "visibility", "state") if k in values})
            params["specType"] = op.spec_type
        if isinstance(op, GetAPIDefinition):
            params.update(resolved=op.resolved, flatten=op.flatten)
        if isinstance(op, (CreateProject, UpdateProject)):
            body = {k: values[k] for k in ("name", "description", "apis", "domains")}
        elif isinstance(op, CloneAPIVersion):
            body = {"version": op.new_version, "private": op.private}
        elif isinstance(op, RenameAPI):
            params["newName"] = op.new_name
        elif isinstance(op, SetDefaultAPIVersion):
            body = {"version": op.version}
        elif isinstance(op, SetAPILifecycle):
            body = {"published": op.published}
            params["force"] = op.force
        elif isinstance(op, SetAPIVisibility):
            body = {"private": op.private}
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        key = self.config.credentials.api_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.swaggerhub.com" + path,
                params=params, json=body,
                headers={"Authorization": key, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            # Keep provider text for connection rejection, without exposing the key.
            message = response.text[:4000].replace(key, "[redacted]")
            result = {"status": "error", "error": message or "SwaggerHub rejected the request", "http_status": response.status_code}
        else:
            data = response.json() if response.content else None
            result = {"status": "success", "data": data, "http_status": response.status_code}
        await self.emit(result)
        return result
