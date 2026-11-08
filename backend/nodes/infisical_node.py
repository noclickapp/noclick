"""Infisical Cloud API operations using a pasted machine identity Token Auth token.

Contract: https://app.infisical.com/api/docs/json (0.0.1).
Token setup: https://infisical.com/docs/documentation/platform/identities/token-auth
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class InfisicalTokenCredential(BaseModel):
    model_config = ConfigDict(title="Infisical API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://infisical.com/docs/documentation/platform/identities/token-auth",
            "x-credential-instructions": "In Organization > Access Control > Machine Identities, configure Token Auth and add a token. Add the identity to each project with the required role. Paste that token here without Bearer. Replace expired tokens manually. Choose the cloud region containing your organization.",
        })
    credential_type: Literal["infisical_api_token"] = Field("infisical_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu"] = Field("us", title="Cloud Region")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("project_id", "secret_name", "folder_id", "tag_id", "environment", mode="before", check_fields=False)
    @classmethod
    def path_segment(cls, value):
        if not isinstance(value, str) or value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Use a resource identifier without controls or dot segments")
        return value


class _Project(_Input):
    project_id: str = Field(..., min_length=1, title="Project ID")


class _Location(_Project):
    environment: str = Field(..., min_length=1, title="Environment Slug")
    secret_path: str = Field("/", title="Secret Path", description="Absolute folder path within the environment.")


class _Secret(_Location):
    secret_name: str = Field(..., min_length=1, title="Secret Name")
    secret_type: Literal["shared", "personal"] = Field("shared", title="Secret Type")


class _Tag(_Project):
    tag_id: str = Field(..., min_length=1, title="Tag ID")


class ListProjects(_Input):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})


class GetProject(_Project):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})


class CreateProject(_Input):
    operation: Literal["create_project"] = Field("create_project", title="Create Project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=64, title="Project Name")
    description: str | None = Field(None, max_length=1024)


class UpdateProject(_Project):
    operation: Literal["update_project"] = Field("update_project", title="Update Project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(None, max_length=1024)


class ListSecrets(_Location):
    operation: Literal["list_secrets"] = Field("list_secrets", title="List Secrets", json_schema_extra={"ui:hidden": True})
    recursive: bool = Field(False)
    include_imports: bool = Field(True)
    view_secret_value: bool = Field(True, description="Secret values appear in workflow output when enabled.")


class GetSecret(_Secret):
    operation: Literal["get_secret"] = Field("get_secret", title="Get Secret", json_schema_extra={"ui:hidden": True})
    version: int | None = Field(None, ge=1)
    view_secret_value: bool = Field(True, description="Secret values appear in workflow output when enabled.")


class CreateSecret(_Secret):
    operation: Literal["create_secret"] = Field("create_secret", title="Create Secret", json_schema_extra={"ui:hidden": True})
    secret_value: str = Field(..., title="Secret Value", json_schema_extra={"ui:widget": "password"})
    secret_comment: str | None = Field(None, title="Secret Comment")


class UpdateSecret(_Secret):
    operation: Literal["update_secret"] = Field("update_secret", title="Update Secret", json_schema_extra={"ui:hidden": True})
    secret_value: str = Field(..., title="Secret Value", json_schema_extra={"ui:widget": "password"})
    secret_comment: str | None = Field(None, title="Secret Comment")


class DeleteSecret(_Secret):
    operation: Literal["delete_secret"] = Field("delete_secret", title="Delete Secret", json_schema_extra={"ui:hidden": True})


class ListFolders(_Location):
    operation: Literal["list_folders"] = Field("list_folders", title="List Folders", json_schema_extra={"ui:hidden": True})
    recursive: bool = Field(False)


class CreateFolder(_Location):
    operation: Literal["create_folder"] = Field("create_folder", title="Create Folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    description: str | None = None


class UpdateFolder(_Location):
    operation: Literal["update_folder"] = Field("update_folder", title="Update Folder", json_schema_extra={"ui:hidden": True})
    folder_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str | None = None


class DeleteFolder(_Location):
    operation: Literal["delete_folder"] = Field("delete_folder", title="Delete Folder", json_schema_extra={"ui:hidden": True})
    folder_id: str = Field(..., min_length=1, description="Folder ID or name.")
    force_delete: bool = Field(False, description="Allow deletion even when the folder contains resources.")


class GetEnvironment(_Project):
    operation: Literal["get_environment"] = Field("get_environment", title="Get Environment", json_schema_extra={"ui:hidden": True})
    environment: str = Field(..., min_length=1, title="Environment Slug")


class CreateEnvironment(_Project):
    operation: Literal["create_environment"] = Field("create_environment", title="Create Environment", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=64)
    position: int | None = Field(None, ge=1)


class ListTags(_Project):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})


class GetTag(_Tag):
    operation: Literal["get_tag"] = Field("get_tag", title="Get Tag", json_schema_extra={"ui:hidden": True})


class CreateTag(_Project):
    operation: Literal["create_tag"] = Field("create_tag", title="Create Tag", json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=1, max_length=64)
    color: str = Field(..., min_length=1)


class UpdateTag(_Tag):
    operation: Literal["update_tag"] = Field("update_tag", title="Update Tag", json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=1, max_length=64)
    color: str = Field(..., min_length=1)


class DeleteTag(_Tag):
    operation: Literal["delete_tag"] = Field("delete_tag", title="Delete Tag", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListProjects, GetProject, CreateProject, UpdateProject, ListSecrets, GetSecret, CreateSecret, UpdateSecret, DeleteSecret, ListFolders, CreateFolder, UpdateFolder, DeleteFolder, GetEnvironment, CreateEnvironment, ListTags, GetTag, CreateTag, UpdateTag, DeleteTag], Field(discriminator="operation")]


class InfisicalNodeConfig(NodeConfig[Operation, InfisicalTokenCredential]):
    pass


ROUTES = {'list_projects': ('GET', '/api/v1/projects', {}, {}),
 'get_project': ('GET', '/api/v1/projects/{project_id}', {}, {}),
 'create_project': ('POST',
                    '/api/v1/projects',
                    {'name': 'projectName', 'description': 'projectDescription'},
                    {}),
 'update_project': ('PATCH',
                    '/api/v1/projects/{project_id}',
                    {'name': 'name', 'description': 'description'},
                    {}),
 'list_secrets': ('GET',
                  '/api/v4/secrets',
                  {},
                  {'project_id': 'projectId',
                   'environment': 'environment',
                   'secret_path': 'secretPath',
                   'recursive': 'recursive',
                   'include_imports': 'includeImports',
                   'view_secret_value': 'viewSecretValue'}),
 'get_secret': ('GET',
                '/api/v4/secrets/{secret_name}',
                {},
                {'project_id': 'projectId',
                 'environment': 'environment',
                 'secret_path': 'secretPath',
                 'secret_type': 'type',
                 'version': 'version',
                 'view_secret_value': 'viewSecretValue'}),
 'create_secret': ('POST',
                   '/api/v4/secrets/{secret_name}',
                   {'project_id': 'projectId',
                    'environment': 'environment',
                    'secret_path': 'secretPath',
                    'secret_type': 'type',
                    'secret_value': 'secretValue',
                    'secret_comment': 'secretComment'},
                   {}),
 'update_secret': ('PATCH',
                   '/api/v4/secrets/{secret_name}',
                   {'project_id': 'projectId',
                    'environment': 'environment',
                    'secret_path': 'secretPath',
                    'secret_type': 'type',
                    'secret_value': 'secretValue',
                    'secret_comment': 'secretComment'},
                   {}),
 'delete_secret': ('DELETE',
                   '/api/v4/secrets/{secret_name}',
                   {'project_id': 'projectId',
                    'environment': 'environment',
                    'secret_path': 'secretPath',
                    'secret_type': 'type'},
                   {}),
 'list_folders': ('GET',
                  '/api/v2/folders',
                  {},
                  {'project_id': 'projectId',
                   'environment': 'environment',
                   'secret_path': 'path',
                   'recursive': 'recursive'}),
 'create_folder': ('POST',
                   '/api/v2/folders',
                   {'project_id': 'projectId',
                    'environment': 'environment',
                    'secret_path': 'path',
                    'name': 'name',
                    'description': 'description'},
                   {}),
 'update_folder': ('PATCH',
                   '/api/v2/folders/{folder_id}',
                   {'project_id': 'projectId',
                    'environment': 'environment',
                    'secret_path': 'path',
                    'name': 'name',
                    'description': 'description'},
                   {}),
 'delete_folder': ('DELETE',
                   '/api/v2/folders/{folder_id}',
                   {'project_id': 'projectId',
                    'environment': 'environment',
                    'secret_path': 'path',
                    'force_delete': 'forceDelete'},
                   {}),
 'get_environment': ('GET',
                     '/api/v1/projects/{project_id}/environments/slug/{environment}',
                     {},
                     {}),
 'create_environment': ('POST',
                        '/api/v1/projects/{project_id}/environments',
                        {'name': 'name', 'slug': 'slug', 'position': 'position'},
                        {}),
 'list_tags': ('GET', '/api/v1/projects/{project_id}/tags', {}, {}),
 'get_tag': ('GET', '/api/v1/projects/{project_id}/tags/{tag_id}', {}, {}),
 'create_tag': ('POST',
                '/api/v1/projects/{project_id}/tags',
                {'slug': 'slug', 'color': 'color'},
                {}),
 'update_tag': ('PATCH',
                '/api/v1/projects/{project_id}/tags/{tag_id}',
                {'slug': 'slug', 'color': 'color'},
                {}),
 'delete_tag': ('DELETE', '/api/v1/projects/{project_id}/tags/{tag_id}', {}, {})}


class InfisicalNode(WorkflowNode):
    integration_type = "automation-infisical"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects")

    @classmethod
    def get_config_model(cls):
        return InfisicalNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Infisical API token")
        credential = self.config.credentials
        operation = self.config.config
        values = operation.model_dump()
        method, template, body_fields, query_fields = ROUTES[operation.operation]
        path = template.format_map({key: quote(str(value), safe="") for key, value in values.items()})
        body = {target: values[source] for source, target in body_fields.items() if values[source] is not None}
        params = {target: str(values[source]).lower() if isinstance(values[source], bool) else values[source]
                  for source, target in query_fields.items() if values[source] is not None}
        base = {"us": "https://us.infisical.com", "eu": "https://eu.infisical.com"}[credential.region]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, base + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    params=params, **({"json": body} if body_fields else {}))
        except httpx.HTTPError:
            raise ValueError("Infisical request failed; inspect the provider before retrying a write") from None
        if not response.is_success:
            try:
                message = response.json().get("message", "Infisical rejected the request")
            except (ValueError, AttributeError):
                message = "Infisical rejected the request"
            message = str(message).replace(credential.api_token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "message": message}
        if response.status_code == 204:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Infisical returned an invalid JSON response") from None
            if not isinstance(data, (dict, list)):
                raise ValueError("Infisical returned an unexpected response shape")
        return {"status": "success", "action": operation.operation, "data": data}
