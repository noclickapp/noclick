"""JumpCloud Console API: explicit, single-request directory operations.

Contract: https://docs.jumpcloud.com/new/console/index.yaml (version 1.0).
API keys belong to an administrator; JumpCloud enforces their permissions.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class JumpcloudAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Jumpcloud API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.jumpcloud.com/",
            "x-credential-instructions": "In the JumpCloud Admin Console, open your username menu and My API Key. Paste your administrator API key. It grants your administrator's access; keep it private. Select the region containing your organization. Optionally enter an organization ID for multi-tenant access.",
        })
    credential_type: Literal["jumpcloud_api_key"] = Field("jumpcloud_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu", "in"] = Field("us", title="Region")
    organization_id: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Organization ID")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(100, ge=1, le=100, description="Maximum records per page.")
    skip: int = Field(0, ge=0, le=100000000, description="Offset; use next_skip to request another page.")


class _UserFields(_Input):
    firstname: str | None = Field(None, max_length=1000)
    lastname: str | None = Field(None, max_length=1000)
    department: str | None = Field(None, max_length=1000)
    jobTitle: str | None = Field(None, max_length=1000)
    company: str | None = Field(None, max_length=1000)


class ListOrganizations(_Page):
    operation: Literal["list_organizations"] = Field("list_organizations", title="List Organizations", json_schema_extra={"ui:hidden": True})


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})


class GetUser(_Input):
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="User ID")


class CreateUser(_UserFields):
    displayname: str | None = Field(None, max_length=1000)
    operation: Literal["create_user"] = Field("create_user", title="Create User", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=1000)
    email: str = Field(..., min_length=1, max_length=1000)


class UpdateUser(_UserFields):
    operation: Literal["update_user"] = Field("update_user", title="Update User", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="User ID")


class DeleteUser(_Input):
    """Permanently delete this resource. Provider-side consequences apply."""
    operation: Literal["delete_user"] = Field("delete_user", title="Delete User", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="User ID")


class ListSystems(_Page):
    operation: Literal["list_systems"] = Field("list_systems", title="List Systems", json_schema_extra={"ui:hidden": True})


class GetSystem(_Input):
    operation: Literal["get_system"] = Field("get_system", title="Get System", json_schema_extra={"ui:hidden": True})
    system_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="System ID")


class UpdateSystem(_Input):
    operation: Literal["update_system"] = Field("update_system", title="Update System", json_schema_extra={"ui:hidden": True})
    system_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="System ID")
    displayName: str = Field(..., min_length=1, max_length=1000)


class DeleteSystem(_Input):
    """Permanently delete this resource. Provider-side consequences apply."""
    operation: Literal["delete_system"] = Field("delete_system", title="Delete System", json_schema_extra={"ui:hidden": True})
    system_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="System ID")


class ListUserGroups(_Page):
    operation: Literal["list_user_groups"] = Field("list_user_groups", title="List User Groups", json_schema_extra={"ui:hidden": True})


class GetUserGroup(_Input):
    operation: Literal["get_user_group"] = Field("get_user_group", title="Get User Group", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Group ID")


class CreateUserGroup(_Input):
    operation: Literal["create_user_group"] = Field("create_user_group", title="Create User Group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=4000)


class DeleteUserGroup(_Input):
    """Permanently delete this resource. Provider-side consequences apply."""
    operation: Literal["delete_user_group"] = Field("delete_user_group", title="Delete User Group", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Group ID")


class ListUserGroupMembers(_Page):
    operation: Literal["list_user_group_members"] = Field("list_user_group_members", title="List User Group Members", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Group ID")


class ManageUserGroupMembership(_Input):
    """Add or remove a direct member of a static group."""
    operation: Literal["manage_user_group_membership"] = Field("manage_user_group_membership", title="Manage User Group Membership", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Group ID")
    member_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="User ID")
    op: Literal["add", "remove"] = Field(..., title="Membership action")


class ListSystemGroups(_Page):
    operation: Literal["list_system_groups"] = Field("list_system_groups", title="List System Groups", json_schema_extra={"ui:hidden": True})


class GetSystemGroup(_Input):
    operation: Literal["get_system_group"] = Field("get_system_group", title="Get System Group", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Group ID")


class CreateSystemGroup(_Input):
    operation: Literal["create_system_group"] = Field("create_system_group", title="Create System Group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=4000)


class DeleteSystemGroup(_Input):
    """Permanently delete this resource. Provider-side consequences apply."""
    operation: Literal["delete_system_group"] = Field("delete_system_group", title="Delete System Group", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Group ID")


class ListSystemGroupMembers(_Page):
    operation: Literal["list_system_group_members"] = Field("list_system_group_members", title="List System Group Members", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Group ID")


class ManageSystemGroupMembership(_Input):
    """Add or remove a direct member of a static group."""
    operation: Literal["manage_system_group_membership"] = Field("manage_system_group_membership", title="Manage System Group Membership", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Group ID")
    member_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="System ID")
    op: Literal["add", "remove"] = Field(..., title="Membership action")


# JumpCloud's own MCP server: agents get its tools through a person's JumpCloud sign-in.
# JumpCloud's US instance; its EU and India instances run their own servers.
JumpcloudMcpCredential = mcp_credential("jumpcloud", "https://mcp.jumpcloud.com/v1", app="JumpCloud")
JumpcloudCredential = Union[JumpcloudAPIKeyCredential, JumpcloudMcpCredential]


Operation = Annotated[Union[ListOrganizations, ListUsers, GetUser, CreateUser, UpdateUser, DeleteUser, ListSystems, GetSystem, UpdateSystem, DeleteSystem, ListUserGroups, GetUserGroup, CreateUserGroup, DeleteUserGroup, ListUserGroupMembers, ManageUserGroupMembership, ListSystemGroups, GetSystemGroup, CreateSystemGroup, DeleteSystemGroup, ListSystemGroupMembers, ManageSystemGroupMembership], Field(discriminator="operation")]


class JumpcloudConfig(NodeConfig[Operation, JumpcloudCredential]):
    pass


ROUTES = {'list_organizations': ('GET', '/api/organizations'),
 'list_users': ('GET', '/api/systemusers'),
 'get_user': ('GET', '/api/systemusers/{user_id}'),
 'create_user': ('POST', '/api/systemusers'),
 'update_user': ('PUT', '/api/systemusers/{user_id}'),
 'delete_user': ('DELETE', '/api/systemusers/{user_id}'),
 'list_systems': ('GET', '/api/systems'),
 'get_system': ('GET', '/api/systems/{system_id}'),
 'update_system': ('PUT', '/api/systems/{system_id}'),
 'delete_system': ('DELETE', '/api/systems/{system_id}'),
 'list_user_groups': ('GET', '/api/v2/usergroups'),
 'get_user_group': ('GET', '/api/v2/usergroups/{group_id}'),
 'create_user_group': ('POST', '/api/v2/usergroups'),
 'delete_user_group': ('DELETE', '/api/v2/usergroups/{group_id}'),
 'list_user_group_members': ('GET', '/api/v2/usergroups/{group_id}/members'),
 'manage_user_group_membership': ('POST', '/api/v2/usergroups/{group_id}/members'),
 'list_system_groups': ('GET', '/api/v2/systemgroups'),
 'get_system_group': ('GET', '/api/v2/systemgroups/{group_id}'),
 'create_system_group': ('POST', '/api/v2/systemgroups'),
 'delete_system_group': ('DELETE', '/api/v2/systemgroups/{group_id}'),
 'list_system_group_members': ('GET', '/api/v2/systemgroups/{group_id}/members'),
 'manage_system_group_membership': ('POST', '/api/v2/systemgroups/{group_id}/members')}


class JumpcloudNode(WorkflowNode):
    integration_type = "automation-jumpcloud"
    credential_provider_labels = {"jumpcloud": "JumpCloud Account"}
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="organizations", label_keys=("displayName", "name", "_id", "id"))

    @classmethod
    def get_config_model(cls):
        return JumpcloudConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a JumpCloud API key")
        config, credential = self.config.config, self.config.credentials
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        params = values if config.operation.startswith("list_") else None
        body = values if method in {"POST", "PUT"} else None
        if config.operation.startswith("manage_"):
            body = {"id": values["member_id"], "op": values["op"],
                    "type": "user" if "user_group" in config.operation else "system"}
        if method == "PUT" and not body:
            raise ValueError("Supply at least one field to update")
        origin = {"us": "https://console.jumpcloud.com", "eu": "https://console.eu.jumpcloud.com", "in": "https://console.in.jumpcloud.com"}[credential.region]
        headers = {"x-api-key": credential.api_key, "Accept": "application/json", "Content-Type": "application/json"}
        # Organization listing has no documented x-org-id parameter.
        if credential.organization_id and config.operation != "list_organizations":
            headers["x-org-id"] = credential.organization_id
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, origin + path, headers=headers, params=params, json=body)
        if not 200 <= response.status_code < 300:
            message = response.text.replace(credential.api_key, "[redacted]")[:4000]
            result = {"status": "error", "status_code": response.status_code, "error": message or "JumpCloud rejected the request"}
        elif response.status_code == 204:
            result = {"status": "success", "acknowledged": True, "status_code": 204}
        else:
            data = response.json()
            if isinstance(data, dict) and ("error" in data or "errors" in data):
                raise ValueError("JumpCloud returned an error response")
            if config.operation.startswith("list_"):
                rows = data.get("results") if isinstance(data, dict) else data
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("JumpCloud returned an unexpected collection")
                total = data.get("totalCount") if isinstance(data, dict) else None
                if total is not None and (type(total) is not int or total < 0):
                    raise ValueError("JumpCloud returned an invalid total count")
                next_skip = config.skip + len(rows)
                has_more = bool(rows) and (next_skip < total if total is not None else len(rows) == config.limit)
                result = {"status": "success", "items": rows, "total_count": total,
                          "has_more": has_more, "next_skip": next_skip if has_more else None}
            else:
                if not isinstance(data, dict):
                    raise ValueError("JumpCloud returned an unexpected record")
                result = {"status": "success", "item": data, "status_code": response.status_code}
        await self.emit(result)
        return result
