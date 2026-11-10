"""Peerdom Public API v0.10.0: organization structure and project automation.

Contract: https://api.peerdom.org/v1/docs. Each operation makes one API call.
There is no documented webhook registration or time-ordered/filtered list API.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.peerdom.app/v1"
RESOURCE_ID = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]
CUSTOM_FIELDS = dict[str, Union[str, list[str]]]


class PeerdomAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Peerdom API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.peerdom.org/v1/docs#section/Authentication",
            "x-credential-instructions": "Create an API key in your Peerdom organization's settings and paste it here. API access requires an active paid subscription or trial. The key selects the organization and is sent as X-Api-Key to api.peerdom.app.",
        },
    )
    credential_type: Literal["peerdom_api_key"] = Field("peerdom_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(50, ge=1, le=100, description="Maximum items in this page. A full page may have more results; advance using next_offset.")
    offset: int = Field(0, ge=0, description="Number of items to skip, starting at zero.")


class GetTenant(_Input):
    """Get the organization selected by this API key, including its palette and live map."""
    operation: Literal["get_tenant"] = "get_tenant"


class ListMaps(_Input):
    """List organization maps, including draft and archived metadata."""
    operation: Literal["list_maps"] = "list_maps"


class ListPeers(_Page):
    """List a page of active peers, optionally including former peers and custom fields."""
    operation: Literal["list_peers"] = "list_peers"
    include_former: bool = False
    include_custom_fields: bool = False


class GetPeer(_Input):
    """Get a peer, optionally including roles, former peers and custom fields."""
    operation: Literal["get_peer"] = "get_peer"
    peer_id: RESOURCE_ID
    include_former: bool = False
    include_roles: bool = False
    include_custom_fields: bool = False


class _PeerFields(_Input):
    first_name: str | None = Field(None, min_length=1)
    last_name: str | None = None
    nick_name: str | None = None
    email: EmailStr | None = None
    birthdate: date | None = None
    percentage: int | None = Field(None, description="Contribution percentage; requires the Contribution app.")
    custom_fields: CUSTOM_FIELDS | None = Field(None, description="Existing custom-field names mapped to a string or list of strings.")


class CreatePeer(_PeerFields):
    """Create a peer. An email links/provisions an account as a guest; no invitation is sent."""
    operation: Literal["create_peer"] = "create_peer"
    first_name: str = Field(..., min_length=1)


class UpdatePeer(_PeerFields):
    """Update supplied peer profile fields. Access permissions are managed in Peerdom's UI."""
    operation: Literal["update_peer"] = "update_peer"
    peer_id: RESOURCE_ID


class DeletePeer(_Input):
    """Delete a peer from this organization."""
    operation: Literal["delete_peer"] = "delete_peer"
    peer_id: RESOURCE_ID


class ListRoles(_Page):
    """List roles from the live map or a selected map. A peer filter overrides the group filter."""
    operation: Literal["list_roles"] = "list_roles"
    peer_id: RESOURCE_ID | None = None
    group_id: RESOURCE_ID | None = None
    map_id: RESOURCE_ID | None = None
    include_holders: bool = False
    include_custom_fields: bool = False
    include_groups: bool = False
    include_representing: bool = False


class GetRole(_Input):
    """Get a role from a live or draft map, with optional related data."""
    operation: Literal["get_role"] = "get_role"
    role_id: RESOURCE_ID
    include_holders: bool = False
    include_custom_fields: bool = False
    include_groups: bool = False
    include_representing: bool = False


class _NodeFields(_Input):
    name: str | None = Field(None, min_length=1)
    parent_id: RESOURCE_ID | None = None
    external: bool | None = Field(None, description="True detaches from its parent; false attaches under the map's root circle. A supplied parent reattaches an external node.")
    color: str | None = Field(None, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", description="Hex color; must be in the tenant palette if personal colors are disabled. Get tenant shows that palette.")
    shape: Literal["circle", "hexagon"] | None = None
    custom_fields: CUSTOM_FIELDS | None = None
    group_email: str | None = None


class _RoleFields(_NodeFields):
    electable: bool | None = None
    target: float | None = Field(None, ge=0, description="Contribution target as a percentage: 100 = 1 FTE. Requires the Contribution app.")


class CreateRole(_RoleFields):
    """Create a role in a selected map and parent circle."""
    operation: Literal["create_role"] = "create_role"
    name: str = Field(..., min_length=1)
    map_id: RESOURCE_ID
    parent_id: RESOURCE_ID
    representing_id: RESOURCE_ID | None = Field(None, description="Must identify this role's parent group.")


class UpdateRole(_RoleFields):
    """Update supplied fields on a role in a live or draft map."""
    operation: Literal["update_role"] = "update_role"
    role_id: RESOURCE_ID


class DeleteRole(_Input):
    """Delete a role from a live or draft map, excluding archived maps."""
    operation: Literal["delete_role"] = "delete_role"
    role_id: RESOURCE_ID


class AssignRole(_Input):
    """Assign an existing role to a peer, optionally setting contribution, focus and election end."""
    operation: Literal["assign_role"] = "assign_role"
    role_id: RESOURCE_ID
    peer_id: RESOURCE_ID
    percentage: float | None = None
    focus: str | None = None
    elected_until: date | None = None


class _Holder(_Input):
    role_id: RESOURCE_ID
    peer_id: RESOURCE_ID


class UnassignRole(_Holder):
    """Remove one peer's role assignment."""
    operation: Literal["unassign_role"] = "unassign_role"


class GetRoleHolder(_Holder):
    """Get one peer's role assignment details."""
    operation: Literal["get_role_holder"] = "get_role_holder"


class UpdateRoleHolder(_Holder):
    """Update supplied assignment fields. Peerdom documents percentage as a string for this endpoint."""
    operation: Literal["update_role_holder"] = "update_role_holder"
    percentage: str | None = None
    focus: str | None = None
    elected_until: date | None = None


class ListGroups(_Page):
    """List groups (circles) in the live or selected map, optionally filtered by peer."""
    operation: Literal["list_groups"] = "list_groups"
    peer_id: RESOURCE_ID | None = None
    map_id: RESOURCE_ID | None = None
    include_custom_fields: bool = False


class GetGroup(_Input):
    """Get one group (circle) with optional custom fields."""
    operation: Literal["get_group"] = "get_group"
    group_id: RESOURCE_ID
    include_custom_fields: bool = False


class CreateGroup(_NodeFields):
    """Create a group (circle) in a selected map and parent circle."""
    operation: Literal["create_group"] = "create_group"
    name: str = Field(..., min_length=1)
    map_id: RESOURCE_ID
    parent_id: RESOURCE_ID
    electable: bool | None = None


class UpdateGroup(_NodeFields):
    """Update supplied group (circle) fields."""
    operation: Literal["update_group"] = "update_group"
    group_id: RESOURCE_ID


class DeleteGroup(_Input):
    """Delete a group from a live or draft map, excluding archived maps."""
    operation: Literal["delete_group"] = "delete_group"
    group_id: RESOURCE_ID


class ListProjects(_Page):
    """List projects. With a peer filter Peerdom ignores pagination and returns that peer's projects."""
    operation: Literal["list_projects"] = "list_projects"
    peer_id: RESOURCE_ID | None = None


class GetProject(_Input):
    """Get one project."""
    operation: Literal["get_project"] = "get_project"
    project_id: RESOURCE_ID


class _ProjectFields(_Input):
    name: str | None = Field(None, min_length=1)
    description: str | None = None
    notes: str | None = None
    external_url: str | None = None
    circle_id: RESOURCE_ID | None = None
    parent_id: RESOURCE_ID | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    archived: bool | None = None


class CreateProject(_ProjectFields):
    """Create a project; requires the Projects app."""
    operation: Literal["create_project"] = "create_project"
    name: str = Field(..., min_length=1)


class UpdateProject(_ProjectFields):
    """Patch only supplied project fields; requires the Projects app. Renaming regenerates the slug."""
    operation: Literal["update_project"] = "update_project"
    project_id: RESOURCE_ID


PeerdomConfig = Annotated[Union[
    GetTenant, ListMaps, ListPeers, GetPeer, CreatePeer, UpdatePeer, DeletePeer,
    ListRoles, GetRole, CreateRole, UpdateRole, DeleteRole, AssignRole, UnassignRole,
    GetRoleHolder, UpdateRoleHolder, ListGroups, GetGroup, CreateGroup, UpdateGroup,
    DeleteGroup, ListProjects, GetProject, CreateProject, UpdateProject,
], Field(discriminator="operation")]


class PeerdomFullConfig(NodeConfig[PeerdomConfig, PeerdomAPIKeyCredential]):
    pass


# Method, exact contract path, expected status, expected response shape.
ROUTES = {
    "get_tenant": ("GET", "/tenant", 200, "object"),
    "list_maps": ("GET", "/maps", 200, "list"),
    "list_peers": ("GET", "/peers", 200, "list"),
    "get_peer": ("GET", "/peers/{peer_id}", 200, "object"),
    "create_peer": ("POST", "/peers", 201, "object"),
    "update_peer": ("PUT", "/peers/{peer_id}", 200, "object"),
    "delete_peer": ("DELETE", "/peers/{peer_id}", 200, "empty"),
    "list_roles": ("GET", "/roles", 200, "list"),
    "get_role": ("GET", "/roles/{role_id}", 200, "object"),
    "create_role": ("POST", "/roles", 200, "object"),
    "update_role": ("PUT", "/roles/{role_id}", 200, "object"),
    "delete_role": ("DELETE", "/roles/{role_id}", 200, "object"),
    "assign_role": ("POST", "/roles/{role_id}/peers", 201, "object"),
    "unassign_role": ("DELETE", "/roles/{role_id}/peers/{peer_id}", 200, "object"),
    "get_role_holder": ("GET", "/roles/{role_id}/peers/{peer_id}", 200, "object"),
    "update_role_holder": ("PUT", "/roles/{role_id}/peers/{peer_id}", 200, "object"),
    "list_groups": ("GET", "/groups", 200, "list"),
    "get_group": ("GET", "/groups/{group_id}", 200, "object"),
    "create_group": ("POST", "/groups", 200, "object"),
    "update_group": ("PUT", "/groups/{group_id}", 200, "object"),
    "delete_group": ("DELETE", "/groups/{group_id}", 200, "object"),
    "list_projects": ("GET", "/projects", 200, "list"),
    "get_project": ("GET", "/projects/{project_id}", 200, "object"),
    "create_project": ("POST", "/projects", 201, "object"),
    "update_project": ("PATCH", "/projects/{project_id}", 200, "object"),
}
BODY_NAMES = {
    "first_name": "firstName", "last_name": "lastName", "nick_name": "nickName",
    "custom_fields": "customFields", "map_id": "mapId", "parent_id": "parentId",
    "group_email": "groupEmail", "representing_id": "representingId", "peer_id": "peerId",
    "elected_until": "electedUntil", "external_url": "externalUrl", "circle_id": "circleId",
    "started_at": "startedAt", "ended_at": "endedAt",
}


def request_parts(config):
    """Render one typed operation into its single contract request."""
    method, template, expected_status, shape = ROUTES[config.operation]
    values = config.model_dump(mode="json", exclude_none=True)
    path_fields = {name for name in ("peer_id", "role_id", "group_id", "project_id") if "{" + name + "}" in template}
    path = template.format(**{name: quote(str(UUID(values[name])), safe="") for name in path_fields})
    params, body = {}, None
    if method == "GET":
        if isinstance(config, _Page) and not (isinstance(config, ListProjects) and config.peer_id):
            params.update(limit=config.limit, offset=config.offset)
        for field, target in (("peer_id", "peer"), ("group_id", "group"), ("map_id", "mapId")):
            if field in values and field not in path_fields:
                params[target] = values[field]
        if "include_former" in values:
            params["includeFormer"] = str(config.include_former).lower()
        related = [name for field, name in (
            ("include_roles", "roles"), ("include_holders", "holders"),
            ("include_custom_fields", "customfields"), ("include_groups", "groups"),
            ("include_representing", "representing"),
        ) if values.get(field)]
        if related:
            params["with"] = ",".join(related)
    elif method != "DELETE":
        body = {BODY_NAMES.get(k, k): v for k, v in values.items() if k not in path_fields and k != "operation"}
        if config.operation.startswith("update_") and not body:
            raise ValueError("Provide at least one field to update")
    return method, path, params, body, expected_status, shape


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value


class PeerdomNode(WorkflowNode):
    integration_type = "automation-peerdom"
    connection_evidence = ConnectionEvidence(noun="Peerdom organization", identity_operation="get_tenant")

    @classmethod
    def get_config_model(cls):
        return PeerdomFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            return {"status": "error", "error": "Connect a Peerdom API key"}
        config = self.config.config
        try:
            method, path, params, body, expected_status, shape = request_parts(config)
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"X-Api-Key": credential.api_key, "Accept": "application/json"})
            if response.status_code != expected_status:
                return {"status": "error", "http_status": response.status_code,
                    "error": _redact(response.text[:2000], credential.api_key) or f"Peerdom returned HTTP {response.status_code}",
                    "write_may_have_succeeded": method != "GET" and response.status_code >= 500}
            # DELETE /peers/{id} documents a 200 without a response body.
            payload = None if shape == "empty" else response.json()
            if shape == "list" and not isinstance(payload, list) or shape == "object" and not isinstance(payload, dict):
                raise ValueError("Peerdom returned an unexpected response shape")
            if isinstance(payload, dict) and payload.get("error"):
                return {"status": "error", "error": _redact(str(payload["error"]), credential.api_key), "http_status": response.status_code}
            result = {"status": "success", "data": _redact(payload, credential.api_key), "http_status": response.status_code}
            if isinstance(config, _Page):
                paginated = not (isinstance(config, ListProjects) and config.peer_id)
                maybe_more = paginated and len(payload) >= config.limit
                result.update(has_more=maybe_more, next_offset=config.offset + len(payload) if maybe_more else None)
            return result
        except httpx.HTTPError:
            return {"status": "error", "error": "Peerdom request did not complete", "write_may_have_succeeded": config.operation.startswith(("create_", "update_", "delete_", "assign_", "unassign_"))}
        except (ValueError, TypeError):
            return {"status": "error", "error": "Peerdom request or response could not be confirmed; check the configuration and provider before retrying"}
