"""Harness NextGen API-key operations, pinned to the published 3.0 contract.

Each operation makes one request. Lists return one explicit page; writes are
never retried. Update operations replace the supplied metadata fields.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://app.harness.io/gateway"

class HarnessApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Harness API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.harness.io/docs/platform/automation/api/add-and-manage-api-keys/"})
    credential_type: Literal["harness_api_key"] = Field("harness_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
        description="Paste the API key token from Harness. It is sent as x-api-key. Grant only the resource permissions your operations need.",
        json_schema_extra={"ui:widget": "password"})
    account_identifier: str = Field(..., title="Account Identifier", min_length=1,
        description="Copy the account identifier from your Harness account URL.")

    @field_validator("api_key", "account_identifier")
    @classmethod
    def clean(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste a nonempty value without whitespace or controls")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith(("_identifier", "_id")):
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", value):
                raise ValueError("Use a Harness identifier without path delimiters")
        if info.field_name == "if_match" and value is not None and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Version must not contain controls")
        return value

class Page(Input):
    page: int = Field(0, ge=0, title="Page Index")
    size: int = Field(50, ge=1, le=100, title="Page Size", description="One page is returned per run. Increment Page Index for subsequent pages.")
    search_term: str | None = Field(None, title="Search Term")

class Org(Input):
    org_identifier: str = Field(..., min_length=1, title="Organization Identifier")

class Project(Org):
    project_identifier: str = Field(..., min_length=1, title="Project Identifier")

class Metadata(Input):
    name: str = Field(..., min_length=1, title="Name")
    description: str = Field("", max_length=1024, title="Description")
    tags: dict[str, str] = Field(default_factory=dict, title="Tags")

class ListOrganizations(Page):
    operation: Literal["list_organizations"] = Field("list_organizations", title="ListOrganizations", json_schema_extra={"ui:hidden": True})

class GetOrganization(Org):
    operation: Literal["get_organization"] = Field("get_organization", title="GetOrganization", json_schema_extra={"ui:hidden": True})

class CreateOrganization(Org, Metadata):
    operation: Literal["create_organization"] = Field("create_organization", title="CreateOrganization", json_schema_extra={"ui:hidden": True})

class UpdateOrganization(Org, Metadata):
    operation: Literal["update_organization"] = Field("update_organization", title="UpdateOrganization", json_schema_extra={"ui:hidden": True})
    if_match: str | None = Field(None, title="If-Match Version", description="Optional optimistic concurrency version.")

class DeleteOrganization(Org):
    operation: Literal["delete_organization"] = Field("delete_organization", title="DeleteOrganization", json_schema_extra={"ui:hidden": True})
    if_match: str | None = Field(None, title="If-Match Version", description="Optional optimistic concurrency version.")

class ListProjects(Org, Page):
    operation: Literal["list_projects"] = Field("list_projects", title="ListProjects", json_schema_extra={"ui:hidden": True})

class GetProject(Project):
    operation: Literal["get_project"] = Field("get_project", title="GetProject", json_schema_extra={"ui:hidden": True})

class CreateProject(Project, Metadata):
    operation: Literal["create_project"] = Field("create_project", title="CreateProject", json_schema_extra={"ui:hidden": True})

class UpdateProject(Project, Metadata):
    operation: Literal["update_project"] = Field("update_project", title="UpdateProject", json_schema_extra={"ui:hidden": True})
    if_match: str | None = Field(None, title="If-Match Version", description="Optional optimistic concurrency version.")

class DeleteProject(Project):
    operation: Literal["delete_project"] = Field("delete_project", title="DeleteProject", json_schema_extra={"ui:hidden": True})
    if_match: str | None = Field(None, title="If-Match Version", description="Optional optimistic concurrency version.")

class ListServices(Project, Page):
    operation: Literal["list_services"] = Field("list_services", title="ListServices", json_schema_extra={"ui:hidden": True})

class GetService(Project):
    operation: Literal["get_service"] = Field("get_service", title="GetService", json_schema_extra={"ui:hidden": True})
    service_identifier: str = Field(..., min_length=1, title="Service Identifier")

class CreateService(Project, Metadata):
    operation: Literal["create_service"] = Field("create_service", title="CreateService", json_schema_extra={"ui:hidden": True})
    service_identifier: str = Field(..., min_length=1, title="Service Identifier")

class UpdateService(Project, Metadata):
    operation: Literal["update_service"] = Field("update_service", title="UpdateService", json_schema_extra={"ui:hidden": True})
    service_identifier: str = Field(..., min_length=1, title="Service Identifier")
    if_match: str | None = Field(None, title="If-Match Version", description="Optional optimistic concurrency version.")

class DeleteService(Project):
    operation: Literal["delete_service"] = Field("delete_service", title="DeleteService", json_schema_extra={"ui:hidden": True})
    service_identifier: str = Field(..., min_length=1, title="Service Identifier")
    if_match: str | None = Field(None, title="If-Match Version", description="Optional optimistic concurrency version.")

class ListEnvironments(Project, Page):
    operation: Literal["list_environments"] = Field("list_environments", title="ListEnvironments", json_schema_extra={"ui:hidden": True})

class GetEnvironment(Project):
    operation: Literal["get_environment"] = Field("get_environment", title="GetEnvironment", json_schema_extra={"ui:hidden": True})
    environment_identifier: str = Field(..., min_length=1, title="Environment Identifier")

class CreateEnvironment(Project, Metadata):
    operation: Literal["create_environment"] = Field("create_environment", title="CreateEnvironment", json_schema_extra={"ui:hidden": True})
    environment_identifier: str = Field(..., min_length=1, title="Environment Identifier")
    environment_type: Literal["PreProduction", "Production"] = Field(..., title="Environment Type")

class UpdateEnvironment(Project, Metadata):
    operation: Literal["update_environment"] = Field("update_environment", title="UpdateEnvironment", json_schema_extra={"ui:hidden": True})
    environment_identifier: str = Field(..., min_length=1, title="Environment Identifier")
    environment_type: Literal["PreProduction", "Production"] = Field(..., title="Environment Type")
    if_match: str | None = Field(None, title="If-Match Version", description="Optional optimistic concurrency version.")

class DeleteEnvironment(Project):
    operation: Literal["delete_environment"] = Field("delete_environment", title="DeleteEnvironment", json_schema_extra={"ui:hidden": True})
    environment_identifier: str = Field(..., min_length=1, title="Environment Identifier")
    if_match: str | None = Field(None, title="If-Match Version", description="Optional optimistic concurrency version.")

class ListPipelines(Project, Page):
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra={"ui:hidden": True})

class GetPipeline(Project):
    operation: Literal["get_pipeline"] = Field("get_pipeline", json_schema_extra={"ui:hidden": True})
    pipeline_identifier: str = Field(..., min_length=1, title="Pipeline Identifier")

class ExecutePipeline(GetPipeline):
    operation: Literal["execute_pipeline"] = Field("execute_pipeline", json_schema_extra={"ui:hidden": True})
    module_type: Literal["CD", "CI"] = Field(..., title="Module Type")
    input_set_yaml: str = Field("", title="Input Set YAML", description="Runtime inputs for this pipeline execution. Executing a pipeline can deploy software.", json_schema_extra={"ui:widget": "textarea"})

class GetExecution(Project):
    operation: Literal["get_execution"] = Field("get_execution", json_schema_extra={"ui:hidden": True})
    plan_execution_id: str = Field(..., min_length=1, title="Plan Execution ID")

Operation = Annotated[Union[ListOrganizations, GetOrganization, CreateOrganization, UpdateOrganization, DeleteOrganization, ListProjects, GetProject, CreateProject, UpdateProject, DeleteProject, ListServices, GetService, CreateService, UpdateService, DeleteService, ListEnvironments, GetEnvironment, CreateEnvironment, UpdateEnvironment, DeleteEnvironment, ListPipelines, GetPipeline, ExecutePipeline, GetExecution], Field(discriminator="operation")]

class HarnessConfig(NodeConfig[Operation, HarnessApiKeyCredential]):
    pass

ROUTES = {'list_organizations': ('GET', '/ng/api/organizations', 'organization', 'list'), 'get_organization': ('GET', '/ng/api/organizations/{identifier}', 'organization', 'get'), 'create_organization': ('POST', '/ng/api/organizations', 'organization', 'create'), 'update_organization': ('PUT', '/ng/api/organizations/{identifier}', 'organization', 'update'), 'delete_organization': ('DELETE', '/ng/api/organizations/{identifier}', 'organization', 'delete'), 'list_projects': ('GET', '/ng/api/projects', 'project', 'list'), 'get_project': ('GET', '/ng/api/projects/{identifier}', 'project', 'get'), 'create_project': ('POST', '/ng/api/projects', 'project', 'create'), 'update_project': ('PUT', '/ng/api/projects/{identifier}', 'project', 'update'), 'delete_project': ('DELETE', '/ng/api/projects/{identifier}', 'project', 'delete'), 'list_services': ('GET', '/ng/api/servicesV2', 'service', 'list'), 'get_service': ('GET', '/ng/api/servicesV2/{serviceIdentifier}', 'service', 'get'), 'create_service': ('POST', '/ng/api/servicesV2', 'service', 'create'), 'update_service': ('PUT', '/ng/api/servicesV2', 'service', 'update'), 'delete_service': ('DELETE', '/ng/api/servicesV2/{serviceIdentifier}', 'service', 'delete'), 'list_environments': ('GET', '/ng/api/environmentsV2', 'environment', 'list'), 'get_environment': ('GET', '/ng/api/environmentsV2/{environmentIdentifier}', 'environment', 'get'), 'create_environment': ('POST', '/ng/api/environmentsV2', 'environment', 'create'), 'update_environment': ('PUT', '/ng/api/environmentsV2', 'environment', 'update'), 'delete_environment': ('DELETE', '/ng/api/environmentsV2/{environmentIdentifier}', 'environment', 'delete'), 'list_pipelines': ('POST', '/pipeline/api/pipelines/list', 'pipeline', 'list'), 'get_pipeline': ('GET', '/pipeline/api/pipelines/{pipelineIdentifier}', 'pipeline', 'get'), 'execute_pipeline': ('POST', '/pipeline/api/pipeline/execute/{identifier}', 'pipeline', 'execute'), 'get_execution': ('GET', '/pipeline/api/pipelines/execution/{planExecutionId}', 'execution', 'get')}

class HarnessNode(WorkflowNode):
    integration_type = "automation-harness"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_organizations")

    @classmethod
    def get_config_model(cls):
        return HarnessConfig

    async def execute(self, inputs):
        if not isinstance(self.config, HarnessConfig) or not self.config.credentials:
            raise ValueError("Connect a Harness API key")
        c, cred = self.config.config, self.config.credentials
        method, path, resource, action = ROUTES[c.operation]
        params = {"accountIdentifier": cred.account_identifier}
        if resource != "organization":
            params["orgIdentifier"] = c.org_identifier
        if resource not in {"organization", "project"}:
            params["projectIdentifier"] = c.project_identifier
        ids = {"identifier": getattr(c, "org_identifier" if resource == "organization" else resource + "_identifier", None),
               "serviceIdentifier": getattr(c, "service_identifier", None),
               "environmentIdentifier": getattr(c, "environment_identifier", None),
               "pipelineIdentifier": getattr(c, "pipeline_identifier", None),
               "planExecutionId": getattr(c, "plan_execution_id", None)}
        for key, value in ids.items():
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(value, safe=""))
        headers = {"x-api-key": cred.api_key, "Accept": "application/json"}
        if getattr(c, "if_match", None) is not None:
            headers["If-Match"] = c.if_match
        body = None
        if action == "list":
            params.update({"pageIndex" if resource in {"organization", "project"} else "page": c.page,
                           "pageSize" if resource in {"organization", "project"} else "size": c.size})
            if c.search_term is not None:
                params["searchTerm"] = c.search_term
        elif action in {"create", "update"}:
            body = {"identifier": getattr(c, "org_identifier" if resource == "organization" else resource + "_identifier"), "name": c.name,
                    "description": c.description, "tags": c.tags}
            if resource != "organization":
                body["orgIdentifier"] = c.org_identifier
            if resource in {"service", "environment"}:
                body["projectIdentifier"] = c.project_identifier
            if resource == "environment":
                body["type"] = c.environment_type
            if resource in {"organization", "project"}:
                body = {resource: body}
        elif action == "execute":
            params["moduleType"] = c.module_type
            body = c.input_set_yaml
        kwargs = {"json": body} if body is not None else {}
        # Fixed provider origin, no redirect or proxy forwarding of the API key.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code, "error": response.text[:2000]}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected a Harness response envelope")
        if data.get("status") not in {None, "SUCCESS"}:
            return {"status": "error", "error": data.get("message") or "Harness returned a failure", "response": data}
        result = {"status": "success", "data": data}
        if action == "list":
            payload = data.get("data")
            if isinstance(payload, dict) and isinstance(payload.get("content"), list):
                result["items"] = [row.get(resource, row) if isinstance(row, dict) else row for row in payload["content"]]
            result["page"] = c.page
        return result
