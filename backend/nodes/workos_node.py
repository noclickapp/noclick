"""WorkOS environment API: organizations, AuthKit and Directory Sync.

Contract: https://github.com/workos/openapi-spec/blob/main/spec/open-api-spec.yaml
Each operation sends one request; lists return one page and its provider cursors.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.workos.com"
ResourceId = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Metadata = dict[Annotated[str, Field(max_length=40)], Annotated[str, Field(max_length=600)]]


class WorkOSAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Workos API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.workos.com/api-keys",
            "x-credential-instructions": "Paste a WorkOS environment API key from the WorkOS dashboard. Select the environment whose organizations and users you want to automate. The key is sent as a Bearer token only to api.workos.com.",
        })
    credential_type: Literal["workos_api_key"] = Field("workos_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    limit: int = Field(10, ge=1, le=100, description="Maximum results in this page; use the returned list_metadata cursors for another page.")
    before: ResourceId | None = None
    after: ResourceId | None = None
    order: Literal["asc", "desc", "normal"] | None = None

    @model_validator(mode="after")
    def one_cursor(self):
        if self.before is not None and self.after is not None:
            raise ValueError("Supply before or after, not both")
        return self


class ListOrganizations(_Page):
    """List organizations in the connected WorkOS environment."""
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})
    search: Text | None = None


class GetOrganization(_Input):
    """Get organization in the connected WorkOS environment."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceId


class CreateOrganization(_Input):
    """Create organization in the connected WorkOS environment."""
    operation: Literal["create_organization"] = Field("create_organization", json_schema_extra={"ui:hidden": True})
    name: Text
    external_id: str | None = Field(None, max_length=128, pattern=r"^[\x00-\x7F]+$")
    metadata: Metadata | None = Field(None, max_length=50)


class UpdateOrganization(_Input):
    """Update organization in the connected WorkOS environment."""
    operation: Literal["update_organization"] = Field("update_organization", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceId
    name: Text
    external_id: str | None = Field(None, max_length=128, pattern=r"^[\x00-\x7F]+$")
    metadata: Metadata | None = Field(None, max_length=50)


class DeleteOrganization(_Input):
    """Delete organization in the connected WorkOS environment."""
    operation: Literal["delete_organization"] = Field("delete_organization", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceId


class ListUsers(_Page):
    """List users in the connected WorkOS environment."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceId | None = None
    email: str | None = None


class GetUser(_Input):
    """Get user in the connected WorkOS environment."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: ResourceId


class CreateUser(_Input):
    """Create user in the connected WorkOS environment."""
    operation: Literal["create_user"] = Field("create_user", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    first_name: Text | None = None
    last_name: Text | None = None
    external_id: str | None = Field(None, max_length=128, pattern=r"^[\x00-\x7F]+$")
    metadata: Metadata | None = Field(None, max_length=50)
    ip_address: str | None = Field(None, description="Originating user IP; required when WorkOS Radar is in Decision mode.")
    user_agent: Text | None = None


class UpdateUser(_Input):
    """Update user in the connected WorkOS environment."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    user_id: ResourceId
    first_name: Text | None = None
    last_name: Text | None = None
    external_id: str | None = Field(None, max_length=128, pattern=r"^[\x00-\x7F]+$")
    metadata: Metadata | None = Field(None, max_length=50)


class DeleteUser(_Input):
    """Delete user in the connected WorkOS environment."""
    operation: Literal["delete_user"] = Field("delete_user", json_schema_extra={"ui:hidden": True})
    user_id: ResourceId


class ListMemberships(_Page):
    """List memberships in the connected WorkOS environment."""
    operation: Literal["list_memberships"] = Field("list_memberships", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceId | None = None
    user_id: ResourceId | None = None


class GetMembership(_Input):
    """Get membership in the connected WorkOS environment."""
    operation: Literal["get_membership"] = Field("get_membership", json_schema_extra={"ui:hidden": True})
    membership_id: ResourceId


class CreateMembership(_Input):
    """Create membership in the connected WorkOS environment."""
    operation: Literal["create_membership"] = Field("create_membership", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceId
    user_id: ResourceId
    role_slug: Text | None = Field(None, description="WorkOS role slug; omission uses the environment default role.")


class UpdateMembership(_Input):
    """Update membership in the connected WorkOS environment."""
    operation: Literal["update_membership"] = Field("update_membership", json_schema_extra={"ui:hidden": True})
    membership_id: ResourceId
    role_slug: Text


class DeleteMembership(_Input):
    """Delete membership in the connected WorkOS environment."""
    operation: Literal["delete_membership"] = Field("delete_membership", json_schema_extra={"ui:hidden": True})
    membership_id: ResourceId


class ListDirectories(_Page):
    """List directories in the connected WorkOS environment."""
    operation: Literal["list_directories"] = Field("list_directories", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceId | None = None
    search: Text | None = None
    domain: Text | None = None


class GetDirectory(_Input):
    """Get directory in the connected WorkOS environment."""
    operation: Literal["get_directory"] = Field("get_directory", json_schema_extra={"ui:hidden": True})
    directory_id: ResourceId


class ListDirectoryUsers(_Page):
    """List directory users in the connected WorkOS environment."""
    operation: Literal["list_directory_users"] = Field("list_directory_users", json_schema_extra={"ui:hidden": True})
    directory: ResourceId | None = None
    group: ResourceId | None = None
    email: str | None = None
    idp_id: Text | None = None


class GetDirectoryUser(_Input):
    """Get directory user in the connected WorkOS environment."""
    operation: Literal["get_directory_user"] = Field("get_directory_user", json_schema_extra={"ui:hidden": True})
    directory_user_id: ResourceId


class ListDirectoryGroups(_Page):
    """List directory groups in the connected WorkOS environment."""
    operation: Literal["list_directory_groups"] = Field("list_directory_groups", json_schema_extra={"ui:hidden": True})
    directory: ResourceId | None = None
    user: ResourceId | None = None


class GetDirectoryGroup(_Input):
    """Get directory group in the connected WorkOS environment."""
    operation: Literal["get_directory_group"] = Field("get_directory_group", json_schema_extra={"ui:hidden": True})
    directory_group_id: ResourceId


class ListConnections(_Page):
    """List connections in the connected WorkOS environment."""
    operation: Literal["list_connections"] = Field("list_connections", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceId | None = None
    search: Text | None = None
    domain: Text | None = None


class GetConnection(_Input):
    """Get connection in the connected WorkOS environment."""
    operation: Literal["get_connection"] = Field("get_connection", json_schema_extra={"ui:hidden": True})
    connection_id: ResourceId


WorkOSConfig = Annotated[Union[
    ListOrganizations,
    GetOrganization,
    CreateOrganization,
    UpdateOrganization,
    DeleteOrganization,
    ListUsers,
    GetUser,
    CreateUser,
    UpdateUser,
    DeleteUser,
    ListMemberships,
    GetMembership,
    CreateMembership,
    UpdateMembership,
    DeleteMembership,
    ListDirectories,
    GetDirectory,
    ListDirectoryUsers,
    GetDirectoryUser,
    ListDirectoryGroups,
    GetDirectoryGroup,
    ListConnections,
    GetConnection
], Field(discriminator="operation")]


class WorkOSFullConfig(NodeConfig[WorkOSConfig, WorkOSAPIKeyCredential]):
    pass


ROUTES = {'list_organizations': ('GET', '/organizations', None),
 'get_organization': ('GET', '/organizations/{id}', 'organization_id'),
 'create_organization': ('POST', '/organizations', None),
 'update_organization': ('PUT', '/organizations/{id}', 'organization_id'),
 'delete_organization': ('DELETE', '/organizations/{id}', 'organization_id'),
 'list_users': ('GET', '/user_management/users', None),
 'get_user': ('GET', '/user_management/users/{id}', 'user_id'),
 'create_user': ('POST', '/user_management/users', None),
 'update_user': ('PUT', '/user_management/users/{id}', 'user_id'),
 'delete_user': ('DELETE', '/user_management/users/{id}', 'user_id'),
 'list_memberships': ('GET', '/user_management/organization_memberships', None),
 'get_membership': ('GET', '/user_management/organization_memberships/{id}', 'membership_id'),
 'create_membership': ('POST', '/user_management/organization_memberships', None),
 'update_membership': ('PUT', '/user_management/organization_memberships/{id}', 'membership_id'),
 'delete_membership': ('DELETE', '/user_management/organization_memberships/{id}', 'membership_id'),
 'list_directories': ('GET', '/directories', None),
 'get_directory': ('GET', '/directories/{id}', 'directory_id'),
 'list_directory_users': ('GET', '/directory_users', None),
 'get_directory_user': ('GET', '/directory_users/{id}', 'directory_user_id'),
 'list_directory_groups': ('GET', '/directory_groups', None),
 'get_directory_group': ('GET', '/directory_groups/{id}', 'directory_group_id'),
 'list_connections': ('GET', '/connections', None),
 'get_connection': ('GET', '/connections/{id}', 'connection_id')}


class WorkOSNode(WorkflowNode):
    integration_type = "automation-workos"
    connection_evidence = ConnectionEvidence(
        noun="organizations", operation="list_organizations", label_keys=("name", "id"))
    edit_examples = ["Create a customer organization", "List directory users", "Add a user to an organization"]

    @classmethod
    def get_config_model(cls):
        return WorkOSFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a WorkOS API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, id_field = ROUTES[op.operation]
        fields = op.model_dump(exclude_none=True, exclude={"operation"})
        if id_field:
            path = path.replace("{id}", quote(fields.pop(id_field), safe=""))
        if method == "PUT" and not fields:
            raise ValueError("Provide at least one field to update")
        kwargs = {"params": fields} if method == "GET" else {"json": fields} if method in {"POST", "PUT"} else {}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            message = response.text.replace(key, "[redacted]")[:2000]
            output = {"status": "error", "http_status": response.status_code, "message": message}
        elif method == "DELETE":
            output = {"status": "success", "http_status": response.status_code,
                "deleted_id": getattr(op, id_field), "deletion_acknowledged": True,
                "absence_verified": False}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("WorkOS response exceeds the supported page size")
            payload = response.json()
            if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
                raise ValueError("WorkOS returned an unexpected response")
            if op.operation.startswith("list_") and not isinstance(payload.get("data"), list):
                raise ValueError("WorkOS returned an invalid list")
            result = payload if op.operation.startswith("list_") else {"data": payload}
            output = {**result, "status": "success", "http_status": response.status_code}
        await self.emit(output)
        return output
