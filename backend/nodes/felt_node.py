"""Felt REST API v2: one published endpoint per operation.

API contract: https://felt.com/api/v2/openapi.json (version 2.0).
Authentication: https://developers.felt.com/rest-api/getting-started
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

ResourceID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Permission = Literal["view_only", "view_and_contribute", "view_and_edit"]
Access = Literal["private", "view_only", "view_and_comment", "view_comment_and_edit"]


class FeltAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Felt API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://felt.com/maps/latest/developers",
            "x-credential-instructions": "Create an API token in Workspace Settings → Developers and paste it here. Felt REST API access requires a Business or Enterprise plan, or a trial. The token is sent as a Bearer token to felt.com.",
        })
    credential_type: Literal["felt_api_token"] = Field("felt_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FeltGetCurrentUserConfig(_Input):
    """Get current user."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})

class FeltListProjectsConfig(_Input):
    """List projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    workspace_id: str | None = None

class FeltCreateProjectConfig(_Input):
    """Create project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    visibility: Literal["workspace", "private"]
    max_inherited_permission: Permission | None = None

class FeltGetProjectConfig(_Input):
    """Get project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: ResourceID = Field(..., description="Paste the Felt project id.")

class FeltUpdateProjectConfig(_Input):
    """Update project."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    project_id: ResourceID = Field(..., description="Paste the Felt project id.")
    name: str | None = Field(None, max_length=1000)
    visibility: Literal["workspace", "private"] | None = None
    max_inherited_permission: Permission | None = None

class FeltDeleteProjectConfig(_Input):
    """Delete a project and all folders and maps inside it."""
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})
    project_id: ResourceID = Field(..., description="Paste the Felt project id.")

class FeltCreateMapConfig(_Input):
    """Create map."""
    operation: Literal["create_map"] = Field("create_map", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=1000)
    description: str | None = None
    public_access: Access = "private"
    workspace_id: str | None = None
    basemap: Literal["default", "light", "dark", "satellite"] | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    zoom: float | None = Field(None, ge=0, le=24)

class FeltGetMapConfig(_Input):
    """Get map."""
    operation: Literal["get_map"] = Field("get_map", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")

class FeltUpdateMapConfig(_Input):
    """Update map."""
    operation: Literal["update_map"] = Field("update_map", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    title: str | None = Field(None, max_length=1000)
    description: str | None = None
    public_access: Access | None = None
    basemap: Literal["default", "light", "dark", "satellite"] | None = None

class FeltDeleteMapConfig(_Input):
    """Delete map."""
    operation: Literal["delete_map"] = Field("delete_map", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")

class FeltDuplicateMapConfig(_Input):
    """Duplicate map."""
    operation: Literal["duplicate_map"] = Field("duplicate_map", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    title: str | None = None

class FeltMoveMapConfig(_Input):
    """Move map."""
    operation: Literal["move_map"] = Field("move_map", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    project_id: ResourceID

class FeltListMapLayersConfig(_Input):
    """List map layers."""
    operation: Literal["list_map_layers"] = Field("list_map_layers", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    include_uploading: bool = True

class FeltGetMapLayerConfig(_Input):
    """Get map layer."""
    operation: Literal["get_map_layer"] = Field("get_map_layer", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    layer_id: ResourceID = Field(..., description="Paste the Felt layer id.")

class FeltDeleteMapLayerConfig(_Input):
    """Delete map layer."""
    operation: Literal["delete_map_layer"] = Field("delete_map_layer", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    layer_id: ResourceID = Field(..., description="Paste the Felt layer id.")

class FeltRefreshMapLayerConfig(_Input):
    """Request a layer refresh; processing continues asynchronously."""
    operation: Literal["refresh_map_layer"] = Field("refresh_map_layer", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    layer_id: ResourceID = Field(..., description="Paste the Felt layer id.")

class FeltListMapElementsConfig(_Input):
    """List map elements."""
    operation: Literal["list_map_elements"] = Field("list_map_elements", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")

class FeltDeleteMapElementConfig(_Input):
    """Delete map element."""
    operation: Literal["delete_map_element"] = Field("delete_map_element", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    element_id: ResourceID = Field(..., description="Paste the Felt element id.")

class FeltListMapLayerGroupsConfig(_Input):
    """List map layer groups."""
    operation: Literal["list_map_layer_groups"] = Field("list_map_layer_groups", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    include_uploading: bool = True

class FeltGetMapLayerGroupConfig(_Input):
    """Get map layer group."""
    operation: Literal["get_map_layer_group"] = Field("get_map_layer_group", json_schema_extra={"ui:hidden": True})
    map_id: ResourceID = Field(..., description="Paste the Felt map id.")
    layer_group_id: ResourceID = Field(..., description="Paste the Felt layer group id.")


FeltConfig = Annotated[Union[
    FeltGetCurrentUserConfig,
    FeltListProjectsConfig,
    FeltCreateProjectConfig,
    FeltGetProjectConfig,
    FeltUpdateProjectConfig,
    FeltDeleteProjectConfig,
    FeltCreateMapConfig,
    FeltGetMapConfig,
    FeltUpdateMapConfig,
    FeltDeleteMapConfig,
    FeltDuplicateMapConfig,
    FeltMoveMapConfig,
    FeltListMapLayersConfig,
    FeltGetMapLayerConfig,
    FeltDeleteMapLayerConfig,
    FeltRefreshMapLayerConfig,
    FeltListMapElementsConfig,
    FeltDeleteMapElementConfig,
    FeltListMapLayerGroupsConfig,
    FeltGetMapLayerGroupConfig
], Field(discriminator="operation")]


class FeltFullConfig(NodeConfig[FeltConfig, FeltAPITokenCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/api/v2/user'), 'list_projects': ('GET', '/api/v2/projects'), 'create_project': ('POST', '/api/v2/projects'), 'get_project': ('GET', '/api/v2/projects/{project_id}'), 'update_project': ('POST', '/api/v2/projects/{project_id}/update'), 'delete_project': ('DELETE', '/api/v2/projects/{project_id}'), 'create_map': ('POST', '/api/v2/maps'), 'get_map': ('GET', '/api/v2/maps/{map_id}'), 'update_map': ('POST', '/api/v2/maps/{map_id}/update'), 'delete_map': ('DELETE', '/api/v2/maps/{map_id}'), 'duplicate_map': ('POST', '/api/v2/maps/{map_id}/duplicate'), 'move_map': ('POST', '/api/v2/maps/{map_id}/move'), 'list_map_layers': ('GET', '/api/v2/maps/{map_id}/layers'), 'get_map_layer': ('GET', '/api/v2/maps/{map_id}/layers/{layer_id}'), 'delete_map_layer': ('DELETE', '/api/v2/maps/{map_id}/layers/{layer_id}'), 'refresh_map_layer': ('POST', '/api/v2/maps/{map_id}/layers/{layer_id}/refresh'), 'list_map_elements': ('GET', '/api/v2/maps/{map_id}/elements'), 'delete_map_element': ('DELETE', '/api/v2/maps/{map_id}/elements/{element_id}'), 'list_map_layer_groups': ('GET', '/api/v2/maps/{map_id}/layer_groups'), 'get_map_layer_group': ('GET', '/api/v2/maps/{map_id}/layer_groups/{layer_group_id}')}


class FeltNode(WorkflowNode):
    integration_type = "automation-felt"
    connection_evidence = ConnectionEvidence(noun="Felt account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return FeltFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Felt API token")
        credential = self.config.credentials
        config = self.config.config
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in re.findall(r"\{(\w+)\}", route):
            route = route.replace("{" + field + "}", quote(values.pop(field), safe=""))
        query = values if method == "GET" else None
        body = values if method == "POST" and values else None
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://felt.com" + route,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                params=query, json=body)
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for connection evidence, with the secret redacted.
            detail = response.text[:2000].replace(credential.api_token, "[redacted]")
            return {"status": "error", "http_status": response.status_code,
                "error": f"Felt HTTP {response.status_code}: {detail}"}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "acknowledged": True}
        if len(response.content) > 10_000_000:
            raise ValueError("Felt response exceeds the JSON response limit")
        result = response.json()
        if not isinstance(result, (dict, list)):
            raise ValueError("Expected a Felt JSON object or list")
        if isinstance(result, dict) and ("errors" in result or "error" in result):
            return {"status": "error", "http_status": response.status_code,
                "error": str(result).replace(credential.api_token, "[redacted]")[:2000]}
        return {"status": "success", "http_status": response.status_code, "data": result}
