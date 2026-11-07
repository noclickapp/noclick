"""Render Public API workflow node.

Generated operation contracts from Render's public OpenAPI 3.0 specification:
https://api-docs.render.com/openapi/render-public-api-1.json

Covers JSON REST endpoints across services, deploys, environment variables,
projects, databases, logs, metrics, blueprints, workflows, and other resources.
Streaming, multipart blueprint validation, and deprecated Redis endpoints are
excluded. The OpenAPI spec can change; API endpoint semantics remain Render's.
"""

import json
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

RENDER_API_BASE = "https://api.render.com/v1"


class RenderAPIKeyCredential(BaseModel):
    credential_type: Literal["render_api_key"] = Field(
        "render_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="Render API Key",
        description="API key from your Render account settings.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="Render API Key",
        json_schema_extra={
            "x-credential-url": "https://dashboard.render.com/u/settings#api-keys",
            "x-credential-instructions": "In Render, open Account Settings and create an API key.",
        }
    )


class RenderRequestBodyConfig(BaseModel):
    """Accept structured workflow JSON as well as the editor's JSON text."""

    @field_validator("body", mode="before", check_fields=False)
    @classmethod
    def encode_structured_body(cls, value):
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value


class RenderListBlueprintsConfig(BaseModel):
    """List Blueprints."""

    operation: Literal["list_blueprints"] = Field(
        "list_blueprints",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Blueprints",
            "x-display-name": "List Blueprints",
            "x-keywords": ["list", "blueprints"],
        },
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderUpdateWorkspaceMemberConfig(RenderRequestBodyConfig):
    """Update workspace member role."""

    operation: Literal["update_workspace_member"] = Field(
        "update_workspace_member",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-display-name": "Update workspace member role",
            "x-keywords": ["update", "workspace", "member", "workspaces"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return resources for",
    )
    user_id: str = Field(
        ...,
        title="userId",
        description="The ID of the user (Render object ID with a `usr-` prefix).",
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: role.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRemoveWorkspaceMemberConfig(BaseModel):
    """Remove workspace member."""

    operation: Literal["remove_workspace_member"] = Field(
        "remove_workspace_member",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-display-name": "Remove workspace member",
            "x-keywords": ["remove", "workspace", "member", "workspaces"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return resources for",
    )
    user_id: str = Field(
        ...,
        title="userId",
        description="The ID of the user (Render object ID with a `usr-` prefix).",
    )


class RenderRetrieveBlueprintConfig(BaseModel):
    """Retrieve Blueprint."""

    operation: Literal["retrieve_blueprint"] = Field(
        "retrieve_blueprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Blueprints",
            "x-display-name": "Retrieve Blueprint",
            "x-keywords": ["retrieve", "blueprint", "blueprints"],
        },
    )
    blueprint_id: str = Field(
        ..., title="blueprintId", description="The ID of the Blueprint"
    )


class RenderUpdateBlueprintConfig(RenderRequestBodyConfig):
    """Update Blueprint."""

    operation: Literal["update_blueprint"] = Field(
        "update_blueprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Blueprints",
            "x-display-name": "Update Blueprint",
            "x-keywords": ["update", "blueprint", "blueprints"],
        },
    )
    blueprint_id: str = Field(
        ..., title="blueprintId", description="The ID of the Blueprint"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDisconnectBlueprintConfig(BaseModel):
    """Disconnect Blueprint."""

    operation: Literal["disconnect_blueprint"] = Field(
        "disconnect_blueprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Blueprints",
            "x-display-name": "Disconnect Blueprint",
            "x-keywords": ["disconnect", "blueprint", "blueprints"],
        },
    )
    blueprint_id: str = Field(
        ..., title="blueprintId", description="The ID of the Blueprint"
    )


class RenderListBlueprintSyncsConfig(BaseModel):
    """List Blueprint syncs."""

    operation: Literal["list_blueprint_syncs"] = Field(
        "list_blueprint_syncs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Blueprints",
            "x-display-name": "List Blueprint syncs",
            "x-keywords": ["list", "blueprint", "syncs", "blueprints"],
        },
    )
    blueprint_id: str = Field(
        ..., title="blueprintId", description="The ID of the Blueprint"
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderListDedicatedIpsConfig(BaseModel):
    """List dedicated IPs."""

    operation: Literal["list_dedicated_ips"] = Field(
        "list_dedicated_ips",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dedicated IPs",
            "x-display-name": "List dedicated IPs",
            "x-keywords": ["list", "dedicated", "ips", "i", "ps"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to list dedicated IP sets for.",
    )
    environment_id: Optional[str] = Field(
        None,
        title="environmentId",
        description="Filter dedicated IP sets limited to this environment. Excludes workspace-scoped dedicated IP sets. The environment must belong to the workspace named by `ownerId`.",
    )


class RenderCreateDedicatedIpConfig(RenderRequestBodyConfig):
    """Create dedicated IP set."""

    operation: Literal["create_dedicated_ip"] = Field(
        "create_dedicated_ip",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dedicated IPs",
            "x-display-name": "Create dedicated IP set",
            "x-keywords": ["create", "dedicated", "ip", "i", "ps"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, ownerId, region.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveDedicatedIpConfig(BaseModel):
    """Retrieve dedicated IP set."""

    operation: Literal["retrieve_dedicated_ip"] = Field(
        "retrieve_dedicated_ip",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dedicated IPs",
            "x-display-name": "Retrieve dedicated IP set",
            "x-keywords": ["retrieve", "dedicated", "ip", "i", "ps"],
        },
    )
    dedicated_ip_id: str = Field(
        ..., title="dedicatedIpId", description="The ID of the dedicated IP set"
    )


class RenderUpdateDedicatedIpConfig(RenderRequestBodyConfig):
    """Update dedicated IP set."""

    operation: Literal["update_dedicated_ip"] = Field(
        "update_dedicated_ip",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dedicated IPs",
            "x-display-name": "Update dedicated IP set",
            "x-keywords": ["update", "dedicated", "ip", "i", "ps"],
        },
    )
    dedicated_ip_id: str = Field(
        ..., title="dedicatedIpId", description="The ID of the dedicated IP set"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteDedicatedIpConfig(BaseModel):
    """Delete dedicated IP set."""

    operation: Literal["delete_dedicated_ip"] = Field(
        "delete_dedicated_ip",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dedicated IPs",
            "x-display-name": "Delete dedicated IP set",
            "x-keywords": ["delete", "dedicated", "ip", "i", "ps"],
        },
    )
    dedicated_ip_id: str = Field(
        ..., title="dedicatedIpId", description="The ID of the dedicated IP set"
    )


class RenderListDisksConfig(BaseModel):
    """List disks."""

    operation: Literal["list_disks"] = Field(
        "list_disks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Disks",
            "x-display-name": "List disks",
            "x-keywords": ["list", "disks"],
        },
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    disk_id: Optional[str] = Field(
        None,
        title="diskId",
        description="Filter by disk IDs Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for resources created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for resources created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for resources updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for resources updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    service_id: Optional[str] = Field(
        None,
        title="serviceId",
        description="Filter for resources by service ID Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderAddDiskConfig(RenderRequestBodyConfig):
    """Add disk."""

    operation: Literal["add_disk"] = Field(
        "add_disk",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Disks",
            "x-display-name": "Add disk",
            "x-keywords": ["add", "disk", "disks"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, sizeGB, mountPath, serviceId.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveDiskConfig(BaseModel):
    """Retrieve disk."""

    operation: Literal["retrieve_disk"] = Field(
        "retrieve_disk",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Disks",
            "x-display-name": "Retrieve disk",
            "x-keywords": ["retrieve", "disk", "disks"],
        },
    )
    disk_id: str = Field(..., title="diskId", description="The ID of the disk")


class RenderUpdateDiskConfig(RenderRequestBodyConfig):
    """Update disk."""

    operation: Literal["update_disk"] = Field(
        "update_disk",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Disks",
            "x-display-name": "Update disk",
            "x-keywords": ["update", "disk", "disks"],
        },
    )
    disk_id: str = Field(..., title="diskId", description="The ID of the disk")
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteDiskConfig(BaseModel):
    """Delete disk."""

    operation: Literal["delete_disk"] = Field(
        "delete_disk",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Disks",
            "x-display-name": "Delete disk",
            "x-keywords": ["delete", "disk", "disks"],
        },
    )
    disk_id: str = Field(..., title="diskId", description="The ID of the disk")


class RenderListSnapshotsConfig(BaseModel):
    """List snapshots."""

    operation: Literal["list_snapshots"] = Field(
        "list_snapshots",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Disks",
            "x-display-name": "List snapshots",
            "x-keywords": ["list", "snapshots", "disks"],
        },
    )
    disk_id: str = Field(..., title="diskId", description="The ID of the disk")


class RenderRestoreSnapshotConfig(RenderRequestBodyConfig):
    """Restore snapshot."""

    operation: Literal["restore_snapshot"] = Field(
        "restore_snapshot",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Disks",
            "x-display-name": "Restore snapshot",
            "x-keywords": ["restore", "snapshot", "disks"],
        },
    )
    disk_id: str = Field(..., title="diskId", description="The ID of the disk")
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: snapshotKey.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderGetUserConfig(BaseModel):
    """Get the authenticated user."""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Users",
            "x-display-name": "Get the authenticated user",
            "x-keywords": ["get", "user", "users"],
        },
    )


class RenderListOwnersConfig(BaseModel):
    """List workspaces."""

    operation: Literal["list_owners"] = Field(
        "list_owners",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-display-name": "List workspaces",
            "x-keywords": ["list", "owners", "workspaces"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Only return workspaces with one of the provided names. Only exact matches are returned. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    email: Optional[str] = Field(
        None,
        title="email",
        description="Only return workspaces owned by one of the provided email addresses. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderRetrieveOwnerConfig(BaseModel):
    """Retrieve workspace."""

    operation: Literal["retrieve_owner"] = Field(
        "retrieve_owner",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-display-name": "Retrieve workspace",
            "x-keywords": ["retrieve", "owner", "workspaces"],
        },
    )
    owner_id: str = Field(
        ..., title="ownerId", description="The ID of the user or team"
    )


class RenderRetrieveOwnerMembersConfig(BaseModel):
    """List workspace members."""

    operation: Literal["retrieve_owner_members"] = Field(
        "retrieve_owner_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-display-name": "List workspace members",
            "x-keywords": ["retrieve", "owner", "members", "workspaces"],
        },
    )
    owner_id: str = Field(..., title="ownerId", description="The ID of the team")


class RenderListOwnerAuditLogsConfig(BaseModel):
    """List workspace audit logs."""

    operation: Literal["list_owner_audit_logs"] = Field(
        "list_owner_audit_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Audit Logs",
            "x-display-name": "List workspace audit logs",
            "x-keywords": ["list", "owner", "audit", "logs"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return resources for",
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Start time for filtering audit logs (ISO 8601 format)",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="End time for filtering audit logs (ISO 8601 format)",
    )
    direction: Optional[str] = Field(
        None,
        title="direction",
        description="The direction to query logs for. Backward will return most recent logs first. Forward will start with the oldest logs in the time range.",
        json_schema_extra={"enum": ["forward", "backward"]},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of audit log items to return. For details, see .",
    )


class RenderListOrganizationAuditLogsConfig(BaseModel):
    """List organization audit logs."""

    operation: Literal["list_organization_audit_logs"] = Field(
        "list_organization_audit_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Audit Logs",
            "x-display-name": "List organization audit logs",
            "x-keywords": ["list", "organization", "audit", "logs"],
        },
    )
    org_id: str = Field(
        ..., title="orgId", description="The unique identifier of the organization"
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Start time for filtering audit logs (ISO 8601 format)",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="End time for filtering audit logs (ISO 8601 format)",
    )
    direction: Optional[str] = Field(
        None,
        title="direction",
        description="The direction to query logs for. Backward will return most recent logs first. Forward will start with the oldest logs in the time range.",
        json_schema_extra={"enum": ["forward", "backward"]},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of audit log items to return. For details, see .",
    )


class RenderRetrieveOwnerNotificationSettingsConfig(BaseModel):
    """Retrieve notification settings."""

    operation: Literal["retrieve_owner_notification_settings"] = Field(
        "retrieve_owner_notification_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification Settings",
            "x-display-name": "Retrieve notification settings",
            "x-keywords": ["retrieve", "owner", "notification", "settings"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return resources for",
    )


class RenderPatchOwnerNotificationSettingsConfig(RenderRequestBodyConfig):
    """Update notification settings."""

    operation: Literal["patch_owner_notification_settings"] = Field(
        "patch_owner_notification_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification Settings",
            "x-display-name": "Update notification settings",
            "x-keywords": ["patch", "owner", "notification", "settings"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return resources for",
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderListNotificationOverridesConfig(BaseModel):
    """List notification overrides."""

    operation: Literal["list_notification_overrides"] = Field(
        "list_notification_overrides",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification Settings",
            "x-display-name": "List notification overrides",
            "x-keywords": ["list", "notification", "overrides", "settings"],
        },
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    service_id: Optional[str] = Field(
        None,
        title="serviceId",
        description="Filter for resources by service ID Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderRetrieveServiceNotificationOverridesConfig(BaseModel):
    """Retrieve notification override."""

    operation: Literal["retrieve_service_notification_overrides"] = Field(
        "retrieve_service_notification_overrides",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification Settings",
            "x-display-name": "Retrieve notification override",
            "x-keywords": [
                "retrieve",
                "service",
                "notification",
                "overrides",
                "settings",
            ],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderPatchServiceNotificationOverridesConfig(RenderRequestBodyConfig):
    """Update notification override."""

    operation: Literal["patch_service_notification_overrides"] = Field(
        "patch_service_notification_overrides",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification Settings",
            "x-display-name": "Update notification override",
            "x-keywords": ["patch", "service", "notification", "overrides", "settings"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderListRegistryCredentialsConfig(BaseModel):
    """List registry credentials."""

    operation: Literal["list_registry_credentials"] = Field(
        "list_registry_credentials",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Registry Credentials",
            "x-display-name": "List registry credentials",
            "x-keywords": ["list", "registry", "credentials"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter for the name of a credential Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    username: Optional[str] = Field(
        None,
        title="username",
        description="Filter for the username of a credential Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    type: Optional[str] = Field(
        None,
        title="type",
        description="Filter for the registry type for the credential Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for services created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for services created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for services updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for services updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreateRegistryCredentialConfig(RenderRequestBodyConfig):
    """Create registry credential."""

    operation: Literal["create_registry_credential"] = Field(
        "create_registry_credential",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Registry Credentials",
            "x-display-name": "Create registry credential",
            "x-keywords": ["create", "registry", "credential", "credentials"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, registry, username, authToken, ownerId.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveRegistryCredentialConfig(BaseModel):
    """Retrieve registry credential."""

    operation: Literal["retrieve_registry_credential"] = Field(
        "retrieve_registry_credential",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Registry Credentials",
            "x-display-name": "Retrieve registry credential",
            "x-keywords": ["retrieve", "registry", "credential", "credentials"],
        },
    )
    registry_credential_id: str = Field(
        ...,
        title="registryCredentialId",
        description="The ID of the registry credential",
    )


class RenderUpdateRegistryCredentialConfig(RenderRequestBodyConfig):
    """Update registry credential."""

    operation: Literal["update_registry_credential"] = Field(
        "update_registry_credential",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Registry Credentials",
            "x-display-name": "Update registry credential",
            "x-keywords": ["update", "registry", "credential", "credentials"],
        },
    )
    registry_credential_id: str = Field(
        ...,
        title="registryCredentialId",
        description="The ID of the registry credential",
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, registry, username, authToken.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteRegistryCredentialConfig(BaseModel):
    """Delete registry credential."""

    operation: Literal["delete_registry_credential"] = Field(
        "delete_registry_credential",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Registry Credentials",
            "x-display-name": "Delete registry credential",
            "x-keywords": ["delete", "registry", "credential", "credentials"],
        },
    )
    registry_credential_id: str = Field(
        ...,
        title="registryCredentialId",
        description="The ID of the registry credential",
    )


class RenderListServicesConfig(BaseModel):
    """List services."""

    operation: Literal["list_services"] = Field(
        "list_services",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "List services",
            "x-keywords": ["list", "services"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    type: Optional[str] = Field(
        None,
        title="type",
        description="Filter for types of services Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    environment_id: Optional[str] = Field(
        None,
        title="environmentId",
        description="Filter for resources that belong to an environment Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    env: Optional[str] = Field(
        None,
        title="env",
        description="Filter for environments (runtimes) of services (deprecated; use `runtime` instead) Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    region: Optional[str] = Field(
        None,
        title="region",
        description="Filter by resource region Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    suspended: Optional[str] = Field(
        None,
        title="suspended",
        description="Filter resources based on whether they're suspended or not suspended Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for resources created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for resources created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for resources updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for resources updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    include_previews: Optional[bool] = Field(
        None, title="includePreviews", description="Include previews in the response"
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreateServiceConfig(RenderRequestBodyConfig):
    """Create service."""

    operation: Literal["create_service"] = Field(
        "create_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Create service",
            "x-keywords": ["create", "service", "services"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: type, name, ownerId.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveServiceConfig(BaseModel):
    """Retrieve service."""

    operation: Literal["retrieve_service"] = Field(
        "retrieve_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Retrieve service",
            "x-keywords": ["retrieve", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderUpdateServiceConfig(RenderRequestBodyConfig):
    """Update service."""

    operation: Literal["update_service"] = Field(
        "update_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Update service",
            "x-keywords": ["update", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteServiceConfig(BaseModel):
    """Delete service."""

    operation: Literal["delete_service"] = Field(
        "delete_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Delete service",
            "x-keywords": ["delete", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderPurgeCacheConfig(BaseModel):
    """Purge Web Service Cache."""

    operation: Literal["purge_cache"] = Field(
        "purge_cache",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Purge Web Service Cache",
            "x-keywords": ["purge", "cache", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderListDeploysConfig(BaseModel):
    """List deploys."""

    operation: Literal["list_deploys"] = Field(
        "list_deploys",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deploys",
            "x-display-name": "List deploys",
            "x-keywords": ["list", "deploys"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    status: Optional[str] = Field(
        None,
        title="status",
        description="Filter for deploys with the specified statuses Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for deploys created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for deploys created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for deploys updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for deploys updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    finished_before: Optional[str] = Field(
        None,
        title="finishedBefore",
        description="Filter for deploys finished before a certain time (specified as an ISO 8601 timestamp)",
    )
    finished_after: Optional[str] = Field(
        None,
        title="finishedAfter",
        description="Filter for deploys finished after a certain time (specified as an ISO 8601 timestamp)",
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreateDeployConfig(RenderRequestBodyConfig):
    """Trigger deploy."""

    operation: Literal["create_deploy"] = Field(
        "create_deploy",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deploys",
            "x-display-name": "Trigger deploy",
            "x-keywords": ["create", "deploy", "deploys"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveDeployConfig(BaseModel):
    """Retrieve deploy."""

    operation: Literal["retrieve_deploy"] = Field(
        "retrieve_deploy",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deploys",
            "x-display-name": "Retrieve deploy",
            "x-keywords": ["retrieve", "deploy", "deploys"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    deploy_id: str = Field(..., title="deployId", description="The ID of the deploy")


class RenderCancelDeployConfig(BaseModel):
    """Cancel deploy."""

    operation: Literal["cancel_deploy"] = Field(
        "cancel_deploy",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deploys",
            "x-display-name": "Cancel deploy",
            "x-keywords": ["cancel", "deploy", "deploys"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    deploy_id: str = Field(..., title="deployId", description="The ID of the deploy")


class RenderRollbackDeployConfig(RenderRequestBodyConfig):
    """Roll back deploy."""

    operation: Literal["rollback_deploy"] = Field(
        "rollback_deploy",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deploys",
            "x-display-name": "Roll back deploy",
            "x-keywords": ["rollback", "deploy", "deploys"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: deployId.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderGetEnvVarsForServiceConfig(BaseModel):
    """List environment variables."""

    operation: Literal["get_env_vars_for_service"] = Field(
        "get_env_vars_for_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "List environment variables",
            "x-keywords": ["get", "env", "vars", "for", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderUpdateEnvVarsForServiceConfig(RenderRequestBodyConfig):
    """Update environment variables."""

    operation: Literal["update_env_vars_for_service"] = Field(
        "update_env_vars_for_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Update environment variables",
            "x-keywords": ["update", "env", "vars", "for", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveEnvVarConfig(BaseModel):
    """Retrieve environment variable."""

    operation: Literal["retrieve_env_var"] = Field(
        "retrieve_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Retrieve environment variable",
            "x-keywords": ["retrieve", "env", "var", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )


class RenderUpdateEnvVarConfig(RenderRequestBodyConfig):
    """Add or update environment variable."""

    operation: Literal["update_env_var"] = Field(
        "update_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Add or update environment variable",
            "x-keywords": ["update", "env", "var", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteEnvVarConfig(BaseModel):
    """Delete environment variable."""

    operation: Literal["delete_env_var"] = Field(
        "delete_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Delete environment variable",
            "x-keywords": ["delete", "env", "var", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )


class RenderListSecretFilesForServiceConfig(BaseModel):
    """List secret files."""

    operation: Literal["list_secret_files_for_service"] = Field(
        "list_secret_files_for_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "List secret files",
            "x-keywords": ["list", "secret", "files", "for", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderUpdateSecretFilesForServiceConfig(RenderRequestBodyConfig):
    """Update secret files."""

    operation: Literal["update_secret_files_for_service"] = Field(
        "update_secret_files_for_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Update secret files",
            "x-keywords": ["update", "secret", "files", "for", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveSecretFileConfig(BaseModel):
    """Retrieve secret file."""

    operation: Literal["retrieve_secret_file"] = Field(
        "retrieve_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Retrieve secret file",
            "x-keywords": ["retrieve", "secret", "file", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The file name of the secret file"
    )


class RenderAddOrUpdateSecretFileConfig(RenderRequestBodyConfig):
    """Add or update secret file."""

    operation: Literal["add_or_update_secret_file"] = Field(
        "add_or_update_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Add or update secret file",
            "x-keywords": ["add", "or", "update", "secret", "file", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The file name of the secret file"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteSecretFileConfig(BaseModel):
    """Delete secret file."""

    operation: Literal["delete_secret_file"] = Field(
        "delete_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Delete secret file",
            "x-keywords": ["delete", "secret", "file", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The file name of the secret file"
    )


class RenderListEventsConfig(BaseModel):
    """List events."""

    operation: Literal["list_events"] = Field(
        "list_events",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "List events",
            "x-keywords": ["list", "events", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    type: Optional[str] = Field(
        None, title="type", description="The type of event to filter to"
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderListHeadersConfig(BaseModel):
    """List header rules."""

    operation: Literal["list_headers"] = Field(
        "list_headers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Headers",
            "x-display-name": "List header rules",
            "x-keywords": ["list", "headers", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    path: Optional[str] = Field(
        None,
        title="path",
        description="Filter for specific paths that headers apply to Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter for header names Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    value: Optional[str] = Field(
        None,
        title="value",
        description="Filter for header values Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderAddHeadersConfig(RenderRequestBodyConfig):
    """Add header rule."""

    operation: Literal["add_headers"] = Field(
        "add_headers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Headers",
            "x-display-name": "Add header rule",
            "x-keywords": ["add", "headers", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: path, name, value.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderUpdateHeadersConfig(RenderRequestBodyConfig):
    """Replace header rules."""

    operation: Literal["update_headers"] = Field(
        "update_headers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Headers",
            "x-display-name": "Replace header rules",
            "x-keywords": ["update", "headers", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteHeaderConfig(BaseModel):
    """Delete header rule."""

    operation: Literal["delete_header"] = Field(
        "delete_header",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Headers",
            "x-display-name": "Delete header rule",
            "x-keywords": ["delete", "header", "services", "headers"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    header_id: str = Field(..., title="headerId", description="The id of the header")


class RenderListRoutesConfig(BaseModel):
    """List redirect/rewrite rules."""

    operation: Literal["list_routes"] = Field(
        "list_routes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Routes",
            "x-display-name": "List redirect/rewrite rules",
            "x-keywords": ["list", "routes", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    type: Optional[str] = Field(
        None,
        title="type",
        description="Filter for the type of route rule Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    source: Optional[str] = Field(
        None,
        title="source",
        description="Filter for the source path of the route Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    destination: Optional[str] = Field(
        None,
        title="destination",
        description="Filter for the destination path of the route Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderAddRouteConfig(RenderRequestBodyConfig):
    """Add redirect/rewrite rules."""

    operation: Literal["add_route"] = Field(
        "add_route",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Routes",
            "x-display-name": "Add redirect/rewrite rules",
            "x-keywords": ["add", "route", "services", "routes"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: type, source, destination.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderPutRoutesConfig(RenderRequestBodyConfig):
    """Update redirect/rewrite rules."""

    operation: Literal["put_routes"] = Field(
        "put_routes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Routes",
            "x-display-name": "Update redirect/rewrite rules",
            "x-keywords": ["put", "routes", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderPatchRouteConfig(RenderRequestBodyConfig):
    """Update redirect/rewrite rule priority."""

    operation: Literal["patch_route"] = Field(
        "patch_route",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Routes",
            "x-display-name": "Update redirect/rewrite rule priority",
            "x-keywords": ["patch", "route", "services", "routes"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    route_id: str = Field(..., title="routeId", description="The id of the route")
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: priority.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteRouteConfig(BaseModel):
    """Delete redirect/rewrite rule."""

    operation: Literal["delete_route"] = Field(
        "delete_route",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Routes",
            "x-display-name": "Delete redirect/rewrite rule",
            "x-keywords": ["delete", "route", "services", "routes"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    route_id: str = Field(..., title="routeId", description="The id of the route")


class RenderListCustomDomainsConfig(BaseModel):
    """List custom domains."""

    operation: Literal["list_custom_domains"] = Field(
        "list_custom_domains",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Custom Domains",
            "x-display-name": "List custom domains",
            "x-keywords": ["list", "custom", "domains"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter for the names of custom domain Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    domain_type: Optional[str] = Field(
        None,
        title="domainType",
        description="Filter for domain type",
        json_schema_extra={"enum": ["apex", "subdomain"]},
    )
    verification_status: Optional[str] = Field(
        None,
        title="verificationStatus",
        description="Filter for domain verification status (`verified` or `unverified`)",
        json_schema_extra={"enum": ["verified", "unverified"]},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for custom domains created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for custom domains created after a certain time (specified as an ISO 8601 timestamp)",
    )


class RenderCreateCustomDomainConfig(RenderRequestBodyConfig):
    """Add custom domain."""

    operation: Literal["create_custom_domain"] = Field(
        "create_custom_domain",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Custom Domains",
            "x-display-name": "Add custom domain",
            "x-keywords": ["create", "custom", "domain", "domains"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveCustomDomainConfig(BaseModel):
    """Retrieve custom domain."""

    operation: Literal["retrieve_custom_domain"] = Field(
        "retrieve_custom_domain",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Custom Domains",
            "x-display-name": "Retrieve custom domain",
            "x-keywords": ["retrieve", "custom", "domain", "domains"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    custom_domain_name_or_id: str = Field(
        ...,
        title="customDomainNameOrID",
        description="The ID or name of the custom domain",
    )


class RenderDeleteCustomDomainConfig(BaseModel):
    """Delete custom domain."""

    operation: Literal["delete_custom_domain"] = Field(
        "delete_custom_domain",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Custom Domains",
            "x-display-name": "Delete custom domain",
            "x-keywords": ["delete", "custom", "domain", "domains"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    custom_domain_name_or_id: str = Field(
        ...,
        title="customDomainNameOrID",
        description="The ID or name of the custom domain",
    )


class RenderRefreshCustomDomainConfig(BaseModel):
    """Verify DNS configuration."""

    operation: Literal["refresh_custom_domain"] = Field(
        "refresh_custom_domain",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Custom Domains",
            "x-display-name": "Verify DNS configuration",
            "x-keywords": ["refresh", "custom", "domain", "domains"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    custom_domain_name_or_id: str = Field(
        ...,
        title="customDomainNameOrID",
        description="The ID or name of the custom domain",
    )


class RenderSuspendServiceConfig(BaseModel):
    """Suspend service."""

    operation: Literal["suspend_service"] = Field(
        "suspend_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Suspend service",
            "x-keywords": ["suspend", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderResumeServiceConfig(BaseModel):
    """Resume service."""

    operation: Literal["resume_service"] = Field(
        "resume_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Resume service",
            "x-keywords": ["resume", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderRestartServiceConfig(BaseModel):
    """Restart service."""

    operation: Literal["restart_service"] = Field(
        "restart_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Restart service",
            "x-keywords": ["restart", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderScaleServiceConfig(RenderRequestBodyConfig):
    """Scale instance count."""

    operation: Literal["scale_service"] = Field(
        "scale_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Scale instance count",
            "x-keywords": ["scale", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: numInstances.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderAutoscaleServiceConfig(RenderRequestBodyConfig):
    """Update autoscaling config."""

    operation: Literal["autoscale_service"] = Field(
        "autoscale_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Update autoscaling config",
            "x-keywords": ["autoscale", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: enabled, min, max, criteria.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteAutoscalingConfigConfig(BaseModel):
    """Delete autoscaling config."""

    operation: Literal["delete_autoscaling_config"] = Field(
        "delete_autoscaling_config",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Delete autoscaling config",
            "x-keywords": ["delete", "autoscaling", "config", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderPreviewServiceConfig(RenderRequestBodyConfig):
    """Create service preview (image-backed)."""

    operation: Literal["preview_service"] = Field(
        "preview_service",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Create service preview (image-backed)",
            "x-keywords": ["preview", "service", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: imagePath.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderListJobConfig(BaseModel):
    """List jobs."""

    operation: Literal["list_job"] = Field(
        "list_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "One-Off Jobs",
            "x-display-name": "List jobs",
            "x-keywords": ["list", "job", "one", "off", "jobs"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )
    status: Optional[str] = Field(
        None,
        title="status",
        description="Filter for the status of the job (`pending`, `running`, `succeeded`, `failed`, or `canceled`) Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for jobs created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for jobs created after a certain time (specified as an ISO 8601 timestamp)",
    )
    started_before: Optional[str] = Field(
        None,
        title="startedBefore",
        description="Filter for jobs started before a certain time (specified as an ISO 8601 timestamp)",
    )
    started_after: Optional[str] = Field(
        None,
        title="startedAfter",
        description="Filter for jobs started after a certain time (specified as an ISO 8601 timestamp)",
    )
    finished_before: Optional[str] = Field(
        None,
        title="finishedBefore",
        description="Filter for jobs finished before a certain time (specified as an ISO 8601 timestamp)",
    )
    finished_after: Optional[str] = Field(
        None,
        title="finishedAfter",
        description="Filter for jobs finished after a certain time (specified as an ISO 8601 timestamp)",
    )


class RenderPostJobConfig(RenderRequestBodyConfig):
    """Create job."""

    operation: Literal["post_job"] = Field(
        "post_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "One-Off Jobs",
            "x-display-name": "Create job",
            "x-keywords": ["post", "job", "one", "off", "jobs"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: startCommand.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveJobConfig(BaseModel):
    """Retrieve job."""

    operation: Literal["retrieve_job"] = Field(
        "retrieve_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "One-Off Jobs",
            "x-display-name": "Retrieve job",
            "x-keywords": ["retrieve", "job", "one", "off", "jobs"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    job_id: str = Field(..., title="jobId", description="The ID of the job")


class RenderCancelJobConfig(BaseModel):
    """Cancel running job."""

    operation: Literal["cancel_job"] = Field(
        "cancel_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "One-Off Jobs",
            "x-display-name": "Cancel running job",
            "x-keywords": ["cancel", "job", "one", "off", "jobs"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )
    job_id: str = Field(..., title="jobId", description="The ID of the job")


class RenderListInstancesConfig(BaseModel):
    """List instances."""

    operation: Literal["list_instances"] = Field(
        "list_instances",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "List instances",
            "x-keywords": ["list", "instances", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderRetrieveServiceOutboundIpsConfig(BaseModel):
    """Retrieve service outbound IPs."""

    operation: Literal["retrieve_service_outbound_ips"] = Field(
        "retrieve_service_outbound_ips",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services",
            "x-display-name": "Retrieve service outbound IPs",
            "x-keywords": ["retrieve", "service", "outbound", "ips", "services"],
        },
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderRunCronJobConfig(BaseModel):
    """Trigger cron job run."""

    operation: Literal["run_cron_job"] = Field(
        "run_cron_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Cron Jobs",
            "x-display-name": "Trigger cron job run",
            "x-keywords": ["run", "cron", "job", "services", "jobs"],
        },
    )
    cron_job_id: str = Field(
        ..., title="cronJobId", description="The ID of the cron job"
    )


class RenderCancelCronJobRunConfig(BaseModel):
    """Cancel running cron job."""

    operation: Literal["cancel_cron_job_run"] = Field(
        "cancel_cron_job_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Services - Cron Jobs",
            "x-display-name": "Cancel running cron job",
            "x-keywords": ["cancel", "cron", "job", "run", "services", "jobs"],
        },
    )
    cron_job_id: str = Field(
        ..., title="cronJobId", description="The ID of the cron job"
    )


class RenderRetrieveEventConfig(BaseModel):
    """Retrieve event."""

    operation: Literal["retrieve_event"] = Field(
        "retrieve_event",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Events",
            "x-display-name": "Retrieve event",
            "x-keywords": ["retrieve", "event", "events"],
        },
    )
    event_id: str = Field(..., title="eventId", description="The ID of the event")


class RenderListLogsConfig(BaseModel):
    """List logs."""

    operation: Literal["list_logs"] = Field(
        "list_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "List logs",
            "x-keywords": ["list", "logs"],
        },
    )
    owner_id: str = Field(
        ..., title="ownerId", description="The ID of the workspace to return logs for"
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    direction: Optional[str] = Field(
        None,
        title="direction",
        description="The direction to query logs for. Backward will return most recent logs first. Forward will start with the oldest logs in the time range.",
        json_schema_extra={"enum": ["forward", "backward"]},
    )
    resource: str = Field(
        ...,
        title="resource",
        description="Filter logs by their resource. A resource is the id of a server, cronjob, job, postgres, redis, workflow, or sandbox group. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    instance: Optional[str] = Field(
        None,
        title="instance",
        description="Filter logs by the instance they were emitted from. An instance is the id of a specific running server. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    host: Optional[str] = Field(
        None,
        title="host",
        description="Filter request logs by their host. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    status_code: Optional[str] = Field(
        None,
        title="statusCode",
        description="Filter request logs by their status code. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    method: Optional[str] = Field(
        None,
        title="method",
        description="Filter request logs by their requests method. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    task: Optional[str] = Field(
        None,
        title="task",
        description="Filter logs by their task(s) Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    task_run: Optional[str] = Field(
        None,
        title="taskRun",
        description="Filter logs by their task run id(s) Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    sandbox: Optional[str] = Field(
        None,
        title="sandbox",
        description="Filter logs by sandbox ID. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    level: Optional[str] = Field(
        None,
        title="level",
        description="Filter logs by their severity level. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    type: Optional[str] = Field(
        None,
        title="type",
        description="Filter logs by their type. Types include `app` for application logs, `request` for request logs, and `build` for build logs. You can find the full set of types available for a query by using the `GET /logs/values` endpoint. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    text: Optional[str] = Field(
        None,
        title="text",
        description="Filter by the text of the logs. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    path: Optional[str] = Field(
        None,
        title="path",
        description="Filter request logs by their path. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderListLogsValuesConfig(BaseModel):
    """List log label values."""

    operation: Literal["list_logs_values"] = Field(
        "list_logs_values",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "List log label values",
            "x-keywords": ["list", "logs", "values"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return log label values for",
    )
    label: str = Field(
        ...,
        title="label",
        description="The label to query logs for",
        json_schema_extra={
            "enum": ["instance", "host", "statusCode", "method", "level", "type"]
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    direction: Optional[str] = Field(
        None,
        title="direction",
        description="The direction to query logs for. Backward will return most recent logs first. Forward will start with the oldest logs in the time range.",
        json_schema_extra={"enum": ["forward", "backward"]},
    )
    resource: str = Field(
        ...,
        title="resource",
        description="Filter logs by their resource. A resource is the id of a server, cronjob, job, postgres, redis, workflow, or sandbox group. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    instance: Optional[str] = Field(
        None,
        title="instance",
        description="Filter logs by the instance they were emitted from. An instance is the id of a specific running server. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    host: Optional[str] = Field(
        None,
        title="host",
        description="Filter request logs by their host. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    status_code: Optional[str] = Field(
        None,
        title="statusCode",
        description="Filter request logs by their status code. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    method: Optional[str] = Field(
        None,
        title="method",
        description="Filter request logs by their requests method. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    task: Optional[str] = Field(
        None,
        title="task",
        description="Filter logs by their task(s) Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    task_run: Optional[str] = Field(
        None,
        title="taskRun",
        description="Filter logs by their task run id(s) Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    sandbox: Optional[str] = Field(
        None,
        title="sandbox",
        description="Filter logs by sandbox ID. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    level: Optional[str] = Field(
        None,
        title="level",
        description="Filter logs by their severity level. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    type: Optional[str] = Field(
        None,
        title="type",
        description="Filter logs by their type. Types include `app` for application logs, `request` for request logs, and `build` for build logs. You can find the full set of types available for a query by using the `GET /logs/values` endpoint. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    text: Optional[str] = Field(
        None,
        title="text",
        description="Filter by the text of the logs. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    path: Optional[str] = Field(
        None,
        title="path",
        description="Filter request logs by their path. are supported. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderGetOwnerLogStreamConfig(BaseModel):
    """Retrieve log stream."""

    operation: Literal["get_owner_log_stream"] = Field(
        "get_owner_log_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "Retrieve log stream",
            "x-keywords": ["get", "owner", "log", "stream", "logs"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return log stream information for",
    )


class RenderUpdateOwnerLogStreamConfig(RenderRequestBodyConfig):
    """Update log stream."""

    operation: Literal["update_owner_log_stream"] = Field(
        "update_owner_log_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "Update log stream",
            "x-keywords": ["update", "owner", "log", "stream", "logs"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to update log stream information for",
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: preview.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteOwnerLogStreamConfig(BaseModel):
    """Delete log stream."""

    operation: Literal["delete_owner_log_stream"] = Field(
        "delete_owner_log_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "Delete log stream",
            "x-keywords": ["delete", "owner", "log", "stream", "logs"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to delete the log stream for",
    )


class RenderListResourceLogStreamsConfig(BaseModel):
    """List log stream overrides."""

    operation: Literal["list_resource_log_streams"] = Field(
        "list_resource_log_streams",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "List log stream overrides",
            "x-keywords": ["list", "resource", "log", "streams", "logs"],
        },
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    log_stream_id: Optional[str] = Field(
        None,
        title="logStreamId",
        description="Filter log streams by their id. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    resource_id: Optional[str] = Field(
        None,
        title="resourceId",
        description="IDs of resources (server, cron job, postgres, or redis) to filter by Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    setting: Optional[str] = Field(
        None,
        title="setting",
        description="Filter log streams by their setting. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderGetResourceLogStreamConfig(BaseModel):
    """Retrieve log stream override."""

    operation: Literal["get_resource_log_stream"] = Field(
        "get_resource_log_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "Retrieve log stream override",
            "x-keywords": ["get", "resource", "log", "stream", "logs"],
        },
    )
    resource_id: str = Field(
        ...,
        title="resourceId",
        description="The ID of the resource (server, cron job, postgres, or redis) to return log stream override information for",
    )


class RenderUpdateResourceLogStreamConfig(RenderRequestBodyConfig):
    """Update log stream override."""

    operation: Literal["update_resource_log_stream"] = Field(
        "update_resource_log_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "Update log stream override",
            "x-keywords": ["update", "resource", "log", "stream", "logs"],
        },
    )
    resource_id: str = Field(
        ...,
        title="resourceId",
        description="The ID of the resource (server, cron job, postgres, or redis) to update log stream override information for",
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: setting.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteResourceLogStreamConfig(BaseModel):
    """Delete log stream override."""

    operation: Literal["delete_resource_log_stream"] = Field(
        "delete_resource_log_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Logs",
            "x-display-name": "Delete log stream override",
            "x-keywords": ["delete", "resource", "log", "stream", "logs"],
        },
    )
    resource_id: str = Field(
        ...,
        title="resourceId",
        description="The ID of the resource (server, cron job, postgres, or redis) whose log streams should be returned",
    )


class RenderGetOwnerMetricsStreamConfig(BaseModel):
    """Retrieve metrics stream."""

    operation: Literal["get_owner_metrics_stream"] = Field(
        "get_owner_metrics_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Retrieve metrics stream",
            "x-keywords": ["get", "owner", "metrics", "stream"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return metrics stream information for",
    )


class RenderUpsertOwnerMetricsStreamConfig(RenderRequestBodyConfig):
    """Create or update metrics stream."""

    operation: Literal["upsert_owner_metrics_stream"] = Field(
        "upsert_owner_metrics_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Create or update metrics stream",
            "x-keywords": ["upsert", "owner", "metrics", "stream"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return metrics stream information for",
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteOwnerMetricsStreamConfig(BaseModel):
    """Delete metrics stream."""

    operation: Literal["delete_owner_metrics_stream"] = Field(
        "delete_owner_metrics_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Delete metrics stream",
            "x-keywords": ["delete", "owner", "metrics", "stream"],
        },
    )
    owner_id: str = Field(
        ...,
        title="ownerId",
        description="The ID of the workspace to return metrics stream information for",
    )


class RenderGetCpuConfig(BaseModel):
    """Get CPU usage."""

    operation: Literal["get_cpu"] = Field(
        "get_cpu",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get CPU usage",
            "x-keywords": ["get", "cpu", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    instance: Optional[str] = Field(
        None,
        title="instance",
        description="Instance ID to query. When multiple instance ID query params are provided, they are ORed together",
    )
    aggregation_method: Optional[str] = Field(
        None,
        title="aggregationMethod",
        description="The aggregation method to apply to multiple time series",
        json_schema_extra={"enum": ["AVG", "MAX", "MIN"]},
    )


class RenderGetCpuLimitConfig(BaseModel):
    """Get CPU limit."""

    operation: Literal["get_cpu_limit"] = Field(
        "get_cpu_limit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get CPU limit",
            "x-keywords": ["get", "cpu", "limit", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    instance: Optional[str] = Field(
        None,
        title="instance",
        description="Instance ID to query. When multiple instance ID query params are provided, they are ORed together",
    )


class RenderGetCpuTargetConfig(BaseModel):
    """Get CPU target."""

    operation: Literal["get_cpu_target"] = Field(
        "get_cpu_target",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get CPU target",
            "x-keywords": ["get", "cpu", "target", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    instance: Optional[str] = Field(
        None,
        title="instance",
        description="Instance ID to query. When multiple instance ID query params are provided, they are ORed together",
    )


class RenderGetMemoryConfig(BaseModel):
    """Get memory usage."""

    operation: Literal["get_memory"] = Field(
        "get_memory",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get memory usage",
            "x-keywords": ["get", "memory", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    instance: Optional[str] = Field(
        None,
        title="instance",
        description="Instance ID to query. When multiple instance ID query params are provided, they are ORed together",
    )


class RenderGetMemoryLimitConfig(BaseModel):
    """Get memory limit."""

    operation: Literal["get_memory_limit"] = Field(
        "get_memory_limit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get memory limit",
            "x-keywords": ["get", "memory", "limit", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    instance: Optional[str] = Field(
        None,
        title="instance",
        description="Instance ID to query. When multiple instance ID query params are provided, they are ORed together",
    )


class RenderGetMemoryTargetConfig(BaseModel):
    """Get memory target."""

    operation: Literal["get_memory_target"] = Field(
        "get_memory_target",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get memory target",
            "x-keywords": ["get", "memory", "target", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    instance: Optional[str] = Field(
        None,
        title="instance",
        description="Instance ID to query. When multiple instance ID query params are provided, they are ORed together",
    )


class RenderGetHttpRequestsConfig(BaseModel):
    """Get HTTP request count."""

    operation: Literal["get_http_requests"] = Field(
        "get_http_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get HTTP request count",
            "x-keywords": ["get", "http", "requests", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Service ID to query. When multiple service ids are provided, they are ORed together",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    host: Optional[str] = Field(
        None,
        title="host",
        description="The hosts of HTTP requests to filter to. When multiple host query params are provided, they are ORed together",
    )
    path: Optional[str] = Field(
        None,
        title="path",
        description="The paths of HTTP requests to filter to. When multiple path query params are provided, they are ORed together",
    )
    aggregate_by: Optional[str] = Field(
        None,
        title="aggregateBy",
        description="The field to aggregate by",
        json_schema_extra={"enum": ["statusCode", "host"]},
    )


class RenderGetHttpLatencyConfig(BaseModel):
    """Get HTTP latency."""

    operation: Literal["get_http_latency"] = Field(
        "get_http_latency",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get HTTP latency",
            "x-keywords": ["get", "http", "latency", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Service ID to query. When multiple service ids are provided, they are ORed together",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    host: Optional[str] = Field(
        None,
        title="host",
        description="The hosts of HTTP requests to filter to. When multiple host query params are provided, they are ORed together",
    )
    path: Optional[str] = Field(
        None,
        title="path",
        description="The paths of HTTP requests to filter to. When multiple path query params are provided, they are ORed together",
    )
    quantile: Optional[float] = Field(
        None,
        title="quantile",
        description="The quantile of latencies to fetch. When multiple quantile query params are provided, they are ORed together",
    )


class RenderGetBandwidthConfig(BaseModel):
    """Get bandwidth usage."""

    operation: Literal["get_bandwidth"] = Field(
        "get_bandwidth",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get bandwidth usage",
            "x-keywords": ["get", "bandwidth", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Service ID to query. When multiple service ids are provided, they are ORed together",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )


class RenderGetBandwidthSourcesConfig(BaseModel):
    """Get bandwidth usage breakdown by traffic source."""

    operation: Literal["get_bandwidth_sources"] = Field(
        "get_bandwidth_sources",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get bandwidth usage breakdown by traffic source",
            "x-keywords": ["get", "bandwidth", "sources", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Service ID to query. When multiple service ids are provided, they are ORed together",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )


class RenderGetDiskUsageConfig(BaseModel):
    """Get disk usage."""

    operation: Literal["get_disk_usage"] = Field(
        "get_disk_usage",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get disk usage",
            "x-keywords": ["get", "disk", "usage", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )


class RenderGetDiskCapacityConfig(BaseModel):
    """Get disk capacity."""

    operation: Literal["get_disk_capacity"] = Field(
        "get_disk_capacity",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get disk capacity",
            "x-keywords": ["get", "disk", "capacity", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )


class RenderGetInstanceCountConfig(BaseModel):
    """Get instance count."""

    operation: Literal["get_instance_count"] = Field(
        "get_instance_count",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get instance count",
            "x-keywords": ["get", "instance", "count", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources can be service ids, Postgres ids, or Redis ids",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )


class RenderGetActiveConnectionsConfig(BaseModel):
    """Get active connection count."""

    operation: Literal["get_active_connections"] = Field(
        "get_active_connections",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get active connection count",
            "x-keywords": ["get", "active", "connections", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Resource ID to query. When multiple resource query params are provided, they are ORed together. Resources Postgres ids or Redis ids",
    )


class RenderGetReplicationLagConfig(BaseModel):
    """Get replica lag."""

    operation: Literal["get_replication_lag"] = Field(
        "get_replication_lag",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get replica lag",
            "x-keywords": ["get", "replication", "lag", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Postgres ID to query. When multiple resource query params are provided, they are ORed together",
    )


class RenderListApplicationFilterValuesConfig(BaseModel):
    """List queryable instance values."""

    operation: Literal["list_application_filter_values"] = Field(
        "list_application_filter_values",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "List queryable instance values",
            "x-keywords": ["list", "application", "filter", "values", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Service ID to query. When multiple service ids are provided, they are ORed together",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )


class RenderListHttpFilterValuesConfig(BaseModel):
    """List queryable status codes and host values."""

    operation: Literal["list_http_filter_values"] = Field(
        "list_http_filter_values",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "List queryable status codes and host values",
            "x-keywords": ["list", "http", "filter", "values", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Service ID to query. When multiple service ids are provided, they are ORed together",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    host: Optional[str] = Field(
        None,
        title="host",
        description="The hosts of HTTP requests to filter to. When multiple host query params are provided, they are ORed together",
    )
    status_code: Optional[str] = Field(
        None,
        title="statusCode",
        description="The status codes of HTTP requests to filter to. When multiple status code query params are provided, they are ORed together",
    )


class RenderListPathFilterValuesConfig(BaseModel):
    """List queryable paths."""

    operation: Literal["list_path_filter_values"] = Field(
        "list_path_filter_values",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "List queryable paths",
            "x-keywords": ["list", "path", "filter", "values", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Service ID to query. When multiple service ids are provided, they are ORed together",
    )
    service: Optional[str] = Field(
        None,
        title="service",
        description="This parameter is deprecated. Please use `resource` instead",
    )
    host: Optional[str] = Field(
        None,
        title="host",
        description="The hosts of HTTP requests to filter to. When multiple host query params are provided, they are ORed together",
    )
    status_code: Optional[str] = Field(
        None,
        title="statusCode",
        description="The status codes of HTTP requests to filter to. When multiple status code query params are provided, they are ORed together",
    )
    path: Optional[str] = Field(
        None,
        title="path",
        description="The paths of HTTP requests to filter to. When multiple path query params are provided, they are ORed together",
    )


class RenderGetTaskRunsQueuedConfig(BaseModel):
    """Get task runs queued count."""

    operation: Literal["get_task_runs_queued"] = Field(
        "get_task_runs_queued",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get task runs queued count",
            "x-keywords": ["get", "task", "runs", "queued", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Task ID to query. When multiple task IDs are provided, they are ORed together",
    )


class RenderGetTaskRunsCompletedConfig(BaseModel):
    """Get task runs completed count."""

    operation: Literal["get_task_runs_completed"] = Field(
        "get_task_runs_completed",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-display-name": "Get task runs completed count",
            "x-keywords": ["get", "task", "runs", "completed", "metrics"],
        },
    )
    start_time: Optional[str] = Field(
        None,
        title="startTime",
        description="Epoch/Unix timestamp of start of time range to return. Defaults to `now() - 1 hour`.",
    )
    end_time: Optional[str] = Field(
        None,
        title="endTime",
        description="Epoch/Unix timestamp of end of time range to return. Defaults to `now()`.",
    )
    resolution_seconds: Optional[float] = Field(
        None,
        title="resolutionSeconds",
        description="The resolution of the returned data",
    )
    resource: Optional[str] = Field(
        None,
        title="resource",
        description="Task ID to query. When multiple task IDs are provided, they are ORed together",
    )
    state: Optional[str] = Field(
        None,
        title="state",
        description="The state of task runs to filter to. When multiple state query params are provided, they are ORed together",
        json_schema_extra={"enum": ["succeeded", "failed"]},
    )
    aggregate_by: Optional[str] = Field(
        None,
        title="aggregateBy",
        description="The field to aggregate by",
        json_schema_extra={"enum": ["state"]},
    )


class RenderListKeyValueConfig(BaseModel):
    """List Key Value instances."""

    operation: Literal["list_key_value"] = Field(
        "list_key_value",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key Value",
            "x-display-name": "List Key Value instances",
            "x-keywords": ["list", "key", "value"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    region: Optional[str] = Field(
        None,
        title="region",
        description="Filter by resource region Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for resources created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for resources created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for resources updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for resources updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    environment_id: Optional[str] = Field(
        None,
        title="environmentId",
        description="Filter for resources that belong to an environment Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreateKeyValueConfig(RenderRequestBodyConfig):
    """Create Key Value instance."""

    operation: Literal["create_key_value"] = Field(
        "create_key_value",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key Value",
            "x-display-name": "Create Key Value instance",
            "x-keywords": ["create", "key", "value"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, ownerId, plan.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveKeyValueConfig(BaseModel):
    """Retrieve Key Value instance."""

    operation: Literal["retrieve_key_value"] = Field(
        "retrieve_key_value",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key Value",
            "x-display-name": "Retrieve Key Value instance",
            "x-keywords": ["retrieve", "key", "value"],
        },
    )
    redis_id: str = Field(..., title="redisId", description="redisId path parameter.")


class RenderUpdateKeyValueConfig(RenderRequestBodyConfig):
    """Update Key Value instance."""

    operation: Literal["update_key_value"] = Field(
        "update_key_value",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key Value",
            "x-display-name": "Update Key Value instance",
            "x-keywords": ["update", "key", "value"],
        },
    )
    redis_id: str = Field(..., title="redisId", description="redisId path parameter.")
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteKeyValueConfig(BaseModel):
    """Delete Key Value instance."""

    operation: Literal["delete_key_value"] = Field(
        "delete_key_value",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key Value",
            "x-display-name": "Delete Key Value instance",
            "x-keywords": ["delete", "key", "value"],
        },
    )
    redis_id: str = Field(..., title="redisId", description="redisId path parameter.")


class RenderRetrieveKeyValueConnectionInfoConfig(BaseModel):
    """Retrieve Key Value connection info."""

    operation: Literal["retrieve_key_value_connection_info"] = Field(
        "retrieve_key_value_connection_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key Value",
            "x-display-name": "Retrieve Key Value connection info",
            "x-keywords": ["retrieve", "key", "value", "connection", "info"],
        },
    )
    redis_id: str = Field(..., title="redisId", description="redisId path parameter.")


class RenderSuspendKeyValueConfig(BaseModel):
    """Suspend Key Value instance."""

    operation: Literal["suspend_key_value"] = Field(
        "suspend_key_value",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key Value",
            "x-display-name": "Suspend Key Value instance",
            "x-keywords": ["suspend", "key", "value"],
        },
    )
    redis_id: str = Field(..., title="redisId", description="redisId path parameter.")


class RenderResumeKeyValueConfig(BaseModel):
    """Resume Key Value instance."""

    operation: Literal["resume_key_value"] = Field(
        "resume_key_value",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key Value",
            "x-display-name": "Resume Key Value instance",
            "x-keywords": ["resume", "key", "value"],
        },
    )
    redis_id: str = Field(..., title="redisId", description="redisId path parameter.")


class RenderListPostgresConfig(BaseModel):
    """List Postgres instances."""

    operation: Literal["list_postgres"] = Field(
        "list_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "List Postgres instances",
            "x-keywords": ["list", "postgres"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    region: Optional[str] = Field(
        None,
        title="region",
        description="Filter by resource region Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    suspended: Optional[str] = Field(
        None,
        title="suspended",
        description="Filter resources based on whether they're suspended or not suspended Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for resources created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for resources created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for resources updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for resources updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    environment_id: Optional[str] = Field(
        None,
        title="environmentId",
        description="Filter for resources that belong to an environment Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    include_replicas: Optional[bool] = Field(
        None, title="includeReplicas", description="Include replicas in the response"
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreatePostgresConfig(RenderRequestBodyConfig):
    """Create Postgres instance."""

    operation: Literal["create_postgres"] = Field(
        "create_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Create Postgres instance",
            "x-keywords": ["create", "postgres"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, plan, ownerId, version.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrievePostgresConfig(BaseModel):
    """Retrieve Postgres instance."""

    operation: Literal["retrieve_postgres"] = Field(
        "retrieve_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Retrieve Postgres instance",
            "x-keywords": ["retrieve", "postgres"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderUpdatePostgresConfig(RenderRequestBodyConfig):
    """Update Postgres instance."""

    operation: Literal["update_postgres"] = Field(
        "update_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Update Postgres instance",
            "x-keywords": ["update", "postgres"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeletePostgresConfig(BaseModel):
    """Delete Postgres instance."""

    operation: Literal["delete_postgres"] = Field(
        "delete_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Delete Postgres instance",
            "x-keywords": ["delete", "postgres"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderRetrievePostgresConnectionInfoConfig(BaseModel):
    """Retrieve Postgres connection info."""

    operation: Literal["retrieve_postgres_connection_info"] = Field(
        "retrieve_postgres_connection_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Retrieve Postgres connection info",
            "x-keywords": ["retrieve", "postgres", "connection", "info"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderRetrievePostgresRecoveryInfoConfig(BaseModel):
    """Retrieve point-in-time recovery status."""

    operation: Literal["retrieve_postgres_recovery_info"] = Field(
        "retrieve_postgres_recovery_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Retrieve point-in-time recovery status",
            "x-keywords": ["retrieve", "postgres", "recovery", "info"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderRecoverPostgresConfig(RenderRequestBodyConfig):
    """Trigger point-in-time recovery."""

    operation: Literal["recover_postgres"] = Field(
        "recover_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Trigger point-in-time recovery",
            "x-keywords": ["recover", "postgres"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderSuspendPostgresConfig(BaseModel):
    """Suspend Postgres instance."""

    operation: Literal["suspend_postgres"] = Field(
        "suspend_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Suspend Postgres instance",
            "x-keywords": ["suspend", "postgres"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderResumePostgresConfig(BaseModel):
    """Resume Postgres instance."""

    operation: Literal["resume_postgres"] = Field(
        "resume_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Resume Postgres instance",
            "x-keywords": ["resume", "postgres"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderRestartPostgresConfig(BaseModel):
    """Restart Postgres instance."""

    operation: Literal["restart_postgres"] = Field(
        "restart_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Restart Postgres instance",
            "x-keywords": ["restart", "postgres"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderFailoverPostgresConfig(BaseModel):
    """Failover Postgres instance."""

    operation: Literal["failover_postgres"] = Field(
        "failover_postgres",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Failover Postgres instance",
            "x-keywords": ["failover", "postgres"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderListPostgresExportConfig(BaseModel):
    """List Postgres exports."""

    operation: Literal["list_postgres_export"] = Field(
        "list_postgres_export",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "List Postgres exports",
            "x-keywords": ["list", "postgres", "export"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderCreatePostgresExportConfig(BaseModel):
    """Create Postgres export."""

    operation: Literal["create_postgres_export"] = Field(
        "create_postgres_export",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Create Postgres export",
            "x-keywords": ["create", "postgres", "export"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderListPostgresUsersConfig(BaseModel):
    """List PostgreSQL Users."""

    operation: Literal["list_postgres_users"] = Field(
        "list_postgres_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "List PostgreSQL Users",
            "x-keywords": ["list", "postgres", "users"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderCreatePostgresUserConfig(RenderRequestBodyConfig):
    """Create PostgreSQL User."""

    operation: Literal["create_postgres_user"] = Field(
        "create_postgres_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Create PostgreSQL User",
            "x-keywords": ["create", "postgres", "user"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: username.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeletePostgresUserConfig(BaseModel):
    """Delete PostgreSQL User."""

    operation: Literal["delete_postgres_user"] = Field(
        "delete_postgres_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "Delete PostgreSQL User",
            "x-keywords": ["delete", "postgres", "user"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )
    username: str = Field(..., title="username", description="username path parameter.")


class RenderListPostgresProcessesConfig(BaseModel):
    """List live queries."""

    operation: Literal["list_postgres_processes"] = Field(
        "list_postgres_processes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "List live queries",
            "x-keywords": ["list", "postgres", "processes"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderListPostgresTopQueriesConfig(BaseModel):
    """List top queries."""

    operation: Literal["list_postgres_top_queries"] = Field(
        "list_postgres_top_queries",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "List top queries",
            "x-keywords": ["list", "postgres", "top", "queries"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderListPostgresSizesConfig(BaseModel):
    """List database, table, and index sizes."""

    operation: Literal["list_postgres_sizes"] = Field(
        "list_postgres_sizes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "List database, table, and index sizes",
            "x-keywords": ["list", "postgres", "sizes"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderListPostgresTableScansConfig(BaseModel):
    """List table scans."""

    operation: Literal["list_postgres_table_scans"] = Field(
        "list_postgres_table_scans",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Postgres",
            "x-display-name": "List table scans",
            "x-keywords": ["list", "postgres", "table", "scans"],
        },
    )
    postgres_id: str = Field(
        ..., title="postgresId", description="postgresId path parameter."
    )


class RenderListProjectsConfig(BaseModel):
    """List projects."""

    operation: Literal["list_projects"] = Field(
        "list_projects",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "List projects",
            "x-keywords": ["list", "projects", "environments"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for resources created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for resources created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for resources updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for resources updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreateProjectConfig(RenderRequestBodyConfig):
    """Create project."""

    operation: Literal["create_project"] = Field(
        "create_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Create project",
            "x-keywords": ["create", "project", "projects", "environments"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, ownerId, environments.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveProjectConfig(BaseModel):
    """Retrieve Project."""

    operation: Literal["retrieve_project"] = Field(
        "retrieve_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Retrieve Project",
            "x-keywords": ["retrieve", "project", "projects", "environments"],
        },
    )
    project_id: str = Field(
        ..., title="projectId", description="projectId path parameter."
    )


class RenderUpdateProjectConfig(RenderRequestBodyConfig):
    """Update project."""

    operation: Literal["update_project"] = Field(
        "update_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Update project",
            "x-keywords": ["update", "project", "projects", "environments"],
        },
    )
    project_id: str = Field(
        ..., title="projectId", description="projectId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteProjectConfig(BaseModel):
    """Delete project."""

    operation: Literal["delete_project"] = Field(
        "delete_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Delete project",
            "x-keywords": ["delete", "project", "projects", "environments"],
        },
    )
    project_id: str = Field(
        ..., title="projectId", description="projectId path parameter."
    )


class RenderCreateEnvironmentConfig(RenderRequestBodyConfig):
    """Create environment."""

    operation: Literal["create_environment"] = Field(
        "create_environment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Create environment",
            "x-keywords": ["create", "environment", "projects", "environments"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, projectId.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderListEnvironmentsConfig(BaseModel):
    """List environments."""

    operation: Literal["list_environments"] = Field(
        "list_environments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "List environments",
            "x-keywords": ["list", "environments", "projects"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    project_id: str = Field(
        ...,
        title="projectId",
        description="Filter for resources that belong to a project Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for resources created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for resources created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for resources updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for resources updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    environment_id: Optional[str] = Field(
        None,
        title="environmentId",
        description="Filter for resources that belong to an environment Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderRetrieveEnvironmentConfig(BaseModel):
    """Retrieve environment."""

    operation: Literal["retrieve_environment"] = Field(
        "retrieve_environment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Retrieve environment",
            "x-keywords": ["retrieve", "environment", "projects", "environments"],
        },
    )
    environment_id: str = Field(
        ..., title="environmentId", description="environmentId path parameter."
    )


class RenderUpdateEnvironmentConfig(RenderRequestBodyConfig):
    """Update environment."""

    operation: Literal["update_environment"] = Field(
        "update_environment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Update environment",
            "x-keywords": ["update", "environment", "projects", "environments"],
        },
    )
    environment_id: str = Field(
        ..., title="environmentId", description="environmentId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteEnvironmentConfig(BaseModel):
    """Delete environment."""

    operation: Literal["delete_environment"] = Field(
        "delete_environment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Delete environment",
            "x-keywords": ["delete", "environment", "projects", "environments"],
        },
    )
    environment_id: str = Field(
        ..., title="environmentId", description="environmentId path parameter."
    )


class RenderAddResourcesToEnvironmentConfig(RenderRequestBodyConfig):
    """Add resources to environment."""

    operation: Literal["add_resources_to_environment"] = Field(
        "add_resources_to_environment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Add resources to environment",
            "x-keywords": [
                "add",
                "resources",
                "to",
                "environment",
                "projects",
                "environments",
            ],
        },
    )
    environment_id: str = Field(
        ..., title="environmentId", description="environmentId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: resourceIds.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRemoveResourcesFromEnvironmentConfig(BaseModel):
    """Remove resources from environment."""

    operation: Literal["remove_resources_from_environment"] = Field(
        "remove_resources_from_environment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Projects & Environments",
            "x-display-name": "Remove resources from environment",
            "x-keywords": [
                "remove",
                "resources",
                "from",
                "environment",
                "projects",
                "environments",
            ],
        },
    )
    environment_id: str = Field(
        ..., title="environmentId", description="environmentId path parameter."
    )
    resource_ids: str = Field(
        ...,
        title="resourceIds",
        description="resourceIds query parameter. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )


class RenderListEnvGroupsConfig(BaseModel):
    """List environment groups."""

    operation: Literal["list_env_groups"] = Field(
        "list_env_groups",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "List environment groups",
            "x-keywords": ["list", "env", "groups", "environment"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for resources created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for resources created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for resources updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for resources updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    environment_id: Optional[str] = Field(
        None,
        title="environmentId",
        description="Filter for resources that belong to an environment Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreateEnvGroupConfig(RenderRequestBodyConfig):
    """Create environment group."""

    operation: Literal["create_env_group"] = Field(
        "create_env_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Create environment group",
            "x-keywords": ["create", "env", "group", "environment", "groups"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, ownerId, envVars.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveEnvGroupConfig(BaseModel):
    """Retrieve environment group."""

    operation: Literal["retrieve_env_group"] = Field(
        "retrieve_env_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Retrieve environment group",
            "x-keywords": ["retrieve", "env", "group", "environment", "groups"],
        },
    )
    env_group_id: str = Field(
        ...,
        title="envGroupId",
        description="Filter for resources that belong to an environment group",
    )


class RenderUpdateEnvGroupConfig(RenderRequestBodyConfig):
    """Update environment group."""

    operation: Literal["update_env_group"] = Field(
        "update_env_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Update environment group",
            "x-keywords": ["update", "env", "group", "environment", "groups"],
        },
    )
    env_group_id: str = Field(
        ..., title="envGroupId", description="envGroupId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteEnvGroupConfig(BaseModel):
    """Delete environment group."""

    operation: Literal["delete_env_group"] = Field(
        "delete_env_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Delete environment group",
            "x-keywords": ["delete", "env", "group", "environment", "groups"],
        },
    )
    env_group_id: str = Field(
        ..., title="envGroupId", description="envGroupId path parameter."
    )


class RenderLinkServiceToEnvGroupConfig(BaseModel):
    """Link service."""

    operation: Literal["link_service_to_env_group"] = Field(
        "link_service_to_env_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Link service",
            "x-keywords": [
                "link",
                "service",
                "to",
                "env",
                "group",
                "environment",
                "groups",
            ],
        },
    )
    env_group_id: str = Field(
        ...,
        title="envGroupId",
        description="Filter for resources that belong to an environment group",
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="The ID of the service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderUnlinkServiceFromEnvGroupConfig(BaseModel):
    """Unlink service."""

    operation: Literal["unlink_service_from_env_group"] = Field(
        "unlink_service_from_env_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Unlink service",
            "x-keywords": [
                "unlink",
                "service",
                "from",
                "env",
                "group",
                "environment",
                "groups",
            ],
        },
    )
    env_group_id: str = Field(
        ..., title="envGroupId", description="envGroupId path parameter."
    )
    service_id: str = Field(
        ...,
        title="serviceId",
        description="serviceId path parameter.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a Render service",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a service ID",
            }
        },
    )


class RenderRetrieveEnvGroupEnvVarConfig(BaseModel):
    """Retrieve environment variable."""

    operation: Literal["retrieve_env_group_env_var"] = Field(
        "retrieve_env_group_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Retrieve environment variable",
            "x-keywords": ["retrieve", "env", "group", "var", "environment", "groups"],
        },
    )
    env_group_id: str = Field(
        ...,
        title="envGroupId",
        description="Filter for resources that belong to an environment group",
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )


class RenderUpdateEnvGroupEnvVarConfig(RenderRequestBodyConfig):
    """Add or update environment variable."""

    operation: Literal["update_env_group_env_var"] = Field(
        "update_env_group_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Add or update environment variable",
            "x-keywords": ["update", "env", "group", "var", "environment", "groups"],
        },
    )
    env_group_id: str = Field(
        ...,
        title="envGroupId",
        description="Filter for resources that belong to an environment group",
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteEnvGroupEnvVarConfig(BaseModel):
    """Remove environment variable."""

    operation: Literal["delete_env_group_env_var"] = Field(
        "delete_env_group_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Remove environment variable",
            "x-keywords": ["delete", "env", "group", "var", "environment", "groups"],
        },
    )
    env_group_id: str = Field(
        ..., title="envGroupId", description="envGroupId path parameter."
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )


class RenderRetrieveEnvGroupSecretFileConfig(BaseModel):
    """Retrieve secret file."""

    operation: Literal["retrieve_env_group_secret_file"] = Field(
        "retrieve_env_group_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Retrieve secret file",
            "x-keywords": [
                "retrieve",
                "env",
                "group",
                "secret",
                "file",
                "environment",
                "groups",
            ],
        },
    )
    env_group_id: str = Field(
        ...,
        title="envGroupId",
        description="Filter for resources that belong to an environment group",
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the secret file"
    )


class RenderUpdateEnvGroupSecretFileConfig(RenderRequestBodyConfig):
    """Add or update secret file."""

    operation: Literal["update_env_group_secret_file"] = Field(
        "update_env_group_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Add or update secret file",
            "x-keywords": [
                "update",
                "env",
                "group",
                "secret",
                "file",
                "environment",
                "groups",
            ],
        },
    )
    env_group_id: str = Field(
        ..., title="envGroupId", description="envGroupId path parameter."
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="envVarKey path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteEnvGroupSecretFileConfig(BaseModel):
    """Remove secret file."""

    operation: Literal["delete_env_group_secret_file"] = Field(
        "delete_env_group_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Groups",
            "x-display-name": "Remove secret file",
            "x-keywords": [
                "delete",
                "env",
                "group",
                "secret",
                "file",
                "environment",
                "groups",
            ],
        },
    )
    env_group_id: str = Field(
        ...,
        title="envGroupId",
        description="Filter for resources that belong to an environment group",
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the secret file"
    )


class RenderListMaintenanceConfig(BaseModel):
    """List maintenance runs."""

    operation: Literal["list_maintenance"] = Field(
        "list_maintenance",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Maintenance",
            "x-display-name": "List maintenance runs",
            "x-keywords": ["list", "maintenance"],
        },
    )
    resource_id: Optional[str] = Field(
        None,
        title="resourceId",
        description="resourceId query parameter. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    state: Optional[str] = Field(
        None,
        title="state",
        description="state query parameter. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )


class RenderRetrieveMaintenanceConfig(BaseModel):
    """Retrieve maintenance run."""

    operation: Literal["retrieve_maintenance"] = Field(
        "retrieve_maintenance",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Maintenance",
            "x-display-name": "Retrieve maintenance run",
            "x-keywords": ["retrieve", "maintenance"],
        },
    )
    maintenance_run_id: str = Field(
        ..., title="maintenanceRunID", description="maintenanceRunID path parameter."
    )


class RenderUpdateMaintenanceConfig(RenderRequestBodyConfig):
    """Update maintenance run."""

    operation: Literal["update_maintenance"] = Field(
        "update_maintenance",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Maintenance",
            "x-display-name": "Update maintenance run",
            "x-keywords": ["update", "maintenance"],
        },
    )
    maintenance_run_id: str = Field(
        ..., title="maintenanceRunID", description="maintenanceRunID path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderTriggerMaintenanceConfig(BaseModel):
    """Trigger maintenance run."""

    operation: Literal["trigger_maintenance"] = Field(
        "trigger_maintenance",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Maintenance",
            "x-display-name": "Trigger maintenance run",
            "x-keywords": ["trigger", "maintenance"],
        },
    )
    maintenance_run_id: str = Field(
        ..., title="maintenanceRunID", description="maintenanceRunID path parameter."
    )


class RenderCreateBuildSourceConfig(RenderRequestBodyConfig):
    """Create a build source."""

    operation: Literal["create_build_source"] = Field(
        "create_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Create a build source",
            "x-keywords": ["create", "build", "source", "sources"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: ownerId, name.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderListBuildSourcesConfig(BaseModel):
    """List build sources."""

    operation: Literal["list_build_sources"] = Field(
        "list_build_sources",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "List build sources",
            "x-keywords": ["list", "build", "sources"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    project_id: Optional[str] = Field(
        None, title="projectId", description="projectId query parameter."
    )
    include_previews: Optional[bool] = Field(
        None, title="includePreviews", description="Include previews in the response"
    )
    created_before: Optional[str] = Field(
        None,
        title="createdBefore",
        description="Filter for resources created before a certain time (specified as an ISO 8601 timestamp)",
    )
    created_after: Optional[str] = Field(
        None,
        title="createdAfter",
        description="Filter for resources created after a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_before: Optional[str] = Field(
        None,
        title="updatedBefore",
        description="Filter for resources updated before a certain time (specified as an ISO 8601 timestamp)",
    )
    updated_after: Optional[str] = Field(
        None,
        title="updatedAfter",
        description="Filter for resources updated after a certain time (specified as an ISO 8601 timestamp)",
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderGetBuildSourceConfig(BaseModel):
    """Retrieve a build source."""

    operation: Literal["get_build_source"] = Field(
        "get_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Retrieve a build source",
            "x-keywords": ["get", "build", "source", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )


class RenderUpdateBuildSourceConfig(RenderRequestBodyConfig):
    """Update a build source."""

    operation: Literal["update_build_source"] = Field(
        "update_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Update a build source",
            "x-keywords": ["update", "build", "source", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteBuildSourceConfig(BaseModel):
    """Delete a build source."""

    operation: Literal["delete_build_source"] = Field(
        "delete_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Delete a build source",
            "x-keywords": ["delete", "build", "source", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )


class RenderListBuildsInBuildSourceConfig(BaseModel):
    """List builds in a build source."""

    operation: Literal["list_builds_in_build_source"] = Field(
        "list_builds_in_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "List builds in a build source",
            "x-keywords": ["list", "builds", "in", "build", "source", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderTriggerBuildSourceBuildConfig(BaseModel):
    """Trigger a build."""

    operation: Literal["trigger_build_source_build"] = Field(
        "trigger_build_source_build",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Trigger a build",
            "x-keywords": ["trigger", "build", "source", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )


class RenderGetEnvVarsForBuildSourceConfig(BaseModel):
    """List environment variables."""

    operation: Literal["get_env_vars_for_build_source"] = Field(
        "get_env_vars_for_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "List environment variables",
            "x-keywords": ["get", "env", "vars", "for", "build", "source", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderUpdateEnvVarsForBuildSourceConfig(RenderRequestBodyConfig):
    """Update environment variables."""

    operation: Literal["update_env_vars_for_build_source"] = Field(
        "update_env_vars_for_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Update environment variables",
            "x-keywords": [
                "update",
                "env",
                "vars",
                "for",
                "build",
                "source",
                "sources",
            ],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveBuildSourceEnvVarConfig(BaseModel):
    """Retrieve environment variable."""

    operation: Literal["retrieve_build_source_env_var"] = Field(
        "retrieve_build_source_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Retrieve environment variable",
            "x-keywords": ["retrieve", "build", "source", "env", "var", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )


class RenderUpdateBuildSourceEnvVarConfig(RenderRequestBodyConfig):
    """Add or update environment variable."""

    operation: Literal["update_build_source_env_var"] = Field(
        "update_build_source_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Add or update environment variable",
            "x-keywords": ["update", "build", "source", "env", "var", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteBuildSourceEnvVarConfig(BaseModel):
    """Delete environment variable."""

    operation: Literal["delete_build_source_env_var"] = Field(
        "delete_build_source_env_var",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Delete environment variable",
            "x-keywords": ["delete", "build", "source", "env", "var", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The name of the environment variable"
    )


class RenderListSecretFilesForBuildSourceConfig(BaseModel):
    """List secret files."""

    operation: Literal["list_secret_files_for_build_source"] = Field(
        "list_secret_files_for_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "List secret files",
            "x-keywords": [
                "list",
                "secret",
                "files",
                "for",
                "build",
                "source",
                "sources",
            ],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderUpdateSecretFilesForBuildSourceConfig(RenderRequestBodyConfig):
    """Update secret files."""

    operation: Literal["update_secret_files_for_build_source"] = Field(
        "update_secret_files_for_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Update secret files",
            "x-keywords": [
                "update",
                "secret",
                "files",
                "for",
                "build",
                "source",
                "sources",
            ],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderRetrieveBuildSourceSecretFileConfig(BaseModel):
    """Retrieve secret file."""

    operation: Literal["retrieve_build_source_secret_file"] = Field(
        "retrieve_build_source_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Retrieve secret file",
            "x-keywords": ["retrieve", "build", "source", "secret", "file", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The file name of the secret file"
    )


class RenderAddOrUpdateBuildSourceSecretFileConfig(RenderRequestBodyConfig):
    """Add or update secret file."""

    operation: Literal["add_or_update_build_source_secret_file"] = Field(
        "add_or_update_build_source_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Add or update secret file",
            "x-keywords": [
                "add",
                "or",
                "update",
                "build",
                "source",
                "secret",
                "file",
                "sources",
            ],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The file name of the secret file"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteBuildSourceSecretFileConfig(BaseModel):
    """Delete secret file."""

    operation: Literal["delete_build_source_secret_file"] = Field(
        "delete_build_source_secret_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Delete secret file",
            "x-keywords": ["delete", "build", "source", "secret", "file", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    env_var_key: str = Field(
        ..., title="envVarKey", description="The file name of the secret file"
    )


class RenderLinkEnvGroupToBuildSourceConfig(BaseModel):
    """Link environment group."""

    operation: Literal["link_env_group_to_build_source"] = Field(
        "link_env_group_to_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Link environment group",
            "x-keywords": ["link", "env", "group", "to", "build", "source", "sources"],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    env_group_id: str = Field(
        ...,
        title="envGroupId",
        description="Filter for resources that belong to an environment group",
    )


class RenderUnlinkEnvGroupFromBuildSourceConfig(BaseModel):
    """Unlink environment group."""

    operation: Literal["unlink_env_group_from_build_source"] = Field(
        "unlink_env_group_from_build_source",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Build Sources",
            "x-display-name": "Unlink environment group",
            "x-keywords": [
                "unlink",
                "env",
                "group",
                "from",
                "build",
                "source",
                "sources",
            ],
        },
    )
    build_source_id: str = Field(
        ..., title="buildSourceId", description="buildSourceId path parameter."
    )
    env_group_id: str = Field(
        ...,
        title="envGroupId",
        description="Filter for resources that belong to an environment group",
    )


class RenderCreateWebhookConfig(RenderRequestBodyConfig):
    """Create a webhook."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-display-name": "Create a webhook",
            "x-keywords": ["create", "webhook", "webhooks"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: ownerId, name, url, enabled, eventFilter.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderListWebhooksConfig(BaseModel):
    """List webhooks."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-display-name": "List webhooks",
            "x-keywords": ["list", "webhooks"],
        },
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )


class RenderRetrieveWebhookConfig(BaseModel):
    """Retrieve a webhook."""

    operation: Literal["retrieve_webhook"] = Field(
        "retrieve_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-display-name": "Retrieve a webhook",
            "x-keywords": ["retrieve", "webhook", "webhooks"],
        },
    )
    webhook_id: str = Field(
        ..., title="webhookId", description="Unique identifier for the webhook"
    )


class RenderUpdateWebhookConfig(RenderRequestBodyConfig):
    """Update a webhook."""

    operation: Literal["update_webhook"] = Field(
        "update_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-display-name": "Update a webhook",
            "x-keywords": ["update", "webhook", "webhooks"],
        },
    )
    webhook_id: str = Field(
        ..., title="webhookId", description="Unique identifier for the webhook"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteWebhookConfig(BaseModel):
    """Delete a webhook."""

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-display-name": "Delete a webhook",
            "x-keywords": ["delete", "webhook", "webhooks"],
        },
    )
    webhook_id: str = Field(
        ..., title="webhookId", description="Unique identifier for the webhook"
    )


class RenderListWebhookEventsConfig(BaseModel):
    """List webhook events."""

    operation: Literal["list_webhook_events"] = Field(
        "list_webhook_events",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-display-name": "List webhook events",
            "x-keywords": ["list", "webhook", "events", "webhooks"],
        },
    )
    webhook_id: str = Field(
        ..., title="webhookId", description="Unique identifier for the webhook"
    )
    sent_before: Optional[str] = Field(
        None,
        title="sentBefore",
        description="Filter events sent before this time (specified as an ISO 8601 timestamp)",
    )
    sent_after: Optional[str] = Field(
        None,
        title="sentAfter",
        description="Filter for resources sent after a certain time (specified as an ISO 8601 timestamp)",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )


class RenderListWorkflowsConfig(BaseModel):
    """List workflows."""

    operation: Literal["list_workflows"] = Field(
        "list_workflows",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-display-name": "List workflows",
            "x-keywords": ["list", "workflows"],
        },
    )
    name: Optional[str] = Field(
        None,
        title="name",
        description="Filter by name Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    workflow_id: Optional[str] = Field(
        None,
        title="workflowID",
        description="The IDs of the workflows to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    environment_id: Optional[str] = Field(
        None,
        title="environmentId",
        description="Filter for resources that belong to an environment Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreateWorkflowConfig(RenderRequestBodyConfig):
    """Create a workflow."""

    operation: Literal["create_workflow"] = Field(
        "create_workflow",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-display-name": "Create a workflow",
            "x-keywords": ["create", "workflow", "workflows"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: name, ownerId, region, runCommand, buildConfig.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderGetWorkflowConfig(BaseModel):
    """Retrieve workflow."""

    operation: Literal["get_workflow"] = Field(
        "get_workflow",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-display-name": "Retrieve workflow",
            "x-keywords": ["get", "workflow", "workflows"],
        },
    )
    workflow_id: str = Field(
        ..., title="workflowId", description="The ID of the workflow"
    )


class RenderUpdateWorkflowConfig(RenderRequestBodyConfig):
    """Update workflow."""

    operation: Literal["update_workflow"] = Field(
        "update_workflow",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-display-name": "Update workflow",
            "x-keywords": ["update", "workflow", "workflows"],
        },
    )
    workflow_id: str = Field(
        ..., title="workflowId", description="The ID of the workflow"
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderDeleteWorkflowConfig(BaseModel):
    """Delete workflow."""

    operation: Literal["delete_workflow"] = Field(
        "delete_workflow",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-display-name": "Delete workflow",
            "x-keywords": ["delete", "workflow", "workflows"],
        },
    )
    workflow_id: str = Field(
        ..., title="workflowId", description="The ID of the workflow"
    )


class RenderListWorkflowVersionsConfig(BaseModel):
    """List workflow versions."""

    operation: Literal["list_workflow_versions"] = Field(
        "list_workflow_versions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-display-name": "List workflow versions",
            "x-keywords": ["list", "workflow", "versions", "workflows"],
        },
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    workflow_id: Optional[str] = Field(
        None,
        title="workflowID",
        description="The IDs of the workflows to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    workflow_version_id: Optional[str] = Field(
        None,
        title="workflowVersionId",
        description="The IDs of the workflow versions to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderCreateWorkflowVersionConfig(RenderRequestBodyConfig):
    """Deploy a workflow version."""

    operation: Literal["create_workflow_version"] = Field(
        "create_workflow_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-display-name": "Deploy a workflow version",
            "x-keywords": ["create", "workflow", "version", "workflows"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: workflowId.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderGetWorkflowVersionConfig(BaseModel):
    """Retrieve workflow version."""

    operation: Literal["get_workflow_version"] = Field(
        "get_workflow_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-display-name": "Retrieve workflow version",
            "x-keywords": ["get", "workflow", "version", "workflows"],
        },
    )
    workflow_version_id: str = Field(
        ..., title="workflowVersionId", description="The ID of the workflow version"
    )


class RenderListTasksConfig(BaseModel):
    """List tasks."""

    operation: Literal["list_tasks"] = Field(
        "list_tasks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow Tasks",
            "x-display-name": "List tasks",
            "x-keywords": ["list", "tasks", "workflow"],
        },
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    task_slug: Optional[str] = Field(
        None,
        title="taskSlug",
        description="An array of task slugs in the format workflow-slug/task-name. An optional version can be appended (workflow-slug/task-name:version). If no version is provided, the latest version is used. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    workflow_version_id: Optional[str] = Field(
        None,
        title="workflowVersionId",
        description="An array of workflow version IDs Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    workflow_id: Optional[str] = Field(
        None,
        title="workflowId",
        description="An array of workflow IDs Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )


class RenderGetTaskConfig(BaseModel):
    """Retrieve task."""

    operation: Literal["get_task"] = Field(
        "get_task",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow Tasks",
            "x-display-name": "Retrieve task",
            "x-keywords": ["get", "task", "workflow", "tasks"],
        },
    )
    task_id: str = Field(..., title="taskId", description="The ID of the task")


class RenderListTaskRunsConfig(BaseModel):
    """List task runs."""

    operation: Literal["list_task_runs"] = Field(
        "list_task_runs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow Tasks",
            "x-display-name": "List task runs",
            "x-keywords": ["list", "task", "runs", "workflow", "tasks"],
        },
    )
    cursor: Optional[str] = Field(
        None,
        title="cursor",
        description="The position in the result list to start from when fetching paginated results. For details, see .",
    )
    limit: Optional[int] = Field(
        None,
        title="limit",
        description="The maximum number of items to return. For details, see .",
    )
    task_slug: Optional[str] = Field(
        None,
        title="taskSlug",
        description="An array of task slugs in the format workflow-slug/task-name. An optional version can be appended (workflow-slug/task-name:version). If no version is provided, the latest version is used. Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    root_task_run_id: Optional[str] = Field(
        None,
        title="rootTaskRunId",
        description="An array of root task run IDs to filter on Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    owner_id: Optional[str] = Field(
        None,
        title="ownerId",
        description="The ID of the workspaces to return resources for Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    workflow_version_id: Optional[str] = Field(
        None,
        title="workflowVersionId",
        description="An array of workflow version IDs Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )
    workflow_id: Optional[str] = Field(
        None,
        title="workflowId",
        description="An array of workflow IDs Enter a JSON array or comma-separated values.",
        json_schema_extra={"ui:rows": 2},
    )


class RenderCreateTaskConfig(RenderRequestBodyConfig):
    """Run task."""

    operation: Literal["create_task"] = Field(
        "create_task",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow Tasks",
            "x-display-name": "Run task",
            "x-keywords": ["create", "task", "workflow", "tasks"],
        },
    )
    body: str = Field(
        ...,
        title="Request Body",
        description="JSON request body. Required properties: task, input.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )


class RenderGetTaskRunConfig(BaseModel):
    """Retrieve task run."""

    operation: Literal["get_task_run"] = Field(
        "get_task_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow Tasks",
            "x-display-name": "Retrieve task run",
            "x-keywords": ["get", "task", "run", "workflow", "tasks"],
        },
    )
    task_run_id: str = Field(
        ..., title="taskRunId", description="The ID of the task run"
    )


class RenderCancelTaskRunConfig(BaseModel):
    """Cancel task run."""

    operation: Literal["cancel_task_run"] = Field(
        "cancel_task_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow Tasks",
            "x-display-name": "Cancel task run",
            "x-keywords": ["cancel", "task", "run", "workflow", "tasks"],
        },
    )
    task_run_id: str = Field(
        ..., title="taskRunId", description="The ID of the task run"
    )


RenderConfig = Annotated[
    Union[
        RenderListBlueprintsConfig,
        RenderUpdateWorkspaceMemberConfig,
        RenderRemoveWorkspaceMemberConfig,
        RenderRetrieveBlueprintConfig,
        RenderUpdateBlueprintConfig,
        RenderDisconnectBlueprintConfig,
        RenderListBlueprintSyncsConfig,
        RenderListDedicatedIpsConfig,
        RenderCreateDedicatedIpConfig,
        RenderRetrieveDedicatedIpConfig,
        RenderUpdateDedicatedIpConfig,
        RenderDeleteDedicatedIpConfig,
        RenderListDisksConfig,
        RenderAddDiskConfig,
        RenderRetrieveDiskConfig,
        RenderUpdateDiskConfig,
        RenderDeleteDiskConfig,
        RenderListSnapshotsConfig,
        RenderRestoreSnapshotConfig,
        RenderGetUserConfig,
        RenderListOwnersConfig,
        RenderRetrieveOwnerConfig,
        RenderRetrieveOwnerMembersConfig,
        RenderListOwnerAuditLogsConfig,
        RenderListOrganizationAuditLogsConfig,
        RenderRetrieveOwnerNotificationSettingsConfig,
        RenderPatchOwnerNotificationSettingsConfig,
        RenderListNotificationOverridesConfig,
        RenderRetrieveServiceNotificationOverridesConfig,
        RenderPatchServiceNotificationOverridesConfig,
        RenderListRegistryCredentialsConfig,
        RenderCreateRegistryCredentialConfig,
        RenderRetrieveRegistryCredentialConfig,
        RenderUpdateRegistryCredentialConfig,
        RenderDeleteRegistryCredentialConfig,
        RenderListServicesConfig,
        RenderCreateServiceConfig,
        RenderRetrieveServiceConfig,
        RenderUpdateServiceConfig,
        RenderDeleteServiceConfig,
        RenderPurgeCacheConfig,
        RenderListDeploysConfig,
        RenderCreateDeployConfig,
        RenderRetrieveDeployConfig,
        RenderCancelDeployConfig,
        RenderRollbackDeployConfig,
        RenderGetEnvVarsForServiceConfig,
        RenderUpdateEnvVarsForServiceConfig,
        RenderRetrieveEnvVarConfig,
        RenderUpdateEnvVarConfig,
        RenderDeleteEnvVarConfig,
        RenderListSecretFilesForServiceConfig,
        RenderUpdateSecretFilesForServiceConfig,
        RenderRetrieveSecretFileConfig,
        RenderAddOrUpdateSecretFileConfig,
        RenderDeleteSecretFileConfig,
        RenderListEventsConfig,
        RenderListHeadersConfig,
        RenderAddHeadersConfig,
        RenderUpdateHeadersConfig,
        RenderDeleteHeaderConfig,
        RenderListRoutesConfig,
        RenderAddRouteConfig,
        RenderPutRoutesConfig,
        RenderPatchRouteConfig,
        RenderDeleteRouteConfig,
        RenderListCustomDomainsConfig,
        RenderCreateCustomDomainConfig,
        RenderRetrieveCustomDomainConfig,
        RenderDeleteCustomDomainConfig,
        RenderRefreshCustomDomainConfig,
        RenderSuspendServiceConfig,
        RenderResumeServiceConfig,
        RenderRestartServiceConfig,
        RenderScaleServiceConfig,
        RenderAutoscaleServiceConfig,
        RenderDeleteAutoscalingConfigConfig,
        RenderPreviewServiceConfig,
        RenderListJobConfig,
        RenderPostJobConfig,
        RenderRetrieveJobConfig,
        RenderCancelJobConfig,
        RenderListInstancesConfig,
        RenderRetrieveServiceOutboundIpsConfig,
        RenderRunCronJobConfig,
        RenderCancelCronJobRunConfig,
        RenderRetrieveEventConfig,
        RenderListLogsConfig,
        RenderListLogsValuesConfig,
        RenderGetOwnerLogStreamConfig,
        RenderUpdateOwnerLogStreamConfig,
        RenderDeleteOwnerLogStreamConfig,
        RenderListResourceLogStreamsConfig,
        RenderGetResourceLogStreamConfig,
        RenderUpdateResourceLogStreamConfig,
        RenderDeleteResourceLogStreamConfig,
        RenderGetOwnerMetricsStreamConfig,
        RenderUpsertOwnerMetricsStreamConfig,
        RenderDeleteOwnerMetricsStreamConfig,
        RenderGetCpuConfig,
        RenderGetCpuLimitConfig,
        RenderGetCpuTargetConfig,
        RenderGetMemoryConfig,
        RenderGetMemoryLimitConfig,
        RenderGetMemoryTargetConfig,
        RenderGetHttpRequestsConfig,
        RenderGetHttpLatencyConfig,
        RenderGetBandwidthConfig,
        RenderGetBandwidthSourcesConfig,
        RenderGetDiskUsageConfig,
        RenderGetDiskCapacityConfig,
        RenderGetInstanceCountConfig,
        RenderGetActiveConnectionsConfig,
        RenderGetReplicationLagConfig,
        RenderListApplicationFilterValuesConfig,
        RenderListHttpFilterValuesConfig,
        RenderListPathFilterValuesConfig,
        RenderGetTaskRunsQueuedConfig,
        RenderGetTaskRunsCompletedConfig,
        RenderListKeyValueConfig,
        RenderCreateKeyValueConfig,
        RenderRetrieveKeyValueConfig,
        RenderUpdateKeyValueConfig,
        RenderDeleteKeyValueConfig,
        RenderRetrieveKeyValueConnectionInfoConfig,
        RenderSuspendKeyValueConfig,
        RenderResumeKeyValueConfig,
        RenderListPostgresConfig,
        RenderCreatePostgresConfig,
        RenderRetrievePostgresConfig,
        RenderUpdatePostgresConfig,
        RenderDeletePostgresConfig,
        RenderRetrievePostgresConnectionInfoConfig,
        RenderRetrievePostgresRecoveryInfoConfig,
        RenderRecoverPostgresConfig,
        RenderSuspendPostgresConfig,
        RenderResumePostgresConfig,
        RenderRestartPostgresConfig,
        RenderFailoverPostgresConfig,
        RenderListPostgresExportConfig,
        RenderCreatePostgresExportConfig,
        RenderListPostgresUsersConfig,
        RenderCreatePostgresUserConfig,
        RenderDeletePostgresUserConfig,
        RenderListPostgresProcessesConfig,
        RenderListPostgresTopQueriesConfig,
        RenderListPostgresSizesConfig,
        RenderListPostgresTableScansConfig,
        RenderListProjectsConfig,
        RenderCreateProjectConfig,
        RenderRetrieveProjectConfig,
        RenderUpdateProjectConfig,
        RenderDeleteProjectConfig,
        RenderCreateEnvironmentConfig,
        RenderListEnvironmentsConfig,
        RenderRetrieveEnvironmentConfig,
        RenderUpdateEnvironmentConfig,
        RenderDeleteEnvironmentConfig,
        RenderAddResourcesToEnvironmentConfig,
        RenderRemoveResourcesFromEnvironmentConfig,
        RenderListEnvGroupsConfig,
        RenderCreateEnvGroupConfig,
        RenderRetrieveEnvGroupConfig,
        RenderUpdateEnvGroupConfig,
        RenderDeleteEnvGroupConfig,
        RenderLinkServiceToEnvGroupConfig,
        RenderUnlinkServiceFromEnvGroupConfig,
        RenderRetrieveEnvGroupEnvVarConfig,
        RenderUpdateEnvGroupEnvVarConfig,
        RenderDeleteEnvGroupEnvVarConfig,
        RenderRetrieveEnvGroupSecretFileConfig,
        RenderUpdateEnvGroupSecretFileConfig,
        RenderDeleteEnvGroupSecretFileConfig,
        RenderListMaintenanceConfig,
        RenderRetrieveMaintenanceConfig,
        RenderUpdateMaintenanceConfig,
        RenderTriggerMaintenanceConfig,
        RenderCreateBuildSourceConfig,
        RenderListBuildSourcesConfig,
        RenderGetBuildSourceConfig,
        RenderUpdateBuildSourceConfig,
        RenderDeleteBuildSourceConfig,
        RenderListBuildsInBuildSourceConfig,
        RenderTriggerBuildSourceBuildConfig,
        RenderGetEnvVarsForBuildSourceConfig,
        RenderUpdateEnvVarsForBuildSourceConfig,
        RenderRetrieveBuildSourceEnvVarConfig,
        RenderUpdateBuildSourceEnvVarConfig,
        RenderDeleteBuildSourceEnvVarConfig,
        RenderListSecretFilesForBuildSourceConfig,
        RenderUpdateSecretFilesForBuildSourceConfig,
        RenderRetrieveBuildSourceSecretFileConfig,
        RenderAddOrUpdateBuildSourceSecretFileConfig,
        RenderDeleteBuildSourceSecretFileConfig,
        RenderLinkEnvGroupToBuildSourceConfig,
        RenderUnlinkEnvGroupFromBuildSourceConfig,
        RenderCreateWebhookConfig,
        RenderListWebhooksConfig,
        RenderRetrieveWebhookConfig,
        RenderUpdateWebhookConfig,
        RenderDeleteWebhookConfig,
        RenderListWebhookEventsConfig,
        RenderListWorkflowsConfig,
        RenderCreateWorkflowConfig,
        RenderGetWorkflowConfig,
        RenderUpdateWorkflowConfig,
        RenderDeleteWorkflowConfig,
        RenderListWorkflowVersionsConfig,
        RenderCreateWorkflowVersionConfig,
        RenderGetWorkflowVersionConfig,
        RenderListTasksConfig,
        RenderGetTaskConfig,
        RenderListTaskRunsConfig,
        RenderCreateTaskConfig,
        RenderGetTaskRunConfig,
        RenderCancelTaskRunConfig,
    ],
    Discriminator("operation"),
]


class RenderNodeConfig(NodeConfig[RenderConfig, RenderAPIKeyCredential]):
    pass


RENDER_OPERATIONS = {
    "list_blueprints": [
        "GET",
        "/blueprints",
        [
            ("owner_id", "ownerId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "update_workspace_member": [
        "PATCH",
        "/owners/{ownerId}/members/{userId}",
        [
            ("owner_id", "ownerId", "path", "string"),
            ("user_id", "userId", "path", "string"),
        ],
        True,
    ],
    "remove_workspace_member": [
        "DELETE",
        "/owners/{ownerId}/members/{userId}",
        [
            ("owner_id", "ownerId", "path", "string"),
            ("user_id", "userId", "path", "string"),
        ],
        False,
    ],
    "retrieve_blueprint": [
        "GET",
        "/blueprints/{blueprintId}",
        [("blueprint_id", "blueprintId", "path", "string")],
        False,
    ],
    "update_blueprint": [
        "PATCH",
        "/blueprints/{blueprintId}",
        [("blueprint_id", "blueprintId", "path", "string")],
        True,
    ],
    "disconnect_blueprint": [
        "DELETE",
        "/blueprints/{blueprintId}",
        [("blueprint_id", "blueprintId", "path", "string")],
        False,
    ],
    "list_blueprint_syncs": [
        "GET",
        "/blueprints/{blueprintId}/syncs",
        [
            ("blueprint_id", "blueprintId", "path", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "list_dedicated_ips": [
        "GET",
        "/dedicated-ips",
        [
            ("owner_id", "ownerId", "query", "string"),
            ("environment_id", "environmentId", "query", "string"),
        ],
        False,
    ],
    "create_dedicated_ip": ["POST", "/dedicated-ips", [], True],
    "retrieve_dedicated_ip": [
        "GET",
        "/dedicated-ips/{dedicatedIpId}",
        [("dedicated_ip_id", "dedicatedIpId", "path", "string")],
        False,
    ],
    "update_dedicated_ip": [
        "PATCH",
        "/dedicated-ips/{dedicatedIpId}",
        [("dedicated_ip_id", "dedicatedIpId", "path", "string")],
        True,
    ],
    "delete_dedicated_ip": [
        "DELETE",
        "/dedicated-ips/{dedicatedIpId}",
        [("dedicated_ip_id", "dedicatedIpId", "path", "string")],
        False,
    ],
    "list_disks": [
        "GET",
        "/disks",
        [
            ("owner_id", "ownerId", "query", "array"),
            ("disk_id", "diskId", "query", "array"),
            ("name", "name", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("service_id", "serviceId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "add_disk": ["POST", "/disks", [], True],
    "retrieve_disk": [
        "GET",
        "/disks/{diskId}",
        [("disk_id", "diskId", "path", "string")],
        False,
    ],
    "update_disk": [
        "PATCH",
        "/disks/{diskId}",
        [("disk_id", "diskId", "path", "string")],
        True,
    ],
    "delete_disk": [
        "DELETE",
        "/disks/{diskId}",
        [("disk_id", "diskId", "path", "string")],
        False,
    ],
    "list_snapshots": [
        "GET",
        "/disks/{diskId}/snapshots",
        [("disk_id", "diskId", "path", "string")],
        False,
    ],
    "restore_snapshot": [
        "POST",
        "/disks/{diskId}/snapshots/restore",
        [("disk_id", "diskId", "path", "string")],
        True,
    ],
    "get_user": ["GET", "/users", [], False],
    "list_owners": [
        "GET",
        "/owners",
        [
            ("name", "name", "query", "array"),
            ("email", "email", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "retrieve_owner": [
        "GET",
        "/owners/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        False,
    ],
    "retrieve_owner_members": [
        "GET",
        "/owners/{ownerId}/members",
        [("owner_id", "ownerId", "path", "string")],
        False,
    ],
    "list_owner_audit_logs": [
        "GET",
        "/owners/{ownerId}/audit-logs",
        [
            ("owner_id", "ownerId", "path", "string"),
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("direction", "direction", "query", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "list_organization_audit_logs": [
        "GET",
        "/organizations/{orgId}/audit-logs",
        [
            ("org_id", "orgId", "path", "string"),
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("direction", "direction", "query", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "retrieve_owner_notification_settings": [
        "GET",
        "/notification-settings/owners/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        False,
    ],
    "patch_owner_notification_settings": [
        "PATCH",
        "/notification-settings/owners/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        True,
    ],
    "list_notification_overrides": [
        "GET",
        "/notification-settings/overrides",
        [
            ("owner_id", "ownerId", "query", "array"),
            ("service_id", "serviceId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "retrieve_service_notification_overrides": [
        "GET",
        "/notification-settings/overrides/services/{serviceId}",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "patch_service_notification_overrides": [
        "PATCH",
        "/notification-settings/overrides/services/{serviceId}",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "list_registry_credentials": [
        "GET",
        "/registrycredentials",
        [
            ("name", "name", "query", "array"),
            ("username", "username", "query", "array"),
            ("type", "type", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("owner_id", "ownerId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_registry_credential": ["POST", "/registrycredentials", [], True],
    "retrieve_registry_credential": [
        "GET",
        "/registrycredentials/{registryCredentialId}",
        [("registry_credential_id", "registryCredentialId", "path", "string")],
        False,
    ],
    "update_registry_credential": [
        "PATCH",
        "/registrycredentials/{registryCredentialId}",
        [("registry_credential_id", "registryCredentialId", "path", "string")],
        True,
    ],
    "delete_registry_credential": [
        "DELETE",
        "/registrycredentials/{registryCredentialId}",
        [("registry_credential_id", "registryCredentialId", "path", "string")],
        False,
    ],
    "list_services": [
        "GET",
        "/services",
        [
            ("name", "name", "query", "array"),
            ("type", "type", "query", "array"),
            ("environment_id", "environmentId", "query", "array"),
            ("env", "env", "query", "array"),
            ("region", "region", "query", "array"),
            ("suspended", "suspended", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("owner_id", "ownerId", "query", "array"),
            ("include_previews", "includePreviews", "query", "boolean"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_service": ["POST", "/services", [], True],
    "retrieve_service": [
        "GET",
        "/services/{serviceId}",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "update_service": [
        "PATCH",
        "/services/{serviceId}",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "delete_service": [
        "DELETE",
        "/services/{serviceId}",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "purge_cache": [
        "POST",
        "/services/{serviceId}/cache/purge",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "list_deploys": [
        "GET",
        "/services/{serviceId}/deploys",
        [
            ("service_id", "serviceId", "path", "string"),
            ("status", "status", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("finished_before", "finishedBefore", "query", "string"),
            ("finished_after", "finishedAfter", "query", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_deploy": [
        "POST",
        "/services/{serviceId}/deploys",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "retrieve_deploy": [
        "GET",
        "/services/{serviceId}/deploys/{deployId}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("deploy_id", "deployId", "path", "string"),
        ],
        False,
    ],
    "cancel_deploy": [
        "POST",
        "/services/{serviceId}/deploys/{deployId}/cancel",
        [
            ("service_id", "serviceId", "path", "string"),
            ("deploy_id", "deployId", "path", "string"),
        ],
        False,
    ],
    "rollback_deploy": [
        "POST",
        "/services/{serviceId}/rollback",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "get_env_vars_for_service": [
        "GET",
        "/services/{serviceId}/env-vars",
        [
            ("service_id", "serviceId", "path", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "update_env_vars_for_service": [
        "PUT",
        "/services/{serviceId}/env-vars",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "retrieve_env_var": [
        "GET",
        "/services/{serviceId}/env-vars/{envVarKey}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "update_env_var": [
        "PUT",
        "/services/{serviceId}/env-vars/{envVarKey}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        True,
    ],
    "delete_env_var": [
        "DELETE",
        "/services/{serviceId}/env-vars/{envVarKey}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "list_secret_files_for_service": [
        "GET",
        "/services/{serviceId}/secret-files",
        [
            ("service_id", "serviceId", "path", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "update_secret_files_for_service": [
        "PUT",
        "/services/{serviceId}/secret-files",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "retrieve_secret_file": [
        "GET",
        "/services/{serviceId}/secret-files/{envVarKey}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "add_or_update_secret_file": [
        "PUT",
        "/services/{serviceId}/secret-files/{envVarKey}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        True,
    ],
    "delete_secret_file": [
        "DELETE",
        "/services/{serviceId}/secret-files/{envVarKey}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "list_events": [
        "GET",
        "/services/{serviceId}/events",
        [
            ("service_id", "serviceId", "path", "string"),
            ("type", "type", "query", "string"),
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "list_headers": [
        "GET",
        "/services/{serviceId}/headers",
        [
            ("service_id", "serviceId", "path", "string"),
            ("path", "path", "query", "array"),
            ("name", "name", "query", "array"),
            ("value", "value", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "add_headers": [
        "POST",
        "/services/{serviceId}/headers",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "update_headers": [
        "PUT",
        "/services/{serviceId}/headers",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "delete_header": [
        "DELETE",
        "/services/{serviceId}/headers/{headerId}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("header_id", "headerId", "path", "string"),
        ],
        False,
    ],
    "list_routes": [
        "GET",
        "/services/{serviceId}/routes",
        [
            ("service_id", "serviceId", "path", "string"),
            ("type", "type", "query", "array"),
            ("source", "source", "query", "array"),
            ("destination", "destination", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "add_route": [
        "POST",
        "/services/{serviceId}/routes",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "put_routes": [
        "PUT",
        "/services/{serviceId}/routes",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "patch_route": [
        "PATCH",
        "/services/{serviceId}/routes/{routeId}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("route_id", "routeId", "path", "string"),
        ],
        True,
    ],
    "delete_route": [
        "DELETE",
        "/services/{serviceId}/routes/{routeId}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("route_id", "routeId", "path", "string"),
        ],
        False,
    ],
    "list_custom_domains": [
        "GET",
        "/services/{serviceId}/custom-domains",
        [
            ("service_id", "serviceId", "path", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
            ("name", "name", "query", "array"),
            ("domain_type", "domainType", "query", "string"),
            ("verification_status", "verificationStatus", "query", "string"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
        ],
        False,
    ],
    "create_custom_domain": [
        "POST",
        "/services/{serviceId}/custom-domains",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "retrieve_custom_domain": [
        "GET",
        "/services/{serviceId}/custom-domains/{customDomainNameOrID}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("custom_domain_name_or_id", "customDomainNameOrID", "path", "string"),
        ],
        False,
    ],
    "delete_custom_domain": [
        "DELETE",
        "/services/{serviceId}/custom-domains/{customDomainNameOrID}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("custom_domain_name_or_id", "customDomainNameOrID", "path", "string"),
        ],
        False,
    ],
    "refresh_custom_domain": [
        "POST",
        "/services/{serviceId}/custom-domains/{customDomainNameOrID}/verify",
        [
            ("service_id", "serviceId", "path", "string"),
            ("custom_domain_name_or_id", "customDomainNameOrID", "path", "string"),
        ],
        False,
    ],
    "suspend_service": [
        "POST",
        "/services/{serviceId}/suspend",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "resume_service": [
        "POST",
        "/services/{serviceId}/resume",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "restart_service": [
        "POST",
        "/services/{serviceId}/restart",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "scale_service": [
        "POST",
        "/services/{serviceId}/scale",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "autoscale_service": [
        "PUT",
        "/services/{serviceId}/autoscaling",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "delete_autoscaling_config": [
        "DELETE",
        "/services/{serviceId}/autoscaling",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "preview_service": [
        "POST",
        "/services/{serviceId}/preview",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "list_job": [
        "GET",
        "/services/{serviceId}/jobs",
        [
            ("service_id", "serviceId", "path", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
            ("status", "status", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("started_before", "startedBefore", "query", "string"),
            ("started_after", "startedAfter", "query", "string"),
            ("finished_before", "finishedBefore", "query", "string"),
            ("finished_after", "finishedAfter", "query", "string"),
        ],
        False,
    ],
    "post_job": [
        "POST",
        "/services/{serviceId}/jobs",
        [("service_id", "serviceId", "path", "string")],
        True,
    ],
    "retrieve_job": [
        "GET",
        "/services/{serviceId}/jobs/{jobId}",
        [
            ("service_id", "serviceId", "path", "string"),
            ("job_id", "jobId", "path", "string"),
        ],
        False,
    ],
    "cancel_job": [
        "POST",
        "/services/{serviceId}/jobs/{jobId}/cancel",
        [
            ("service_id", "serviceId", "path", "string"),
            ("job_id", "jobId", "path", "string"),
        ],
        False,
    ],
    "list_instances": [
        "GET",
        "/services/{serviceId}/instances",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "retrieve_service_outbound_ips": [
        "GET",
        "/services/{serviceId}/outbound-ips",
        [("service_id", "serviceId", "path", "string")],
        False,
    ],
    "run_cron_job": [
        "POST",
        "/cron-jobs/{cronJobId}/runs",
        [("cron_job_id", "cronJobId", "path", "string")],
        False,
    ],
    "cancel_cron_job_run": [
        "DELETE",
        "/cron-jobs/{cronJobId}/runs",
        [("cron_job_id", "cronJobId", "path", "string")],
        False,
    ],
    "retrieve_event": [
        "GET",
        "/events/{eventId}",
        [("event_id", "eventId", "path", "string")],
        False,
    ],
    "list_logs": [
        "GET",
        "/logs",
        [
            ("owner_id", "ownerId", "query", "string"),
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("direction", "direction", "query", "string"),
            ("resource", "resource", "query", "array"),
            ("instance", "instance", "query", "array"),
            ("host", "host", "query", "array"),
            ("status_code", "statusCode", "query", "array"),
            ("method", "method", "query", "array"),
            ("task", "task", "query", "array"),
            ("task_run", "taskRun", "query", "array"),
            ("sandbox", "sandbox", "query", "array"),
            ("level", "level", "query", "array"),
            ("type", "type", "query", "array"),
            ("text", "text", "query", "array"),
            ("path", "path", "query", "array"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "list_logs_values": [
        "GET",
        "/logs/values",
        [
            ("owner_id", "ownerId", "query", "string"),
            ("label", "label", "query", "string"),
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("direction", "direction", "query", "string"),
            ("resource", "resource", "query", "array"),
            ("instance", "instance", "query", "array"),
            ("host", "host", "query", "array"),
            ("status_code", "statusCode", "query", "array"),
            ("method", "method", "query", "array"),
            ("task", "task", "query", "array"),
            ("task_run", "taskRun", "query", "array"),
            ("sandbox", "sandbox", "query", "array"),
            ("level", "level", "query", "array"),
            ("type", "type", "query", "array"),
            ("text", "text", "query", "array"),
            ("path", "path", "query", "array"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "get_owner_log_stream": [
        "GET",
        "/logs/streams/owner/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        False,
    ],
    "update_owner_log_stream": [
        "PUT",
        "/logs/streams/owner/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        True,
    ],
    "delete_owner_log_stream": [
        "DELETE",
        "/logs/streams/owner/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        False,
    ],
    "list_resource_log_streams": [
        "GET",
        "/logs/streams/resource",
        [
            ("owner_id", "ownerId", "query", "array"),
            ("log_stream_id", "logStreamId", "query", "array"),
            ("resource_id", "resourceId", "query", "array"),
            ("setting", "setting", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "get_resource_log_stream": [
        "GET",
        "/logs/streams/resource/{resourceId}",
        [("resource_id", "resourceId", "path", "string")],
        False,
    ],
    "update_resource_log_stream": [
        "PUT",
        "/logs/streams/resource/{resourceId}",
        [("resource_id", "resourceId", "path", "string")],
        True,
    ],
    "delete_resource_log_stream": [
        "DELETE",
        "/logs/streams/resource/{resourceId}",
        [("resource_id", "resourceId", "path", "string")],
        False,
    ],
    "get_owner_metrics_stream": [
        "GET",
        "/metrics-stream/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        False,
    ],
    "upsert_owner_metrics_stream": [
        "PUT",
        "/metrics-stream/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        True,
    ],
    "delete_owner_metrics_stream": [
        "DELETE",
        "/metrics-stream/{ownerId}",
        [("owner_id", "ownerId", "path", "string")],
        False,
    ],
    "get_cpu": [
        "GET",
        "/metrics/cpu",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("instance", "instance", "query", "string"),
            ("aggregation_method", "aggregationMethod", "query", "string"),
        ],
        False,
    ],
    "get_cpu_limit": [
        "GET",
        "/metrics/cpu-limit",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("instance", "instance", "query", "string"),
        ],
        False,
    ],
    "get_cpu_target": [
        "GET",
        "/metrics/cpu-target",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("instance", "instance", "query", "string"),
        ],
        False,
    ],
    "get_memory": [
        "GET",
        "/metrics/memory",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("instance", "instance", "query", "string"),
        ],
        False,
    ],
    "get_memory_limit": [
        "GET",
        "/metrics/memory-limit",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("instance", "instance", "query", "string"),
        ],
        False,
    ],
    "get_memory_target": [
        "GET",
        "/metrics/memory-target",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("instance", "instance", "query", "string"),
        ],
        False,
    ],
    "get_http_requests": [
        "GET",
        "/metrics/http-requests",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("host", "host", "query", "string"),
            ("path", "path", "query", "string"),
            ("aggregate_by", "aggregateBy", "query", "string"),
        ],
        False,
    ],
    "get_http_latency": [
        "GET",
        "/metrics/http-latency",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("host", "host", "query", "string"),
            ("path", "path", "query", "string"),
            ("quantile", "quantile", "query", "number"),
        ],
        False,
    ],
    "get_bandwidth": [
        "GET",
        "/metrics/bandwidth",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
        ],
        False,
    ],
    "get_bandwidth_sources": [
        "GET",
        "/metrics/bandwidth-sources",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
        ],
        False,
    ],
    "get_disk_usage": [
        "GET",
        "/metrics/disk-usage",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
        ],
        False,
    ],
    "get_disk_capacity": [
        "GET",
        "/metrics/disk-capacity",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
        ],
        False,
    ],
    "get_instance_count": [
        "GET",
        "/metrics/instance-count",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
        ],
        False,
    ],
    "get_active_connections": [
        "GET",
        "/metrics/active-connections",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
        ],
        False,
    ],
    "get_replication_lag": [
        "GET",
        "/metrics/replication-lag",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
        ],
        False,
    ],
    "list_application_filter_values": [
        "GET",
        "/metrics/filters/application",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
        ],
        False,
    ],
    "list_http_filter_values": [
        "GET",
        "/metrics/filters/http",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("host", "host", "query", "string"),
            ("status_code", "statusCode", "query", "string"),
        ],
        False,
    ],
    "list_path_filter_values": [
        "GET",
        "/metrics/filters/path",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("service", "service", "query", "string"),
            ("host", "host", "query", "string"),
            ("status_code", "statusCode", "query", "string"),
            ("path", "path", "query", "string"),
        ],
        False,
    ],
    "get_task_runs_queued": [
        "GET",
        "/metrics/task-runs-queued",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
        ],
        False,
    ],
    "get_task_runs_completed": [
        "GET",
        "/metrics/task-runs-completed",
        [
            ("start_time", "startTime", "query", "string"),
            ("end_time", "endTime", "query", "string"),
            ("resolution_seconds", "resolutionSeconds", "query", "number"),
            ("resource", "resource", "query", "string"),
            ("state", "state", "query", "string"),
            ("aggregate_by", "aggregateBy", "query", "string"),
        ],
        False,
    ],
    "list_key_value": [
        "GET",
        "/key-value",
        [
            ("name", "name", "query", "array"),
            ("region", "region", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("owner_id", "ownerId", "query", "array"),
            ("environment_id", "environmentId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_key_value": ["POST", "/key-value", [], True],
    "retrieve_key_value": [
        "GET",
        "/key-value/{redisId}",
        [("redis_id", "redisId", "path", "string")],
        False,
    ],
    "update_key_value": [
        "PATCH",
        "/key-value/{redisId}",
        [("redis_id", "redisId", "path", "string")],
        True,
    ],
    "delete_key_value": [
        "DELETE",
        "/key-value/{redisId}",
        [("redis_id", "redisId", "path", "string")],
        False,
    ],
    "retrieve_key_value_connection_info": [
        "GET",
        "/key-value/{redisId}/connection-info",
        [("redis_id", "redisId", "path", "string")],
        False,
    ],
    "suspend_key_value": [
        "POST",
        "/key-value/{redisId}/suspend",
        [("redis_id", "redisId", "path", "string")],
        False,
    ],
    "resume_key_value": [
        "POST",
        "/key-value/{redisId}/resume",
        [("redis_id", "redisId", "path", "string")],
        False,
    ],
    "list_postgres": [
        "GET",
        "/postgres",
        [
            ("name", "name", "query", "array"),
            ("region", "region", "query", "array"),
            ("suspended", "suspended", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("owner_id", "ownerId", "query", "array"),
            ("environment_id", "environmentId", "query", "array"),
            ("include_replicas", "includeReplicas", "query", "boolean"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_postgres": ["POST", "/postgres", [], True],
    "retrieve_postgres": [
        "GET",
        "/postgres/{postgresId}",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "update_postgres": [
        "PATCH",
        "/postgres/{postgresId}",
        [("postgres_id", "postgresId", "path", "string")],
        True,
    ],
    "delete_postgres": [
        "DELETE",
        "/postgres/{postgresId}",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "retrieve_postgres_connection_info": [
        "GET",
        "/postgres/{postgresId}/connection-info",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "retrieve_postgres_recovery_info": [
        "GET",
        "/postgres/{postgresId}/recovery",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "recover_postgres": [
        "POST",
        "/postgres/{postgresId}/recovery",
        [("postgres_id", "postgresId", "path", "string")],
        True,
    ],
    "suspend_postgres": [
        "POST",
        "/postgres/{postgresId}/suspend",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "resume_postgres": [
        "POST",
        "/postgres/{postgresId}/resume",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "restart_postgres": [
        "POST",
        "/postgres/{postgresId}/restart",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "failover_postgres": [
        "POST",
        "/postgres/{postgresId}/failover",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "list_postgres_export": [
        "GET",
        "/postgres/{postgresId}/export",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "create_postgres_export": [
        "POST",
        "/postgres/{postgresId}/export",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "list_postgres_users": [
        "GET",
        "/postgres/{postgresId}/credentials",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "create_postgres_user": [
        "POST",
        "/postgres/{postgresId}/credentials",
        [("postgres_id", "postgresId", "path", "string")],
        True,
    ],
    "delete_postgres_user": [
        "DELETE",
        "/postgres/{postgresId}/credentials/{username}",
        [
            ("postgres_id", "postgresId", "path", "string"),
            ("username", "username", "path", "string"),
        ],
        False,
    ],
    "list_postgres_processes": [
        "GET",
        "/postgres/{postgresId}/query/processes",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "list_postgres_top_queries": [
        "GET",
        "/postgres/{postgresId}/query/top-queries",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "list_postgres_sizes": [
        "GET",
        "/postgres/{postgresId}/query/sizes",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "list_postgres_table_scans": [
        "GET",
        "/postgres/{postgresId}/query/table-scans",
        [("postgres_id", "postgresId", "path", "string")],
        False,
    ],
    "list_projects": [
        "GET",
        "/projects",
        [
            ("name", "name", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("owner_id", "ownerId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_project": ["POST", "/projects", [], True],
    "retrieve_project": [
        "GET",
        "/projects/{projectId}",
        [("project_id", "projectId", "path", "string")],
        False,
    ],
    "update_project": [
        "PATCH",
        "/projects/{projectId}",
        [("project_id", "projectId", "path", "string")],
        True,
    ],
    "delete_project": [
        "DELETE",
        "/projects/{projectId}",
        [("project_id", "projectId", "path", "string")],
        False,
    ],
    "create_environment": ["POST", "/environments", [], True],
    "list_environments": [
        "GET",
        "/environments",
        [
            ("name", "name", "query", "array"),
            ("project_id", "projectId", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("owner_id", "ownerId", "query", "array"),
            ("environment_id", "environmentId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "retrieve_environment": [
        "GET",
        "/environments/{environmentId}",
        [("environment_id", "environmentId", "path", "string")],
        False,
    ],
    "update_environment": [
        "PATCH",
        "/environments/{environmentId}",
        [("environment_id", "environmentId", "path", "string")],
        True,
    ],
    "delete_environment": [
        "DELETE",
        "/environments/{environmentId}",
        [("environment_id", "environmentId", "path", "string")],
        False,
    ],
    "add_resources_to_environment": [
        "POST",
        "/environments/{environmentId}/resources",
        [("environment_id", "environmentId", "path", "string")],
        True,
    ],
    "remove_resources_from_environment": [
        "DELETE",
        "/environments/{environmentId}/resources",
        [
            ("environment_id", "environmentId", "path", "string"),
            ("resource_ids", "resourceIds", "query", "array"),
        ],
        False,
    ],
    "list_env_groups": [
        "GET",
        "/env-groups",
        [
            ("name", "name", "query", "array"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("owner_id", "ownerId", "query", "array"),
            ("environment_id", "environmentId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_env_group": ["POST", "/env-groups", [], True],
    "retrieve_env_group": [
        "GET",
        "/env-groups/{envGroupId}",
        [("env_group_id", "envGroupId", "path", "string")],
        False,
    ],
    "update_env_group": [
        "PATCH",
        "/env-groups/{envGroupId}",
        [("env_group_id", "envGroupId", "path", "string")],
        True,
    ],
    "delete_env_group": [
        "DELETE",
        "/env-groups/{envGroupId}",
        [("env_group_id", "envGroupId", "path", "string")],
        False,
    ],
    "link_service_to_env_group": [
        "POST",
        "/env-groups/{envGroupId}/services/{serviceId}",
        [
            ("env_group_id", "envGroupId", "path", "string"),
            ("service_id", "serviceId", "path", "string"),
        ],
        False,
    ],
    "unlink_service_from_env_group": [
        "DELETE",
        "/env-groups/{envGroupId}/services/{serviceId}",
        [
            ("env_group_id", "envGroupId", "path", "string"),
            ("service_id", "serviceId", "path", "string"),
        ],
        False,
    ],
    "retrieve_env_group_env_var": [
        "GET",
        "/env-groups/{envGroupId}/env-vars/{envVarKey}",
        [
            ("env_group_id", "envGroupId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "update_env_group_env_var": [
        "PUT",
        "/env-groups/{envGroupId}/env-vars/{envVarKey}",
        [
            ("env_group_id", "envGroupId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        True,
    ],
    "delete_env_group_env_var": [
        "DELETE",
        "/env-groups/{envGroupId}/env-vars/{envVarKey}",
        [
            ("env_group_id", "envGroupId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "retrieve_env_group_secret_file": [
        "GET",
        "/env-groups/{envGroupId}/secret-files/{envVarKey}",
        [
            ("env_group_id", "envGroupId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "update_env_group_secret_file": [
        "PUT",
        "/env-groups/{envGroupId}/secret-files/{envVarKey}",
        [
            ("env_group_id", "envGroupId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        True,
    ],
    "delete_env_group_secret_file": [
        "DELETE",
        "/env-groups/{envGroupId}/secret-files/{envVarKey}",
        [
            ("env_group_id", "envGroupId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "list_maintenance": [
        "GET",
        "/maintenance",
        [
            ("resource_id", "resourceId", "query", "array"),
            ("owner_id", "ownerId", "query", "array"),
            ("state", "state", "query", "array"),
        ],
        False,
    ],
    "retrieve_maintenance": [
        "GET",
        "/maintenance/{maintenanceRunID}",
        [("maintenance_run_id", "maintenanceRunID", "path", "string")],
        False,
    ],
    "update_maintenance": [
        "PATCH",
        "/maintenance/{maintenanceRunID}",
        [("maintenance_run_id", "maintenanceRunID", "path", "string")],
        True,
    ],
    "trigger_maintenance": [
        "POST",
        "/maintenance/{maintenanceRunID}/trigger",
        [("maintenance_run_id", "maintenanceRunID", "path", "string")],
        False,
    ],
    "create_build_source": ["POST", "/build-sources", [], True],
    "list_build_sources": [
        "GET",
        "/build-sources",
        [
            ("name", "name", "query", "array"),
            ("owner_id", "ownerId", "query", "array"),
            ("project_id", "projectId", "query", "string"),
            ("include_previews", "includePreviews", "query", "boolean"),
            ("created_before", "createdBefore", "query", "string"),
            ("created_after", "createdAfter", "query", "string"),
            ("updated_before", "updatedBefore", "query", "string"),
            ("updated_after", "updatedAfter", "query", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "get_build_source": [
        "GET",
        "/build-sources/{buildSourceId}",
        [("build_source_id", "buildSourceId", "path", "string")],
        False,
    ],
    "update_build_source": [
        "PATCH",
        "/build-sources/{buildSourceId}",
        [("build_source_id", "buildSourceId", "path", "string")],
        True,
    ],
    "delete_build_source": [
        "DELETE",
        "/build-sources/{buildSourceId}",
        [("build_source_id", "buildSourceId", "path", "string")],
        False,
    ],
    "list_builds_in_build_source": [
        "GET",
        "/build-sources/{buildSourceId}/builds",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "trigger_build_source_build": [
        "POST",
        "/build-sources/{buildSourceId}/builds",
        [("build_source_id", "buildSourceId", "path", "string")],
        False,
    ],
    "get_env_vars_for_build_source": [
        "GET",
        "/build-sources/{buildSourceId}/env-vars",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "update_env_vars_for_build_source": [
        "PUT",
        "/build-sources/{buildSourceId}/env-vars",
        [("build_source_id", "buildSourceId", "path", "string")],
        True,
    ],
    "retrieve_build_source_env_var": [
        "GET",
        "/build-sources/{buildSourceId}/env-vars/{envVarKey}",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "update_build_source_env_var": [
        "PUT",
        "/build-sources/{buildSourceId}/env-vars/{envVarKey}",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        True,
    ],
    "delete_build_source_env_var": [
        "DELETE",
        "/build-sources/{buildSourceId}/env-vars/{envVarKey}",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "list_secret_files_for_build_source": [
        "GET",
        "/build-sources/{buildSourceId}/secret-files",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "update_secret_files_for_build_source": [
        "PUT",
        "/build-sources/{buildSourceId}/secret-files",
        [("build_source_id", "buildSourceId", "path", "string")],
        True,
    ],
    "retrieve_build_source_secret_file": [
        "GET",
        "/build-sources/{buildSourceId}/secret-files/{envVarKey}",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "add_or_update_build_source_secret_file": [
        "PUT",
        "/build-sources/{buildSourceId}/secret-files/{envVarKey}",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        True,
    ],
    "delete_build_source_secret_file": [
        "DELETE",
        "/build-sources/{buildSourceId}/secret-files/{envVarKey}",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("env_var_key", "envVarKey", "path", "string"),
        ],
        False,
    ],
    "link_env_group_to_build_source": [
        "POST",
        "/build-sources/{buildSourceId}/env-groups/{envGroupId}",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("env_group_id", "envGroupId", "path", "string"),
        ],
        False,
    ],
    "unlink_env_group_from_build_source": [
        "DELETE",
        "/build-sources/{buildSourceId}/env-groups/{envGroupId}",
        [
            ("build_source_id", "buildSourceId", "path", "string"),
            ("env_group_id", "envGroupId", "path", "string"),
        ],
        False,
    ],
    "create_webhook": ["POST", "/webhooks", [], True],
    "list_webhooks": [
        "GET",
        "/webhooks",
        [
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
            ("owner_id", "ownerId", "query", "array"),
        ],
        False,
    ],
    "retrieve_webhook": [
        "GET",
        "/webhooks/{webhookId}",
        [("webhook_id", "webhookId", "path", "string")],
        False,
    ],
    "update_webhook": [
        "PATCH",
        "/webhooks/{webhookId}",
        [("webhook_id", "webhookId", "path", "string")],
        True,
    ],
    "delete_webhook": [
        "DELETE",
        "/webhooks/{webhookId}",
        [("webhook_id", "webhookId", "path", "string")],
        False,
    ],
    "list_webhook_events": [
        "GET",
        "/webhooks/{webhookId}/events",
        [
            ("webhook_id", "webhookId", "path", "string"),
            ("sent_before", "sentBefore", "query", "string"),
            ("sent_after", "sentAfter", "query", "string"),
            ("limit", "limit", "query", "integer"),
            ("cursor", "cursor", "query", "string"),
        ],
        False,
    ],
    "list_workflows": [
        "GET",
        "/workflows",
        [
            ("name", "name", "query", "array"),
            ("owner_id", "ownerId", "query", "array"),
            ("workflow_id", "workflowID", "query", "array"),
            ("environment_id", "environmentId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_workflow": ["POST", "/workflows", [], True],
    "get_workflow": [
        "GET",
        "/workflows/{workflowId}",
        [("workflow_id", "workflowId", "path", "string")],
        False,
    ],
    "update_workflow": [
        "PATCH",
        "/workflows/{workflowId}",
        [("workflow_id", "workflowId", "path", "string")],
        True,
    ],
    "delete_workflow": [
        "DELETE",
        "/workflows/{workflowId}",
        [("workflow_id", "workflowId", "path", "string")],
        False,
    ],
    "list_workflow_versions": [
        "GET",
        "/workflowversions",
        [
            ("owner_id", "ownerId", "query", "array"),
            ("workflow_id", "workflowID", "query", "array"),
            ("workflow_version_id", "workflowVersionId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "create_workflow_version": ["POST", "/workflowversions", [], True],
    "get_workflow_version": [
        "GET",
        "/workflowversions/{workflowVersionId}",
        [("workflow_version_id", "workflowVersionId", "path", "string")],
        False,
    ],
    "list_tasks": [
        "GET",
        "/tasks",
        [
            ("owner_id", "ownerId", "query", "array"),
            ("task_slug", "taskSlug", "query", "array"),
            ("workflow_version_id", "workflowVersionId", "query", "array"),
            ("workflow_id", "workflowId", "query", "array"),
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
        ],
        False,
    ],
    "get_task": [
        "GET",
        "/tasks/{taskId}",
        [("task_id", "taskId", "path", "string")],
        False,
    ],
    "list_task_runs": [
        "GET",
        "/task-runs",
        [
            ("cursor", "cursor", "query", "string"),
            ("limit", "limit", "query", "integer"),
            ("task_slug", "taskSlug", "query", "array"),
            ("root_task_run_id", "rootTaskRunId", "query", "array"),
            ("owner_id", "ownerId", "query", "array"),
            ("workflow_version_id", "workflowVersionId", "query", "array"),
            ("workflow_id", "workflowId", "query", "array"),
        ],
        False,
    ],
    "create_task": ["POST", "/task-runs", [], True],
    "get_task_run": [
        "GET",
        "/task-runs/{taskRunId}",
        [("task_run_id", "taskRunId", "path", "string")],
        False,
    ],
    "cancel_task_run": [
        "DELETE",
        "/task-runs/{taskRunId}",
        [("task_run_id", "taskRunId", "path", "string")],
        False,
    ],
}


def _decode_parameter(value: Any, data_type: str) -> Any:
    if data_type == "array":
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                value = json.loads(value)
            else:
                value = [part.strip() for part in value.split(",") if part.strip()]
        if not isinstance(value, list):
            raise ValueError(
                "Array parameter must be a JSON array or comma-separated list"
            )
        return value
    if data_type == "object":
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("Object parameter must be a JSON object")
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


async def _render_request(
    api_key: str,
    method: str,
    path: str,
    *,
    params: list[tuple[str, Any]],
    body: Any,
    operation: str,
) -> Dict[str, Any]:
    started = time.monotonic()
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as session:
            response = await session.request(
                method,
                f"{RENDER_API_BASE}{path}",
                headers=headers,
                params=params,
                json=body,
            )
            raw = response.text
            try:
                data = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                data = {"raw": raw}
            timing = {"api": round((time.monotonic() - started) * 1000, 2)}
            if response.status_code >= 400:
                message = (
                    data.get("message") or data.get("error") or str(data)
                    if isinstance(data, dict)
                    else str(data)
                )
                return {
                    "status": "error",
                    "action": operation,
                    "status_code": response.status_code,
                    "error": str(message).replace(api_key, "[redacted]"),
                    "timing_ms": timing,
                }
            result = (
                {"items": data, "count": len(data)}
                if isinstance(data, list)
                else data
            )
            return {
                "status": "success",
                "action": operation,
                "status_code": response.status_code,
                "data": result,
                "timing_ms": timing,
            }
    except (httpx.RequestError, TimeoutError) as exc:
        return {
            "status": "error",
            "action": operation,
            "status_code": 0,
            "error": str(exc).replace(api_key, "[redacted]"),
            "timing_ms": {"api": round((time.monotonic() - started) * 1000, 2)},
        }


class RenderNode(WorkflowNode):
    """Execute Render's JSON REST operations with an account API key."""

    integration_type = "automation-render"

    connection_evidence = ConnectionEvidence(
        field="service_id",
        noun="services",
        identity_operation="get_user",
    )

    @classmethod
    def get_config_model(cls):
        return RenderNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> list[Dict[str, Any]]:
        if field_name != "service_id":
            return []
        api_key = credential_data.get("api_key")
        if not api_key:
            raise ValueError("Render API key is required")
        result = await _render_request(
            api_key,
            "GET",
            "/services",
            params=[("limit", 100)],
            body=None,
            operation="list_services",
        )
        if result["status"] != "success":
            raise ValueError(f"Render refused the API key: {result['error']}")
        items = result.get("data", {}).get("items", [])
        options = []
        for item in items:
            service = item.get("service", item)
            if isinstance(service, dict) and service.get("id"):
                options.append(
                    {
                        "value": service["id"],
                        "label": service.get("name") or service["id"],
                    }
                )
        return options

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self.config or not self.config.credentials:
            raise ValueError("Render API key is required")
        config = self.config.config
        method, path, parameters, has_body = RENDER_OPERATIONS[config.operation]
        query: list[tuple[str, Any]] = []
        for attr, api_name, location, data_type in parameters:
            value = getattr(config, attr)
            if value is None:
                continue
            value = _decode_parameter(value, data_type)
            if location == "path":
                path = path.replace("{" + api_name + "}", quote(str(value), safe=""))
            elif isinstance(value, list):
                query.extend((api_name, item) for item in value)
            else:
                query.append(
                    (api_name, json.dumps(value) if isinstance(value, dict) else value)
                )
        body = None
        if has_body and config.body is not None:
            try:
                body = json.loads(config.body)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Request body must be valid JSON: {exc.msg}") from exc
        return await _render_request(
            self.config.credentials.api_key,
            method,
            path,
            params=query,
            body=body,
            operation=config.operation,
        )
