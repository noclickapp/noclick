"""
Airtable REST API automation node.

Provides workflow integration with Airtable for operations including:
- Base Operations: list bases, get schema, create/update tables, create/update fields
- Record Operations: list, get, create, update, delete records (single and batch)
- Comment Operations: list, create, update, delete comments on records
- Webhook Operations: list, create, delete webhooks, list payloads, refresh

Authentication: Personal Access Token (PAT) or OAuth 2.0
API Base URL: https://api.airtable.com/v0
Documentation: https://airtable.com/developers/web/api/introduction
Rate Limit: 5 requests per second per base
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.airtable_oauth import is_token_expired, refresh_access_token
from nodes.scopes.airtable import AIRTABLE_SCOPES

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

AIRTABLE_API_BASE = "https://api.airtable.com/v0"

# ============================================================================
# Credential Schema
# ============================================================================


class AirtablePATCredential(BaseModel):
    """
    Personal Access Token credential for Airtable.

    Get your PAT at: https://airtable.com/create/tokens
    """

    credential_type: Literal["airtable_pat"] = Field(
        "airtable_pat", json_schema_extra={"ui:hidden": True}
    )
    personal_access_token: str = Field(
        ...,
        title="Personal Access Token",
        description="Your Airtable Personal Access Token (PAT)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://airtable.com/create/tokens"}
    )


class AirtableOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for Airtable.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://airtable.com/create/oauth
    """

    credential_type: Literal["airtable_oauth"] = Field(
        "airtable_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Airtable"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: Optional[str] = Field(
        None,
        title="Account Email",
        description="Email address of the connected Airtable account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "airtable",
            "x-oauth-scopes": [
                "data.records:read",
                "data.records:write",
                "data.recordComments:read",
                "data.recordComments:write",
                "schema.bases:read",
                "schema.bases:write",
                "webhook:manage",
            ],
        }
    )


# Union type for credentials - supports both PAT and OAuth
AirtableCredential = Union[AirtablePATCredential, AirtableOAuthCredential]


# ============================================================================
# Base/Meta Operation Configs
# ============================================================================


class AirtableListBasesConfig(BaseModel):
    """List all accessible bases"""

    operation: Literal["list_accessible_bases"] = Field(
        "list_accessible_bases",
        json_schema_extra={
            "const": "list_accessible_bases",
            "ui:hidden": True,
            "x-category": "Base",
            "x-is-trigger": False,
            "x-display-name": "List Accessible Bases",
            "x-keywords": [
                "my bases",
                "list bases",
                "available bases",
                "workspace bases",
                "show bases",
            ],
        },
        title="List Accessible Bases",
    )
    offset: Optional[str] = Field(
        None, title="Offset", description="Pagination offset from previous response"
    )


class AirtableGetBaseSchemaConfig(BaseModel):
    """Get the schema (tables and fields) of a base"""

    operation: Literal["fetch_base_schema"] = Field(
        "fetch_base_schema",
        json_schema_extra={
            "const": "fetch_base_schema",
            "ui:hidden": True,
            "x-category": "Base",
            "x-is-trigger": False,
            "x-display-name": "Fetch Base Schema",
            "x-keywords": [
                "base schema",
                "tables and fields",
                "base structure",
                "list tables",
                "schema of base",
            ],
        },
        title="Fetch Base Schema",
    )
    base_id: str = Field(
        ..., title="Base ID", description="The ID of the base (starts with 'app')"
    )


class AirtableCreateTableConfig(BaseModel):
    """Create a new table in a base"""

    operation: Literal["create_new_table"] = Field(
        "create_new_table",
        json_schema_extra={
            "const": "create_new_table",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Create New Table",
            "x-keywords": [
                "new table",
                "add table",
                "make table",
                "create table in base",
            ],
        },
        title="Create New Table",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    name: str = Field(..., title="Table Name", description="Name for the new table")
    description: Optional[str] = Field(
        None, title="Description", description="Description of the table"
    )
    fields: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Fields",
        description="Array of field definitions [{name, type, options}]",
    )


class AirtableUpdateTableConfig(BaseModel):
    """Update a table's name or description"""

    operation: Literal["update_table_metadata"] = Field(
        "update_table_metadata",
        json_schema_extra={
            "const": "update_table_metadata",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Update Table Metadata",
            "x-keywords": [
                "rename table",
                "table name",
                "table description",
                "edit table",
            ],
        },
        title="Update Table Metadata",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id: str = Field(
        ..., title="Table ID", description="The ID of the table to update"
    )
    name: Optional[str] = Field(
        None, title="Name", description="New name for the table"
    )
    description: Optional[str] = Field(
        None, title="Description", description="New description for the table"
    )


class AirtableCreateFieldConfig(BaseModel):
    """Create a new field in a table"""

    operation: Literal["create_table_field"] = Field(
        "create_table_field",
        json_schema_extra={
            "const": "create_table_field",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Create Table Field",
            "x-keywords": [
                "add field",
                "new column",
                "add column",
                "create field",
                "new field",
            ],
        },
        title="Create Table Field",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id: str = Field(..., title="Table ID", description="The ID of the table")
    name: str = Field(..., title="Field Name", description="Name for the new field")
    field_type: str = Field(
        ...,
        title="Field Type",
        description="Type of field (singleLineText, multilineText, number, checkbox, etc.)",
        json_schema_extra={
            "enum": [
                "singleLineText",
                "email",
                "url",
                "multilineText",
                "number",
                "percent",
                "currency",
                "singleSelect",
                "multipleSelects",
                "singleCollaborator",
                "multipleCollaborators",
                "multipleRecordLinks",
                "date",
                "dateTime",
                "phoneNumber",
                "multipleAttachments",
                "checkbox",
                "formula",
                "createdTime",
                "rollup",
                "count",
                "lookup",
                "multipleLookupValues",
                "autoNumber",
                "barcode",
                "rating",
                "richText",
                "duration",
                "lastModifiedTime",
                "button",
                "createdBy",
                "lastModifiedBy",
                "externalSyncSource",
            ]
        },
    )
    description: Optional[str] = Field(
        None, title="Description", description="Description of the field"
    )
    options: Optional[Dict[str, Any]] = Field(
        None,
        title="Options",
        description="Field type-specific options (e.g., choices for select fields)",
    )


class AirtableUpdateFieldConfig(BaseModel):
    """Update a field's name or description"""

    operation: Literal["update_table_field"] = Field(
        "update_table_field",
        json_schema_extra={
            "const": "update_table_field",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Update Table Field",
            "x-keywords": [
                "rename field",
                "edit field",
                "rename column",
                "field name",
                "modify column",
            ],
        },
        title="Update Table Field",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id: str = Field(..., title="Table ID", description="The ID of the table")
    field_id: str = Field(
        ..., title="Field ID", description="The ID of the field to update"
    )
    name: Optional[str] = Field(
        None, title="Name", description="New name for the field"
    )
    description: Optional[str] = Field(
        None, title="Description", description="New description for the field"
    )


# ============================================================================
# Record Operation Configs
# ============================================================================


class AirtableListRecordsConfig(BaseModel):
    """List records from a table with filtering, sorting, and pagination"""

    operation: Literal["list_table_records"] = Field(
        "list_table_records",
        json_schema_extra={
            "const": "list_table_records",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "List Table Records",
            "x-keywords": [
                "list records",
                "get rows",
                "query records",
                "filter records",
                "fetch rows",
                "search records",
            ],
        },
        title="List Table Records",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    view: Optional[str] = Field(
        None, title="View", description="View ID or name to filter records"
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Number of records per page (max 100)",
        ge=1,
        le=100,
    )
    offset: Optional[str] = Field(
        None, title="Offset", description="Pagination offset from previous response"
    )
    filter_by_formula: Optional[str] = Field(
        None,
        title="Filter Formula",
        description="Airtable formula to filter records (e.g., {Status}='Active')",
    )
    sort_field: Optional[str] = Field(
        None, title="Sort Field", description="Field name to sort by"
    )
    sort_direction: Optional[str] = Field(
        "asc",
        title="Sort Direction",
        description="Sort direction",
        json_schema_extra={"enum": ["asc", "desc"]},
    )
    fields: Optional[List[str]] = Field(
        None, title="Fields", description="List of field names to include in response"
    )
    max_records: Optional[int] = Field(
        None, title="Max Records", description="Maximum total records to return"
    )
    cell_format: Optional[str] = Field(
        "json",
        title="Cell Format",
        description="Format for cell values",
        json_schema_extra={"enum": ["json", "string"]},
    )
    time_zone: Optional[str] = Field(
        None,
        title="Time Zone",
        description="Time zone for date/time fields (e.g., 'America/New_York')",
    )
    user_locale: Optional[str] = Field(
        None, title="User Locale", description="Locale for formatting (e.g., 'en-us')"
    )


class AirtableGetRecordConfig(BaseModel):
    """Get a single record by ID"""

    operation: Literal["fetch_single_record"] = Field(
        "fetch_single_record",
        json_schema_extra={
            "const": "fetch_single_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Fetch Single Record",
            "x-keywords": [
                "get record",
                "single record",
                "one record",
                "record by id",
                "fetch one row",
            ],
        },
        title="Fetch Single Record",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    record_id: str = Field(
        ..., title="Record ID", description="The ID of the record (starts with 'rec')"
    )
    cell_format: Optional[str] = Field(
        "json",
        title="Cell Format",
        description="Format for cell values",
        json_schema_extra={"enum": ["json", "string"]},
    )


class AirtableCreateRecordsConfig(BaseModel):
    """Create one or more records (batch create up to 10)"""

    operation: Literal["create_multiple_records"] = Field(
        "create_multiple_records",
        json_schema_extra={
            "const": "create_multiple_records",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Create Multiple Records",
            "x-keywords": [
                "create records",
                "batch create",
                "add rows",
                "insert records",
                "bulk add records",
                "add multiple rows",
            ],
        },
        title="Create Multiple Records",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    records: List[Dict[str, Any]] = Field(
        ...,
        title="Records",
        description="Array of records to create [{fields: {Field1: 'value1', ...}}]. Max 10 per request.",
    )
    typecast: Optional[bool] = Field(
        False,
        title="Typecast",
        description="Automatically convert strings to appropriate types",
    )
    return_fields_by_field_id: Optional[bool] = Field(
        False,
        title="Return Fields by ID",
        description="Return field values keyed by field ID instead of name",
    )


class AirtableUpdateRecordsConfig(BaseModel):
    """Update one or more records (batch update up to 10)"""

    operation: Literal["update_multiple_records"] = Field(
        "update_multiple_records",
        json_schema_extra={
            "const": "update_multiple_records",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Update Multiple Records",
            "x-keywords": [
                "update records",
                "batch update",
                "bulk update",
                "edit multiple rows",
                "update many records",
            ],
        },
        title="Update Multiple Records",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    records: List[Dict[str, Any]] = Field(
        ...,
        title="Records",
        description="Array of records to update [{id: 'recXXX', fields: {...}}]. Max 10 per request.",
    )
    typecast: Optional[bool] = Field(
        False,
        title="Typecast",
        description="Automatically convert strings to appropriate types",
    )
    return_fields_by_field_id: Optional[bool] = Field(
        False,
        title="Return Fields by ID",
        description="Return field values keyed by field ID instead of name",
    )


class AirtableUpdateRecordConfig(BaseModel):
    """Update a single record by ID"""

    operation: Literal["update_single_record"] = Field(
        "update_single_record",
        json_schema_extra={
            "const": "update_single_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Update Single Record",
            "x-keywords": [
                "update record",
                "edit one row",
                "single record update",
                "change record",
                "update one record",
            ],
        },
        title="Update Single Record",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    record_id: str = Field(
        ..., title="Record ID", description="The ID of the record to update"
    )
    fields: Dict[str, Any] = Field(
        ...,
        title="Fields",
        description="Field values to update {Field1: 'value1', ...}",
    )
    typecast: Optional[bool] = Field(
        False,
        title="Typecast",
        description="Automatically convert strings to appropriate types",
    )


class AirtableDeleteRecordsConfig(BaseModel):
    """Delete one or more records (batch delete up to 10)"""

    operation: Literal["delete_multiple_records"] = Field(
        "delete_multiple_records",
        json_schema_extra={
            "const": "delete_multiple_records",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Delete Multiple Records",
            "x-keywords": [
                "delete records",
                "batch delete",
                "bulk delete",
                "remove rows",
                "delete many records",
            ],
        },
        title="Delete Multiple Records",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    record_ids: List[str] = Field(
        ...,
        title="Record IDs",
        description="Array of record IDs to delete. Max 10 per request.",
    )


class AirtableDeleteRecordConfig(BaseModel):
    """Delete a single record by ID"""

    operation: Literal["delete_single_record"] = Field(
        "delete_single_record",
        json_schema_extra={
            "const": "delete_single_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Delete Single Record",
            "x-keywords": [
                "delete record",
                "remove one row",
                "single record delete",
                "delete one record",
            ],
        },
        title="Delete Single Record",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    record_id: str = Field(
        ..., title="Record ID", description="The ID of the record to delete"
    )


class AirtableUpsertRecordsConfig(BaseModel):
    """Create or update records based on field matching (upsert)"""

    operation: Literal["upsert_records_by_field_match"] = Field(
        "upsert_records_by_field_match",
        json_schema_extra={
            "const": "upsert_records_by_field_match",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Upsert Records by Field Match",
            "x-keywords": [
                "upsert records",
                "create or update",
                "match and update",
                "sync records",
                "merge records",
            ],
        },
        title="Upsert Records by Field Match",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    records: List[Dict[str, Any]] = Field(
        ...,
        title="Records",
        description="Array of records to upsert [{fields: {...}}]. Max 10 per request.",
    )
    fields_to_merge_on: List[str] = Field(
        ...,
        title="Fields to Merge On",
        description="Field names to use for matching existing records",
    )
    typecast: Optional[bool] = Field(
        False,
        title="Typecast",
        description="Automatically convert strings to appropriate types",
    )


# ============================================================================
# Comment Operation Configs
# ============================================================================


class AirtableListCommentsConfig(BaseModel):
    """List comments on a record"""

    operation: Literal["list_record_comments"] = Field(
        "list_record_comments",
        json_schema_extra={
            "const": "list_record_comments",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "List Record Comments",
            "x-keywords": [
                "get comments",
                "record comments",
                "list comments",
                "view comments",
            ],
        },
        title="List Record Comments",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    record_id: str = Field(..., title="Record ID", description="The ID of the record")
    offset: Optional[str] = Field(
        None, title="Offset", description="Pagination offset from previous response"
    )


class AirtableCreateCommentConfig(BaseModel):
    """Create a comment on a record"""

    operation: Literal["create_record_comment"] = Field(
        "create_record_comment",
        json_schema_extra={
            "const": "create_record_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Create Record Comment",
            "x-keywords": [
                "add comment",
                "comment on record",
                "post comment",
                "leave comment",
            ],
        },
        title="Create Record Comment",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    record_id: str = Field(..., title="Record ID", description="The ID of the record")
    text: str = Field(
        ...,
        title="Comment Text",
        description="The comment text (supports @mentions with user IDs)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AirtableUpdateCommentConfig(BaseModel):
    """Update a comment"""

    operation: Literal["update_record_comment"] = Field(
        "update_record_comment",
        json_schema_extra={
            "const": "update_record_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Update Record Comment",
            "x-keywords": ["edit comment", "change comment", "modify comment"],
        },
        title="Update Record Comment",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    record_id: str = Field(..., title="Record ID", description="The ID of the record")
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to update"
    )
    text: str = Field(
        ...,
        title="Comment Text",
        description="New comment text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AirtableDeleteCommentConfig(BaseModel):
    """Delete a comment"""

    operation: Literal["delete_record_comment"] = Field(
        "delete_record_comment",
        json_schema_extra={
            "const": "delete_record_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Delete Record Comment",
            "x-keywords": ["remove comment", "delete comment"],
        },
        title="Delete Record Comment",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    table_id_or_name: str = Field(..., title="Table", description="Table ID or name")
    record_id: str = Field(..., title="Record ID", description="The ID of the record")
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to delete"
    )


# ============================================================================
# Webhook Operation Configs
# ============================================================================


class AirtableListWebhooksConfig(BaseModel):
    """List all webhooks for a base"""

    operation: Literal["list_base_webhooks"] = Field(
        "list_base_webhooks",
        json_schema_extra={
            "const": "list_base_webhooks",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Base Webhooks",
            "x-keywords": [
                "list webhooks",
                "view webhooks",
                "show webhooks",
                "base webhooks",
            ],
        },
        title="List Base Webhooks",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")


class AirtableCreateWebhookConfig(BaseModel):
    """Create a webhook for a base"""

    operation: Literal["create_base_webhook"] = Field(
        "create_base_webhook",
        json_schema_extra={
            "const": "create_base_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Base Webhook",
            "x-keywords": [
                "add webhook",
                "new webhook",
                "register webhook",
                "setup webhook",
            ],
        },
        title="Create Base Webhook",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    notification_url: str = Field(
        ...,
        title="Notification URL",
        description="URL to receive webhook notifications",
    )
    specification: Dict[str, Any] = Field(
        ...,
        title="Specification",
        description="Webhook specification defining what changes to watch",
    )


class AirtableDeleteWebhookConfig(BaseModel):
    """Delete a webhook"""

    operation: Literal["delete_base_webhook"] = Field(
        "delete_base_webhook",
        json_schema_extra={
            "const": "delete_base_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Base Webhook",
            "x-keywords": ["remove webhook", "delete webhook"],
        },
        title="Delete Base Webhook",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook to delete"
    )


class AirtableListWebhookPayloadsConfig(BaseModel):
    """List payloads for a webhook"""

    operation: Literal["list_webhook_payloads"] = Field(
        "list_webhook_payloads",
        json_schema_extra={
            "const": "list_webhook_payloads",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Webhook Payloads",
            "x-keywords": [
                "webhook payloads",
                "webhook deliveries",
                "payload history",
                "list payloads",
            ],
        },
        title="List Webhook Payloads",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor from previous response"
    )


class AirtableRefreshWebhookConfig(BaseModel):
    """Refresh a webhook to extend its expiration"""

    operation: Literal["refresh_webhook_expiration"] = Field(
        "refresh_webhook_expiration",
        json_schema_extra={
            "const": "refresh_webhook_expiration",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Refresh Webhook Expiration",
            "x-keywords": [
                "extend webhook",
                "renew webhook",
                "refresh webhook",
                "keep webhook alive",
            ],
        },
        title="Refresh Webhook Expiration",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook to refresh"
    )


class AirtableEnableWebhookNotificationsConfig(BaseModel):
    """Enable notifications for a webhook"""

    operation: Literal["enable_webhook_notifications"] = Field(
        "enable_webhook_notifications",
        json_schema_extra={
            "const": "enable_webhook_notifications",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Enable Webhook Notifications",
            "x-keywords": [
                "turn on notifications",
                "enable notifications",
                "webhook notifications on",
            ],
        },
        title="Enable Webhook Notifications",
    )
    base_id: str = Field(..., title="Base ID", description="The ID of the base")
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )


# ============================================================================
# Discriminated Union
# ============================================================================

AirtableConfig = Annotated[
    Union[
        # Base/Meta operations (6)
        AirtableListBasesConfig,
        AirtableGetBaseSchemaConfig,
        AirtableCreateTableConfig,
        AirtableUpdateTableConfig,
        AirtableCreateFieldConfig,
        AirtableUpdateFieldConfig,
        # Record operations (8)
        AirtableListRecordsConfig,
        AirtableGetRecordConfig,
        AirtableCreateRecordsConfig,
        AirtableUpdateRecordsConfig,
        AirtableUpdateRecordConfig,
        AirtableDeleteRecordsConfig,
        AirtableDeleteRecordConfig,
        AirtableUpsertRecordsConfig,
        # Comment operations (4)
        AirtableListCommentsConfig,
        AirtableCreateCommentConfig,
        AirtableUpdateCommentConfig,
        AirtableDeleteCommentConfig,
        # Webhook operations (6)
        AirtableListWebhooksConfig,
        AirtableCreateWebhookConfig,
        AirtableDeleteWebhookConfig,
        AirtableListWebhookPayloadsConfig,
        AirtableRefreshWebhookConfig,
        AirtableEnableWebhookNotificationsConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class AirtableNodeConfig(NodeConfig[AirtableConfig, AirtableCredential]):
    """Full configuration for Airtable node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class AirtableNode(WorkflowNode):
    """
    Airtable automation node.

    Executes Airtable API operations for workflow automation.
    Supports 24 operations across bases, records, comments, and webhooks.
    """

    edit_examples = [
        'Create a new record in the "Customers" table with name and email',
        'Update the status field of record rec_12345 to "Completed"',
        'List all records from the "Projects" base with a limit of 50',
        "Delete a record by ID and return the deletion timestamp",
        "Add a comment to record rec_67890 with the approval status",
        'Create a webhook that triggers on record updates in the "Sales" table',
        "Get the schema of the base to extract all table and field definitions",
    ]

    scope_registry = AIRTABLE_SCOPES

    # A user knows their own base names instantly. New accounts have none, so
    # the same listing doubles as the identity fallback.
    connection_evidence = ConnectionEvidence(
        operation="list_accessible_bases",
        noun="bases",
    )

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return AirtableNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, AirtableNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your Airtable Personal Access Token."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Base/Meta operations
            "list_accessible_bases": self._handle_list_bases,
            "fetch_base_schema": self._handle_get_base_schema,
            "create_new_table": self._handle_create_table,
            "update_table_metadata": self._handle_update_table,
            "create_table_field": self._handle_create_field,
            "update_table_field": self._handle_update_field,
            # Record operations
            "list_table_records": self._handle_list_records,
            "fetch_single_record": self._handle_get_record,
            "create_multiple_records": self._handle_create_records,
            "update_multiple_records": self._handle_update_records,
            "update_single_record": self._handle_update_record,
            "delete_multiple_records": self._handle_delete_records,
            "delete_single_record": self._handle_delete_record,
            "upsert_records_by_field_match": self._handle_upsert_records,
            # Comment operations
            "list_record_comments": self._handle_list_comments,
            "create_record_comment": self._handle_create_comment,
            "update_record_comment": self._handle_update_comment,
            "delete_record_comment": self._handle_delete_comment,
            # Webhook operations
            "list_base_webhooks": self._handle_list_webhooks,
            "create_base_webhook": self._handle_create_webhook,
            "delete_base_webhook": self._handle_delete_webhook,
            "list_webhook_payloads": self._handle_list_webhook_payloads,
            "refresh_webhook_expiration": self._handle_refresh_webhook,
            "enable_webhook_notifications": self._handle_enable_webhook_notifications,
        }

        action = op_config.operation
        handler = handlers.get(action)

        if not handler:
            raise ValueError(f"Unknown action: {action}")

        # Execute the handler
        result = await handler(op_config, credentials)

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.airtable_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="airtable",
        )

    async def _get_access_token(self, credentials: AirtableCredential) -> str:
        """
        Get access token from credentials, refreshing OAuth token if expired.

        Args:
            credentials: PAT or OAuth credentials

        Returns:
            Access token string
        """
        if isinstance(credentials, AirtablePATCredential):
            return credentials.personal_access_token
        elif isinstance(credentials, AirtableOAuthCredential):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            
            cred_dict = credentials.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=refresh_access_token,
                provider="airtable",
            )
            credentials.access_token = cred_dict["access_token"]
            credentials.expires_at = cred_dict.get("expires_at")
            if cred_dict.get("refresh_token"):
                credentials.refresh_token = cred_dict["refresh_token"]
            return token
        else:
            raise ValueError(f"Unknown credential type: {type(credentials)}")

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: AirtableCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Airtable API.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint (without base URL)
            credentials: API credentials (PAT or OAuth)
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        url = f"{AIRTABLE_API_BASE}{endpoint}"

        # Get access token (handles both PAT and OAuth with refresh)
        access_token = await self._get_access_token(credentials)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get("error", {})
                        if isinstance(error_message, dict):
                            error_message = error_message.get(
                                "message", str(error_message)
                            )
                    except Exception:
                        error_message = error_text

                    logger.error(f"[AirtableNode] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:  # No content
                    data = {"success": True}
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
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[AirtableNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Base/Meta Operation Handlers
    # =========================================================================

    async def _handle_list_bases(
        self, config: AirtableListBasesConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """List all accessible bases."""
        params = {}
        if config.offset:
            params["offset"] = config.offset

        return await self._make_request(
            method="GET",
            endpoint="/meta/bases",
            credentials=credentials,
            params=params if params else None,
            action_name="list_accessible_bases",
        )

    async def _handle_get_base_schema(
        self, config: AirtableGetBaseSchemaConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Get the schema of a base."""
        return await self._make_request(
            method="GET",
            endpoint=f"/meta/bases/{config.base_id}/tables",
            credentials=credentials,
            action_name="fetch_base_schema",
        )

    async def _handle_create_table(
        self, config: AirtableCreateTableConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Create a new table in a base."""
        body: Dict[str, Any] = {"name": config.name}
        if config.description:
            body["description"] = config.description
        if config.fields:
            body["fields"] = config.fields

        return await self._make_request(
            method="POST",
            endpoint=f"/meta/bases/{config.base_id}/tables",
            credentials=credentials,
            json_body=body,
            action_name="create_new_table",
        )

    async def _handle_update_table(
        self, config: AirtableUpdateTableConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Update a table's name or description."""
        body: Dict[str, Any] = {}
        if config.name is not None:
            body["name"] = config.name
        if config.description is not None:
            body["description"] = config.description

        return await self._make_request(
            method="PATCH",
            endpoint=f"/meta/bases/{config.base_id}/tables/{config.table_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_table_metadata",
        )

    async def _handle_create_field(
        self, config: AirtableCreateFieldConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Create a new field in a table."""
        body: Dict[str, Any] = {
            "name": config.name,
            "type": config.field_type,
        }
        if config.description:
            body["description"] = config.description
        if config.options:
            body["options"] = config.options

        return await self._make_request(
            method="POST",
            endpoint=f"/meta/bases/{config.base_id}/tables/{config.table_id}/fields",
            credentials=credentials,
            json_body=body,
            action_name="create_table_field",
        )

    async def _handle_update_field(
        self, config: AirtableUpdateFieldConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Update a field's name or description."""
        body: Dict[str, Any] = {}
        if config.name is not None:
            body["name"] = config.name
        if config.description is not None:
            body["description"] = config.description

        return await self._make_request(
            method="PATCH",
            endpoint=f"/meta/bases/{config.base_id}/tables/{config.table_id}/fields/{config.field_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_table_field",
        )

    # =========================================================================
    # Record Operation Handlers
    # =========================================================================

    async def _handle_list_records(
        self, config: AirtableListRecordsConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """List records from a table."""
        params: Dict[str, Any] = {}

        if config.view:
            params["view"] = config.view
        if config.page_size:
            params["pageSize"] = config.page_size
        if config.offset:
            params["offset"] = config.offset
        if config.filter_by_formula:
            params["filterByFormula"] = config.filter_by_formula
        if config.sort_field:
            params["sort[0][field]"] = config.sort_field
            params["sort[0][direction]"] = config.sort_direction or "asc"
        if config.fields:
            for i, field in enumerate(config.fields):
                params[f"fields[{i}]"] = field
        if config.max_records:
            params["maxRecords"] = config.max_records
        if config.cell_format:
            params["cellFormat"] = config.cell_format
        if config.time_zone:
            params["timeZone"] = config.time_zone
        if config.user_locale:
            params["userLocale"] = config.user_locale

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}",
            credentials=credentials,
            params=params if params else None,
            action_name="list_table_records",
        )

    async def _handle_get_record(
        self, config: AirtableGetRecordConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Get a single record."""
        params = {}
        if config.cell_format:
            params["cellFormat"] = config.cell_format

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}/{config.record_id}",
            credentials=credentials,
            params=params if params else None,
            action_name="fetch_single_record",
        )

    async def _handle_create_records(
        self, config: AirtableCreateRecordsConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Create one or more records."""
        body: Dict[str, Any] = {"records": config.records}
        if config.typecast:
            body["typecast"] = config.typecast
        if config.return_fields_by_field_id:
            body["returnFieldsByFieldId"] = config.return_fields_by_field_id

        return await self._make_request(
            method="POST",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}",
            credentials=credentials,
            json_body=body,
            action_name="create_multiple_records",
        )

    async def _handle_update_records(
        self, config: AirtableUpdateRecordsConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Update one or more records."""
        body: Dict[str, Any] = {"records": config.records}
        if config.typecast:
            body["typecast"] = config.typecast
        if config.return_fields_by_field_id:
            body["returnFieldsByFieldId"] = config.return_fields_by_field_id

        return await self._make_request(
            method="PATCH",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}",
            credentials=credentials,
            json_body=body,
            action_name="update_multiple_records",
        )

    async def _handle_update_record(
        self, config: AirtableUpdateRecordConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Update a single record."""
        body: Dict[str, Any] = {"fields": config.fields}
        if config.typecast:
            body["typecast"] = config.typecast

        return await self._make_request(
            method="PATCH",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}/{config.record_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_single_record",
        )

    async def _handle_delete_records(
        self, config: AirtableDeleteRecordsConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Delete one or more records."""
        # Airtable expects records[] query params for batch delete
        params = {}
        for i, record_id in enumerate(config.record_ids):
            params[f"records[{i}]"] = record_id

        return await self._make_request(
            method="DELETE",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}",
            credentials=credentials,
            params=params,
            action_name="delete_multiple_records",
        )

    async def _handle_delete_record(
        self, config: AirtableDeleteRecordConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Delete a single record."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}/{config.record_id}",
            credentials=credentials,
            action_name="delete_single_record",
        )

    async def _handle_upsert_records(
        self, config: AirtableUpsertRecordsConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Upsert (create or update) records."""
        body: Dict[str, Any] = {
            "performUpsert": {"fieldsToMergeOn": config.fields_to_merge_on},
            "records": config.records,
        }
        if config.typecast:
            body["typecast"] = config.typecast

        return await self._make_request(
            method="PATCH",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}",
            credentials=credentials,
            json_body=body,
            action_name="upsert_records_by_field_match",
        )

    # =========================================================================
    # Comment Operation Handlers
    # =========================================================================

    async def _handle_list_comments(
        self, config: AirtableListCommentsConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """List comments on a record."""
        params = {}
        if config.offset:
            params["offset"] = config.offset

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}/{config.record_id}/comments",
            credentials=credentials,
            params=params if params else None,
            action_name="list_record_comments",
        )

    async def _handle_create_comment(
        self, config: AirtableCreateCommentConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Create a comment on a record."""
        body = {"text": config.text}

        return await self._make_request(
            method="POST",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}/{config.record_id}/comments",
            credentials=credentials,
            json_body=body,
            action_name="create_record_comment",
        )

    async def _handle_update_comment(
        self, config: AirtableUpdateCommentConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Update a comment."""
        body = {"text": config.text}

        return await self._make_request(
            method="PATCH",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}/{config.record_id}/comments/{config.comment_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_record_comment",
        )

    async def _handle_delete_comment(
        self, config: AirtableDeleteCommentConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Delete a comment."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/{config.base_id}/{config.table_id_or_name}/{config.record_id}/comments/{config.comment_id}",
            credentials=credentials,
            action_name="delete_record_comment",
        )

    # =========================================================================
    # Webhook Operation Handlers
    # =========================================================================

    async def _handle_list_webhooks(
        self, config: AirtableListWebhooksConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """List all webhooks for a base."""
        return await self._make_request(
            method="GET",
            endpoint=f"/bases/{config.base_id}/webhooks",
            credentials=credentials,
            action_name="list_base_webhooks",
        )

    async def _handle_create_webhook(
        self, config: AirtableCreateWebhookConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Create a webhook for a base."""
        body = {
            "notificationUrl": config.notification_url,
            "specification": config.specification,
        }

        return await self._make_request(
            method="POST",
            endpoint=f"/bases/{config.base_id}/webhooks",
            credentials=credentials,
            json_body=body,
            action_name="create_base_webhook",
        )

    async def _handle_delete_webhook(
        self, config: AirtableDeleteWebhookConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Delete a webhook."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/bases/{config.base_id}/webhooks/{config.webhook_id}",
            credentials=credentials,
            action_name="delete_base_webhook",
        )

    async def _handle_list_webhook_payloads(
        self, config: AirtableListWebhookPayloadsConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """List payloads for a webhook."""
        params = {}
        if config.cursor:
            params["cursor"] = config.cursor

        return await self._make_request(
            method="GET",
            endpoint=f"/bases/{config.base_id}/webhooks/{config.webhook_id}/payloads",
            credentials=credentials,
            params=params if params else None,
            action_name="list_webhook_payloads",
        )

    async def _handle_refresh_webhook(
        self, config: AirtableRefreshWebhookConfig, credentials: AirtableCredential
    ) -> Dict[str, Any]:
        """Refresh a webhook to extend its expiration."""
        return await self._make_request(
            method="POST",
            endpoint=f"/bases/{config.base_id}/webhooks/{config.webhook_id}/refresh",
            credentials=credentials,
            action_name="refresh_webhook_expiration",
        )

    async def _handle_enable_webhook_notifications(
        self,
        config: AirtableEnableWebhookNotificationsConfig,
        credentials: AirtableCredential,
    ) -> Dict[str, Any]:
        """Enable notifications for a webhook."""
        body = {"enable": True}

        return await self._make_request(
            method="POST",
            endpoint=f"/bases/{config.base_id}/webhooks/{config.webhook_id}/enableNotifications",
            credentials=credentials,
            json_body=body,
            action_name="enable_webhook_notifications",
        )
