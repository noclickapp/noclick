"""Auth0 Management API v2: users, roles, organizations and logs.

REST reference: https://auth0.com/docs/api/management/v2
Uses a pasted Management API token; no OAuth authorization flow or live trigger.
List operations return one page, preserving Auth0 pagination metadata.
"""
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import normalize_provider_https_origin


class Auth0TokenCredential(BaseModel):
    model_config = ConfigDict(title="Auth0 Token", json_schema_extra={
        "x-credential-url": "https://auth0.com/docs/secure/tokens/access-tokens/management-api-access-tokens",
        "x-credential-instructions": "Paste a Management API access token and your tenant domain from Auth0 Dashboard → Settings. Use the tenant's auth0.com domain, including its region, rather than a custom login domain. Grant read:users for connection verification and the permissions required by your operations. Tokens expire; replace an expired token here.",
    })
    credential_type: Literal["auth0_token"] = Field("auth0_token", json_schema_extra={"ui:hidden": True})
    tenant_domain: str = Field(..., title="Tenant Domain", description="Your Auth0 tenant domain, e.g. example.us.auth0.com.")
    access_token: str = Field(..., min_length=1, title="Access Token", description="Management API bearer token with permissions for the selected operation.", json_schema_extra={"ui:widget": "password"})

    @field_validator("tenant_domain")
    @classmethod
    def normalize_tenant(cls, value: str) -> str:
        return normalize_provider_https_origin(value, "auth0.com", field_name="Tenant Domain", allow_nested_labels=True).removeprefix("https://")


class Auth0Page(BaseModel):
    page: int = Field(0, ge=0, title="Page", description="Zero-based page index. Each run fetches one page.")
    per_page: int = Field(50, ge=1, le=50, title="Results Per Page", description="Maximum results in this page (public cloud limit: 50).")
    include_totals: bool = Field(True, title="Include Totals", description="Return Auth0's pagination metadata alongside the records.")


class Auth0UserID(BaseModel):
    user_id: str = Field(..., min_length=1, title="User ID", description="Auth0 user ID including the identity provider prefix.")


class Auth0RoleID(BaseModel):
    role_id: str = Field(..., min_length=1, title="Role ID", description="ID of the Auth0 role.")


class Auth0OrganizationID(BaseModel):
    organization_id: str = Field(..., min_length=1, title="Organization ID", description="ID of the Auth0 organization.")


class Auth0LogID(BaseModel):
    log_id: str = Field(..., min_length=1, title="Log ID", description="Auth0 log event ID.")


class Auth0UserPage(Auth0UserID, Auth0Page):
    pass


class Auth0OrganizationPage(Auth0OrganizationID, Auth0Page):
    pass


class Auth0CreateUser(BaseModel):
    connection: str = Field(..., min_length=1, title="Connection", description="Name of the connection in which to create the user.")
    email: str | None = Field(None, title="Email", description="User email address.")
    password: str | None = Field(None, title="Password", description="Initial password, required for database connections.", json_schema_extra={"ui:widget": "password"})
    name: str | None = Field(None, title="Name", description="Full name of the user.")
    user_metadata: dict[str, Any] | None = Field(None, title="User Metadata", description="User-editable profile metadata.")
    app_metadata: dict[str, Any] | None = Field(None, title="App Metadata", description="Application-controlled metadata.")
    verify_email: bool = Field(False, title="Send Verification Email", description="Ask Auth0 to email this user a verification link.")


class Auth0UpdateUser(Auth0UserID):
    name: str | None = Field(None, title="Name", description="New full name.")
    email: str | None = Field(None, title="Email", description="New email address.")
    blocked: bool | None = Field(None, title="Blocked", description="Block or unblock this user.")
    user_metadata: dict[str, Any] | None = Field(None, title="User Metadata", description="Profile metadata to merge with existing metadata.")
    app_metadata: dict[str, Any] | None = Field(None, title="App Metadata", description="Application metadata to merge with existing metadata.")


class Auth0UserRoles(Auth0UserID):
    roles: list[str] = Field(..., min_length=1, title="Role IDs", description="Array of role IDs to assign or remove.")


class Auth0CreateRole(BaseModel):
    name: str = Field(..., min_length=1, title="Name", description="Name of the role.")
    description: str | None = Field(None, title="Description", description="Description of the role.")


class Auth0UpdateRole(Auth0RoleID):
    name: str | None = Field(None, title="Name", description="New role name.")
    description: str | None = Field(None, title="Description", description="New role description.")


class Auth0CreateOrganization(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, title="Name", description="Organization name: lowercase letters, digits, underscores and hyphens.")
    display_name: str | None = Field(None, title="Display Name", description="Friendly organization name.")
    metadata: dict[str, str] | None = Field(None, title="Metadata", description="Organization metadata as string key/value pairs.")


class Auth0OrganizationMembers(Auth0OrganizationID):
    members: list[str] = Field(..., min_length=1, max_length=10, title="User IDs", description="Array of up to ten Auth0 user IDs to add or remove.")


class Auth0ListUsersConfig(Auth0Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"const": "list_users", "ui:hidden": True, "x-category": "Users", "x-is-trigger": False})
    q: str | None = Field(None, title="Search Query", description="Lucene query, e.g. email:john.doe@gmail.com. Search is eventually consistent.")
    search_engine: Literal["v3"] = Field("v3", title="Search Engine", description="Auth0 user search engine version.")


class Auth0GetUserConfig(Auth0UserID):
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"const": "get_user", "ui:hidden": True, "x-category": "Users", "x-is-trigger": False})


class Auth0CreateUserConfig(Auth0CreateUser):
    operation: Literal["create_user"] = Field("create_user", title="Create User", json_schema_extra={"const": "create_user", "ui:hidden": True, "x-category": "Users", "x-is-trigger": False})


class Auth0UpdateUserConfig(Auth0UpdateUser):
    operation: Literal["update_user"] = Field("update_user", title="Update User", json_schema_extra={"const": "update_user", "ui:hidden": True, "x-category": "Users", "x-is-trigger": False})


class Auth0DeleteUserConfig(Auth0UserID):
    operation: Literal["delete_user"] = Field("delete_user", title="Delete User", json_schema_extra={"const": "delete_user", "ui:hidden": True, "x-category": "Users", "x-is-trigger": False})


class Auth0ListUserRolesConfig(Auth0UserPage):
    operation: Literal["list_user_roles"] = Field("list_user_roles", title="List User Roles", json_schema_extra={"const": "list_user_roles", "ui:hidden": True, "x-category": "Roles", "x-is-trigger": False})


class Auth0AssignUserRolesConfig(Auth0UserRoles):
    operation: Literal["assign_user_roles"] = Field("assign_user_roles", title="Assign User Roles", json_schema_extra={"const": "assign_user_roles", "ui:hidden": True, "x-category": "Roles", "x-is-trigger": False})


class Auth0RemoveUserRolesConfig(Auth0UserRoles):
    operation: Literal["remove_user_roles"] = Field("remove_user_roles", title="Remove User Roles", json_schema_extra={"const": "remove_user_roles", "ui:hidden": True, "x-category": "Roles", "x-is-trigger": False})


class Auth0ListRolesConfig(Auth0Page):
    operation: Literal["list_roles"] = Field("list_roles", title="List Roles", json_schema_extra={"const": "list_roles", "ui:hidden": True, "x-category": "Roles", "x-is-trigger": False})
    name_filter: str | None = Field(None, title="Name Filter", description="Filter roles by name.")


class Auth0CreateRoleConfig(Auth0CreateRole):
    operation: Literal["create_role"] = Field("create_role", title="Create Role", json_schema_extra={"const": "create_role", "ui:hidden": True, "x-category": "Roles", "x-is-trigger": False})


class Auth0UpdateRoleConfig(Auth0UpdateRole):
    operation: Literal["update_role"] = Field("update_role", title="Update Role", json_schema_extra={"const": "update_role", "ui:hidden": True, "x-category": "Roles", "x-is-trigger": False})


class Auth0DeleteRoleConfig(Auth0RoleID):
    operation: Literal["delete_role"] = Field("delete_role", title="Delete Role", json_schema_extra={"const": "delete_role", "ui:hidden": True, "x-category": "Roles", "x-is-trigger": False})


class Auth0ListOrganizationsConfig(Auth0Page):
    operation: Literal["list_organizations"] = Field("list_organizations", title="List Organizations", json_schema_extra={"const": "list_organizations", "ui:hidden": True, "x-category": "Organizations", "x-is-trigger": False})


class Auth0GetOrganizationConfig(Auth0OrganizationID):
    operation: Literal["get_organization"] = Field("get_organization", title="Get Organization", json_schema_extra={"const": "get_organization", "ui:hidden": True, "x-category": "Organizations", "x-is-trigger": False})


class Auth0CreateOrganizationConfig(Auth0CreateOrganization):
    operation: Literal["create_organization"] = Field("create_organization", title="Create Organization", json_schema_extra={"const": "create_organization", "ui:hidden": True, "x-category": "Organizations", "x-is-trigger": False})


class Auth0ListOrganizationMembersConfig(Auth0OrganizationPage):
    operation: Literal["list_organization_members"] = Field("list_organization_members", title="List Organization Members", json_schema_extra={"const": "list_organization_members", "ui:hidden": True, "x-category": "Organizations", "x-is-trigger": False})


class Auth0AddOrganizationMembersConfig(Auth0OrganizationMembers):
    operation: Literal["add_organization_members"] = Field("add_organization_members", title="Add Organization Members", json_schema_extra={"const": "add_organization_members", "ui:hidden": True, "x-category": "Organizations", "x-is-trigger": False})


class Auth0RemoveOrganizationMembersConfig(Auth0OrganizationMembers):
    operation: Literal["remove_organization_members"] = Field("remove_organization_members", title="Remove Organization Members", json_schema_extra={"const": "remove_organization_members", "ui:hidden": True, "x-category": "Organizations", "x-is-trigger": False})


class Auth0ListLogsConfig(Auth0Page):
    operation: Literal["list_logs"] = Field("list_logs", title="List Logs", json_schema_extra={"const": "list_logs", "ui:hidden": True, "x-category": "Logs", "x-is-trigger": False})
    search: str | None = Field(None, title="Search Query", description="Lucene query over tenant log events.")
    sort: str | None = Field(None, title="Sort", description="Sort by date, e.g. date:-1 for newest first.")


class Auth0GetLogConfig(Auth0LogID):
    operation: Literal["get_log"] = Field("get_log", title="Get Log", json_schema_extra={"const": "get_log", "ui:hidden": True, "x-category": "Logs", "x-is-trigger": False})


Auth0Operation = Annotated[Union[
    Auth0ListUsersConfig,
    Auth0GetUserConfig,
    Auth0CreateUserConfig,
    Auth0UpdateUserConfig,
    Auth0DeleteUserConfig,
    Auth0ListUserRolesConfig,
    Auth0AssignUserRolesConfig,
    Auth0RemoveUserRolesConfig,
    Auth0ListRolesConfig,
    Auth0CreateRoleConfig,
    Auth0UpdateRoleConfig,
    Auth0DeleteRoleConfig,
    Auth0ListOrganizationsConfig,
    Auth0GetOrganizationConfig,
    Auth0CreateOrganizationConfig,
    Auth0ListOrganizationMembersConfig,
    Auth0AddOrganizationMembersConfig,
    Auth0RemoveOrganizationMembersConfig,
    Auth0ListLogsConfig,
    Auth0GetLogConfig
], Field(discriminator="operation")]


class Auth0NodeConfig(NodeConfig[Auth0Operation, Auth0TokenCredential]):
    pass


# One entry per documented API operation; path IDs never enter query or body.
_ENDPOINTS = {
    "list_users": ('GET', '/users', None, 'users'),
    "get_user": ('GET', '/users/{id}', 'user_id', None),
    "create_user": ('POST', '/users', None, None),
    "update_user": ('PATCH', '/users/{id}', 'user_id', None),
    "delete_user": ('DELETE', '/users/{id}', 'user_id', None),
    "list_user_roles": ('GET', '/users/{id}/roles', 'user_id', 'roles'),
    "assign_user_roles": ('POST', '/users/{id}/roles', 'user_id', None),
    "remove_user_roles": ('DELETE', '/users/{id}/roles', 'user_id', None),
    "list_roles": ('GET', '/roles', None, 'roles'),
    "create_role": ('POST', '/roles', None, None),
    "update_role": ('PATCH', '/roles/{id}', 'role_id', None),
    "delete_role": ('DELETE', '/roles/{id}', 'role_id', None),
    "list_organizations": ('GET', '/organizations', None, 'organizations'),
    "get_organization": ('GET', '/organizations/{id}', 'organization_id', None),
    "create_organization": ('POST', '/organizations', None, None),
    "list_organization_members": ('GET', '/organizations/{id}/members', 'organization_id', 'members'),
    "add_organization_members": ('POST', '/organizations/{id}/members', 'organization_id', None),
    "remove_organization_members": ('DELETE', '/organizations/{id}/members', 'organization_id', None),
    "list_logs": ('GET', '/logs', None, 'logs'),
    "get_log": ('GET', '/logs/{id}', 'log_id', None),
}


class Auth0Node(WorkflowNode):
    integration_type = "automation-auth0"
    credential_provider_labels = {"auth0": "Auth0 Account"}
    connection_evidence = ConnectionEvidence(operation="list_users", operation_arguments={"per_page": 3}, noun="users")

    @classmethod
    def get_config_model(cls):
        return Auth0NodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, Auth0NodeConfig):
            raise ValueError("Valid Auth0 configuration is required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Auth0 Management API token")
        config = self.config.config
        action = config.operation
        method, path, id_field, collection = _ENDPOINTS[action]
        fields = config.model_dump(exclude_none=True, exclude={"operation"})
        if id_field:
            path = path.replace("{id}", quote(fields.pop(id_field), safe=""))
        if action.startswith("update_") and not fields:
            raise ValueError("Supply at least one field to update")
        kwargs = {"params": fields} if method == "GET" else ({"json": fields} if fields else {})
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(
                    method, f"https://{credential.tenant_domain}/api/v2{path}",
                    headers={"Authorization": f"Bearer {credential.access_token}", "Accept": "application/json", "Content-Type": "application/json"},
                    **kwargs,
                )
            timing = {"api_request": round((time.perf_counter() - started) * 1000, 2)}
            if not response.is_success:
                try:
                    error = response.json()
                except ValueError:
                    error = response.text
                return {"status": "error", "action": action, "status_code": response.status_code, "error": error, "timing_ms": timing}
            payload = response.json() if response.content else {}
            if collection and isinstance(payload, list):
                data = {collection: payload, "count": len(payload)}
            elif isinstance(payload, dict):
                data = payload
            else:
                raise ValueError("Unexpected Auth0 response shape")
            return {"status": "success", "action": action, "data": data, "timing_ms": timing}
        except httpx.RequestError as exc:
            return {"status": "error", "action": action, "error": str(exc), "timing_ms": {"api_request": round((time.perf_counter() - started) * 1000, 2)}}
