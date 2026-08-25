"""
Google Cloud Storage automation node.

Provides workflow integration with Google Cloud Storage (JSON API v1 plus the
Storage Intelligence JSON v2 surface) for
operations including:
- Buckets: list, get, create, update, patch, delete, lock retention policy,
  get storage layout, restore soft-deleted buckets, relocate buckets
- Bucket IAM: get policy, set policy, test permissions
- Objects: list, get metadata, download, upload, update, patch, delete, copy,
  rewrite, compose, move, restore, bulk restore, get ACL
- Notifications: create, get, list, delete Pub/Sub notification configs
- Operations: get, list, cancel, advance relocate bucket
- Projects: create, get, list, update, delete HMAC keys; get service account

Authentication: bearer access tokens via either:
- Google OAuth 2.0 user credentials
- Google service-account JSON key -> JWT bearer exchange
API Base URL: https://storage.googleapis.com/storage/v1
              (uploads: https://storage.googleapis.com/upload/storage/v1)
              (intelligence config: https://storage.googleapis.com/v2)
Documentation: https://cloud.google.com/storage/docs/json_api/v1

Static Google API keys cannot authenticate private data access, and HMAC keys
are only for the XML API. The handler for x-oauth-provider="google" is shared
with the other Google nodes, so no new OAuth app-handler is required.
"""

import base64
import json
import logging
import time
import uuid as uuid_module
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from urllib.parse import quote
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx
import jwt

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.schedule_registration import CronScheduleTriggerMixin
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)
from nodes.scopes.google_cloud import GOOGLE_CLOUD_STORAGE_SCOPES
from utils.google_service_account import require_google_service_account_token_uri
from utils.ssrf import assert_url_allowed, guarded_async_client

logger = logging.getLogger(__name__)

GCS_API_BASE = "https://storage.googleapis.com/storage/v1"
GCS_UPLOAD_BASE = "https://storage.googleapis.com/upload/storage/v1"
GCS_V2_BASE = "https://storage.googleapis.com/v2"

# OAuth scope needed for full read/write data + metadata access.
GCS_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/devstorage.read_write",
    "https://www.googleapis.com/auth/devstorage.full_control",
]


def _bucket_dynamic_options(field_name: str = "bucket") -> Dict[str, Any]:
    return {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": "Select a bucket...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or type a bucket name",
        },
        "x-resource-type": "google_cloud_storage_bucket",
    }


def _folder_dynamic_options(field_name: str = "folder_name") -> Dict[str, Any]:
    return {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": "Select a folder...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or type a folder path",
        },
        "x-resource-type": "google_cloud_storage_folder",
    }


def _managed_folder_dynamic_options(field_name: str = "managed_folder") -> Dict[str, Any]:
    return {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": "Select a managed folder...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or type a managed folder path",
        },
        "x-resource-type": "google_cloud_storage_managed_folder",
    }


# ============================================================================
# Credential Schema
# ============================================================================


class GoogleCloudStorageOAuthCredential(BaseModel):
    """OAuth credential for Google Cloud Storage access.

    Tokens are obtained via the Google OAuth flow, not entered manually.
    """

    credential_type: Literal["google_cloud_storage_oauth"] = Field(
        "google_cloud_storage_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
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
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-oauth-scopes": GCS_OAUTH_SCOPES,
            "x-credential-url": "https://console.cloud.google.com/apis/credentials",
        }
    )


class GoogleCloudStorageServiceAccountCredential(BaseModel):
    """Service-account JSON key for server-to-server Cloud Storage access."""

    credential_type: Literal["google_cloud_storage_service_account"] = Field(
        "google_cloud_storage_service_account",
        json_schema_extra={"ui:hidden": True},
    )
    service_account_json: str = Field(
        ...,
        title="Service Account JSON",
        description="Raw JSON key for a Google Cloud service account with Cloud Storage access",
        json_schema_extra={
            "ui:widget": "textarea",
            "ui:rows": 12,
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.cloud.google.com/iam-admin/serviceaccounts",
            "x-credential-instructions": (
                "Create a JSON key for a service account that has the required "
                "Cloud Storage IAM roles. Prefer user OAuth for user-delegated "
                "access; use service accounts for server-to-server automation."
            ),
        }
    )


GoogleCloudStorageCredential = Union[
    GoogleCloudStorageOAuthCredential,
    GoogleCloudStorageServiceAccountCredential,
]


# ============================================================================
# Bucket Operation Configs
# ============================================================================


class GCSListBucketsConfig(BaseModel):
    """List the buckets in a project."""

    operation: Literal["list_buckets"] = Field(
        "list_buckets",
        json_schema_extra={
            "const": "list_buckets",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "List Buckets",
        },
        title="List Buckets",
    )
    project_id: str = Field(
        ..., title="Project ID", description="The GCP project ID whose buckets to list"
    )
    prefix: Optional[str] = Field(
        None, title="Name Prefix", description="Only list buckets whose names start with this prefix"
    )
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of buckets to return per page"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="nextPageToken from a previous response for pagination"
    )


class GCSGetBucketConfig(BaseModel):
    """Get a bucket's metadata."""

    operation: Literal["get_bucket"] = Field(
        "get_bucket",
        json_schema_extra={
            "const": "get_bucket",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Get Bucket",
        },
        title="Get Bucket",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    project_id: Optional[str] = Field(
        None,
        title="Project ID",
        description="GCP project ID (used to populate the bucket dropdown)",
    )


class GCSCreateBucketConfig(BaseModel):
    """Create a new bucket in a project."""

    operation: Literal["create_bucket"] = Field(
        "create_bucket",
        json_schema_extra={
            "const": "create_bucket",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Create Bucket",
            "x-creates-resource": True,
            "x-resource-type": "google_cloud_storage_bucket",
            "x-resource-id-path": "data.name",
        },
        title="Create Bucket",
    )
    project_id: str = Field(
        ..., title="Project ID", description="The GCP project ID to create the bucket in"
    )
    name: str = Field(..., title="Bucket Name", description="Globally-unique name for the new bucket")
    location: Optional[str] = Field(
        "US", title="Location", description="Bucket location (e.g. US, EU, us-central1)"
    )
    storage_class: Optional[str] = Field(
        None,
        title="Storage Class",
        description="Default storage class for objects in the bucket",
        json_schema_extra={
            "enum": ["", "STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"],
            "enumNames": ["Default", "Standard", "Nearline", "Coldline", "Archive"],
            "x-enum-searchable": True,
        },
    )
    metadata_json: Optional[str] = Field(
        None,
        title="Additional Metadata (JSON)",
        description="Extra bucket resource fields as a JSON object (e.g. labels, lifecycle)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GCSUpdateBucketConfig(BaseModel):
    """Replace a bucket's metadata (full update)."""

    operation: Literal["update_bucket"] = Field(
        "update_bucket",
        json_schema_extra={
            "const": "update_bucket",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Update Bucket",
        },
        title="Update Bucket",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket to update")
    metadata_json: str = Field(
        ...,
        title="Bucket Metadata (JSON)",
        description="Full bucket resource as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GCSPatchBucketConfig(BaseModel):
    """Partially update a bucket's metadata (e.g. labels, lifecycle)."""

    operation: Literal["patch_bucket"] = Field(
        "patch_bucket",
        json_schema_extra={
            "const": "patch_bucket",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Patch Bucket",
        },
        title="Patch Bucket",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket to patch")
    metadata_json: str = Field(
        ...,
        title="Patch Metadata (JSON)",
        description="Partial bucket resource fields to update as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GCSDeleteBucketConfig(BaseModel):
    """Delete an empty bucket."""

    operation: Literal["delete_bucket"] = Field(
        "delete_bucket",
        json_schema_extra={
            "const": "delete_bucket",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Delete Bucket",
        },
        title="Delete Bucket",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the empty bucket to delete")


class GCSLockRetentionPolicyConfig(BaseModel):
    """Permanently lock a bucket's retention policy."""

    operation: Literal["lock_retention_policy"] = Field(
        "lock_retention_policy",
        json_schema_extra={
            "const": "lock_retention_policy",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Lock Retention Policy",
        },
        title="Lock Retention Policy",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    metageneration: str = Field(
        ...,
        title="Metageneration",
        description="Current metageneration of the bucket (precondition for the lock)",
    )


class GCSGetStorageLayoutConfig(BaseModel):
    """Return a bucket's storage layout and HNS status."""

    operation: Literal["get_storage_layout"] = Field(
        "get_storage_layout",
        json_schema_extra={
            "const": "get_storage_layout",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Get Storage Layout",
        },
        title="Get Storage Layout",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    prefix: Optional[str] = Field(
        None,
        title="Prefix",
        description="Optional prefix to scope the permission check for the request",
    )


class GCSRestoreBucketConfig(BaseModel):
    """Restore a soft-deleted bucket generation."""

    operation: Literal["restore_bucket"] = Field(
        "restore_bucket",
        json_schema_extra={
            "const": "restore_bucket",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Restore Bucket",
        },
        title="Restore Bucket",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the soft-deleted bucket")
    generation: str = Field(
        ...,
        title="Generation",
        description="Generation number of the soft-deleted bucket to restore",
    )


class GCSRelocateBucketConfig(BaseModel):
    """Start a dry-run or live bucket relocation operation."""

    operation: Literal["relocate_bucket"] = Field(
        "relocate_bucket",
        json_schema_extra={
            "const": "relocate_bucket",
            "ui:hidden": True,
            "x-category": "Buckets",
            "x-is-trigger": False,
            "x-display-name": "Relocate Bucket",
        },
        title="Relocate Bucket",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket to relocate")
    destination_location: str = Field(
        ...,
        title="Destination Location",
        description="Destination location for the relocation operation",
    )
    destination_data_locations: Optional[str] = Field(
        None,
        title="Destination Data Locations",
        description="Comma-separated locations for configurable dual-region relocation",
    )
    validate_only: Optional[bool] = Field(
        False,
        title="Dry Run Only",
        description="Start a relocation dry run instead of the live relocation step",
    )


# ============================================================================
# Bucket IAM Operation Configs
# ============================================================================


class GCSGetBucketIamConfig(BaseModel):
    """Read a bucket's IAM policy."""

    operation: Literal["get_bucket_iam"] = Field(
        "get_bucket_iam",
        json_schema_extra={
            "const": "get_bucket_iam",
            "ui:hidden": True,
            "x-category": "IAM",
            "x-is-trigger": False,
            "x-display-name": "Get Bucket IAM Policy",
        },
        title="Get Bucket IAM Policy",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")


class GCSSetBucketIamConfig(BaseModel):
    """Replace a bucket's IAM policy."""

    operation: Literal["set_bucket_iam"] = Field(
        "set_bucket_iam",
        json_schema_extra={
            "const": "set_bucket_iam",
            "ui:hidden": True,
            "x-category": "IAM",
            "x-is-trigger": False,
            "x-display-name": "Set Bucket IAM Policy",
        },
        title="Set Bucket IAM Policy",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    policy_json: str = Field(
        ...,
        title="IAM Policy (JSON)",
        description="The complete IAM policy resource as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GCSTestIamPermissionsConfig(BaseModel):
    """Check the caller's permissions on a bucket."""

    operation: Literal["test_iam_permissions"] = Field(
        "test_iam_permissions",
        json_schema_extra={
            "const": "test_iam_permissions",
            "ui:hidden": True,
            "x-category": "IAM",
            "x-is-trigger": False,
            "x-display-name": "Test IAM Permissions",
        },
        title="Test IAM Permissions",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    permissions: str = Field(
        ...,
        title="Permissions",
        description="Permissions to test, comma-separated (e.g. storage.buckets.get,storage.objects.list)",
    )


class GCSGetObjectIamConfig(BaseModel):
    """Read an object's IAM policy."""

    operation: Literal["get_object_iam"] = Field(
        "get_object_iam",
        json_schema_extra={
            "const": "get_object_iam",
            "ui:hidden": True,
            "x-category": "IAM",
            "x-is-trigger": False,
            "x-display-name": "Get Object IAM Policy",
        },
        title="Get Object IAM Policy",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Name of the object")


class GCSSetObjectIamConfig(BaseModel):
    """Replace an object's IAM policy."""

    operation: Literal["set_object_iam"] = Field(
        "set_object_iam",
        json_schema_extra={
            "const": "set_object_iam",
            "ui:hidden": True,
            "x-category": "IAM",
            "x-is-trigger": False,
            "x-display-name": "Set Object IAM Policy",
        },
        title="Set Object IAM Policy",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Name of the object")
    policy_json: str = Field(
        ...,
        title="IAM Policy (JSON)",
        description="The complete IAM policy resource as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GCSTestObjectIamPermissionsConfig(BaseModel):
    """Check the caller's permissions on an object."""

    operation: Literal["test_object_iam_permissions"] = Field(
        "test_object_iam_permissions",
        json_schema_extra={
            "const": "test_object_iam_permissions",
            "ui:hidden": True,
            "x-category": "IAM",
            "x-is-trigger": False,
            "x-display-name": "Test Object IAM Permissions",
        },
        title="Test Object IAM Permissions",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Name of the object")
    permissions: str = Field(
        ...,
        title="Permissions",
        description="Permissions to test, comma-separated (e.g. storage.objects.get,storage.objects.update)",
    )


# ============================================================================
# Object Operation Configs
# ============================================================================


class GCSListObjectsConfig(BaseModel):
    """List the objects in a bucket."""

    operation: Literal["list_objects"] = Field(
        "list_objects",
        json_schema_extra={
            "const": "list_objects",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "List Objects",
        },
        title="List Objects",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    project_id: Optional[str] = Field(
        None, title="Project ID", description="GCP project ID (used to populate the bucket dropdown)"
    )
    prefix: Optional[str] = Field(
        None, title="Prefix", description="Only list objects whose names start with this prefix"
    )
    delimiter: Optional[str] = Field(
        None, title="Delimiter", description="Returns folder-style prefixes when set (e.g. '/')"
    )
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of objects to return per page"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="nextPageToken from a previous response for pagination"
    )


class GCSGetObjectConfig(BaseModel):
    """Get an object's metadata."""

    operation: Literal["get_object"] = Field(
        "get_object",
        json_schema_extra={
            "const": "get_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Get Object Metadata",
        },
        title="Get Object Metadata",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(
        ..., title="Object Name", description="Full name (path) of the object"
    )


class GCSDownloadObjectConfig(BaseModel):
    """Download an object's bytes."""

    operation: Literal["download_object"] = Field(
        "download_object",
        json_schema_extra={
            "const": "download_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Download Object",
        },
        title="Download Object",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(
        ..., title="Object Name", description="Full name (path) of the object to download"
    )


class GCSUploadObjectConfig(BaseModel):
    """Upload a new object using simple, multipart, or resumable upload."""

    operation: Literal["upload_object"] = Field(
        "upload_object",
        json_schema_extra={
            "const": "upload_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Upload Object",
        },
        title="Upload Object",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the destination bucket")
    object_name: str = Field(
        ..., title="Object Name", description="Name to give the uploaded object (path)"
    )
    media_input: Optional[str] = Field(
        None,
        title="File / URL",
        description=(
            "Upload a local file, paste a public URL, or drag a workflow resource reference. "
            "If set, this is used instead of Content and Base64 Content."
        ),
        json_schema_extra={"ui:widget": "media_upload"},
    )
    content: Optional[str] = Field(
        None,
        title="Content",
        description="UTF-8 text content to upload as the object's bytes",
        json_schema_extra={"ui:widget": "textarea"},
    )
    content_base64: Optional[str] = Field(
        None,
        title="Base64 Content",
        description="Base64-encoded object bytes. If provided, this is used instead of Content.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    content_type: Optional[str] = Field(
        "text/plain",
        title="Content Type",
        description="MIME type of the content (e.g. text/plain, application/json)",
    )
    metadata_json: Optional[str] = Field(
        None,
        title="Object Metadata (JSON)",
        description="Optional object metadata. Required for multipart/resumable upload metadata.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    upload_type: Optional[str] = Field(
        "simple",
        title="Upload Type",
        description="JSON API upload mode",
        json_schema_extra={
            "enum": ["simple", "multipart", "resumable"],
            "enumNames": ["Simple", "Multipart", "Resumable"],
            "x-enum-searchable": True,
        },
    )


class GCSUpdateObjectConfig(BaseModel):
    """Replace an object's metadata (full update)."""

    operation: Literal["update_object"] = Field(
        "update_object",
        json_schema_extra={
            "const": "update_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Update Object Metadata",
        },
        title="Update Object Metadata",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")
    metadata_json: str = Field(
        ...,
        title="Object Metadata (JSON)",
        description="Full object resource as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GCSPatchObjectConfig(BaseModel):
    """Partially update an object's metadata (e.g. contentType, custom metadata)."""

    operation: Literal["patch_object"] = Field(
        "patch_object",
        json_schema_extra={
            "const": "patch_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Patch Object Metadata",
        },
        title="Patch Object Metadata",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")
    metadata_json: str = Field(
        ...,
        title="Patch Metadata (JSON)",
        description="Partial object resource fields to update as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GCSDeleteObjectConfig(BaseModel):
    """Delete an object (or a specific generation)."""

    operation: Literal["delete_object"] = Field(
        "delete_object",
        json_schema_extra={
            "const": "delete_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Delete Object",
        },
        title="Delete Object",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(
        ..., title="Object Name", description="Full name of the object to delete"
    )
    generation: Optional[str] = Field(
        None, title="Generation", description="Specific object generation to delete (optional)"
    )


class GCSCopyObjectConfig(BaseModel):
    """Copy an object to a new destination."""

    operation: Literal["copy_object"] = Field(
        "copy_object",
        json_schema_extra={
            "const": "copy_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Copy Object",
        },
        title="Copy Object",
    )
    source_bucket: str = Field(..., title="Source Bucket", description="Bucket of the source object")
    source_object: str = Field(..., title="Source Object", description="Name of the source object")
    destination_bucket: str = Field(
        ..., title="Destination Bucket", description="Bucket for the copied object"
    )
    destination_object: str = Field(
        ..., title="Destination Object", description="Name for the copied object"
    )


class GCSRewriteObjectConfig(BaseModel):
    """Rewrite/copy large objects (resumable via rewriteToken)."""

    operation: Literal["rewrite_object"] = Field(
        "rewrite_object",
        json_schema_extra={
            "const": "rewrite_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Rewrite Object",
        },
        title="Rewrite Object",
    )
    source_bucket: str = Field(..., title="Source Bucket", description="Bucket of the source object")
    source_object: str = Field(..., title="Source Object", description="Name of the source object")
    destination_bucket: str = Field(
        ..., title="Destination Bucket", description="Bucket for the rewritten object"
    )
    destination_object: str = Field(
        ..., title="Destination Object", description="Name for the rewritten object"
    )
    rewrite_token: Optional[str] = Field(
        None, title="Rewrite Token", description="Token from a previous rewrite response to resume"
    )


class GCSComposeObjectsConfig(BaseModel):
    """Concatenate up to 32 source objects into one destination object."""

    operation: Literal["compose_objects"] = Field(
        "compose_objects",
        json_schema_extra={
            "const": "compose_objects",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Compose Objects",
        },
        title="Compose Objects",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    destination_object: str = Field(
        ..., title="Destination Object", description="Name of the composed result object"
    )
    source_objects: str = Field(
        ...,
        title="Source Objects",
        description="Names of source objects to concatenate, comma-separated (max 32)",
    )


class GCSMoveObjectConfig(BaseModel):
    """Rename/move an object within a bucket (HNS-enabled buckets)."""

    operation: Literal["move_object"] = Field(
        "move_object",
        json_schema_extra={
            "const": "move_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Move Object",
        },
        title="Move Object",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    source_object: str = Field(..., title="Source Object", description="Current object name")
    destination_object: str = Field(
        ..., title="Destination Object", description="New object name"
    )


class GCSRestoreObjectConfig(BaseModel):
    """Restore a soft-deleted object generation."""

    operation: Literal["restore_object"] = Field(
        "restore_object",
        json_schema_extra={
            "const": "restore_object",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Restore Object",
        },
        title="Restore Object",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Name of the object to restore")
    generation: str = Field(
        ..., title="Generation", description="Generation of the soft-deleted object to restore"
    )


class GCSGetObjectAclConfig(BaseModel):
    """List the access-control entries for an object."""

    operation: Literal["get_object_acl"] = Field(
        "get_object_acl",
        json_schema_extra={
            "const": "get_object_acl",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Get Object ACL",
        },
        title="Get Object ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")


class GCSBulkRestoreObjectsConfig(BaseModel):
    """Start a long-running bulk restore for soft-deleted objects in a bucket."""

    operation: Literal["bulk_restore_objects"] = Field(
        "bulk_restore_objects",
        json_schema_extra={
            "const": "bulk_restore_objects",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Bulk Restore Objects",
        },
        title="Bulk Restore Objects",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    allow_overwrite: Optional[bool] = Field(
        False,
        title="Allow Overwrite",
        description="Allow restored objects to overwrite live objects with the same name",
    )
    copy_source_acl: Optional[bool] = Field(
        False,
        title="Copy Source ACL",
        description="Copy source ACLs to restored objects when uniform access is disabled",
    )
    deleted_after_time: Optional[str] = Field(
        None,
        title="Deleted After Time",
        description="Only restore objects soft-deleted after this RFC3339 timestamp",
    )
    deleted_before_time: Optional[str] = Field(
        None,
        title="Deleted Before Time",
        description="Only restore objects soft-deleted before this RFC3339 timestamp",
    )
    match_glob: Optional[str] = Field(
        None,
        title="Match Glob",
        description="Optional glob pattern for object names to restore",
    )


# ============================================================================
# Notification Operation Configs
# ============================================================================


class GCSCreateNotificationConfig(BaseModel):
    """Create a Pub/Sub notification config for bucket events."""

    operation: Literal["create_notification"] = Field(
        "create_notification",
        json_schema_extra={
            "const": "create_notification",
            "ui:hidden": True,
            "x-category": "Notifications",
            "x-is-trigger": False,
            "x-display-name": "Create Notification Config",
        },
        title="Create Notification Config",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    topic: str = Field(
        ...,
        title="Pub/Sub Topic",
        description="Full Pub/Sub topic (e.g. //pubsub.googleapis.com/projects/PROJECT/topics/TOPIC)",
    )
    payload_format: Optional[str] = Field(
        "JSON_API_V1",
        title="Payload Format",
        description="Notification payload format",
        json_schema_extra={
            "enum": ["JSON_API_V1", "NONE"],
            "enumNames": ["JSON API v1", "None"],
            "x-enum-searchable": True,
        },
    )
    event_types: Optional[str] = Field(
        None,
        title="Event Types",
        description="Events to notify on, comma-separated (e.g. OBJECT_FINALIZE,OBJECT_DELETE). Empty = all",
    )


class GCSListNotificationsConfig(BaseModel):
    """List a bucket's Pub/Sub notification configs."""

    operation: Literal["list_notifications"] = Field(
        "list_notifications",
        json_schema_extra={
            "const": "list_notifications",
            "ui:hidden": True,
            "x-category": "Notifications",
            "x-is-trigger": False,
            "x-display-name": "List Notification Configs",
        },
        title="List Notification Configs",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")


class GCSGetNotificationConfig(BaseModel):
    """Get a notification config by ID."""

    operation: Literal["get_notification"] = Field(
        "get_notification",
        json_schema_extra={
            "const": "get_notification",
            "ui:hidden": True,
            "x-category": "Notifications",
            "x-is-trigger": False,
            "x-display-name": "Get Notification Config",
        },
        title="Get Notification Config",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    notification_id: str = Field(
        ..., title="Notification ID", description="ID of the notification config"
    )


class GCSDeleteNotificationConfig(BaseModel):
    """Delete a notification config."""

    operation: Literal["delete_notification"] = Field(
        "delete_notification",
        json_schema_extra={
            "const": "delete_notification",
            "ui:hidden": True,
            "x-category": "Notifications",
            "x-is-trigger": False,
            "x-display-name": "Delete Notification Config",
        },
        title="Delete Notification Config",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    notification_id: str = Field(
        ..., title="Notification ID", description="ID of the notification config to delete"
    )


# ============================================================================
# Project Operation Configs
# ============================================================================


class GCSCreateHmacKeyConfig(BaseModel):
    """Create an HMAC key for a service account."""

    operation: Literal["create_hmac_key"] = Field(
        "create_hmac_key",
        json_schema_extra={
            "const": "create_hmac_key",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create HMAC Key",
        },
        title="Create HMAC Key",
    )
    project_id: str = Field(..., title="Project ID", description="The GCP project ID")
    service_account_email: str = Field(
        ...,
        title="Service Account Email",
        description="Email of the service account the HMAC key belongs to",
    )


class GCSListHmacKeysConfig(BaseModel):
    """List a project's HMAC keys."""

    operation: Literal["list_hmac_keys"] = Field(
        "list_hmac_keys",
        json_schema_extra={
            "const": "list_hmac_keys",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "List HMAC Keys",
        },
        title="List HMAC Keys",
    )
    project_id: str = Field(..., title="Project ID", description="The GCP project ID")
    service_account_email: Optional[str] = Field(
        None, title="Service Account Email", description="Filter keys to this service account (optional)"
    )


class GCSGetHmacKeyConfig(BaseModel):
    """Get HMAC key metadata."""

    operation: Literal["get_hmac_key"] = Field(
        "get_hmac_key",
        json_schema_extra={
            "const": "get_hmac_key",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get HMAC Key",
        },
        title="Get HMAC Key",
    )
    project_id: str = Field(..., title="Project ID", description="The GCP project ID")
    access_id: str = Field(..., title="Access ID", description="Access ID of the HMAC key")


class GCSUpdateHmacKeyConfig(BaseModel):
    """Update an HMAC key's state."""

    operation: Literal["update_hmac_key"] = Field(
        "update_hmac_key",
        json_schema_extra={
            "const": "update_hmac_key",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Update HMAC Key",
        },
        title="Update HMAC Key",
    )
    project_id: str = Field(..., title="Project ID", description="The GCP project ID")
    access_id: str = Field(..., title="Access ID", description="Access ID of the HMAC key")
    state: Literal["ACTIVE", "INACTIVE"] = Field(
        ...,
        title="State",
        description="New state for the HMAC key",
    )


class GCSDeleteHmacKeyConfig(BaseModel):
    """Delete an HMAC key."""

    operation: Literal["delete_hmac_key"] = Field(
        "delete_hmac_key",
        json_schema_extra={
            "const": "delete_hmac_key",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Delete HMAC Key",
        },
        title="Delete HMAC Key",
    )
    project_id: str = Field(..., title="Project ID", description="The GCP project ID")
    access_id: str = Field(..., title="Access ID", description="Access ID of the HMAC key")


class GCSGetServiceAccountConfig(BaseModel):
    """Get the project's Cloud Storage service account email."""

    operation: Literal["get_service_account"] = Field(
        "get_service_account",
        json_schema_extra={
            "const": "get_service_account",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Service Account",
        },
        title="Get Service Account",
    )
    project_id: str = Field(..., title="Project ID", description="The GCP project ID")


class GCSGetOperationConfig(BaseModel):
    """Get a long-running bucket operation."""

    operation: Literal["get_operation"] = Field(
        "get_operation",
        json_schema_extra={
            "const": "get_operation",
            "ui:hidden": True,
            "x-category": "Operations",
            "x-is-trigger": False,
            "x-display-name": "Get Operation",
        },
        title="Get Operation",
    )
    bucket: str = Field(..., title="Bucket", description="Bucket associated with the operation")
    operation_id: str = Field(..., title="Operation ID", description="Long-running operation ID")


class GCSListOperationsConfig(BaseModel):
    """List long-running bucket operations."""

    operation: Literal["list_operations"] = Field(
        "list_operations",
        json_schema_extra={
            "const": "list_operations",
            "ui:hidden": True,
            "x-category": "Operations",
            "x-is-trigger": False,
            "x-display-name": "List Operations",
        },
        title="List Operations",
    )
    bucket: str = Field(..., title="Bucket", description="Bucket whose operations to list")
    page_token: Optional[str] = Field(
        None,
        title="Page Token",
        description="nextPageToken from a previous response for pagination",
    )
    max_results: Optional[str] = Field(
        None,
        title="Max Results",
        description="Maximum number of operations to return per page",
    )


class GCSCancelOperationConfig(BaseModel):
    """Cancel a long-running bucket operation."""

    operation: Literal["cancel_operation"] = Field(
        "cancel_operation",
        json_schema_extra={
            "const": "cancel_operation",
            "ui:hidden": True,
            "x-category": "Operations",
            "x-is-trigger": False,
            "x-display-name": "Cancel Operation",
        },
        title="Cancel Operation",
    )
    bucket: str = Field(..., title="Bucket", description="Bucket associated with the operation")
    operation_id: str = Field(..., title="Operation ID", description="Long-running operation ID")


class GCSAdvanceRelocateBucketConfig(BaseModel):
    """Advance a relocation operation to final synchronization."""

    operation: Literal["advance_relocate_bucket"] = Field(
        "advance_relocate_bucket",
        json_schema_extra={
            "const": "advance_relocate_bucket",
            "ui:hidden": True,
            "x-category": "Operations",
            "x-is-trigger": False,
            "x-display-name": "Advance Relocate Bucket",
        },
        title="Advance Relocate Bucket",
    )
    bucket: str = Field(..., title="Bucket", description="Bucket associated with the relocation")
    operation_id: str = Field(..., title="Operation ID", description="Relocation operation ID")


# ============================================================================
# ACL / Folder / Cache Operation Configs
# ============================================================================


class GCSListBucketAclConfig(BaseModel):
    """List ACL entries on a bucket."""

    operation: Literal["list_bucket_acl"] = Field(
        "list_bucket_acl",
        json_schema_extra={
            "const": "list_bucket_acl",
            "ui:hidden": True,
            "x-category": "Bucket ACLs",
            "x-is-trigger": False,
            "x-display-name": "List Bucket ACLs",
        },
        title="List Bucket ACLs",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")


class GCSGetBucketAclConfig(BaseModel):
    """Get a single bucket ACL entry."""

    operation: Literal["get_bucket_acl"] = Field(
        "get_bucket_acl",
        json_schema_extra={
            "const": "get_bucket_acl",
            "ui:hidden": True,
            "x-category": "Bucket ACLs",
            "x-is-trigger": False,
            "x-display-name": "Get Bucket ACL",
        },
        title="Get Bucket ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity, such as user-name@example.com")


class GCSCreateBucketAclConfig(BaseModel):
    """Create a bucket ACL entry."""

    operation: Literal["create_bucket_acl"] = Field(
        "create_bucket_acl",
        json_schema_extra={
            "const": "create_bucket_acl",
            "ui:hidden": True,
            "x-category": "Bucket ACLs",
            "x-is-trigger": False,
            "x-display-name": "Create Bucket ACL",
        },
        title="Create Bucket ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to grant access to")
    role: str = Field(..., title="Role", description="ACL role, such as READER, WRITER, or OWNER")


class GCSPatchBucketAclConfig(BaseModel):
    """Patch a bucket ACL entry."""

    operation: Literal["patch_bucket_acl"] = Field(
        "patch_bucket_acl",
        json_schema_extra={
            "const": "patch_bucket_acl",
            "ui:hidden": True,
            "x-category": "Bucket ACLs",
            "x-is-trigger": False,
            "x-display-name": "Patch Bucket ACL",
        },
        title="Patch Bucket ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to patch")
    role: str = Field(..., title="Role", description="Updated ACL role")


class GCSUpdateBucketAclConfig(BaseModel):
    """Replace a bucket ACL entry."""

    operation: Literal["update_bucket_acl"] = Field(
        "update_bucket_acl",
        json_schema_extra={
            "const": "update_bucket_acl",
            "ui:hidden": True,
            "x-category": "Bucket ACLs",
            "x-is-trigger": False,
            "x-display-name": "Update Bucket ACL",
        },
        title="Update Bucket ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to update")
    role: str = Field(..., title="Role", description="ACL role to set")


class GCSDeleteBucketAclConfig(BaseModel):
    """Delete a bucket ACL entry."""

    operation: Literal["delete_bucket_acl"] = Field(
        "delete_bucket_acl",
        json_schema_extra={
            "const": "delete_bucket_acl",
            "ui:hidden": True,
            "x-category": "Bucket ACLs",
            "x-is-trigger": False,
            "x-display-name": "Delete Bucket ACL",
        },
        title="Delete Bucket ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to remove")


class GCSListDefaultObjectAclConfig(BaseModel):
    """List default object ACL entries on a bucket."""

    operation: Literal["list_default_object_acl"] = Field(
        "list_default_object_acl",
        json_schema_extra={
            "const": "list_default_object_acl",
            "ui:hidden": True,
            "x-category": "Default Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "List Default Object ACLs",
        },
        title="List Default Object ACLs",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")


class GCSGetDefaultObjectAclConfig(BaseModel):
    """Get a single default object ACL entry."""

    operation: Literal["get_default_object_acl"] = Field(
        "get_default_object_acl",
        json_schema_extra={
            "const": "get_default_object_acl",
            "ui:hidden": True,
            "x-category": "Default Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Get Default Object ACL",
        },
        title="Get Default Object ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to retrieve")


class GCSCreateDefaultObjectAclConfig(BaseModel):
    """Create a default object ACL entry."""

    operation: Literal["create_default_object_acl"] = Field(
        "create_default_object_acl",
        json_schema_extra={
            "const": "create_default_object_acl",
            "ui:hidden": True,
            "x-category": "Default Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Create Default Object ACL",
        },
        title="Create Default Object ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to grant access to")
    role: str = Field(..., title="Role", description="ACL role to assign")


class GCSPatchDefaultObjectAclConfig(BaseModel):
    """Patch a default object ACL entry."""

    operation: Literal["patch_default_object_acl"] = Field(
        "patch_default_object_acl",
        json_schema_extra={
            "const": "patch_default_object_acl",
            "ui:hidden": True,
            "x-category": "Default Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Patch Default Object ACL",
        },
        title="Patch Default Object ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to patch")
    role: str = Field(..., title="Role", description="Updated ACL role")


class GCSUpdateDefaultObjectAclConfig(BaseModel):
    """Replace a default object ACL entry."""

    operation: Literal["update_default_object_acl"] = Field(
        "update_default_object_acl",
        json_schema_extra={
            "const": "update_default_object_acl",
            "ui:hidden": True,
            "x-category": "Default Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Update Default Object ACL",
        },
        title="Update Default Object ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to update")
    role: str = Field(..., title="Role", description="ACL role to set")


class GCSDeleteDefaultObjectAclConfig(BaseModel):
    """Delete a default object ACL entry."""

    operation: Literal["delete_default_object_acl"] = Field(
        "delete_default_object_acl",
        json_schema_extra={
            "const": "delete_default_object_acl",
            "ui:hidden": True,
            "x-category": "Default Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Delete Default Object ACL",
        },
        title="Delete Default Object ACL",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    entity: str = Field(..., title="Entity", description="ACL entity to remove")


class GCSListObjectAclEntriesConfig(BaseModel):
    """List ACL entries on an object."""

    operation: Literal["list_object_acl_entries"] = Field(
        "list_object_acl_entries",
        json_schema_extra={
            "const": "list_object_acl_entries",
            "ui:hidden": True,
            "x-category": "Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "List Object ACLs",
        },
        title="List Object ACLs",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")
    generation: Optional[str] = Field(
        None, title="Generation", description="Optional object generation to query"
    )


class GCSGetObjectAclEntryConfig(BaseModel):
    """Get a single object ACL entry."""

    operation: Literal["get_object_acl_entry"] = Field(
        "get_object_acl_entry",
        json_schema_extra={
            "const": "get_object_acl_entry",
            "ui:hidden": True,
            "x-category": "Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Get Object ACL Entry",
        },
        title="Get Object ACL Entry",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")
    entity: str = Field(..., title="Entity", description="ACL entity to retrieve")
    generation: Optional[str] = Field(
        None, title="Generation", description="Optional object generation to query"
    )


class GCSCreateObjectAclEntryConfig(BaseModel):
    """Create an object ACL entry."""

    operation: Literal["create_object_acl_entry"] = Field(
        "create_object_acl_entry",
        json_schema_extra={
            "const": "create_object_acl_entry",
            "ui:hidden": True,
            "x-category": "Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Create Object ACL Entry",
        },
        title="Create Object ACL Entry",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")
    entity: str = Field(..., title="Entity", description="ACL entity to grant access to")
    role: str = Field(..., title="Role", description="ACL role to assign")
    generation: Optional[str] = Field(
        None, title="Generation", description="Optional object generation to update"
    )


class GCSPatchObjectAclEntryConfig(BaseModel):
    """Patch an object ACL entry."""

    operation: Literal["patch_object_acl_entry"] = Field(
        "patch_object_acl_entry",
        json_schema_extra={
            "const": "patch_object_acl_entry",
            "ui:hidden": True,
            "x-category": "Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Patch Object ACL Entry",
        },
        title="Patch Object ACL Entry",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")
    entity: str = Field(..., title="Entity", description="ACL entity to patch")
    role: str = Field(..., title="Role", description="Updated ACL role")
    generation: Optional[str] = Field(
        None, title="Generation", description="Optional object generation to update"
    )


class GCSUpdateObjectAclEntryConfig(BaseModel):
    """Replace an object ACL entry."""

    operation: Literal["update_object_acl_entry"] = Field(
        "update_object_acl_entry",
        json_schema_extra={
            "const": "update_object_acl_entry",
            "ui:hidden": True,
            "x-category": "Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Update Object ACL Entry",
        },
        title="Update Object ACL Entry",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")
    entity: str = Field(..., title="Entity", description="ACL entity to update")
    role: str = Field(..., title="Role", description="ACL role to set")
    generation: Optional[str] = Field(
        None, title="Generation", description="Optional object generation to update"
    )


class GCSDeleteObjectAclEntryConfig(BaseModel):
    """Delete an object ACL entry."""

    operation: Literal["delete_object_acl_entry"] = Field(
        "delete_object_acl_entry",
        json_schema_extra={
            "const": "delete_object_acl_entry",
            "ui:hidden": True,
            "x-category": "Object ACLs",
            "x-is-trigger": False,
            "x-display-name": "Delete Object ACL Entry",
        },
        title="Delete Object ACL Entry",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    object_name: str = Field(..., title="Object Name", description="Full name of the object")
    entity: str = Field(..., title="Entity", description="ACL entity to remove")
    generation: Optional[str] = Field(
        None, title="Generation", description="Optional object generation to update"
    )


class GCSListFoldersConfig(BaseModel):
    """List folders in an HNS-enabled bucket."""

    operation: Literal["list_folders"] = Field(
        "list_folders",
        json_schema_extra={
            "const": "list_folders",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "List Folders",
        },
        title="List Folders",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    prefix: Optional[str] = Field(None, title="Prefix", description="Optional folder prefix filter")
    delimiter: Optional[str] = Field(
        None, title="Delimiter", description="Use / for one-level directory-style listing"
    )
    start_offset: Optional[str] = Field(
        None, title="Start Offset", description="Lower lexicographic bound for folder names"
    )
    end_offset: Optional[str] = Field(
        None, title="End Offset", description="Upper lexicographic bound for folder names"
    )
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of folders to return per page"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Continuation token from a previous response"
    )


class GCSGetFolderConfig(BaseModel):
    """Get folder metadata from an HNS-enabled bucket."""

    operation: Literal["get_folder"] = Field(
        "get_folder",
        json_schema_extra={
            "const": "get_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Get Folder",
        },
        title="Get Folder",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    folder_name: str = Field(
        ...,
        title="Folder Name",
        description="Folder path to retrieve",
        json_schema_extra=_folder_dynamic_options("folder_name"),
    )


class GCSCreateFolderConfig(BaseModel):
    """Create a folder in an HNS-enabled bucket."""

    operation: Literal["create_folder"] = Field(
        "create_folder",
        json_schema_extra={
            "const": "create_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Create Folder",
            "x-creates-resource": True,
            "x-resource-type": "google_cloud_storage_folder",
            "x-resource-id-path": "data.name",
        },
        title="Create Folder",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    folder_name: str = Field(..., title="Folder Name", description="Folder path to create")
    recursive: Optional[bool] = Field(
        False,
        title="Create Parents",
        description="Create missing parent folders automatically",
    )


class GCSRenameFolderConfig(BaseModel):
    """Rename a folder in an HNS-enabled bucket."""

    operation: Literal["rename_folder"] = Field(
        "rename_folder",
        json_schema_extra={
            "const": "rename_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Rename Folder",
        },
        title="Rename Folder",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    source_folder_name: str = Field(
        ..., title="Source Folder Name", description="Existing folder path to rename"
    )
    destination_folder_name: str = Field(
        ..., title="Destination Folder Name", description="New folder path"
    )


class GCSDeleteFolderConfig(BaseModel):
    """Delete an empty folder from an HNS-enabled bucket."""

    operation: Literal["delete_folder"] = Field(
        "delete_folder",
        json_schema_extra={
            "const": "delete_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Delete Folder",
        },
        title="Delete Folder",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    folder_name: str = Field(
        ...,
        title="Folder Name",
        description="Folder path to delete",
        json_schema_extra=_folder_dynamic_options("folder_name"),
    )


class GCSDeleteFolderRecursiveConfig(BaseModel):
    """Delete a folder and all descendants from an HNS-enabled bucket."""

    operation: Literal["delete_folder_recursive"] = Field(
        "delete_folder_recursive",
        json_schema_extra={
            "const": "delete_folder_recursive",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Delete Folder Recursively",
        },
        title="Delete Folder Recursively",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    folder_name: str = Field(
        ...,
        title="Folder Name",
        description="Folder path to delete recursively",
        json_schema_extra=_folder_dynamic_options("folder_name"),
    )
    if_metageneration_match: Optional[str] = Field(
        None,
        title="If Metageneration Match",
        description="Only delete if the folder metageneration matches this value",
    )
    if_metageneration_not_match: Optional[str] = Field(
        None,
        title="If Metageneration Not Match",
        description="Only delete if the folder metageneration does not match this value",
    )


class GCSListManagedFoldersConfig(BaseModel):
    """List managed folders in a bucket."""

    operation: Literal["list_managed_folders"] = Field(
        "list_managed_folders",
        json_schema_extra={
            "const": "list_managed_folders",
            "ui:hidden": True,
            "x-category": "Managed Folders",
            "x-is-trigger": False,
            "x-display-name": "List Managed Folders",
        },
        title="List Managed Folders",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    prefix: Optional[str] = Field(None, title="Prefix", description="Optional managed folder prefix filter")
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of managed folders to return"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Continuation token from a previous response"
    )


class GCSGetManagedFolderConfig(BaseModel):
    """Get a managed folder."""

    operation: Literal["get_managed_folder"] = Field(
        "get_managed_folder",
        json_schema_extra={
            "const": "get_managed_folder",
            "ui:hidden": True,
            "x-category": "Managed Folders",
            "x-is-trigger": False,
            "x-display-name": "Get Managed Folder",
        },
        title="Get Managed Folder",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    managed_folder: str = Field(
        ...,
        title="Managed Folder Name",
        description="Managed folder path to retrieve",
        json_schema_extra=_managed_folder_dynamic_options("managed_folder"),
    )


class GCSCreateManagedFolderConfig(BaseModel):
    """Create a managed folder."""

    operation: Literal["create_managed_folder"] = Field(
        "create_managed_folder",
        json_schema_extra={
            "const": "create_managed_folder",
            "ui:hidden": True,
            "x-category": "Managed Folders",
            "x-is-trigger": False,
            "x-display-name": "Create Managed Folder",
            "x-creates-resource": True,
            "x-resource-type": "google_cloud_storage_managed_folder",
            "x-resource-id-path": "data.name",
        },
        title="Create Managed Folder",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    managed_folder: str = Field(
        ..., title="Managed Folder Name", description="Managed folder path to create"
    )


class GCSDeleteManagedFolderConfig(BaseModel):
    """Delete a managed folder."""

    operation: Literal["delete_managed_folder"] = Field(
        "delete_managed_folder",
        json_schema_extra={
            "const": "delete_managed_folder",
            "ui:hidden": True,
            "x-category": "Managed Folders",
            "x-is-trigger": False,
            "x-display-name": "Delete Managed Folder",
        },
        title="Delete Managed Folder",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    managed_folder: str = Field(
        ...,
        title="Managed Folder Name",
        description="Managed folder path to delete",
        json_schema_extra=_managed_folder_dynamic_options("managed_folder"),
    )
    allow_non_empty: Optional[bool] = Field(
        False,
        title="Allow Non-Empty Delete",
        description="Allow deleting a non-empty managed folder",
    )


class GCSGetManagedFolderIamConfig(BaseModel):
    """Get the IAM policy for a managed folder."""

    operation: Literal["get_managed_folder_iam"] = Field(
        "get_managed_folder_iam",
        json_schema_extra={
            "const": "get_managed_folder_iam",
            "ui:hidden": True,
            "x-category": "Managed Folders",
            "x-is-trigger": False,
            "x-display-name": "Get Managed Folder IAM Policy",
        },
        title="Get Managed Folder IAM Policy",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    managed_folder: str = Field(
        ...,
        title="Managed Folder Name",
        description="Managed folder path to inspect",
        json_schema_extra=_managed_folder_dynamic_options("managed_folder"),
    )
    requested_policy_version: Optional[int] = Field(
        None,
        title="Requested Policy Version",
        description="Optional IAM policy version to request",
    )


class GCSSetManagedFolderIamConfig(BaseModel):
    """Set the IAM policy for a managed folder."""

    operation: Literal["set_managed_folder_iam"] = Field(
        "set_managed_folder_iam",
        json_schema_extra={
            "const": "set_managed_folder_iam",
            "ui:hidden": True,
            "x-category": "Managed Folders",
            "x-is-trigger": False,
            "x-display-name": "Set Managed Folder IAM Policy",
        },
        title="Set Managed Folder IAM Policy",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    managed_folder: str = Field(
        ...,
        title="Managed Folder Name",
        description="Managed folder path to update",
        json_schema_extra=_managed_folder_dynamic_options("managed_folder"),
    )
    policy_json: str = Field(
        ...,
        title="IAM Policy (JSON)",
        description="Complete IAM policy resource as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GCSTestManagedFolderIamPermissionsConfig(BaseModel):
    """Test caller permissions on a managed folder."""

    operation: Literal["test_managed_folder_iam_permissions"] = Field(
        "test_managed_folder_iam_permissions",
        json_schema_extra={
            "const": "test_managed_folder_iam_permissions",
            "ui:hidden": True,
            "x-category": "Managed Folders",
            "x-is-trigger": False,
            "x-display-name": "Test Managed Folder IAM Permissions",
        },
        title="Test Managed Folder IAM Permissions",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Name of the bucket",
        json_schema_extra=_bucket_dynamic_options("bucket"),
    )
    managed_folder: str = Field(
        ...,
        title="Managed Folder Name",
        description="Managed folder path to test",
        json_schema_extra=_managed_folder_dynamic_options("managed_folder"),
    )
    permissions: str = Field(
        ...,
        title="Permissions",
        description="Permissions to test, comma-separated",
    )


class GCSListAnywhereCachesConfig(BaseModel):
    """List Rapid Cache instances for a bucket."""

    operation: Literal["list_anywhere_caches"] = Field(
        "list_anywhere_caches",
        json_schema_extra={
            "const": "list_anywhere_caches",
            "ui:hidden": True,
            "x-category": "Anywhere Cache",
            "x-is-trigger": False,
            "x-display-name": "List Anywhere Caches",
        },
        title="List Anywhere Caches",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")


class GCSGetAnywhereCacheConfig(BaseModel):
    """Get a Rapid Cache instance."""

    operation: Literal["get_anywhere_cache"] = Field(
        "get_anywhere_cache",
        json_schema_extra={
            "const": "get_anywhere_cache",
            "ui:hidden": True,
            "x-category": "Anywhere Cache",
            "x-is-trigger": False,
            "x-display-name": "Get Anywhere Cache",
        },
        title="Get Anywhere Cache",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    anywhere_cache_id: str = Field(
        ..., title="Anywhere Cache ID", description="Cache identifier, typically a zone ID"
    )


class GCSCreateAnywhereCacheConfig(BaseModel):
    """Create a Rapid Cache instance."""

    operation: Literal["create_anywhere_cache"] = Field(
        "create_anywhere_cache",
        json_schema_extra={
            "const": "create_anywhere_cache",
            "ui:hidden": True,
            "x-category": "Anywhere Cache",
            "x-is-trigger": False,
            "x-display-name": "Create Anywhere Cache",
        },
        title="Create Anywhere Cache",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    zone: str = Field(..., title="Zone", description="Zone where the cache should run")
    ttl: Optional[str] = Field(
        None, title="TTL", description="Cache TTL, such as 86400s"
    )
    ingest_on_write: Optional[bool] = Field(
        None,
        title="Ingest On Write",
        description="Ingest object data into the cache when written",
    )


class GCSUpdateAnywhereCacheConfig(BaseModel):
    """Update a Rapid Cache instance."""

    operation: Literal["update_anywhere_cache"] = Field(
        "update_anywhere_cache",
        json_schema_extra={
            "const": "update_anywhere_cache",
            "ui:hidden": True,
            "x-category": "Anywhere Cache",
            "x-is-trigger": False,
            "x-display-name": "Update Anywhere Cache",
        },
        title="Update Anywhere Cache",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    anywhere_cache_id: str = Field(
        ..., title="Anywhere Cache ID", description="Cache identifier to update"
    )
    ttl: str = Field(..., title="TTL", description="New cache TTL, such as 86400s")
    ingest_on_write: bool = Field(
        ..., title="Ingest On Write", description="Whether the cache ingests new writes"
    )


class GCSDisableAnywhereCacheConfig(BaseModel):
    """Disable a Rapid Cache instance."""

    operation: Literal["disable_anywhere_cache"] = Field(
        "disable_anywhere_cache",
        json_schema_extra={
            "const": "disable_anywhere_cache",
            "ui:hidden": True,
            "x-category": "Anywhere Cache",
            "x-is-trigger": False,
            "x-display-name": "Disable Anywhere Cache",
        },
        title="Disable Anywhere Cache",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    anywhere_cache_id: str = Field(
        ..., title="Anywhere Cache ID", description="Cache identifier to disable"
    )


class GCSPauseAnywhereCacheConfig(BaseModel):
    """Pause an Anywhere Cache instance."""

    operation: Literal["pause_anywhere_cache"] = Field(
        "pause_anywhere_cache",
        json_schema_extra={
            "const": "pause_anywhere_cache",
            "ui:hidden": True,
            "x-category": "Anywhere Cache",
            "x-is-trigger": False,
            "x-display-name": "Pause Anywhere Cache",
        },
        title="Pause Anywhere Cache",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    anywhere_cache_id: str = Field(
        ..., title="Anywhere Cache ID", description="Cache identifier to pause"
    )


class GCSResumeAnywhereCacheConfig(BaseModel):
    """Resume a Rapid Cache instance."""

    operation: Literal["resume_anywhere_cache"] = Field(
        "resume_anywhere_cache",
        json_schema_extra={
            "const": "resume_anywhere_cache",
            "ui:hidden": True,
            "x-category": "Anywhere Cache",
            "x-is-trigger": False,
            "x-display-name": "Resume Anywhere Cache",
        },
        title="Resume Anywhere Cache",
    )
    bucket: str = Field(..., title="Bucket", description="Name of the bucket")
    anywhere_cache_id: str = Field(
        ..., title="Anywhere Cache ID", description="Cache identifier to resume"
    )


class GCSGetProjectIntelligenceConfig(BaseModel):
    """Get the Storage Intelligence config for a project."""

    operation: Literal["get_project_intelligence_config"] = Field(
        "get_project_intelligence_config",
        json_schema_extra={
            "const": "get_project_intelligence_config",
            "ui:hidden": True,
            "x-category": "Storage Intelligence",
            "x-is-trigger": False,
            "x-display-name": "Get Project Intelligence Config",
        },
        title="Get Project Intelligence Config",
    )
    project_id: str = Field(..., title="Project ID", description="Google Cloud project ID")


class GCSUpdateProjectIntelligenceConfig(BaseModel):
    """Update the Storage Intelligence config for a project."""

    operation: Literal["update_project_intelligence_config"] = Field(
        "update_project_intelligence_config",
        json_schema_extra={
            "const": "update_project_intelligence_config",
            "ui:hidden": True,
            "x-category": "Storage Intelligence",
            "x-is-trigger": False,
            "x-display-name": "Update Project Intelligence Config",
        },
        title="Update Project Intelligence Config",
    )
    project_id: str = Field(..., title="Project ID", description="Google Cloud project ID")
    intelligence_config_json: str = Field(
        ...,
        title="Intelligence Config (JSON)",
        description="The IntelligenceConfig resource as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )
    update_mask: str = Field(
        ...,
        title="Update Mask",
        description="Comma-separated field mask of IntelligenceConfig fields to update",
    )
    request_id: Optional[str] = Field(
        None,
        title="Request ID",
        description="Optional idempotency token for the update request",
    )


class GCSGetFolderIntelligenceConfig(BaseModel):
    """Get the Storage Intelligence config for a folder."""

    operation: Literal["get_folder_intelligence_config"] = Field(
        "get_folder_intelligence_config",
        json_schema_extra={
            "const": "get_folder_intelligence_config",
            "ui:hidden": True,
            "x-category": "Storage Intelligence",
            "x-is-trigger": False,
            "x-display-name": "Get Folder Intelligence Config",
        },
        title="Get Folder Intelligence Config",
    )
    folder_id: str = Field(..., title="Folder ID", description="Google Cloud folder ID")


class GCSUpdateFolderIntelligenceConfig(BaseModel):
    """Update the Storage Intelligence config for a folder."""

    operation: Literal["update_folder_intelligence_config"] = Field(
        "update_folder_intelligence_config",
        json_schema_extra={
            "const": "update_folder_intelligence_config",
            "ui:hidden": True,
            "x-category": "Storage Intelligence",
            "x-is-trigger": False,
            "x-display-name": "Update Folder Intelligence Config",
        },
        title="Update Folder Intelligence Config",
    )
    folder_id: str = Field(..., title="Folder ID", description="Google Cloud folder ID")
    intelligence_config_json: str = Field(
        ...,
        title="Intelligence Config (JSON)",
        description="The IntelligenceConfig resource as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )
    update_mask: str = Field(
        ...,
        title="Update Mask",
        description="Comma-separated field mask of IntelligenceConfig fields to update",
    )
    request_id: Optional[str] = Field(
        None,
        title="Request ID",
        description="Optional idempotency token for the update request",
    )


class GCSGetOrganizationIntelligenceConfig(BaseModel):
    """Get the Storage Intelligence config for an organization."""

    operation: Literal["get_organization_intelligence_config"] = Field(
        "get_organization_intelligence_config",
        json_schema_extra={
            "const": "get_organization_intelligence_config",
            "ui:hidden": True,
            "x-category": "Storage Intelligence",
            "x-is-trigger": False,
            "x-display-name": "Get Organization Intelligence Config",
        },
        title="Get Organization Intelligence Config",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="Google Cloud organization ID"
    )


class GCSUpdateOrganizationIntelligenceConfig(BaseModel):
    """Update the Storage Intelligence config for an organization."""

    operation: Literal["update_organization_intelligence_config"] = Field(
        "update_organization_intelligence_config",
        json_schema_extra={
            "const": "update_organization_intelligence_config",
            "ui:hidden": True,
            "x-category": "Storage Intelligence",
            "x-is-trigger": False,
            "x-display-name": "Update Organization Intelligence Config",
        },
        title="Update Organization Intelligence Config",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="Google Cloud organization ID"
    )
    intelligence_config_json: str = Field(
        ...,
        title="Intelligence Config (JSON)",
        description="The IntelligenceConfig resource as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )
    update_mask: str = Field(
        ...,
        title="Update Mask",
        description="Comma-separated field mask of IntelligenceConfig fields to update",
    )
    request_id: Optional[str] = Field(
        None,
        title="Request ID",
        description="Optional idempotency token for the update request",
    )


# ============================================================================
# Trigger Operation Config (poll-based)
# ============================================================================


class GCSOnNewObjectConfig(BaseModel):
    """Poll a bucket/prefix and trigger on newly-created objects.

    GCS has no direct HTTP webhook (only Pub/Sub notifications), so this trigger
    is poll-based: an external scheduler POSTs the node's webhook URL on the
    configured schedule, ``execute()`` lists objects, and emits only those whose
    creation time is newer than the last poll. The cursor (``last_polled_at``)
    is the max ``timeCreated`` seen so far, so already-seen objects never
    re-emit. The first poll baselines (records the cursor, emits nothing).
    """

    operation: Literal["on_new_object"] = Field(
        "on_new_object",
        json_schema_extra={
            "const": "on_new_object",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On New Object",
        },
        title="On New Object",
    )
    bucket: str = Field(
        ...,
        title="Bucket",
        description="Bucket to watch for newly-created objects",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "bucket",
                "placeholder": "Select a bucket...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a bucket name",
            }
        },
    )
    project_id: Optional[str] = Field(
        None,
        title="Project ID",
        description="GCP project ID (used to populate the bucket dropdown)",
    )
    prefix: Optional[str] = Field(
        None,
        title="Prefix",
        description="Only watch objects whose names start with this prefix (e.g. 'incoming/')",
    )
    max_results: Optional[str] = Field(
        "100",
        title="Max Objects Per Poll",
        description="Maximum number of objects to scan per poll",
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to poll the bucket for new objects",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    # Hidden internal fields for webhook/schedule management
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True, "ui:copyable": True},
    )
    schedule_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_active: Optional[bool] = Field(
        default=True, json_schema_extra={"ui:hidden": True}
    )
    # Dedup cursor: the max object timeCreated seen on the previous poll.
    last_polled_at: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


# ============================================================================
# Discriminated Union
# ============================================================================


GoogleCloudStorageConfig = Annotated[
    Union[
        GCSListBucketsConfig,
        GCSGetBucketConfig,
        GCSCreateBucketConfig,
        GCSUpdateBucketConfig,
        GCSPatchBucketConfig,
        GCSDeleteBucketConfig,
        GCSLockRetentionPolicyConfig,
        GCSGetStorageLayoutConfig,
        GCSRestoreBucketConfig,
        GCSRelocateBucketConfig,
        GCSGetBucketIamConfig,
        GCSSetBucketIamConfig,
        GCSTestIamPermissionsConfig,
        GCSGetObjectIamConfig,
        GCSSetObjectIamConfig,
        GCSTestObjectIamPermissionsConfig,
        GCSListObjectsConfig,
        GCSGetObjectConfig,
        GCSDownloadObjectConfig,
        GCSUploadObjectConfig,
        GCSUpdateObjectConfig,
        GCSPatchObjectConfig,
        GCSDeleteObjectConfig,
        GCSCopyObjectConfig,
        GCSRewriteObjectConfig,
        GCSComposeObjectsConfig,
        GCSMoveObjectConfig,
        GCSRestoreObjectConfig,
        GCSGetObjectAclConfig,
        GCSBulkRestoreObjectsConfig,
        GCSCreateNotificationConfig,
        GCSGetNotificationConfig,
        GCSListNotificationsConfig,
        GCSDeleteNotificationConfig,
        GCSCreateHmacKeyConfig,
        GCSListHmacKeysConfig,
        GCSGetHmacKeyConfig,
        GCSUpdateHmacKeyConfig,
        GCSDeleteHmacKeyConfig,
        GCSGetServiceAccountConfig,
        GCSGetOperationConfig,
        GCSListOperationsConfig,
        GCSCancelOperationConfig,
        GCSAdvanceRelocateBucketConfig,
        GCSListBucketAclConfig,
        GCSGetBucketAclConfig,
        GCSCreateBucketAclConfig,
        GCSPatchBucketAclConfig,
        GCSUpdateBucketAclConfig,
        GCSDeleteBucketAclConfig,
        GCSListDefaultObjectAclConfig,
        GCSGetDefaultObjectAclConfig,
        GCSCreateDefaultObjectAclConfig,
        GCSPatchDefaultObjectAclConfig,
        GCSUpdateDefaultObjectAclConfig,
        GCSDeleteDefaultObjectAclConfig,
        GCSListObjectAclEntriesConfig,
        GCSGetObjectAclEntryConfig,
        GCSCreateObjectAclEntryConfig,
        GCSPatchObjectAclEntryConfig,
        GCSUpdateObjectAclEntryConfig,
        GCSDeleteObjectAclEntryConfig,
        GCSListFoldersConfig,
        GCSGetFolderConfig,
        GCSCreateFolderConfig,
        GCSRenameFolderConfig,
        GCSDeleteFolderConfig,
        GCSDeleteFolderRecursiveConfig,
        GCSListManagedFoldersConfig,
        GCSGetManagedFolderConfig,
        GCSCreateManagedFolderConfig,
        GCSDeleteManagedFolderConfig,
        GCSGetManagedFolderIamConfig,
        GCSSetManagedFolderIamConfig,
        GCSTestManagedFolderIamPermissionsConfig,
        GCSListAnywhereCachesConfig,
        GCSGetAnywhereCacheConfig,
        GCSCreateAnywhereCacheConfig,
        GCSUpdateAnywhereCacheConfig,
        GCSDisableAnywhereCacheConfig,
        GCSPauseAnywhereCacheConfig,
        GCSResumeAnywhereCacheConfig,
        GCSGetProjectIntelligenceConfig,
        GCSUpdateProjectIntelligenceConfig,
        GCSGetFolderIntelligenceConfig,
        GCSUpdateFolderIntelligenceConfig,
        GCSGetOrganizationIntelligenceConfig,
        GCSUpdateOrganizationIntelligenceConfig,
        GCSOnNewObjectConfig,
    ],
    Discriminator("operation"),
]


class GoogleCloudStorageNodeConfig(
    NodeConfig[GoogleCloudStorageConfig, GoogleCloudStorageCredential]
):
    """Full configuration for the Google Cloud Storage node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _enc(value: str) -> str:
    """URL-encode an object name for use in a path segment (slashes included)."""
    return quote(value, safe="")


def _parse_json_object(value: Optional[str], field_label: str) -> Dict[str, Any]:
    """Parse a JSON-object string field, raising a clear error on bad input."""
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field_label} must be valid JSON: {e}")
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_label} must be a JSON object")
    return parsed


def _parse_service_account_json(value: str) -> Dict[str, Any]:
    """Parse and validate a Google service-account JSON key blob."""
    data = _parse_json_object(value, "Service Account JSON")
    required_fields = [
        "type",
        "client_email",
        "private_key",
        "private_key_id",
        "token_uri",
    ]
    missing = [field for field in required_fields if not data.get(field)]
    if missing:
        raise ValueError(
            f"Service Account JSON is missing required fields: {', '.join(missing)}"
        )
    if data.get("type") != "service_account":
        raise ValueError("Service Account JSON must have type=service_account")
    return data


def _project_id_from_credential_data(
    credential_data: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Best-effort project lookup from credential payloads."""
    credential_data = credential_data or {}
    project_id = credential_data.get("project_id")
    if project_id:
        return project_id
    if credential_data.get("credential_type") == "google_cloud_storage_service_account":
        try:
            return _parse_service_account_json(
                credential_data.get("service_account_json", "")
            ).get("project_id")
        except ValueError:
            return None
    return None


def _normalize_folder_name(folder: str) -> str:
    folder = (folder or "").strip()
    if not folder:
        raise ValueError("Folder Name is required")
    return folder if folder.endswith("/") else f"{folder}/"


def _normalize_managed_folder_name(folder: str) -> str:
    folder = (folder or "").strip().strip("/")
    if not folder:
        raise ValueError("Managed Folder Name is required")
    return folder


def _decode_upload_bytes(content: Optional[str], content_base64: Optional[str]) -> bytes:
    """Resolve upload input as raw bytes, supporting text and base64 payloads."""
    if content_base64:
        try:
            return base64.b64decode(content_base64, validate=True)
        except Exception as e:
            raise ValueError(f"Base64 Content must be valid base64: {e}")
    if content is None:
        raise ValueError("Either Content or Base64 Content is required")
    return content.encode("utf-8")


async def _mint_service_account_access_token(
    service_account_json: str, scopes: Optional[List[str]] = None
) -> str:
    """Exchange a service-account JWT assertion for an OAuth access token."""
    service_account = _parse_service_account_json(service_account_json)
    token_uri = require_google_service_account_token_uri(
        service_account["token_uri"]
    )
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": service_account["client_email"],
            "scope": " ".join(scopes or GCS_OAUTH_SCOPES),
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        },
        service_account["private_key"],
        algorithm="RS256",
        headers={"kid": service_account["private_key_id"]},
    )
    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(
            token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
    if response.status_code >= 400:
        raise ValueError(
            f"Service account token exchange failed: {_extract_error_message(response)}"
        )
    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("Service account token exchange returned no access_token")
    return access_token


async def _resolve_access_token_from_credential_data(
    credential_data: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Resolve a usable bearer token from raw credential data."""
    credential_data = credential_data or {}
    credential_type = credential_data.get("credential_type")
    if credential_type == "google_cloud_storage_service_account":
        service_account_json = credential_data.get("service_account_json")
        if not service_account_json:
            return None
        return await _mint_service_account_access_token(service_account_json)
    return credential_data.get("access_token")


def _extract_error_message(response: httpx.Response) -> str:
    try:
        err = response.json()
        message = err.get("error", {})
        if isinstance(message, dict):
            message = message.get("message") or str(err)
        else:
            message = err.get("message", str(err))
    except Exception:
        message = response.text
    if isinstance(message, str):
        return message.encode("ascii", errors="replace").decode("ascii")
    return str(message).encode("ascii", errors="replace").decode("ascii")


def _error_result(action_name: str, response: httpx.Response, api_ms: float) -> Dict[str, Any]:
    message = _extract_error_message(response)
    logger.error(f"[GoogleCloudStorageNode] API error ({action_name}): {message}")
    return {
        "status": "error",
        "action": action_name,
        "error": message,
        "status_code": response.status_code,
        "timing_ms": {"api_request": api_ms},
    }


def _success_result(action_name: str, data: Any, status_code: int, api_ms: float) -> Dict[str, Any]:
    return {
        "status": "success",
        "action": action_name,
        "data": data,
        "status_code": status_code,
        "timing_ms": {"api_request": api_ms},
    }


async def _gcs_request(
    access_token: str,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    raw_body: Optional[bytes] = None,
    content_type: Optional[str] = None,
    expect_bytes: bool = False,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Google Cloud Storage request and return a structured result."""
    headers = {"Authorization": f"Bearer {access_token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if content_type and raw_body is not None:
        headers["Content-Type"] = content_type
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body if json_body is not None else None,
                content=raw_body,
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                return _error_result(action_name, response, api_ms)
            if expect_bytes:
                raw = response.content
                data: Any = {
                    "content_base64": base64.b64encode(raw).decode("ascii"),
                    "size": len(raw),
                }
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
                if text is not None:
                    data["content"] = text
                    data["content_text"] = text
            elif response.status_code == 204 or not response.content:
                data = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return _success_result(action_name, data, response.status_code, api_ms)
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
            logger.error(f"[GoogleCloudStorageNode] Request failed ({action_name}): {msg}")
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


class GoogleCloudStorageNode(CronScheduleTriggerMixin, WorkflowNode):
    """Google Cloud Storage automation node (JSON API v1)."""

    schedule_trigger_operations = ("on_new_object",)
    schedule_source = "gcs_trigger"

    edit_examples = [
        "List all objects in my data bucket",
        "Upload a JSON report to a Cloud Storage bucket",
        "Download a file from a bucket and pass its contents downstream",
        "Copy an object from one bucket to another",
        "Create a new storage bucket in my project",
    ]

    scope_registry = GOOGLE_CLOUD_STORAGE_SCOPES
    connection_evidence = ConnectionEvidence(
        field="bucket",
        noun="buckets",
    )

    @classmethod
    def get_config_model(cls):
        return GoogleCloudStorageNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """The GCS trigger is poll-based: the cron webhook is a wake-up signal,
        not data. Return None so execute() runs and actually polls the API."""
        if config.get("operation") == "on_new_object":
            return None
        return payload

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """A scheduled poll that found no newly-created objects → skip downstream.
        Dedup is done via the ``last_polled_at`` cursor, so emptiness is read off
        the poll output's ``new_count``. See ``WorkflowNode``."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_new_object"
            and not output.get("new_count")
        )

    def trigger_emitted_event(self, output):
        """Fresh objects emitted → executor stamps _pollFired so a wired agent
        receives them on any run source."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_new_object"
            and bool(output.get("new_count"))
        )

    # load_field_value (webhook + schedule registration, incl. the
    # config-validity gate) is inherited from CronScheduleTriggerMixin —
    # it converges through reconcile_node.

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns / triggers)."""
        if (credential_data or {}).get("credential_type") == "google_cloud_storage_service_account":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="google",
        )

    # ------------------------------------------------------------------
    # Dynamic options (buckets / folders / managed folders)
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
        if field_name not in {"bucket", "folder_name", "managed_folder"}:
            return {"options": [], "next_page_token": None}

        access_token = await _resolve_access_token_from_credential_data(credential_data)
        if not access_token:
            return {"options": [], "next_page_token": None}

        if field_name == "bucket":
            project_id = (context or {}).get("project_id") or _project_id_from_credential_data(
                credential_data
            )
            if not project_id:
                return {"options": [], "next_page_token": None}

            result = await _gcs_request(
                access_token,
                "GET",
                f"{GCS_API_BASE}/b",
                params={
                    "project": project_id,
                    "pageToken": page_token,
                    "prefix": search,
                },
                action_name="list_buckets",
            )
            if result.get("status") != "success":
                return {"options": [], "next_page_token": None}
            items = (result.get("data") or {}).get("items") or []
            options = []
            for b in items:
                if not isinstance(b, dict):
                    continue
                name = b.get("name")
                if name:
                    options.append({"label": name, "value": name})
            return {
                "options": options,
                "next_page_token": (result.get("data") or {}).get("nextPageToken"),
            }

        bucket = (context or {}).get("bucket")
        if not bucket:
            return {"options": [], "next_page_token": None}

        if field_name == "folder_name":
            result = await _gcs_request(
                access_token,
                "GET",
                f"{GCS_API_BASE}/b/{_enc(bucket)}/folders",
                params={"prefix": search, "pageToken": page_token},
                action_name="list_folder_options",
            )
            if result.get("status") != "success":
                return {"options": [], "next_page_token": None}
            items = (result.get("data") or {}).get("items") or (result.get("data") or {}).get("folders") or []
            options = []
            for folder in items:
                if not isinstance(folder, dict):
                    continue
                name = folder.get("name")
                if name:
                    options.append({"label": name, "value": name})
            return {
                "options": options,
                "next_page_token": (result.get("data") or {}).get("nextPageToken"),
            }

        result = await _gcs_request(
            access_token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(bucket)}/managedFolders",
            params={"prefix": search, "pageToken": page_token},
            action_name="list_managed_folder_options",
        )
        if result.get("status") != "success":
            return {"options": [], "next_page_token": None}
        items = (result.get("data") or {}).get("items") or (result.get("data") or {}).get("managedFolders") or []
        options = []
        for folder in items:
            if not isinstance(folder, dict):
                continue
            name = folder.get("name")
            if name:
                options.append({"label": name, "value": name})
        return {
            "options": options,
            "next_page_token": (result.get("data") or {}).get("nextPageToken"),
        }

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------
    async def _ensure_fresh_token(
        self, credentials: GoogleCloudStorageCredential
    ) -> str:
        """Return a valid Google access token for either supported credential mode."""
        if isinstance(credentials, GoogleCloudStorageServiceAccountCredential):
            return await _mint_service_account_access_token(
                credentials.service_account_json
            )

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, GoogleCloudStorageNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect your Google Cloud Storage account."
            )
        access_token = await self._ensure_fresh_token(credentials)

        handlers = {
            "list_buckets": self._list_buckets,
            "get_bucket": self._get_bucket,
            "create_bucket": self._create_bucket,
            "update_bucket": self._update_bucket,
            "patch_bucket": self._patch_bucket,
            "delete_bucket": self._delete_bucket,
            "lock_retention_policy": self._lock_retention_policy,
            "get_storage_layout": self._get_storage_layout,
            "restore_bucket": self._restore_bucket,
            "relocate_bucket": self._relocate_bucket,
            "get_bucket_iam": self._get_bucket_iam,
            "set_bucket_iam": self._set_bucket_iam,
            "test_iam_permissions": self._test_iam_permissions,
            "get_object_iam": self._get_object_iam,
            "set_object_iam": self._set_object_iam,
            "test_object_iam_permissions": self._test_object_iam_permissions,
            "list_objects": self._list_objects,
            "get_object": self._get_object,
            "download_object": self._download_object,
            "upload_object": self._upload_object,
            "update_object": self._update_object,
            "patch_object": self._patch_object,
            "delete_object": self._delete_object,
            "copy_object": self._copy_object,
            "rewrite_object": self._rewrite_object,
            "compose_objects": self._compose_objects,
            "move_object": self._move_object,
            "restore_object": self._restore_object,
            "get_object_acl": self._get_object_acl,
            "bulk_restore_objects": self._bulk_restore_objects,
            "create_notification": self._create_notification,
            "get_notification": self._get_notification,
            "list_notifications": self._list_notifications,
            "delete_notification": self._delete_notification,
            "create_hmac_key": self._create_hmac_key,
            "list_hmac_keys": self._list_hmac_keys,
            "get_hmac_key": self._get_hmac_key,
            "update_hmac_key": self._update_hmac_key,
            "delete_hmac_key": self._delete_hmac_key,
            "get_service_account": self._get_service_account,
            "get_operation": self._get_operation,
            "list_operations": self._list_operations,
            "cancel_operation": self._cancel_operation,
            "advance_relocate_bucket": self._advance_relocate_bucket,
            "list_bucket_acl": self._list_bucket_acl,
            "get_bucket_acl": self._get_bucket_acl,
            "create_bucket_acl": self._create_bucket_acl,
            "patch_bucket_acl": self._patch_bucket_acl,
            "update_bucket_acl": self._update_bucket_acl,
            "delete_bucket_acl": self._delete_bucket_acl,
            "list_default_object_acl": self._list_default_object_acl,
            "get_default_object_acl": self._get_default_object_acl,
            "create_default_object_acl": self._create_default_object_acl,
            "patch_default_object_acl": self._patch_default_object_acl,
            "update_default_object_acl": self._update_default_object_acl,
            "delete_default_object_acl": self._delete_default_object_acl,
            "list_object_acl_entries": self._list_object_acl_entries,
            "get_object_acl_entry": self._get_object_acl_entry,
            "create_object_acl_entry": self._create_object_acl_entry,
            "patch_object_acl_entry": self._patch_object_acl_entry,
            "update_object_acl_entry": self._update_object_acl_entry,
            "delete_object_acl_entry": self._delete_object_acl_entry,
            "list_folders": self._list_folders,
            "get_folder": self._get_folder,
            "create_folder": self._create_folder,
            "rename_folder": self._rename_folder,
            "delete_folder": self._delete_folder,
            "delete_folder_recursive": self._delete_folder_recursive,
            "list_managed_folders": self._list_managed_folders,
            "get_managed_folder": self._get_managed_folder,
            "create_managed_folder": self._create_managed_folder,
            "delete_managed_folder": self._delete_managed_folder,
            "get_managed_folder_iam": self._get_managed_folder_iam,
            "set_managed_folder_iam": self._set_managed_folder_iam,
            "test_managed_folder_iam_permissions": self._test_managed_folder_iam_permissions,
            "list_anywhere_caches": self._list_anywhere_caches,
            "get_anywhere_cache": self._get_anywhere_cache,
            "create_anywhere_cache": self._create_anywhere_cache,
            "update_anywhere_cache": self._update_anywhere_cache,
            "disable_anywhere_cache": self._disable_anywhere_cache,
            "pause_anywhere_cache": self._pause_anywhere_cache,
            "resume_anywhere_cache": self._resume_anywhere_cache,
            "get_project_intelligence_config": self._get_project_intelligence_config,
            "update_project_intelligence_config": self._update_project_intelligence_config,
            "get_folder_intelligence_config": self._get_folder_intelligence_config,
            "update_folder_intelligence_config": self._update_folder_intelligence_config,
            "get_organization_intelligence_config": self._get_organization_intelligence_config,
            "update_organization_intelligence_config": self._update_organization_intelligence_config,
            "on_new_object": self._poll_new_objects,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, access_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    async def _bucket_acl_request(
        self,
        token: str,
        method: str,
        bucket: str,
        action_name: str,
        entity: Optional[str] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{GCS_API_BASE}/b/{bucket}/acl"
        if entity:
            url += f"/{_enc(entity)}"
        return await _gcs_request(
            token,
            method,
            url,
            json_body=json_body,
            action_name=action_name,
        )

    async def _default_object_acl_request(
        self,
        token: str,
        method: str,
        bucket: str,
        action_name: str,
        entity: Optional[str] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{GCS_API_BASE}/b/{bucket}/defaultObjectAcl"
        if entity:
            url += f"/{_enc(entity)}"
        return await _gcs_request(
            token,
            method,
            url,
            json_body=json_body,
            action_name=action_name,
        )

    async def _object_acl_request(
        self,
        token: str,
        method: str,
        bucket: str,
        object_name: str,
        action_name: str,
        entity: Optional[str] = None,
        generation: Optional[str] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{GCS_API_BASE}/b/{bucket}/o/{_enc(object_name)}/acl"
        if entity:
            url += f"/{_enc(entity)}"
        return await _gcs_request(
            token,
            method,
            url,
            params={"generation": generation},
            json_body=json_body,
            action_name=action_name,
        )

    async def _folder_request(
        self,
        token: str,
        method: str,
        bucket: str,
        action_name: str,
        folder_name: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{GCS_API_BASE}/b/{bucket}/folders"
        if folder_name:
            url += f"/{_enc(_normalize_folder_name(folder_name))}"
        return await _gcs_request(
            token,
            method,
            url,
            params=params,
            json_body=json_body,
            action_name=action_name,
        )

    async def _managed_folder_request(
        self,
        token: str,
        method: str,
        bucket: str,
        action_name: str,
        managed_folder: Optional[str] = None,
        suffix: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{GCS_API_BASE}/b/{bucket}/managedFolders"
        if managed_folder:
            url += f"/{_enc(_normalize_managed_folder_name(managed_folder))}"
        if suffix:
            url += suffix
        return await _gcs_request(
            token,
            method,
            url,
            params=params,
            json_body=json_body,
            action_name=action_name,
        )

    async def _anywhere_cache_request(
        self,
        token: str,
        method: str,
        bucket: str,
        action_name: str,
        anywhere_cache_id: Optional[str] = None,
        suffix: Optional[str] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{GCS_API_BASE}/b/{bucket}/anywhereCaches"
        if anywhere_cache_id:
            url += f"/{_enc(anywhere_cache_id)}"
        if suffix:
            url += suffix
        return await _gcs_request(
            token,
            method,
            url,
            json_body=json_body,
            action_name=action_name,
        )

    async def _intelligence_config_request(
        self,
        token: str,
        method: str,
        resource_type: str,
        resource_id: str,
        action_name: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            method,
            f"{GCS_V2_BASE}/{resource_type}/{_enc(resource_id)}/locations/global/intelligenceConfig",
            params=params,
            json_body=json_body,
            action_name=action_name,
        )

    # ------------------------------------------------------------------
    # Bucket handlers
    # ------------------------------------------------------------------
    async def _list_buckets(self, c: GCSListBucketsConfig, token: str) -> Dict[str, Any]:
        params = {
            "project": c.project_id,
            "prefix": c.prefix,
            "maxResults": c.max_results,
            "pageToken": c.page_token,
        }
        return await _gcs_request(
            token, "GET", f"{GCS_API_BASE}/b", params=params, action_name="list_buckets"
        )

    async def _get_bucket(self, c: GCSGetBucketConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token, "GET", f"{GCS_API_BASE}/b/{_enc(c.bucket)}", action_name="get_bucket"
        )

    async def _create_bucket(self, c: GCSCreateBucketConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name, "location": c.location}
        if c.storage_class:
            body["storageClass"] = c.storage_class
        body.update(_parse_json_object(c.metadata_json, "Additional Metadata"))
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b",
            params={"project": c.project_id},
            json_body=body,
            action_name="create_bucket",
        )

    async def _update_bucket(self, c: GCSUpdateBucketConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_object(c.metadata_json, "Bucket Metadata")
        return await _gcs_request(
            token, "PUT", f"{GCS_API_BASE}/b/{_enc(c.bucket)}", json_body=body,
            action_name="update_bucket",
        )

    async def _patch_bucket(self, c: GCSPatchBucketConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_object(c.metadata_json, "Patch Metadata")
        return await _gcs_request(
            token, "PATCH", f"{GCS_API_BASE}/b/{_enc(c.bucket)}", json_body=body,
            action_name="patch_bucket",
        )

    async def _delete_bucket(self, c: GCSDeleteBucketConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token, "DELETE", f"{GCS_API_BASE}/b/{_enc(c.bucket)}", action_name="delete_bucket"
        )

    async def _lock_retention_policy(
        self, c: GCSLockRetentionPolicyConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/lockRetentionPolicy",
            params={"ifMetagenerationMatch": c.metageneration},
            action_name="lock_retention_policy",
        )

    async def _get_storage_layout(
        self, c: GCSGetStorageLayoutConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/storageLayout",
            params={"prefix": c.prefix},
            action_name="get_storage_layout",
        )

    async def _restore_bucket(self, c: GCSRestoreBucketConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/restore",
            params={"generation": c.generation},
            json_body={},
            action_name="restore_bucket",
        )

    async def _relocate_bucket(
        self, c: GCSRelocateBucketConfig, token: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "destinationLocation": c.destination_location,
            "validateOnly": c.validate_only,
        }
        data_locations = _comma_list(c.destination_data_locations)
        if data_locations:
            body["destinationCustomPlacementConfig"] = {
                "dataLocations": data_locations,
            }
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/relocate",
            json_body=body,
            action_name="relocate_bucket",
        )

    # ------------------------------------------------------------------
    # IAM handlers
    # ------------------------------------------------------------------
    async def _get_bucket_iam(self, c: GCSGetBucketIamConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token, "GET", f"{GCS_API_BASE}/b/{_enc(c.bucket)}/iam", action_name="get_bucket_iam"
        )

    async def _set_bucket_iam(self, c: GCSSetBucketIamConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_object(c.policy_json, "IAM Policy")
        return await _gcs_request(
            token, "PUT", f"{GCS_API_BASE}/b/{_enc(c.bucket)}/iam", json_body=body,
            action_name="set_bucket_iam",
        )

    async def _test_iam_permissions(
        self, c: GCSTestIamPermissionsConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/iam/testPermissions",
            params={"permissions": _comma_list(c.permissions)},
            action_name="test_iam_permissions",
        )

    async def _get_object_iam(self, c: GCSGetObjectIamConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}/iam",
            action_name="get_object_iam",
        )

    async def _set_object_iam(self, c: GCSSetObjectIamConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_object(c.policy_json, "IAM Policy")
        return await _gcs_request(
            token,
            "PUT",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}/iam",
            json_body=body,
            action_name="set_object_iam",
        )

    async def _test_object_iam_permissions(
        self, c: GCSTestObjectIamPermissionsConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}/iam/testPermissions",
            params={"permissions": _comma_list(c.permissions)},
            action_name="test_object_iam_permissions",
        )

    # ------------------------------------------------------------------
    # Object handlers
    # ------------------------------------------------------------------
    async def _list_objects(self, c: GCSListObjectsConfig, token: str) -> Dict[str, Any]:
        params = {
            "prefix": c.prefix,
            "delimiter": c.delimiter,
            "maxResults": c.max_results,
            "pageToken": c.page_token,
        }
        return await _gcs_request(
            token, "GET", f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o", params=params,
            action_name="list_objects",
        )

    async def _get_object(self, c: GCSGetObjectConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}",
            action_name="get_object",
        )

    async def _download_object(self, c: GCSDownloadObjectConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}",
            params={"alt": "media"},
            expect_bytes=True,
            action_name="download_object",
        )

    async def _upload_object(self, c: GCSUploadObjectConfig, token: str) -> Dict[str, Any]:
        resolved_mime: Optional[str] = None
        if c.media_input:
            from nodes.core.media_resolver import resolve_media_input

            resolved = await resolve_media_input(c.media_input)
            raw_bytes = resolved.data
            resolved_mime = resolved.mime_type
        else:
            raw_bytes = _decode_upload_bytes(c.content, c.content_base64)
        metadata = _parse_json_object(c.metadata_json, "Object Metadata")
        upload_type = (c.upload_type or "simple").strip().lower()
        content_type = c.content_type or resolved_mime or "text/plain"
        if resolved_mime and c.content_type == "text/plain":
            content_type = resolved_mime

        if upload_type == "simple":
            return await _gcs_request(
                token,
                "POST",
                f"{GCS_UPLOAD_BASE}/b/{_enc(c.bucket)}/o",
                params={"uploadType": "media", "name": c.object_name},
                raw_body=raw_bytes,
                content_type=content_type,
                action_name="upload_object",
            )

        if upload_type == "multipart":
            metadata = {"name": c.object_name, **metadata}
            boundary = "noclick-gcs-upload"
            multipart_body = (
                f"--{boundary}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            ).encode("utf-8")
            multipart_body += json.dumps(metadata).encode("utf-8")
            multipart_body += (
                f"\r\n--{boundary}\r\n"
                f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n"
            ).encode("utf-8")
            multipart_body += raw_bytes
            multipart_body += f"\r\n--{boundary}--\r\n".encode("utf-8")
            return await _gcs_request(
                token,
                "POST",
                f"{GCS_UPLOAD_BASE}/b/{_enc(c.bucket)}/o",
                params={"uploadType": "multipart"},
                raw_body=multipart_body,
                content_type=f"multipart/related; boundary={boundary}",
                action_name="upload_object",
            )

        if upload_type != "resumable":
            raise ValueError("Upload Type must be one of: simple, multipart, resumable")

        metadata = {"name": c.object_name, **metadata}
        init_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Upload-Content-Type": content_type or "application/octet-stream",
        }
        start = time.time()
        async with guarded_async_client(timeout=60.0) as client:
            try:
                init_response = await client.request(
                    method="POST",
                    url=f"{GCS_UPLOAD_BASE}/b/{_enc(c.bucket)}/o",
                    headers=init_headers,
                    params={"uploadType": "resumable"},
                    json=metadata,
                )
                init_ms = round((time.time() - start) * 1000, 2)
                if init_response.status_code >= 400:
                    return _error_result("upload_object", init_response, init_ms)

                session_uri = init_response.headers.get("Location")
                if not session_uri:
                    return {
                        "status": "error",
                        "action": "upload_object",
                        "error": "Missing resumable upload session URI",
                        "status_code": 500,
                        "timing_ms": {"api_request": init_ms},
                    }

                await assert_url_allowed(session_uri)

                upload_start = time.time()
                upload_response = await client.request(
                    method="PUT",
                    url=session_uri,
                    headers={"Content-Type": c.content_type or "application/octet-stream"},
                    content=raw_bytes,
                )
                upload_ms = round((time.time() - upload_start) * 1000, 2)
                if upload_response.status_code >= 400:
                    return _error_result("upload_object", upload_response, upload_ms)
                try:
                    data: Any = upload_response.json()
                except Exception:
                    data = {"raw": upload_response.text}
                return _success_result(
                    "upload_object",
                    data,
                    upload_response.status_code,
                    upload_ms,
                )
            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": "upload_object",
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
                }
            except Exception as e:
                msg = str(e).encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[GoogleCloudStorageNode] Request failed (upload_object): {msg}")
                return {
                    "status": "error",
                    "action": "upload_object",
                    "error": msg,
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
                }

    async def _update_object(self, c: GCSUpdateObjectConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_object(c.metadata_json, "Object Metadata")
        return await _gcs_request(
            token,
            "PUT",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}",
            json_body=body,
            action_name="update_object",
        )

    async def _patch_object(self, c: GCSPatchObjectConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_object(c.metadata_json, "Patch Metadata")
        return await _gcs_request(
            token,
            "PATCH",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}",
            json_body=body,
            action_name="patch_object",
        )

    async def _delete_object(self, c: GCSDeleteObjectConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "DELETE",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}",
            params={"generation": c.generation},
            action_name="delete_object",
        )

    async def _copy_object(self, c: GCSCopyObjectConfig, token: str) -> Dict[str, Any]:
        url = (
            f"{GCS_API_BASE}/b/{_enc(c.source_bucket)}/o/{_enc(c.source_object)}"
            f"/copyTo/b/{_enc(c.destination_bucket)}/o/{_enc(c.destination_object)}"
        )
        return await _gcs_request(token, "POST", url, json_body={}, action_name="copy_object")

    async def _rewrite_object(self, c: GCSRewriteObjectConfig, token: str) -> Dict[str, Any]:
        url = (
            f"{GCS_API_BASE}/b/{_enc(c.source_bucket)}/o/{_enc(c.source_object)}"
            f"/rewriteTo/b/{_enc(c.destination_bucket)}/o/{_enc(c.destination_object)}"
        )
        return await _gcs_request(
            token, "POST", url, params={"rewriteToken": c.rewrite_token},
            json_body={}, action_name="rewrite_object",
        )

    async def _compose_objects(self, c: GCSComposeObjectsConfig, token: str) -> Dict[str, Any]:
        sources = _comma_list(c.source_objects) or []
        body = {"sourceObjects": [{"name": s} for s in sources]}
        url = f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.destination_object)}/compose"
        return await _gcs_request(token, "POST", url, json_body=body, action_name="compose_objects")

    async def _move_object(self, c: GCSMoveObjectConfig, token: str) -> Dict[str, Any]:
        url = (
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.source_object)}"
            f"/moveTo/o/{_enc(c.destination_object)}"
        )
        return await _gcs_request(token, "POST", url, json_body={}, action_name="move_object")

    async def _restore_object(self, c: GCSRestoreObjectConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}/restore",
            params={"generation": c.generation},
            json_body={},
            action_name="restore_object",
        )

    async def _get_object_acl(self, c: GCSGetObjectAclConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/{_enc(c.object_name)}/acl",
            action_name="get_object_acl",
        )

    async def _bulk_restore_objects(
        self, c: GCSBulkRestoreObjectsConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "allowOverwrite": c.allow_overwrite,
            "copySourceAcl": c.copy_source_acl,
            "deletedAfterTime": c.deleted_after_time,
            "deletedBeforeTime": c.deleted_before_time,
            "matchGlob": c.match_glob,
        }
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o/bulkRestore",
            json_body=body,
            action_name="bulk_restore_objects",
        )

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------
    async def _create_notification(
        self, c: GCSCreateNotificationConfig, token: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"topic": c.topic, "payload_format": c.payload_format}
        event_types = _comma_list(c.event_types)
        if event_types:
            body["event_types"] = event_types
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/notificationConfigs",
            json_body=body,
            action_name="create_notification",
        )

    async def _list_notifications(
        self, c: GCSListNotificationsConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/notificationConfigs",
            action_name="list_notifications",
        )

    async def _get_notification(
        self, c: GCSGetNotificationConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/notificationConfigs/{_enc(c.notification_id)}",
            action_name="get_notification",
        )

    async def _delete_notification(
        self, c: GCSDeleteNotificationConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "DELETE",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/notificationConfigs/{_enc(c.notification_id)}",
            action_name="delete_notification",
        )

    # ------------------------------------------------------------------
    # Project handlers
    # ------------------------------------------------------------------
    async def _create_hmac_key(self, c: GCSCreateHmacKeyConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/projects/{_enc(c.project_id)}/hmacKeys",
            params={"serviceAccountEmail": c.service_account_email},
            action_name="create_hmac_key",
        )

    async def _list_hmac_keys(self, c: GCSListHmacKeysConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/projects/{_enc(c.project_id)}/hmacKeys",
            params={"serviceAccountEmail": c.service_account_email},
            action_name="list_hmac_keys",
        )

    async def _get_hmac_key(self, c: GCSGetHmacKeyConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/projects/{_enc(c.project_id)}/hmacKeys/{_enc(c.access_id)}",
            action_name="get_hmac_key",
        )

    async def _update_hmac_key(
        self, c: GCSUpdateHmacKeyConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "PUT",
            f"{GCS_API_BASE}/projects/{_enc(c.project_id)}/hmacKeys/{_enc(c.access_id)}",
            json_body={"state": c.state},
            action_name="update_hmac_key",
        )

    async def _delete_hmac_key(
        self, c: GCSDeleteHmacKeyConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "DELETE",
            f"{GCS_API_BASE}/projects/{_enc(c.project_id)}/hmacKeys/{_enc(c.access_id)}",
            action_name="delete_hmac_key",
        )

    async def _get_service_account(
        self, c: GCSGetServiceAccountConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/projects/{_enc(c.project_id)}/serviceAccount",
            action_name="get_service_account",
        )

    async def _get_operation(self, c: GCSGetOperationConfig, token: str) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/operations/{_enc(c.operation_id)}",
            action_name="get_operation",
        )

    async def _list_operations(
        self, c: GCSListOperationsConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/operations",
            params={"pageToken": c.page_token, "maxResults": c.max_results},
            action_name="list_operations",
        )

    async def _cancel_operation(
        self, c: GCSCancelOperationConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/operations/{_enc(c.operation_id)}/cancel",
            json_body={},
            action_name="cancel_operation",
        )

    async def _advance_relocate_bucket(
        self, c: GCSAdvanceRelocateBucketConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/operations/{_enc(c.operation_id)}/advanceRelocateBucket",
            json_body={},
            action_name="advance_relocate_bucket",
        )

    async def _list_bucket_acl(
        self, c: GCSListBucketAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._bucket_acl_request(
            token, "GET", c.bucket, "list_bucket_acl"
        )

    async def _get_bucket_acl(
        self, c: GCSGetBucketAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._bucket_acl_request(
            token, "GET", c.bucket, "get_bucket_acl", entity=c.entity
        )

    async def _create_bucket_acl(
        self, c: GCSCreateBucketAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._bucket_acl_request(
            token,
            "POST",
            c.bucket,
            "create_bucket_acl",
            json_body={"entity": c.entity, "role": c.role},
        )

    async def _patch_bucket_acl(
        self, c: GCSPatchBucketAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._bucket_acl_request(
            token,
            "PATCH",
            c.bucket,
            "patch_bucket_acl",
            entity=c.entity,
            json_body={"role": c.role},
        )

    async def _update_bucket_acl(
        self, c: GCSUpdateBucketAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._bucket_acl_request(
            token,
            "PUT",
            c.bucket,
            "update_bucket_acl",
            entity=c.entity,
            json_body={"entity": c.entity, "role": c.role},
        )

    async def _delete_bucket_acl(
        self, c: GCSDeleteBucketAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._bucket_acl_request(
            token, "DELETE", c.bucket, "delete_bucket_acl", entity=c.entity
        )

    async def _list_default_object_acl(
        self, c: GCSListDefaultObjectAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._default_object_acl_request(
            token, "GET", c.bucket, "list_default_object_acl"
        )

    async def _get_default_object_acl(
        self, c: GCSGetDefaultObjectAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._default_object_acl_request(
            token,
            "GET",
            c.bucket,
            "get_default_object_acl",
            entity=c.entity,
        )

    async def _create_default_object_acl(
        self, c: GCSCreateDefaultObjectAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._default_object_acl_request(
            token,
            "POST",
            c.bucket,
            "create_default_object_acl",
            json_body={"entity": c.entity, "role": c.role},
        )

    async def _patch_default_object_acl(
        self, c: GCSPatchDefaultObjectAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._default_object_acl_request(
            token,
            "PATCH",
            c.bucket,
            "patch_default_object_acl",
            entity=c.entity,
            json_body={"role": c.role},
        )

    async def _update_default_object_acl(
        self, c: GCSUpdateDefaultObjectAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._default_object_acl_request(
            token,
            "PUT",
            c.bucket,
            "update_default_object_acl",
            entity=c.entity,
            json_body={"entity": c.entity, "role": c.role},
        )

    async def _delete_default_object_acl(
        self, c: GCSDeleteDefaultObjectAclConfig, token: str
    ) -> Dict[str, Any]:
        return await self._default_object_acl_request(
            token,
            "DELETE",
            c.bucket,
            "delete_default_object_acl",
            entity=c.entity,
        )

    async def _list_object_acl_entries(
        self, c: GCSListObjectAclEntriesConfig, token: str
    ) -> Dict[str, Any]:
        return await self._object_acl_request(
            token,
            "GET",
            c.bucket,
            c.object_name,
            "list_object_acl_entries",
            generation=c.generation,
        )

    async def _get_object_acl_entry(
        self, c: GCSGetObjectAclEntryConfig, token: str
    ) -> Dict[str, Any]:
        return await self._object_acl_request(
            token,
            "GET",
            c.bucket,
            c.object_name,
            "get_object_acl_entry",
            entity=c.entity,
            generation=c.generation,
        )

    async def _create_object_acl_entry(
        self, c: GCSCreateObjectAclEntryConfig, token: str
    ) -> Dict[str, Any]:
        return await self._object_acl_request(
            token,
            "POST",
            c.bucket,
            c.object_name,
            "create_object_acl_entry",
            generation=c.generation,
            json_body={"entity": c.entity, "role": c.role},
        )

    async def _patch_object_acl_entry(
        self, c: GCSPatchObjectAclEntryConfig, token: str
    ) -> Dict[str, Any]:
        return await self._object_acl_request(
            token,
            "PATCH",
            c.bucket,
            c.object_name,
            "patch_object_acl_entry",
            entity=c.entity,
            generation=c.generation,
            json_body={"role": c.role},
        )

    async def _update_object_acl_entry(
        self, c: GCSUpdateObjectAclEntryConfig, token: str
    ) -> Dict[str, Any]:
        return await self._object_acl_request(
            token,
            "PUT",
            c.bucket,
            c.object_name,
            "update_object_acl_entry",
            entity=c.entity,
            generation=c.generation,
            json_body={"entity": c.entity, "role": c.role},
        )

    async def _delete_object_acl_entry(
        self, c: GCSDeleteObjectAclEntryConfig, token: str
    ) -> Dict[str, Any]:
        return await self._object_acl_request(
            token,
            "DELETE",
            c.bucket,
            c.object_name,
            "delete_object_acl_entry",
            entity=c.entity,
            generation=c.generation,
        )

    async def _list_folders(self, c: GCSListFoldersConfig, token: str) -> Dict[str, Any]:
        return await self._folder_request(
            token,
            "GET",
            c.bucket,
            "list_folders",
            params={
                "prefix": c.prefix,
                "delimiter": c.delimiter,
                "startOffset": c.start_offset,
                "endOffset": c.end_offset,
                "maxResults": c.max_results,
                "pageToken": c.page_token,
            },
        )

    async def _get_folder(self, c: GCSGetFolderConfig, token: str) -> Dict[str, Any]:
        return await self._folder_request(
            token,
            "GET",
            c.bucket,
            "get_folder",
            folder_name=c.folder_name,
        )

    async def _create_folder(
        self, c: GCSCreateFolderConfig, token: str
    ) -> Dict[str, Any]:
        return await self._folder_request(
            token,
            "POST",
            c.bucket,
            "create_folder",
            params={"recursive": c.recursive},
            json_body={"name": _normalize_folder_name(c.folder_name)},
        )

    async def _rename_folder(
        self, c: GCSRenameFolderConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "POST",
            (
                f"{GCS_API_BASE}/b/{c.bucket}/folders/"
                f"{_enc(_normalize_folder_name(c.source_folder_name))}"
                f"/renameTo/folders/{_enc(_normalize_folder_name(c.destination_folder_name))}"
            ),
            action_name="rename_folder",
        )

    async def _delete_folder(
        self, c: GCSDeleteFolderConfig, token: str
    ) -> Dict[str, Any]:
        return await self._folder_request(
            token,
            "DELETE",
            c.bucket,
            "delete_folder",
            folder_name=c.folder_name,
        )

    async def _delete_folder_recursive(
        self, c: GCSDeleteFolderRecursiveConfig, token: str
    ) -> Dict[str, Any]:
        return await _gcs_request(
            token,
            "POST",
            f"{GCS_API_BASE}/b/{c.bucket}/folders/{_enc(_normalize_folder_name(c.folder_name))}/deleteRecursive",
            params={
                "ifMetagenerationMatch": c.if_metageneration_match,
                "ifMetagenerationNotMatch": c.if_metageneration_not_match,
            },
            action_name="delete_folder_recursive",
        )

    async def _list_managed_folders(
        self, c: GCSListManagedFoldersConfig, token: str
    ) -> Dict[str, Any]:
        return await self._managed_folder_request(
            token,
            "GET",
            c.bucket,
            "list_managed_folders",
            params={
                "prefix": c.prefix,
                "maxResults": c.max_results,
                "pageToken": c.page_token,
            },
        )

    async def _get_managed_folder(
        self, c: GCSGetManagedFolderConfig, token: str
    ) -> Dict[str, Any]:
        return await self._managed_folder_request(
            token,
            "GET",
            c.bucket,
            "get_managed_folder",
            managed_folder=c.managed_folder,
        )

    async def _create_managed_folder(
        self, c: GCSCreateManagedFolderConfig, token: str
    ) -> Dict[str, Any]:
        return await self._managed_folder_request(
            token,
            "POST",
            c.bucket,
            "create_managed_folder",
            json_body={"name": _normalize_managed_folder_name(c.managed_folder)},
        )

    async def _delete_managed_folder(
        self, c: GCSDeleteManagedFolderConfig, token: str
    ) -> Dict[str, Any]:
        return await self._managed_folder_request(
            token,
            "DELETE",
            c.bucket,
            "delete_managed_folder",
            managed_folder=c.managed_folder,
            params={"allowNonEmpty": c.allow_non_empty},
        )

    async def _get_managed_folder_iam(
        self, c: GCSGetManagedFolderIamConfig, token: str
    ) -> Dict[str, Any]:
        return await self._managed_folder_request(
            token,
            "GET",
            c.bucket,
            "get_managed_folder_iam",
            managed_folder=c.managed_folder,
            suffix="/iam",
            params={"optionsRequestedPolicyVersion": c.requested_policy_version},
        )

    async def _set_managed_folder_iam(
        self, c: GCSSetManagedFolderIamConfig, token: str
    ) -> Dict[str, Any]:
        return await self._managed_folder_request(
            token,
            "PUT",
            c.bucket,
            "set_managed_folder_iam",
            managed_folder=c.managed_folder,
            suffix="/iam",
            json_body=_parse_json_object(c.policy_json, "IAM Policy (JSON)"),
        )

    async def _test_managed_folder_iam_permissions(
        self, c: GCSTestManagedFolderIamPermissionsConfig, token: str
    ) -> Dict[str, Any]:
        return await self._managed_folder_request(
            token,
            "GET",
            c.bucket,
            "test_managed_folder_iam_permissions",
            managed_folder=c.managed_folder,
            suffix="/iam/testPermissions",
            params={"permissions": _comma_list(c.permissions)},
        )

    async def _list_anywhere_caches(
        self, c: GCSListAnywhereCachesConfig, token: str
    ) -> Dict[str, Any]:
        return await self._anywhere_cache_request(
            token, "GET", c.bucket, "list_anywhere_caches"
        )

    async def _get_anywhere_cache(
        self, c: GCSGetAnywhereCacheConfig, token: str
    ) -> Dict[str, Any]:
        return await self._anywhere_cache_request(
            token,
            "GET",
            c.bucket,
            "get_anywhere_cache",
            anywhere_cache_id=c.anywhere_cache_id,
        )

    async def _create_anywhere_cache(
        self, c: GCSCreateAnywhereCacheConfig, token: str
    ) -> Dict[str, Any]:
        return await self._anywhere_cache_request(
            token,
            "POST",
            c.bucket,
            "create_anywhere_cache",
            json_body={
                "zone": c.zone,
                "ttl": c.ttl,
                "ingestOnWrite": c.ingest_on_write,
            },
        )

    async def _update_anywhere_cache(
        self, c: GCSUpdateAnywhereCacheConfig, token: str
    ) -> Dict[str, Any]:
        return await self._anywhere_cache_request(
            token,
            "PATCH",
            c.bucket,
            "update_anywhere_cache",
            anywhere_cache_id=c.anywhere_cache_id,
            json_body={"ttl": c.ttl, "ingestOnWrite": c.ingest_on_write},
        )

    async def _disable_anywhere_cache(
        self, c: GCSDisableAnywhereCacheConfig, token: str
    ) -> Dict[str, Any]:
        return await self._anywhere_cache_request(
            token,
            "POST",
            c.bucket,
            "disable_anywhere_cache",
            anywhere_cache_id=c.anywhere_cache_id,
            suffix="/disable",
        )

    async def _pause_anywhere_cache(
        self, c: GCSPauseAnywhereCacheConfig, token: str
    ) -> Dict[str, Any]:
        return await self._anywhere_cache_request(
            token,
            "POST",
            c.bucket,
            "pause_anywhere_cache",
            anywhere_cache_id=c.anywhere_cache_id,
            suffix="/pause",
        )

    async def _resume_anywhere_cache(
        self, c: GCSResumeAnywhereCacheConfig, token: str
    ) -> Dict[str, Any]:
        return await self._anywhere_cache_request(
            token,
            "POST",
            c.bucket,
            "resume_anywhere_cache",
            anywhere_cache_id=c.anywhere_cache_id,
            suffix="/resume",
        )

    async def _get_project_intelligence_config(
        self, c: GCSGetProjectIntelligenceConfig, token: str
    ) -> Dict[str, Any]:
        return await self._intelligence_config_request(
            token,
            "GET",
            "projects",
            c.project_id,
            "get_project_intelligence_config",
        )

    async def _update_project_intelligence_config(
        self, c: GCSUpdateProjectIntelligenceConfig, token: str
    ) -> Dict[str, Any]:
        return await self._intelligence_config_request(
            token,
            "PATCH",
            "projects",
            c.project_id,
            "update_project_intelligence_config",
            params={"updateMask": c.update_mask, "requestId": c.request_id},
            json_body=_parse_json_object(c.intelligence_config_json, "Intelligence Config"),
        )

    async def _get_folder_intelligence_config(
        self, c: GCSGetFolderIntelligenceConfig, token: str
    ) -> Dict[str, Any]:
        return await self._intelligence_config_request(
            token,
            "GET",
            "folders",
            c.folder_id,
            "get_folder_intelligence_config",
        )

    async def _update_folder_intelligence_config(
        self, c: GCSUpdateFolderIntelligenceConfig, token: str
    ) -> Dict[str, Any]:
        return await self._intelligence_config_request(
            token,
            "PATCH",
            "folders",
            c.folder_id,
            "update_folder_intelligence_config",
            params={"updateMask": c.update_mask, "requestId": c.request_id},
            json_body=_parse_json_object(c.intelligence_config_json, "Intelligence Config"),
        )

    async def _get_organization_intelligence_config(
        self, c: GCSGetOrganizationIntelligenceConfig, token: str
    ) -> Dict[str, Any]:
        return await self._intelligence_config_request(
            token,
            "GET",
            "organizations",
            c.organization_id,
            "get_organization_intelligence_config",
        )

    async def _update_organization_intelligence_config(
        self, c: GCSUpdateOrganizationIntelligenceConfig, token: str
    ) -> Dict[str, Any]:
        return await self._intelligence_config_request(
            token,
            "PATCH",
            "organizations",
            c.organization_id,
            "update_organization_intelligence_config",
            params={"updateMask": c.update_mask, "requestId": c.request_id},
            json_body=_parse_json_object(c.intelligence_config_json, "Intelligence Config"),
        )

    # ------------------------------------------------------------------
    # Trigger handler (poll-based)
    # ------------------------------------------------------------------
    async def _poll_new_objects(
        self, c: GCSOnNewObjectConfig, token: str
    ) -> Dict[str, Any]:
        """List objects in a bucket/prefix and emit only those created since the
        last poll. The cursor is the max ``timeCreated`` seen; the first poll
        baselines (records the cursor, emits nothing)."""
        params = {
            "prefix": c.prefix,
            "maxResults": c.max_results,
        }
        result = await _gcs_request(
            token,
            "GET",
            f"{GCS_API_BASE}/b/{_enc(c.bucket)}/o",
            params=params,
            action_name="on_new_object",
        )
        if result.get("status") != "success":
            return result

        items = (result.get("data") or {}).get("items") or []

        def mutator(state):
            # The cursor lives in NODE STATE — config is not persisted across
            # poll runs, so a config-held cursor never advanced (the trigger
            # baselined every tick and never fired).
            is_first_poll = "last_polled_at" not in state
            cursor = state.get("last_polled_at")

            # Newest creation time present in this poll, used to advance the cursor.
            latest = cursor
            for obj in items:
                created = obj.get("timeCreated") if isinstance(obj, dict) else None
                if created and (latest is None or created > latest):
                    latest = created

            if is_first_poll:
                if latest is None:
                    # No object with a timeCreated yet — stay UNBASELINED so the
                    # next non-empty poll baselines instead of flooding.
                    return None, ([], None)
                # Baseline: record the cursor, emit nothing.
                return {"last_polled_at": latest}, ([], latest)

            new_items = [
                obj
                for obj in items
                if isinstance(obj, dict)
                and obj.get("timeCreated")
                and obj["timeCreated"] > cursor
            ]
            if latest != cursor:
                return {"last_polled_at": latest}, (new_items, latest)
            return None, (new_items, latest)  # nothing new → no write

        new_items, latest = await self._update_node_state(
            mutator, skip_result=([], None)
        )

        return {
            "status": "success",
            "operation": "on_new_object",
            "bucket": c.bucket,
            "prefix": c.prefix,
            "items": new_items,
            "new_count": len(new_items),
            "last_polled_at": latest,
            "timing_ms": result.get("timing_ms", {}),
        }
