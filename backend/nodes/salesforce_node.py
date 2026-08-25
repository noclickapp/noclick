"""
Salesforce REST API automation node.

Provides workflow integration with Salesforce for operations including:
- Query Operations: execute SOQL queries, SOSL search, query more results
- Record Operations: create, read, update, delete, upsert single records
- Batch Operations: create, update, delete multiple records (sObject Collections)
- Describe Operations: list objects, describe objects, global describe
- Utility Operations: get limits, user info, API versions

Authentication: OAuth 2.0 (Web Server Flow)
API Base URL: https://{instance}.salesforce.com/services/data/v63.0
Documentation: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest
Rate Limit: Varies by org edition (typically 15,000-100,000+ requests per 24 hours)
"""

import json
import logging
import mimetypes
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.oauth.salesforce_oauth import (
    is_token_expired,
    normalize_salesforce_instance_url,
    refresh_access_token,
)
from nodes.scopes.salesforce import SALESFORCE_SCOPES
from utils.ssrf import assert_exact_url_origin, guarded_async_client

logger = logging.getLogger(__name__)

# Default API version - Salesforce releases 3 versions per year
SALESFORCE_API_VERSION = "v63.0"

# ============================================================================
# Credential Schema
# ============================================================================


class SalesforceOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for Salesforce.
    Tokens are obtained via OAuth flow, not entered manually.

    Register Connected App at: https://help.salesforce.com/s/articleView?id=sf.connected_app_create.htm
    """

    credential_type: Literal["salesforce_oauth"] = Field(
        "salesforce_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Salesforce"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    instance_url: str = Field(
        ...,
        title="Instance URL",
        description="Salesforce instance URL (e.g., https://na1.salesforce.com)",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: Optional[str] = Field(
        None,
        title="Account Email",
        description="Email address of the connected Salesforce user",
    )
    is_sandbox: Optional[bool] = Field(
        False, title="Is Sandbox", description="Whether this is a sandbox org"
    )

    @field_validator("instance_url")
    @classmethod
    def validate_instance_url(cls, value: str) -> str:
        return normalize_salesforce_instance_url(value)

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "salesforce",
            "x-oauth-scopes": [
                "api",
                "refresh_token",
                "full",
            ],
        },
    )


# Single credential type - OAuth only for Salesforce
SalesforceCredential = SalesforceOAuthCredential


# ============================================================================
# Query Operation Configs
# ============================================================================


class SalesforceQueryConfig(BaseModel):
    """Execute a SOQL query to retrieve records"""

    operation: Literal["execute_soql_query"] = Field(
        "execute_soql_query",
        json_schema_extra={
            "const": "execute_soql_query",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Execute Soql Query",
        },
        title="Execute Soql Query",
    )
    query: str = Field(
        ...,
        title="SOQL Query",
        description="SOQL query string (e.g., SELECT Id, Name FROM Account WHERE CreatedDate > YESTERDAY)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class SalesforceQueryMoreConfig(BaseModel):
    """Get the next batch of query results using a query locator"""

    operation: Literal["get_query_result_next_batch"] = Field(
        "get_query_result_next_batch",
        json_schema_extra={
            "const": "get_query_result_next_batch",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Get Query Result Next Batch",
        },
        title="Get Query Result Next Batch",
    )
    next_records_url: str = Field(
        ...,
        title="Next Records URL",
        description="The nextRecordsUrl from a previous query response",
    )


class SalesforceSearchConfig(BaseModel):
    """Execute a SOSL search across multiple objects"""

    operation: Literal["execute_sosl_search"] = Field(
        "execute_sosl_search",
        json_schema_extra={
            "const": "execute_sosl_search",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Execute Sosl Search",
        },
        title="Execute Sosl Search",
    )
    search_query: str = Field(
        ...,
        title="SOSL Search Query",
        description="SOSL search query (e.g., FIND {Acme} IN ALL FIELDS RETURNING Account, Contact)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Record Operation Configs
# ============================================================================


class SalesforceGetRecordConfig(BaseModel):
    """Get a single record by ID"""

    operation: Literal["get_single_record"] = Field(
        "get_single_record",
        json_schema_extra={
            "const": "get_single_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Get Single Record",
        },
        title="Get Single Record",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact, Lead, Opportunity)",
    )
    record_id: str = Field(
        ...,
        title="Record ID",
        description="The 15 or 18 character Salesforce record ID",
    )
    fields: Optional[List[str]] = Field(
        None,
        title="Fields",
        description="List of field names to retrieve (leave empty for all fields)",
    )


class SalesforceCreateRecordConfig(BaseModel):
    """Create a new record"""

    operation: Literal["create_single_record"] = Field(
        "create_single_record",
        json_schema_extra={
            "const": "create_single_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Create Single Record",
        },
        title="Create Single Record",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact, Lead)",
    )
    fields: Dict[str, Any] = Field(
        ...,
        title="Field Values",
        description='Object with field names and values to set (e.g., {"Name": "Acme Corp", "Industry": "Technology"})',
    )


class SalesforceUpdateRecordConfig(BaseModel):
    """Update an existing record"""

    operation: Literal["update_single_record"] = Field(
        "update_single_record",
        json_schema_extra={
            "const": "update_single_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Update Single Record",
        },
        title="Update Single Record",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )
    record_id: str = Field(
        ..., title="Record ID", description="The Salesforce record ID to update"
    )
    fields: Dict[str, Any] = Field(
        ...,
        title="Field Values",
        description="Object with field names and values to update",
    )


class SalesforceDeleteRecordConfig(BaseModel):
    """Delete a record"""

    operation: Literal["delete_single_record"] = Field(
        "delete_single_record",
        json_schema_extra={
            "const": "delete_single_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Delete Single Record",
        },
        title="Delete Single Record",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )
    record_id: str = Field(
        ..., title="Record ID", description="The Salesforce record ID to delete"
    )


class SalesforceUpsertRecordConfig(BaseModel):
    """Create or update a record using an external ID field"""

    operation: Literal["upsert_record_by_external_id"] = Field(
        "upsert_record_by_external_id",
        json_schema_extra={
            "const": "upsert_record_by_external_id",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Upsert Record by External Id",
        },
        title="Upsert Record by External Id",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )
    external_id_field: str = Field(
        ...,
        title="External ID Field",
        description="API name of the external ID field to match on",
    )
    external_id_value: str = Field(
        ..., title="External ID Value", description="Value of the external ID to match"
    )
    fields: Dict[str, Any] = Field(
        ...,
        title="Field Values",
        description="Object with field names and values to set/update",
    )


# ============================================================================
# Batch Operation Configs (sObject Collections)
# ============================================================================


class SalesforceCreateRecordsConfig(BaseModel):
    """Create multiple records in a single request (up to 200)"""

    operation: Literal["create_multiple_records"] = Field(
        "create_multiple_records",
        json_schema_extra={
            "const": "create_multiple_records",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Create Multiple Records",
        },
        title="Create Multiple Records",
    )
    sobject_type: str = Field(
        ..., title="Object Type", description="Salesforce object type for all records"
    )
    records: List[Dict[str, Any]] = Field(
        ...,
        title="Records",
        description="Array of objects with field values. Max 200 records per request.",
    )
    all_or_none: Optional[bool] = Field(
        False,
        title="All or None",
        description="If true, all records must succeed or all fail (atomic transaction)",
    )


class SalesforceUpdateRecordsConfig(BaseModel):
    """Update multiple records in a single request (up to 200)"""

    operation: Literal["update_multiple_records"] = Field(
        "update_multiple_records",
        json_schema_extra={
            "const": "update_multiple_records",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Update Multiple Records",
        },
        title="Update Multiple Records",
    )
    sobject_type: str = Field(
        ..., title="Object Type", description="Salesforce object type for all records"
    )
    records: List[Dict[str, Any]] = Field(
        ...,
        title="Records",
        description="Array of objects with 'Id' and field values to update. Max 200 records.",
    )
    all_or_none: Optional[bool] = Field(
        False,
        title="All or None",
        description="If true, all records must succeed or all fail",
    )


class SalesforceDeleteRecordsConfig(BaseModel):
    """Delete multiple records in a single request (up to 200)"""

    operation: Literal["delete_multiple_records"] = Field(
        "delete_multiple_records",
        json_schema_extra={
            "const": "delete_multiple_records",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Delete Multiple Records",
        },
        title="Delete Multiple Records",
    )
    record_ids: List[str] = Field(
        ...,
        title="Record IDs",
        description="Array of Salesforce record IDs to delete. Max 200.",
    )
    all_or_none: Optional[bool] = Field(
        False,
        title="All or None",
        description="If true, all deletes must succeed or all fail",
    )


# ============================================================================
# Describe/Metadata Operation Configs
# ============================================================================


class SalesforceListObjectsConfig(BaseModel):
    """List all available sObjects in the org"""

    operation: Literal["list_available_sobjects"] = Field(
        "list_available_sobjects",
        json_schema_extra={
            "const": "list_available_sobjects",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "List Available Sobjects",
        },
        title="List Available Sobjects",
    )


class SalesforceDescribeObjectConfig(BaseModel):
    """Get detailed metadata for a specific sObject including all fields"""

    operation: Literal["get_sobject_metadata"] = Field(
        "get_sobject_metadata",
        json_schema_extra={
            "const": "get_sobject_metadata",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Get Sobject Metadata",
        },
        title="Get Sobject Metadata",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type to describe (e.g., Account, Contact)",
    )


class SalesforceDescribeGlobalConfig(BaseModel):
    """Get global metadata about the org"""

    operation: Literal["get_org_global_metadata"] = Field(
        "get_org_global_metadata",
        json_schema_extra={
            "const": "get_org_global_metadata",
            "ui:hidden": True,
            "x-category": "Org",
            "x-is-trigger": False,
            "x-display-name": "Get Org Global Metadata",
        },
        title="Get Org Global Metadata",
    )


# ============================================================================
# Utility Operation Configs
# ============================================================================


class SalesforceGetLimitsConfig(BaseModel):
    """Get org API usage limits"""

    operation: Literal["get_org_api_limits"] = Field(
        "get_org_api_limits",
        json_schema_extra={
            "const": "get_org_api_limits",
            "ui:hidden": True,
            "x-category": "Org",
            "x-is-trigger": False,
            "x-display-name": "Get Org Api Limits",
        },
        title="Get Org Api Limits",
    )


class SalesforceGetUserInfoConfig(BaseModel):
    """Get information about the current authenticated user"""

    operation: Literal["get_current_user_info"] = Field(
        "get_current_user_info",
        json_schema_extra={
            "const": "get_current_user_info",
            "ui:hidden": True,
            "x-category": "Org",
            "x-is-trigger": False,
            "x-display-name": "Get Current User Info",
        },
        title="Get Current User Info",
    )


class SalesforceGetVersionsConfig(BaseModel):
    """Get available Salesforce API versions"""

    operation: Literal["get_available_api_versions"] = Field(
        "get_available_api_versions",
        json_schema_extra={
            "const": "get_available_api_versions",
            "ui:hidden": True,
            "x-category": "Org",
            "x-is-trigger": False,
            "x-display-name": "Get Available Api Versions",
        },
        title="Get Available Api Versions",
    )


# ============================================================================
# Approval Process Operation Configs
# ============================================================================


class SalesforceListApprovalProcessesConfig(BaseModel):
    """List all approval processes in the org"""

    operation: Literal["list_approval_processes"] = Field(
        "list_approval_processes",
        json_schema_extra={
            "const": "list_approval_processes",
            "ui:hidden": True,
            "x-category": "Approval",
            "x-is-trigger": False,
            "x-display-name": "List Approval Processes",
        },
        title="List Approval Processes",
    )


class SalesforceSubmitForApprovalConfig(BaseModel):
    """Submit a record for approval"""

    operation: Literal["submit_record_for_approval"] = Field(
        "submit_record_for_approval",
        json_schema_extra={
            "const": "submit_record_for_approval",
            "ui:hidden": True,
            "x-category": "Approval",
            "x-is-trigger": False,
            "x-display-name": "Submit Record for Approval",
        },
        title="Submit Record for Approval",
    )
    record_id: str = Field(
        ..., title="Record ID", description="ID of the record to submit for approval"
    )
    process_definition_name_or_id: Optional[str] = Field(
        None,
        title="Process Definition",
        description="Name or ID of the approval process (optional, uses default if not specified)",
    )
    comments: Optional[str] = Field(
        None, title="Comments", description="Comments to include with the submission"
    )
    next_approver_ids: Optional[List[str]] = Field(
        None,
        title="Next Approver IDs",
        description="List of user IDs for next approvers",
    )
    skip_entry_criteria: Optional[bool] = Field(
        False,
        title="Skip Entry Criteria",
        description="Skip the entry criteria for the approval process",
    )


class SalesforceApproveRejectConfig(BaseModel):
    """Approve or reject a pending approval request"""

    operation: Literal["approve_or_reject_approval_request"] = Field(
        "approve_or_reject_approval_request",
        json_schema_extra={
            "const": "approve_or_reject_approval_request",
            "ui:hidden": True,
            "x-category": "Approval",
            "x-is-trigger": False,
            "x-display-name": "Approve or Reject Approval Request",
        },
        title="Approve or Reject Approval Request",
    )
    work_item_ids: List[str] = Field(
        ...,
        title="Work Item IDs",
        description="List of work item IDs to approve or reject",
    )
    action_type: Literal["Approve", "Reject"] = Field(
        ..., title="Action", description="Whether to approve or reject"
    )
    comments: Optional[str] = Field(
        None, title="Comments", description="Comments for the approval/rejection"
    )
    next_approver_ids: Optional[List[str]] = Field(
        None,
        title="Next Approver IDs",
        description="For approve action, IDs of next approvers",
    )


# ============================================================================
# File/Attachment Operation Configs
# ============================================================================


class SalesforceGetBlobConfig(BaseModel):
    """Get blob (binary) data for a record field like Attachment body or Document body"""

    operation: Literal["get_blob_field_content"] = Field(
        "get_blob_field_content",
        json_schema_extra={
            "const": "get_blob_field_content",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get Blob Field Content",
        },
        title="Get Blob Field Content",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (e.g., Attachment, Document, ContentVersion)",
    )
    record_id: str = Field(
        ..., title="Record ID", description="ID of the record containing the blob"
    )
    blob_field: str = Field(
        "Body", title="Blob Field", description="Name of the blob field (default: Body)"
    )


class SalesforceCreateAttachmentConfig(BaseModel):
    """Create an attachment on a record"""

    operation: Literal["create_record_attachment"] = Field(
        "create_record_attachment",
        json_schema_extra={
            "const": "create_record_attachment",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Create Record Attachment",
        },
        title="Create Record Attachment",
    )
    parent_id: str = Field(
        ...,
        title="Parent Record ID",
        description="ID of the parent record to attach to",
    )
    name: str = Field(..., title="File Name", description="Name of the attachment file")
    body: str = Field(
        ..., title="Body (Base64)", description="Base64-encoded file content"
    )
    content_type: Optional[str] = Field(
        None,
        title="Content Type",
        description="MIME type of the file (e.g., application/pdf)",
    )
    description: Optional[str] = Field(
        None, title="Description", description="Description of the attachment"
    )


class SalesforceCreateContentVersionConfig(BaseModel):
    """Upload a file as ContentVersion (Files)"""

    operation: Literal["upload_file_as_content_version"] = Field(
        "upload_file_as_content_version",
        json_schema_extra={
            "const": "upload_file_as_content_version",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Upload File As Content Version",
        },
        title="Upload File As Content Version",
    )
    title: str = Field(..., title="Title", description="Title of the file")
    path_on_client: str = Field(
        ..., title="File Name", description="Name of the file including extension"
    )
    version_data: str = Field(
        ..., title="Version Data (Base64)", description="Base64-encoded file content"
    )
    first_publish_location_id: Optional[str] = Field(
        None,
        title="First Publish Location ID",
        description="ID of record or library to link the file to",
    )
    description: Optional[str] = Field(
        None, title="Description", description="Description of the file"
    )


# ============================================================================
# Composite Operation Configs
# ============================================================================


class SalesforceCompositeRequestConfig(BaseModel):
    """Execute multiple REST API requests in a single call"""

    operation: Literal["execute_composite_api_request"] = Field(
        "execute_composite_api_request",
        json_schema_extra={
            "const": "execute_composite_api_request",
            "ui:hidden": True,
            "x-category": "Composite Request",
            "x-is-trigger": False,
            "x-display-name": "Execute Composite Api Request",
        },
        title="Execute Composite Api Request",
    )
    composite_requests: List[Dict[str, Any]] = Field(
        ...,
        title="Requests",
        description="Array of subrequest objects with method, url, referenceId, and optionally body",
    )
    all_or_none: Optional[bool] = Field(
        False,
        title="All or None",
        description="If true, all subrequests must succeed or all fail",
    )
    collate_subrequests: Optional[bool] = Field(
        False,
        title="Collate Subrequests",
        description="If true, independent subrequests execute in parallel",
    )


class SalesforceSObjectTreeConfig(BaseModel):
    """Create a tree of nested, parent-child records in a single request"""

    operation: Literal["create_nested_record_tree"] = Field(
        "create_nested_record_tree",
        json_schema_extra={
            "const": "create_nested_record_tree",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Create Nested Record Tree",
        },
        title="Create Nested Record Tree",
    )
    sobject_type: str = Field(
        ...,
        title="Root Object Type",
        description="Object type of the root records (e.g., Account)",
    )
    records: List[Dict[str, Any]] = Field(
        ...,
        title="Records",
        description="Array of records with nested child relationships",
    )


# ============================================================================
# Recently Viewed Operation Configs
# ============================================================================


class SalesforceGetRecentlyViewedConfig(BaseModel):
    """Get recently viewed records"""

    operation: Literal["get_recently_viewed_records"] = Field(
        "get_recently_viewed_records",
        json_schema_extra={
            "const": "get_recently_viewed_records",
            "ui:hidden": True,
            "x-category": "Org",
            "x-is-trigger": False,
            "x-display-name": "Get Recently Viewed Records",
        },
        title="Get Recently Viewed Records",
    )
    limit: Optional[int] = Field(
        None, title="Limit", description="Maximum number of records to return"
    )


# ============================================================================
# Quick Actions Operation Configs
# ============================================================================


class SalesforceListQuickActionsConfig(BaseModel):
    """List available global quick actions"""

    operation: Literal["list_global_quick_actions"] = Field(
        "list_global_quick_actions",
        json_schema_extra={
            "const": "list_global_quick_actions",
            "ui:hidden": True,
            "x-category": "Quick Action",
            "x-is-trigger": False,
            "x-display-name": "List Global Quick Actions",
        },
        title="List Global Quick Actions",
    )


class SalesforceListObjectQuickActionsConfig(BaseModel):
    """List quick actions for a specific object"""

    operation: Literal["list_object_quick_actions"] = Field(
        "list_object_quick_actions",
        json_schema_extra={
            "const": "list_object_quick_actions",
            "ui:hidden": True,
            "x-category": "Quick Action",
            "x-is-trigger": False,
            "x-display-name": "List Object Quick Actions",
        },
        title="List Object Quick Actions",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Case)",
    )


class SalesforceExecuteQuickActionConfig(BaseModel):
    """Execute a quick action"""

    operation: Literal["execute_quick_action"] = Field(
        "execute_quick_action",
        json_schema_extra={
            "const": "execute_quick_action",
            "ui:hidden": True,
            "x-category": "Quick Action",
            "x-is-trigger": False,
            "x-display-name": "Execute Quick Action",
        },
        title="Execute Quick Action",
    )
    quick_action_name: str = Field(
        ..., title="Quick Action Name", description="API name of the quick action"
    )
    context_id: Optional[str] = Field(
        None,
        title="Context ID",
        description="ID of the record to execute the action on (for object-specific actions)",
    )
    record: Optional[Dict[str, Any]] = Field(
        None, title="Record Data", description="Field values for the quick action"
    )


# ============================================================================
# Layouts Operation Configs
# ============================================================================


class SalesforceGetLayoutsConfig(BaseModel):
    """Get page layouts for an object"""

    operation: Literal["get_sobject_page_layouts"] = Field(
        "get_sobject_page_layouts",
        json_schema_extra={
            "const": "get_sobject_page_layouts",
            "ui:hidden": True,
            "x-category": "Layout",
            "x-is-trigger": False,
            "x-display-name": "Get Sobject Page Layouts",
        },
        title="Get Sobject Page Layouts",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )


class SalesforceGetCompactLayoutsConfig(BaseModel):
    """Get compact layouts for an object"""

    operation: Literal["get_sobject_compact_layouts"] = Field(
        "get_sobject_compact_layouts",
        json_schema_extra={
            "const": "get_sobject_compact_layouts",
            "ui:hidden": True,
            "x-category": "Layout",
            "x-is-trigger": False,
            "x-display-name": "Get Sobject Compact Layouts",
        },
        title="Get Sobject Compact Layouts",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )


# ============================================================================
# Bulk API 2.0 Operation Configs
# ============================================================================


class SalesforceCreateBulkJobConfig(BaseModel):
    """Create a bulk ingest job for large data operations"""

    operation: Literal["create_bulk_data_job"] = Field(
        "create_bulk_data_job",
        json_schema_extra={
            "const": "create_bulk_data_job",
            "ui:hidden": True,
            "x-category": "Bulk Job",
            "x-is-trigger": False,
            "x-display-name": "Create Bulk Data Job",
        },
        title="Create Bulk Data Job",
    )
    bulk_operation: Literal[
        "insert", "update", "upsert", "delete", "hardDelete"
    ] = Field(..., title="Bulk Operation", description="Type of bulk operation")
    sobject_type: str = Field(
        ..., title="Object Type", description="Salesforce object type for the job"
    )
    external_id_field: Optional[str] = Field(
        None, title="External ID Field", description="Required for upsert operation"
    )
    line_ending: Optional[Literal["LF", "CRLF"]] = Field(
        "LF", title="Line Ending", description="Line ending for CSV data"
    )


class SalesforceUploadBulkDataConfig(BaseModel):
    """Upload CSV data to a bulk job"""

    operation: Literal["upload_csv_to_bulk_job"] = Field(
        "upload_csv_to_bulk_job",
        json_schema_extra={
            "const": "upload_csv_to_bulk_job",
            "ui:hidden": True,
            "x-category": "Bulk Job",
            "x-is-trigger": False,
            "x-display-name": "Upload Csv to Bulk Job",
        },
        title="Upload Csv to Bulk Job",
    )
    job_id: str = Field(..., title="Job ID", description="ID of the bulk job")
    csv_data: str = Field(
        ...,
        title="CSV Data",
        description="CSV-formatted data to upload",
        json_schema_extra={"ui:widget": "textarea"},
    )


class SalesforceCloseBulkJobConfig(BaseModel):
    """Close a bulk job to start processing"""

    operation: Literal["close_bulk_data_job"] = Field(
        "close_bulk_data_job",
        json_schema_extra={
            "const": "close_bulk_data_job",
            "ui:hidden": True,
            "x-category": "Bulk Job",
            "x-is-trigger": False,
            "x-display-name": "Close Bulk Data Job",
        },
        title="Close Bulk Data Job",
    )
    job_id: str = Field(..., title="Job ID", description="ID of the bulk job to close")


class SalesforceGetBulkJobStatusConfig(BaseModel):
    """Get the status of a bulk job"""

    operation: Literal["get_bulk_job_status"] = Field(
        "get_bulk_job_status",
        json_schema_extra={
            "const": "get_bulk_job_status",
            "ui:hidden": True,
            "x-category": "Bulk Job",
            "x-is-trigger": False,
            "x-display-name": "Get Bulk Job Status",
        },
        title="Get Bulk Job Status",
    )
    job_id: str = Field(..., title="Job ID", description="ID of the bulk job")


class SalesforceGetBulkJobResultsConfig(BaseModel):
    """Get results (successful or failed records) from a bulk job"""

    operation: Literal["get_bulk_job_results"] = Field(
        "get_bulk_job_results",
        json_schema_extra={
            "const": "get_bulk_job_results",
            "ui:hidden": True,
            "x-category": "Bulk Job",
            "x-is-trigger": False,
            "x-display-name": "Get Bulk Job Results",
        },
        title="Get Bulk Job Results",
    )
    job_id: str = Field(..., title="Job ID", description="ID of the bulk job")
    result_type: Literal["successful", "failed", "unprocessed"] = Field(
        "successful", title="Result Type", description="Type of results to retrieve"
    )


class SalesforceAbortBulkJobConfig(BaseModel):
    """Abort a bulk job"""

    operation: Literal["abort_bulk_data_job"] = Field(
        "abort_bulk_data_job",
        json_schema_extra={
            "const": "abort_bulk_data_job",
            "ui:hidden": True,
            "x-category": "Bulk Job",
            "x-is-trigger": False,
            "x-display-name": "Abort Bulk Data Job",
        },
        title="Abort Bulk Data Job",
    )
    job_id: str = Field(..., title="Job ID", description="ID of the bulk job to abort")


class SalesforceListBulkJobsConfig(BaseModel):
    """List bulk jobs"""

    operation: Literal["list_bulk_data_jobs"] = Field(
        "list_bulk_data_jobs",
        json_schema_extra={
            "const": "list_bulk_data_jobs",
            "ui:hidden": True,
            "x-category": "Bulk Job",
            "x-is-trigger": False,
            "x-display-name": "List Bulk Data Jobs",
        },
        title="List Bulk Data Jobs",
    )
    is_pk_chunking_enabled: Optional[bool] = Field(
        None,
        title="PK Chunking Enabled",
        description="Filter by PK chunking enabled status",
    )
    job_type: Optional[Literal["BigObjectIngest", "Classic", "V2Ingest"]] = Field(
        None, title="Job Type", description="Filter by job type"
    )


# ============================================================================
# Reports Operation Configs
# ============================================================================


class SalesforceListReportsConfig(BaseModel):
    """List available reports"""

    operation: Literal["list_available_reports"] = Field(
        "list_available_reports",
        json_schema_extra={
            "const": "list_available_reports",
            "ui:hidden": True,
            "x-category": "Report",
            "x-is-trigger": False,
            "x-display-name": "List Available Reports",
        },
        title="List Available Reports",
    )


class SalesforceRunReportConfig(BaseModel):
    """Execute a report and get results"""

    operation: Literal["execute_report_and_get_results"] = Field(
        "execute_report_and_get_results",
        json_schema_extra={
            "const": "execute_report_and_get_results",
            "ui:hidden": True,
            "x-category": "Report",
            "x-is-trigger": False,
            "x-display-name": "Execute Report and Get Results",
        },
        title="Execute Report and Get Results",
    )
    report_id: str = Field(
        ..., title="Report ID", description="ID of the report to run"
    )
    include_details: Optional[bool] = Field(
        True, title="Include Details", description="Include detail rows in the results"
    )


class SalesforceGetReportMetadataConfig(BaseModel):
    """Get metadata for a report"""

    operation: Literal["get_report_metadata"] = Field(
        "get_report_metadata",
        json_schema_extra={
            "const": "get_report_metadata",
            "ui:hidden": True,
            "x-category": "Report",
            "x-is-trigger": False,
            "x-display-name": "Get Report Metadata",
        },
        title="Get Report Metadata",
    )
    report_id: str = Field(..., title="Report ID", description="ID of the report")


# ============================================================================
# Tabs Operation Configs
# ============================================================================


class SalesforceGetTabsConfig(BaseModel):
    """Get available tabs for the user"""

    operation: Literal["get_user_available_tabs"] = Field(
        "get_user_available_tabs",
        json_schema_extra={
            "const": "get_user_available_tabs",
            "ui:hidden": True,
            "x-category": "Tab",
            "x-is-trigger": False,
            "x-display-name": "Get User Available Tabs",
        },
        title="Get User Available Tabs",
    )


# ============================================================================
# Deleted/Updated Records Operation Configs
# ============================================================================


class SalesforceGetDeletedConfig(BaseModel):
    """Get records deleted within a time range"""

    operation: Literal["get_deleted_records_in_range"] = Field(
        "get_deleted_records_in_range",
        json_schema_extra={
            "const": "get_deleted_records_in_range",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Get Deleted Records in Range",
        },
        title="Get Deleted Records in Range",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )
    start: str = Field(
        ...,
        title="Start Date/Time",
        description="Start of time range (ISO 8601 format, e.g., 2024-01-01T00:00:00Z)",
    )
    end: str = Field(
        ...,
        title="End Date/Time",
        description="End of time range (ISO 8601 format, e.g., 2024-01-31T23:59:59Z)",
    )


class SalesforceGetUpdatedConfig(BaseModel):
    """Get records updated within a time range"""

    operation: Literal["get_updated_records_in_range"] = Field(
        "get_updated_records_in_range",
        json_schema_extra={
            "const": "get_updated_records_in_range",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Get Updated Records in Range",
        },
        title="Get Updated Records in Range",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )
    start: str = Field(
        ...,
        title="Start Date/Time",
        description="Start of time range (ISO 8601 format, e.g., 2024-01-01T00:00:00Z)",
    )
    end: str = Field(
        ...,
        title="End Date/Time",
        description="End of time range (ISO 8601 format, e.g., 2024-01-31T23:59:59Z)",
    )


class SalesforceQueryAllConfig(BaseModel):
    """Execute a SOQL query including deleted and archived records"""

    operation: Literal["execute_soql_query_including_deleted"] = Field(
        "execute_soql_query_including_deleted",
        json_schema_extra={
            "const": "execute_soql_query_including_deleted",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Execute Soql Query Including Deleted",
        },
        title="Execute Soql Query Including Deleted",
    )
    query: str = Field(
        ...,
        title="SOQL Query",
        description="SOQL query string (includes deleted records via IsDeleted field)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# List Views Operation Configs
# ============================================================================


class SalesforceListListViewsConfig(BaseModel):
    """Get list views for an object"""

    operation: Literal["list_object_list_views"] = Field(
        "list_object_list_views",
        json_schema_extra={
            "const": "list_object_list_views",
            "ui:hidden": True,
            "x-category": "List View",
            "x-is-trigger": False,
            "x-display-name": "List Object List Views",
        },
        title="List Object List Views",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )


class SalesforceGetListViewConfig(BaseModel):
    """Get details of a specific list view"""

    operation: Literal["get_list_view_details"] = Field(
        "get_list_view_details",
        json_schema_extra={
            "const": "get_list_view_details",
            "ui:hidden": True,
            "x-category": "List View",
            "x-is-trigger": False,
            "x-display-name": "Get List View Details",
        },
        title="Get List View Details",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )
    listview_id: str = Field(
        ..., title="List View ID", description="ID of the list view"
    )


class SalesforceExecuteListViewConfig(BaseModel):
    """Execute a list view and get results"""

    operation: Literal["execute_list_view_query"] = Field(
        "execute_list_view_query",
        json_schema_extra={
            "const": "execute_list_view_query",
            "ui:hidden": True,
            "x-category": "List View",
            "x-is-trigger": False,
            "x-display-name": "Execute List View Query",
        },
        title="Execute List View Query",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type (e.g., Account, Contact)",
    )
    listview_id: str = Field(
        ..., title="List View ID", description="ID of the list view to execute"
    )
    limit: Optional[int] = Field(
        None, title="Limit", description="Maximum number of records to return"
    )
    offset: Optional[int] = Field(
        None, title="Offset", description="Starting row offset for pagination"
    )


# ============================================================================
# Dashboard Operation Configs
# ============================================================================


class SalesforceListDashboardsConfig(BaseModel):
    """List available dashboards"""

    operation: Literal["list_available_dashboards"] = Field(
        "list_available_dashboards",
        json_schema_extra={
            "const": "list_available_dashboards",
            "ui:hidden": True,
            "x-category": "Dashboard",
            "x-is-trigger": False,
            "x-display-name": "List Available Dashboards",
        },
        title="List Available Dashboards",
    )


class SalesforceGetDashboardConfig(BaseModel):
    """Get dashboard data and metadata"""

    operation: Literal["get_dashboard_data"] = Field(
        "get_dashboard_data",
        json_schema_extra={
            "const": "get_dashboard_data",
            "ui:hidden": True,
            "x-category": "Dashboard",
            "x-is-trigger": False,
            "x-display-name": "Get Dashboard Data",
        },
        title="Get Dashboard Data",
    )
    dashboard_id: str = Field(
        ..., title="Dashboard ID", description="ID of the dashboard"
    )


class SalesforceRefreshDashboardConfig(BaseModel):
    """Refresh a dashboard to get latest data"""

    operation: Literal["refresh_dashboard_data"] = Field(
        "refresh_dashboard_data",
        json_schema_extra={
            "const": "refresh_dashboard_data",
            "ui:hidden": True,
            "x-category": "Dashboard",
            "x-is-trigger": False,
            "x-display-name": "Refresh Dashboard Data",
        },
        title="Refresh Dashboard Data",
    )
    dashboard_id: str = Field(
        ..., title="Dashboard ID", description="ID of the dashboard to refresh"
    )


# ============================================================================
# Invocable Actions Operation Configs
# ============================================================================


class SalesforceListInvocableActionsConfig(BaseModel):
    """List available standard invocable actions"""

    operation: Literal["list_invocable_actions"] = Field(
        "list_invocable_actions",
        json_schema_extra={
            "const": "list_invocable_actions",
            "ui:hidden": True,
            "x-category": "Invocable Action",
            "x-is-trigger": False,
            "x-display-name": "List Invocable Actions",
        },
        title="List Invocable Actions",
    )
    action_type: Optional[Literal["standard", "custom"]] = Field(
        None,
        title="Action Type",
        description="Filter by action type (standard or custom). Leave empty for all.",
    )


class SalesforceGetInvocableActionConfig(BaseModel):
    """Get details of a specific invocable action"""

    operation: Literal["get_invocable_action_details"] = Field(
        "get_invocable_action_details",
        json_schema_extra={
            "const": "get_invocable_action_details",
            "ui:hidden": True,
            "x-category": "Invocable Action",
            "x-is-trigger": False,
            "x-display-name": "Get Invocable Action Details",
        },
        title="Get Invocable Action Details",
    )
    action_type: Literal["standard", "custom"] = Field(
        ..., title="Action Type", description="Type of action (standard or custom)"
    )
    action_name: str = Field(
        ..., title="Action Name", description="API name of the invocable action"
    )


class SalesforceExecuteInvocableActionConfig(BaseModel):
    """Execute an invocable action"""

    operation: Literal["execute_invocable_action"] = Field(
        "execute_invocable_action",
        json_schema_extra={
            "const": "execute_invocable_action",
            "ui:hidden": True,
            "x-category": "Invocable Action",
            "x-is-trigger": False,
            "x-display-name": "Execute Invocable Action",
        },
        title="Execute Invocable Action",
    )
    action_type: Literal["standard", "custom"] = Field(
        ..., title="Action Type", description="Type of action (standard or custom)"
    )
    action_name: str = Field(
        ..., title="Action Name", description="API name of the invocable action"
    )
    inputs: List[Dict[str, Any]] = Field(
        ..., title="Inputs", description="Array of input objects for the action"
    )


# ============================================================================
# Chatter Operation Configs
# ============================================================================


class SalesforcePostToChatterConfig(BaseModel):
    """Post a message to Chatter feed"""

    operation: Literal["post_message_to_chatter_feed"] = Field(
        "post_message_to_chatter_feed",
        json_schema_extra={
            "const": "post_message_to_chatter_feed",
            "ui:hidden": True,
            "x-category": "Chatter",
            "x-is-trigger": False,
            "x-display-name": "Post Message to Chatter Feed",
        },
        title="Post Message to Chatter Feed",
    )
    text: str = Field(
        ...,
        title="Message Text",
        description="Text content of the post",
        json_schema_extra={"ui:widget": "textarea"},
    )
    subject_id: Optional[str] = Field(
        None,
        title="Subject ID",
        description="ID of a record to post to (leave empty for user's own feed)",
    )


class SalesforceGetChatterFeedConfig(BaseModel):
    """Get Chatter feed items"""

    operation: Literal["get_chatter_feed_items"] = Field(
        "get_chatter_feed_items",
        json_schema_extra={
            "const": "get_chatter_feed_items",
            "ui:hidden": True,
            "x-category": "Chatter",
            "x-is-trigger": False,
            "x-display-name": "Get Chatter Feed Items",
        },
        title="Get Chatter Feed Items",
    )
    feed_type: Literal["news", "record", "user"] = Field(
        "news", title="Feed Type", description="Type of feed to retrieve"
    )
    subject_id: Optional[str] = Field(
        None,
        title="Subject ID",
        description="ID of record or user (required for record/user feed types)",
    )
    page_size: Optional[int] = Field(
        None, title="Page Size", description="Number of feed items to return"
    )


# ==== NEW ACTION CONFIGS ====

class SalesforceConvertLeadConfig(BaseModel):
    """Convert Lead"""

    operation: Literal["convert_lead"] = Field(
        "convert_lead",
        json_schema_extra={
            "const": "convert_lead",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Convert Lead",
            "x-keywords": ["convert lead", "lead to account contact opportunity", "qualify lead"],
        },
        title="Convert Lead",
    )
    lead_id: str = Field(
        ...,
        title="Lead ID",
        description="ID of the Lead to convert",
    )
    converted_status: Optional[str] = Field(
        'Closed - Converted',
        title="Converted Status",
        description="Lead status after conversion",
    )
    account_id: Optional[str] = Field(
        None,
        title="Account ID",
        description="Existing account to convert into (optional)",
    )
    contact_id: Optional[str] = Field(
        None,
        title="Contact ID",
        description="Existing contact to convert into (optional)",
    )
    opportunity_name: Optional[str] = Field(
        None,
        title="Opportunity Name",
        description="Name of opportunity to create (optional)",
    )
    do_not_create_opportunity: Optional[str] = Field(
        'false',
        title="Do Not Create Opportunity",
        description="Skip creating an opportunity",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )
    send_notification_email: Optional[str] = Field(
        'false',
        title="Send Notification Email",
        description="Send owner notification email",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )

class SalesforceMergeRecordsConfig(BaseModel):
    """Merge Records"""

    operation: Literal["merge_records"] = Field(
        "merge_records",
        json_schema_extra={
            "const": "merge_records",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Merge Records",
            "x-keywords": ["merge records", "merge duplicate accounts", "combine records"],
        },
        title="Merge Records",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object type (Account, Contact, or Lead)",
    )
    master_id: str = Field(
        ...,
        title="Master Record ID",
        description="ID of the surviving master record",
    )
    additional_ids: str = Field(
        ...,
        title="Additional IDs",
        description="Comma-separated or JSON array of record IDs to merge into master",
    )
    field_values: Optional[str] = Field(
        None,
        title="Field Overrides",
        description="Optional JSON of field values to set on the master",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceCreateTaskConfig(BaseModel):
    """Create Task"""

    operation: Literal["create_task"] = Field(
        "create_task",
        json_schema_extra={
            "const": "create_task",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Create Task",
            "x-keywords": ["create task", "add activity task", "new to-do"],
        },
        title="Create Task",
    )
    subject: str = Field(
        ...,
        title="Subject",
        description="Task subject",
    )
    status: Optional[str] = Field(
        'Not Started',
        title="Status",
        description="Task status",
        json_schema_extra={'enum': ['Not Started', 'In Progress', 'Completed', 'Waiting on someone else', 'Deferred'], 'x-enum-searchable': True},
    )
    priority: Optional[str] = Field(
        'Normal',
        title="Priority",
        description="Task priority",
        json_schema_extra={'enum': ['High', 'Normal', 'Low'], 'x-enum-searchable': True},
    )
    who_id: Optional[str] = Field(
        None,
        title="Who ID",
        description="Related Lead or Contact ID",
    )
    what_id: Optional[str] = Field(
        None,
        title="What ID",
        description="Related object ID (Account, Opportunity, etc.)",
    )
    activity_date: Optional[str] = Field(
        None,
        title="Due Date",
        description="Due date (YYYY-MM-DD)",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Task description",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    owner_id: Optional[str] = Field(
        None,
        title="Owner ID",
        description="User ID to assign the task to",
    )

class SalesforceUpdateTaskConfig(BaseModel):
    """Update Task"""

    operation: Literal["update_task"] = Field(
        "update_task",
        json_schema_extra={
            "const": "update_task",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Update Task",
            "x-keywords": ["update task", "edit task", "change activity"],
        },
        title="Update Task",
    )
    task_id: str = Field(
        ...,
        title="Task ID",
        description="ID of the task to update",
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="New status",
        json_schema_extra={'enum': ['Not Started', 'In Progress', 'Completed', 'Waiting on someone else', 'Deferred'], 'x-enum-searchable': True},
    )
    priority: Optional[str] = Field(
        None,
        title="Priority",
        description="New priority",
        json_schema_extra={'enum': ['High', 'Normal', 'Low'], 'x-enum-searchable': True},
    )
    subject: Optional[str] = Field(
        None,
        title="Subject",
        description="New subject",
    )
    activity_date: Optional[str] = Field(
        None,
        title="Due Date",
        description="New due date (YYYY-MM-DD)",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New description",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceCreateEventConfig(BaseModel):
    """Create Event"""

    operation: Literal["create_event"] = Field(
        "create_event",
        json_schema_extra={
            "const": "create_event",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Create Event",
            "x-keywords": ["create event", "add calendar event", "schedule meeting"],
        },
        title="Create Event",
    )
    subject: str = Field(
        ...,
        title="Subject",
        description="Event subject",
    )
    start_datetime: str = Field(
        ...,
        title="Start",
        description="Start datetime (ISO 8601)",
    )
    end_datetime: str = Field(
        ...,
        title="End",
        description="End datetime (ISO 8601)",
    )
    who_id: Optional[str] = Field(
        None,
        title="Who ID",
        description="Related Lead or Contact ID",
    )
    what_id: Optional[str] = Field(
        None,
        title="What ID",
        description="Related object ID",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Event description",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    location: Optional[str] = Field(
        None,
        title="Location",
        description="Event location",
    )
    owner_id: Optional[str] = Field(
        None,
        title="Owner ID",
        description="User ID to assign the event to",
    )

class SalesforceUpdateEventConfig(BaseModel):
    """Update Event"""

    operation: Literal["update_event"] = Field(
        "update_event",
        json_schema_extra={
            "const": "update_event",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Update Event",
            "x-keywords": ["update event", "edit calendar event", "reschedule meeting"],
        },
        title="Update Event",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to update",
    )
    subject: Optional[str] = Field(
        None,
        title="Subject",
        description="New subject",
    )
    start_datetime: Optional[str] = Field(
        None,
        title="Start",
        description="New start datetime (ISO 8601)",
    )
    end_datetime: Optional[str] = Field(
        None,
        title="End",
        description="New end datetime (ISO 8601)",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New description",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    location: Optional[str] = Field(
        None,
        title="Location",
        description="New location",
    )

class SalesforceCreateNoteConfig(BaseModel):
    """Create Note"""

    operation: Literal["create_note"] = Field(
        "create_note",
        json_schema_extra={
            "const": "create_note",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Create Note",
            "x-keywords": ["create note", "add note to record", "attach note"],
        },
        title="Create Note",
    )
    title: str = Field(
        ...,
        title="Title",
        description="Note title",
    )
    body: Optional[str] = Field(
        None,
        title="Body",
        description="Note text",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    parent_id: str = Field(
        ...,
        title="Parent Record ID",
        description="ID of the related record",
    )
    is_private: Optional[str] = Field(
        'false',
        title="Is Private",
        description="Whether the note is private",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )

class SalesforceAddCampaignMemberConfig(BaseModel):
    """Add Campaign Member"""

    operation: Literal["add_campaign_member"] = Field(
        "add_campaign_member",
        json_schema_extra={
            "const": "add_campaign_member",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Add Campaign Member",
            "x-keywords": ["add campaign member", "add lead to campaign", "add contact to campaign"],
        },
        title="Add Campaign Member",
    )
    campaign_id: str = Field(
        ...,
        title="Campaign ID",
        description="ID of the campaign",
    )
    lead_or_contact_id: str = Field(
        ...,
        title="Lead/Contact ID",
        description="ID of the Lead or Contact to add",
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Campaign member status",
    )

class SalesforceUpdateCampaignMemberStatusConfig(BaseModel):
    """Update Campaign Member Status"""

    operation: Literal["update_campaign_member_status"] = Field(
        "update_campaign_member_status",
        json_schema_extra={
            "const": "update_campaign_member_status",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Update Campaign Member Status",
            "x-keywords": ["update campaign member status", "change member status"],
        },
        title="Update Campaign Member Status",
    )
    member_id: str = Field(
        ...,
        title="Member ID",
        description="ID of the CampaignMember record",
    )
    status: str = Field(
        ...,
        title="Status",
        description="New campaign member status",
    )

class SalesforceCreateCampaignConfig(BaseModel):
    """Create Campaign"""

    operation: Literal["create_campaign"] = Field(
        "create_campaign",
        json_schema_extra={
            "const": "create_campaign",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Create Campaign",
            "x-keywords": ["create campaign", "new marketing campaign"],
        },
        title="Create Campaign",
    )
    name: str = Field(
        ...,
        title="Name",
        description="Campaign name",
    )
    type: Optional[str] = Field(
        None,
        title="Type",
        description="Campaign type",
    )
    status: Optional[str] = Field(
        'Planning',
        title="Status",
        description="Campaign status",
    )
    start_date: Optional[str] = Field(
        None,
        title="Start Date",
        description="Start date (YYYY-MM-DD)",
    )
    end_date: Optional[str] = Field(
        None,
        title="End Date",
        description="End date (YYYY-MM-DD)",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Campaign description",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    budget_cost: Optional[float] = Field(
        None,
        title="Budget Cost",
        description="Budgeted cost",
    )

class SalesforceAddCaseCommentConfig(BaseModel):
    """Add Case Comment"""

    operation: Literal["add_case_comment"] = Field(
        "add_case_comment",
        json_schema_extra={
            "const": "add_case_comment",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Add Case Comment",
            "x-keywords": ["add case comment", "comment on case", "case note"],
        },
        title="Add Case Comment",
    )
    parent_id: str = Field(
        ...,
        title="Case ID",
        description="ID of the parent Case",
    )
    comment_body: str = Field(
        ...,
        title="Comment",
        description="Comment text",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    is_published: Optional[str] = Field(
        'true',
        title="Is Published",
        description="Whether the comment is published/public",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )

class SalesforceAddOpportunityLineItemConfig(BaseModel):
    """Add Opportunity Line Item"""

    operation: Literal["add_opportunity_line_item"] = Field(
        "add_opportunity_line_item",
        json_schema_extra={
            "const": "add_opportunity_line_item",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Add Opportunity Line Item",
            "x-keywords": ["add opportunity line item", "add product to opportunity", "add opportunity product"],
        },
        title="Add Opportunity Line Item",
    )
    opportunity_id: str = Field(
        ...,
        title="Opportunity ID",
        description="ID of the opportunity",
    )
    pricebook_entry_id: str = Field(
        ...,
        title="Pricebook Entry ID",
        description="ID of the PricebookEntry (product)",
    )
    quantity: float = Field(
        ...,
        title="Quantity",
        description="Quantity of the product",
    )
    unit_price: Optional[float] = Field(
        None,
        title="Unit Price",
        description="Unit sales price",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Line item description",
    )

class SalesforceAddContactToOpportunityConfig(BaseModel):
    """Add Contact to Opportunity"""

    operation: Literal["add_contact_to_opportunity"] = Field(
        "add_contact_to_opportunity",
        json_schema_extra={
            "const": "add_contact_to_opportunity",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Add Contact to Opportunity",
            "x-keywords": ["add contact to opportunity", "opportunity contact role", "link contact opportunity"],
        },
        title="Add Contact to Opportunity",
    )
    opportunity_id: str = Field(
        ...,
        title="Opportunity ID",
        description="ID of the opportunity",
    )
    contact_id: str = Field(
        ...,
        title="Contact ID",
        description="ID of the contact",
    )
    role: Optional[str] = Field(
        None,
        title="Role",
        description="Contact role on the opportunity",
        json_schema_extra={'enum': ['Business User', 'Champion', 'Decision Maker', 'Economic Buyer', 'Economic Decision Maker', 'Evaluator', 'Executive Sponsor', 'Influencer', 'Technical Buyer', 'Other'], 'x-enum-searchable': True},
    )
    is_primary: Optional[str] = Field(
        'false',
        title="Is Primary",
        description="Whether this is the primary contact",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )

class SalesforceAssignPermissionSetConfig(BaseModel):
    """Assign Permission Set to User"""

    operation: Literal["assign_permission_set_to_user"] = Field(
        "assign_permission_set_to_user",
        json_schema_extra={
            "const": "assign_permission_set_to_user",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Assign Permission Set to User",
            "x-keywords": ["assign permission set", "grant permission set", "add permission set to user"],
        },
        title="Assign Permission Set to User",
    )
    permission_set_id: str = Field(
        ...,
        title="Permission Set ID",
        description="ID of the permission set",
    )
    assignee_id: str = Field(
        ...,
        title="Assignee ID",
        description="User ID to assign to",
    )

class SalesforceResetUserPasswordConfig(BaseModel):
    """Reset User Password"""

    operation: Literal["reset_user_password"] = Field(
        "reset_user_password",
        json_schema_extra={
            "const": "reset_user_password",
            "ui:hidden": True,
            "x-category": 'CRM Actions',
            "x-is-trigger": False,
            "x-display-name": "Reset User Password",
            "x-keywords": ["reset user password", "reset password"],
        },
        title="Reset User Password",
    )
    user_id: str = Field(
        ...,
        title="User ID",
        description="ID of the user whose password to reset",
    )

class SalesforceGetContentDocumentConfig(BaseModel):
    """Get Content Document"""

    operation: Literal["get_content_document"] = Field(
        "get_content_document",
        json_schema_extra={
            "const": "get_content_document",
            "ui:hidden": True,
            "x-category": 'Files',
            "x-is-trigger": False,
            "x-display-name": "Get Content Document",
            "x-keywords": ["get content document", "get file metadata", "retrieve document"],
        },
        title="Get Content Document",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="ContentDocument ID",
    )
    fields: Optional[str] = Field(
        None,
        title="Fields",
        description="Comma-separated field list (optional)",
    )

class SalesforceDownloadContentVersionConfig(BaseModel):
    """Download Content Version"""

    operation: Literal["download_content_version"] = Field(
        "download_content_version",
        json_schema_extra={
            "const": "download_content_version",
            "ui:hidden": True,
            "x-category": 'Files',
            "x-is-trigger": False,
            "x-display-name": "Download Content Version",
            "x-keywords": ["download content version", "download file", "get file data"],
        },
        title="Download Content Version",
    )
    version_id: str = Field(
        ...,
        title="Version ID",
        description="ContentVersion ID to download",
    )

class SalesforceListContentVersionsConfig(BaseModel):
    """List Content Versions"""

    operation: Literal["list_content_versions"] = Field(
        "list_content_versions",
        json_schema_extra={
            "const": "list_content_versions",
            "ui:hidden": True,
            "x-category": 'Files',
            "x-is-trigger": False,
            "x-display-name": "List Content Versions",
            "x-keywords": ["list content versions", "file versions", "document version history"],
        },
        title="List Content Versions",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="ContentDocument ID",
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Max versions to return",
    )

class SalesforceDeleteContentDocumentConfig(BaseModel):
    """Delete Content Document"""

    operation: Literal["delete_content_document"] = Field(
        "delete_content_document",
        json_schema_extra={
            "const": "delete_content_document",
            "ui:hidden": True,
            "x-category": 'Files',
            "x-is-trigger": False,
            "x-display-name": "Delete Content Document",
            "x-keywords": ["delete content document", "delete file", "remove document"],
        },
        title="Delete Content Document",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="ContentDocument ID to delete",
    )

class SalesforceCreateContentDocumentLinkConfig(BaseModel):
    """Create Content Document Link"""

    operation: Literal["create_content_document_link"] = Field(
        "create_content_document_link",
        json_schema_extra={
            "const": "create_content_document_link",
            "ui:hidden": True,
            "x-category": 'Files',
            "x-is-trigger": False,
            "x-display-name": "Create Content Document Link",
            "x-keywords": ["create content document link", "link file to record", "share file"],
        },
        title="Create Content Document Link",
    )
    content_document_id: str = Field(
        ...,
        title="Content Document ID",
        description="ContentDocument ID",
    )
    linked_entity_id: str = Field(
        ...,
        title="Linked Entity ID",
        description="Record ID to link the file to",
    )
    share_type: Optional[str] = Field(
        'V',
        title="Share Type",
        description="Share type: V=Viewer, C=Collaborator, I=Inferred",
        json_schema_extra={'enum': ['V', 'C', 'I'], 'x-enum-searchable': True},
    )
    visibility: Optional[str] = Field(
        None,
        title="Visibility",
        description="Visibility scope",
        json_schema_extra={'enum': ['AllUsers', 'InternalUsers', 'SharedUsers'], 'x-enum-searchable': True},
    )

class SalesforceListFilesLinkedToRecordConfig(BaseModel):
    """List Files Linked to Record"""

    operation: Literal["list_files_linked_to_record"] = Field(
        "list_files_linked_to_record",
        json_schema_extra={
            "const": "list_files_linked_to_record",
            "ui:hidden": True,
            "x-category": 'Files',
            "x-is-trigger": False,
            "x-display-name": "List Files Linked to Record",
            "x-keywords": ["list files linked to record", "files on record", "record attachments files"],
        },
        title="List Files Linked to Record",
    )
    record_id: str = Field(
        ...,
        title="Record ID",
        description="ID of the record to list linked files for",
    )

class SalesforceSendSingleEmailConfig(BaseModel):
    """Send Single Email"""

    operation: Literal["send_single_email"] = Field(
        "send_single_email",
        json_schema_extra={
            "const": "send_single_email",
            "ui:hidden": True,
            "x-category": 'Email',
            "x-is-trigger": False,
            "x-display-name": "Send Single Email",
            "x-keywords": ["send email", "send single email", "email contact"],
        },
        title="Send Single Email",
    )
    to_addresses: str = Field(
        ...,
        title="To",
        description="Comma-separated recipient email addresses",
    )
    subject: str = Field(
        ...,
        title="Subject",
        description="Email subject",
    )
    body: str = Field(
        ...,
        title="Body",
        description="Email body",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    cc_addresses: Optional[str] = Field(
        None,
        title="CC",
        description="Comma-separated CC addresses",
    )
    bcc_addresses: Optional[str] = Field(
        None,
        title="BCC",
        description="Comma-separated BCC addresses",
    )
    sender_display_name: Optional[str] = Field(
        None,
        title="Sender Display Name",
        description="Display name of the sender",
    )

class SalesforceSendEmailViaTemplateConfig(BaseModel):
    """Send Email via Template"""

    operation: Literal["send_email_via_template"] = Field(
        "send_email_via_template",
        json_schema_extra={
            "const": "send_email_via_template",
            "ui:hidden": True,
            "x-category": 'Email',
            "x-is-trigger": False,
            "x-display-name": "Send Email via Template",
            "x-keywords": ["send email via template", "templated email", "email from template"],
        },
        title="Send Email via Template",
    )
    template_id: str = Field(
        ...,
        title="Template ID",
        description="EmailTemplate ID",
    )
    recipient_id: str = Field(
        ...,
        title="Recipient ID",
        description="Contact or Lead ID (target object)",
    )
    what_id: Optional[str] = Field(
        None,
        title="What ID",
        description="Related record ID (optional)",
    )
    bcc_sender: Optional[str] = Field(
        'false',
        title="BCC Sender",
        description="BCC the sender",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )
    save_as_activity: Optional[str] = Field(
        'true',
        title="Save as Activity",
        description="Log the send as an activity",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )

class SalesforceListEmailTemplatesConfig(BaseModel):
    """List Email Templates"""

    operation: Literal["list_email_templates"] = Field(
        "list_email_templates",
        json_schema_extra={
            "const": "list_email_templates",
            "ui:hidden": True,
            "x-category": 'Email',
            "x-is-trigger": False,
            "x-display-name": "List Email Templates",
            "x-keywords": ["list email templates", "available templates", "email templates"],
        },
        title="List Email Templates",
    )
    folder_name: Optional[str] = Field(
        None,
        title="Folder Name",
        description="Filter by folder name (optional)",
    )
    page_size: Optional[int] = Field(
        200,
        title="Page Size",
        description="Max templates to return",
    )

class SalesforceSendMassEmailConfig(BaseModel):
    """Send Mass Email"""

    operation: Literal["send_mass_email"] = Field(
        "send_mass_email",
        json_schema_extra={
            "const": "send_mass_email",
            "ui:hidden": True,
            "x-category": 'Email',
            "x-is-trigger": False,
            "x-display-name": "Send Mass Email",
            "x-keywords": ["send mass email", "bulk email", "mass send email"],
        },
        title="Send Mass Email",
    )
    template_id: str = Field(
        ...,
        title="Template ID",
        description="EmailTemplate ID",
    )
    target_ids: str = Field(
        ...,
        title="Target IDs",
        description="JSON array or comma-separated Contact/Lead IDs",
    )
    activity_date: Optional[str] = Field(
        None,
        title="Activity Date",
        description="Activity date (YYYY-MM-DD)",
    )

class SalesforceGetChatterFeedItemConfig(BaseModel):
    """Get Chatter Feed Item"""

    operation: Literal["get_chatter_feed_item"] = Field(
        "get_chatter_feed_item",
        json_schema_extra={
            "const": "get_chatter_feed_item",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Get Chatter Feed Item",
            "x-keywords": ["get chatter feed item", "get chatter post"],
        },
        title="Get Chatter Feed Item",
    )
    feed_item_id: str = Field(
        ...,
        title="Feed Item ID",
        description="Chatter feed item ID",
    )

class SalesforceDeleteChatterFeedItemConfig(BaseModel):
    """Delete Chatter Feed Item"""

    operation: Literal["delete_chatter_feed_item"] = Field(
        "delete_chatter_feed_item",
        json_schema_extra={
            "const": "delete_chatter_feed_item",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Delete Chatter Feed Item",
            "x-keywords": ["delete chatter feed item", "delete chatter post", "remove post"],
        },
        title="Delete Chatter Feed Item",
    )
    feed_item_id: str = Field(
        ...,
        title="Feed Item ID",
        description="Chatter feed item ID",
    )

class SalesforceCreateChatterCommentConfig(BaseModel):
    """Create Chatter Comment"""

    operation: Literal["create_chatter_comment"] = Field(
        "create_chatter_comment",
        json_schema_extra={
            "const": "create_chatter_comment",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Create Chatter Comment",
            "x-keywords": ["create chatter comment", "comment on chatter post", "reply to post"],
        },
        title="Create Chatter Comment",
    )
    feed_item_id: str = Field(
        ...,
        title="Feed Item ID",
        description="Chatter feed item ID",
    )
    message_text: str = Field(
        ...,
        title="Message",
        description="Comment text",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceGetChatterCommentsConfig(BaseModel):
    """Get Chatter Comments"""

    operation: Literal["get_chatter_comments"] = Field(
        "get_chatter_comments",
        json_schema_extra={
            "const": "get_chatter_comments",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Get Chatter Comments",
            "x-keywords": ["get chatter comments", "list post comments"],
        },
        title="Get Chatter Comments",
    )
    feed_item_id: str = Field(
        ...,
        title="Feed Item ID",
        description="Chatter feed item ID",
    )
    page_size: Optional[int] = Field(
        25,
        title="Page Size",
        description="Max comments to return",
    )

class SalesforceDeleteChatterCommentConfig(BaseModel):
    """Delete Chatter Comment"""

    operation: Literal["delete_chatter_comment"] = Field(
        "delete_chatter_comment",
        json_schema_extra={
            "const": "delete_chatter_comment",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Delete Chatter Comment",
            "x-keywords": ["delete chatter comment", "remove comment"],
        },
        title="Delete Chatter Comment",
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="Chatter comment ID",
    )

class SalesforceLikeChatterFeedItemConfig(BaseModel):
    """Like Chatter Feed Item"""

    operation: Literal["like_chatter_feed_item"] = Field(
        "like_chatter_feed_item",
        json_schema_extra={
            "const": "like_chatter_feed_item",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Like Chatter Feed Item",
            "x-keywords": ["like chatter post", "like feed item"],
        },
        title="Like Chatter Feed Item",
    )
    feed_item_id: str = Field(
        ...,
        title="Feed Item ID",
        description="Chatter feed item ID",
    )

class SalesforceGetRecordChatterFeedConfig(BaseModel):
    """Get Record Chatter Feed"""

    operation: Literal["get_record_chatter_feed"] = Field(
        "get_record_chatter_feed",
        json_schema_extra={
            "const": "get_record_chatter_feed",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Get Record Chatter Feed",
            "x-keywords": ["get record chatter feed", "record feed elements"],
        },
        title="Get Record Chatter Feed",
    )
    record_id: str = Field(
        ...,
        title="Record ID",
        description="Record ID whose feed to retrieve",
    )
    page_size: Optional[int] = Field(
        25,
        title="Page Size",
        description="Max feed elements to return",
    )

class SalesforceGetChatterUserProfileConfig(BaseModel):
    """Get Chatter User Profile"""

    operation: Literal["get_chatter_user_profile"] = Field(
        "get_chatter_user_profile",
        json_schema_extra={
            "const": "get_chatter_user_profile",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Get Chatter User Profile",
            "x-keywords": ["get chatter user profile", "chatter user info"],
        },
        title="Get Chatter User Profile",
    )
    user_id: Optional[str] = Field(
        'me',
        title="User ID",
        description="User ID (use 'me' for current user)",
    )

class SalesforceListChatterGroupsConfig(BaseModel):
    """List Chatter Groups"""

    operation: Literal["list_chatter_groups"] = Field(
        "list_chatter_groups",
        json_schema_extra={
            "const": "list_chatter_groups",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "List Chatter Groups",
            "x-keywords": ["list chatter groups", "chatter groups"],
        },
        title="List Chatter Groups",
    )
    page_size: Optional[int] = Field(
        25,
        title="Page Size",
        description="Max groups to return",
    )
    search_query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Filter groups by name (optional)",
    )

class SalesforcePostToChatterGroupConfig(BaseModel):
    """Post to Chatter Group"""

    operation: Literal["post_to_chatter_group"] = Field(
        "post_to_chatter_group",
        json_schema_extra={
            "const": "post_to_chatter_group",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Post to Chatter Group",
            "x-keywords": ["post to chatter group", "group post"],
        },
        title="Post to Chatter Group",
    )
    group_id: str = Field(
        ...,
        title="Group ID",
        description="Chatter group ID",
    )
    message_text: str = Field(
        ...,
        title="Message",
        description="Post text",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    mention_ids: Optional[str] = Field(
        None,
        title="Mention IDs",
        description="Comma-separated user IDs to @mention",
    )

class SalesforceGetChatterGroupMembersConfig(BaseModel):
    """Get Chatter Group Members"""

    operation: Literal["get_chatter_group_members"] = Field(
        "get_chatter_group_members",
        json_schema_extra={
            "const": "get_chatter_group_members",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Get Chatter Group Members",
            "x-keywords": ["get chatter group members", "group members"],
        },
        title="Get Chatter Group Members",
    )
    group_id: str = Field(
        ...,
        title="Group ID",
        description="Chatter group ID",
    )
    page_size: Optional[int] = Field(
        25,
        title="Page Size",
        description="Max members to return",
    )

class SalesforceSendChatterDirectMessageConfig(BaseModel):
    """Send Chatter Direct Message"""

    operation: Literal["send_chatter_direct_message"] = Field(
        "send_chatter_direct_message",
        json_schema_extra={
            "const": "send_chatter_direct_message",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Send Chatter Direct Message",
            "x-keywords": ["send chatter direct message", "chatter dm", "private message"],
        },
        title="Send Chatter Direct Message",
    )
    recipient_ids: str = Field(
        ...,
        title="Recipient IDs",
        description="Comma-separated user IDs",
    )
    message_text: str = Field(
        ...,
        title="Message",
        description="Message text",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceGetChatterDirectMessagesConfig(BaseModel):
    """Get Chatter Direct Messages"""

    operation: Literal["get_chatter_direct_messages"] = Field(
        "get_chatter_direct_messages",
        json_schema_extra={
            "const": "get_chatter_direct_messages",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Get Chatter Direct Messages",
            "x-keywords": ["get chatter direct messages", "list dms"],
        },
        title="Get Chatter Direct Messages",
    )
    page_size: Optional[int] = Field(
        25,
        title="Page Size",
        description="Max messages to return",
    )
    conversation_id: Optional[str] = Field(
        None,
        title="Conversation ID",
        description="Specific conversation ID (optional)",
    )

class SalesforceSearchChatterConfig(BaseModel):
    """Search Chatter"""

    operation: Literal["search_chatter"] = Field(
        "search_chatter",
        json_schema_extra={
            "const": "search_chatter",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Search Chatter",
            "x-keywords": ["search chatter", "find chatter posts"],
        },
        title="Search Chatter",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Search text",
    )
    page_size: Optional[int] = Field(
        25,
        title="Page Size",
        description="Max results to return",
    )

class SalesforceGetChatterNewsFeedConfig(BaseModel):
    """Get Chatter News Feed"""

    operation: Literal["get_chatter_news_feed"] = Field(
        "get_chatter_news_feed",
        json_schema_extra={
            "const": "get_chatter_news_feed",
            "ui:hidden": True,
            "x-category": 'Chatter',
            "x-is-trigger": False,
            "x-display-name": "Get Chatter News Feed",
            "x-keywords": ["get chatter news feed", "my feed", "news feed"],
        },
        title="Get Chatter News Feed",
    )
    page_size: Optional[int] = Field(
        25,
        title="Page Size",
        description="Max feed elements to return",
    )

class SalesforceExecuteAnonymousApexConfig(BaseModel):
    """Execute Anonymous Apex"""

    operation: Literal["execute_anonymous_apex"] = Field(
        "execute_anonymous_apex",
        json_schema_extra={
            "const": "execute_anonymous_apex",
            "ui:hidden": True,
            "x-category": 'Developer Tools',
            "x-is-trigger": False,
            "x-display-name": "Execute Anonymous Apex",
            "x-keywords": ["execute anonymous apex", "run apex code", "anonymous apex"],
        },
        title="Execute Anonymous Apex",
    )
    apex_code: str = Field(
        ...,
        title="Apex Code",
        description="Anonymous Apex code to execute",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceRunApexTestsConfig(BaseModel):
    """Run Apex Tests"""

    operation: Literal["run_apex_tests"] = Field(
        "run_apex_tests",
        json_schema_extra={
            "const": "run_apex_tests",
            "ui:hidden": True,
            "x-category": 'Developer Tools',
            "x-is-trigger": False,
            "x-display-name": "Run Apex Tests",
            "x-keywords": ["run apex tests", "execute tests", "apex test run"],
        },
        title="Run Apex Tests",
    )
    class_names: Optional[str] = Field(
        None,
        title="Class Names",
        description="Comma-separated Apex test class names",
    )
    suite_ids: Optional[str] = Field(
        None,
        title="Suite IDs",
        description="Comma-separated test suite IDs",
    )
    max_failed_tests: Optional[int] = Field(
        -1,
        title="Max Failed Tests",
        description="Abort after this many failures (-1 = no limit)",
    )

class SalesforceGetApexTestResultsConfig(BaseModel):
    """Get Apex Test Results"""

    operation: Literal["get_apex_test_results"] = Field(
        "get_apex_test_results",
        json_schema_extra={
            "const": "get_apex_test_results",
            "ui:hidden": True,
            "x-category": 'Developer Tools',
            "x-is-trigger": False,
            "x-display-name": "Get Apex Test Results",
            "x-keywords": ["get apex test results", "test results", "test queue status"],
        },
        title="Get Apex Test Results",
    )
    job_id: str = Field(
        ...,
        title="Job ID",
        description="Parent job ID of the test run",
    )

class SalesforceQueryDebugLogsConfig(BaseModel):
    """Query Debug Logs"""

    operation: Literal["query_debug_logs"] = Field(
        "query_debug_logs",
        json_schema_extra={
            "const": "query_debug_logs",
            "ui:hidden": True,
            "x-category": 'Developer Tools',
            "x-is-trigger": False,
            "x-display-name": "Query Debug Logs",
            "x-keywords": ["query debug logs", "list apex logs", "debug logs"],
        },
        title="Query Debug Logs",
    )
    user_id: Optional[str] = Field(
        None,
        title="User ID",
        description="Filter logs by user (optional)",
    )
    page_size: Optional[int] = Field(
        20,
        title="Page Size",
        description="Max logs to return",
    )

class SalesforceGetDebugLogBodyConfig(BaseModel):
    """Get Debug Log Body"""

    operation: Literal["get_debug_log_body"] = Field(
        "get_debug_log_body",
        json_schema_extra={
            "const": "get_debug_log_body",
            "ui:hidden": True,
            "x-category": 'Developer Tools',
            "x-is-trigger": False,
            "x-display-name": "Get Debug Log Body",
            "x-keywords": ["get debug log body", "read apex log", "log content"],
        },
        title="Get Debug Log Body",
    )
    log_id: str = Field(
        ...,
        title="Log ID",
        description="ApexLog ID",
    )

class SalesforceCreateTraceFlagConfig(BaseModel):
    """Create Trace Flag"""

    operation: Literal["create_trace_flag"] = Field(
        "create_trace_flag",
        json_schema_extra={
            "const": "create_trace_flag",
            "ui:hidden": True,
            "x-category": 'Developer Tools',
            "x-is-trigger": False,
            "x-display-name": "Create Trace Flag",
            "x-keywords": ["create trace flag", "enable debug logging", "trace flag"],
        },
        title="Create Trace Flag",
    )
    traced_entity_id: str = Field(
        ...,
        title="Traced Entity ID",
        description="User ID or class ID to trace",
    )
    debug_level_id: str = Field(
        ...,
        title="Debug Level ID",
        description="DebugLevel ID",
    )
    expiration_date: str = Field(
        ...,
        title="Expiration Date",
        description="Expiration datetime (ISO 8601)",
    )
    log_type: Optional[str] = Field(
        'USER_DEBUG',
        title="Log Type",
        description="Type of trace",
        json_schema_extra={'enum': ['USER_DEBUG', 'CLASS', 'TRIGGER', 'VALIDATION', 'WORKFLOW'], 'x-enum-searchable': True},
    )

class SalesforceGetApexCodeCoverageConfig(BaseModel):
    """Get Apex Code Coverage"""

    operation: Literal["get_apex_code_coverage"] = Field(
        "get_apex_code_coverage",
        json_schema_extra={
            "const": "get_apex_code_coverage",
            "ui:hidden": True,
            "x-category": 'Developer Tools',
            "x-is-trigger": False,
            "x-display-name": "Get Apex Code Coverage",
            "x-keywords": ["get apex code coverage", "test coverage", "code coverage"],
        },
        title="Get Apex Code Coverage",
    )
    class_name_filter: Optional[str] = Field(
        None,
        title="Class Name Filter",
        description="Filter by class/trigger name (optional)",
    )

class SalesforceToolingSoqlQueryConfig(BaseModel):
    """Tooling SOQL Query"""

    operation: Literal["tooling_soql_query"] = Field(
        "tooling_soql_query",
        json_schema_extra={
            "const": "tooling_soql_query",
            "ui:hidden": True,
            "x-category": 'Developer Tools',
            "x-is-trigger": False,
            "x-display-name": "Tooling SOQL Query",
            "x-keywords": ["tooling soql query", "query tooling api", "query apex class"],
        },
        title="Tooling SOQL Query",
    )
    query: str = Field(
        ...,
        title="Query",
        description="SOQL query against Tooling API objects",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceGetPendingApprovalItemsConfig(BaseModel):
    """Get Pending Approval Items"""

    operation: Literal["get_pending_approval_items"] = Field(
        "get_pending_approval_items",
        json_schema_extra={
            "const": "get_pending_approval_items",
            "ui:hidden": True,
            "x-category": 'Approval',
            "x-is-trigger": False,
            "x-display-name": "Get Pending Approval Items",
            "x-keywords": ["get pending approval items", "my approvals", "pending approvals"],
        },
        title="Get Pending Approval Items",
    )

class SalesforceRecallApprovalRequestConfig(BaseModel):
    """Recall Approval Request"""

    operation: Literal["recall_approval_request"] = Field(
        "recall_approval_request",
        json_schema_extra={
            "const": "recall_approval_request",
            "ui:hidden": True,
            "x-category": 'Approval',
            "x-is-trigger": False,
            "x-display-name": "Recall Approval Request",
            "x-keywords": ["recall approval request", "withdraw approval", "cancel approval"],
        },
        title="Recall Approval Request",
    )
    process_instance_id: str = Field(
        ...,
        title="Process Instance ID",
        description="Work item / process instance context ID",
    )
    comments: Optional[str] = Field(
        None,
        title="Comments",
        description="Recall comments (optional)",
    )

class SalesforceGetApprovalHistoryConfig(BaseModel):
    """Get Approval History"""

    operation: Literal["get_approval_history"] = Field(
        "get_approval_history",
        json_schema_extra={
            "const": "get_approval_history",
            "ui:hidden": True,
            "x-category": 'Approval',
            "x-is-trigger": False,
            "x-display-name": "Get Approval History",
            "x-keywords": ["get approval history", "approval steps", "process instance steps"],
        },
        title="Get Approval History",
    )
    record_id: str = Field(
        ...,
        title="Record ID",
        description="Target record ID whose approval history to fetch",
    )

class SalesforceGetBulkJobFailedResultsConfig(BaseModel):
    """Get Bulk Job Failed Results"""

    operation: Literal["get_bulk_job_failed_results"] = Field(
        "get_bulk_job_failed_results",
        json_schema_extra={
            "const": "get_bulk_job_failed_results",
            "ui:hidden": True,
            "x-category": 'Bulk Job',
            "x-is-trigger": False,
            "x-display-name": "Get Bulk Job Failed Results",
            "x-keywords": ["get bulk job failed results", "bulk failures"],
        },
        title="Get Bulk Job Failed Results",
    )
    job_id: str = Field(
        ...,
        title="Job ID",
        description="Bulk ingest job ID",
    )

class SalesforceGetBulkJobUnprocessedResultsConfig(BaseModel):
    """Get Bulk Job Unprocessed Results"""

    operation: Literal["get_bulk_job_unprocessed_results"] = Field(
        "get_bulk_job_unprocessed_results",
        json_schema_extra={
            "const": "get_bulk_job_unprocessed_results",
            "ui:hidden": True,
            "x-category": 'Bulk Job',
            "x-is-trigger": False,
            "x-display-name": "Get Bulk Job Unprocessed Results",
            "x-keywords": ["get bulk job unprocessed results", "bulk unprocessed"],
        },
        title="Get Bulk Job Unprocessed Results",
    )
    job_id: str = Field(
        ...,
        title="Job ID",
        description="Bulk ingest job ID",
    )

class SalesforceDeleteBulkDataJobConfig(BaseModel):
    """Delete Bulk Data Job"""

    operation: Literal["delete_bulk_data_job"] = Field(
        "delete_bulk_data_job",
        json_schema_extra={
            "const": "delete_bulk_data_job",
            "ui:hidden": True,
            "x-category": 'Bulk Job',
            "x-is-trigger": False,
            "x-display-name": "Delete Bulk Data Job",
            "x-keywords": ["delete bulk data job", "remove bulk job"],
        },
        title="Delete Bulk Data Job",
    )
    job_id: str = Field(
        ...,
        title="Job ID",
        description="Bulk ingest job ID",
    )

class SalesforceCreateBulkQueryJobConfig(BaseModel):
    """Create Bulk Query Job"""

    operation: Literal["create_bulk_query_job"] = Field(
        "create_bulk_query_job",
        json_schema_extra={
            "const": "create_bulk_query_job",
            "ui:hidden": True,
            "x-category": 'Bulk Job',
            "x-is-trigger": False,
            "x-display-name": "Create Bulk Query Job",
            "x-keywords": ["create bulk query job", "bulk query", "async query job"],
        },
        title="Create Bulk Query Job",
    )
    soql_query: str = Field(
        ...,
        title="SOQL Query",
        description="SOQL query for the bulk query job",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    column_delimiter: Optional[str] = Field(
        'COMMA',
        title="Column Delimiter",
        description="CSV column delimiter",
        json_schema_extra={'enum': ['COMMA', 'TAB', 'PIPE', 'SEMICOLON', 'CARET', 'BACKQUOTE'], 'x-enum-searchable': True},
    )
    line_ending: Optional[str] = Field(
        'LF',
        title="Line Ending",
        description="CSV line ending",
        json_schema_extra={'enum': ['LF', 'CRLF'], 'x-enum-searchable': True},
    )

class SalesforceGetBulkQueryJobResultsConfig(BaseModel):
    """Get Bulk Query Job Results"""

    operation: Literal["get_bulk_query_job_results"] = Field(
        "get_bulk_query_job_results",
        json_schema_extra={
            "const": "get_bulk_query_job_results",
            "ui:hidden": True,
            "x-category": 'Bulk Job',
            "x-is-trigger": False,
            "x-display-name": "Get Bulk Query Job Results",
            "x-keywords": ["get bulk query job results", "bulk query results"],
        },
        title="Get Bulk Query Job Results",
    )
    job_id: str = Field(
        ...,
        title="Job ID",
        description="Bulk query job ID",
    )
    locator: Optional[str] = Field(
        None,
        title="Locator",
        description="Pagination locator (optional)",
    )
    max_records: Optional[int] = Field(
        50000,
        title="Max Records",
        description="Max records per page",
    )

class SalesforceExecuteCompositeBatchConfig(BaseModel):
    """Execute Composite Batch"""

    operation: Literal["execute_composite_batch"] = Field(
        "execute_composite_batch",
        json_schema_extra={
            "const": "execute_composite_batch",
            "ui:hidden": True,
            "x-category": 'Composite Request',
            "x-is-trigger": False,
            "x-display-name": "Execute Composite Batch",
            "x-keywords": ["execute composite batch", "batch requests", "composite batch"],
        },
        title="Execute Composite Batch",
    )
    subrequests: str = Field(
        ...,
        title="Subrequests",
        description="JSON array of subrequest objects",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    halt_on_error: Optional[str] = Field(
        'false',
        title="Halt on Error",
        description="Stop on first error",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )

class SalesforceBulkRetrieveRecordsConfig(BaseModel):
    """Bulk Retrieve Records"""

    operation: Literal["bulk_retrieve_records"] = Field(
        "bulk_retrieve_records",
        json_schema_extra={
            "const": "bulk_retrieve_records",
            "ui:hidden": True,
            "x-category": 'Composite Request',
            "x-is-trigger": False,
            "x-display-name": "Bulk Retrieve Records",
            "x-keywords": ["bulk retrieve records", "get multiple records", "retrieve by ids"],
        },
        title="Bulk Retrieve Records",
    )
    sobject_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type",
    )
    record_ids: str = Field(
        ...,
        title="Record IDs",
        description="JSON array or comma-separated record IDs",
    )
    fields: Optional[str] = Field(
        None,
        title="Fields",
        description="Comma-separated field names",
    )

class SalesforceCompositeUpdateMultipleConfig(BaseModel):
    """Composite Update Multiple"""

    operation: Literal["composite_update_multiple"] = Field(
        "composite_update_multiple",
        json_schema_extra={
            "const": "composite_update_multiple",
            "ui:hidden": True,
            "x-category": 'Composite Request',
            "x-is-trigger": False,
            "x-display-name": "Composite Update Multiple",
            "x-keywords": ["composite update multiple", "update multiple mixed", "update records collection"],
        },
        title="Composite Update Multiple",
    )
    records: str = Field(
        ...,
        title="Records",
        description="JSON array of records (each with attributes.type and Id)",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    all_or_none: Optional[str] = Field(
        'false',
        title="All or None",
        description="Atomic transaction",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )

class SalesforceRunReportAsyncConfig(BaseModel):
    """Run Report Async"""

    operation: Literal["run_report_async"] = Field(
        "run_report_async",
        json_schema_extra={
            "const": "run_report_async",
            "ui:hidden": True,
            "x-category": 'Report',
            "x-is-trigger": False,
            "x-display-name": "Run Report Async",
            "x-keywords": ["run report async", "async report", "report instance"],
        },
        title="Run Report Async",
    )
    report_id: str = Field(
        ...,
        title="Report ID",
        description="ID of the report",
    )
    filters: Optional[str] = Field(
        None,
        title="Filters",
        description="JSON array of filter overrides (optional)",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceGetAsyncReportResultConfig(BaseModel):
    """Get Async Report Result"""

    operation: Literal["get_async_report_result"] = Field(
        "get_async_report_result",
        json_schema_extra={
            "const": "get_async_report_result",
            "ui:hidden": True,
            "x-category": 'Report',
            "x-is-trigger": False,
            "x-display-name": "Get Async Report Result",
            "x-keywords": ["get async report result", "report instance result"],
        },
        title="Get Async Report Result",
    )
    report_id: str = Field(
        ...,
        title="Report ID",
        description="ID of the report",
    )
    instance_id: str = Field(
        ...,
        title="Instance ID",
        description="Report instance ID",
    )

class SalesforceGetDashboardComponentDataConfig(BaseModel):
    """Get Dashboard Component Data"""

    operation: Literal["get_dashboard_component_data"] = Field(
        "get_dashboard_component_data",
        json_schema_extra={
            "const": "get_dashboard_component_data",
            "ui:hidden": True,
            "x-category": 'Dashboard',
            "x-is-trigger": False,
            "x-display-name": "Get Dashboard Component Data",
            "x-keywords": ["get dashboard component data", "dashboard component"],
        },
        title="Get Dashboard Component Data",
    )
    dashboard_id: str = Field(
        ...,
        title="Dashboard ID",
        description="Dashboard ID",
    )
    component_id: str = Field(
        ...,
        title="Component ID",
        description="Component ID",
    )

class SalesforceListReportFoldersConfig(BaseModel):
    """List Report Folders"""

    operation: Literal["list_report_folders"] = Field(
        "list_report_folders",
        json_schema_extra={
            "const": "list_report_folders",
            "ui:hidden": True,
            "x-category": 'Report',
            "x-is-trigger": False,
            "x-display-name": "List Report Folders",
            "x-keywords": ["list report folders", "report folders", "analytics folders"],
        },
        title="List Report Folders",
    )
    type: Optional[str] = Field(
        'report',
        title="Type",
        description="Folder type",
        json_schema_extra={'enum': ['report', 'dashboard', 'both'], 'x-enum-searchable': True},
    )
    page_size: Optional[int] = Field(
        50,
        title="Page Size",
        description="Max folders to return",
    )

class SalesforceExecuteFlowConfig(BaseModel):
    """Execute Flow"""

    operation: Literal["execute_flow"] = Field(
        "execute_flow",
        json_schema_extra={
            "const": "execute_flow",
            "ui:hidden": True,
            "x-category": 'Flow',
            "x-is-trigger": False,
            "x-display-name": "Execute Flow",
            "x-keywords": ["execute flow", "run flow", "trigger flow"],
        },
        title="Execute Flow",
    )
    flow_api_name: str = Field(
        ...,
        title="Flow API Name",
        description="API name of the active flow",
    )
    input_variables: Optional[str] = Field(
        None,
        title="Input Variables",
        description="JSON object of variable name to value",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceListFlowsConfig(BaseModel):
    """List Flows"""

    operation: Literal["list_flows"] = Field(
        "list_flows",
        json_schema_extra={
            "const": "list_flows",
            "ui:hidden": True,
            "x-category": 'Flow',
            "x-is-trigger": False,
            "x-display-name": "List Flows",
            "x-keywords": ["list flows", "available flows", "active flows"],
        },
        title="List Flows",
    )
    process_type: Optional[str] = Field(
        None,
        title="Process Type",
        description="Filter by flow process type (optional)",
    )

class SalesforceInvokeEmailAlertActionConfig(BaseModel):
    """Invoke Email Alert Action"""

    operation: Literal["invoke_email_alert_action"] = Field(
        "invoke_email_alert_action",
        json_schema_extra={
            "const": "invoke_email_alert_action",
            "ui:hidden": True,
            "x-category": 'Flow',
            "x-is-trigger": False,
            "x-display-name": "Invoke Email Alert Action",
            "x-keywords": ["invoke email alert", "send email alert action"],
        },
        title="Invoke Email Alert Action",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object the email alert belongs to",
    )
    action_name: str = Field(
        ...,
        title="Action Name",
        description="API name of the email alert",
    )
    record_id: str = Field(
        ...,
        title="Record ID",
        description="Record ID to run the action on",
    )
    context_id: Optional[str] = Field(
        None,
        title="Context ID",
        description="Context ID (optional)",
    )

class SalesforceInvokeFieldUpdateActionConfig(BaseModel):
    """Invoke Field Update Action"""

    operation: Literal["invoke_field_update_action"] = Field(
        "invoke_field_update_action",
        json_schema_extra={
            "const": "invoke_field_update_action",
            "ui:hidden": True,
            "x-category": 'Flow',
            "x-is-trigger": False,
            "x-display-name": "Invoke Field Update Action",
            "x-keywords": ["invoke field update", "field update action"],
        },
        title="Invoke Field Update Action",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Object the field update belongs to",
    )
    action_name: str = Field(
        ...,
        title="Action Name",
        description="API name of the field update",
    )
    record_id: str = Field(
        ...,
        title="Record ID",
        description="Record ID to run the action on",
    )

class SalesforceGetOrgInfoConfig(BaseModel):
    """Get Org Info"""

    operation: Literal["get_org_info"] = Field(
        "get_org_info",
        json_schema_extra={
            "const": "get_org_info",
            "ui:hidden": True,
            "x-category": 'Org',
            "x-is-trigger": False,
            "x-display-name": "Get Org Info",
            "x-keywords": ["get org info", "organization info", "org details"],
        },
        title="Get Org Info",
    )

class SalesforceParameterizedSearchConfig(BaseModel):
    """Parameterized Search"""

    operation: Literal["parameterized_search"] = Field(
        "parameterized_search",
        json_schema_extra={
            "const": "parameterized_search",
            "ui:hidden": True,
            "x-category": 'Record',
            "x-is-trigger": False,
            "x-display-name": "Parameterized Search",
            "x-keywords": ["parameterized search", "structured search", "search objects fields"],
        },
        title="Parameterized Search",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Search text",
    )
    sobjects: str = Field(
        ...,
        title="Objects",
        description="JSON array of object/field specs",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    page_size: Optional[int] = Field(
        20,
        title="Page Size",
        description="Max results to return",
    )

class SalesforceGetSearchSuggestionsConfig(BaseModel):
    """Get Search Suggestions"""

    operation: Literal["get_search_suggestions"] = Field(
        "get_search_suggestions",
        json_schema_extra={
            "const": "get_search_suggestions",
            "ui:hidden": True,
            "x-category": 'Record',
            "x-is-trigger": False,
            "x-display-name": "Get Search Suggestions",
            "x-keywords": ["get search suggestions", "autocomplete search", "search suggestions"],
        },
        title="Get Search Suggestions",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Partial search text",
    )
    sobject_type: Optional[str] = Field(
        'Account',
        title="Object Type",
        description="Object to suggest from",
    )
    page_size: Optional[int] = Field(
        10,
        title="Page Size",
        description="Max suggestions",
    )

class SalesforceExplainQueryPlanConfig(BaseModel):
    """Explain Query Plan"""

    operation: Literal["explain_query_plan"] = Field(
        "explain_query_plan",
        json_schema_extra={
            "const": "explain_query_plan",
            "ui:hidden": True,
            "x-category": 'Query',
            "x-is-trigger": False,
            "x-display-name": "Explain Query Plan",
            "x-keywords": ["explain query plan", "query plan", "soql performance"],
        },
        title="Explain Query Plan",
    )
    query: str = Field(
        ...,
        title="Query",
        description="SOQL query to explain",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceGetRecordCountConfig(BaseModel):
    """Get Record Count"""

    operation: Literal["get_record_count"] = Field(
        "get_record_count",
        json_schema_extra={
            "const": "get_record_count",
            "ui:hidden": True,
            "x-category": 'Org',
            "x-is-trigger": False,
            "x-display-name": "Get Record Count",
            "x-keywords": ["get record count", "count records", "object record count"],
        },
        title="Get Record Count",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Single or comma-separated object types",
    )

class SalesforceListUsersConfig(BaseModel):
    """List Users"""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": 'User Admin',
            "x-is-trigger": False,
            "x-display-name": "List Users",
            "x-keywords": ["list users", "org users", "active users"],
        },
        title="List Users",
    )
    is_active: Optional[str] = Field(
        'true',
        title="Is Active",
        description="Filter to active users only",
        json_schema_extra={'enum': ['true', 'false'], 'x-enum-searchable': True, 'enumNames': ['Yes', 'No']},
    )
    profile_id: Optional[str] = Field(
        None,
        title="Profile ID",
        description="Filter by profile (optional)",
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Max users to return",
    )

class SalesforceGetUserConfig(BaseModel):
    """Get User"""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": 'User Admin',
            "x-is-trigger": False,
            "x-display-name": "Get User",
            "x-keywords": ["get user", "user details", "retrieve user"],
        },
        title="Get User",
    )
    user_id: str = Field(
        ...,
        title="User ID",
        description="User ID",
    )
    fields: Optional[str] = Field(
        None,
        title="Fields",
        description="Comma-separated field list (optional)",
    )

class SalesforceUpdateUserConfig(BaseModel):
    """Update User"""

    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={
            "const": "update_user",
            "ui:hidden": True,
            "x-category": 'User Admin',
            "x-is-trigger": False,
            "x-display-name": "Update User",
            "x-keywords": ["update user", "edit user", "change user fields"],
        },
        title="Update User",
    )
    user_id: str = Field(
        ...,
        title="User ID",
        description="User ID",
    )
    field_updates: str = Field(
        ...,
        title="Field Updates",
        description="JSON object of field to value",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceListProfilesConfig(BaseModel):
    """List Profiles"""

    operation: Literal["list_profiles"] = Field(
        "list_profiles",
        json_schema_extra={
            "const": "list_profiles",
            "ui:hidden": True,
            "x-category": 'User Admin',
            "x-is-trigger": False,
            "x-display-name": "List Profiles",
            "x-keywords": ["list profiles", "user profiles", "org profiles"],
        },
        title="List Profiles",
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Max profiles to return",
    )

class SalesforceListRolesConfig(BaseModel):
    """List Roles"""

    operation: Literal["list_roles"] = Field(
        "list_roles",
        json_schema_extra={
            "const": "list_roles",
            "ui:hidden": True,
            "x-category": 'User Admin',
            "x-is-trigger": False,
            "x-display-name": "List Roles",
            "x-keywords": ["list roles", "user roles", "role hierarchy"],
        },
        title="List Roles",
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Max roles to return",
    )

class SalesforceGetOrgStorageUsageConfig(BaseModel):
    """Get Org Storage Usage"""

    operation: Literal["get_org_storage_usage"] = Field(
        "get_org_storage_usage",
        json_schema_extra={
            "const": "get_org_storage_usage",
            "ui:hidden": True,
            "x-category": 'Org',
            "x-is-trigger": False,
            "x-display-name": "Get Org Storage Usage",
            "x-keywords": ["get org storage usage", "storage usage", "record count usage"],
        },
        title="Get Org Storage Usage",
    )

class SalesforceListExternalDataSourcesConfig(BaseModel):
    """List External Data Sources"""

    operation: Literal["list_external_data_sources"] = Field(
        "list_external_data_sources",
        json_schema_extra={
            "const": "list_external_data_sources",
            "ui:hidden": True,
            "x-category": 'External Object',
            "x-is-trigger": False,
            "x-display-name": "List External Data Sources",
            "x-keywords": ["list external data sources", "external data sources"],
        },
        title="List External Data Sources",
    )
    page_size: Optional[int] = Field(
        50,
        title="Page Size",
        description="Max sources to return",
    )

class SalesforceQueryExternalObjectConfig(BaseModel):
    """Query External Object"""

    operation: Literal["query_external_object"] = Field(
        "query_external_object",
        json_schema_extra={
            "const": "query_external_object",
            "ui:hidden": True,
            "x-category": 'External Object',
            "x-is-trigger": False,
            "x-display-name": "Query External Object",
            "x-keywords": ["query external object", "external object soql"],
        },
        title="Query External Object",
    )
    query: str = Field(
        ...,
        title="Query",
        description="SOQL against an external __x object",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceCreateExternalObjectRecordConfig(BaseModel):
    """Create External Object Record"""

    operation: Literal["create_external_object_record"] = Field(
        "create_external_object_record",
        json_schema_extra={
            "const": "create_external_object_record",
            "ui:hidden": True,
            "x-category": 'External Object',
            "x-is-trigger": False,
            "x-display-name": "Create External Object Record",
            "x-keywords": ["create external object record", "external object insert"],
        },
        title="Create External Object Record",
    )
    external_object_type: str = Field(
        ...,
        title="External Object Type",
        description="External object API name (with __x)",
    )
    field_values: str = Field(
        ...,
        title="Field Values",
        description="JSON of field values",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceListKnowledgeArticlesConfig(BaseModel):
    """List Knowledge Articles"""

    operation: Literal["list_knowledge_articles"] = Field(
        "list_knowledge_articles",
        json_schema_extra={
            "const": "list_knowledge_articles",
            "ui:hidden": True,
            "x-category": 'Knowledge',
            "x-is-trigger": False,
            "x-display-name": "List Knowledge Articles",
            "x-keywords": ["list knowledge articles", "kb articles", "help articles"],
        },
        title="List Knowledge Articles",
    )
    publish_status: Optional[str] = Field(
        'Online',
        title="Publish Status",
        description="Publish status filter",
        json_schema_extra={'enum': ['Online', 'Draft', 'Archived'], 'x-enum-searchable': True},
    )
    language: Optional[str] = Field(
        'en_US',
        title="Language",
        description="Article language",
    )
    search_term: Optional[str] = Field(
        None,
        title="Search Term",
        description="Filter by title (optional)",
    )
    page_size: Optional[int] = Field(
        50,
        title="Page Size",
        description="Max articles to return",
    )

class SalesforceCreateKnowledgeArticleConfig(BaseModel):
    """Create Knowledge Article"""

    operation: Literal["create_knowledge_article"] = Field(
        "create_knowledge_article",
        json_schema_extra={
            "const": "create_knowledge_article",
            "ui:hidden": True,
            "x-category": 'Knowledge',
            "x-is-trigger": False,
            "x-display-name": "Create Knowledge Article",
            "x-keywords": ["create knowledge article", "new kb article"],
        },
        title="Create Knowledge Article",
    )
    title: str = Field(
        ...,
        title="Title",
        description="Article title",
    )
    article_body: Optional[str] = Field(
        None,
        title="Body",
        description="Article body",
        json_schema_extra={'ui:widget': 'textarea'},
    )
    summary: Optional[str] = Field(
        None,
        title="Summary",
        description="Article summary",
    )
    url_name: Optional[str] = Field(
        None,
        title="URL Name",
        description="URL slug for the article",
    )

class SalesforcePublishKnowledgeArticleConfig(BaseModel):
    """Publish Knowledge Article"""

    operation: Literal["publish_knowledge_article"] = Field(
        "publish_knowledge_article",
        json_schema_extra={
            "const": "publish_knowledge_article",
            "ui:hidden": True,
            "x-category": 'Knowledge',
            "x-is-trigger": False,
            "x-display-name": "Publish Knowledge Article",
            "x-keywords": ["publish knowledge article", "publish kb article"],
        },
        title="Publish Knowledge Article",
    )
    article_id: str = Field(
        ...,
        title="Article ID",
        description="Knowledge article version ID",
    )

class SalesforceAttachArticleToCaseConfig(BaseModel):
    """Attach Article to Case"""

    operation: Literal["attach_article_to_case"] = Field(
        "attach_article_to_case",
        json_schema_extra={
            "const": "attach_article_to_case",
            "ui:hidden": True,
            "x-category": 'Knowledge',
            "x-is-trigger": False,
            "x-display-name": "Attach Article to Case",
            "x-keywords": ["attach article to case", "link kb to case"],
        },
        title="Attach Article to Case",
    )
    case_id: str = Field(
        ...,
        title="Case ID",
        description="Case ID",
    )
    knowledge_article_version_id: str = Field(
        ...,
        title="Article Version ID",
        description="KnowledgeArticleVersion ID",
    )

class SalesforcePublishPlatformEventConfig(BaseModel):
    """Publish Platform Event"""

    operation: Literal["publish_platform_event"] = Field(
        "publish_platform_event",
        json_schema_extra={
            "const": "publish_platform_event",
            "ui:hidden": True,
            "x-category": 'Platform Event',
            "x-is-trigger": False,
            "x-display-name": "Publish Platform Event",
            "x-keywords": ["publish platform event", "emit event", "fire platform event"],
        },
        title="Publish Platform Event",
    )
    event_type: str = Field(
        ...,
        title="Event Type",
        description="Platform event API name (without __e)",
    )
    payload: str = Field(
        ...,
        title="Payload",
        description="JSON of event fields",
        json_schema_extra={'ui:widget': 'textarea'},
    )

class SalesforceListPlatformEventChannelsConfig(BaseModel):
    """List Platform Event Channels"""

    operation: Literal["list_platform_event_channels"] = Field(
        "list_platform_event_channels",
        json_schema_extra={
            "const": "list_platform_event_channels",
            "ui:hidden": True,
            "x-category": 'Platform Event',
            "x-is-trigger": False,
            "x-display-name": "List Platform Event Channels",
            "x-keywords": ["list platform event channels", "event channels"],
        },
        title="List Platform Event Channels",
    )

class SalesforceGetListViewResultsWithColumnsConfig(BaseModel):
    """Get List View Results with Columns"""

    operation: Literal["get_list_view_results_with_columns"] = Field(
        "get_list_view_results_with_columns",
        json_schema_extra={
            "const": "get_list_view_results_with_columns",
            "ui:hidden": True,
            "x-category": 'List View',
            "x-is-trigger": False,
            "x-display-name": "Get List View Results with Columns",
            "x-keywords": ["get list view results with columns", "list view rows", "list view data"],
        },
        title="Get List View Results with Columns",
    )
    object_type: str = Field(
        ...,
        title="Object Type",
        description="Salesforce object type",
    )
    list_view_id: str = Field(
        ...,
        title="List View ID",
        description="List view ID",
    )
    page_size: Optional[int] = Field(
        200,
        title="Page Size",
        description="Max rows to return",
    )

# ==== NEW TRIGGER CONFIGS ====

class SalesforceOnNewLeadConfig(PollTriggerConfigBase):
    """On New Lead"""

    operation: Literal["on_new_lead"] = Field(
        "on_new_lead",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Lead",
            "x-keywords": ["when new lead created", "on new lead", "watch for leads", "new lead trigger"],
        },
        title="On New Lead",
    )

class SalesforceOnNewContactConfig(PollTriggerConfigBase):
    """On New Contact"""

    operation: Literal["on_new_contact"] = Field(
        "on_new_contact",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Contact",
            "x-keywords": ["when new contact created", "on new contact", "new contact trigger"],
        },
        title="On New Contact",
    )

class SalesforceOnNewAccountConfig(PollTriggerConfigBase):
    """On New Account"""

    operation: Literal["on_new_account"] = Field(
        "on_new_account",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Account",
            "x-keywords": ["when new account created", "on new account", "new account trigger"],
        },
        title="On New Account",
    )

class SalesforceOnNewOpportunityConfig(PollTriggerConfigBase):
    """On New Opportunity"""

    operation: Literal["on_new_opportunity"] = Field(
        "on_new_opportunity",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Opportunity",
            "x-keywords": ["when new opportunity created", "on new opportunity", "new deal trigger"],
        },
        title="On New Opportunity",
    )

class SalesforceOnNewCaseConfig(PollTriggerConfigBase):
    """On New Case"""

    operation: Literal["on_new_case"] = Field(
        "on_new_case",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Case",
            "x-keywords": ["when new case created", "on new case", "new support case trigger"],
        },
        title="On New Case",
    )

class SalesforceOnUpdatedLeadConfig(PollTriggerConfigBase):
    """On Updated Lead"""

    operation: Literal["on_updated_lead"] = Field(
        "on_updated_lead",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Updated Lead",
            "x-keywords": ["when lead updated", "on lead change", "lead modified trigger"],
        },
        title="On Updated Lead",
    )
    soql_where_clause: Optional[str] = Field(
        None,
        title="Extra Filter",
        description="Optional additional SOQL WHERE clause (without WHERE)",
    )

class SalesforceOnUpdatedOpportunityConfig(PollTriggerConfigBase):
    """On Updated Opportunity"""

    operation: Literal["on_updated_opportunity"] = Field(
        "on_updated_opportunity",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Updated Opportunity",
            "x-keywords": ["when opportunity updated", "on opportunity change", "deal modified trigger"],
        },
        title="On Updated Opportunity",
    )

class SalesforceOnUpdatedCaseConfig(PollTriggerConfigBase):
    """On Updated Case"""

    operation: Literal["on_updated_case"] = Field(
        "on_updated_case",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Updated Case",
            "x-keywords": ["when case updated", "on case change", "case modified trigger"],
        },
        title="On Updated Case",
    )

class SalesforceOnNewTaskConfig(PollTriggerConfigBase):
    """On New Task"""

    operation: Literal["on_new_task"] = Field(
        "on_new_task",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Task",
            "x-keywords": ["when new task created", "on new task", "new activity trigger"],
        },
        title="On New Task",
    )

class SalesforceOnOpportunityStageChangeConfig(PollTriggerConfigBase):
    """On Opportunity Stage Change"""

    operation: Literal["on_opportunity_stage_change"] = Field(
        "on_opportunity_stage_change",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Opportunity Stage Change",
            "x-keywords": ["when opportunity reaches stage", "on stage change", "deal stage trigger"],
        },
        title="On Opportunity Stage Change",
    )
    stage_name: str = Field(
        ...,
        title="Stage Name",
        description="The stage to watch for",
    )

class SalesforceOnNewFileUploadConfig(PollTriggerConfigBase):
    """On New File Upload"""

    operation: Literal["on_new_file_upload"] = Field(
        "on_new_file_upload",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New File Upload",
            "x-keywords": ["when new file uploaded", "on new file", "new content version trigger"],
        },
        title="On New File Upload",
    )

class SalesforceOnNewApprovalRequestConfig(PollTriggerConfigBase):
    """On New Approval Request"""

    operation: Literal["on_new_approval_request"] = Field(
        "on_new_approval_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Approval Request",
            "x-keywords": ["when approval submitted", "on new approval request", "pending approval trigger"],
        },
        title="On New Approval Request",
    )

class SalesforceOnApprovalDecisionConfig(PollTriggerConfigBase):
    """On Approval Decision"""

    operation: Literal["on_approval_decision"] = Field(
        "on_approval_decision",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Approval Decision",
            "x-keywords": ["when approval decided", "on approval or rejection", "approval decision trigger"],
        },
        title="On Approval Decision",
    )

class SalesforceOnNewChatterPostOnRecordConfig(PollTriggerConfigBase):
    """On New Chatter Post on Record"""

    operation: Literal["on_new_chatter_post_on_record"] = Field(
        "on_new_chatter_post_on_record",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Chatter Post on Record",
            "x-keywords": ["when new chatter post on record", "on record feed post", "new comment on record trigger"],
        },
        title="On New Chatter Post on Record",
    )
    record_id: str = Field(
        ...,
        title="Record ID",
        description="Record whose feed to watch",
    )

class SalesforceOnChatterMentionConfig(PollTriggerConfigBase):
    """On Chatter Mention"""

    operation: Literal["on_chatter_mention"] = Field(
        "on_chatter_mention",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Chatter Mention",
            "x-keywords": ["when mentioned in chatter", "on chatter mention", "chatter mention trigger"],
        },
        title="On Chatter Mention",
    )
    mention_text: Optional[str] = Field(
        None,
        title="Mention Text",
        description="Text to watch for in feed posts (optional)",
    )

class SalesforceOnNewUserConfig(PollTriggerConfigBase):
    """On New User"""

    operation: Literal["on_new_user"] = Field(
        "on_new_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New User",
            "x-keywords": ["when new user created", "on new user", "new user trigger"],
        },
        title="On New User",
    )

class SalesforceOnReportThresholdCrossedConfig(PollTriggerConfigBase):
    """On Report Threshold Crossed"""

    operation: Literal["on_report_threshold_crossed"] = Field(
        "on_report_threshold_crossed",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Report Threshold Crossed",
            "x-keywords": ["when report value crosses threshold", "on report threshold", "report metric trigger"],
        },
        title="On Report Threshold Crossed",
    )
    report_id: str = Field(
        ...,
        title="Report ID",
        description="ID of the report to monitor",
    )
    column_name: str = Field(
        ...,
        title="Column Name",
        description="Aggregate/column label to check",
    )
    threshold: float = Field(
        ...,
        title="Threshold",
        description="Threshold value",
    )
    comparison: str = Field(
        ...,
        title="Comparison",
        description="Comparison operator",
        json_schema_extra={'enum': ['gt', 'lt', 'gte', 'lte', 'eq'], 'x-enum-searchable': True},
    )


# ============================================================================
# Discriminated Union
# ============================================================================

SalesforceConfig = Annotated[
    Union[
        # Query operations (3)
        SalesforceQueryConfig,
        SalesforceQueryMoreConfig,
        SalesforceSearchConfig,
        # Record operations (5)
        SalesforceGetRecordConfig,
        SalesforceCreateRecordConfig,
        SalesforceUpdateRecordConfig,
        SalesforceDeleteRecordConfig,
        SalesforceUpsertRecordConfig,
        # Batch operations (3)
        SalesforceCreateRecordsConfig,
        SalesforceUpdateRecordsConfig,
        SalesforceDeleteRecordsConfig,
        # Describe operations (3)
        SalesforceListObjectsConfig,
        SalesforceDescribeObjectConfig,
        SalesforceDescribeGlobalConfig,
        # Utility operations (4)
        SalesforceGetLimitsConfig,
        SalesforceGetUserInfoConfig,
        SalesforceGetVersionsConfig,
        SalesforceGetTabsConfig,
        # Approval Process operations (3)
        SalesforceListApprovalProcessesConfig,
        SalesforceSubmitForApprovalConfig,
        SalesforceApproveRejectConfig,
        # File/Attachment operations (3)
        SalesforceGetBlobConfig,
        SalesforceCreateAttachmentConfig,
        SalesforceCreateContentVersionConfig,
        # Composite operations (2)
        SalesforceCompositeRequestConfig,
        SalesforceSObjectTreeConfig,
        # Recently Viewed operations (1)
        SalesforceGetRecentlyViewedConfig,
        # Quick Actions operations (3)
        SalesforceListQuickActionsConfig,
        SalesforceListObjectQuickActionsConfig,
        SalesforceExecuteQuickActionConfig,
        # Layouts operations (2)
        SalesforceGetLayoutsConfig,
        SalesforceGetCompactLayoutsConfig,
        # Bulk API 2.0 operations (7)
        SalesforceCreateBulkJobConfig,
        SalesforceUploadBulkDataConfig,
        SalesforceCloseBulkJobConfig,
        SalesforceGetBulkJobStatusConfig,
        SalesforceGetBulkJobResultsConfig,
        SalesforceAbortBulkJobConfig,
        SalesforceListBulkJobsConfig,
        # Reports operations (3)
        SalesforceListReportsConfig,
        SalesforceRunReportConfig,
        SalesforceGetReportMetadataConfig,
        # Deleted/Updated Records operations (3)
        SalesforceGetDeletedConfig,
        SalesforceGetUpdatedConfig,
        SalesforceQueryAllConfig,
        # List Views operations (3)
        SalesforceListListViewsConfig,
        SalesforceGetListViewConfig,
        SalesforceExecuteListViewConfig,
        # Dashboard operations (3)
        SalesforceListDashboardsConfig,
        SalesforceGetDashboardConfig,
        SalesforceRefreshDashboardConfig,
        # Invocable Actions operations (3)
        SalesforceListInvocableActionsConfig,
        SalesforceGetInvocableActionConfig,
        SalesforceExecuteInvocableActionConfig,
        # Chatter operations (2)
        SalesforcePostToChatterConfig,
        SalesforceGetChatterFeedConfig,
        # === Triggers (17) ===
        SalesforceOnNewLeadConfig,
        SalesforceOnNewContactConfig,
        SalesforceOnNewAccountConfig,
        SalesforceOnNewOpportunityConfig,
        SalesforceOnNewCaseConfig,
        SalesforceOnUpdatedLeadConfig,
        SalesforceOnUpdatedOpportunityConfig,
        SalesforceOnUpdatedCaseConfig,
        SalesforceOnNewTaskConfig,
        SalesforceOnOpportunityStageChangeConfig,
        SalesforceOnNewFileUploadConfig,
        SalesforceOnNewApprovalRequestConfig,
        SalesforceOnApprovalDecisionConfig,
        SalesforceOnNewChatterPostOnRecordConfig,
        SalesforceOnChatterMentionConfig,
        SalesforceOnNewUserConfig,
        SalesforceOnReportThresholdCrossedConfig,
        # === Expanded actions (88) ===
        SalesforceConvertLeadConfig,
        SalesforceMergeRecordsConfig,
        SalesforceCreateTaskConfig,
        SalesforceUpdateTaskConfig,
        SalesforceCreateEventConfig,
        SalesforceUpdateEventConfig,
        SalesforceCreateNoteConfig,
        SalesforceAddCampaignMemberConfig,
        SalesforceUpdateCampaignMemberStatusConfig,
        SalesforceCreateCampaignConfig,
        SalesforceAddCaseCommentConfig,
        SalesforceAddOpportunityLineItemConfig,
        SalesforceAddContactToOpportunityConfig,
        SalesforceAssignPermissionSetConfig,
        SalesforceResetUserPasswordConfig,
        SalesforceGetContentDocumentConfig,
        SalesforceDownloadContentVersionConfig,
        SalesforceListContentVersionsConfig,
        SalesforceDeleteContentDocumentConfig,
        SalesforceCreateContentDocumentLinkConfig,
        SalesforceListFilesLinkedToRecordConfig,
        SalesforceSendSingleEmailConfig,
        SalesforceSendEmailViaTemplateConfig,
        SalesforceListEmailTemplatesConfig,
        SalesforceSendMassEmailConfig,
        SalesforceGetChatterFeedItemConfig,
        SalesforceDeleteChatterFeedItemConfig,
        SalesforceCreateChatterCommentConfig,
        SalesforceGetChatterCommentsConfig,
        SalesforceDeleteChatterCommentConfig,
        SalesforceLikeChatterFeedItemConfig,
        SalesforceGetRecordChatterFeedConfig,
        SalesforceGetChatterUserProfileConfig,
        SalesforceListChatterGroupsConfig,
        SalesforcePostToChatterGroupConfig,
        SalesforceGetChatterGroupMembersConfig,
        SalesforceSendChatterDirectMessageConfig,
        SalesforceGetChatterDirectMessagesConfig,
        SalesforceSearchChatterConfig,
        SalesforceGetChatterNewsFeedConfig,
        SalesforceExecuteAnonymousApexConfig,
        SalesforceRunApexTestsConfig,
        SalesforceGetApexTestResultsConfig,
        SalesforceQueryDebugLogsConfig,
        SalesforceGetDebugLogBodyConfig,
        SalesforceCreateTraceFlagConfig,
        SalesforceGetApexCodeCoverageConfig,
        SalesforceToolingSoqlQueryConfig,
        SalesforceGetPendingApprovalItemsConfig,
        SalesforceRecallApprovalRequestConfig,
        SalesforceGetApprovalHistoryConfig,
        SalesforceGetBulkJobFailedResultsConfig,
        SalesforceGetBulkJobUnprocessedResultsConfig,
        SalesforceDeleteBulkDataJobConfig,
        SalesforceCreateBulkQueryJobConfig,
        SalesforceGetBulkQueryJobResultsConfig,
        SalesforceExecuteCompositeBatchConfig,
        SalesforceBulkRetrieveRecordsConfig,
        SalesforceCompositeUpdateMultipleConfig,
        SalesforceRunReportAsyncConfig,
        SalesforceGetAsyncReportResultConfig,
        SalesforceGetDashboardComponentDataConfig,
        SalesforceListReportFoldersConfig,
        SalesforceExecuteFlowConfig,
        SalesforceListFlowsConfig,
        SalesforceInvokeEmailAlertActionConfig,
        SalesforceInvokeFieldUpdateActionConfig,
        SalesforceGetOrgInfoConfig,
        SalesforceParameterizedSearchConfig,
        SalesforceGetSearchSuggestionsConfig,
        SalesforceExplainQueryPlanConfig,
        SalesforceGetRecordCountConfig,
        SalesforceListUsersConfig,
        SalesforceGetUserConfig,
        SalesforceUpdateUserConfig,
        SalesforceListProfilesConfig,
        SalesforceListRolesConfig,
        SalesforceGetOrgStorageUsageConfig,
        SalesforceListExternalDataSourcesConfig,
        SalesforceQueryExternalObjectConfig,
        SalesforceCreateExternalObjectRecordConfig,
        SalesforceListKnowledgeArticlesConfig,
        SalesforceCreateKnowledgeArticleConfig,
        SalesforcePublishKnowledgeArticleConfig,
        SalesforceAttachArticleToCaseConfig,
        SalesforcePublishPlatformEventConfig,
        SalesforceListPlatformEventChannelsConfig,
        SalesforceGetListViewResultsWithColumnsConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class SalesforceNodeConfig(NodeConfig[SalesforceConfig, SalesforceCredential]):
    """Full configuration for Salesforce node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class SalesforceNode(ScheduledPollTriggerMixin, WorkflowNode):
    """
    Salesforce automation node.

    Executes Salesforce API operations for workflow automation.
    Supports 144 actions and 17 poll triggers including queries, records,
    batches, metadata, CRM actions, email, files, chatter, developer/tooling,
    approvals, bulk API, reports, dashboards, flows, users, and more.
    """

    edit_examples = [
        "Query all closed opportunities over 50k from the last quarter",
        "Create a new Contact record with name, email, and phone fields",
        "Update Lead status to Qualified when company size is Enterprise",
        "Search all Account records mentioning technology in description",
        "Bulk upsert customer records from CSV by external ID",
        "Get recently viewed Opportunities and their stage info",
        "Execute quick action to create a task for a sales rep",
    ]

    scope_registry = SALESFORCE_SCOPES

    # Org identity matters more here than elsewhere: a Salesforce credential can
    # authenticate against the WRONG org and look perfectly healthy.
    # NOT list_available_sobjects: Account/Contact/Lead/Opportunity are the
    # same in every org, so they prove nothing. The org's own name does — and
    # it catches the failure that matters here, authenticating against a real
    # but WRONG org (sandbox vs production).
    connection_evidence = ConnectionEvidence(
        identity_operation="get_org_info",
        noun="org",
    )

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return SalesforceNodeConfig

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
        if not config or not isinstance(config, SalesforceNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect your Salesforce account via OAuth."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Query operations
            "execute_soql_query": self._handle_query,
            "get_query_result_next_batch": self._handle_query_more,
            "execute_sosl_search": self._handle_search,
            # Record operations
            "get_single_record": self._handle_get_record,
            "create_single_record": self._handle_create_record,
            "update_single_record": self._handle_update_record,
            "delete_single_record": self._handle_delete_record,
            "upsert_record_by_external_id": self._handle_upsert_record,
            # Batch operations
            "create_multiple_records": self._handle_create_records,
            "update_multiple_records": self._handle_update_records,
            "delete_multiple_records": self._handle_delete_records,
            # Describe operations
            "list_available_sobjects": self._handle_list_objects,
            "get_sobject_metadata": self._handle_describe_object,
            "get_org_global_metadata": self._handle_describe_global,
            # Utility operations
            "get_org_api_limits": self._handle_get_limits,
            "get_current_user_info": self._handle_get_user_info,
            "get_available_api_versions": self._handle_get_versions,
            "get_user_available_tabs": self._handle_get_tabs,
            # Approval Process operations
            "list_approval_processes": self._handle_list_approval_processes,
            "submit_record_for_approval": self._handle_submit_for_approval,
            "approve_or_reject_approval_request": self._handle_approve_reject,
            # File/Attachment operations
            "get_blob_field_content": self._handle_get_blob,
            "create_record_attachment": self._handle_create_attachment,
            "upload_file_as_content_version": self._handle_create_content_version,
            # Composite operations
            "execute_composite_api_request": self._handle_composite_request,
            "create_nested_record_tree": self._handle_sobject_tree,
            # Recently Viewed operations
            "get_recently_viewed_records": self._handle_get_recently_viewed,
            # Quick Actions operations
            "list_global_quick_actions": self._handle_list_quick_actions,
            "list_object_quick_actions": self._handle_list_object_quick_actions,
            "execute_quick_action": self._handle_execute_quick_action,
            # Layouts operations
            "get_sobject_page_layouts": self._handle_get_layouts,
            "get_sobject_compact_layouts": self._handle_get_compact_layouts,
            # Bulk API 2.0 operations
            "create_bulk_data_job": self._handle_create_bulk_job,
            "upload_csv_to_bulk_job": self._handle_upload_bulk_data,
            "close_bulk_data_job": self._handle_close_bulk_job,
            "get_bulk_job_status": self._handle_get_bulk_job_status,
            "get_bulk_job_results": self._handle_get_bulk_job_results,
            "abort_bulk_data_job": self._handle_abort_bulk_job,
            "list_bulk_data_jobs": self._handle_list_bulk_jobs,
            # Reports operations
            "list_available_reports": self._handle_list_reports,
            "execute_report_and_get_results": self._handle_run_report,
            "get_report_metadata": self._handle_get_report_metadata,
            # Deleted/Updated Records operations
            "get_deleted_records_in_range": self._handle_get_deleted,
            "get_updated_records_in_range": self._handle_get_updated,
            "execute_soql_query_including_deleted": self._handle_query_all,
            # List Views operations
            "list_object_list_views": self._handle_list_listviews,
            "get_list_view_details": self._handle_get_listview,
            "execute_list_view_query": self._handle_execute_listview,
            # Dashboard operations
            "list_available_dashboards": self._handle_list_dashboards,
            "get_dashboard_data": self._handle_get_dashboard,
            "refresh_dashboard_data": self._handle_refresh_dashboard,
            # Invocable Actions operations
            "list_invocable_actions": self._handle_list_invocable_actions,
            "get_invocable_action_details": self._handle_get_invocable_action,
            "execute_invocable_action": self._handle_execute_invocable_action,
            # Chatter operations
            "post_message_to_chatter_feed": self._handle_post_to_chatter,
            "get_chatter_feed_items": self._handle_get_chatter_feed,
            # === Triggers ===
            "on_new_lead": self._trigger_on_new_lead,
            "on_new_contact": self._trigger_on_new_contact,
            "on_new_account": self._trigger_on_new_account,
            "on_new_opportunity": self._trigger_on_new_opportunity,
            "on_new_case": self._trigger_on_new_case,
            "on_updated_lead": self._trigger_on_updated_lead,
            "on_updated_opportunity": self._trigger_on_updated_opportunity,
            "on_updated_case": self._trigger_on_updated_case,
            "on_new_task": self._trigger_on_new_task,
            "on_opportunity_stage_change": self._trigger_on_opportunity_stage_change,
            "on_new_file_upload": self._trigger_on_new_file_upload,
            "on_new_approval_request": self._trigger_on_new_approval_request,
            "on_approval_decision": self._trigger_on_approval_decision,
            "on_new_chatter_post_on_record": self._trigger_on_new_chatter_post_on_record,
            "on_chatter_mention": self._trigger_on_chatter_mention,
            "on_new_user": self._trigger_on_new_user,
            "on_report_threshold_crossed": self._trigger_on_report_threshold_crossed,
            # === Expanded actions ===
            "convert_lead": self._handle_convert_lead,
            "merge_records": self._handle_merge_records,
            "create_task": self._handle_create_task,
            "update_task": self._handle_update_task,
            "create_event": self._handle_create_event,
            "update_event": self._handle_update_event,
            "create_note": self._handle_create_note,
            "add_campaign_member": self._handle_add_campaign_member,
            "update_campaign_member_status": self._handle_update_campaign_member_status,
            "create_campaign": self._handle_create_campaign,
            "add_case_comment": self._handle_add_case_comment,
            "add_opportunity_line_item": self._handle_add_opportunity_line_item,
            "add_contact_to_opportunity": self._handle_add_contact_to_opportunity,
            "assign_permission_set_to_user": self._handle_assign_permission_set_to_user,
            "reset_user_password": self._handle_reset_user_password,
            "get_content_document": self._handle_get_content_document,
            "download_content_version": self._handle_download_content_version,
            "list_content_versions": self._handle_list_content_versions,
            "delete_content_document": self._handle_delete_content_document,
            "create_content_document_link": self._handle_create_content_document_link,
            "list_files_linked_to_record": self._handle_list_files_linked_to_record,
            "send_single_email": self._handle_send_single_email,
            "send_email_via_template": self._handle_send_email_via_template,
            "list_email_templates": self._handle_list_email_templates,
            "send_mass_email": self._handle_send_mass_email,
            "get_chatter_feed_item": self._handle_get_chatter_feed_item,
            "delete_chatter_feed_item": self._handle_delete_chatter_feed_item,
            "create_chatter_comment": self._handle_create_chatter_comment,
            "get_chatter_comments": self._handle_get_chatter_comments,
            "delete_chatter_comment": self._handle_delete_chatter_comment,
            "like_chatter_feed_item": self._handle_like_chatter_feed_item,
            "get_record_chatter_feed": self._handle_get_record_chatter_feed,
            "get_chatter_user_profile": self._handle_get_chatter_user_profile,
            "list_chatter_groups": self._handle_list_chatter_groups,
            "post_to_chatter_group": self._handle_post_to_chatter_group,
            "get_chatter_group_members": self._handle_get_chatter_group_members,
            "send_chatter_direct_message": self._handle_send_chatter_direct_message,
            "get_chatter_direct_messages": self._handle_get_chatter_direct_messages,
            "search_chatter": self._handle_search_chatter,
            "get_chatter_news_feed": self._handle_get_chatter_news_feed,
            "execute_anonymous_apex": self._handle_execute_anonymous_apex,
            "run_apex_tests": self._handle_run_apex_tests,
            "get_apex_test_results": self._handle_get_apex_test_results,
            "query_debug_logs": self._handle_query_debug_logs,
            "get_debug_log_body": self._handle_get_debug_log_body,
            "create_trace_flag": self._handle_create_trace_flag,
            "get_apex_code_coverage": self._handle_get_apex_code_coverage,
            "tooling_soql_query": self._handle_tooling_soql_query,
            "get_pending_approval_items": self._handle_get_pending_approval_items,
            "recall_approval_request": self._handle_recall_approval_request,
            "get_approval_history": self._handle_get_approval_history,
            "get_bulk_job_failed_results": self._handle_get_bulk_job_failed_results,
            "get_bulk_job_unprocessed_results": self._handle_get_bulk_job_unprocessed_results,
            "delete_bulk_data_job": self._handle_delete_bulk_data_job,
            "create_bulk_query_job": self._handle_create_bulk_query_job,
            "get_bulk_query_job_results": self._handle_get_bulk_query_job_results,
            "execute_composite_batch": self._handle_execute_composite_batch,
            "bulk_retrieve_records": self._handle_bulk_retrieve_records,
            "composite_update_multiple": self._handle_composite_update_multiple,
            "run_report_async": self._handle_run_report_async,
            "get_async_report_result": self._handle_get_async_report_result,
            "get_dashboard_component_data": self._handle_get_dashboard_component_data,
            "list_report_folders": self._handle_list_report_folders,
            "execute_flow": self._handle_execute_flow,
            "list_flows": self._handle_list_flows,
            "invoke_email_alert_action": self._handle_invoke_email_alert_action,
            "invoke_field_update_action": self._handle_invoke_field_update_action,
            "get_org_info": self._handle_get_org_info,
            "parameterized_search": self._handle_parameterized_search,
            "get_search_suggestions": self._handle_get_search_suggestions,
            "explain_query_plan": self._handle_explain_query_plan,
            "get_record_count": self._handle_get_record_count,
            "list_users": self._handle_list_users,
            "get_user": self._handle_get_user,
            "update_user": self._handle_update_user,
            "list_profiles": self._handle_list_profiles,
            "list_roles": self._handle_list_roles,
            "get_org_storage_usage": self._handle_get_org_storage_usage,
            "list_external_data_sources": self._handle_list_external_data_sources,
            "query_external_object": self._handle_query_external_object,
            "create_external_object_record": self._handle_create_external_object_record,
            "list_knowledge_articles": self._handle_list_knowledge_articles,
            "create_knowledge_article": self._handle_create_knowledge_article,
            "publish_knowledge_article": self._handle_publish_knowledge_article,
            "attach_article_to_case": self._handle_attach_article_to_case,
            "publish_platform_event": self._handle_publish_platform_event,
            "list_platform_event_channels": self._handle_list_platform_event_channels,
            "get_list_view_results_with_columns": self._handle_get_list_view_results_with_columns,
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
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.salesforce_oauth import refresh_access_token

        async def _refresh(refresh_token: str):
            return await refresh_access_token(
                refresh_token,
                normalize_salesforce_instance_url(credential_data["instance_url"]),
                bool(credential_data.get("is_sandbox")),
            )

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=_refresh,
            additional_token_fields=("instance_url",),
            provider="salesforce",
        )

    async def _get_access_token(self, credentials: SalesforceCredential) -> str:
        """
        Get access token from credentials, refreshing if expired.

        Args:
            credentials: OAuth credentials

        Returns:
            Access token string
        """
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        
        async def _refresh(refresh_token: str):
            return await refresh_access_token(
                refresh_token,
                credentials.instance_url,
                credentials.is_sandbox or False,
            )

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=_refresh,
            additional_token_fields=("instance_url",),
            provider="salesforce",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        if cred_dict.get("instance_url"):
            credentials.instance_url = cred_dict["instance_url"]
        return token

    def _get_base_url(self, credentials: SalesforceCredential) -> str:
        """Get the base API URL for requests."""
        instance_url = normalize_salesforce_instance_url(credentials.instance_url)
        return f"{instance_url}/services/data/{SALESFORCE_API_VERSION}"

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: SalesforceCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        action_name: str = "request",
        use_full_url: bool = False,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Salesforce API.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint (without base URL) or full URL if use_full_url=True
            credentials: OAuth credentials
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)
            use_full_url: If True, endpoint is treated as full URL

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        # Reject an opaque/pagination URL before even refreshing a credential.
        # This keeps attacker-authored endpoints from triggering any auth work.
        instance_origin = normalize_salesforce_instance_url(credentials.instance_url)
        if use_full_url:
            url = endpoint
        else:
            url = f"{instance_origin}/services/data/{SALESFORCE_API_VERSION}{endpoint}"
        assert_exact_url_origin(url, instance_origin)

        # Salesforce may rotate the canonical instance with a refresh. Rebuild
        # ordinary API URLs and re-check opaque URLs against the fresh origin.
        access_token = await self._get_access_token(credentials)
        instance_origin = normalize_salesforce_instance_url(credentials.instance_url)
        if not use_full_url:
            url = f"{instance_origin}/services/data/{SALESFORCE_API_VERSION}{endpoint}"
        assert_exact_url_origin(url, instance_origin)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with guarded_async_client(timeout=60.0) as client:
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
                        if isinstance(error_data, list) and len(error_data) > 0:
                            # Salesforce often returns errors as array
                            error_message = error_data[0].get(
                                "message", str(error_data[0])
                            )
                            error_code = error_data[0].get("errorCode", "UNKNOWN_ERROR")
                        else:
                            error_message = error_data.get("message", str(error_data))
                            error_code = error_data.get("errorCode", "UNKNOWN_ERROR")
                    except Exception:
                        error_message = error_text
                        error_code = "UNKNOWN_ERROR"

                    logger.error(
                        f"[SalesforceNode] API error: {error_code} - {error_message}"
                    )
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "error_code": error_code,
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
                logger.exception(f"[SalesforceNode] Request failed: {e}")
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
    # Query Operation Handlers
    # =========================================================================

    async def _handle_query(
        self, config: SalesforceQueryConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Execute a SOQL query."""
        # URL encode the query
        encoded_query = quote(config.query, safe="")

        return await self._make_request(
            method="GET",
            endpoint=f"/query/?q={encoded_query}",
            credentials=credentials,
            action_name="execute_soql_query",
        )

    async def _handle_query_more(
        self, config: SalesforceQueryMoreConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get next batch of query results."""
        # The nextRecordsUrl is a full path like /services/data/vXX.0/query/...
        # We need to use the instance URL as base
        instance_url = credentials.instance_url.rstrip("/")
        full_url = f"{instance_url}{config.next_records_url}"

        return await self._make_request(
            method="GET",
            endpoint=full_url,
            credentials=credentials,
            action_name="get_query_result_next_batch",
            use_full_url=True,
        )

    async def _handle_search(
        self, config: SalesforceSearchConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Execute a SOSL search."""
        # URL encode the search query
        encoded_query = quote(config.search_query, safe="")

        return await self._make_request(
            method="GET",
            endpoint=f"/search/?q={encoded_query}",
            credentials=credentials,
            action_name="execute_sosl_search",
        )

    # =========================================================================
    # Record Operation Handlers
    # =========================================================================

    async def _handle_get_record(
        self, config: SalesforceGetRecordConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get a single record."""
        endpoint = f"/sobjects/{config.sobject_type}/{config.record_id}"

        params = {}
        if config.fields:
            params["fields"] = ",".join(config.fields)

        return await self._make_request(
            method="GET",
            endpoint=endpoint,
            credentials=credentials,
            params=params if params else None,
            action_name="get_single_record",
        )

    async def _handle_create_record(
        self, config: SalesforceCreateRecordConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Create a new record."""
        return await self._make_request(
            method="POST",
            endpoint=f"/sobjects/{config.sobject_type}/",
            credentials=credentials,
            json_body=config.fields,
            action_name="create_single_record",
        )

    async def _handle_update_record(
        self, config: SalesforceUpdateRecordConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Update an existing record."""
        result = await self._make_request(
            method="PATCH",
            endpoint=f"/sobjects/{config.sobject_type}/{config.record_id}",
            credentials=credentials,
            json_body=config.fields,
            action_name="update_single_record",
        )

        # PATCH returns 204 No Content on success
        if result["status"] == "success" and result["status_code"] == 204:
            result["data"] = {"id": config.record_id, "success": True}

        return result

    async def _handle_delete_record(
        self, config: SalesforceDeleteRecordConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Delete a record."""
        result = await self._make_request(
            method="DELETE",
            endpoint=f"/sobjects/{config.sobject_type}/{config.record_id}",
            credentials=credentials,
            action_name="delete_single_record",
        )

        # DELETE returns 204 No Content on success
        if result["status"] == "success" and result["status_code"] == 204:
            result["data"] = {"id": config.record_id, "deleted": True}

        return result

    async def _handle_upsert_record(
        self, config: SalesforceUpsertRecordConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Upsert a record using external ID."""
        endpoint = f"/sobjects/{config.sobject_type}/{config.external_id_field}/{config.external_id_value}"

        result = await self._make_request(
            method="PATCH",
            endpoint=endpoint,
            credentials=credentials,
            json_body=config.fields,
            action_name="upsert_record_by_external_id",
        )

        # 201 = created, 204 = updated
        if result["status"] == "success":
            if result["status_code"] == 204:
                result["data"] = {"success": True, "created": False}
            elif result["status_code"] == 201:
                result["data"]["created"] = True

        return result

    # =========================================================================
    # Batch Operation Handlers (sObject Collections)
    # =========================================================================

    async def _handle_create_records(
        self, config: SalesforceCreateRecordsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Create multiple records."""
        # Add attributes to each record for sObject Collections
        records = []
        for record in config.records:
            records.append({"attributes": {"type": config.sobject_type}, **record})

        body = {"allOrNone": config.all_or_none, "records": records}

        return await self._make_request(
            method="POST",
            endpoint="/composite/sobjects",
            credentials=credentials,
            json_body=body,
            action_name="create_multiple_records",
        )

    async def _handle_update_records(
        self, config: SalesforceUpdateRecordsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Update multiple records."""
        # Add attributes to each record
        records = []
        for record in config.records:
            if "Id" not in record and "id" not in record:
                raise ValueError("Each record must have an 'Id' field for updates")
            records.append({"attributes": {"type": config.sobject_type}, **record})

        body = {"allOrNone": config.all_or_none, "records": records}

        return await self._make_request(
            method="PATCH",
            endpoint="/composite/sobjects",
            credentials=credentials,
            json_body=body,
            action_name="update_multiple_records",
        )

    async def _handle_delete_records(
        self, config: SalesforceDeleteRecordsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Delete multiple records."""
        # Build query string with record IDs
        ids_param = ",".join(config.record_ids)
        params = {"ids": ids_param, "allOrNone": str(config.all_or_none).lower()}

        return await self._make_request(
            method="DELETE",
            endpoint="/composite/sobjects",
            credentials=credentials,
            params=params,
            action_name="delete_multiple_records",
        )

    # =========================================================================
    # Describe Operation Handlers
    # =========================================================================

    async def _handle_list_objects(
        self, config: SalesforceListObjectsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """List all available sObjects."""
        return await self._make_request(
            method="GET",
            endpoint="/sobjects/",
            credentials=credentials,
            action_name="list_available_sobjects",
        )

    async def _handle_describe_object(
        self, config: SalesforceDescribeObjectConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get detailed metadata for an sObject."""
        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/describe/",
            credentials=credentials,
            action_name="get_sobject_metadata",
        )

    async def _handle_describe_global(
        self, config: SalesforceDescribeGlobalConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get global org metadata."""
        return await self._make_request(
            method="GET",
            endpoint="/sobjects/",
            credentials=credentials,
            action_name="get_org_global_metadata",
        )

    # =========================================================================
    # Utility Operation Handlers
    # =========================================================================

    async def _handle_get_limits(
        self, config: SalesforceGetLimitsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get org API limits."""
        return await self._make_request(
            method="GET",
            endpoint="/limits/",
            credentials=credentials,
            action_name="get_org_api_limits",
        )

    async def _handle_get_user_info(
        self, config: SalesforceGetUserInfoConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get current user info."""
        # Use the identity endpoint
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/oauth2/userinfo"

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            action_name="get_current_user_info",
            use_full_url=True,
        )

    async def _handle_get_versions(
        self, config: SalesforceGetVersionsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get available API versions."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/"

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            action_name="get_available_api_versions",
            use_full_url=True,
        )

    async def _handle_get_tabs(
        self, config: SalesforceGetTabsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get available tabs."""
        return await self._make_request(
            method="GET",
            endpoint="/tabs/",
            credentials=credentials,
            action_name="get_user_available_tabs",
        )

    # =========================================================================
    # Approval Process Operation Handlers
    # =========================================================================

    async def _handle_list_approval_processes(
        self,
        config: SalesforceListApprovalProcessesConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """List all approval processes."""
        return await self._make_request(
            method="GET",
            endpoint="/process/approvals/",
            credentials=credentials,
            action_name="list_approval_processes",
        )

    async def _handle_submit_for_approval(
        self,
        config: SalesforceSubmitForApprovalConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Submit a record for approval."""
        body = {
            "requests": [
                {
                    "actionType": "Submit",
                    "contextId": config.record_id,
                }
            ]
        }

        if config.process_definition_name_or_id:
            body["requests"][0][
                "processDefinitionNameOrId"
            ] = config.process_definition_name_or_id
        if config.comments:
            body["requests"][0]["comments"] = config.comments
        if config.next_approver_ids:
            body["requests"][0]["nextApproverIds"] = config.next_approver_ids
        if config.skip_entry_criteria:
            body["requests"][0]["skipEntryCriteria"] = config.skip_entry_criteria

        return await self._make_request(
            method="POST",
            endpoint="/process/approvals/",
            credentials=credentials,
            json_body=body,
            action_name="submit_record_for_approval",
        )

    async def _handle_approve_reject(
        self, config: SalesforceApproveRejectConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Approve or reject pending approval requests."""
        requests = []
        for work_item_id in config.work_item_ids:
            req = {
                "actionType": config.action_type,
                "contextId": work_item_id,
            }
            if config.comments:
                req["comments"] = config.comments
            if config.next_approver_ids and config.action_type == "Approve":
                req["nextApproverIds"] = config.next_approver_ids
            requests.append(req)

        return await self._make_request(
            method="POST",
            endpoint="/process/approvals/",
            credentials=credentials,
            json_body={"requests": requests},
            action_name="approve_or_reject_approval_request",
        )

    # =========================================================================
    # File/Attachment Operation Handlers
    # =========================================================================

    async def _handle_get_blob(
        self, config: SalesforceGetBlobConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get blob data for a record."""
        endpoint = (
            f"/sobjects/{config.sobject_type}/{config.record_id}/{config.blob_field}"
        )

        # Get access token
        access_token = await self._get_access_token(credentials)
        base_url = self._get_base_url(credentials)
        url = f"{base_url}{endpoint}"

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        start_time = time.time()

        async with guarded_async_client(timeout=60.0) as client:
            try:
                response = await client.get(url, headers=headers)
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    return {
                        "status": "error",
                        "action": "get_blob_field_content",
                        "error": response.text,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                from nodes.core.binary_output import BinaryOutput

                content_type = response.headers.get(
                    "Content-Type", "application/octet-stream"
                )
                ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
                filename = f"{config.record_id}_{config.blob_field}{ext}"

                return {
                    "status": "success",
                    "action": "get_blob_field_content",
                    "data": {
                        "content_type": content_type,
                        "content_length": len(response.content),
                        "blob": BinaryOutput(
                            data=response.content,
                            content_type=content_type,
                            filename=filename,
                        ),
                    },
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }
            except Exception as e:
                return {
                    "status": "error",
                    "action": "get_blob_field_content",
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    async def _handle_create_attachment(
        self,
        config: SalesforceCreateAttachmentConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Create an attachment."""
        fields = {
            "ParentId": config.parent_id,
            "Name": config.name,
            "Body": config.body,  # Base64 encoded
        }
        if config.content_type:
            fields["ContentType"] = config.content_type
        if config.description:
            fields["Description"] = config.description

        return await self._make_request(
            method="POST",
            endpoint="/sobjects/Attachment/",
            credentials=credentials,
            json_body=fields,
            action_name="create_record_attachment",
        )

    async def _handle_create_content_version(
        self,
        config: SalesforceCreateContentVersionConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Upload a file as ContentVersion."""
        fields = {
            "Title": config.title,
            "PathOnClient": config.path_on_client,
            "VersionData": config.version_data,  # Base64 encoded
        }
        if config.first_publish_location_id:
            fields["FirstPublishLocationId"] = config.first_publish_location_id
        if config.description:
            fields["Description"] = config.description

        return await self._make_request(
            method="POST",
            endpoint="/sobjects/ContentVersion/",
            credentials=credentials,
            json_body=fields,
            action_name="upload_file_as_content_version",
        )

    # =========================================================================
    # Composite Operation Handlers
    # =========================================================================

    async def _handle_composite_request(
        self,
        config: SalesforceCompositeRequestConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Execute multiple REST API requests in a single call."""
        body = {
            "compositeRequest": config.composite_requests,
            "allOrNone": config.all_or_none,
        }
        if config.collate_subrequests:
            body["collateSubrequests"] = config.collate_subrequests

        return await self._make_request(
            method="POST",
            endpoint="/composite/",
            credentials=credentials,
            json_body=body,
            action_name="execute_composite_api_request",
        )

    async def _handle_sobject_tree(
        self, config: SalesforceSObjectTreeConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Create a tree of nested records."""
        return await self._make_request(
            method="POST",
            endpoint=f"/composite/tree/{config.sobject_type}/",
            credentials=credentials,
            json_body={"records": config.records},
            action_name="create_nested_record_tree",
        )

    # =========================================================================
    # Recently Viewed Operation Handlers
    # =========================================================================

    async def _handle_get_recently_viewed(
        self,
        config: SalesforceGetRecentlyViewedConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Get recently viewed records."""
        params = {}
        if config.limit:
            params["limit"] = config.limit

        return await self._make_request(
            method="GET",
            endpoint="/recent/",
            credentials=credentials,
            params=params if params else None,
            action_name="get_recently_viewed_records",
        )

    # =========================================================================
    # Quick Actions Operation Handlers
    # =========================================================================

    async def _handle_list_quick_actions(
        self,
        config: SalesforceListQuickActionsConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """List global quick actions."""
        return await self._make_request(
            method="GET",
            endpoint="/quickActions/",
            credentials=credentials,
            action_name="list_global_quick_actions",
        )

    async def _handle_list_object_quick_actions(
        self,
        config: SalesforceListObjectQuickActionsConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """List quick actions for a specific object."""
        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/quickActions/",
            credentials=credentials,
            action_name="list_object_quick_actions",
        )

    async def _handle_execute_quick_action(
        self,
        config: SalesforceExecuteQuickActionConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Execute a quick action."""
        endpoint = f"/quickActions/{config.quick_action_name}"

        body = {}
        if config.context_id:
            body["contextId"] = config.context_id
        if config.record:
            body["record"] = config.record

        return await self._make_request(
            method="POST",
            endpoint=endpoint,
            credentials=credentials,
            json_body=body if body else None,
            action_name="execute_quick_action",
        )

    # =========================================================================
    # Layouts Operation Handlers
    # =========================================================================

    async def _handle_get_layouts(
        self, config: SalesforceGetLayoutsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get page layouts for an object."""
        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/describe/layouts/",
            credentials=credentials,
            action_name="get_sobject_page_layouts",
        )

    async def _handle_get_compact_layouts(
        self,
        config: SalesforceGetCompactLayoutsConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Get compact layouts for an object."""
        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/describe/compactLayouts/",
            credentials=credentials,
            action_name="get_sobject_compact_layouts",
        )

    # =========================================================================
    # Bulk API 2.0 Operation Handlers
    # =========================================================================

    async def _handle_create_bulk_job(
        self, config: SalesforceCreateBulkJobConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Create a bulk ingest job."""
        body = {
            "operation": config.bulk_operation,
            "object": config.sobject_type,
            "contentType": "CSV",
            "lineEnding": config.line_ending or "LF",
        }
        if config.external_id_field:
            body["externalIdFieldName"] = config.external_id_field

        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/jobs/ingest"

        return await self._make_request(
            method="POST",
            endpoint=url,
            credentials=credentials,
            json_body=body,
            action_name="create_bulk_data_job",
            use_full_url=True,
        )

    async def _handle_upload_bulk_data(
        self, config: SalesforceUploadBulkDataConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Upload CSV data to a bulk job."""
        access_token = await self._get_access_token(credentials)
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/jobs/ingest/{config.job_id}/batches"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "text/csv",
        }

        start_time = time.time()

        async with guarded_async_client(timeout=300.0) as client:
            try:
                response = await client.put(
                    url, headers=headers, content=config.csv_data
                )
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    return {
                        "status": "error",
                        "action": "upload_csv_to_bulk_job",
                        "error": response.text,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                return {
                    "status": "success",
                    "action": "upload_csv_to_bulk_job",
                    "data": {"job_id": config.job_id, "uploaded": True},
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }
            except Exception as e:
                return {
                    "status": "error",
                    "action": "upload_csv_to_bulk_job",
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    async def _handle_close_bulk_job(
        self, config: SalesforceCloseBulkJobConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Close a bulk job to start processing."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/jobs/ingest/{config.job_id}"

        return await self._make_request(
            method="PATCH",
            endpoint=url,
            credentials=credentials,
            json_body={"state": "UploadComplete"},
            action_name="close_bulk_data_job",
            use_full_url=True,
        )

    async def _handle_get_bulk_job_status(
        self,
        config: SalesforceGetBulkJobStatusConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Get bulk job status."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/jobs/ingest/{config.job_id}"

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            action_name="get_bulk_job_status",
            use_full_url=True,
        )

    async def _handle_get_bulk_job_results(
        self,
        config: SalesforceGetBulkJobResultsConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Get bulk job results."""
        result_endpoints = {
            "successful": "successfulResults",
            "failed": "failedResults",
            "unprocessed": "unprocessedrecords",
        }
        endpoint_suffix = result_endpoints.get(config.result_type, "successfulResults")
        endpoint = (
            f"/jobs/ingest/{config.job_id}/{endpoint_suffix}"
        )
        result = await self._bulk_csv_get(
            credentials,
            endpoint,
            "get_bulk_job_results",
        )
        if result.get("status") == "success":
            result["data"]["result_type"] = config.result_type
        return result

    async def _handle_abort_bulk_job(
        self, config: SalesforceAbortBulkJobConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Abort a bulk job."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/jobs/ingest/{config.job_id}"

        return await self._make_request(
            method="PATCH",
            endpoint=url,
            credentials=credentials,
            json_body={"state": "Aborted"},
            action_name="abort_bulk_data_job",
            use_full_url=True,
        )

    async def _handle_list_bulk_jobs(
        self, config: SalesforceListBulkJobsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """List bulk jobs."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/jobs/ingest"

        params = {}
        if config.is_pk_chunking_enabled is not None:
            params["isPkChunkingEnabled"] = str(config.is_pk_chunking_enabled).lower()
        if config.job_type:
            params["jobType"] = config.job_type

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            params=params if params else None,
            action_name="list_bulk_data_jobs",
            use_full_url=True,
        )

    # =========================================================================
    # Reports Operation Handlers
    # =========================================================================

    async def _handle_list_reports(
        self, config: SalesforceListReportsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """List available reports."""
        # Query Report object
        return await self._make_request(
            method="GET",
            endpoint="/query/?q=SELECT+Id,Name,DeveloperName,FolderName+FROM+Report+LIMIT+200",
            credentials=credentials,
            action_name="list_available_reports",
        )

    async def _handle_run_report(
        self, config: SalesforceRunReportConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Run a report."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/reports/{config.report_id}"

        params = {}
        if config.include_details is not None:
            params["includeDetails"] = str(config.include_details).lower()

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            params=params if params else None,
            action_name="execute_report_and_get_results",
            use_full_url=True,
        )

    async def _handle_get_report_metadata(
        self,
        config: SalesforceGetReportMetadataConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Get report metadata."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/reports/{config.report_id}/describe"

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            action_name="get_report_metadata",
            use_full_url=True,
        )

    # =========================================================================
    # Deleted/Updated Records Operation Handlers
    # =========================================================================

    async def _handle_get_deleted(
        self, config: SalesforceGetDeletedConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get records deleted within a time range."""
        # URL encode the dates
        start = quote(config.start, safe="")
        end = quote(config.end, safe="")

        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/deleted/?start={start}&end={end}",
            credentials=credentials,
            action_name="get_deleted_records_in_range",
        )

    async def _handle_get_updated(
        self, config: SalesforceGetUpdatedConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get records updated within a time range."""
        # URL encode the dates
        start = quote(config.start, safe="")
        end = quote(config.end, safe="")

        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/updated/?start={start}&end={end}",
            credentials=credentials,
            action_name="get_updated_records_in_range",
        )

    async def _handle_query_all(
        self, config: SalesforceQueryAllConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Execute SOQL query including deleted and archived records."""
        # URL encode the query
        encoded_query = quote(config.query, safe="")

        return await self._make_request(
            method="GET",
            endpoint=f"/queryAll/?q={encoded_query}",
            credentials=credentials,
            action_name="execute_soql_query_including_deleted",
        )

    # =========================================================================
    # List Views Operation Handlers
    # =========================================================================

    async def _handle_list_listviews(
        self, config: SalesforceListListViewsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """List list views for an object."""
        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/listviews/",
            credentials=credentials,
            action_name="list_object_list_views",
        )

    async def _handle_get_listview(
        self, config: SalesforceGetListViewConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get a specific list view."""
        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/listviews/{config.listview_id}/",
            credentials=credentials,
            action_name="get_list_view_details",
        )

    async def _handle_execute_listview(
        self, config: SalesforceExecuteListViewConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Execute a list view and get results."""
        params = {}
        if config.limit is not None:
            params["limit"] = config.limit
        if config.offset is not None:
            params["offset"] = config.offset

        return await self._make_request(
            method="GET",
            endpoint=f"/sobjects/{config.sobject_type}/listviews/{config.listview_id}/results",
            credentials=credentials,
            params=params if params else None,
            action_name="execute_list_view_query",
        )

    # =========================================================================
    # Dashboard Operation Handlers
    # =========================================================================

    async def _handle_list_dashboards(
        self, config: SalesforceListDashboardsConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """List available dashboards."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/dashboards"

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            action_name="list_available_dashboards",
            use_full_url=True,
        )

    async def _handle_get_dashboard(
        self, config: SalesforceGetDashboardConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get dashboard data and metadata."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/dashboards/{config.dashboard_id}"

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            action_name="get_dashboard_data",
            use_full_url=True,
        )

    async def _handle_refresh_dashboard(
        self,
        config: SalesforceRefreshDashboardConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Refresh a dashboard to get latest data."""
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/dashboards/{config.dashboard_id}"

        return await self._make_request(
            method="PUT",
            endpoint=url,
            credentials=credentials,
            action_name="refresh_dashboard_data",
            use_full_url=True,
        )

    # =========================================================================
    # Invocable Actions Operation Handlers
    # =========================================================================

    async def _handle_list_invocable_actions(
        self,
        config: SalesforceListInvocableActionsConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """List available invocable actions."""
        if config.action_type == "standard":
            endpoint = "/actions/standard"
        elif config.action_type == "custom":
            endpoint = "/actions/custom"
        else:
            # List both standard and custom
            endpoint = "/actions"

        return await self._make_request(
            method="GET",
            endpoint=endpoint,
            credentials=credentials,
            action_name="list_invocable_actions",
        )

    async def _handle_get_invocable_action(
        self,
        config: SalesforceGetInvocableActionConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Get details of a specific invocable action."""
        endpoint = f"/actions/{config.action_type}/{config.action_name}"

        return await self._make_request(
            method="GET",
            endpoint=endpoint,
            credentials=credentials,
            action_name="get_invocable_action_details",
        )

    async def _handle_execute_invocable_action(
        self,
        config: SalesforceExecuteInvocableActionConfig,
        credentials: SalesforceCredential,
    ) -> Dict[str, Any]:
        """Execute an invocable action."""
        endpoint = f"/actions/{config.action_type}/{config.action_name}"

        return await self._make_request(
            method="POST",
            endpoint=endpoint,
            credentials=credentials,
            json_body={"inputs": config.inputs},
            action_name="execute_invocable_action",
        )

    # =========================================================================
    # Chatter Operation Handlers
    # =========================================================================

    async def _handle_post_to_chatter(
        self, config: SalesforcePostToChatterConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Post a message to Chatter feed."""
        instance_url = credentials.instance_url.rstrip("/")

        # Build the feed element body
        body = {
            "body": {"messageSegments": [{"type": "Text", "text": config.text}]},
            "feedElementType": "FeedItem",
        }

        if config.subject_id:
            body["subjectId"] = config.subject_id
            url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/chatter/feed-elements"
        else:
            # Post to current user's feed
            url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/chatter/feeds/news/me/feed-elements"

        return await self._make_request(
            method="POST",
            endpoint=url,
            credentials=credentials,
            json_body=body,
            action_name="post_message_to_chatter_feed",
            use_full_url=True,
        )

    async def _handle_get_chatter_feed(
        self, config: SalesforceGetChatterFeedConfig, credentials: SalesforceCredential
    ) -> Dict[str, Any]:
        """Get Chatter feed items."""
        instance_url = credentials.instance_url.rstrip("/")

        if config.feed_type == "news":
            url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/chatter/feeds/news/me/feed-elements"
        elif config.feed_type == "record":
            if not config.subject_id:
                return {
                    "status": "error",
                    "action": "get_chatter_feed_items",
                    "error": "subject_id is required for record feed type",
                    "status_code": 400,
                    "timing_ms": {},
                }
            url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/chatter/feeds/record/{config.subject_id}/feed-elements"
        elif config.feed_type == "user":
            if not config.subject_id:
                return {
                    "status": "error",
                    "action": "get_chatter_feed_items",
                    "error": "subject_id is required for user feed type",
                    "status_code": 400,
                    "timing_ms": {},
                }
            url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/chatter/feeds/user-profile/{config.subject_id}/feed-elements"
        else:
            url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/chatter/feeds/news/me/feed-elements"

        params = {}
        if config.page_size is not None:
            params["pageSize"] = config.page_size

        return await self._make_request(
            method="GET",
            endpoint=url,
            credentials=credentials,
            params=params if params else None,
            action_name="get_chatter_feed_items",
            use_full_url=True,
        )

    # =========================================================================
    # Expanded Operation Helpers
    # =========================================================================

    def _tooling_url(self, credentials, path: str) -> str:
        instance_url = credentials.instance_url.rstrip("/")
        return f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/tooling{path}"

    def _chatter_url(self, credentials, path: str) -> str:
        instance_url = credentials.instance_url.rstrip("/")
        return f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/chatter{path}"

    async def _soql(self, credentials, soql: str, action_name: str) -> Dict[str, Any]:
        """Run a SOQL query via the standard /query endpoint."""
        encoded = quote(soql, safe="")
        return await self._make_request(
            method="GET",
            endpoint=f"/query/?q={encoded}",
            credentials=credentials,
            action_name=action_name,
        )

    @staticmethod
    def _split_ids(value: str) -> List[str]:
        """Parse a comma-separated string or JSON array of IDs into a list."""
        value = (value or "").strip()
        if not value:
            return []
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except Exception:
                pass
        return [v.strip() for v in value.split(",") if v.strip()]

    @staticmethod
    def _parse_json_obj(value: Optional[str]) -> Dict[str, Any]:
        if not value:
            return {}
        return json.loads(value)

    @staticmethod
    def _parse_json_list(value: Optional[str]) -> List[Any]:
        if not value:
            return []
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON array")
        return parsed

    async def _handle_convert_lead(self, config, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "leadId": config.lead_id,
            "convertedStatus": config.converted_status,
            "doNotCreateOpportunity": (config.do_not_create_opportunity == "true"),
            "sendNotificationEmail": (config.send_notification_email == "true"),
        }
        if config.account_id:
            body["accountId"] = config.account_id
        if config.contact_id:
            body["contactId"] = config.contact_id
        if config.opportunity_name:
            body["opportunityName"] = config.opportunity_name
        return await self._make_request(
            "POST", "/actions/standard/leadConvert", credentials,
            json_body={"inputs": [body]}, action_name="convert_lead",
        )

    async def _handle_merge_records(self, config, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"additionalIds": self._split_ids(config.additional_ids)}
        if config.field_values:
            body.update(self._parse_json_obj(config.field_values))
        return await self._make_request(
            "POST",
            f"/sobjects/{config.object_type}/{config.master_id}/merge",
            credentials, json_body=body, action_name="merge_records",
        )

    async def _handle_create_task(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"Subject": config.subject, "Status": config.status, "Priority": config.priority}
        if config.who_id: fields["WhoId"] = config.who_id
        if config.what_id: fields["WhatId"] = config.what_id
        if config.activity_date: fields["ActivityDate"] = config.activity_date
        if config.description: fields["Description"] = config.description
        if config.owner_id: fields["OwnerId"] = config.owner_id
        return await self._make_request("POST", "/sobjects/Task/", credentials, json_body=fields, action_name="create_task")

    async def _handle_update_task(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}
        for k, attr in [("Status", "status"), ("Priority", "priority"), ("Subject", "subject"), ("ActivityDate", "activity_date"), ("Description", "description")]:
            v = getattr(config, attr)
            if v is not None:
                fields[k] = v
        result = await self._make_request("PATCH", f"/sobjects/Task/{config.task_id}", credentials, json_body=fields, action_name="update_task")
        if result["status"] == "success" and result.get("status_code") == 204:
            result["data"] = {"id": config.task_id, "success": True}
        return result

    async def _handle_create_event(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"Subject": config.subject, "StartDateTime": config.start_datetime, "EndDateTime": config.end_datetime}
        if config.who_id: fields["WhoId"] = config.who_id
        if config.what_id: fields["WhatId"] = config.what_id
        if config.description: fields["Description"] = config.description
        if config.location: fields["Location"] = config.location
        if config.owner_id: fields["OwnerId"] = config.owner_id
        return await self._make_request("POST", "/sobjects/Event/", credentials, json_body=fields, action_name="create_event")

    async def _handle_update_event(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}
        for k, attr in [("Subject", "subject"), ("StartDateTime", "start_datetime"), ("EndDateTime", "end_datetime"), ("Description", "description"), ("Location", "location")]:
            v = getattr(config, attr)
            if v is not None:
                fields[k] = v
        result = await self._make_request("PATCH", f"/sobjects/Event/{config.event_id}", credentials, json_body=fields, action_name="update_event")
        if result["status"] == "success" and result.get("status_code") == 204:
            result["data"] = {"id": config.event_id, "success": True}
        return result

    async def _handle_create_note(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"Title": config.title, "ParentId": config.parent_id, "IsPrivate": (config.is_private == "true")}
        if config.body: fields["Body"] = config.body
        return await self._make_request("POST", "/sobjects/Note/", credentials, json_body=fields, action_name="create_note")

    async def _handle_add_campaign_member(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"CampaignId": config.campaign_id}
        cid = config.lead_or_contact_id
        # Contact IDs start with 003, Lead IDs with 00Q
        if cid.startswith("00Q"):
            fields["LeadId"] = cid
        else:
            fields["ContactId"] = cid
        if config.status: fields["Status"] = config.status
        return await self._make_request("POST", "/sobjects/CampaignMember/", credentials, json_body=fields, action_name="add_campaign_member")

    async def _handle_update_campaign_member_status(self, config, credentials) -> Dict[str, Any]:
        result = await self._make_request("PATCH", f"/sobjects/CampaignMember/{config.member_id}", credentials, json_body={"Status": config.status}, action_name="update_campaign_member_status")
        if result["status"] == "success" and result.get("status_code") == 204:
            result["data"] = {"id": config.member_id, "success": True}
        return result

    async def _handle_create_campaign(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"Name": config.name, "Status": config.status}
        if config.type: fields["Type"] = config.type
        if config.start_date: fields["StartDate"] = config.start_date
        if config.end_date: fields["EndDate"] = config.end_date
        if config.description: fields["Description"] = config.description
        if config.budget_cost is not None: fields["BudgetedCost"] = config.budget_cost
        return await self._make_request("POST", "/sobjects/Campaign/", credentials, json_body=fields, action_name="create_campaign")

    async def _handle_add_case_comment(self, config, credentials) -> Dict[str, Any]:
        fields = {"ParentId": config.parent_id, "CommentBody": config.comment_body, "IsPublished": (config.is_published == "true")}
        return await self._make_request("POST", "/sobjects/CaseComment/", credentials, json_body=fields, action_name="add_case_comment")

    async def _handle_add_opportunity_line_item(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"OpportunityId": config.opportunity_id, "PricebookEntryId": config.pricebook_entry_id, "Quantity": config.quantity}
        if config.unit_price is not None: fields["UnitPrice"] = config.unit_price
        if config.description: fields["Description"] = config.description
        return await self._make_request("POST", "/sobjects/OpportunityLineItem/", credentials, json_body=fields, action_name="add_opportunity_line_item")

    async def _handle_add_contact_to_opportunity(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"OpportunityId": config.opportunity_id, "ContactId": config.contact_id, "IsPrimary": (config.is_primary == "true")}
        if config.role: fields["Role"] = config.role
        return await self._make_request("POST", "/sobjects/OpportunityContactRole/", credentials, json_body=fields, action_name="add_contact_to_opportunity")

    async def _handle_assign_permission_set_to_user(self, config, credentials) -> Dict[str, Any]:
        fields = {"PermissionSetId": config.permission_set_id, "AssigneeId": config.assignee_id}
        return await self._make_request("POST", "/sobjects/PermissionSetAssignment/", credentials, json_body=fields, action_name="assign_permission_set_to_user")

    async def _handle_reset_user_password(self, config, credentials) -> Dict[str, Any]:
        result = await self._make_request("DELETE", f"/sobjects/User/{config.user_id}/password", credentials, action_name="reset_user_password")
        if result["status"] == "success":
            result["data"] = {"id": config.user_id, "password_reset": True}
        return result

    async def _handle_get_content_document(self, config, credentials) -> Dict[str, Any]:
        params = {"fields": config.fields} if config.fields else None
        return await self._make_request("GET", f"/sobjects/ContentDocument/{config.document_id}", credentials, params=params, action_name="get_content_document")

    async def _handle_download_content_version(self, config, credentials) -> Dict[str, Any]:
        access_token = await self._get_access_token(credentials)
        base_url = self._get_base_url(credentials)
        url = f"{base_url}/sobjects/ContentVersion/{config.version_id}/VersionData"
        headers = {"Authorization": f"Bearer {access_token}"}
        start_time = time.time()
        async with guarded_async_client(timeout=120.0) as client:
            try:
                response = await client.get(url, headers=headers)
                api_time = (time.time() - start_time) * 1000
                if response.status_code >= 400:
                    return {"status": "error", "action": "download_content_version", "error": response.text, "status_code": response.status_code, "timing_ms": {"api_request": round(api_time, 2)}}
                from nodes.core.binary_output import BinaryOutput

                content_type = response.headers.get("Content-Type", "application/octet-stream")
                ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
                filename = f"{config.version_id}{ext}"
                return {
                    "status": "success",
                    "action": "download_content_version",
                    "data": {
                        "content_type": content_type,
                        "content_length": len(response.content),
                        "blob": BinaryOutput(
                            data=response.content,
                            content_type=content_type,
                            filename=filename,
                        ),
                    },
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }
            except Exception as e:
                return {"status": "error", "action": "download_content_version", "error": str(e), "status_code": 500, "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}}

    async def _handle_list_content_versions(self, config, credentials) -> Dict[str, Any]:
        soql = f"SELECT Id, Title, ContentDocumentId, VersionNumber, FileType, ContentSize, CreatedDate FROM ContentVersion WHERE ContentDocumentId = '{config.document_id}' ORDER BY VersionNumber DESC LIMIT {config.page_size or 100}"
        return await self._soql(credentials, soql, "list_content_versions")

    async def _handle_delete_content_document(self, config, credentials) -> Dict[str, Any]:
        result = await self._make_request("DELETE", f"/sobjects/ContentDocument/{config.document_id}", credentials, action_name="delete_content_document")
        if result["status"] == "success" and result.get("status_code") == 204:
            result["data"] = {"id": config.document_id, "deleted": True}
        return result

    async def _handle_create_content_document_link(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"ContentDocumentId": config.content_document_id, "LinkedEntityId": config.linked_entity_id, "ShareType": config.share_type}
        if config.visibility: fields["Visibility"] = config.visibility
        return await self._make_request("POST", "/sobjects/ContentDocumentLink/", credentials, json_body=fields, action_name="create_content_document_link")

    async def _handle_list_files_linked_to_record(self, config, credentials) -> Dict[str, Any]:
        soql = f"SELECT Id, ContentDocumentId, ContentDocument.Title, ContentDocument.FileType, ContentDocument.ContentSize, LinkedEntityId, ShareType FROM ContentDocumentLink WHERE LinkedEntityId = '{config.record_id}'"
        return await self._soql(credentials, soql, "list_files_linked_to_record")

    async def _handle_send_single_email(self, config, credentials) -> Dict[str, Any]:
        inp: Dict[str, Any] = {"emailAddresses": config.to_addresses, "emailSubject": config.subject, "emailBody": config.body}
        if config.cc_addresses: inp["ccEmailAddresses"] = config.cc_addresses
        if config.bcc_addresses: inp["bccEmailAddresses"] = config.bcc_addresses
        if config.sender_display_name: inp["senderDisplayName"] = config.sender_display_name
        return await self._make_request("POST", "/actions/standard/emailSimple", credentials, json_body={"inputs": [inp]}, action_name="send_single_email")

    async def _handle_send_email_via_template(self, config, credentials) -> Dict[str, Any]:
        inp: Dict[str, Any] = {"templateId": config.template_id, "targetObjectId": config.recipient_id, "bccSender": (config.bcc_sender == "true"), "saveAsActivity": (config.save_as_activity == "true")}
        if config.what_id: inp["whatId"] = config.what_id
        return await self._make_request("POST", "/actions/standard/emailSimple", credentials, json_body={"inputs": [inp]}, action_name="send_email_via_template")

    async def _handle_list_email_templates(self, config, credentials) -> Dict[str, Any]:
        where = "WHERE IsActive = true"
        if config.folder_name:
            where += f" AND FolderName = '{config.folder_name}'"
        soql = f"SELECT Id, Name, Subject, FolderName, IsActive FROM EmailTemplate {where} ORDER BY Name LIMIT {config.page_size or 200}"
        return await self._soql(credentials, soql, "list_email_templates")

    async def _handle_send_mass_email(self, config, credentials) -> Dict[str, Any]:
        inp: Dict[str, Any] = {"templateId": config.template_id, "targetObjectIds": self._split_ids(config.target_ids)}
        if config.activity_date: inp["activityDate"] = config.activity_date
        return await self._make_request("POST", "/actions/standard/massSendEmail", credentials, json_body={"inputs": [inp]}, action_name="send_mass_email")

    async def _handle_get_chatter_feed_item(self, config, credentials) -> Dict[str, Any]:
        return await self._make_request("GET", self._chatter_url(credentials, f"/feed-elements/{config.feed_item_id}"), credentials, action_name="get_chatter_feed_item", use_full_url=True)

    async def _handle_delete_chatter_feed_item(self, config, credentials) -> Dict[str, Any]:
        result = await self._make_request("DELETE", self._chatter_url(credentials, f"/feed-elements/{config.feed_item_id}"), credentials, action_name="delete_chatter_feed_item", use_full_url=True)
        if result["status"] == "success" and result.get("status_code") in (204, 200):
            result["data"] = {"id": config.feed_item_id, "deleted": True}
        return result

    async def _handle_create_chatter_comment(self, config, credentials) -> Dict[str, Any]:
        body = {"body": {"messageSegments": [{"type": "Text", "text": config.message_text}]}}
        return await self._make_request("POST", self._chatter_url(credentials, f"/feed-elements/{config.feed_item_id}/capabilities/comments/items"), credentials, json_body=body, action_name="create_chatter_comment", use_full_url=True)

    async def _handle_get_chatter_comments(self, config, credentials) -> Dict[str, Any]:
        params = {"pageSize": config.page_size} if config.page_size else None
        return await self._make_request("GET", self._chatter_url(credentials, f"/feed-elements/{config.feed_item_id}/capabilities/comments/items"), credentials, params=params, action_name="get_chatter_comments", use_full_url=True)

    async def _handle_delete_chatter_comment(self, config, credentials) -> Dict[str, Any]:
        result = await self._make_request("DELETE", self._chatter_url(credentials, f"/comments/{config.comment_id}"), credentials, action_name="delete_chatter_comment", use_full_url=True)
        if result["status"] == "success" and result.get("status_code") in (204, 200):
            result["data"] = {"id": config.comment_id, "deleted": True}
        return result

    async def _handle_like_chatter_feed_item(self, config, credentials) -> Dict[str, Any]:
        return await self._make_request("POST", self._chatter_url(credentials, f"/feed-elements/{config.feed_item_id}/capabilities/chatter-likes/items"), credentials, action_name="like_chatter_feed_item", use_full_url=True)

    async def _handle_get_record_chatter_feed(self, config, credentials) -> Dict[str, Any]:
        params = {"pageSize": config.page_size} if config.page_size else None
        return await self._make_request("GET", self._chatter_url(credentials, f"/feeds/record/{config.record_id}/feed-elements"), credentials, params=params, action_name="get_record_chatter_feed", use_full_url=True)

    async def _handle_get_chatter_user_profile(self, config, credentials) -> Dict[str, Any]:
        return await self._make_request("GET", self._chatter_url(credentials, f"/users/{config.user_id or 'me'}"), credentials, action_name="get_chatter_user_profile", use_full_url=True)

    async def _handle_list_chatter_groups(self, config, credentials) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if config.page_size: params["pageSize"] = config.page_size
        if config.search_query: params["q"] = config.search_query
        return await self._make_request("GET", self._chatter_url(credentials, "/groups"), credentials, params=params or None, action_name="list_chatter_groups", use_full_url=True)

    async def _handle_post_to_chatter_group(self, config, credentials) -> Dict[str, Any]:
        segments: List[Dict[str, Any]] = []
        for uid in self._split_ids(config.mention_ids or ""):
            segments.append({"type": "Mention", "id": uid})
        segments.append({"type": "Text", "text": config.message_text})
        body = {"body": {"messageSegments": segments}, "feedElementType": "FeedItem", "subjectId": config.group_id}
        return await self._make_request("POST", self._chatter_url(credentials, f"/feeds/group/{config.group_id}/feed-elements"), credentials, json_body=body, action_name="post_to_chatter_group", use_full_url=True)

    async def _handle_get_chatter_group_members(self, config, credentials) -> Dict[str, Any]:
        params = {"pageSize": config.page_size} if config.page_size else None
        return await self._make_request("GET", self._chatter_url(credentials, f"/groups/{config.group_id}/members"), credentials, params=params, action_name="get_chatter_group_members", use_full_url=True)

    async def _handle_send_chatter_direct_message(self, config, credentials) -> Dict[str, Any]:
        recipients = [{"id": uid} for uid in self._split_ids(config.recipient_ids)]
        body = {"recipients": {"users": recipients}, "body": {"messageSegments": [{"type": "Text", "text": config.message_text}]}}
        return await self._make_request("POST", self._chatter_url(credentials, "/direct-messages"), credentials, json_body=body, action_name="send_chatter_direct_message", use_full_url=True)

    async def _handle_get_chatter_direct_messages(self, config, credentials) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if config.page_size: params["pageSize"] = config.page_size
        path = f"/direct-messages/{config.conversation_id}" if config.conversation_id else "/direct-messages"
        return await self._make_request("GET", self._chatter_url(credentials, path), credentials, params=params or None, action_name="get_chatter_direct_messages", use_full_url=True)

    async def _handle_search_chatter(self, config, credentials) -> Dict[str, Any]:
        params: Dict[str, Any] = {"q": config.query}
        if config.page_size: params["pageSize"] = config.page_size
        return await self._make_request("GET", self._chatter_url(credentials, "/feed-elements"), credentials, params=params, action_name="search_chatter", use_full_url=True)

    async def _handle_get_chatter_news_feed(self, config, credentials) -> Dict[str, Any]:
        params = {"pageSize": config.page_size} if config.page_size else None
        return await self._make_request("GET", self._chatter_url(credentials, "/feeds/news/me/feed-elements"), credentials, params=params, action_name="get_chatter_news_feed", use_full_url=True)

    async def _handle_execute_anonymous_apex(self, config, credentials) -> Dict[str, Any]:
        encoded = quote(config.apex_code, safe="")
        return await self._make_request("GET", self._tooling_url(credentials, f"/executeAnonymous/?anonymousBody={encoded}"), credentials, action_name="execute_anonymous_apex", use_full_url=True)

    async def _handle_run_apex_tests(self, config, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if config.max_failed_tests is not None and config.max_failed_tests >= 0:
            body["maxFailedTests"] = config.max_failed_tests
        if config.class_names:
            body["classNames"] = config.class_names
        if config.suite_ids:
            body["suiteids"] = config.suite_ids
        # If no specific classes/suites, run all tests
        if not config.class_names and not config.suite_ids:
            body["testLevel"] = "RunAllTestsInOrg"
        result = await self._make_request("POST", self._tooling_url(credentials, "/runTestsAsynchronous"), credentials, json_body=body, action_name="run_apex_tests", use_full_url=True)
        # If RunAllTestsInOrg fails, try RunLocalTests
        if result.get("status") == "error" and not config.class_names and not config.suite_ids:
            body["testLevel"] = "RunLocalTests"
            result = await self._make_request("POST", self._tooling_url(credentials, "/runTestsAsynchronous"), credentials, json_body=body, action_name="run_apex_tests", use_full_url=True)
        return result

    async def _handle_get_apex_test_results(self, config, credentials) -> Dict[str, Any]:
        soql = f"SELECT Id, ApexClassId, Status, ExtendedStatus FROM ApexTestQueueItem WHERE ParentJobId = '{config.job_id}'"
        return await self._make_request("GET", self._tooling_url(credentials, f"/query/?q={quote(soql, safe='')}"), credentials, action_name="get_apex_test_results", use_full_url=True)

    async def _handle_query_debug_logs(self, config, credentials) -> Dict[str, Any]:
        where = f"WHERE LogUserId = '{config.user_id}'" if config.user_id else ""
        soql = f"SELECT Id, LogUser.Name, Operation, Status, LogLength, LastModifiedDate FROM ApexLog {where} ORDER BY LastModifiedDate DESC LIMIT {config.page_size or 20}"
        return await self._make_request("GET", self._tooling_url(credentials, f"/query/?q={quote(soql, safe='')}"), credentials, action_name="query_debug_logs", use_full_url=True)

    async def _handle_get_debug_log_body(self, config, credentials) -> Dict[str, Any]:
        access_token = await self._get_access_token(credentials)
        url = self._tooling_url(credentials, f"/sobjects/ApexLog/{config.log_id}/Body")
        headers = {"Authorization": f"Bearer {access_token}"}
        start_time = time.time()
        async with guarded_async_client(timeout=60.0) as client:
            try:
                response = await client.get(url, headers=headers)
                api_time = (time.time() - start_time) * 1000
                if response.status_code >= 400:
                    return {"status": "error", "action": "get_debug_log_body", "error": response.text, "status_code": response.status_code, "timing_ms": {"api_request": round(api_time, 2)}}
                return {"status": "success", "action": "get_debug_log_body", "data": {"log_body": response.text}, "status_code": response.status_code, "timing_ms": {"api_request": round(api_time, 2)}}
            except Exception as e:
                return {"status": "error", "action": "get_debug_log_body", "error": str(e), "status_code": 500, "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}}

    async def _handle_create_trace_flag(self, config, credentials) -> Dict[str, Any]:
        body = {"TracedEntityId": config.traced_entity_id, "DebugLevelId": config.debug_level_id, "ExpirationDate": config.expiration_date, "LogType": config.log_type}
        return await self._make_request("POST", self._tooling_url(credentials, "/sobjects/TraceFlag/"), credentials, json_body=body, action_name="create_trace_flag", use_full_url=True)

    async def _handle_get_apex_code_coverage(self, config, credentials) -> Dict[str, Any]:
        where = f"WHERE ApexClassOrTrigger.Name = '{config.class_name_filter}'" if config.class_name_filter else ""
        soql = f"SELECT ApexClassOrTriggerId, ApexClassOrTrigger.Name, NumLinesCovered, NumLinesUncovered FROM ApexCodeCoverageAggregate {where}"
        return await self._make_request("GET", self._tooling_url(credentials, f"/query/?q={quote(soql, safe='')}"), credentials, action_name="get_apex_code_coverage", use_full_url=True)

    async def _handle_tooling_soql_query(self, config, credentials) -> Dict[str, Any]:
        return await self._make_request("GET", self._tooling_url(credentials, f"/query/?q={quote(config.query, safe='')}"), credentials, action_name="tooling_soql_query", use_full_url=True)

    async def _handle_get_pending_approval_items(self, config, credentials) -> Dict[str, Any]:
        return await self._make_request("GET", "/process/approvals/", credentials, action_name="get_pending_approval_items")

    async def _handle_recall_approval_request(self, config, credentials) -> Dict[str, Any]:
        req: Dict[str, Any] = {"actionType": "Removed", "contextId": config.process_instance_id}
        if config.comments: req["comments"] = config.comments
        return await self._make_request("POST", "/process/approvals/", credentials, json_body={"requests": [req]}, action_name="recall_approval_request")

    async def _handle_get_approval_history(self, config, credentials) -> Dict[str, Any]:
        soql = f"SELECT Id, StepStatus, ActorId, Actor.Name, Comments, CreatedDate FROM ProcessInstanceStep WHERE ProcessInstance.TargetObjectId = '{config.record_id}' ORDER BY CreatedDate DESC"
        return await self._soql(credentials, soql, "get_approval_history")

    async def _bulk_csv_get(
        self,
        credentials,
        endpoint: str,
        action_name: str,
    ) -> Dict[str, Any]:
        """Fetch Bulk API CSV from the instance selected by a fresh token."""
        access_token = await self._get_access_token(credentials)
        url = f"{self._get_base_url(credentials)}{endpoint}"
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "text/csv"}
        start_time = time.time()
        async with guarded_async_client(timeout=120.0) as client:
            try:
                response = await client.get(url, headers=headers)
                api_time = (time.time() - start_time) * 1000
                if response.status_code >= 400:
                    return {"status": "error", "action": action_name, "error": response.text, "status_code": response.status_code, "timing_ms": {"api_request": round(api_time, 2)}}
                return {"status": "success", "action": action_name, "data": {"csv_data": response.text}, "status_code": response.status_code, "timing_ms": {"api_request": round(api_time, 2)}}
            except Exception as e:
                return {"status": "error", "action": action_name, "error": str(e), "status_code": 500, "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}}

    async def _handle_get_bulk_job_failed_results(self, config, credentials) -> Dict[str, Any]:
        endpoint = f"/jobs/ingest/{config.job_id}/failedResults"
        return await self._bulk_csv_get(
            credentials,
            endpoint,
            "get_bulk_job_failed_results",
        )

    async def _handle_get_bulk_job_unprocessed_results(self, config, credentials) -> Dict[str, Any]:
        endpoint = f"/jobs/ingest/{config.job_id}/unprocessedrecords"
        return await self._bulk_csv_get(
            credentials,
            endpoint,
            "get_bulk_job_unprocessed_results",
        )

    async def _handle_delete_bulk_data_job(self, config, credentials) -> Dict[str, Any]:
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/jobs/ingest/{config.job_id}"
        result = await self._make_request("DELETE", url, credentials, action_name="delete_bulk_data_job", use_full_url=True)
        if result["status"] == "success" and result.get("status_code") in (204, 200):
            result["data"] = {"id": config.job_id, "deleted": True}
        return result

    async def _handle_create_bulk_query_job(self, config, credentials) -> Dict[str, Any]:
        body = {"operation": "query", "query": config.soql_query, "columnDelimiter": config.column_delimiter or "COMMA", "lineEnding": config.line_ending or "LF"}
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/jobs/query"
        return await self._make_request("POST", url, credentials, json_body=body, action_name="create_bulk_query_job", use_full_url=True)

    async def _handle_get_bulk_query_job_results(self, config, credentials) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if config.locator: params["locator"] = config.locator
        if config.max_records: params["maxRecords"] = config.max_records
        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        endpoint = f"/jobs/query/{config.job_id}/results{query}"
        return await self._bulk_csv_get(
            credentials,
            endpoint,
            "get_bulk_query_job_results",
        )

    async def _handle_execute_composite_batch(self, config, credentials) -> Dict[str, Any]:
        body = {"batchRequests": self._parse_json_list(config.subrequests), "haltOnError": (config.halt_on_error == "true")}
        return await self._make_request("POST", "/composite/batch", credentials, json_body=body, action_name="execute_composite_batch")

    async def _handle_bulk_retrieve_records(self, config, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"ids": self._split_ids(config.record_ids)}
        if config.fields:
            body["fields"] = [f.strip() for f in config.fields.split(",") if f.strip()]
        else:
            body["fields"] = ["Id"]
        return await self._make_request("POST", f"/composite/sobjects/{config.sobject_type}", credentials, json_body=body, action_name="bulk_retrieve_records")

    async def _handle_composite_update_multiple(self, config, credentials) -> Dict[str, Any]:
        body = {"allOrNone": (config.all_or_none == "true"), "records": self._parse_json_list(config.records)}
        return await self._make_request("PATCH", "/composite/sobjects", credentials, json_body=body, action_name="composite_update_multiple")

    async def _handle_run_report_async(self, config, credentials) -> Dict[str, Any]:
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/reports/{config.report_id}/instances"
        body = None
        if config.filters:
            body = {"reportMetadata": {"reportFilters": self._parse_json_list(config.filters)}}
        return await self._make_request("POST", url, credentials, json_body=body, action_name="run_report_async", use_full_url=True)

    async def _handle_get_async_report_result(self, config, credentials) -> Dict[str, Any]:
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/reports/{config.report_id}/instances/{config.instance_id}"
        return await self._make_request("GET", url, credentials, action_name="get_async_report_result", use_full_url=True)

    async def _handle_get_dashboard_component_data(self, config, credentials) -> Dict[str, Any]:
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/dashboards/{config.dashboard_id}/{config.component_id}"
        return await self._make_request("GET", url, credentials, action_name="get_dashboard_component_data", use_full_url=True)

    async def _handle_list_report_folders(self, config, credentials) -> Dict[str, Any]:
        instance_url = credentials.instance_url.rstrip("/")
        params = {"type": config.type or "report", "pageSize": config.page_size or 50}
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/folders"
        return await self._make_request("GET", url, credentials, params=params, action_name="list_report_folders", use_full_url=True)

    async def _handle_execute_flow(self, config, credentials) -> Dict[str, Any]:
        inp = self._parse_json_obj(config.input_variables) if config.input_variables else {}
        return await self._make_request("POST", f"/actions/custom/flow/{config.flow_api_name}", credentials, json_body={"inputs": [inp]}, action_name="execute_flow")

    async def _handle_list_flows(self, config, credentials) -> Dict[str, Any]:
        where = "WHERE Status = 'Active'"
        if config.process_type:
            where += f" AND ProcessType = '{config.process_type}'"
        soql = f"SELECT Id, MasterLabel, ProcessType, Status FROM Flow {where} ORDER BY MasterLabel"
        return await self._make_request("GET", self._tooling_url(credentials, f"/query/?q={quote(soql, safe='')}"), credentials, action_name="list_flows", use_full_url=True)

    async def _handle_invoke_email_alert_action(self, config, credentials) -> Dict[str, Any]:
        inp: Dict[str, Any] = {"objectId": config.record_id}
        if config.context_id: inp["contextId"] = config.context_id
        return await self._make_request("POST", f"/actions/custom/emailAlert/{config.object_type}/{config.action_name}", credentials, json_body={"inputs": [inp]}, action_name="invoke_email_alert_action")

    async def _handle_invoke_field_update_action(self, config, credentials) -> Dict[str, Any]:
        return await self._make_request("POST", f"/actions/custom/fieldUpdate/{config.object_type}/{config.action_name}", credentials, json_body={"inputs": [{"objectId": config.record_id}]}, action_name="invoke_field_update_action")

    async def _handle_get_org_info(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Name, InstanceName, IsSandbox, OrganizationType, DefaultLocaleSidKey FROM Organization LIMIT 1"
        return await self._soql(credentials, soql, "get_org_info")

    async def _handle_parameterized_search(self, config, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"q": config.query, "sobjects": self._parse_json_list(config.sobjects)}
        if config.page_size:
            body["overallLimit"] = config.page_size
        return await self._make_request("POST", "/parameterizedSearch/", credentials, json_body=body, action_name="parameterized_search")

    async def _handle_get_search_suggestions(self, config, credentials) -> Dict[str, Any]:
        params = {"q": config.query, "sobject": config.sobject_type or "Account", "limit": config.page_size or 10}
        return await self._make_request("GET", "/search/suggestions", credentials, params=params, action_name="get_search_suggestions")

    async def _handle_explain_query_plan(self, config, credentials) -> Dict[str, Any]:
        return await self._make_request("GET", f"/query/?explain={quote(config.query, safe='')}", credentials, action_name="explain_query_plan")

    async def _handle_get_record_count(self, config, credentials) -> Dict[str, Any]:
        params = {"sObjects": config.object_type}
        return await self._make_request("GET", "/limits/recordCount", credentials, params=params, action_name="get_record_count")

    async def _handle_list_users(self, config, credentials) -> Dict[str, Any]:
        clauses = []
        if (config.is_active or "true") == "true":
            clauses.append("IsActive = true")
        if config.profile_id:
            clauses.append(f"ProfileId = '{config.profile_id}'")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        soql = f"SELECT Id, Name, Email, Username, IsActive, ProfileId, UserRoleId FROM User {where} ORDER BY Name LIMIT {config.page_size or 100}"
        return await self._soql(credentials, soql, "list_users")

    async def _handle_get_user(self, config, credentials) -> Dict[str, Any]:
        params = {"fields": config.fields} if config.fields else None
        return await self._make_request("GET", f"/sobjects/User/{config.user_id}", credentials, params=params, action_name="get_user")

    async def _handle_update_user(self, config, credentials) -> Dict[str, Any]:
        fields = self._parse_json_obj(config.field_updates)
        result = await self._make_request("PATCH", f"/sobjects/User/{config.user_id}", credentials, json_body=fields, action_name="update_user")
        if result["status"] == "success" and result.get("status_code") == 204:
            result["data"] = {"id": config.user_id, "success": True}
        return result

    async def _handle_list_profiles(self, config, credentials) -> Dict[str, Any]:
        soql = f"SELECT Id, Name, UserType, Description FROM Profile ORDER BY Name LIMIT {config.page_size or 100}"
        return await self._soql(credentials, soql, "list_profiles")

    async def _handle_list_roles(self, config, credentials) -> Dict[str, Any]:
        soql = f"SELECT Id, Name, DeveloperName, ParentRoleId FROM UserRole ORDER BY Name LIMIT {config.page_size or 100}"
        return await self._soql(credentials, soql, "list_roles")

    async def _handle_get_org_storage_usage(self, config, credentials) -> Dict[str, Any]:
        return await self._make_request("GET", "/limits/recordCount", credentials, action_name="get_org_storage_usage")

    async def _handle_list_external_data_sources(self, config, credentials) -> Dict[str, Any]:
        soql = f"SELECT Id, DeveloperName, MasterLabel, Type FROM ExternalDataSource LIMIT {config.page_size or 50}"
        return await self._make_request("GET", self._tooling_url(credentials, f"/query/?q={quote(soql, safe='')}"), credentials, action_name="list_external_data_sources", use_full_url=True)

    async def _handle_query_external_object(self, config, credentials) -> Dict[str, Any]:
        return await self._soql(credentials, config.query, "query_external_object")

    async def _handle_create_external_object_record(self, config, credentials) -> Dict[str, Any]:
        fields = self._parse_json_obj(config.field_values)
        return await self._make_request("POST", f"/sobjects/{config.external_object_type}/", credentials, json_body=fields, action_name="create_external_object_record")

    async def _handle_list_knowledge_articles(self, config, credentials) -> Dict[str, Any]:
        # Try Knowledge__kav (custom) first, fall back to KnowledgeArticleVersion
        clauses = [f"PublishStatus = '{config.publish_status or 'Online'}'", f"Language = '{config.language or 'en_US'}'"]
        if config.search_term:
            clauses.append(f"Title LIKE '%{config.search_term}%'")
        where = "WHERE " + " AND ".join(clauses)
        soql = f"SELECT Id, Title, Summary, ArticleNumber, PublishStatus FROM KnowledgeArticleVersion {where} ORDER BY Title LIMIT {config.page_size or 50}"
        result = await self._soql(credentials, soql, "list_knowledge_articles")
        # If KnowledgeArticleVersion not supported (Knowledge not enabled), return empty list
        if result.get("status") == "error" and "INVALID_TYPE" in result.get("error_code", ""):
            return {"status": "success", "action": "list_knowledge_articles", "data": {"records": [], "totalSize": 0, "done": True, "note": "Knowledge is not enabled in this org"}, "status_code": 200, "timing_ms": result.get("timing_ms", {})}
        return result

    async def _handle_create_knowledge_article(self, config, credentials) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"Title": config.title}
        if config.article_body: fields["ArticleBody__c"] = config.article_body
        if config.summary: fields["Summary"] = config.summary
        if config.url_name: fields["UrlName"] = config.url_name
        else:
            fields["UrlName"] = config.title.lower().replace(" ", "-")
        return await self._make_request("POST", "/sobjects/Knowledge__kav/", credentials, json_body=fields, action_name="create_knowledge_article")

    async def _handle_publish_knowledge_article(self, config, credentials) -> Dict[str, Any]:
        body = {"inputs": [{"articleVersionIds": [config.article_id]}]}
        return await self._make_request("POST", "/actions/standard/publishKnowledgeArticles", credentials, json_body=body, action_name="publish_knowledge_article")

    async def _handle_attach_article_to_case(self, config, credentials) -> Dict[str, Any]:
        fields = {"CaseId": config.case_id, "KnowledgeArticleVersionId": config.knowledge_article_version_id}
        return await self._make_request("POST", "/sobjects/CaseArticle/", credentials, json_body=fields, action_name="attach_article_to_case")

    async def _handle_publish_platform_event(self, config, credentials) -> Dict[str, Any]:
        payload = self._parse_json_obj(config.payload)
        event_type = config.event_type
        if not event_type.endswith("__e"):
            event_type = f"{event_type}__e"
        return await self._make_request("POST", f"/sobjects/{event_type}/", credentials, json_body=payload, action_name="publish_platform_event")

    async def _handle_list_platform_event_channels(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, DeveloperName, MasterLabel FROM PlatformEventChannel"
        return await self._make_request("GET", self._tooling_url(credentials, f"/query/?q={quote(soql, safe='')}"), credentials, action_name="list_platform_event_channels", use_full_url=True)

    async def _handle_get_list_view_results_with_columns(self, config, credentials) -> Dict[str, Any]:
        params = {"pageSize": config.page_size} if config.page_size else None
        return await self._make_request("GET", f"/sobjects/{config.object_type}/listviews/{config.list_view_id}/results", credentials, params=params, action_name="get_list_view_results_with_columns")

    # =========================================================================
    # Poll Trigger Handlers
    # =========================================================================

    async def _poll_query(self, credentials, soql: str, action_name: str, id_fn) -> Dict[str, Any]:
        """Run a SOQL poll query and emit only unseen records."""
        result = await self._soql(credentials, soql, action_name)
        if result.get("status") == "error":
            raise ValueError(f"Salesforce poll failed: {result.get('error') or result.get('data')}")
        records = (result.get("data") or {}).get("records", [])
        new_items = await self._filter_unseen(records, id_fn)
        return {"items": new_items, "new_item_count": len(new_items)}

    @staticmethod
    def _created_id(r):
        return r.get("Id")

    @staticmethod
    def _modified_id(r):
        rid = r.get("Id")
        return f"{rid}:{r.get('LastModifiedDate', '')}" if rid else None

    async def _trigger_on_new_lead(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, FirstName, LastName, Email, Company, Status, Phone, LeadSource, CreatedDate FROM Lead ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_lead", self._created_id)

    async def _trigger_on_new_contact(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, FirstName, LastName, Email, AccountId, Phone, Title, CreatedDate FROM Contact ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_contact", self._created_id)

    async def _trigger_on_new_account(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Name, Type, Industry, BillingCity, Phone, OwnerId, CreatedDate FROM Account ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_account", self._created_id)

    async def _trigger_on_new_opportunity(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Name, StageName, Amount, CloseDate, AccountId, OwnerId, Probability, CreatedDate FROM Opportunity ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_opportunity", self._created_id)

    async def _trigger_on_new_case(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, CaseNumber, Subject, Status, Priority, AccountId, ContactId, OwnerId, CreatedDate FROM Case ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_case", self._created_id)

    async def _trigger_on_updated_lead(self, config, credentials) -> Dict[str, Any]:
        where = f"WHERE {config.soql_where_clause} " if getattr(config, "soql_where_clause", None) else ""
        soql = f"SELECT Id, FirstName, LastName, Email, Company, Status, LastModifiedDate FROM Lead {where}ORDER BY LastModifiedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_updated_lead", self._modified_id)

    async def _trigger_on_updated_opportunity(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Name, StageName, Amount, CloseDate, AccountId, LastModifiedDate FROM Opportunity ORDER BY LastModifiedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_updated_opportunity", self._modified_id)

    async def _trigger_on_updated_case(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, CaseNumber, Subject, Status, Priority, AccountId, LastModifiedDate FROM Case ORDER BY LastModifiedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_updated_case", self._modified_id)

    async def _trigger_on_new_task(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Subject, Status, Priority, WhoId, WhatId, ActivityDate, OwnerId, CreatedDate FROM Task ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_task", self._created_id)

    async def _trigger_on_opportunity_stage_change(self, config, credentials) -> Dict[str, Any]:
        stage = config.stage_name.replace("'", "\\'")
        soql = f"SELECT Id, Name, StageName, Amount, AccountId, LastModifiedDate FROM Opportunity WHERE StageName = '{stage}' ORDER BY LastModifiedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_opportunity_stage_change", self._modified_id)

    async def _trigger_on_new_file_upload(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Title, FileExtension, ContentDocumentId, ContentSize, OwnerId, CreatedDate FROM ContentVersion WHERE IsLatest = true ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_file_upload", self._created_id)

    async def _trigger_on_new_approval_request(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Status, TargetObjectId, SubmittedById, CreatedDate FROM ProcessInstance WHERE Status = 'Pending' ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_approval_request", self._created_id)

    async def _trigger_on_approval_decision(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Status, TargetObjectId, CompletedDate, LastModifiedDate FROM ProcessInstance WHERE Status IN ('Approved','Rejected') ORDER BY LastModifiedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_approval_decision", self._modified_id)

    async def _trigger_on_new_chatter_post_on_record(self, config, credentials) -> Dict[str, Any]:
        soql = f"SELECT Id, Body, ParentId, CreatedById, CreatedDate FROM FeedItem WHERE ParentId = '{config.record_id}' ORDER BY CreatedDate DESC LIMIT 200"
        return await self._poll_query(credentials, soql, "on_new_chatter_post_on_record", self._created_id)

    async def _trigger_on_chatter_mention(self, config, credentials) -> Dict[str, Any]:
        # FeedItem.Body is not filterable in SOQL; fetch all recent items and filter in Python
        soql = "SELECT Id, Body, ParentId, CreatedById, CreatedDate FROM FeedItem ORDER BY CreatedDate DESC LIMIT 200"
        result = await self._soql(credentials, soql, "on_chatter_mention")
        if result.get("status") == "error":
            raise ValueError(f"Salesforce poll failed: {result.get('error') or result.get('data')}")
        records = (result.get("data") or {}).get("records", [])
        mention_text = getattr(config, "mention_text", None)
        if mention_text:
            records = [r for r in records if mention_text.lower() in (r.get("Body") or "").lower()]
        new_items = await self._filter_unseen(records, self._created_id)
        return {"items": new_items, "new_item_count": len(new_items)}

    async def _trigger_on_new_user(self, config, credentials) -> Dict[str, Any]:
        soql = "SELECT Id, Name, Email, Username, ProfileId, CreatedDate FROM User ORDER BY CreatedDate DESC LIMIT 50"
        return await self._poll_query(credentials, soql, "on_new_user", self._created_id)

    async def _trigger_on_report_threshold_crossed(self, config, credentials) -> Dict[str, Any]:
        instance_url = credentials.instance_url.rstrip("/")
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/analytics/reports/{config.report_id}"
        result = await self._make_request("GET", url, credentials, action_name="on_report_threshold_crossed", use_full_url=True)
        if result.get("status") == "error":
            raise ValueError(f"Salesforce report poll failed: {result.get('error') or result.get('data')}")
        data = result.get("data") or {}
        grand_total = ((data.get("factMap") or {}).get("T!T") or {}).get("aggregates") or []
        value = None
        for agg in grand_total:
            if agg.get("label") == config.column_name:
                value = agg.get("value")
                break
        if value is None and grand_total:
            value = grand_total[0].get("value")
        if value is None:
            return {"items": [], "new_item_count": 0, "current_value": None}
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return {"items": [], "new_item_count": 0, "current_value": value}
        thr = config.threshold
        cmp = config.comparison
        crossed = (
            (cmp == "gt" and numeric > thr)
            or (cmp == "lt" and numeric < thr)
            or (cmp == "gte" and numeric >= thr)
            or (cmp == "lte" and numeric <= thr)
            or (cmp == "eq" and numeric == thr)
        )
        if not crossed:
            return {"items": [], "new_item_count": 0, "current_value": numeric}
        item = {"report_id": config.report_id, "column_name": config.column_name, "value": numeric, "threshold": thr, "comparison": cmp}
        new_items = await self._filter_unseen([item], lambda i: f"{config.report_id}:{numeric}")
        return {"items": new_items, "new_item_count": len(new_items), "current_value": numeric}
