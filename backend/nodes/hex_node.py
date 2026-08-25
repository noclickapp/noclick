"""
Hex data/BI automation node.

Provides workflow integration with the Hex REST API for operations including:
- Project runs: run, get status, list runs, cancel, get cell image
- Projects: list, get, update, sharing (collections, workspace/public, groups, users)
- Embedding: create presigned embed URL
- Admin (Team/Enterprise): users, groups, collections, data connections
- Semantic models: ingest

Authentication: Static API token (Bearer). Hex documents these as
"OAuth 2.0 Bearer Tokens" but there is NO OAuth flow — you generate a
Personal Access Token (hxtp_) or Workspace Token (hxtw_) in the Hex UI and
send it as `Authorization: Bearer {TOKEN}`.

API Base URL: https://app.hex.tech/api/v1 (single-tenant / EU / HIPAA
customers replace `app.hex.tech` with their workspace host, e.g. eu.hex.tech —
configurable via the credential's Workspace Host field).
Documentation: https://learn.hex.tech/docs/api/api-reference
"""

import logging
import time
import uuid as uuid_module
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)
from utils.ssrf import SSRFError, guarded_async_client, normalize_provider_subdomain

logger = logging.getLogger(__name__)

DEFAULT_HEX_HOST = "app.hex.tech"


# ============================================================================
# Credential Schema
# ============================================================================


class HexApiTokenCredential(BaseModel):
    """API token credential for Hex (Personal Access Token or Workspace Token)."""

    credential_type: Literal["hex_api_token"] = Field(
        "hex_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="Your Hex token (Personal hxtp_ or Workspace hxtw_) from Settings -> API keys",
        json_schema_extra={"ui:widget": "password"},
    )
    workspace_host: str = Field(
        DEFAULT_HEX_HOST,
        title="Workspace Host",
        description="Host for your Hex workspace. Use app.hex.tech for multi-tenant, or your single-tenant/EU/HIPAA host (e.g. eu.hex.tech)",
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.hex.tech/settings/api-keys"}
    )


HexCredential = HexApiTokenCredential


# ============================================================================
# Operation Configs
# ============================================================================


class HexRunProjectConfig(BaseModel):
    """Trigger a run of a project's latest published version."""

    operation: Literal["run_project"] = Field(
        "run_project",
        json_schema_extra={
            "const": "run_project",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "Run Project",
        },
        title="Run Project",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project to run",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )
    input_params: Optional[str] = Field(
        None,
        title="Input Parameters",
        description='JSON object of published app parameters, e.g. {"region": "EU"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    dry_run: str = Field(
        "false",
        title="Dry Run",
        description="Validate the run without executing or consuming usage",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    update_published_results: str = Field(
        "false",
        title="Update Published Results",
        description="Persist results to the published app (requires Can Edit; incompatible with input parameters)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    use_cached_sql_results: str = Field(
        "true",
        title="Use Cached SQL Results",
        description="Reuse cached SQL results where possible",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    view_id: Optional[str] = Field(
        None,
        title="View ID",
        description="Run a saved view (incompatible with input parameters)",
    )


class HexGetRunStatusConfig(BaseModel):
    """Get the status of a single project run."""

    operation: Literal["get_run_status"] = Field(
        "get_run_status",
        json_schema_extra={
            "const": "get_run_status",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "Get Run Status",
        },
        title="Get Run Status",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project the run belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )
    run_id: str = Field(..., title="Run ID", description="The run to check the status of")


class HexGetProjectRunsConfig(BaseModel):
    """List recent runs for a project."""

    operation: Literal["get_project_runs"] = Field(
        "get_project_runs",
        json_schema_extra={
            "const": "get_project_runs",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "Get Project Runs",
        },
        title="Get Project Runs",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project to list runs for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of runs to return"
    )
    status_filter: Optional[str] = Field(
        None,
        title="Status Filter",
        description="Filter runs by status",
        json_schema_extra={
            "enum": [
                "",
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "ERRORED",
                "KILLED",
                "UNABLE_TO_ALLOCATE_KERNEL",
            ],
            "enumNames": [
                "Any",
                "Pending",
                "Running",
                "Completed",
                "Errored",
                "Killed",
                "Unable to allocate kernel",
            ],
            "x-enum-searchable": True,
        },
    )


class HexCancelRunConfig(BaseModel):
    """Cancel an in-progress run."""

    operation: Literal["cancel_run"] = Field(
        "cancel_run",
        json_schema_extra={
            "const": "cancel_run",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "Cancel Run",
        },
        title="Cancel Run",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project the run belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )
    run_id: str = Field(..., title="Run ID", description="The run to cancel")


class HexGetRunCellImageConfig(BaseModel):
    """Download a rendered PNG of a chart/cell output from a run."""

    operation: Literal["get_run_cell_image"] = Field(
        "get_run_cell_image",
        json_schema_extra={
            "const": "get_run_cell_image",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "Get Run Cell Image",
        },
        title="Get Run Cell Image",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project the run belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )
    run_id: str = Field(..., title="Run ID", description="The run to fetch the cell image from")
    static_id: str = Field(
        ..., title="Cell Static ID", description="The static ID of the chart/cell to render"
    )


class HexListProjectsConfig(BaseModel):
    """List all projects the caller can view."""

    operation: Literal["list_projects"] = Field(
        "list_projects",
        json_schema_extra={
            "const": "list_projects",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "List Projects",
        },
        title="List Projects",
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of projects to return per page"
    )
    after: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (pagination.after from a prior page)"
    )


class HexGetProjectConfig(BaseModel):
    """Fetch metadata for a single project."""

    operation: Literal["get_project"] = Field(
        "get_project",
        json_schema_extra={
            "const": "get_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Project",
        },
        title="Get Project",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project to fetch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )


class HexUpdateProjectConfig(BaseModel):
    """Update a project's status or endorsements."""

    operation: Literal["update_project"] = Field(
        "update_project",
        json_schema_extra={
            "const": "update_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Update Project",
        },
        title="Update Project",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Update Body",
        description='JSON body of fields to update, e.g. {"status": {"name": "In review"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class HexUpdateProjectCollectionSharingConfig(BaseModel):
    """Add or remove a project from collections."""

    operation: Literal["update_collection_sharing"] = Field(
        "update_collection_sharing",
        json_schema_extra={
            "const": "update_collection_sharing",
            "ui:hidden": True,
            "x-category": "Sharing",
            "x-is-trigger": False,
            "x-display-name": "Update Collection Sharing",
        },
        title="Update Collection Sharing",
    )
    project_id: str = Field(..., title="Project ID", description="The project to update sharing for")
    body: str = Field(
        ...,
        title="Sharing Body",
        description='JSON body. Must include a "sharing" wrapper. To add a project to a collection: {"sharing": {"upsert": {"collections": [{"collection": {"id": "COLLECTION_ID"}, "access": "CAN_VIEW"}]}}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class HexUpdateProjectWorkspaceSharingConfig(BaseModel):
    """Set workspace-wide or public access level for a project."""

    operation: Literal["update_workspace_sharing"] = Field(
        "update_workspace_sharing",
        json_schema_extra={
            "const": "update_workspace_sharing",
            "ui:hidden": True,
            "x-category": "Sharing",
            "x-is-trigger": False,
            "x-display-name": "Update Workspace/Public Sharing",
        },
        title="Update Workspace/Public Sharing",
    )
    project_id: str = Field(..., title="Project ID", description="The project to update sharing for")
    body: str = Field(
        ...,
        title="Sharing Body",
        description='JSON body. Must include a "sharing" wrapper. Set workspace access: {"sharing": {"workspace": "CAN_VIEW"}} — valid values: "NONE", "CAN_VIEW", "CAN_EDIT", "CAN_PUBLISH".',
        json_schema_extra={"ui:widget": "textarea"},
    )


class HexUpdateProjectGroupSharingConfig(BaseModel):
    """Add groups or change their access level on a project."""

    operation: Literal["update_group_sharing"] = Field(
        "update_group_sharing",
        json_schema_extra={
            "const": "update_group_sharing",
            "ui:hidden": True,
            "x-category": "Sharing",
            "x-is-trigger": False,
            "x-display-name": "Update Group Sharing",
        },
        title="Update Group Sharing",
    )
    project_id: str = Field(..., title="Project ID", description="The project to update sharing for")
    body: str = Field(
        ...,
        title="Sharing Body",
        description='JSON body. Must include a "sharing" wrapper. To add a group: {"sharing": {"upsert": {"groups": [{"group": {"id": "GROUP_ID"}, "access": "CAN_VIEW"}]}}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class HexUpdateProjectUserSharingConfig(BaseModel):
    """Add users or change their access level on a project."""

    operation: Literal["update_user_sharing"] = Field(
        "update_user_sharing",
        json_schema_extra={
            "const": "update_user_sharing",
            "ui:hidden": True,
            "x-category": "Sharing",
            "x-is-trigger": False,
            "x-display-name": "Update User Sharing",
        },
        title="Update User Sharing",
    )
    project_id: str = Field(..., title="Project ID", description="The project to update sharing for")
    body: str = Field(
        ...,
        title="Sharing Body",
        description='JSON body. Must include a "sharing" wrapper. To add a user: {"sharing": {"upsert": {"users": [{"user": {"id": "USER_ID"}, "access": "CAN_VIEW"}]}}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class HexCreateEmbedUrlConfig(BaseModel):
    """Create a signed embed URL for a project."""

    operation: Literal["create_embed_url"] = Field(
        "create_embed_url",
        json_schema_extra={
            "const": "create_embed_url",
            "ui:hidden": True,
            "x-category": "Embedding",
            "x-is-trigger": False,
            "x-display-name": "Create Embed URL",
        },
        title="Create Embed URL",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project to embed",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )
    hex_user_attributes: Optional[str] = Field(
        None,
        title="Hex User Attributes",
        description="JSON object of user attributes to scope the embed",
        json_schema_extra={"ui:widget": "textarea"},
    )
    input_parameters: Optional[str] = Field(
        None,
        title="Input Parameters",
        description="JSON object of published app parameters for the embed",
        json_schema_extra={"ui:widget": "textarea"},
    )
    expires_in: Optional[str] = Field(
        None, title="Expires In (ms)", description="Lifetime of the signed URL in milliseconds"
    )
    test_mode: str = Field(
        "false",
        title="Test Mode",
        description="Validate the embed without consuming usage",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class HexListUsersConfig(BaseModel):
    """List workspace users (Admin API; Team/Enterprise)."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
        title="List Users",
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of users to return per page"
    )
    after: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor for the next page"
    )


class HexGetMeConfig(BaseModel):
    """Return the token owner's user info."""

    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


class HexDeactivateUserConfig(BaseModel):
    """Deactivate a workspace user."""

    operation: Literal["deactivate_user"] = Field(
        "deactivate_user",
        json_schema_extra={
            "const": "deactivate_user",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "Deactivate User",
        },
        title="Deactivate User",
    )
    user_id: str = Field(..., title="User ID", description="The user to deactivate")


class HexListGroupsConfig(BaseModel):
    """List all groups."""

    operation: Literal["list_groups"] = Field(
        "list_groups",
        json_schema_extra={
            "const": "list_groups",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "List Groups",
        },
        title="List Groups",
    )


class HexCreateGroupConfig(BaseModel):
    """Create a new group."""

    operation: Literal["create_group"] = Field(
        "create_group",
        json_schema_extra={
            "const": "create_group",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Create Group",
        },
        title="Create Group",
    )
    name: str = Field(..., title="Group Name", description="Name of the new group")


class HexGetGroupConfig(BaseModel):
    """Fetch a group's details."""

    operation: Literal["get_group"] = Field(
        "get_group",
        json_schema_extra={
            "const": "get_group",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Get Group",
        },
        title="Get Group",
    )
    group_id: str = Field(..., title="Group ID", description="The group to fetch")


class HexEditGroupConfig(BaseModel):
    """Rename a group or add/remove members."""

    operation: Literal["edit_group"] = Field(
        "edit_group",
        json_schema_extra={
            "const": "edit_group",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Edit Group",
        },
        title="Edit Group",
    )
    group_id: str = Field(..., title="Group ID", description="The group to edit")
    body: str = Field(
        ...,
        title="Edit Body",
        description='JSON body, e.g. {"name": "New name"} or member add/remove operations',
        json_schema_extra={"ui:widget": "textarea"},
    )


class HexDeleteGroupConfig(BaseModel):
    """Delete a group."""

    operation: Literal["delete_group"] = Field(
        "delete_group",
        json_schema_extra={
            "const": "delete_group",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Delete Group",
        },
        title="Delete Group",
    )
    group_id: str = Field(..., title="Group ID", description="The group to delete")


class HexListCollectionsConfig(BaseModel):
    """List all collections."""

    operation: Literal["list_collections"] = Field(
        "list_collections",
        json_schema_extra={
            "const": "list_collections",
            "ui:hidden": True,
            "x-category": "Collections",
            "x-is-trigger": False,
            "x-display-name": "List Collections",
        },
        title="List Collections",
    )


class HexCreateCollectionConfig(BaseModel):
    """Create a collection."""

    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={
            "const": "create_collection",
            "ui:hidden": True,
            "x-category": "Collections",
            "x-is-trigger": False,
            "x-display-name": "Create Collection",
        },
        title="Create Collection",
    )
    name: str = Field(..., title="Collection Name", description="Name of the new collection")
    description: Optional[str] = Field(
        None, title="Description", description="Optional collection description"
    )


class HexGetCollectionConfig(BaseModel):
    """Fetch a collection's details."""

    operation: Literal["get_collection"] = Field(
        "get_collection",
        json_schema_extra={
            "const": "get_collection",
            "ui:hidden": True,
            "x-category": "Collections",
            "x-is-trigger": False,
            "x-display-name": "Get Collection",
        },
        title="Get Collection",
    )
    collection_id: str = Field(..., title="Collection ID", description="The collection to fetch")


class HexEditCollectionConfig(BaseModel):
    """Edit a collection; upsert user/group/workspace access."""

    operation: Literal["edit_collection"] = Field(
        "edit_collection",
        json_schema_extra={
            "const": "edit_collection",
            "ui:hidden": True,
            "x-category": "Collections",
            "x-is-trigger": False,
            "x-display-name": "Edit Collection",
        },
        title="Edit Collection",
    )
    collection_id: str = Field(..., title="Collection ID", description="The collection to edit")
    body: str = Field(
        ...,
        title="Edit Body",
        description='JSON body, e.g. {"name": "...", "sharing": {"upsert": [...]}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class HexListDataConnectionsConfig(BaseModel):
    """List configured data connections."""

    operation: Literal["list_data_connections"] = Field(
        "list_data_connections",
        json_schema_extra={
            "const": "list_data_connections",
            "ui:hidden": True,
            "x-category": "Data Connections",
            "x-is-trigger": False,
            "x-display-name": "List Data Connections",
        },
        title="List Data Connections",
    )


class HexEditDataConnectionConfig(BaseModel):
    """Edit a data connection / rotate secrets."""

    operation: Literal["edit_data_connection"] = Field(
        "edit_data_connection",
        json_schema_extra={
            "const": "edit_data_connection",
            "ui:hidden": True,
            "x-category": "Data Connections",
            "x-is-trigger": False,
            "x-display-name": "Edit Data Connection",
        },
        title="Edit Data Connection",
    )
    data_connection_id: str = Field(
        ..., title="Data Connection ID", description="The data connection to edit"
    )
    body: str = Field(
        ...,
        title="Edit Body",
        description="JSON body describing the connection edits (e.g. rotate password / service account)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class HexIngestSemanticProjectConfig(BaseModel):
    """Ingest a semantic project from a zip (max 3 req/min)."""

    operation: Literal["ingest_semantic_project"] = Field(
        "ingest_semantic_project",
        json_schema_extra={
            "const": "ingest_semantic_project",
            "ui:hidden": True,
            "x-category": "Semantic Models",
            "x-is-trigger": False,
            "x-display-name": "Ingest Semantic Project",
        },
        title="Ingest Semantic Project",
    )
    semantic_project_id: str = Field(
        ..., title="Semantic Project ID", description="The semantic project to ingest into"
    )
    body: Optional[str] = Field(
        None,
        title="Ingest Body",
        description="JSON body describing the ingest source (e.g. zip reference)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Trigger Config (poll-based)
# ============================================================================


class HexOnRunCompletedConfig(PollTriggerConfigBase):
    """Trigger: poll a project's runs for newly-finished runs (COMPLETED/ERRORED/KILLED).

    Hex has no inbound webhook subscription API, so this is poll-based: the
    webhook is a wake-up signal and execute() actually polls the Get Project
    Runs endpoint. Dedup and state persistence are handled by ScheduledPollTriggerMixin."""

    operation: Literal["on_run_completed"] = Field(
        "on_run_completed",
        json_schema_extra={
            "const": "on_run_completed",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Project Run Completed",
        },
        title="On Project Run Completed",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The project whose runs to watch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID",
            }
        },
    )
    status_filter: Optional[str] = Field(
        None,
        title="Status Filter",
        description="Only fire for runs that reached this status (default: any terminal status)",
        json_schema_extra={
            "enum": ["", "COMPLETED", "ERRORED", "KILLED"],
            "enumNames": ["Any terminal", "Completed", "Errored", "Killed"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "25",
        title="Max Runs Per Poll",
        description="Max number of recent runs to inspect each poll",
        json_schema_extra={"ui:hidden": True},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


HexConfig = Annotated[
    Union[
        HexRunProjectConfig,
        HexGetRunStatusConfig,
        HexGetProjectRunsConfig,
        HexCancelRunConfig,
        HexGetRunCellImageConfig,
        HexListProjectsConfig,
        HexGetProjectConfig,
        HexUpdateProjectConfig,
        HexUpdateProjectCollectionSharingConfig,
        HexUpdateProjectWorkspaceSharingConfig,
        HexUpdateProjectGroupSharingConfig,
        HexUpdateProjectUserSharingConfig,
        HexCreateEmbedUrlConfig,
        HexListUsersConfig,
        HexGetMeConfig,
        HexDeactivateUserConfig,
        HexListGroupsConfig,
        HexCreateGroupConfig,
        HexGetGroupConfig,
        HexEditGroupConfig,
        HexDeleteGroupConfig,
        HexListCollectionsConfig,
        HexCreateCollectionConfig,
        HexGetCollectionConfig,
        HexEditCollectionConfig,
        HexListDataConnectionsConfig,
        HexEditDataConnectionConfig,
        HexIngestSemanticProjectConfig,
        HexOnRunCompletedConfig,
    ],
    Discriminator("operation"),
]


class HexNodeConfig(NodeConfig[HexConfig, HexCredential]):
    """Full configuration for the Hex node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _base_url(workspace_host: Optional[str]) -> str:
    raw_host = (workspace_host or DEFAULT_HEX_HOST).strip()
    parts = urlsplit(raw_host if "://" in raw_host else f"//{raw_host}")
    parsed_host = (parts.hostname or "").lower().rstrip(".")
    if "." in parsed_host and not parsed_host.endswith(".hex.tech"):
        raise SSRFError("Hex workspace host must be under hex.tech")
    tenant = normalize_provider_subdomain(
        raw_host,
        "hex.tech",
        field_name="Hex workspace host",
        allow_nested_labels=True,
    )
    return f"https://{tenant}.hex.tech/api/v1"


def _parse_json_field(value: Optional[str], field_label: str) -> Optional[Dict[str, Any]]:
    """Parse a textarea JSON field. Raises ValueError on invalid JSON."""
    if value is None or value == "":
        return None
    import json

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field_label} must be valid JSON: {e}")
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_label} must be a JSON object")
    return parsed


def _parse_int(value: Optional[str], field_label: str) -> Optional[int]:
    """Parse an optional integer string field. Raises ValueError on non-integer input."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field_label} must be a whole number, got: {value!r}")


async def _hex_request(
    api_token: str,
    workspace_host: Optional[str],
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Hex API request and return a structured result."""
    url = f"{_base_url(workspace_host)}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with guarded_async_client(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        message = err.get("reason") or err.get("message") or err.get("error") or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[HexNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}
                elif content_type.startswith("image/"):
                    import mimetypes
                    from nodes.core.binary_output import BinaryOutput
                    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".png"
                    data = BinaryOutput(
                        data=response.content,
                        content_type=content_type,
                        filename=f"hex_export{ext}",
                    )
                else:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[HexNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class HexNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Hex data/BI automation node."""

    edit_examples = [
        "Run a Hex project with input parameters and poll for completion",
        "Get the status of a Hex project run",
        "List all Hex projects I can view",
        "Create a signed embed URL for a Hex app",
        "List workspace users via the Hex Admin API",
    ]

    @classmethod
    def get_config_model(cls):
        return HexNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (projects)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        user_id: str,
        config_data: Dict[str, Any],
        credential_ids: Optional[Dict[str, str]] = None,
        pool=None,
    ) -> Dict[str, Any]:
        if field_name != "project_id":
            return {"options": []}
        from utils.credential_loader import load_credential

        credential_id = next((cid for cid in (credential_ids or {}).values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id) if credential_id else None
        if not credential:
            return {"options": []}
        api_token = credential.get("api_token")
        workspace_host = credential.get("workspace_host")
        result = await _hex_request(
            api_token,
            workspace_host,
            "GET",
            "/projects",
            params={"limit": 100},
            action_name="list_projects",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        projects = data.get("values") if isinstance(data, dict) else data
        if not isinstance(projects, list):
            projects = []
        options = []
        for p in projects:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            title = p.get("title") or p.get("name") or f"Project {pid}"
            if pid is not None:
                options.append({"label": str(title), "value": str(pid)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, HexNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Hex API token.")
        api_token = credentials.api_token
        workspace_host = credentials.workspace_host

        handlers = {
            "run_project": self._run_project,
            "get_run_status": self._get_run_status,
            "get_project_runs": self._get_project_runs,
            "cancel_run": self._cancel_run,
            "get_run_cell_image": self._get_run_cell_image,
            "list_projects": self._list_projects,
            "get_project": self._get_project,
            "update_project": self._update_project,
            "update_collection_sharing": self._update_collection_sharing,
            "update_workspace_sharing": self._update_workspace_sharing,
            "update_group_sharing": self._update_group_sharing,
            "update_user_sharing": self._update_user_sharing,
            "create_embed_url": self._create_embed_url,
            "list_users": self._list_users,
            "get_me": self._get_me,
            "deactivate_user": self._deactivate_user,
            "list_groups": self._list_groups,
            "create_group": self._create_group,
            "get_group": self._get_group,
            "edit_group": self._edit_group,
            "delete_group": self._delete_group,
            "list_collections": self._list_collections,
            "create_collection": self._create_collection,
            "get_collection": self._get_collection,
            "edit_collection": self._edit_collection,
            "list_data_connections": self._list_data_connections,
            "edit_data_connection": self._edit_data_connection,
            "ingest_semantic_project": self._ingest_semantic_project,
            "on_run_completed": self._on_run_completed,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_token, workspace_host)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Runs
    # ------------------------------------------------------------------
    async def _run_project(self, c: HexRunProjectConfig, token: str, host: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "inputParams": _parse_json_field(c.input_params, "Input Parameters"),
            "dryRun": c.dry_run == "true",
            "updatePublishedResults": c.update_published_results == "true",
            "useCachedSqlResults": c.use_cached_sql_results == "true",
            "viewId": c.view_id,
        }
        return await _hex_request(
            token, host, "POST", f"/projects/{c.project_id}/runs", json_body=body,
            action_name="run_project",
        )

    async def _get_run_status(self, c: HexGetRunStatusConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "GET", f"/projects/{c.project_id}/runs/{c.run_id}",
            action_name="get_run_status",
        )

    async def _get_project_runs(self, c: HexGetProjectRunsConfig, token: str, host: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "statusFilter": c.status_filter or None}
        return await _hex_request(
            token, host, "GET", f"/projects/{c.project_id}/runs", params=params,
            action_name="get_project_runs",
        )

    async def _on_run_completed(
        self, c: HexOnRunCompletedConfig, token: str, host: str
    ) -> Dict[str, Any]:
        """Poll Get Project Runs for runs that newly reached a terminal status.

        Hex has no push API, so we poll on the configured schedule. Dedup is
        handled by ScheduledPollTriggerMixin._filter_unseen, which persists
        seen run IDs via _save_node_state and baselines on the first poll
        (records current IDs as seen, emits nothing) to avoid flooding old runs.
        """
        terminal_statuses = (
            {c.status_filter} if c.status_filter else {"COMPLETED", "ERRORED", "KILLED"}
        )
        result = await _hex_request(
            token, host, "GET", f"/projects/{c.project_id}/runs",
            params={"limit": c.limit, "statusFilter": c.status_filter or None},
            action_name="on_run_completed",
        )
        if result.get("status") != "success":
            return result

        data = result.get("data") or {}
        runs = data.get("runs") if isinstance(data, dict) else []
        if not isinstance(runs, list):
            runs = []

        terminal_runs = [
            r for r in runs
            if isinstance(r, dict) and r.get("status") in terminal_statuses
        ]

        fresh = await self._filter_unseen(
            terminal_runs,
            id_fn=lambda r: r.get("runId") or r.get("id"),
        )

        return {
            "status": "success",
            "operation": "on_run_completed",
            "project_id": c.project_id,
            "new_count": len(fresh),
            "items": fresh,
            "timing_ms": result.get("timing_ms", {}),
        }

    async def _cancel_run(self, c: HexCancelRunConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "DELETE", f"/projects/{c.project_id}/runs/{c.run_id}",
            action_name="cancel_run",
        )

    async def _get_run_cell_image(self, c: HexGetRunCellImageConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "GET",
            f"/projects/{c.project_id}/runs/{c.run_id}/cells/{c.static_id}/image",
            action_name="get_run_cell_image",
        )

    # ------------------------------------------------------------------
    # Handlers — Projects
    # ------------------------------------------------------------------
    async def _list_projects(self, c: HexListProjectsConfig, token: str, host: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "after": c.after}
        return await _hex_request(
            token, host, "GET", "/projects", params=params, action_name="list_projects",
        )

    async def _get_project(self, c: HexGetProjectConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "GET", f"/projects/{c.project_id}", action_name="get_project",
        )

    async def _update_project(self, c: HexUpdateProjectConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "PATCH", f"/projects/{c.project_id}",
            json_body=_parse_json_field(c.body, "Update Body"), action_name="update_project",
        )

    async def _update_collection_sharing(self, c: HexUpdateProjectCollectionSharingConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "PATCH", f"/projects/{c.project_id}/sharing/collections",
            json_body=_parse_json_field(c.body, "Sharing Body"),
            action_name="update_collection_sharing",
        )

    async def _update_workspace_sharing(self, c: HexUpdateProjectWorkspaceSharingConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "PATCH", f"/projects/{c.project_id}/sharing/workspaceAndPublic",
            json_body=_parse_json_field(c.body, "Sharing Body"),
            action_name="update_workspace_sharing",
        )

    async def _update_group_sharing(self, c: HexUpdateProjectGroupSharingConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "PATCH", f"/projects/{c.project_id}/sharing/groups",
            json_body=_parse_json_field(c.body, "Sharing Body"),
            action_name="update_group_sharing",
        )

    async def _update_user_sharing(self, c: HexUpdateProjectUserSharingConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "PATCH", f"/projects/{c.project_id}/sharing/users",
            json_body=_parse_json_field(c.body, "Sharing Body"),
            action_name="update_user_sharing",
        )

    # ------------------------------------------------------------------
    # Handlers — Embedding
    # ------------------------------------------------------------------
    async def _create_embed_url(self, c: HexCreateEmbedUrlConfig, token: str, host: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "hexUserAttributes": _parse_json_field(c.hex_user_attributes, "Hex User Attributes"),
            "inputParameters": _parse_json_field(c.input_parameters, "Input Parameters"),
            "expiresIn": _parse_int(c.expires_in, "Expires In"),
            "testMode": c.test_mode == "true",
        }
        return await _hex_request(
            token, host, "POST", f"/embedding/createPresignedUrl/{c.project_id}",
            json_body=body, action_name="create_embed_url",
        )

    # ------------------------------------------------------------------
    # Handlers — Admin / Users
    # ------------------------------------------------------------------
    async def _list_users(self, c: HexListUsersConfig, token: str, host: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "after": c.after}
        return await _hex_request(
            token, host, "GET", "/users", params=params, action_name="list_users",
        )

    async def _get_me(self, c: HexGetMeConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(token, host, "GET", "/users/me", action_name="get_me")

    async def _deactivate_user(self, c: HexDeactivateUserConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "POST", f"/users/{c.user_id}/deactivate", action_name="deactivate_user",
        )

    # ------------------------------------------------------------------
    # Handlers — Groups
    # ------------------------------------------------------------------
    async def _list_groups(self, c: HexListGroupsConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(token, host, "GET", "/groups", action_name="list_groups")

    async def _create_group(self, c: HexCreateGroupConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "POST", "/groups", json_body={"name": c.name}, action_name="create_group",
        )

    async def _get_group(self, c: HexGetGroupConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "GET", f"/groups/{c.group_id}", action_name="get_group",
        )

    async def _edit_group(self, c: HexEditGroupConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "PATCH", f"/groups/{c.group_id}",
            json_body=_parse_json_field(c.body, "Edit Body"), action_name="edit_group",
        )

    async def _delete_group(self, c: HexDeleteGroupConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "DELETE", f"/groups/{c.group_id}", action_name="delete_group",
        )

    # ------------------------------------------------------------------
    # Handlers — Collections
    # ------------------------------------------------------------------
    async def _list_collections(self, c: HexListCollectionsConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(token, host, "GET", "/collections", action_name="list_collections")

    async def _create_collection(self, c: HexCreateCollectionConfig, token: str, host: str) -> Dict[str, Any]:
        body = {"name": c.name, "description": c.description}
        return await _hex_request(
            token, host, "POST", "/collections", json_body=body, action_name="create_collection",
        )

    async def _get_collection(self, c: HexGetCollectionConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "GET", f"/collections/{c.collection_id}", action_name="get_collection",
        )

    async def _edit_collection(self, c: HexEditCollectionConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "PATCH", f"/collections/{c.collection_id}",
            json_body=_parse_json_field(c.body, "Edit Body"), action_name="edit_collection",
        )

    # ------------------------------------------------------------------
    # Handlers — Data Connections
    # ------------------------------------------------------------------
    async def _list_data_connections(self, c: HexListDataConnectionsConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "GET", "/data-connections", action_name="list_data_connections",
        )

    async def _edit_data_connection(self, c: HexEditDataConnectionConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "PATCH", f"/data-connections/{c.data_connection_id}",
            json_body=_parse_json_field(c.body, "Edit Body"), action_name="edit_data_connection",
        )

    # ------------------------------------------------------------------
    # Handlers — Semantic Models
    # ------------------------------------------------------------------
    async def _ingest_semantic_project(self, c: HexIngestSemanticProjectConfig, token: str, host: str) -> Dict[str, Any]:
        return await _hex_request(
            token, host, "POST", f"/semantic-models/{c.semantic_project_id}/ingest",
            json_body=_parse_json_field(c.body, "Ingest Body"),
            action_name="ingest_semantic_project",
        )
