"""
Sigma Computing BI automation node.

Provides workflow integration with the Sigma Computing REST API (v2) for
operations including:
- Workbooks: list, get, create, update, delete, export, download, materialize, sources
- Members: list, get, create, update, delete
- Teams: list, create, add members, remove member
- Connections: list, create, test
- Workspaces: list, create, add grant
- Catalog: list files, list data models, get data model spec, list account types, list API credentials

Authentication: OAuth 2.0 client-credentials grant. The user supplies a Sigma
API Client ID + Client Secret (generated in Administration -> Developer Access);
the node exchanges them for a 1-hour Bearer JWT on each request. No interactive
authorize step (server-to-server), so this behaves like an API-key credential.

API Base URL: region-specific, e.g. https://aws-api.sigmacomputing.com/v2
Documentation: https://help.sigmacomputing.com/reference/get-started-sigma-api
"""

import logging
import time
import uuid as uuid_module
from typing import Dict, Any, Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.poll_trigger import bounded_seen_ids
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)
from utils.oauth_token_cache import (
    OAuthTokenCache,
    oauth_authority_digest,
    token_expiry_input,
)

logger = logging.getLogger(__name__)

# Region host -> API base host. The org's cloud platform is fixed at creation
# and cannot be migrated, so the base URL must be selected per org.
SIGMA_REGION_HOSTS = {
    "aws-us-west": "aws-api.sigmacomputing.com",
    "aws-us-east": "api.us-a.aws.sigmacomputing.com",
    "aws-canada": "api.ca.aws.sigmacomputing.com",
    "aws-europe": "api.eu.aws.sigmacomputing.com",
    "aws-uk": "api.uk.aws.sigmacomputing.com",
    "aws-ap-sydney": "api.au.aws.sigmacomputing.com",
    "azure-us": "api.us.azure.sigmacomputing.com",
    "azure-eu": "api.eu.azure.sigmacomputing.com",
    "azure-canada": "api.ca.azure.sigmacomputing.com",
    "azure-uk": "api.uk.azure.sigmacomputing.com",
    "gcp-us": "api.sigmacomputing.com",
    "gcp-saudi-arabia": "api.sa.gcp.sigmacomputing.com",
}
SIGMA_DEFAULT_REGION = "aws-us-west"


def _sigma_base_url(region: Optional[str]) -> str:
    host = SIGMA_REGION_HOSTS.get(region or SIGMA_DEFAULT_REGION, SIGMA_REGION_HOSTS[SIGMA_DEFAULT_REGION])
    return f"https://{host}/v2"


# ============================================================================
# Credential Schema
# ============================================================================


class SigmaApiKeyCredential(BaseModel):
    """Sigma API client-credentials (Client ID + Client Secret)."""

    credential_type: Literal["sigma_api_key"] = Field(
        "sigma_api_key", json_schema_extra={"ui:hidden": True}
    )
    client_id: str = Field(
        ...,
        title="Client ID",
        description="Sigma API Client ID from Administration -> Developer Access -> Create New",
    )
    client_secret: str = Field(
        ...,
        title="Client Secret",
        description="Sigma API Client Secret paired with the Client ID",
        json_schema_extra={"ui:widget": "password"},
    )
    region: str = Field(
        SIGMA_DEFAULT_REGION,
        title="Region",
        description="Cloud region your Sigma org runs in (fixed at org creation)",
        json_schema_extra={
            "enum": list(SIGMA_REGION_HOSTS.keys()),
            "enumNames": [
                "AWS US West (Oregon)",
                "AWS US East (Virginia)",
                "AWS Canada",
                "AWS Europe (Frankfurt)",
                "AWS UK (London)",
                "AWS Asia-Pacific (Sydney)",
                "Azure US",
                "Azure EU",
                "Azure Canada",
                "Azure UK",
                "GCP US (Iowa)",
                "GCP Saudi Arabia",
            ],
            "x-enum-searchable": True,
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://help.sigmacomputing.com/reference/get-started-sigma-api"
        }
    )


SigmaCredential = SigmaApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class SigmaListWorkbooksConfig(BaseModel):
    """List workbooks the credential can access."""

    operation: Literal["list_workbooks"] = Field(
        "list_workbooks",
        json_schema_extra={
            "const": "list_workbooks",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "List Workbooks",
        },
        title="List Workbooks",
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max workbooks to return (1-1000)"
    )
    page: Optional[str] = Field(
        None, title="Page", description="Cursor (nextPage value) for pagination"
    )


class SigmaGetWorkbookConfig(BaseModel):
    """Get metadata for a single workbook."""

    operation: Literal["get_workbook"] = Field(
        "get_workbook",
        json_schema_extra={
            "const": "get_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Get Workbook",
        },
        title="Get Workbook",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="The workbook to retrieve",
        json_schema_extra={
            "x-resource-type": "sigma_workbook",
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a workbook ID",
            }
        },
    )


class SigmaCreateWorkbookConfig(BaseModel):
    """Create a new workbook."""

    operation: Literal["create_workbook"] = Field(
        "create_workbook",
        json_schema_extra={
            "const": "create_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Create Workbook",
            "x-creates-resource": True,
            "x-resource-type": "sigma_workbook",
            "x-resource-id-path": "data.workbookId",
        },
        title="Create Workbook",
    )
    name: str = Field(..., title="Name", description="Name of the new workbook")
    folder_id: Optional[str] = Field(
        None, title="Folder ID", description="ID of the folder to create the workbook in"
    )


class SigmaUpdateWorkbookConfig(BaseModel):
    """Update a workbook's metadata."""

    operation: Literal["update_workbook"] = Field(
        "update_workbook",
        json_schema_extra={
            "const": "update_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Update Workbook",
        },
        title="Update Workbook",
    )
    workbook_id: str = Field(..., title="Workbook ID", description="The workbook to update")
    name: Optional[str] = Field(None, title="Name", description="New workbook name")


class SigmaDeleteWorkbookConfig(BaseModel):
    """Delete a workbook."""

    operation: Literal["delete_workbook"] = Field(
        "delete_workbook",
        json_schema_extra={
            "const": "delete_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Delete Workbook",
        },
        title="Delete Workbook",
    )
    workbook_id: str = Field(..., title="Workbook ID", description="The workbook to delete")


class SigmaExportWorkbookConfig(BaseModel):
    """Trigger an async export of a workbook (returns a queryId)."""

    operation: Literal["export_workbook"] = Field(
        "export_workbook",
        json_schema_extra={
            "const": "export_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Export Workbook",
        },
        title="Export Workbook",
    )
    workbook_id: str = Field(..., title="Workbook ID", description="The workbook to export")
    export_format: str = Field(
        "pdf",
        title="Format",
        description="Export file format. CSV/JSON/JSONL/PNG require an Element ID. Whole-workbook exports support PDF and XLSX only.",
        json_schema_extra={
            "enum": ["pdf", "xlsx", "csv", "json", "jsonl", "png"],
            "enumNames": ["PDF (whole workbook)", "XLSX (whole workbook)", "CSV (element only)", "JSON (element only)", "JSONL (element only)", "PNG (element only)"],
            "x-enum-searchable": True,
        },
    )
    element_id: Optional[str] = Field(
        None, title="Element ID", description="Specific workbook element to export (required for CSV/JSON/JSONL/PNG formats)"
    )


class SigmaDownloadExportConfig(BaseModel):
    """Download the file produced by an export once ready."""

    operation: Literal["download_export"] = Field(
        "download_export",
        json_schema_extra={
            "const": "download_export",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Download Export",
        },
        title="Download Export",
    )
    query_id: str = Field(
        ..., title="Query ID", description="The queryId returned by an export request"
    )


class SigmaMaterializeWorkbookConfig(BaseModel):
    """Trigger a materialization job for a workbook element."""

    operation: Literal["materialize_workbook"] = Field(
        "materialize_workbook",
        json_schema_extra={
            "const": "materialize_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Materialize Workbook",
        },
        title="Materialize Workbook",
    )
    workbook_id: str = Field(..., title="Workbook ID", description="The workbook to materialize")
    sheet_id: Optional[str] = Field(
        None, title="Sheet ID", description="Specific sheet/element ID to materialize (from materialization-schedules)"
    )


class SigmaGetWorkbookSourcesConfig(BaseModel):
    """List the data sources a workbook depends on."""

    operation: Literal["get_workbook_sources"] = Field(
        "get_workbook_sources",
        json_schema_extra={
            "const": "get_workbook_sources",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Get Workbook Sources",
        },
        title="Get Workbook Sources",
    )
    workbook_id: str = Field(..., title="Workbook ID", description="The workbook to inspect")


class SigmaListMembersConfig(BaseModel):
    """List organization members/users."""

    operation: Literal["list_members"] = Field(
        "list_members",
        json_schema_extra={
            "const": "list_members",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "List Members",
        },
        title="List Members",
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max members to return (1-1000)"
    )
    page: Optional[str] = Field(
        None, title="Page", description="Cursor (nextPage value) for pagination"
    )


class SigmaGetMemberConfig(BaseModel):
    """Get a single member's profile."""

    operation: Literal["get_member"] = Field(
        "get_member",
        json_schema_extra={
            "const": "get_member",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Get Member",
        },
        title="Get Member",
    )
    member_id: str = Field(..., title="Member ID", description="The member to retrieve")


class SigmaCreateMemberConfig(BaseModel):
    """Invite/provision a new member."""

    operation: Literal["create_member"] = Field(
        "create_member",
        json_schema_extra={
            "const": "create_member",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Create Member",
        },
        title="Create Member",
    )
    email: str = Field(..., title="Email", description="Email address of the new member")
    first_name: str = Field(..., title="First Name", description="Member's first name")
    last_name: str = Field(..., title="Last Name", description="Member's last name")
    member_type: Optional[str] = Field(
        None,
        title="Account Type",
        description="Account type / license tier name (e.g. Admin, Creator, Viewer)",
    )


class SigmaUpdateMemberConfig(BaseModel):
    """Update a member's account type, name, or status."""

    operation: Literal["update_member"] = Field(
        "update_member",
        json_schema_extra={
            "const": "update_member",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Update Member",
        },
        title="Update Member",
    )
    member_id: str = Field(..., title="Member ID", description="The member to update")
    first_name: Optional[str] = Field(None, title="First Name", description="New first name")
    last_name: Optional[str] = Field(None, title="Last Name", description="New last name")
    member_type: Optional[str] = Field(
        None, title="Account Type", description="New account type / license tier name"
    )


class SigmaDeleteMemberConfig(BaseModel):
    """Deactivate/delete a member."""

    operation: Literal["delete_member"] = Field(
        "delete_member",
        json_schema_extra={
            "const": "delete_member",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Delete Member",
        },
        title="Delete Member",
    )
    member_id: str = Field(..., title="Member ID", description="The member to delete")


class SigmaListTeamsConfig(BaseModel):
    """List teams in the organization."""

    operation: Literal["list_teams"] = Field(
        "list_teams",
        json_schema_extra={
            "const": "list_teams",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
        },
        title="List Teams",
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max teams to return (1-1000)"
    )


class SigmaCreateTeamConfig(BaseModel):
    """Create a team."""

    operation: Literal["create_team"] = Field(
        "create_team",
        json_schema_extra={
            "const": "create_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Create Team",
        },
        title="Create Team",
    )
    name: str = Field(..., title="Name", description="Name of the new team")
    description: Optional[str] = Field(
        None, title="Description", description="Optional team description"
    )


class SigmaAddTeamMembersConfig(BaseModel):
    """Add one or more members to a team."""

    operation: Literal["add_team_members"] = Field(
        "add_team_members",
        json_schema_extra={
            "const": "add_team_members",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Add Members to Team",
        },
        title="Add Members to Team",
    )
    team_id: str = Field(..., title="Team ID", description="The team to add members to")
    member_ids: str = Field(
        ..., title="Member IDs", description="Member IDs to add, comma-separated"
    )


class SigmaRemoveTeamMemberConfig(BaseModel):
    """Remove a member from a team."""

    operation: Literal["remove_team_member"] = Field(
        "remove_team_member",
        json_schema_extra={
            "const": "remove_team_member",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Remove Member from Team",
        },
        title="Remove Member from Team",
    )
    team_id: str = Field(..., title="Team ID", description="The team to remove the member from")
    member_id: str = Field(..., title="Member ID", description="The member to remove")


class SigmaGetTeamConfig(BaseModel):
    """Get details of a single team."""

    operation: Literal["get_team"] = Field(
        "get_team",
        json_schema_extra={
            "const": "get_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Get Team",
        },
        title="Get Team",
    )
    team_id: str = Field(..., title="Team ID", description="The team to retrieve")


class SigmaUpdateTeamConfig(BaseModel):
    """Update a team's name or description."""

    operation: Literal["update_team"] = Field(
        "update_team",
        json_schema_extra={
            "const": "update_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Update Team",
        },
        title="Update Team",
    )
    team_id: str = Field(..., title="Team ID", description="The team to update")
    name: Optional[str] = Field(None, title="Name", description="New team name")
    description: Optional[str] = Field(None, title="Description", description="New team description")


class SigmaDeleteTeamConfig(BaseModel):
    """Delete a team."""

    operation: Literal["delete_team"] = Field(
        "delete_team",
        json_schema_extra={
            "const": "delete_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Delete Team",
        },
        title="Delete Team",
    )
    team_id: str = Field(..., title="Team ID", description="The team to delete")


class SigmaListTeamMembersConfig(BaseModel):
    """List members of a team."""

    operation: Literal["list_team_members"] = Field(
        "list_team_members",
        json_schema_extra={
            "const": "list_team_members",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "List Team Members",
        },
        title="List Team Members",
    )
    team_id: str = Field(..., title="Team ID", description="The team whose members to list")
    limit: Optional[str] = Field("50", title="Limit", description="Max members to return")


class SigmaListConnectionsConfig(BaseModel):
    """List data-warehouse connections."""

    operation: Literal["list_connections"] = Field(
        "list_connections",
        json_schema_extra={
            "const": "list_connections",
            "ui:hidden": True,
            "x-category": "Connections",
            "x-is-trigger": False,
            "x-display-name": "List Connections",
        },
        title="List Connections",
    )


class SigmaCreateConnectionConfig(BaseModel):
    """Create a connection to a cloud data warehouse."""

    operation: Literal["create_connection"] = Field(
        "create_connection",
        json_schema_extra={
            "const": "create_connection",
            "ui:hidden": True,
            "x-category": "Connections",
            "x-is-trigger": False,
            "x-display-name": "Create Connection",
        },
        title="Create Connection",
    )
    name: str = Field(..., title="Name", description="Name of the connection")
    connection_type: str = Field(
        ...,
        title="Type",
        description="Warehouse type (e.g. snowflake, bigquery, redshift, postgres)",
    )


class SigmaTestConnectionConfig(BaseModel):
    """Test read/write access of an existing connection."""

    operation: Literal["test_connection"] = Field(
        "test_connection",
        json_schema_extra={
            "const": "test_connection",
            "ui:hidden": True,
            "x-category": "Connections",
            "x-is-trigger": False,
            "x-display-name": "Test Connection",
        },
        title="Test Connection",
    )
    connection_id: str = Field(..., title="Connection ID", description="The connection to test")


class SigmaGetConnectionConfig(BaseModel):
    """Get details of a single connection."""

    operation: Literal["get_connection"] = Field(
        "get_connection",
        json_schema_extra={
            "const": "get_connection",
            "ui:hidden": True,
            "x-category": "Connections",
            "x-is-trigger": False,
            "x-display-name": "Get Connection",
        },
        title="Get Connection",
    )
    connection_id: str = Field(..., title="Connection ID", description="The connection to retrieve")


class SigmaDeleteConnectionConfig(BaseModel):
    """Delete a connection."""

    operation: Literal["delete_connection"] = Field(
        "delete_connection",
        json_schema_extra={
            "const": "delete_connection",
            "ui:hidden": True,
            "x-category": "Connections",
            "x-is-trigger": False,
            "x-display-name": "Delete Connection",
        },
        title="Delete Connection",
    )
    connection_id: str = Field(..., title="Connection ID", description="The connection to delete")


class SigmaSyncConnectionConfig(BaseModel):
    """Sync a connection (refresh its schema in Sigma)."""

    operation: Literal["sync_connection"] = Field(
        "sync_connection",
        json_schema_extra={
            "const": "sync_connection",
            "ui:hidden": True,
            "x-category": "Connections",
            "x-is-trigger": False,
            "x-display-name": "Sync Connection",
        },
        title="Sync Connection",
    )
    connection_id: str = Field(..., title="Connection ID", description="The connection to sync")


class SigmaListWorkspacesConfig(BaseModel):
    """List workspaces."""

    operation: Literal["list_workspaces"] = Field(
        "list_workspaces",
        json_schema_extra={
            "const": "list_workspaces",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "List Workspaces",
        },
        title="List Workspaces",
    )


class SigmaCreateWorkspaceConfig(BaseModel):
    """Create a workspace."""

    operation: Literal["create_workspace"] = Field(
        "create_workspace",
        json_schema_extra={
            "const": "create_workspace",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Create Workspace",
        },
        title="Create Workspace",
    )
    name: str = Field(..., title="Name", description="Name of the new workspace")


class SigmaAddWorkspaceGrantConfig(BaseModel):
    """Grant a user or team access to a workspace."""

    operation: Literal["add_workspace_grant"] = Field(
        "add_workspace_grant",
        json_schema_extra={
            "const": "add_workspace_grant",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Add Workspace Grant",
        },
        title="Add Workspace Grant",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="The workspace to grant access to")
    grantee_id: str = Field(
        ..., title="Grantee ID", description="Member or team ID receiving the grant"
    )
    grantee_type: str = Field(
        "member",
        title="Grantee Type",
        description="Whether the grant is for a member or a team",
        json_schema_extra={
            "enum": ["member", "team"],
            "enumNames": ["Member", "Team"],
            "x-enum-searchable": True,
        },
    )
    permission: str = Field(
        "view",
        title="Permission",
        description="Access level to grant",
        json_schema_extra={
            "enum": ["view", "edit", "explore"],
            "enumNames": ["View", "Edit", "Explore"],
            "x-enum-searchable": True,
        },
    )


class SigmaGetWorkspaceConfig(BaseModel):
    """Get a single workspace."""

    operation: Literal["get_workspace"] = Field(
        "get_workspace",
        json_schema_extra={
            "const": "get_workspace",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Get Workspace",
        },
        title="Get Workspace",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="The workspace to retrieve")


class SigmaUpdateWorkspaceConfig(BaseModel):
    """Rename a workspace."""

    operation: Literal["update_workspace"] = Field(
        "update_workspace",
        json_schema_extra={
            "const": "update_workspace",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Update Workspace",
        },
        title="Update Workspace",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="The workspace to update")
    name: str = Field(..., title="Name", description="New name for the workspace")


class SigmaDeleteWorkspaceConfig(BaseModel):
    """Permanently delete a workspace."""

    operation: Literal["delete_workspace"] = Field(
        "delete_workspace",
        json_schema_extra={
            "const": "delete_workspace",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Delete Workspace",
        },
        title="Delete Workspace",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="The workspace to delete")


class SigmaListFilesConfig(BaseModel):
    """List folders/documents in the file tree."""

    operation: Literal["list_files"] = Field(
        "list_files",
        json_schema_extra={
            "const": "list_files",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Files",
        },
        title="List Files",
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max files to return (1-1000)"
    )


class SigmaListDataModelsConfig(BaseModel):
    """List data models."""

    operation: Literal["list_data_models"] = Field(
        "list_data_models",
        json_schema_extra={
            "const": "list_data_models",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Data Models",
        },
        title="List Data Models",
    )


class SigmaGetDataModelSpecConfig(BaseModel):
    """Get the as-code representation of a data model."""

    operation: Literal["get_data_model_spec"] = Field(
        "get_data_model_spec",
        json_schema_extra={
            "const": "get_data_model_spec",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "Get Data Model Spec",
        },
        title="Get Data Model Spec",
    )
    data_model_id: str = Field(..., title="Data Model ID", description="The data model to inspect")


class SigmaListAccountTypesConfig(BaseModel):
    """List available account types (license/permission tiers)."""

    operation: Literal["list_account_types"] = Field(
        "list_account_types",
        json_schema_extra={
            "const": "list_account_types",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Account Types",
        },
        title="List Account Types",
    )


class SigmaListApiCredentialsConfig(BaseModel):
    """List the org's API credentials (non-sensitive metadata)."""

    operation: Literal["list_api_credentials"] = Field(
        "list_api_credentials",
        json_schema_extra={
            "const": "list_api_credentials",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List API Credentials",
        },
        title="List API Credentials",
    )


# ============================================================================
# Trigger config (poll-based)
# ============================================================================


class SigmaOnExportCompletedConfig(BaseModel):
    """Poll-based trigger: fires when a workbook materialization/export newly
    completes. Sigma has no outbound webhooks, so a cron tick wakes the node and
    execute() polls the materializations endpoint, deduping on materialization id.
    """

    operation: Literal["on_export_completed"] = Field(
        "on_export_completed",
        title="On Export Completed",
        description="Trigger when a workbook export/materialization finishes",
        json_schema_extra={
            "const": "on_export_completed",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Export Completed",
        },
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="The workbook whose exports/materializations to watch",
        json_schema_extra={
            "x-resource-type": "sigma_workbook",
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a workbook ID",
            }
        },
    )
    status_filter: str = Field(
        "ready",
        title="Status",
        description="Only emit materializations that reached this status",
        json_schema_extra={
            "enum": ["ready", "completed", "failed", "any"],
            "enumNames": ["Ready", "Completed", "Failed", "Any"],
            "x-enum-searchable": True,
        },
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to check for newly completed exports",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    # Hidden cursor: id of the most-recent materialization seen on a prior poll.
    last_seen_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    # Hidden internal fields for webhook/schedule management.
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True, "ui:copyable": True},
    )
    schedule_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    is_active: Optional[bool] = Field(
        default=True,
        json_schema_extra={"ui:hidden": True},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


SigmaConfig = Annotated[
    Union[
        SigmaListWorkbooksConfig,
        SigmaGetWorkbookConfig,
        SigmaCreateWorkbookConfig,
        SigmaUpdateWorkbookConfig,
        SigmaDeleteWorkbookConfig,
        SigmaExportWorkbookConfig,
        SigmaDownloadExportConfig,
        SigmaMaterializeWorkbookConfig,
        SigmaGetWorkbookSourcesConfig,
        SigmaListMembersConfig,
        SigmaGetMemberConfig,
        SigmaCreateMemberConfig,
        SigmaUpdateMemberConfig,
        SigmaDeleteMemberConfig,
        SigmaListTeamsConfig,
        SigmaGetTeamConfig,
        SigmaCreateTeamConfig,
        SigmaUpdateTeamConfig,
        SigmaDeleteTeamConfig,
        SigmaAddTeamMembersConfig,
        SigmaRemoveTeamMemberConfig,
        SigmaListTeamMembersConfig,
        SigmaListConnectionsConfig,
        SigmaGetConnectionConfig,
        SigmaCreateConnectionConfig,
        SigmaTestConnectionConfig,
        SigmaDeleteConnectionConfig,
        SigmaSyncConnectionConfig,
        SigmaListWorkspacesConfig,
        SigmaGetWorkspaceConfig,
        SigmaCreateWorkspaceConfig,
        SigmaUpdateWorkspaceConfig,
        SigmaDeleteWorkspaceConfig,
        SigmaAddWorkspaceGrantConfig,
        SigmaListFilesConfig,
        SigmaListDataModelsConfig,
        SigmaGetDataModelSpecConfig,
        SigmaListAccountTypesConfig,
        SigmaListApiCredentialsConfig,
        SigmaOnExportCompletedConfig,
    ],
    Discriminator("operation"),
]


class SigmaNodeConfig(NodeConfig[SigmaConfig, SigmaCredential]):
    """Full configuration for the Sigma node including credentials."""

    pass


# ============================================================================
# HTTP helpers
# ============================================================================

# In-process token cache: SHA-256(all credential authority) → expiring token
# Tokens are valid 1 hour; we re-use them until 5 minutes before expiry.
_TOKEN_REFRESH_SKEW_SECONDS = 300
_TOKEN_CACHE = OAuthTokenCache(
    refresh_skew_seconds=_TOKEN_REFRESH_SKEW_SECONDS
)


def _sigma_token_cache_key(
    base_url: str, client_id: str, client_secret: str
) -> str:
    return oauth_authority_digest(
        provider="sigma",
        token_url=f"{base_url}/auth/token",
        grant_type="client_credentials",
        client_id=client_id,
        client_secret=client_secret,
    )


async def _sigma_get_token(
    base_url: str, client_id: str, client_secret: str
) -> str:
    """Exchange client credentials for a 1-hour Bearer JWT.

    Caches the token in-process and reuses it until 5 minutes before expiry
    to stay within Sigma's token-generation rate limits.
    Raises RuntimeError on failure so the caller surfaces a structured error.
    """
    cache_key = _sigma_token_cache_key(base_url, client_id, client_secret)
    cached = _TOKEN_CACHE.get(cache_key, now=time.monotonic())
    if cached:
        return cached

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}/auth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        try:
            err = response.json()
            message = err.get("error_description") or err.get("error") or str(err)
        except Exception:
            message = response.text
        raise RuntimeError(f"Sigma token request failed ({response.status_code}): {message}")
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Sigma token response did not include an access_token")
    _TOKEN_CACHE.put(
        cache_key,
        token,
        expires_in=token_expiry_input(payload),
        now=time.monotonic(),
    )
    return token


async def _sigma_request(
    base_url: str,
    token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Sigma v2 request and return a structured result."""
    url = f"{base_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = (
                        err.get("message")
                        or err.get("error")
                        or err.get("detail")
                        or str(err)
                    )
                except Exception:
                    message = response.text
                logger.error(f"[SigmaNode] API error ({action_name}): {message}")
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
                try:
                    data = response.json()
                except Exception:
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
            logger.error(f"[SigmaNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _comma_list(value: Optional[str]) -> Optional[list]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


# ============================================================================
# Node Implementation
# ============================================================================


class SigmaNode(WorkflowNode):
    """Sigma Computing BI automation node."""

    edit_examples = [
        "List all workbooks in my Sigma org",
        "Export a workbook to CSV and download the result",
        "Invite a new member as a Viewer",
        "Create a team and add members to it",
        "Materialize a workbook element on a schedule",
    ]

    @classmethod
    def get_config_model(cls):
        return SigmaNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Sigma trigger is poll-based: the cron POST is a wake-up signal, not
        data. Return None so execute() runs and actually polls the Sigma API."""
        if config.get("operation") == "on_export_completed":
            return None
        return payload

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """Scheduled poll found no newly completed exports → skip downstream."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_export_completed"
            and not output.get("items")
        )

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: uuid_module.UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the internal webhook URL + recurring cron schedule for the
        poll trigger (same pattern as the Gmail trigger)."""
        from utils.webhook_manager import WebhookManager
        from utils.cron_scheduler_client import (
            create_schedule,
            update_schedule,
            is_cron_scheduler_enabled,
        )

        if field_name != "webhook_url":
            return {"value": None}

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        webhook_id = webhook_data.get("webhook_id")
        webhook_url = webhook_data.get("webhook_url")

        schedule = {"frequency": "minutes", "interval": 5}
        if context and context.get("schedule"):
            schedule = context["schedule"]
        cron_expression = schedule_to_cron(schedule)
        logger.info(f"[SigmaNode] Trigger schedule {schedule} -> cron: {cron_expression}")

        existing_schedule_id = context.get("schedule_id") if context else None
        schedule_id = existing_schedule_id
        next_run = None

        if is_cron_scheduler_enabled() and webhook_url:
            if existing_schedule_id:
                result = await update_schedule(
                    schedule_id=existing_schedule_id,
                    cron_expression=cron_expression,
                )
                if result.get("success"):
                    next_run = result.get("next_run")
                elif "error" in result:
                    logger.warning(f"Failed to update schedule: {result['error']}")
                    existing_schedule_id = None

            if not existing_schedule_id:
                result = await create_schedule(
                    user_id=user_id,
                    workflow_id=str(workflow_id),
                    node_id=node_id,
                    cron_expression=cron_expression,
                    webhook_url=webhook_url,
                    payload={"source": "sigma_trigger", "node_id": node_id},
                )
                if "id" in result:
                    schedule_id = result["id"]
                    next_run = result.get("next_run")
                elif "error" in result:
                    logger.warning(f"Failed to create schedule: {result['error']}")

        interval_ms = schedule_to_interval_ms(schedule)

        return {
            "values": {
                "webhook_id": webhook_id,
                "webhook_url": webhook_url,
                "schedule_id": schedule_id,
                "next_run": next_run,
                "interval_ms": interval_ms,
                "is_active": True,
            }
        }

    # ------------------------------------------------------------------
    # Dynamic options (workbooks)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "workbook_id":
            return {"options": []}

        creds = credential_data or {}
        if not creds.get("client_id") or not creds.get("client_secret"):
            return {"options": []}

        base_url = _sigma_base_url(creds.get("region"))
        try:
            token = await _sigma_get_token(
                base_url, creds.get("client_id"), creds.get("client_secret")
            )
        except Exception:
            return {"options": []}

        result = await _sigma_request(
            base_url, token, "GET", "/workbooks", params={"limit": "100"}, action_name="list_workbooks"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        entries = data.get("entries") if isinstance(data, dict) else data
        entries = entries or []
        options = []
        for wb in entries:
            if not isinstance(wb, dict):
                continue
            wb_id = wb.get("workbookId") or wb.get("id")
            name = wb.get("name") or wb.get("workbookId") or f"Workbook {wb_id}"
            if wb_id is not None:
                options.append({"label": str(name), "value": str(wb_id)})
        return {"options": options}

    @classmethod
    async def cleanup_external_webhook(
        cls,
        pool,
        workflow_id: str,
        node_id: str,
        config: Dict[str, Any],
        credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Delete the cron schedule and the internal webhook when trigger is removed."""
        from utils.cron_scheduler_client import delete_schedules_for_nodes

        try:
            await delete_schedules_for_nodes(str(workflow_id), [node_id])
        except Exception as e:
            logger.warning(f"[SigmaNode] Failed to delete cron schedule for node {node_id}: {e}")

        from utils.webhook_manager import WebhookManager
        await WebhookManager.delete_webhook(pool, workflow_id, node_id)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, SigmaNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Sigma API client ID and secret.")

        base_url = _sigma_base_url(credentials.region)
        try:
            token = await _sigma_get_token(
                base_url, credentials.client_id, credentials.client_secret
            )
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            return {
                "status": "error",
                "action": op.operation,
                "error": msg,
                "status_code": 401,
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        handlers = {
            "list_workbooks": self._list_workbooks,
            "get_workbook": self._get_workbook,
            "create_workbook": self._create_workbook,
            "update_workbook": self._update_workbook,
            "delete_workbook": self._delete_workbook,
            "export_workbook": self._export_workbook,
            "download_export": self._download_export,
            "materialize_workbook": self._materialize_workbook,
            "get_workbook_sources": self._get_workbook_sources,
            "list_members": self._list_members,
            "get_member": self._get_member,
            "create_member": self._create_member,
            "update_member": self._update_member,
            "delete_member": self._delete_member,
            "list_teams": self._list_teams,
            "get_team": self._get_team,
            "create_team": self._create_team,
            "update_team": self._update_team,
            "delete_team": self._delete_team,
            "add_team_members": self._add_team_members,
            "remove_team_member": self._remove_team_member,
            "list_team_members": self._list_team_members,
            "list_connections": self._list_connections,
            "get_connection": self._get_connection,
            "create_connection": self._create_connection,
            "test_connection": self._test_connection,
            "delete_connection": self._delete_connection,
            "sync_connection": self._sync_connection,
            "list_workspaces": self._list_workspaces,
            "get_workspace": self._get_workspace,
            "create_workspace": self._create_workspace,
            "update_workspace": self._update_workspace,
            "delete_workspace": self._delete_workspace,
            "add_workspace_grant": self._add_workspace_grant,
            "list_files": self._list_files,
            "list_data_models": self._list_data_models,
            "get_data_model_spec": self._get_data_model_spec,
            "list_account_types": self._list_account_types,
            "list_api_credentials": self._list_api_credentials,
            "on_export_completed": self._on_export_completed,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, base_url, token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Workbook handlers
    # ------------------------------------------------------------------
    async def _list_workbooks(self, c: SigmaListWorkbooksConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/workbooks",
            params={"limit": c.limit, "page": c.page}, action_name="list_workbooks"
        )

    async def _get_workbook(self, c: SigmaGetWorkbookConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/workbooks/{c.workbook_id}", action_name="get_workbook"
        )

    async def _create_workbook(self, c: SigmaCreateWorkbookConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "POST", "/workbooks",
            json_body={"name": c.name, "folderId": c.folder_id}, action_name="create_workbook"
        )

    async def _update_workbook(self, c: SigmaUpdateWorkbookConfig, base_url, token):
        # Sigma uses the Files API for workbook metadata mutations
        return await _sigma_request(
            base_url, token, "PATCH", f"/files/{c.workbook_id}",
            json_body={"name": c.name}, action_name="update_workbook"
        )

    async def _delete_workbook(self, c: SigmaDeleteWorkbookConfig, base_url, token):
        # Sigma uses the Files API for workbook deletion
        return await _sigma_request(
            base_url, token, "DELETE", f"/files/{c.workbook_id}", action_name="delete_workbook"
        )

    async def _export_workbook(self, c: SigmaExportWorkbookConfig, base_url, token):
        fmt: dict = {"type": c.export_format}
        # PDF whole-workbook exports require a layout orientation
        if c.export_format == "pdf":
            fmt["layout"] = "portrait"
        body: dict = {"format": fmt}
        if c.element_id:
            body["elementId"] = c.element_id
        return await _sigma_request(
            base_url, token, "POST", f"/workbooks/{c.workbook_id}/export",
            json_body=body, action_name="export_workbook"
        )

    async def _download_export(self, c: SigmaDownloadExportConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/query/{c.query_id}/download", action_name="download_export"
        )

    async def _materialize_workbook(self, c: SigmaMaterializeWorkbookConfig, base_url, token):
        body = {}
        if c.sheet_id:
            body["sheetId"] = c.sheet_id
        return await _sigma_request(
            base_url, token, "POST", f"/workbooks/{c.workbook_id}/materializations",
            json_body=body, action_name="materialize_workbook"
        )

    async def _get_workbook_sources(self, c: SigmaGetWorkbookSourcesConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/workbooks/{c.workbook_id}/sources",
            action_name="get_workbook_sources"
        )

    # ------------------------------------------------------------------
    # Member handlers
    # ------------------------------------------------------------------
    async def _list_members(self, c: SigmaListMembersConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/members",
            params={"limit": c.limit, "page": c.page}, action_name="list_members"
        )

    async def _get_member(self, c: SigmaGetMemberConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/members/{c.member_id}", action_name="get_member"
        )

    async def _create_member(self, c: SigmaCreateMemberConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "POST", "/members",
            json_body={
                "email": c.email,
                "firstName": c.first_name,
                "lastName": c.last_name,
                "memberType": c.member_type,
            },
            action_name="create_member",
        )

    async def _update_member(self, c: SigmaUpdateMemberConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "PATCH", f"/members/{c.member_id}",
            json_body={
                "firstName": c.first_name,
                "lastName": c.last_name,
                "memberType": c.member_type,
            },
            action_name="update_member",
        )

    async def _delete_member(self, c: SigmaDeleteMemberConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "DELETE", f"/members/{c.member_id}", action_name="delete_member"
        )

    # ------------------------------------------------------------------
    # Team handlers
    # ------------------------------------------------------------------
    async def _list_teams(self, c: SigmaListTeamsConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/teams", params={"limit": c.limit}, action_name="list_teams"
        )

    async def _create_team(self, c: SigmaCreateTeamConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "POST", "/teams",
            json_body={"name": c.name, "description": c.description}, action_name="create_team"
        )

    async def _add_team_members(self, c: SigmaAddTeamMembersConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "PATCH", f"/teams/{c.team_id}/members",
            json_body={"add": _comma_list(c.member_ids)}, action_name="add_team_members"
        )

    async def _remove_team_member(self, c: SigmaRemoveTeamMemberConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "PATCH", f"/teams/{c.team_id}/members",
            json_body={"remove": [c.member_id]}, action_name="remove_team_member"
        )

    async def _get_team(self, c: SigmaGetTeamConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/teams/{c.team_id}", action_name="get_team"
        )

    async def _update_team(self, c: SigmaUpdateTeamConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "PATCH", f"/teams/{c.team_id}",
            json_body={"name": c.name, "description": c.description}, action_name="update_team"
        )

    async def _delete_team(self, c: SigmaDeleteTeamConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "DELETE", f"/teams/{c.team_id}", action_name="delete_team"
        )

    async def _list_team_members(self, c: SigmaListTeamMembersConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/teams/{c.team_id}/members",
            params={"limit": c.limit}, action_name="list_team_members"
        )

    # ------------------------------------------------------------------
    # Connection handlers
    # ------------------------------------------------------------------
    async def _list_connections(self, c: SigmaListConnectionsConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/connections", action_name="list_connections"
        )

    async def _create_connection(self, c: SigmaCreateConnectionConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "POST", "/connections",
            json_body={"name": c.name, "type": c.connection_type}, action_name="create_connection"
        )

    async def _test_connection(self, c: SigmaTestConnectionConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "POST", f"/connections/{c.connection_id}/test",
            action_name="test_connection"
        )

    async def _get_connection(self, c: SigmaGetConnectionConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/connections/{c.connection_id}", action_name="get_connection"
        )

    async def _delete_connection(self, c: SigmaDeleteConnectionConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "DELETE", f"/connections/{c.connection_id}", action_name="delete_connection"
        )

    async def _sync_connection(self, c: SigmaSyncConnectionConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "POST", f"/connections/{c.connection_id}/sync",
            json_body={"path": []}, action_name="sync_connection"
        )

    # ------------------------------------------------------------------
    # Workspace handlers
    # ------------------------------------------------------------------
    async def _list_workspaces(self, c: SigmaListWorkspacesConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/workspaces", action_name="list_workspaces"
        )

    async def _create_workspace(self, c: SigmaCreateWorkspaceConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "POST", "/workspaces",
            json_body={"name": c.name}, action_name="create_workspace"
        )

    async def _add_workspace_grant(self, c: SigmaAddWorkspaceGrantConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "POST", f"/workspaces/{c.workspace_id}/grants",
            json_body={
                "granteeId": c.grantee_id,
                "granteeType": c.grantee_type,
                "permission": c.permission,
            },
            action_name="add_workspace_grant",
        )

    async def _get_workspace(self, c: SigmaGetWorkspaceConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/workspaces/{c.workspace_id}", action_name="get_workspace"
        )

    async def _update_workspace(self, c: SigmaUpdateWorkspaceConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "PATCH", f"/workspaces/{c.workspace_id}",
            json_body={"name": c.name}, action_name="update_workspace"
        )

    async def _delete_workspace(self, c: SigmaDeleteWorkspaceConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "DELETE", f"/workspaces/{c.workspace_id}", action_name="delete_workspace"
        )

    # ------------------------------------------------------------------
    # Catalog handlers
    # ------------------------------------------------------------------
    async def _list_files(self, c: SigmaListFilesConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/files", params={"limit": c.limit}, action_name="list_files"
        )

    async def _list_data_models(self, c: SigmaListDataModelsConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/dataModels", action_name="list_data_models"
        )

    async def _get_data_model_spec(self, c: SigmaGetDataModelSpecConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", f"/dataModels/{c.data_model_id}/spec",
            action_name="get_data_model_spec"
        )

    async def _list_account_types(self, c: SigmaListAccountTypesConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/accountTypes", action_name="list_account_types"
        )

    async def _list_api_credentials(self, c: SigmaListApiCredentialsConfig, base_url, token):
        return await _sigma_request(
            base_url, token, "GET", "/api-credentials", action_name="list_api_credentials"
        )

    # ------------------------------------------------------------------
    # Trigger handler (poll-based)
    # ------------------------------------------------------------------
    @staticmethod
    def _materialization_complete(m: Dict[str, Any], status_filter: str) -> bool:
        """Whether a materialization entry counts as 'newly completed' under the
        configured status filter. Sigma reports status as 'ready'/'completed'/
        'building'/'failed' (terminology varies by API version)."""
        status = str(m.get("status") or m.get("state") or "").lower()
        if status_filter == "any":
            return status in ("ready", "completed", "complete", "failed", "error")
        if status_filter == "failed":
            return status in ("failed", "error")
        # ready / completed both mean "finished successfully"
        return status in ("ready", "completed", "complete")

    async def _on_export_completed(self, c: SigmaOnExportCompletedConfig, base_url, token):
        """Poll the workbook materializations endpoint and emit only the ones
        that newly completed since the last poll, deduping on materialization id.

        The cursor (set of seen materialization ids) is persisted in node state so
        it survives across scheduled runs; the first poll baselines (emits nothing)
        so the trigger only fires for materializations that complete afterwards.
        """
        result = await _sigma_request(
            base_url,
            token,
            "GET",
            f"/workbooks/{c.workbook_id}/materializations",
            params={"limit": "100"},
            action_name="on_export_completed",
        )
        if result.get("status") != "success":
            return result

        data = result.get("data") or {}
        entries = data.get("entries") if isinstance(data, dict) else data
        entries = entries or []

        completed = [
            m
            for m in entries
            if isinstance(m, dict)
            and self._materialization_complete(m, c.status_filter)
        ]

        def _mid(m: Dict[str, Any]) -> Optional[str]:
            mid = m.get("materializationId") or m.get("id") or m.get("queryId")
            return str(mid) if mid is not None else None

        # Materialization ids for completed entries — derived purely from the
        # API response, so a CAS retry of the mutator never re-computes it.
        id_pairs = [(mid, m) for m in completed if (mid := _mid(m)) is not None]
        current_ids = [mid for mid, _ in id_pairs]

        def mutator(state):
            seen_list = state.get("seen_ids", [])
            is_first_poll = "seen_ids" not in state
            seen = set(seen_list)
            if c.last_seen_id:
                seen.add(c.last_seen_id)

            if is_first_poll:
                # Baseline: record the current ids as seen and emit nothing.
                return {"seen_ids": bounded_seen_ids([], current_ids)}, []

            new_items = [m for mid, m in id_pairs if mid not in seen]
            if new_items:
                all_seen = bounded_seen_ids(seen_list, current_ids)
                return {"seen_ids": all_seen}, new_items
            return None, []  # nothing new → no write

        # skip_result: on a transient state blip / lost CAS contention, emit
        # nothing this tick (state untouched) instead of failing the run.
        new_items = await self._update_node_state(mutator, skip_result=[])

        last_seen_id = current_ids[-1] if current_ids else c.last_seen_id

        return {
            "status": "success",
            "operation": "on_export_completed",
            "action": "on_export_completed",
            "workbook_id": c.workbook_id,
            "status_filter": c.status_filter,
            "items": new_items,
            "new_count": len(new_items),
            "last_seen_id": last_seen_id,
        }
