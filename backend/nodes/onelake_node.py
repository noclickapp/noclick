"""
OneLake (Microsoft Fabric) automation node.

Provides workflow integration with Microsoft Fabric OneLake across its three
REST surfaces:
- Filesystem (ADLS Gen2 / DFS): list paths, create directory/file, append,
  flush, read, properties, set metadata, rename, delete, get access control
- Table API (read-only metadata): Iceberg REST Catalog config / namespaces /
  tables and Delta (Unity Catalog) schemas / tables
- Shortcuts & settings (Fabric Core REST API): create / get / list / delete
  shortcuts, reset shortcut cache, read OneLake settings

Authentication: Microsoft Entra ID (Azure AD) OAuth 2.0 bearer token. There is
no API-key / SAS / account-key option for OneLake — it is Entra-only (a single
SaaS with no storage account to sign against). The DFS + Table surfaces require
a token in the Storage audience (`https://storage.azure.com/.default`); the
Fabric Core surface (shortcuts / settings / data-access roles) requires the
Fabric audience (`https://api.fabric.microsoft.com/.default`). A single token
canNOT carry both `aud` claims, so the one Microsoft OAuth credential below
consents to both resources up front (offline_access → refresh token), and at
execute time the node redeems that refresh token ONCE PER AUDIENCE and routes
each request to the matching token by operation (see `_ensure_tokens` +
`FABRIC_AUDIENCE_OPS`). Service principals and managed identities also work
(they need the Fabric tenant setting "Service principals can use Fabric APIs").

API base URLs:
- DFS filesystem: https://onelake.dfs.fabric.microsoft.com
- Blob variant:   https://onelake.blob.fabric.microsoft.com
- Table API:      https://onelake.table.fabric.microsoft.com
- Fabric Core:    https://api.fabric.microsoft.com/v1

Documentation: https://learn.microsoft.com/en-us/fabric/onelake/onelake-access-api
"""

import logging
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft import ONELAKE_SCOPES
from nodes.core.poll_trigger import ScheduledPollTriggerMixin, PollTriggerConfigBase

logger = logging.getLogger(__name__)

# REST surface base URLs (exact hosts from the OneLake access API spec).
ONELAKE_DFS_BASE = "https://onelake.dfs.fabric.microsoft.com"
ONELAKE_BLOB_BASE = "https://onelake.blob.fabric.microsoft.com"
ONELAKE_TABLE_BASE = "https://onelake.table.fabric.microsoft.com"
FABRIC_CORE_BASE = "https://api.fabric.microsoft.com/v1"

# OneLake spans two Entra token audiences that a single token can NOT cover
# (different `aud` claims): the DFS filesystem + Table catalog hosts require a
# Storage-audience token; the Fabric Core host (shortcuts/settings/data-access
# roles) requires the Fabric-audience token. The node redeems the credential's
# refresh token once per audience and routes each request to the right token.
STORAGE_SCOPE = "https://storage.azure.com/.default"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

# Operations whose requests hit api.fabric.microsoft.com (Fabric audience).
# Everything else (DFS filesystem + Table Iceberg/Delta) uses the Storage token.
FABRIC_AUDIENCE_OPS = {
    "create_shortcut",
    "create_shortcuts_bulk",
    "get_shortcut",
    "list_shortcuts",
    "delete_shortcut",
    "reset_shortcut_cache",
    "get_settings",
    "list_data_access_roles",
    "get_data_access_role",
    "create_or_update_data_access_role",
    "delete_data_access_role",
}


# ============================================================================
# Credential Schema
# ============================================================================


class OneLakeOAuthCredential(BaseModel):
    """
    Microsoft Entra ID (Azure AD) OAuth credential for OneLake.

    OneLake has no API-key path: every surface is bearer-token only. Two
    distinct audiences are needed depending on the operation, so both scopes
    are requested up front:
    - Storage audience (`https://storage.azure.com/user_impersonation`) for the
      DFS filesystem and table APIs.
    - Fabric audience (`https://api.fabric.microsoft.com/OneLake.ReadWrite.All`)
      for shortcut + settings management.
    """

    credential_type: Literal["microsoft_onelake_oauth"] = Field(
        "microsoft_onelake_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str = Field(..., description="OAuth refresh token for token renewal")
    expires_at: str = Field(..., description="Token expiry timestamp (ISO 8601)")
    email: str = Field(..., description="Microsoft account email address")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "microsoft",  # Uses centralized Microsoft OAuth
            "x-oauth-scopes": [
                "https://storage.azure.com/user_impersonation",  # DFS + table APIs (Storage audience)
                "https://api.fabric.microsoft.com/OneLake.ReadWrite.All",  # Shortcuts + settings (Fabric audience)
                "offline_access",  # refresh tokens
            ],
            "x-credential-url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
            "x-credential-instructions": "Connect your Microsoft account with access to a Fabric workspace. OneLake uses Microsoft Entra ID (Azure AD) OAuth 2.0; no API key is available.",
        }
    )


OneLakeCredential = OneLakeOAuthCredential


# ============================================================================
# Filesystem (DFS / ADLS Gen2) Operation Configs
# ============================================================================


class OneLakeListPathsConfig(BaseModel):
    """List files and folders under a workspace or item path (DFS filesystem)."""

    operation: Literal["list_paths"] = Field(
        "list_paths",
        json_schema_extra={
            "const": "list_paths",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "List Paths",
        },
        title="List Paths",
    )
    workspace: str = Field(
        ...,
        title="Workspace",
        description="Workspace name or GUID (the OneLake container)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace name / GUID",
            }
        },
    )
    directory: Optional[str] = Field(
        None,
        title="Directory",
        description="Optional directory path to list under (e.g. MyLakehouse.lakehouse/Files)",
    )
    recursive: str = Field(
        "false",
        title="Recursive",
        description="List nested paths recursively",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class OneLakeCreateDirectoryConfig(BaseModel):
    """Create a folder inside a managed item (e.g. a lakehouse Files folder)."""

    operation: Literal["create_directory"] = Field(
        "create_directory",
        json_schema_extra={
            "const": "create_directory",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Create Directory",
        },
        title="Create Directory",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(
        ...,
        title="Item",
        description="Item name with extension (e.g. MyLakehouse.lakehouse) or GUID",
    )
    path: str = Field(
        ...,
        title="Directory Path",
        description="Directory path under the item's Files folder (e.g. reports/2026)",
    )


class OneLakeCreateFileConfig(BaseModel):
    """Create a new (empty) file resource to append to."""

    operation: Literal["create_file"] = Field(
        "create_file",
        json_schema_extra={
            "const": "create_file",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Create File",
        },
        title="Create File",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(
        ...,
        title="File Path",
        description="File path under the item's Files folder (e.g. data/input.csv)",
    )


class OneLakeAppendFileConfig(BaseModel):
    """Upload bytes into a created file at a given offset."""

    operation: Literal["append_file"] = Field(
        "append_file",
        json_schema_extra={
            "const": "append_file",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Append to File",
        },
        title="Append to File",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="File Path", description="File path under the item's Files folder")
    content: str = Field(
        ...,
        title="Content",
        description="Data to append (UTF-8 text)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    position: str = Field(
        "0",
        title="Position",
        description="Byte offset to append at (0 for a new file)",
        json_schema_extra={"type": "number"},
    )


class OneLakeFlushFileConfig(BaseModel):
    """Commit appended bytes, finalizing the upload."""

    operation: Literal["flush_file"] = Field(
        "flush_file",
        json_schema_extra={
            "const": "flush_file",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Flush File",
        },
        title="Flush File",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="File Path", description="File path under the item's Files folder")
    length: str = Field(
        ...,
        title="Length",
        description="Total byte length to commit (the file size after all appends)",
        json_schema_extra={"type": "number"},
    )


class OneLakeReadFileConfig(BaseModel):
    """Download file content."""

    operation: Literal["read_file"] = Field(
        "read_file",
        json_schema_extra={
            "const": "read_file",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Read File",
        },
        title="Read File",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="File Path", description="File path under the item's Files folder")
    byte_range: Optional[str] = Field(
        None,
        title="Range",
        description='Optional HTTP Range for a partial read (e.g. bytes=0-1023)',
    )


class OneLakeGetPropertiesConfig(BaseModel):
    """Return metadata (size, ETag, last-modified) for a file or directory."""

    operation: Literal["get_properties"] = Field(
        "get_properties",
        json_schema_extra={
            "const": "get_properties",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Get Properties",
        },
        title="Get Properties",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="Path", description="File or directory path under the item")


class OneLakeGetAccessControlConfig(BaseModel):
    """Read the Fabric permissions mapped to a POSIX x-ms-acl for a path."""

    operation: Literal["get_access_control"] = Field(
        "get_access_control",
        json_schema_extra={
            "const": "get_access_control",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Get Access Control",
        },
        title="Get Access Control",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="Path", description="File or directory path under the item")


class OneLakeSetPropertiesConfig(BaseModel):
    """Update user-defined x-ms-properties metadata on a path."""

    operation: Literal["set_properties"] = Field(
        "set_properties",
        json_schema_extra={
            "const": "set_properties",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Set Properties",
        },
        title="Set Properties",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="Path", description="File or directory path under the item")
    properties: str = Field(
        ...,
        title="Properties",
        description="Comma-separated base64-encoded name=value pairs (the x-ms-properties value)",
    )


class OneLakeRenamePathConfig(BaseModel):
    """Move or rename a user-created file or folder within allowed paths."""

    operation: Literal["rename_path"] = Field(
        "rename_path",
        json_schema_extra={
            "const": "rename_path",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Rename / Move Path",
        },
        title="Rename / Move Path",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    source_path: str = Field(
        ..., title="Source Path", description="Existing path under the item to move/rename"
    )
    destination_path: str = Field(
        ..., title="Destination Path", description="New path under the item"
    )


class OneLakeDeletePathConfig(BaseModel):
    """Delete a user-created file or folder."""

    operation: Literal["delete_path"] = Field(
        "delete_path",
        json_schema_extra={
            "const": "delete_path",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Delete Path",
        },
        title="Delete Path",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="Path", description="File or directory path under the item")
    recursive: str = Field(
        "true",
        title="Recursive",
        description="Delete directory contents recursively",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Trigger (poll-based) Operation Config
# ============================================================================


class OneLakeOnNewFileConfig(PollTriggerConfigBase):
    """Poll a OneLake path for newly-created files on a schedule.

    OneLake has no native webhook/event-subscription API (see node docstring),
    so this trigger polls the DFS list-paths endpoint and emits only files it
    has not seen before. The schedule/webhook plumbing and the seen-set dedup
    (persisted in node state, not config) come from ``PollTriggerConfigBase`` +
    ``ScheduledPollTriggerMixin``; only the OneLake-specific target fields live
    here.
    """

    operation: Literal["on_new_file"] = Field(
        "on_new_file",
        title="On New File",
        description="Trigger when a new file appears under a OneLake path",
        json_schema_extra={
            "const": "on_new_file",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New File",
        },
    )
    workspace: str = Field(
        ...,
        title="Workspace",
        description="Workspace name or GUID (the OneLake container) to watch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace name / GUID",
            }
        },
    )
    directory: Optional[str] = Field(
        None,
        title="Directory",
        description="Directory path to watch for new files (e.g. MyLakehouse.lakehouse/Files)",
    )
    recursive: str = Field(
        "false",
        title="Recursive",
        description="Watch nested paths recursively",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Table API (read-only metadata) Operation Configs
# ============================================================================


class OneLakeGetIcebergConfigConfig(BaseModel):
    """Get the Iceberg REST Catalog config for an item (returns the prefix)."""

    operation: Literal["get_iceberg_config"] = Field(
        "get_iceberg_config",
        json_schema_extra={
            "const": "get_iceberg_config",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Get Iceberg Config",
        },
        title="Get Iceberg Config",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")


class OneLakeListIcebergNamespacesConfig(BaseModel):
    """List schemas (namespaces) in an item via the Iceberg REST Catalog."""

    operation: Literal["list_iceberg_namespaces"] = Field(
        "list_iceberg_namespaces",
        json_schema_extra={
            "const": "list_iceberg_namespaces",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "List Iceberg Namespaces",
        },
        title="List Iceberg Namespaces",
    )
    prefix: str = Field(
        ...,
        title="Prefix",
        description="The Iceberg catalog prefix returned by Get Iceberg Config",
    )


class OneLakeListIcebergTablesConfig(BaseModel):
    """List tables within a schema via the Iceberg REST Catalog."""

    operation: Literal["list_iceberg_tables"] = Field(
        "list_iceberg_tables",
        json_schema_extra={
            "const": "list_iceberg_tables",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "List Iceberg Tables",
        },
        title="List Iceberg Tables",
    )
    prefix: str = Field(..., title="Prefix", description="Iceberg catalog prefix")
    schema_name: str = Field(
        ..., title="Schema", description="Namespace / schema (e.g. dbo)"
    )


class OneLakeGetIcebergTableConfig(BaseModel):
    """Load Iceberg table metadata."""

    operation: Literal["get_iceberg_table"] = Field(
        "get_iceberg_table",
        json_schema_extra={
            "const": "get_iceberg_table",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Get Iceberg Table",
        },
        title="Get Iceberg Table",
    )
    prefix: str = Field(..., title="Prefix", description="Iceberg catalog prefix")
    schema_name: str = Field(..., title="Schema", description="Namespace / schema")
    table: str = Field(..., title="Table", description="Table name")


class OneLakeListDeltaSchemasConfig(BaseModel):
    """List schemas via the Unity Catalog-compatible Delta API."""

    operation: Literal["list_delta_schemas"] = Field(
        "list_delta_schemas",
        json_schema_extra={
            "const": "list_delta_schemas",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "List Delta Schemas",
        },
        title="List Delta Schemas",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")


class OneLakeListDeltaTablesConfig(BaseModel):
    """List Delta tables in a schema (Unity Catalog API)."""

    operation: Literal["list_delta_tables"] = Field(
        "list_delta_tables",
        json_schema_extra={
            "const": "list_delta_tables",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "List Delta Tables",
        },
        title="List Delta Tables",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    schema_name: str = Field(..., title="Schema", description="Schema name")


class OneLakeGetDeltaTableConfig(BaseModel):
    """Get Delta table metadata details (Unity Catalog API)."""

    operation: Literal["get_delta_table"] = Field(
        "get_delta_table",
        json_schema_extra={
            "const": "get_delta_table",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Get Delta Table",
        },
        title="Get Delta Table",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    full_name: str = Field(
        ...,
        title="Table Full Name",
        description="Three-part Delta table name (catalog.schema.table)",
    )


# ============================================================================
# Shortcuts & Settings (Fabric Core REST API) Operation Configs
# ============================================================================


class OneLakeCreateShortcutConfig(BaseModel):
    """Create a shortcut to OneLake, ADLS Gen2, S3, GCS, Blob, Dataverse, etc."""

    operation: Literal["create_shortcut"] = Field(
        "create_shortcut",
        json_schema_extra={
            "const": "create_shortcut",
            "ui:hidden": True,
            "x-category": "Shortcuts",
            "x-is-trigger": False,
            "x-display-name": "Create Shortcut",
        },
        title="Create Shortcut",
    )
    workspace_id: str = Field(
        ..., title="Workspace ID", description="Fabric workspace GUID"
    )
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    name: str = Field(..., title="Shortcut Name", description="Name of the new shortcut")
    path: str = Field(
        ...,
        title="Path",
        description="Path inside the item where the shortcut is created (e.g. Tables or Files)",
    )
    target: str = Field(
        ...,
        title="Target",
        description="JSON object describing the shortcut target (e.g. OneLake / AdlsGen2 target definition)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    conflict_policy: Optional[str] = Field(
        None,
        title="Conflict Policy",
        description="How to handle a name conflict",
        json_schema_extra={
            "enum": ["", "Abort", "GenerateUniqueName"],
            "enumNames": ["Default", "Abort", "Generate Unique Name"],
            "x-enum-searchable": True,
        },
    )


class OneLakeGetShortcutConfig(BaseModel):
    """Retrieve a single shortcut definition."""

    operation: Literal["get_shortcut"] = Field(
        "get_shortcut",
        json_schema_extra={
            "const": "get_shortcut",
            "ui:hidden": True,
            "x-category": "Shortcuts",
            "x-is-trigger": False,
            "x-display-name": "Get Shortcut",
        },
        title="Get Shortcut",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    shortcut_path: str = Field(
        ..., title="Shortcut Path", description="Path of the shortcut within the item"
    )
    shortcut_name: str = Field(..., title="Shortcut Name", description="Name of the shortcut")


class OneLakeListShortcutsConfig(BaseModel):
    """List all shortcuts in an item."""

    operation: Literal["list_shortcuts"] = Field(
        "list_shortcuts",
        json_schema_extra={
            "const": "list_shortcuts",
            "ui:hidden": True,
            "x-category": "Shortcuts",
            "x-is-trigger": False,
            "x-display-name": "List Shortcuts",
        },
        title="List Shortcuts",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    continuation_token: Optional[str] = Field(
        None, title="Continuation Token", description="Token for the next page of results"
    )


class OneLakeDeleteShortcutConfig(BaseModel):
    """Delete a shortcut (does not delete the target data)."""

    operation: Literal["delete_shortcut"] = Field(
        "delete_shortcut",
        json_schema_extra={
            "const": "delete_shortcut",
            "ui:hidden": True,
            "x-category": "Shortcuts",
            "x-is-trigger": False,
            "x-display-name": "Delete Shortcut",
        },
        title="Delete Shortcut",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    shortcut_path: str = Field(
        ..., title="Shortcut Path", description="Path of the shortcut within the item"
    )
    shortcut_name: str = Field(..., title="Shortcut Name", description="Name of the shortcut")


class OneLakeResetShortcutCacheConfig(BaseModel):
    """Clear cached files for shortcuts in the workspace."""

    operation: Literal["reset_shortcut_cache"] = Field(
        "reset_shortcut_cache",
        json_schema_extra={
            "const": "reset_shortcut_cache",
            "ui:hidden": True,
            "x-category": "Shortcuts",
            "x-is-trigger": False,
            "x-display-name": "Reset Shortcut Cache",
        },
        title="Reset Shortcut Cache",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")


class OneLakeGetSettingsConfig(BaseModel):
    """Read workspace-level OneLake settings (Fabric Core)."""

    operation: Literal["get_settings"] = Field(
        "get_settings",
        json_schema_extra={
            "const": "get_settings",
            "ui:hidden": True,
            "x-category": "Settings",
            "x-is-trigger": False,
            "x-display-name": "Get OneLake Settings",
        },
        title="Get OneLake Settings",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")


class OneLakeCheckAccessConfig(BaseModel):
    """Check whether the caller has r/w/x access to a path (no data read)."""

    operation: Literal["check_access"] = Field(
        "check_access",
        json_schema_extra={
            "const": "check_access",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Check Access",
        },
        title="Check Access",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="Path", description="File or directory path under the item")
    fs_action: str = Field(
        "rwx",
        title="Access to Check",
        description="POSIX access bits to test",
        json_schema_extra={
            "enum": ["r--", "-w-", "--x", "rw-", "r-x", "rwx"],
            "enumNames": ["Read", "Write", "Execute", "Read/Write", "Read/Execute", "Read/Write/Execute"],
            "x-enum-searchable": True,
        },
    )


class OneLakeLeasePathConfig(BaseModel):
    """Acquire, renew, change, release, or break a lease on a file (concurrency)."""

    operation: Literal["lease_path"] = Field(
        "lease_path",
        json_schema_extra={
            "const": "lease_path",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "Lease Path",
        },
        title="Lease Path",
    )
    workspace: str = Field(..., title="Workspace", description="Workspace name or GUID")
    item: str = Field(..., title="Item", description="Item name with extension or GUID")
    path: str = Field(..., title="Path", description="File path under the item")
    lease_action: str = Field(
        ...,
        title="Lease Action",
        description="The lease operation to perform",
        json_schema_extra={
            "enum": ["acquire", "renew", "change", "release", "break"],
            "enumNames": ["Acquire", "Renew", "Change", "Release", "Break"],
            "x-enum-searchable": True,
        },
    )
    lease_id: Optional[str] = Field(
        None, title="Lease ID", description="Existing lease GUID (renew/change/release/break)"
    )
    proposed_lease_id: Optional[str] = Field(
        None, title="Proposed Lease ID", description="New lease GUID (acquire/change)"
    )
    duration: Optional[int] = Field(
        -1, title="Duration (s)", description="Lease duration for acquire: 15-60, or -1 for infinite"
    )


class OneLakeListBlobsConfig(BaseModel):
    """List blobs under a workspace container via the Blob endpoint (flat/prefix)."""

    operation: Literal["list_blobs"] = Field(
        "list_blobs",
        json_schema_extra={
            "const": "list_blobs",
            "ui:hidden": True,
            "x-category": "Filesystem",
            "x-is-trigger": False,
            "x-display-name": "List Blobs",
        },
        title="List Blobs",
    )
    workspace: str = Field(
        ...,
        title="Workspace",
        description="Workspace name or GUID (the OneLake container)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace name / GUID",
            }
        },
    )
    prefix: Optional[str] = Field(
        None, title="Prefix", description="Only list blobs whose name starts with this prefix"
    )
    delimiter: Optional[str] = Field(
        "/", title="Delimiter", description="Group blobs by delimiter (blank = flat listing)"
    )
    marker: Optional[str] = Field(
        None, title="Marker", description="Continuation marker for the next page"
    )


class OneLakeGetIcebergNamespaceConfig(BaseModel):
    """Load metadata (location, properties) for an Iceberg namespace."""

    operation: Literal["get_iceberg_namespace"] = Field(
        "get_iceberg_namespace",
        json_schema_extra={
            "const": "get_iceberg_namespace",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Get Iceberg Namespace",
        },
        title="Get Iceberg Namespace",
    )
    prefix: str = Field(..., title="Prefix", description="Iceberg catalog prefix")
    schema_name: str = Field(..., title="Namespace", description="Namespace / schema (e.g. dbo)")


class OneLakeCreateShortcutsBulkConfig(BaseModel):
    """Create many shortcuts in one call (Fabric Core bulk shortcut API)."""

    operation: Literal["create_shortcuts_bulk"] = Field(
        "create_shortcuts_bulk",
        json_schema_extra={
            "const": "create_shortcuts_bulk",
            "ui:hidden": True,
            "x-category": "Shortcuts",
            "x-is-trigger": False,
            "x-display-name": "Create Shortcuts (Bulk)",
        },
        title="Create Shortcuts (Bulk)",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    shortcuts: str = Field(
        ...,
        title="Shortcuts",
        description="JSON array of shortcut definitions ({name, path, target}, ...)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    conflict_policy: Optional[str] = Field(
        None,
        title="Conflict Policy",
        description="How to handle name conflicts across the batch",
        json_schema_extra={
            "enum": ["", "Abort", "GenerateUniqueName", "CreateOrOverwrite", "OverwriteOnly"],
            "enumNames": ["Default", "Abort", "Generate Unique Name", "Create or Overwrite", "Overwrite Only"],
            "x-enum-searchable": True,
        },
    )


class OneLakeListDataAccessRolesConfig(BaseModel):
    """List OneLake data access (RBAC) roles for an item — the only API to read them."""

    operation: Literal["list_data_access_roles"] = Field(
        "list_data_access_roles",
        json_schema_extra={
            "const": "list_data_access_roles",
            "ui:hidden": True,
            "x-category": "Data Access",
            "x-is-trigger": False,
            "x-display-name": "List Data Access Roles",
        },
        title="List Data Access Roles",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    continuation_token: Optional[str] = Field(
        None, title="Continuation Token", description="Token for the next page of results"
    )


class OneLakeGetDataAccessRoleConfig(BaseModel):
    """Get a single OneLake data access role's rules and members."""

    operation: Literal["get_data_access_role"] = Field(
        "get_data_access_role",
        json_schema_extra={
            "const": "get_data_access_role",
            "ui:hidden": True,
            "x-category": "Data Access",
            "x-is-trigger": False,
            "x-display-name": "Get Data Access Role",
        },
        title="Get Data Access Role",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    role_name: str = Field(..., title="Role Name", description="Data access role name")


class OneLakeCreateOrUpdateDataAccessRoleConfig(BaseModel):
    """Create or update a single OneLake data access role (the only API to set OneLake perms)."""

    operation: Literal["create_or_update_data_access_role"] = Field(
        "create_or_update_data_access_role",
        json_schema_extra={
            "const": "create_or_update_data_access_role",
            "ui:hidden": True,
            "x-category": "Data Access",
            "x-is-trigger": False,
            "x-display-name": "Create/Update Data Access Role",
        },
        title="Create/Update Data Access Role",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    role_name: str = Field(..., title="Role Name", description="Data access role name")
    definition: str = Field(
        ...,
        title="Role Definition",
        description="JSON role object (decisionRules + members)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    etag: Optional[str] = Field(
        None,
        title="ETag (If-Match)",
        description="Concurrency ETag from a prior list/get; sent as If-Match",
    )


class OneLakeDeleteDataAccessRoleConfig(BaseModel):
    """Delete a OneLake data access role."""

    operation: Literal["delete_data_access_role"] = Field(
        "delete_data_access_role",
        json_schema_extra={
            "const": "delete_data_access_role",
            "ui:hidden": True,
            "x-category": "Data Access",
            "x-is-trigger": False,
            "x-display-name": "Delete Data Access Role",
        },
        title="Delete Data Access Role",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Fabric workspace GUID")
    item_id: str = Field(..., title="Item ID", description="Fabric item GUID")
    role_name: str = Field(..., title="Role Name", description="Data access role name")


# ============================================================================
# Discriminated Union
# ============================================================================


OneLakeConfig = Annotated[
    Union[
        OneLakeListPathsConfig,
        OneLakeCreateDirectoryConfig,
        OneLakeCreateFileConfig,
        OneLakeAppendFileConfig,
        OneLakeFlushFileConfig,
        OneLakeReadFileConfig,
        OneLakeGetPropertiesConfig,
        OneLakeGetAccessControlConfig,
        OneLakeCheckAccessConfig,
        OneLakeLeasePathConfig,
        OneLakeSetPropertiesConfig,
        OneLakeRenamePathConfig,
        OneLakeDeletePathConfig,
        OneLakeListBlobsConfig,
        # Trigger
        OneLakeOnNewFileConfig,
        OneLakeGetIcebergConfigConfig,
        OneLakeListIcebergNamespacesConfig,
        OneLakeGetIcebergNamespaceConfig,
        OneLakeListIcebergTablesConfig,
        OneLakeGetIcebergTableConfig,
        OneLakeListDeltaSchemasConfig,
        OneLakeListDeltaTablesConfig,
        OneLakeGetDeltaTableConfig,
        OneLakeCreateShortcutConfig,
        OneLakeCreateShortcutsBulkConfig,
        OneLakeGetShortcutConfig,
        OneLakeListShortcutsConfig,
        OneLakeDeleteShortcutConfig,
        OneLakeResetShortcutCacheConfig,
        OneLakeGetSettingsConfig,
        OneLakeListDataAccessRolesConfig,
        OneLakeGetDataAccessRoleConfig,
        OneLakeCreateOrUpdateDataAccessRoleConfig,
        OneLakeDeleteDataAccessRoleConfig,
    ],
    Discriminator("operation"),
]


class OneLakeNodeConfig(NodeConfig[OneLakeConfig, OneLakeCredential]):
    """Full configuration for the OneLake node including credentials."""

    pass


# ============================================================================
# HTTP request helper
# ============================================================================


async def _onelake_request(
    access_token: str,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    data: Optional[bytes] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated OneLake/Fabric request and return a structured result.

    OneLake DFS/table responses are not always JSON (HEAD returns headers only,
    GET file returns raw bytes), so non-JSON bodies are surfaced as text plus
    the relevant response headers.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                content=data,
            )
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("error", err) if isinstance(err, dict) else err
                    if isinstance(message, dict):
                        message = message.get("message") or message.get("code") or str(message)
                except Exception:
                    message = response.text or f"HTTP {response.status_code}"
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[OneLakeNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            content_type = response.headers.get("content-type", "")
            if response.status_code == 204 or not response.content:
                data_out: Any = {"success": True, "headers": dict(response.headers)}
            elif "application/json" in content_type:
                try:
                    data_out = response.json()
                except Exception:
                    data_out = {"raw": response.text}
            else:
                data_out = {"raw": response.text, "headers": dict(response.headers)}

            return {
                "status": "success",
                "action": action_name,
                "data": data_out,
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
            logger.error(f"[OneLakeNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _item_files_url(workspace: str, item: str, path: str) -> str:
    """Build a DFS URL rooted at an item's Files folder."""
    path = path.lstrip("/")
    return f"{ONELAKE_DFS_BASE}/{workspace}/{item}/Files/{path}"


# ============================================================================
# Node Implementation
# ============================================================================


class OneLakeNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Microsoft Fabric OneLake automation node (filesystem, tables, shortcuts).

    ScheduledPollTriggerMixin (mixed in before WorkflowNode) owns the poll-trigger
    plumbing for ``on_new_file``: webhook + cron-schedule provisioning via
    ``load_field_value``, ``resolve_trigger_payload`` (the cron POST is a wake-up
    signal), teardown, and the node-state seen-set dedup used by ``_filter_unseen``.
    """

    edit_examples = [
        "List all files under a lakehouse's Files folder",
        "Create a directory and upload a CSV into a OneLake lakehouse",
        "List the Delta tables in a Fabric warehouse",
        "Create a shortcut from a lakehouse to an external S3 bucket",
        "Read the Iceberg metadata for a OneLake table",
    ]

    #: OAuth scope requirements per operation (nodes/scopes/microsoft.py).
    scope_registry = ONELAKE_SCOPES
    connection_evidence = ConnectionEvidence(
        field="workspace",
        noun="workspaces",
    )

    @classmethod
    def get_config_model(cls):
        return OneLakeNodeConfig


    # ------------------------------------------------------------------
    # OAuth token refresh
    # ------------------------------------------------------------------
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Microsoft OAuth token at credential load."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="microsoft",
        )

    async def _ensure_tokens(self, credentials: OneLakeOAuthCredential) -> tuple[str, str]:
        """Return ``(storage_token, fabric_token)`` — one Entra token per OneLake
        audience.

        A single token cannot carry both the ``storage.azure.com`` and
        ``api.fabric.microsoft.com`` ``aud`` claims, so the credential's refresh
        token is redeemed once per audience. The choke point runs first to
        refresh-if-expired + persist any rotated refresh token (CAS-safe); the
        two explicit, scoped mints then guarantee the correct audience for each
        surface regardless of what audience the cached/stored token happened to
        carry.
        """
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token

        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=lambda rt: refresh_access_token(rt, scope=STORAGE_SCOPE),
            provider="microsoft",
            caller_path="execute",
        )
        refresh_token = cred_dict.get("refresh_token") or credentials.refresh_token
        if not refresh_token:
            raise ValueError(
                "OneLake credential is missing a refresh token. Reconnect your "
                "Microsoft account (offline_access is required)."
            )
        credentials.refresh_token = refresh_token
        credentials.access_token = cred_dict.get("access_token")
        credentials.expires_at = cred_dict.get("expires_at")

        storage = await refresh_access_token(refresh_token, scope=STORAGE_SCOPE)
        fabric = await refresh_access_token(refresh_token, scope=FABRIC_SCOPE)
        return storage.access_token, fabric.access_token

    # ------------------------------------------------------------------
    # Dynamic options (workspaces)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Populate the workspace dropdown. credential_data arrives pre-loaded,
        decrypted and freshened by the workflow handler. Workspaces are listed
        via the Fabric Core REST API, so a Fabric-audience token is minted from
        the refresh token (the persisted access token may carry either audience)."""
        if field_name != "workspace":
            return {"options": []}
        refresh_token = (credential_data or {}).get("refresh_token")
        if not refresh_token:
            return {"options": []}
        from nodes.oauth.microsoft_oauth import refresh_access_token

        try:
            fabric = await refresh_access_token(refresh_token, scope=FABRIC_SCOPE)
        except Exception as e:
            logger.warning(f"[OneLakeNode] Failed to mint Fabric token for workspace list: {e}")
            return {"options": []}
        access_token = fabric.access_token
        result = await _onelake_request(
            access_token,
            "GET",
            f"{FABRIC_CORE_BASE}/workspaces",
            action_name="list_workspaces",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        workspaces = data.get("value") if isinstance(data, dict) else data
        options = []
        for ws in workspaces or []:
            if not isinstance(ws, dict):
                continue
            ws_id = ws.get("id")
            name = ws.get("displayName") or ws.get("name") or ws_id
            if name:
                options.append({"label": str(name), "value": str(name)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, OneLakeNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect your Microsoft account.")

        storage_token, fabric_token = await self._ensure_tokens(credentials)
        op = config.config

        handlers = {
            "list_paths": self._list_paths,
            "create_directory": self._create_directory,
            "create_file": self._create_file,
            "append_file": self._append_file,
            "flush_file": self._flush_file,
            "read_file": self._read_file,
            "get_properties": self._get_properties,
            "get_access_control": self._get_access_control,
            "check_access": self._check_access,
            "lease_path": self._lease_path,
            "set_properties": self._set_properties,
            "rename_path": self._rename_path,
            "delete_path": self._delete_path,
            "list_blobs": self._list_blobs,
            "on_new_file": self._poll_new_files,
            "get_iceberg_config": self._get_iceberg_config,
            "list_iceberg_namespaces": self._list_iceberg_namespaces,
            "get_iceberg_namespace": self._get_iceberg_namespace,
            "list_iceberg_tables": self._list_iceberg_tables,
            "get_iceberg_table": self._get_iceberg_table,
            "list_delta_schemas": self._list_delta_schemas,
            "list_delta_tables": self._list_delta_tables,
            "get_delta_table": self._get_delta_table,
            "create_shortcut": self._create_shortcut,
            "create_shortcuts_bulk": self._create_shortcuts_bulk,
            "get_shortcut": self._get_shortcut,
            "list_shortcuts": self._list_shortcuts,
            "delete_shortcut": self._delete_shortcut,
            "reset_shortcut_cache": self._reset_shortcut_cache,
            "get_settings": self._get_settings,
            "list_data_access_roles": self._list_data_access_roles,
            "get_data_access_role": self._get_data_access_role,
            "create_or_update_data_access_role": self._create_or_update_data_access_role,
            "delete_data_access_role": self._delete_data_access_role,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        # Route to the correct-audience token: Fabric Core ops → Fabric token,
        # DFS filesystem + Table catalog ops → Storage token.
        token = fabric_token if op.operation in FABRIC_AUDIENCE_OPS else storage_token
        result = await handler(op, token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Filesystem handlers
    # ------------------------------------------------------------------
    async def _list_paths(self, c: OneLakeListPathsConfig, token: str) -> Dict[str, Any]:
        params = {
            "resource": "filesystem",
            "recursive": c.recursive,
            "directory": c.directory,
        }
        return await _onelake_request(
            token, "GET", f"{ONELAKE_DFS_BASE}/{c.workspace}", params=params,
            action_name="list_paths",
        )

    async def _create_directory(self, c: OneLakeCreateDirectoryConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(
            token, "PUT", url, params={"resource": "directory"},
            action_name="create_directory",
        )

    async def _create_file(self, c: OneLakeCreateFileConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(
            token, "PUT", url, params={"resource": "file"}, action_name="create_file"
        )

    async def _append_file(self, c: OneLakeAppendFileConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(
            token, "PATCH", url,
            params={"action": "append", "position": c.position},
            data=c.content.encode("utf-8"),
            extra_headers={"Content-Type": "application/octet-stream"},
            action_name="append_file",
        )

    async def _flush_file(self, c: OneLakeFlushFileConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(
            token, "PATCH", url,
            params={"action": "flush", "position": c.length},
            action_name="flush_file",
        )

    async def _read_file(self, c: OneLakeReadFileConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        extra = {"Range": c.byte_range} if c.byte_range else None
        return await _onelake_request(
            token, "GET", url, extra_headers=extra, action_name="read_file"
        )

    async def _get_properties(self, c: OneLakeGetPropertiesConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(token, "HEAD", url, action_name="get_properties")

    async def _get_access_control(self, c: OneLakeGetAccessControlConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(
            token, "HEAD", url, params={"action": "getAccessControl"},
            action_name="get_access_control",
        )

    async def _set_properties(self, c: OneLakeSetPropertiesConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(
            token, "PATCH", url,
            params={"action": "setProperties"},
            extra_headers={"x-ms-properties": c.properties},
            action_name="set_properties",
        )

    async def _rename_path(self, c: OneLakeRenamePathConfig, token: str) -> Dict[str, Any]:
        dest_url = _item_files_url(c.workspace, c.item, c.destination_path)
        source = f"/{c.workspace}/{c.item}/Files/{c.source_path.lstrip('/')}"
        return await _onelake_request(
            token, "PUT", dest_url,
            params={"resource": "file"},
            extra_headers={"x-ms-rename-source": source},
            action_name="rename_path",
        )

    async def _delete_path(self, c: OneLakeDeletePathConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(
            token, "DELETE", url, params={"recursive": c.recursive},
            action_name="delete_path",
        )

    async def _check_access(self, c: OneLakeCheckAccessConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        return await _onelake_request(
            token, "HEAD", url,
            params={"action": "checkAccess", "fsAction": c.fs_action},
            action_name="check_access",
        )

    async def _lease_path(self, c: OneLakeLeasePathConfig, token: str) -> Dict[str, Any]:
        url = _item_files_url(c.workspace, c.item, c.path)
        headers = {"x-ms-lease-action": c.lease_action}
        if c.lease_id:
            headers["x-ms-lease-id"] = c.lease_id
        if c.proposed_lease_id:
            headers["x-ms-proposed-lease-id"] = c.proposed_lease_id
        if c.lease_action == "acquire":
            headers["x-ms-lease-duration"] = str(c.duration if c.duration is not None else -1)
        return await _onelake_request(
            token, "POST", url, params={"comp": "lease"},
            extra_headers=headers, action_name="lease_path",
        )

    async def _list_blobs(self, c: OneLakeListBlobsConfig, token: str) -> Dict[str, Any]:
        params = {
            "restype": "container",
            "comp": "list",
            "prefix": c.prefix,
            "delimiter": c.delimiter,
            "marker": c.marker,
        }
        return await _onelake_request(
            token, "GET", f"{ONELAKE_BLOB_BASE}/{c.workspace}", params=params,
            action_name="list_blobs",
        )

    # ------------------------------------------------------------------
    # Trigger handler (poll-based)
    # ------------------------------------------------------------------
    async def _poll_new_files(self, c: OneLakeOnNewFileConfig, token: str) -> Dict[str, Any]:
        """Poll the DFS list-paths endpoint and emit only newly-created files.

        Dedup is delegated to ``ScheduledPollTriggerMixin._filter_unseen``, which
        keeps the seen-path set in node state (not config): the first poll after
        the trigger is created baselines silently, and only files that appear
        afterwards fire downstream. Directories are ignored — only files count.
        """
        params = {
            "resource": "filesystem",
            "recursive": c.recursive,
            "directory": c.directory,
        }
        result = await _onelake_request(
            token, "GET", f"{ONELAKE_DFS_BASE}/{c.workspace}", params=params,
            action_name="on_new_file",
        )
        if result.get("status") != "success":
            return result

        data = result.get("data") or {}
        raw_paths = data.get("paths") if isinstance(data, dict) else None
        files = []
        for p in raw_paths or []:
            if not isinstance(p, dict):
                continue
            # DFS marks directories with isDirectory == "true" (string).
            if str(p.get("isDirectory", "")).lower() == "true":
                continue
            if p.get("name"):
                files.append(p)

        new_files = await self._filter_unseen(files, lambda f: f.get("name"))

        return {
            "status": "success",
            "operation": "on_new_file",
            "workspace": c.workspace,
            "directory": c.directory,
            "new_count": len(new_files),
            "items": new_files,
            "timestamp": time.time(),
        }

    # ------------------------------------------------------------------
    # Table API handlers
    # ------------------------------------------------------------------
    async def _get_iceberg_config(self, c: OneLakeGetIcebergConfigConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET", f"{ONELAKE_TABLE_BASE}/iceberg/v1/config",
            params={"warehouse": f"{c.workspace}/{c.item}"},
            action_name="get_iceberg_config",
        )

    async def _list_iceberg_namespaces(self, c: OneLakeListIcebergNamespacesConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{ONELAKE_TABLE_BASE}/iceberg/v1/{c.prefix}/namespaces",
            action_name="list_iceberg_namespaces",
        )

    async def _get_iceberg_namespace(self, c: OneLakeGetIcebergNamespaceConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{ONELAKE_TABLE_BASE}/iceberg/v1/{c.prefix}/namespaces/{c.schema_name}",
            action_name="get_iceberg_namespace",
        )

    async def _list_iceberg_tables(self, c: OneLakeListIcebergTablesConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{ONELAKE_TABLE_BASE}/iceberg/v1/{c.prefix}/namespaces/{c.schema_name}/tables",
            action_name="list_iceberg_tables",
        )

    async def _get_iceberg_table(self, c: OneLakeGetIcebergTableConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{ONELAKE_TABLE_BASE}/iceberg/v1/{c.prefix}/namespaces/{c.schema_name}/tables/{c.table}",
            action_name="get_iceberg_table",
        )

    async def _list_delta_schemas(self, c: OneLakeListDeltaSchemasConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{ONELAKE_TABLE_BASE}/delta/{c.workspace}/{c.item}/api/2.1/unity-catalog/schemas",
            params={"catalog_name": c.item},
            action_name="list_delta_schemas",
        )

    async def _list_delta_tables(self, c: OneLakeListDeltaTablesConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{ONELAKE_TABLE_BASE}/delta/{c.workspace}/{c.item}/api/2.1/unity-catalog/tables",
            params={"catalog_name": c.item, "schema_name": c.schema_name},
            action_name="list_delta_tables",
        )

    async def _get_delta_table(self, c: OneLakeGetDeltaTableConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{ONELAKE_TABLE_BASE}/delta/{c.workspace}/{c.item}/api/2.1/unity-catalog/tables/{c.full_name}",
            action_name="get_delta_table",
        )

    # ------------------------------------------------------------------
    # Shortcut & settings handlers (Fabric Core REST API)
    # ------------------------------------------------------------------
    async def _create_shortcut(self, c: OneLakeCreateShortcutConfig, token: str) -> Dict[str, Any]:
        import json as _json

        try:
            target = _json.loads(c.target)
        except Exception as e:
            return {
                "status": "error",
                "action": "create_shortcut",
                "error": f"Target must be valid JSON: {e}",
                "status_code": 400,
            }
        body = {"name": c.name, "path": c.path, "target": target}
        params = {"shortcutConflictPolicy": c.conflict_policy} if c.conflict_policy else None
        return await _onelake_request(
            token, "POST",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/shortcuts",
            params=params, json_body=body, action_name="create_shortcut",
        )

    async def _create_shortcuts_bulk(self, c: OneLakeCreateShortcutsBulkConfig, token: str) -> Dict[str, Any]:
        import json as _json

        try:
            shortcuts = _json.loads(c.shortcuts)
        except Exception as e:
            return {
                "status": "error",
                "action": "create_shortcuts_bulk",
                "error": f"Shortcuts must be a valid JSON array: {e}",
                "status_code": 400,
            }
        body = {"createShortcutRequests": shortcuts}
        params = {"shortcutConflictPolicy": c.conflict_policy} if c.conflict_policy else None
        return await _onelake_request(
            token, "POST",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/shortcuts/bulkCreate",
            params=params, json_body=body, action_name="create_shortcuts_bulk",
        )

    async def _get_shortcut(self, c: OneLakeGetShortcutConfig, token: str) -> Dict[str, Any]:
        path = c.shortcut_path.strip("/")
        return await _onelake_request(
            token, "GET",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/shortcuts/{path}/{c.shortcut_name}",
            action_name="get_shortcut",
        )

    async def _list_shortcuts(self, c: OneLakeListShortcutsConfig, token: str) -> Dict[str, Any]:
        params = {"continuationToken": c.continuation_token} if c.continuation_token else None
        return await _onelake_request(
            token, "GET",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/shortcuts",
            params=params, action_name="list_shortcuts",
        )

    async def _delete_shortcut(self, c: OneLakeDeleteShortcutConfig, token: str) -> Dict[str, Any]:
        path = c.shortcut_path.strip("/")
        return await _onelake_request(
            token, "DELETE",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/shortcuts/{path}/{c.shortcut_name}",
            action_name="delete_shortcut",
        )

    async def _reset_shortcut_cache(self, c: OneLakeResetShortcutCacheConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "POST",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/onelake/resetShortcutCache",
            action_name="reset_shortcut_cache",
        )

    async def _get_settings(self, c: OneLakeGetSettingsConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/onelake/settings",
            action_name="get_settings",
        )

    # ------------------------------------------------------------------
    # Data access security (RBAC) handlers — the ONLY API to manage OneLake
    # permissions (ADLS setAccessControl is blocked by OneLake). Fabric Core.
    # ------------------------------------------------------------------
    async def _list_data_access_roles(self, c: OneLakeListDataAccessRolesConfig, token: str) -> Dict[str, Any]:
        params = {"continuationToken": c.continuation_token} if c.continuation_token else None
        return await _onelake_request(
            token, "GET",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/dataAccessRoles",
            params=params, action_name="list_data_access_roles",
        )

    async def _get_data_access_role(self, c: OneLakeGetDataAccessRoleConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "GET",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/dataAccessRoles/{c.role_name}",
            action_name="get_data_access_role",
        )

    async def _create_or_update_data_access_role(
        self, c: OneLakeCreateOrUpdateDataAccessRoleConfig, token: str
    ) -> Dict[str, Any]:
        import json as _json

        try:
            definition = _json.loads(c.definition)
        except Exception as e:
            return {
                "status": "error",
                "action": "create_or_update_data_access_role",
                "error": f"Role definition must be valid JSON: {e}",
                "status_code": 400,
            }
        headers = {"If-Match": c.etag} if c.etag else None
        return await _onelake_request(
            token, "PUT",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/dataAccessRoles/{c.role_name}",
            json_body=definition, extra_headers=headers,
            action_name="create_or_update_data_access_role",
        )

    async def _delete_data_access_role(self, c: OneLakeDeleteDataAccessRoleConfig, token: str) -> Dict[str, Any]:
        return await _onelake_request(
            token, "DELETE",
            f"{FABRIC_CORE_BASE}/workspaces/{c.workspace_id}/items/{c.item_id}/dataAccessRoles/{c.role_name}",
            action_name="delete_data_access_role",
        )
