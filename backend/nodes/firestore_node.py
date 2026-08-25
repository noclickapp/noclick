"""
Google Cloud Firestore automation node.

Provides workflow integration with Cloud Firestore (Firestore REST API v1) for
operations including:
- Documents: get, list, create, update/upsert, delete
- Batch: batch get, batch write
- Queries: run structured query, run aggregation query, list collection IDs
- Transactions: begin, commit, rollback
- Databases: get, list
- Indexes: list composite indexes
- Operations: poll a long-running operation

Authentication: Google OAuth 2.0 Bearer token (scope
`https://www.googleapis.com/auth/datastore`). Firestore has NO static API key
that authorizes data access — a real identity (OAuth) token is mandatory.

API Base URL: https://firestore.googleapis.com/v1/
Documentation: https://docs.cloud.google.com/firestore/docs/reference/rest

Firestore wraps every value in a type tag (e.g. {"stringValue": "x"}). Document
bodies passed to/from this node use that typed `fields` representation; the node
sends/returns it verbatim — it does not translate plain JSON to typed values.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Literal, Union, Annotated, Tuple
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx
import jwt

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.schedule_registration import CronScheduleTriggerMixin
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)

import base64
from nodes.scopes.google_cloud import FIRESTORE_SCOPES
from utils.google_service_account import (
    BoundedTTLTokenCache,
    GOOGLE_SERVICE_ACCOUNT_TOKEN_URL,
    google_service_account_authority_key,
    normalize_google_service_account_private_key,
    require_google_service_account_token_uri,
)
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

FIRESTORE_API_BASE = "https://firestore.googleapis.com/v1"
GOOGLE_TOKEN_URL = GOOGLE_SERVICE_ACCOUNT_TOKEN_URL
FIREBASE_SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"

# Default Firestore database id used by the vast majority of projects.
DEFAULT_DATABASE = "(default)"


def _project_id_from_credential(cred_data: Dict[str, Any]) -> Optional[str]:
    """Extract a GCP/Firebase project ID from a decrypted credential dict.

    For service-account credentials the project_id is stored explicitly.
    For Firebase ID-token credentials the `aud` JWT claim IS the project ID.
    """
    if not cred_data:
        return None
    # Explicit field (SA JSON key and optionally Firebase form field)
    if cred_data.get("project_id"):
        return cred_data["project_id"]
    # Derive from Firebase ID-token JWT payload: aud == project_id
    id_token = cred_data.get("id_token") or ""
    if id_token:
        try:
            parts = id_token.split(".")
            if len(parts) == 3:
                # base64url padding
                padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(padded))
                aud = payload.get("aud")
                if aud:
                    return str(aud)
        except Exception:
            pass
    return None

_FIRESTORE_SERVICE_ACCOUNT_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
)

# Authority-fingerprinted, bounded process-local access-token cache.
_sa_token_cache = BoundedTTLTokenCache()


def _firebase_id_token_is_expired(expires_at: Optional[str]) -> bool:
    """Treat a missing expires_at as expired so tokens without a set expiry are refreshed."""
    if not expires_at:
        return True
    try:
        from nodes.oauth.google_oauth import is_token_expired
        return is_token_expired(expires_at)
    except Exception:
        return True


def _make_firebase_refresh(api_key: str):
    """Return a refresh callable compatible with ensure_fresh_oauth_token (id_token key)."""
    async def _refresh(refresh_token: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{FIREBASE_SECURE_TOKEN_URL}?key={api_key}",
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.status_code >= 400:
                try:
                    err = response.json()
                except Exception:
                    err = response.text
                raise ValueError(f"Firebase token refresh failed: {err}")
            data = response.json()
        id_token = data.get("id_token")
        if not id_token:
            raise ValueError("Firebase token refresh returned no id_token")
        expires_in = int(data.get("expires_in", "3600"))
        return {
            "id_token": id_token,
            "refresh_token": data.get("refresh_token") or refresh_token,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat(),
        }
    return _refresh


# ============================================================================
# Credential Schema (Google OAuth 2.0)
# ============================================================================


class FirestoreOAuthCredential(BaseModel):
    """OAuth credential for Google Cloud Firestore.

    Tokens are obtained via the Google OAuth flow, not entered manually. The
    `datastore` scope grants read/write access to documents, queries, and
    transactions.
    """

    credential_type: Literal["firestore_oauth"] = Field(
        "firestore_oauth", json_schema_extra={"ui:hidden": True}
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
        description="ISO 8601 timestamp when the access token expires",
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
            "x-oauth-scopes": [
                "https://www.googleapis.com/auth/datastore",
            ],
            "x-credential-url": "https://console.cloud.google.com/apis/credentials",
        }
    )


class FirestoreServiceAccountCredential(BaseModel):
    """Service-account credential for server-side Firestore access.

    This path exchanges a locally signed JWT assertion for a Google OAuth 2.0
    access token on each execution. Firestore then authorizes requests with IAM,
    not Security Rules.
    """

    credential_type: Literal["firestore_service_account"] = Field(
        "firestore_service_account", json_schema_extra={"ui:hidden": True}
    )
    client_email: str = Field(
        ...,
        title="Client Email",
        description="The service account client_email from the JSON key",
    )
    private_key: str = Field(
        ...,
        title="Private Key",
        description="The service account private_key PEM block",
        json_schema_extra={"ui:widget": "textarea"},
    )
    private_key_id: Optional[str] = Field(
        None,
        title="Private Key ID",
        description="Optional private_key_id from the JSON key",
    )
    project_id: Optional[str] = Field(
        None,
        title="Project ID",
        description="Optional project_id from the JSON key",
    )
    token_uri: str = Field(
        GOOGLE_TOKEN_URL,
        title="Token URI",
        description="OAuth 2.0 token endpoint for the service account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.cloud.google.com/iam-admin/serviceaccounts",
        }
    )


class FirestoreFirebaseIdTokenCredential(BaseModel):
    """Firebase Authentication ID-token credential.

    Firestore REST accepts Firebase ID tokens and authorizes them with
    Firestore Security Rules. If `refresh_token` + `api_key` are provided, the
    node can renew the ID token automatically through Firebase Auth REST.
    """

    credential_type: Literal["firestore_firebase_id_token"] = Field(
        "firestore_firebase_id_token", json_schema_extra={"ui:hidden": True}
    )
    id_token: str = Field(
        ...,
        title="Firebase ID Token",
        description="A Firebase Authentication ID token (JWT)",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(
        None,
        title="Firebase Refresh Token",
        description="Optional Firebase refresh token for automatic renewal",
        json_schema_extra={"ui:widget": "password"},
    )
    api_key: Optional[str] = Field(
        None,
        title="Firebase Web API Key",
        description="Required to refresh Firebase ID tokens automatically",
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: Optional[str] = Field(
        None,
        title="Token Expiry",
        description="Optional ISO 8601 expiry timestamp for the ID token",
    )
    project_id: Optional[str] = Field(
        None,
        title="Project ID",
        description="Optional Firebase project ID for reference",
    )
    email: Optional[str] = Field(
        None,
        title="Firebase User Email",
        description="Optional email of the authenticated Firebase user",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.firebase.google.com/project/_/settings/general/",
        }
    )


FirestoreCredential = Union[
    FirestoreOAuthCredential,
    FirestoreServiceAccountCredential,
    FirestoreFirebaseIdTokenCredential,
]


# ============================================================================
# Shared project/database fields helper
# ============================================================================


def _project_field() -> Any:
    return Field(
        ...,
        title="Project ID",
        description="Your Google Cloud / Firebase project ID",
        json_schema_extra={"ui:loadValue": True},
    )


def _database_field() -> Any:
    return Field(
        DEFAULT_DATABASE,
        title="Database ID",
        description="Firestore database id. Most projects use the default: (default)",
        json_schema_extra={
            "x-resource-type": "firestore_database",
            "x-dynamic-options": {
                "field_name": "database_id",
                "placeholder": "Select a database...",
                "searchable": True,
                "depends_on": "project_id",
                "allow_custom": True,
                "custom_placeholder": "Or paste database ID",
            },
            "x-resource-type": "firestore_database",
        },
    )


def _collection_path_field(description: str) -> Any:
    """Collection-path field with a live dropdown of top-level collection ids.

    Options come from `documents:listCollectionIds` (root-level collections);
    sub-collection paths (e.g. users/abc/orders) are entered via allow_custom.
    """
    return Field(
        ...,
        title="Collection Path",
        description=description,
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "collection_path",
                "placeholder": "Select a collection...",
                "searchable": True,
                "depends_on": "database_id",
                "allow_custom": True,
                "custom_placeholder": "Or paste collection path",
            },
            "x-resource-type": "firestore_collection",
        },
    )


def _json_textarea_extra(placeholder: Optional[str] = None) -> Dict[str, Any]:
    extra: Dict[str, Any] = {
        "ui:widget": "text_upload_textarea",
        "ui:accept": ".json,.txt,application/json,text/plain",
    }
    if placeholder is not None:
        extra["placeholder"] = placeholder
    return extra


# ============================================================================
# Document Operation Configs
# ============================================================================


class FirestoreGetDocumentConfig(BaseModel):
    """Fetch a single document by its collection and document id."""

    operation: Literal["get_document"] = Field(
        "get_document",
        json_schema_extra={
            "const": "get_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Get Document",
        },
        title="Get Document",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_path: str = _collection_path_field(
        "Collection path, e.g. users or users/abc/orders"
    )
    document_id: str = Field(
        ..., title="Document ID", description="The id of the document to fetch"
    )


class FirestoreListDocumentsConfig(BaseModel):
    """List documents in a collection."""

    operation: Literal["list_documents"] = Field(
        "list_documents",
        json_schema_extra={
            "const": "list_documents",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "List Documents",
        },
        title="List Documents",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_path: str = _collection_path_field(
        "Collection (or sub-collection) path to list, e.g. users"
    )
    page_size: Optional[str] = Field(
        "50", title="Page Size", description="Max documents to return per page"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="nextPageToken from a previous call"
    )
    order_by: Optional[str] = Field(
        None,
        title="Order By",
        description="Field to order by, e.g. createdAt desc",
    )


class FirestoreCreateDocumentConfig(BaseModel):
    """Create a new document in a collection."""

    operation: Literal["create_document"] = Field(
        "create_document",
        json_schema_extra={
            "const": "create_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Create Document",
        },
        title="Create Document",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_path: str = _collection_path_field(
        "Collection to create the document in, e.g. users"
    )
    document_id: Optional[str] = Field(
        None,
        title="Document ID",
        description="Optional id for the new document. Auto-generated if omitted.",
    )
    fields: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Fields",
        description=(
            'Typed Firestore fields object, e.g. '
            '{"name": {"stringValue": "Ada"}, "age": {"integerValue": "30"}}'
        ),
        json_schema_extra=_json_textarea_extra(
            '{"name": {"stringValue": "Ada"}}'
        ),
    )


class FirestoreUpdateDocumentConfig(BaseModel):
    """Update (patch / upsert) fields on a document."""

    operation: Literal["update_document"] = Field(
        "update_document",
        json_schema_extra={
            "const": "update_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Update / Upsert Document",
        },
        title="Update / Upsert Document",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_path: str = _collection_path_field("Collection path, e.g. users")
    document_id: str = Field(
        ..., title="Document ID", description="The id of the document to patch"
    )
    fields: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Fields",
        description='Typed Firestore fields object to set, e.g. {"age": {"integerValue": "31"}}',
        json_schema_extra=_json_textarea_extra(
            '{"age": {"integerValue": "31"}}'
        ),
    )
    update_mask: Optional[str] = Field(
        None,
        title="Update Mask",
        description=(
            "Comma-separated field paths to patch (e.g. age,name). Without a mask "
            "the whole document is replaced (omitted fields are deleted)."
        ),
    )


class FirestoreDeleteDocumentConfig(BaseModel):
    """Delete a document."""

    operation: Literal["delete_document"] = Field(
        "delete_document",
        json_schema_extra={
            "const": "delete_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Delete Document",
        },
        title="Delete Document",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_path: str = _collection_path_field("Collection path, e.g. users")
    document_id: str = Field(
        ..., title="Document ID", description="The id of the document to delete"
    )


# ============================================================================
# Batch Operation Configs
# ============================================================================


class FirestoreBatchGetConfig(BaseModel):
    """Retrieve multiple documents by full name in a single call."""

    operation: Literal["batch_get_documents"] = Field(
        "batch_get_documents",
        json_schema_extra={
            "const": "batch_get_documents",
            "ui:hidden": True,
            "x-category": "Batch",
            "x-is-trigger": False,
            "x-display-name": "Batch Get Documents",
        },
        title="Batch Get Documents",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    document_paths: str = Field(
        ...,
        title="Document Paths",
        description=(
            "Comma-separated document paths relative to the database root, "
            "e.g. users/abc, users/def"
        ),
    )


class FirestoreBatchWriteConfig(BaseModel):
    """Apply a set of writes in one (non-atomic, best-effort) call."""

    operation: Literal["batch_write"] = Field(
        "batch_write",
        json_schema_extra={
            "const": "batch_write",
            "ui:hidden": True,
            "x-category": "Batch",
            "x-is-trigger": False,
            "x-display-name": "Batch Write",
        },
        title="Batch Write",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    writes: Union[str, List[Any]] = Field(
        ...,
        title="Writes",
        description=(
            'JSON array of Firestore Write objects, e.g. '
            '[{"update": {"name": "projects/p/databases/(default)/documents/users/abc", '
            '"fields": {"age": {"integerValue": "30"}}}}]'
        ),
        json_schema_extra=_json_textarea_extra(
            '[{"update": {"name": "...", "fields": {}}}]'
        ),
    )


# ============================================================================
# Query Operation Configs
# ============================================================================


class FirestoreRunQueryConfig(BaseModel):
    """Run a structured query over a collection."""

    operation: Literal["run_query"] = Field(
        "run_query",
        json_schema_extra={
            "const": "run_query",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Run Query",
        },
        title="Run Query",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    parent_path: Optional[str] = Field(
        None,
        title="Parent Path",
        description="Document path the query runs under (blank = database root)",
    )
    structured_query: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Structured Query",
        description=(
            'A Firestore structuredQuery object, e.g. '
            '{"from": [{"collectionId": "users"}], "limit": 10}'
        ),
        json_schema_extra=_json_textarea_extra(
            '{"from": [{"collectionId": "users"}], "limit": 10}'
        ),
    )


class FirestoreRunAggregationQueryConfig(BaseModel):
    """Run a COUNT / SUM / AVG aggregation over a query."""

    operation: Literal["run_aggregation_query"] = Field(
        "run_aggregation_query",
        json_schema_extra={
            "const": "run_aggregation_query",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Run Aggregation Query",
        },
        title="Run Aggregation Query",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    parent_path: Optional[str] = Field(
        None,
        title="Parent Path",
        description="Document path the query runs under (blank = database root)",
    )
    structured_aggregation_query: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Structured Aggregation Query",
        description=(
            'A Firestore structuredAggregationQuery object, e.g. '
            '{"structuredQuery": {"from": [{"collectionId": "users"}]}, '
            '"aggregations": [{"count": {}, "alias": "total"}]}'
        ),
        json_schema_extra=_json_textarea_extra(
            '{"structuredQuery": {...}, "aggregations": [{"count": {}}]}'
        ),
    )


class FirestoreListCollectionIdsConfig(BaseModel):
    """List collection IDs under the database root or a document."""

    operation: Literal["list_collection_ids"] = Field(
        "list_collection_ids",
        json_schema_extra={
            "const": "list_collection_ids",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "List Collection IDs",
        },
        title="List Collection IDs",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    parent_path: Optional[str] = Field(
        None,
        title="Parent Path",
        description="Document path to list collections under (blank = database root)",
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Max collection ids to return"
    )


# ============================================================================
# Transaction Operation Configs
# ============================================================================


class FirestoreBeginTransactionConfig(BaseModel):
    """Start a read/write transaction; returns a transaction token."""

    operation: Literal["begin_transaction"] = Field(
        "begin_transaction",
        json_schema_extra={
            "const": "begin_transaction",
            "ui:hidden": True,
            "x-category": "Transactions",
            "x-is-trigger": False,
            "x-display-name": "Begin Transaction",
        },
        title="Begin Transaction",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()


class FirestoreCommitConfig(BaseModel):
    """Atomically commit a set of writes (optionally within a transaction)."""

    operation: Literal["commit"] = Field(
        "commit",
        json_schema_extra={
            "const": "commit",
            "ui:hidden": True,
            "x-category": "Transactions",
            "x-is-trigger": False,
            "x-display-name": "Commit",
        },
        title="Commit",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    writes: Union[str, List[Any]] = Field(
        ...,
        title="Writes",
        description="JSON array of Firestore Write objects to commit atomically",
        json_schema_extra=_json_textarea_extra(
            '[{"update": {"name": "...", "fields": {}}}]'
        ),
    )
    transaction: Optional[str] = Field(
        None,
        title="Transaction",
        description="Optional transaction token from Begin Transaction",
    )


class FirestoreRollbackConfig(BaseModel):
    """Abort an in-progress transaction."""

    operation: Literal["rollback"] = Field(
        "rollback",
        json_schema_extra={
            "const": "rollback",
            "ui:hidden": True,
            "x-category": "Transactions",
            "x-is-trigger": False,
            "x-display-name": "Rollback",
        },
        title="Rollback",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    transaction: str = Field(
        ..., title="Transaction", description="The transaction token to roll back"
    )


# ============================================================================
# Database / Index / Operation Configs
# ============================================================================


class FirestoreGetDatabaseConfig(BaseModel):
    """Get metadata/config for a database."""

    operation: Literal["get_database"] = Field(
        "get_database",
        json_schema_extra={
            "const": "get_database",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Get Database",
        },
        title="Get Database",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()


class FirestoreListDatabasesConfig(BaseModel):
    """List databases in the project."""

    operation: Literal["list_databases"] = Field(
        "list_databases",
        json_schema_extra={
            "const": "list_databases",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "List Databases",
        },
        title="List Databases",
    )
    project_id: str = _project_field()


class FirestoreListIndexesConfig(BaseModel):
    """List composite indexes for a collection group."""

    operation: Literal["list_indexes"] = Field(
        "list_indexes",
        json_schema_extra={
            "const": "list_indexes",
            "ui:hidden": True,
            "x-category": "Indexes",
            "x-is-trigger": False,
            "x-display-name": "List Indexes",
        },
        title="List Indexes",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_id: str = Field(
        ...,
        title="Collection Group",
        description="Collection group id to list composite indexes for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "collection_id",
                "placeholder": "Select a collection group...",
                "searchable": True,
                "depends_on": "database_id",
                "allow_custom": True,
                "custom_placeholder": "Or paste collection group id",
            },
            "x-resource-type": "firestore_collection",
        },
    )


class FirestoreGetOperationConfig(BaseModel):
    """Poll the status of a long-running operation (export/import/index build)."""

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
    project_id: str = _project_field()
    database_id: str = _database_field()
    operation_id: str = Field(
        ...,
        title="Operation ID",
        description="The id of the long-running operation to poll",
    )


class FirestorePartitionQueryConfig(BaseModel):
    """Partition a structured query for parallel execution."""

    operation: Literal["partition_query"] = Field(
        "partition_query",
        json_schema_extra={
            "const": "partition_query",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Partition Query",
        },
        title="Partition Query",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    parent_path: Optional[str] = Field(
        None,
        title="Parent Path",
        description="Document path the query runs under (blank = database root)",
    )
    structured_query: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Structured Query",
        description="StructuredQuery JSON to partition",
        json_schema_extra=_json_textarea_extra(
            '{"from": [{"collectionId": "users"}]}'
        ),
    )
    partition_count: Optional[str] = Field(
        "10",
        title="Partition Count",
        description="Maximum number of partition cursors to return",
    )


class FirestoreExecutePipelineConfig(BaseModel):
    """Execute a Firestore pipeline query."""

    operation: Literal["execute_pipeline"] = Field(
        "execute_pipeline",
        json_schema_extra={
            "const": "execute_pipeline",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Execute Pipeline",
        },
        title="Execute Pipeline",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    pipeline_request: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Pipeline Request",
        description="ExecutePipeline JSON body",
        json_schema_extra=_json_textarea_extra(
            '{"structuredPipeline": {"stages": []}}'
        ),
    )


class FirestoreListenConfig(BaseModel):
    """Open a Firestore listen stream request."""

    operation: Literal["listen"] = Field(
        "listen",
        json_schema_extra={
            "const": "listen",
            "ui:hidden": True,
            "x-category": "Advanced",
            "x-is-trigger": False,
            "x-display-name": "Listen Stream",
        },
        title="Listen Stream",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    listen_request: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Listen Request",
        description="Listen JSON body",
        json_schema_extra=_json_textarea_extra(
            '{"addTarget": {"documents": {"documents": ["projects/my-proj/databases/(default)/documents/users/a"]}, "targetId": 1}}'
        ),
    )


class FirestoreWriteConfig(BaseModel):
    """Open a Firestore write stream request."""

    operation: Literal["write"] = Field(
        "write",
        json_schema_extra={
            "const": "write",
            "ui:hidden": True,
            "x-category": "Advanced",
            "x-is-trigger": False,
            "x-display-name": "Write Stream",
        },
        title="Write Stream",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    write_request: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Write Request",
        description="Write JSON body",
        json_schema_extra=_json_textarea_extra(
            '{"streamId": "stream-1", "writes": []}'
        ),
    )


class FirestoreCreateDatabaseConfig(BaseModel):
    """Create a Firestore database."""

    operation: Literal["create_database"] = Field(
        "create_database",
        json_schema_extra={
            "const": "create_database",
            "x-creates-resource": True,
            "x-resource-type": "firestore_database",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Create Database",
        },
        title="Create Database",
    )
    project_id: str = _project_field()
    new_database_id: str = Field(
        ...,
        title="New Database ID",
        description='Database ID to create, e.g. "analytics" or "(default)"',
    )
    database: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Database",
        description="Database JSON body",
        json_schema_extra=_json_textarea_extra(
            '{"locationId": "us-central", "type": "FIRESTORE_NATIVE"}'
        ),
    )


class FirestoreCloneDatabaseConfig(BaseModel):
    """Clone an existing Firestore database from PITR."""

    operation: Literal["clone_database"] = Field(
        "clone_database",
        json_schema_extra={
            "const": "clone_database",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Clone Database",
        },
        title="Clone Database",
    )
    project_id: str = _project_field()
    new_database_id: str = Field(..., title="New Database ID")
    clone_request: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Clone Request",
        description="CloneDatabase JSON body without the top-level databaseId if desired",
        json_schema_extra=_json_textarea_extra(
            '{"pitrSnapshot": {"sourceDatabase": "projects/my-proj/databases/(default)", "snapshotTime": "2026-06-20T00:00:00Z"}}'
        ),
    )


class FirestoreRestoreDatabaseConfig(BaseModel):
    """Restore a Firestore database from a backup."""

    operation: Literal["restore_database"] = Field(
        "restore_database",
        json_schema_extra={
            "const": "restore_database",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Restore Database",
        },
        title="Restore Database",
    )
    project_id: str = _project_field()
    new_database_id: str = Field(..., title="New Database ID")
    restore_request: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Restore Request",
        description="RestoreDatabase JSON body without the top-level databaseId if desired",
        json_schema_extra=_json_textarea_extra(
            '{"backup": "projects/my-proj/locations/us/backups/backup-1"}'
        ),
    )


class FirestoreUpdateDatabaseConfig(BaseModel):
    """Patch database metadata/configuration."""

    operation: Literal["update_database"] = Field(
        "update_database",
        json_schema_extra={
            "const": "update_database",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Update Database",
        },
        title="Update Database",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    database: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Database",
        description="Database JSON body to patch",
        json_schema_extra=_json_textarea_extra(
            '{"type": "FIRESTORE_NATIVE"}'
        ),
    )
    update_mask: str = Field(
        ...,
        title="Update Mask",
        description='Comma-separated database field paths, e.g. "deleteProtectionState"',
    )


class FirestoreDeleteDatabaseConfig(BaseModel):
    """Delete a Firestore database."""

    operation: Literal["delete_database"] = Field(
        "delete_database",
        json_schema_extra={
            "const": "delete_database",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Delete Database",
        },
        title="Delete Database",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    etag: Optional[str] = Field(
        None,
        title="ETag",
        description="Optional etag precondition for delete",
    )


class FirestoreCreateBackupScheduleConfig(BaseModel):
    """Create a backup schedule for a Firestore database."""

    operation: Literal["create_backup_schedule"] = Field(
        "create_backup_schedule",
        json_schema_extra={
            "const": "create_backup_schedule",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "Create Backup Schedule",
        },
        title="Create Backup Schedule",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    backup_schedule: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Backup Schedule",
        description="BackupSchedule JSON body",
        json_schema_extra=_json_textarea_extra(
            '{"retention": "604800s", "dailyRecurrence": {}}'
        ),
    )


class FirestoreGetBackupScheduleConfig(BaseModel):
    """Get one backup schedule."""

    operation: Literal["get_backup_schedule"] = Field(
        "get_backup_schedule",
        json_schema_extra={
            "const": "get_backup_schedule",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "Get Backup Schedule",
        },
        title="Get Backup Schedule",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    backup_schedule_id: str = Field(..., title="Backup Schedule ID")


class FirestoreListBackupSchedulesConfig(BaseModel):
    """List backup schedules for a Firestore database."""

    operation: Literal["list_backup_schedules"] = Field(
        "list_backup_schedules",
        json_schema_extra={
            "const": "list_backup_schedules",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "List Backup Schedules",
        },
        title="List Backup Schedules",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    page_size: Optional[str] = Field("50", title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


class FirestoreUpdateBackupScheduleConfig(BaseModel):
    """Update a backup schedule."""

    operation: Literal["update_backup_schedule"] = Field(
        "update_backup_schedule",
        json_schema_extra={
            "const": "update_backup_schedule",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "Update Backup Schedule",
        },
        title="Update Backup Schedule",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    backup_schedule_id: str = Field(..., title="Backup Schedule ID")
    backup_schedule: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Backup Schedule",
        description="BackupSchedule JSON body to patch",
        json_schema_extra=_json_textarea_extra(
            '{"retention": "1209600s"}'
        ),
    )
    update_mask: str = Field(
        ...,
        title="Update Mask",
        description='Comma-separated backup schedule field paths, e.g. "retention"',
    )


class FirestoreDeleteBackupScheduleConfig(BaseModel):
    """Delete a backup schedule."""

    operation: Literal["delete_backup_schedule"] = Field(
        "delete_backup_schedule",
        json_schema_extra={
            "const": "delete_backup_schedule",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "Delete Backup Schedule",
        },
        title="Delete Backup Schedule",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    backup_schedule_id: str = Field(..., title="Backup Schedule ID")


class FirestoreExportDocumentsConfig(BaseModel):
    """Export documents to Cloud Storage."""

    operation: Literal["export_documents"] = Field(
        "export_documents",
        json_schema_extra={
            "const": "export_documents",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Export Documents",
        },
        title="Export Documents",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    output_uri_prefix: str = Field(
        ...,
        title="Output GCS URI Prefix",
        description="Cloud Storage URI prefix, e.g. gs://bucket/firestore-export",
    )
    collection_ids: Optional[str] = Field(
        None,
        title="Collection IDs",
        description="Optional comma-separated collection IDs to export",
    )
    namespace_ids: Optional[str] = Field(
        None,
        title="Namespace IDs",
        description="Optional comma-separated namespace IDs",
    )


class FirestoreImportDocumentsConfig(BaseModel):
    """Import documents from Cloud Storage."""

    operation: Literal["import_documents"] = Field(
        "import_documents",
        json_schema_extra={
            "const": "import_documents",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Import Documents",
        },
        title="Import Documents",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    input_uri_prefix: str = Field(
        ...,
        title="Input GCS URI Prefix",
        description="Cloud Storage URI prefix, e.g. gs://bucket/firestore-export",
    )
    collection_ids: Optional[str] = Field(
        None,
        title="Collection IDs",
        description="Optional comma-separated collection IDs to import",
    )
    namespace_ids: Optional[str] = Field(
        None,
        title="Namespace IDs",
        description="Optional comma-separated namespace IDs",
    )


class FirestoreBulkDeleteDocumentsConfig(BaseModel):
    """Bulk delete collection groups in the background."""

    operation: Literal["bulk_delete_documents"] = Field(
        "bulk_delete_documents",
        json_schema_extra={
            "const": "bulk_delete_documents",
            "ui:hidden": True,
            "x-category": "Databases",
            "x-is-trigger": False,
            "x-display-name": "Bulk Delete Documents",
        },
        title="Bulk Delete Documents",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_ids: Optional[str] = Field(
        None,
        title="Collection Group IDs",
        description="Optional comma-separated collection group IDs",
    )
    namespace_ids: Optional[str] = Field(
        None,
        title="Namespace IDs",
        description="Optional comma-separated namespace IDs",
    )


class FirestoreGetIndexConfig(BaseModel):
    """Get a composite index definition."""

    operation: Literal["get_index"] = Field(
        "get_index",
        json_schema_extra={
            "const": "get_index",
            "ui:hidden": True,
            "x-category": "Indexes",
            "x-is-trigger": False,
            "x-display-name": "Get Index",
        },
        title="Get Index",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_id: str = Field(..., title="Collection Group")
    index_id: str = Field(..., title="Index ID")


class FirestoreDeleteIndexConfig(BaseModel):
    """Delete a composite index."""

    operation: Literal["delete_index"] = Field(
        "delete_index",
        json_schema_extra={
            "const": "delete_index",
            "ui:hidden": True,
            "x-category": "Indexes",
            "x-is-trigger": False,
            "x-display-name": "Delete Index",
        },
        title="Delete Index",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_id: str = Field(..., title="Collection Group")
    index_id: str = Field(..., title="Index ID")


class FirestoreCreateUserCredsConfig(BaseModel):
    """Create a database user creds resource."""

    operation: Literal["create_user_creds"] = Field(
        "create_user_creds",
        json_schema_extra={
            "const": "create_user_creds",
            "ui:hidden": True,
            "x-category": "User Creds",
            "x-is-trigger": False,
            "x-display-name": "Create User Creds",
        },
        title="Create User Creds",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    user_creds_id: str = Field(..., title="User Creds ID")
    user_creds: Union[str, Dict[str, Any]] = Field(
        ...,
        title="User Creds",
        description="UserCreds JSON body",
        json_schema_extra=_json_textarea_extra(
            '{"userName": "app_user", "userSecret": "secret-value"}'
        ),
    )


class FirestoreGetUserCredsConfig(BaseModel):
    """Get a database user creds resource."""

    operation: Literal["get_user_creds"] = Field(
        "get_user_creds",
        json_schema_extra={
            "const": "get_user_creds",
            "ui:hidden": True,
            "x-category": "User Creds",
            "x-is-trigger": False,
            "x-display-name": "Get User Creds",
        },
        title="Get User Creds",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    user_creds_id: str = Field(..., title="User Creds ID")


class FirestoreListUserCredsConfig(BaseModel):
    """List user creds for a database."""

    operation: Literal["list_user_creds"] = Field(
        "list_user_creds",
        json_schema_extra={
            "const": "list_user_creds",
            "ui:hidden": True,
            "x-category": "User Creds",
            "x-is-trigger": False,
            "x-display-name": "List User Creds",
        },
        title="List User Creds",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()


class FirestoreEnableUserCredsConfig(BaseModel):
    """Enable a user creds resource."""

    operation: Literal["enable_user_creds"] = Field(
        "enable_user_creds",
        json_schema_extra={
            "const": "enable_user_creds",
            "ui:hidden": True,
            "x-category": "User Creds",
            "x-is-trigger": False,
            "x-display-name": "Enable User Creds",
        },
        title="Enable User Creds",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    user_creds_id: str = Field(..., title="User Creds ID")


class FirestoreDisableUserCredsConfig(BaseModel):
    """Disable a user creds resource."""

    operation: Literal["disable_user_creds"] = Field(
        "disable_user_creds",
        json_schema_extra={
            "const": "disable_user_creds",
            "ui:hidden": True,
            "x-category": "User Creds",
            "x-is-trigger": False,
            "x-display-name": "Disable User Creds",
        },
        title="Disable User Creds",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    user_creds_id: str = Field(..., title="User Creds ID")


class FirestoreDeleteUserCredsConfig(BaseModel):
    """Delete a user creds resource."""

    operation: Literal["delete_user_creds"] = Field(
        "delete_user_creds",
        json_schema_extra={
            "const": "delete_user_creds",
            "ui:hidden": True,
            "x-category": "User Creds",
            "x-is-trigger": False,
            "x-display-name": "Delete User Creds",
        },
        title="Delete User Creds",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    user_creds_id: str = Field(..., title="User Creds ID")


class FirestoreResetUserCredsPasswordConfig(BaseModel):
    """Reset the password of a user creds resource."""

    operation: Literal["reset_user_creds_password"] = Field(
        "reset_user_creds_password",
        json_schema_extra={
            "const": "reset_user_creds_password",
            "ui:hidden": True,
            "x-category": "User Creds",
            "x-is-trigger": False,
            "x-display-name": "Reset User Creds Password",
        },
        title="Reset User Creds Password",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    user_creds_id: str = Field(..., title="User Creds ID")


class FirestoreListFieldsConfig(BaseModel):
    """List field index / TTL configurations."""

    operation: Literal["list_fields"] = Field(
        "list_fields",
        json_schema_extra={
            "const": "list_fields",
            "ui:hidden": True,
            "x-category": "Indexes",
            "x-is-trigger": False,
            "x-display-name": "List Fields",
        },
        title="List Fields",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_id: str = Field(
        "__default__",
        title="Collection Group",
        description='Collection group id, or "__default__" for default field settings',
    )
    filter: Optional[str] = Field(
        "indexConfig.usesAncestorConfig:false",
        title="Filter",
        description='Optional filter, e.g. "indexConfig.usesAncestorConfig:false" or "ttlConfig:*"',
    )
    page_size: Optional[str] = Field("50", title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


class FirestoreGetFieldConfig(BaseModel):
    """Get one field configuration."""

    operation: Literal["get_field"] = Field(
        "get_field",
        json_schema_extra={
            "const": "get_field",
            "ui:hidden": True,
            "x-category": "Indexes",
            "x-is-trigger": False,
            "x-display-name": "Get Field",
        },
        title="Get Field",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_id: str = Field(..., title="Collection Group")
    field_path: str = Field(
        ...,
        title="Field Path",
        description='Field path, e.g. "age" or "*" for the default field entry',
    )


class FirestoreUpdateFieldConfig(BaseModel):
    """Patch a field configuration."""

    operation: Literal["update_field"] = Field(
        "update_field",
        json_schema_extra={
            "const": "update_field",
            "ui:hidden": True,
            "x-category": "Indexes",
            "x-is-trigger": False,
            "x-display-name": "Update Field",
        },
        title="Update Field",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_id: str = Field(..., title="Collection Group")
    field_path: str = Field(..., title="Field Path")
    field: Union[str, Dict[str, Any]] = Field(
        ...,
        title="Field Config",
        description="Field JSON body to patch",
        json_schema_extra=_json_textarea_extra(
            '{"indexConfig": {"indexes": []}}'
        ),
    )
    update_mask: str = Field(
        ...,
        title="Update Mask",
        description='Comma-separated field mask, e.g. "indexConfig" or "ttlConfig"',
    )


class FirestoreListOperationsConfig(BaseModel):
    """List long-running operations."""

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
    project_id: str = _project_field()
    database_id: str = _database_field()
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description='Optional operation filter string, e.g. "done=false"',
    )
    page_size: Optional[str] = Field("50", title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


class FirestoreCancelOperationConfig(BaseModel):
    """Request cancellation for a long-running operation."""

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
    project_id: str = _project_field()
    database_id: str = _database_field()
    operation_id: str = Field(..., title="Operation ID")


class FirestoreDeleteOperationConfig(BaseModel):
    """Delete interest in a long-running operation result."""

    operation: Literal["delete_operation"] = Field(
        "delete_operation",
        json_schema_extra={
            "const": "delete_operation",
            "ui:hidden": True,
            "x-category": "Operations",
            "x-is-trigger": False,
            "x-display-name": "Delete Operation",
        },
        title="Delete Operation",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    operation_id: str = Field(..., title="Operation ID")


class FirestoreGetLocationConfig(BaseModel):
    """Get one Firestore-supported location."""

    operation: Literal["get_location"] = Field(
        "get_location",
        json_schema_extra={
            "const": "get_location",
            "ui:hidden": True,
            "x-category": "Locations",
            "x-is-trigger": False,
            "x-display-name": "Get Location",
        },
        title="Get Location",
    )
    project_id: str = _project_field()
    location_id: str = Field(..., title="Location ID")


class FirestoreListLocationsConfig(BaseModel):
    """List Firestore-supported locations."""

    operation: Literal["list_locations"] = Field(
        "list_locations",
        json_schema_extra={
            "const": "list_locations",
            "ui:hidden": True,
            "x-category": "Locations",
            "x-is-trigger": False,
            "x-display-name": "List Locations",
        },
        title="List Locations",
    )
    project_id: str = _project_field()
    filter: Optional[str] = Field(None, title="Filter")
    page_size: Optional[str] = Field("50", title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


class FirestoreGetBackupConfig(BaseModel):
    """Get one Firestore backup."""

    operation: Literal["get_backup"] = Field(
        "get_backup",
        json_schema_extra={
            "const": "get_backup",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "Get Backup",
        },
        title="Get Backup",
    )
    project_id: str = _project_field()
    location_id: str = Field(..., title="Location ID")
    backup_id: str = Field(..., title="Backup ID")


class FirestoreListBackupsConfig(BaseModel):
    """List Firestore backups in a location."""

    operation: Literal["list_backups"] = Field(
        "list_backups",
        json_schema_extra={
            "const": "list_backups",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "List Backups",
        },
        title="List Backups",
    )
    project_id: str = _project_field()
    location_id: str = Field(..., title="Location ID")
    page_size: Optional[str] = Field("50", title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")
    filter: Optional[str] = Field(None, title="Filter")


class FirestoreDeleteBackupConfig(BaseModel):
    """Delete a Firestore backup."""

    operation: Literal["delete_backup"] = Field(
        "delete_backup",
        json_schema_extra={
            "const": "delete_backup",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "Delete Backup",
        },
        title="Delete Backup",
    )
    project_id: str = _project_field()
    location_id: str = Field(..., title="Location ID")
    backup_id: str = Field(..., title="Backup ID")


class FirestoreCustomApiCallConfig(BaseModel):
    """Raw Firestore REST call escape hatch for newly added or niche endpoints."""

    operation: Literal["custom_api_call"] = Field(
        "custom_api_call",
        json_schema_extra={
            "const": "custom_api_call",
            "ui:hidden": True,
            "x-category": "Advanced",
            "x-is-trigger": False,
            "x-display-name": "Custom API Call",
        },
        title="Custom API Call",
    )
    method: Literal["GET", "POST", "PATCH", "DELETE"] = Field(
        "GET",
        title="HTTP Method",
    )
    path: str = Field(
        ...,
        title="API Path",
        description='Path relative to https://firestore.googleapis.com/v1/, e.g. "projects/my-proj/databases/(default)"',
    )
    query_params: Optional[Union[str, Dict[str, Any]]] = Field(
        None,
        title="Query Params",
        description="Optional JSON object of query params",
        json_schema_extra=_json_textarea_extra(),
    )
    body: Optional[Union[str, Dict[str, Any], List[Any]]] = Field(
        None,
        title="JSON Body",
        description="Optional JSON request body",
        json_schema_extra=_json_textarea_extra(),
    )


# ============================================================================
# Trigger Operation Config (poll-based)
# ============================================================================


class FirestoreOnDocumentChangedConfig(BaseModel):
    """Trigger: poll a collection for documents created/updated since the last check.

    Firestore exposes no outbound webhooks over REST, so this trigger polls on a
    schedule. Each tick runs a structured query (`runQuery`) ordered by the
    document's update time and emits only documents whose `updateTime` is newer
    than the stored cursor (`last_polled_at`), then advances the cursor.
    """

    operation: Literal["on_document_changed"] = Field(
        "on_document_changed",
        json_schema_extra={
            "const": "on_document_changed",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Document Created/Updated",
        },
        title="On Document Created/Updated",
    )
    project_id: str = _project_field()
    database_id: str = _database_field()
    collection_path: str = _collection_path_field(
        "Collection to watch for new/updated documents, e.g. users"
    )
    page_size: Optional[str] = Field(
        "50",
        title="Max Documents",
        description="Max documents to fetch per check (most recent first)",
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to poll the collection for changes",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    # Hidden cursor: highest document updateTime seen so far (ISO 8601 string).
    last_polled_at: Optional[str] = Field(
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


FirestoreConfig = Annotated[
    Union[
        FirestoreGetDocumentConfig,
        FirestoreListDocumentsConfig,
        FirestoreCreateDocumentConfig,
        FirestoreUpdateDocumentConfig,
        FirestoreDeleteDocumentConfig,
        FirestoreBatchGetConfig,
        FirestoreBatchWriteConfig,
        FirestoreRunQueryConfig,
        FirestoreRunAggregationQueryConfig,
        FirestoreListCollectionIdsConfig,
        FirestoreBeginTransactionConfig,
        FirestoreCommitConfig,
        FirestoreRollbackConfig,
        FirestoreExecutePipelineConfig,
        FirestoreListenConfig,
        FirestoreWriteConfig,
        FirestoreGetDatabaseConfig,
        FirestoreListDatabasesConfig,
        FirestoreCreateDatabaseConfig,
        FirestoreCloneDatabaseConfig,
        FirestoreRestoreDatabaseConfig,
        FirestoreListIndexesConfig,
        FirestoreGetOperationConfig,
        FirestorePartitionQueryConfig,
        FirestoreUpdateDatabaseConfig,
        FirestoreDeleteDatabaseConfig,
        FirestoreCreateBackupScheduleConfig,
        FirestoreGetBackupScheduleConfig,
        FirestoreListBackupSchedulesConfig,
        FirestoreUpdateBackupScheduleConfig,
        FirestoreDeleteBackupScheduleConfig,
        FirestoreExportDocumentsConfig,
        FirestoreImportDocumentsConfig,
        FirestoreBulkDeleteDocumentsConfig,
        FirestoreGetIndexConfig,
        FirestoreDeleteIndexConfig,
        FirestoreCreateUserCredsConfig,
        FirestoreGetUserCredsConfig,
        FirestoreListUserCredsConfig,
        FirestoreEnableUserCredsConfig,
        FirestoreDisableUserCredsConfig,
        FirestoreDeleteUserCredsConfig,
        FirestoreResetUserCredsPasswordConfig,
        FirestoreListFieldsConfig,
        FirestoreGetFieldConfig,
        FirestoreUpdateFieldConfig,
        FirestoreListOperationsConfig,
        FirestoreCancelOperationConfig,
        FirestoreDeleteOperationConfig,
        FirestoreGetLocationConfig,
        FirestoreListLocationsConfig,
        FirestoreGetBackupConfig,
        FirestoreListBackupsConfig,
        FirestoreDeleteBackupConfig,
        FirestoreCustomApiCallConfig,
        FirestoreOnDocumentChangedConfig,
    ],
    Discriminator("operation"),
]


class FirestoreNodeConfig(NodeConfig[FirestoreConfig, FirestoreCredential]):
    """Full configuration for the Firestore node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _db_root(project_id: str, database_id: str) -> str:
    """Build the `projects/.../databases/.../documents` prefix."""
    return f"projects/{project_id}/databases/{database_id}/documents"


def _parse_json(value: Union[str, Dict[str, Any], List[Any]], field_name: str) -> Any:
    """Parse a field that may arrive as a JSON string or an already-parsed object."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {field_name}: {e}")
    return value


def _comma_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def _split_collection_path(collection_path: str) -> Tuple[str, Optional[str]]:
    """Split `users/abc/orders` into (`orders`, `users/abc`).

    Firestore collection paths must end in a collection id. If a document path
    prefix is present, it becomes the parent for listDocuments / runQuery.
    """
    parts = [p for p in collection_path.strip("/").split("/") if p]
    if not parts:
        raise ValueError("collection_path is required")
    collection_id = parts[-1]
    parent_path = "/".join(parts[:-1]) or None
    return collection_id, parent_path


async def _exchange_service_account_access_token(
    credentials: FirestoreServiceAccountCredential,
) -> str:
    token_uri = require_google_service_account_token_uri(credentials.token_uri)
    private_key = normalize_google_service_account_private_key(credentials.private_key)
    cache_key = google_service_account_authority_key(
        private_key=private_key,
        client_email=credentials.client_email,
        token_uri=token_uri,
        scopes=_FIRESTORE_SERVICE_ACCOUNT_SCOPES,
        project_id=credentials.project_id,
        private_key_id=credentials.private_key_id,
    )
    now = time.time()
    cached = _sa_token_cache.get(cache_key, now=now)
    if cached is not None:
        return cached

    issued_at = int(now)
    claims = {
        "iss": credentials.client_email,
        "scope": " ".join(_FIRESTORE_SERVICE_ACCOUNT_SCOPES),
        "aud": token_uri,
        "iat": issued_at,
        "exp": issued_at + 3600,
    }
    headers = {"alg": "RS256", "typ": "JWT"}
    if credentials.private_key_id:
        headers["kid"] = credentials.private_key_id
    assertion = jwt.encode(claims, private_key, algorithm="RS256", headers=headers)

    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(
            token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise ValueError(f"Service account token exchange failed: {err}")
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise ValueError("Service account token exchange returned no access_token")
        _sa_token_cache.put(
            cache_key, token, expires_at=issued_at + 3600, now=now
        )
        return token



async def _firestore_request(
    access_token: str,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Firestore REST request and return a structured result.

    `path` is relative to FIRESTORE_API_BASE (no leading slash needed).
    """
    url = f"{FIRESTORE_API_BASE}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    error_obj = err.get("error", {}) if isinstance(err, dict) else {}
                    message = (
                        error_obj.get("message")
                        if isinstance(error_obj, dict)
                        else str(err)
                    ) or response.text
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[FirestoreNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204 or not response.content:
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
            logger.error(f"[FirestoreNode] Request failed ({action_name}): {msg}")
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


class FirestoreNode(CronScheduleTriggerMixin, WorkflowNode):
    """Google Cloud Firestore automation node."""

    schedule_trigger_operations = ("on_document_changed",)
    schedule_source = "firestore_trigger"

    edit_examples = [
        "Get a user document from the users collection",
        "List the documents in a collection",
        "Create a new document with typed fields",
        "Run a structured query over a collection",
        "Count documents with an aggregation query",
    ]

    scope_registry = FIRESTORE_SCOPES

    @classmethod
    def get_config_model(cls):
        return FirestoreNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Firestore trigger is poll-based: the scheduled webhook is a wake-up
        signal, not data. Return None so execute() runs and polls Firestore."""
        if config.get("operation") == "on_document_changed":
            return None
        return payload

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Firestore-specific field loads (project_id auto-fill); webhook +
        schedule registration delegates to the family loader
        (CronScheduleTriggerMixin → reconcile_node)."""
        if field_name == "project_id":
            # Preserve existing value; only auto-fill when empty.
            existing = (context or {}).get("project_id") or ""
            if existing:
                return {"value": existing}
            # Extract project_id from credential (SA explicit field or Firebase JWT aud claim).
            if credential_ids:
                from utils.credential_loader import load_credential
                for cred_id in credential_ids.values():
                    if not cred_id:
                        continue
                    try:
                        cred_data = await load_credential(pool, user_id, str(cred_id))
                    except Exception:
                        continue
                    extracted = _project_id_from_credential(cred_data)
                    if extracted:
                        return {"value": extracted}
            return {"value": ""}

        return await super().load_field_value(
            field_name, user_id, workflow_id, node_id, pool,
            context=context, credential_ids=credential_ids,
        )

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring credential at load time (dropdowns, trigger registration)."""
        ctype = (credential_data or {}).get("credential_type")
        if ctype == "firestore_oauth":
            from nodes.core.oauth_refresh import freshen_oauth_credential
            from nodes.oauth.google_oauth import refresh_access_token

            return await freshen_oauth_credential(
                credential_data,
                pool=pool,
                user_id=user_id,
                credential_id=credential_id,
                refresh=refresh_access_token,
                provider="google",
            )
        if ctype == "firestore_firebase_id_token":
            api_key = (credential_data or {}).get("api_key")
            if not api_key or not (credential_data or {}).get("refresh_token"):
                return credential_data  # no auto-refresh possible without api_key+refresh_token
            from nodes.core.oauth_refresh import freshen_oauth_credential

            return await freshen_oauth_credential(
                credential_data,
                pool=pool,
                user_id=user_id,
                credential_id=credential_id,
                refresh=_make_firebase_refresh(api_key),
                is_expired=_firebase_id_token_is_expired,
                access_token_key="id_token",
                refresh_token_key="refresh_token",
                expires_at_key="expires_at",
                provider="firebase",
            )
        # Service account: no per-request token to freshen (derived from private key).
        return credential_data

    # ------------------------------------------------------------------
    # Dynamic options (databases + collections)
    # ------------------------------------------------------------------
    @classmethod
    async def _get_token_for_dynamic_options(
        cls, credential_data: Dict[str, Any]
    ) -> Optional[str]:
        credential_type = (credential_data or {}).get("credential_type")
        if credential_type == "firestore_service_account":
            return await _exchange_service_account_access_token(
                FirestoreServiceAccountCredential.model_validate(credential_data)
            )
        if credential_type == "firestore_firebase_id_token":
            # freshen_credential refreshes and persists at load time; just use it.
            return (credential_data or {}).get("id_token")
        return (credential_data or {}).get("access_token")

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic options for the database / collection pickers.

        - `database_id`: lists databases in the project (`project_id` from context).
        - `collection_path` / `collection_id`: lists root-level collection ids in
          the database (`project_id` + `database_id` from context).
        """
        empty = {"options": [], "next_page_token": None}
        access_token = await cls._get_token_for_dynamic_options(credential_data)
        ctx = context or {}
        if not access_token:
            return empty

        if field_name == "database_id":
            return await cls._list_database_options(access_token, ctx, search)
        if field_name in ("collection_path", "collection_id"):
            return await cls._list_collection_options(access_token, ctx, search)
        return empty

    @classmethod
    async def _list_database_options(
        cls, access_token: str, ctx: Dict[str, Any], search: Optional[str]
    ) -> Dict[str, Any]:
        project_id = ctx.get("project_id")
        if not project_id:
            return {"options": [], "next_page_token": None}

        result = await _firestore_request(
            access_token,
            "GET",
            f"projects/{project_id}/databases",
            action_name="list_databases",
        )
        if result.get("status") != "success":
            return {"options": [], "next_page_token": None}

        databases = (result.get("data") or {}).get("databases") or []
        options = []
        for db in databases:
            if not isinstance(db, dict):
                continue
            # name looks like projects/{p}/databases/{db_id}
            name = db.get("name") or ""
            db_id = name.rsplit("/", 1)[-1] if name else None
            if db_id:
                options.append({"label": db_id, "value": db_id})
        return {
            "options": filter_options_by_search(options, normalize_search(search)),
            "next_page_token": None,
        }

    @classmethod
    async def _list_collection_options(
        cls, access_token: str, ctx: Dict[str, Any], search: Optional[str]
    ) -> Dict[str, Any]:
        project_id = ctx.get("project_id")
        if not project_id:
            return {"options": [], "next_page_token": None}
        database_id = ctx.get("database_id") or DEFAULT_DATABASE

        root = _db_root(project_id, database_id)
        result = await _firestore_request(
            access_token,
            "POST",
            f"{root}:listCollectionIds",
            json_body={"pageSize": 300},
            action_name="list_collection_ids",
        )
        if result.get("status") != "success":
            return {"options": [], "next_page_token": None}

        collection_ids = (result.get("data") or {}).get("collectionIds") or []
        options = [
            {"label": cid, "value": cid}
            for cid in collection_ids
            if isinstance(cid, str) and cid
        ]
        return {
            "options": filter_options_by_search(options, normalize_search(search)),
            "next_page_token": None,
        }

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------
    async def _ensure_fresh_token(self, credentials: FirestoreCredential) -> str:
        """Return a valid bearer token for the configured Firestore auth mode."""
        if isinstance(credentials, FirestoreServiceAccountCredential):
            return await _exchange_service_account_access_token(credentials)

        if isinstance(credentials, FirestoreFirebaseIdTokenCredential):
            if not credentials.refresh_token or not credentials.api_key:
                # No auto-refresh possible — return existing token as-is.
                return credentials.id_token
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            
            cred_dict = credentials.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=_make_firebase_refresh(credentials.api_key),
                is_expired=_firebase_id_token_is_expired,
                access_token_key="id_token",
                refresh_token_key="refresh_token",
                expires_at_key="expires_at",
                provider="firebase",
                caller_path="execute",
            )
            credentials.id_token = cred_dict["id_token"]
            credentials.expires_at = cred_dict.get("expires_at")
            if cred_dict.get("refresh_token"):
                credentials.refresh_token = cred_dict["refresh_token"]
            return token

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
            caller_path="execute",
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
        if not config or not isinstance(config, FirestoreNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect a Google account with Firestore access."
            )

        access_token = await self._ensure_fresh_token(credentials)

        handlers = {
            "get_document": self._get_document,
            "list_documents": self._list_documents,
            "create_document": self._create_document,
            "update_document": self._update_document,
            "delete_document": self._delete_document,
            "batch_get_documents": self._batch_get_documents,
            "batch_write": self._batch_write,
            "run_query": self._run_query,
            "run_aggregation_query": self._run_aggregation_query,
            "partition_query": self._partition_query,
            "execute_pipeline": self._execute_pipeline,
            "listen": self._listen,
            "write": self._write,
            "list_collection_ids": self._list_collection_ids,
            "begin_transaction": self._begin_transaction,
            "commit": self._commit,
            "rollback": self._rollback,
            "get_database": self._get_database,
            "list_databases": self._list_databases,
            "create_database": self._create_database,
            "clone_database": self._clone_database,
            "restore_database": self._restore_database,
            "update_database": self._update_database,
            "delete_database": self._delete_database,
            "create_backup_schedule": self._create_backup_schedule,
            "get_backup_schedule": self._get_backup_schedule,
            "list_backup_schedules": self._list_backup_schedules,
            "update_backup_schedule": self._update_backup_schedule,
            "delete_backup_schedule": self._delete_backup_schedule,
            "export_documents": self._export_documents,
            "import_documents": self._import_documents,
            "bulk_delete_documents": self._bulk_delete_documents,
            "list_indexes": self._list_indexes,
            "get_index": self._get_index,
            "delete_index": self._delete_index,
            "create_user_creds": self._create_user_creds,
            "get_user_creds": self._get_user_creds,
            "list_user_creds": self._list_user_creds,
            "enable_user_creds": self._enable_user_creds,
            "disable_user_creds": self._disable_user_creds,
            "delete_user_creds": self._delete_user_creds,
            "reset_user_creds_password": self._reset_user_creds_password,
            "list_fields": self._list_fields,
            "get_field": self._get_field,
            "update_field": self._update_field,
            "get_operation": self._get_operation,
            "list_operations": self._list_operations,
            "cancel_operation": self._cancel_operation,
            "delete_operation": self._delete_operation,
            "get_location": self._get_location,
            "list_locations": self._list_locations,
            "get_backup": self._get_backup,
            "list_backups": self._list_backups,
            "delete_backup": self._delete_backup,
            "custom_api_call": self._custom_api_call,
            "on_document_changed": self._poll_document_changes,
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

    # ------------------------------------------------------------------
    # Document handlers
    # ------------------------------------------------------------------
    async def _get_document(
        self, c: FirestoreGetDocumentConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        path = f"{root}/{c.collection_path.strip('/')}/{c.document_id}"
        return await _firestore_request(token, "GET", path, action_name="get_document")

    async def _list_documents(
        self, c: FirestoreListDocumentsConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        path = f"{root}/{c.collection_path.strip('/')}"
        params = {
            "pageSize": c.page_size,
            "pageToken": c.page_token,
            "orderBy": c.order_by,
        }
        return await _firestore_request(
            token, "GET", path, params=params, action_name="list_documents"
        )

    async def _create_document(
        self, c: FirestoreCreateDocumentConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        path = f"{root}/{c.collection_path.strip('/')}"
        params = {"documentId": c.document_id} if c.document_id else None
        body = {"fields": _parse_json(c.fields, "fields")}
        return await _firestore_request(
            token, "POST", path, params=params, json_body=body, action_name="create_document"
        )

    async def _update_document(
        self, c: FirestoreUpdateDocumentConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        path = f"{root}/{c.collection_path.strip('/')}/{c.document_id}"
        params: Dict[str, Any] = {}
        mask_fields = _comma_list(c.update_mask)
        if mask_fields:
            params["updateMask.fieldPaths"] = mask_fields
        body = {"fields": _parse_json(c.fields, "fields")}
        return await _firestore_request(
            token, "PATCH", path, params=params, json_body=body, action_name="update_document"
        )

    async def _delete_document(
        self, c: FirestoreDeleteDocumentConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        path = f"{root}/{c.collection_path.strip('/')}/{c.document_id}"
        return await _firestore_request(
            token, "DELETE", path, action_name="delete_document"
        )

    # ------------------------------------------------------------------
    # Batch handlers
    # ------------------------------------------------------------------
    async def _batch_get_documents(
        self, c: FirestoreBatchGetConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        names = [f"{root}/{p.strip('/')}" for p in _comma_list(c.document_paths)]
        body = {"documents": names}
        return await _firestore_request(
            token, "POST", f"{root}:batchGet", json_body=body, action_name="batch_get_documents"
        )

    async def _batch_write(
        self, c: FirestoreBatchWriteConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        body = {"writes": _parse_json(c.writes, "writes")}
        return await _firestore_request(
            token, "POST", f"{root}:batchWrite", json_body=body, action_name="batch_write"
        )

    # ------------------------------------------------------------------
    # Query handlers
    # ------------------------------------------------------------------
    def _query_parent(self, c, root: str) -> str:
        parent = getattr(c, "parent_path", None)
        if parent:
            return f"{root}/{parent.strip('/')}"
        return root

    async def _run_query(
        self, c: FirestoreRunQueryConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        parent = self._query_parent(c, root)
        body = {"structuredQuery": _parse_json(c.structured_query, "structured_query")}
        return await _firestore_request(
            token, "POST", f"{parent}:runQuery", json_body=body, action_name="run_query"
        )

    async def _run_aggregation_query(
        self, c: FirestoreRunAggregationQueryConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        parent = self._query_parent(c, root)
        body = {
            "structuredAggregationQuery": _parse_json(
                c.structured_aggregation_query, "structured_aggregation_query"
            )
        }
        return await _firestore_request(
            token,
            "POST",
            f"{parent}:runAggregationQuery",
            json_body=body,
            action_name="run_aggregation_query",
        )

    async def _partition_query(
        self, c: FirestorePartitionQueryConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        parent = self._query_parent(c, root)
        body: Dict[str, Any] = {
            "structuredQuery": _parse_json(c.structured_query, "structured_query")
        }
        if c.partition_count:
            body["partitionCount"] = (
                int(c.partition_count)
                if str(c.partition_count).isdigit()
                else c.partition_count
            )
        return await _firestore_request(
            token,
            "POST",
            f"{parent}:partitionQuery",
            json_body=body,
            action_name="partition_query",
        )

    async def _execute_pipeline(
        self, c: FirestoreExecutePipelineConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/documents:executePipeline"
        body = _parse_json(c.pipeline_request, "pipeline_request")
        return await _firestore_request(
            token, "POST", path, json_body=body, action_name="execute_pipeline"
        )

    async def _listen(self, c: FirestoreListenConfig, token: str) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/documents:listen"
        body = _parse_json(c.listen_request, "listen_request")
        return await _firestore_request(
            token, "POST", path, json_body=body, action_name="listen"
        )

    async def _write(self, c: FirestoreWriteConfig, token: str) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/documents:write"
        body = _parse_json(c.write_request, "write_request")
        return await _firestore_request(
            token, "POST", path, json_body=body, action_name="write"
        )

    async def _list_collection_ids(
        self, c: FirestoreListCollectionIdsConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        parent = self._query_parent(c, root)
        body: Dict[str, Any] = {}
        if c.page_size:
            body["pageSize"] = int(c.page_size) if str(c.page_size).isdigit() else c.page_size
        return await _firestore_request(
            token,
            "POST",
            f"{parent}:listCollectionIds",
            json_body=body,
            action_name="list_collection_ids",
        )

    # ------------------------------------------------------------------
    # Transaction handlers
    # ------------------------------------------------------------------
    async def _begin_transaction(
        self, c: FirestoreBeginTransactionConfig, token: str
    ) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        return await _firestore_request(
            token, "POST", f"{root}:beginTransaction", json_body={}, action_name="begin_transaction"
        )

    async def _commit(self, c: FirestoreCommitConfig, token: str) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        body: Dict[str, Any] = {"writes": _parse_json(c.writes, "writes")}
        if c.transaction:
            body["transaction"] = c.transaction
        return await _firestore_request(
            token, "POST", f"{root}:commit", json_body=body, action_name="commit"
        )

    async def _rollback(self, c: FirestoreRollbackConfig, token: str) -> Dict[str, Any]:
        root = _db_root(c.project_id, c.database_id)
        return await _firestore_request(
            token,
            "POST",
            f"{root}:rollback",
            json_body={"transaction": c.transaction},
            action_name="rollback",
        )

    # ------------------------------------------------------------------
    # Database / index / operation handlers
    # ------------------------------------------------------------------
    async def _get_database(
        self, c: FirestoreGetDatabaseConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}"
        return await _firestore_request(token, "GET", path, action_name="get_database")

    async def _list_databases(
        self, c: FirestoreListDatabasesConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases"
        return await _firestore_request(token, "GET", path, action_name="list_databases")

    async def _create_database(
        self, c: FirestoreCreateDatabaseConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases"
        body = _parse_json(c.database, "database")
        return await _firestore_request(
            token,
            "POST",
            path,
            params={"databaseId": c.new_database_id},
            json_body=body,
            action_name="create_database",
        )

    async def _clone_database(
        self, c: FirestoreCloneDatabaseConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases:clone"
        body = _parse_json(c.clone_request, "clone_request")
        if not isinstance(body, dict):
            raise ValueError("clone_request must decode to a JSON object")
        body.setdefault("databaseId", c.new_database_id)
        return await _firestore_request(
            token, "POST", path, json_body=body, action_name="clone_database"
        )

    async def _restore_database(
        self, c: FirestoreRestoreDatabaseConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases:restore"
        body = _parse_json(c.restore_request, "restore_request")
        if not isinstance(body, dict):
            raise ValueError("restore_request must decode to a JSON object")
        body.setdefault("databaseId", c.new_database_id)
        return await _firestore_request(
            token, "POST", path, json_body=body, action_name="restore_database"
        )

    async def _update_database(
        self, c: FirestoreUpdateDatabaseConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}"
        params = {"updateMask": c.update_mask}
        body = _parse_json(c.database, "database")
        if isinstance(body, dict) and "name" not in body:
            body["name"] = path
        return await _firestore_request(
            token, "PATCH", path, params=params, json_body=body, action_name="update_database"
        )

    async def _delete_database(
        self, c: FirestoreDeleteDatabaseConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}"
        params = {"etag": c.etag}
        return await _firestore_request(
            token, "DELETE", path, params=params, action_name="delete_database"
        )

    async def _create_backup_schedule(
        self, c: FirestoreCreateBackupScheduleConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/backupSchedules"
        body = _parse_json(c.backup_schedule, "backup_schedule")
        return await _firestore_request(
            token,
            "POST",
            path,
            json_body=body,
            action_name="create_backup_schedule",
        )

    async def _get_backup_schedule(
        self, c: FirestoreGetBackupScheduleConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/backupSchedules/"
            f"{c.backup_schedule_id}"
        )
        return await _firestore_request(
            token, "GET", path, action_name="get_backup_schedule"
        )

    async def _list_backup_schedules(
        self, c: FirestoreListBackupSchedulesConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/backupSchedules"
        params = {"pageSize": c.page_size, "pageToken": c.page_token}
        return await _firestore_request(
            token,
            "GET",
            path,
            params=params,
            action_name="list_backup_schedules",
        )

    async def _update_backup_schedule(
        self, c: FirestoreUpdateBackupScheduleConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/backupSchedules/"
            f"{c.backup_schedule_id}"
        )
        body = _parse_json(c.backup_schedule, "backup_schedule")
        if isinstance(body, dict) and "name" not in body:
            body["name"] = path
        return await _firestore_request(
            token,
            "PATCH",
            path,
            params={"updateMask": c.update_mask},
            json_body=body,
            action_name="update_backup_schedule",
        )

    async def _delete_backup_schedule(
        self, c: FirestoreDeleteBackupScheduleConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/backupSchedules/"
            f"{c.backup_schedule_id}"
        )
        return await _firestore_request(
            token, "DELETE", path, action_name="delete_backup_schedule"
        )

    async def _export_documents(
        self, c: FirestoreExportDocumentsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}:exportDocuments"
        body: Dict[str, Any] = {"outputUriPrefix": c.output_uri_prefix}
        if c.collection_ids:
            body["collectionIds"] = _comma_list(c.collection_ids)
        if c.namespace_ids:
            body["namespaceIds"] = _comma_list(c.namespace_ids)
        return await _firestore_request(
            token, "POST", path, json_body=body, action_name="export_documents"
        )

    async def _import_documents(
        self, c: FirestoreImportDocumentsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}:importDocuments"
        body: Dict[str, Any] = {"inputUriPrefix": c.input_uri_prefix}
        if c.collection_ids:
            body["collectionIds"] = _comma_list(c.collection_ids)
        if c.namespace_ids:
            body["namespaceIds"] = _comma_list(c.namespace_ids)
        return await _firestore_request(
            token, "POST", path, json_body=body, action_name="import_documents"
        )

    async def _bulk_delete_documents(
        self, c: FirestoreBulkDeleteDocumentsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}:bulkDeleteDocuments"
        body: Dict[str, Any] = {}
        if c.collection_ids:
            body["collectionIds"] = _comma_list(c.collection_ids)
        if c.namespace_ids:
            body["namespaceIds"] = _comma_list(c.namespace_ids)
        return await _firestore_request(
            token, "POST", path, json_body=body, action_name="bulk_delete_documents"
        )

    async def _list_indexes(
        self, c: FirestoreListIndexesConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}"
            f"/collectionGroups/{c.collection_id}/indexes"
        )
        return await _firestore_request(token, "GET", path, action_name="list_indexes")

    async def _get_index(
        self, c: FirestoreGetIndexConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/collectionGroups/"
            f"{c.collection_id}/indexes/{c.index_id}"
        )
        return await _firestore_request(token, "GET", path, action_name="get_index")

    async def _delete_index(
        self, c: FirestoreDeleteIndexConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/collectionGroups/"
            f"{c.collection_id}/indexes/{c.index_id}"
        )
        return await _firestore_request(token, "DELETE", path, action_name="delete_index")

    async def _create_user_creds(
        self, c: FirestoreCreateUserCredsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/userCreds"
        body = _parse_json(c.user_creds, "user_creds")
        return await _firestore_request(
            token,
            "POST",
            path,
            params={"userCredsId": c.user_creds_id},
            json_body=body,
            action_name="create_user_creds",
        )

    async def _get_user_creds(
        self, c: FirestoreGetUserCredsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/userCreds/{c.user_creds_id}"
        return await _firestore_request(token, "GET", path, action_name="get_user_creds")

    async def _list_user_creds(
        self, c: FirestoreListUserCredsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/userCreds"
        return await _firestore_request(token, "GET", path, action_name="list_user_creds")

    async def _enable_user_creds(
        self, c: FirestoreEnableUserCredsConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/userCreds/"
            f"{c.user_creds_id}:enable"
        )
        return await _firestore_request(
            token, "POST", path, json_body={}, action_name="enable_user_creds"
        )

    async def _disable_user_creds(
        self, c: FirestoreDisableUserCredsConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/userCreds/"
            f"{c.user_creds_id}:disable"
        )
        return await _firestore_request(
            token, "POST", path, json_body={}, action_name="disable_user_creds"
        )

    async def _delete_user_creds(
        self, c: FirestoreDeleteUserCredsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/userCreds/{c.user_creds_id}"
        return await _firestore_request(
            token, "DELETE", path, action_name="delete_user_creds"
        )

    async def _reset_user_creds_password(
        self, c: FirestoreResetUserCredsPasswordConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/userCreds/"
            f"{c.user_creds_id}:resetPassword"
        )
        return await _firestore_request(
            token,
            "POST",
            path,
            json_body={},
            action_name="reset_user_creds_password",
        )

    async def _list_fields(
        self, c: FirestoreListFieldsConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/collectionGroups/"
            f"{c.collection_id}/fields"
        )
        params = {
            "filter": c.filter,
            "pageSize": c.page_size,
            "pageToken": c.page_token,
        }
        return await _firestore_request(token, "GET", path, params=params, action_name="list_fields")

    async def _get_field(
        self, c: FirestoreGetFieldConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/collectionGroups/"
            f"{c.collection_id}/fields/{c.field_path}"
        )
        return await _firestore_request(token, "GET", path, action_name="get_field")

    async def _update_field(
        self, c: FirestoreUpdateFieldConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}/collectionGroups/"
            f"{c.collection_id}/fields/{c.field_path}"
        )
        params = {"updateMask": c.update_mask}
        body = _parse_json(c.field, "field")
        if isinstance(body, dict) and "name" not in body:
            body["name"] = path
        return await _firestore_request(
            token, "PATCH", path, params=params, json_body=body, action_name="update_field"
        )

    async def _get_operation(
        self, c: FirestoreGetOperationConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}"
            f"/operations/{c.operation_id}"
        )
        return await _firestore_request(token, "GET", path, action_name="get_operation")

    async def _list_operations(
        self, c: FirestoreListOperationsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/databases/{c.database_id}/operations"
        params = {
            "filter": c.filter,
            "pageSize": c.page_size,
            "pageToken": c.page_token,
        }
        return await _firestore_request(token, "GET", path, params=params, action_name="list_operations")

    async def _cancel_operation(
        self, c: FirestoreCancelOperationConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}"
            f"/operations/{c.operation_id}:cancel"
        )
        return await _firestore_request(
            token, "POST", path, json_body={}, action_name="cancel_operation"
        )

    async def _delete_operation(
        self, c: FirestoreDeleteOperationConfig, token: str
    ) -> Dict[str, Any]:
        path = (
            f"projects/{c.project_id}/databases/{c.database_id}"
            f"/operations/{c.operation_id}"
        )
        return await _firestore_request(token, "DELETE", path, action_name="delete_operation")

    async def _get_location(
        self, c: FirestoreGetLocationConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/locations/{c.location_id}"
        return await _firestore_request(token, "GET", path, action_name="get_location")

    async def _list_locations(
        self, c: FirestoreListLocationsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/locations"
        params = {
            "filter": c.filter,
            "pageSize": c.page_size,
            "pageToken": c.page_token,
        }
        return await _firestore_request(
            token, "GET", path, params=params, action_name="list_locations"
        )

    async def _get_backup(
        self, c: FirestoreGetBackupConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/locations/{c.location_id}/backups/{c.backup_id}"
        return await _firestore_request(token, "GET", path, action_name="get_backup")

    async def _list_backups(
        self, c: FirestoreListBackupsConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/locations/{c.location_id}/backups"
        params = {
            "pageSize": c.page_size,
            "pageToken": c.page_token,
            "filter": c.filter,
        }
        return await _firestore_request(
            token, "GET", path, params=params, action_name="list_backups"
        )

    async def _delete_backup(
        self, c: FirestoreDeleteBackupConfig, token: str
    ) -> Dict[str, Any]:
        path = f"projects/{c.project_id}/locations/{c.location_id}/backups/{c.backup_id}"
        return await _firestore_request(token, "DELETE", path, action_name="delete_backup")

    async def _custom_api_call(
        self, c: FirestoreCustomApiCallConfig, token: str
    ) -> Dict[str, Any]:
        params = _parse_json(c.query_params, "query_params") if c.query_params else None
        body = _parse_json(c.body, "body") if c.body is not None else None
        return await _firestore_request(
            token,
            c.method,
            c.path,
            params=params,
            json_body=body,
            action_name="custom_api_call",
        )

    # ------------------------------------------------------------------
    # Trigger handler (poll-based)
    # ------------------------------------------------------------------
    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """No documents changed since the cursor on a scheduled poll → skip
        downstream. Firestore dedups via the `last_polled_at` updateTime cursor,
        so emptiness is read straight off the poll output. See ``WorkflowNode``."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_document_changed"
            and not output.get("items")
        )

    async def _poll_document_changes(
        self, c: FirestoreOnDocumentChangedConfig, token: str
    ) -> Dict[str, Any]:
        """Poll a collection for documents created/updated since the cursor.

        Uses `documents.list` for the exact collection path being watched,
        ordering by update time descending so the newest changed documents are
        fetched first. Emits only documents whose `updateTime` is newer than the
        stored cursor and advances the cursor to the newest `updateTime` seen.

        The cursor persists in `workflow_node_state` (keyed by workflow+node),
        never in config. The FIRST poll *baselines* — it records the current
        high-water mark and emits nothing, so enabling the trigger never floods
        the workflow with the collection's entire backlog; it only fires for
        documents changed afterwards. The dedup write is a compare-and-swap
        (`_update_node_state`) so an overlapping poll on another container can't
        double-fire.
        """
        root = _db_root(c.project_id, c.database_id)
        collection_id, parent_path = _split_collection_path(c.collection_path)
        try:
            limit = int(c.page_size) if c.page_size and str(c.page_size).isdigit() else 50
        except (TypeError, ValueError):
            limit = 50

        parent = f"{root}/{parent_path}" if parent_path else root
        path = f"{parent}/{collection_id}"
        params: Dict[str, Any] = {
            "pageSize": limit,
            "orderBy": "updateTime desc, __name__ desc",
        }
        result = await _firestore_request(
            token,
            "GET",
            path,
            params=params,
            action_name="on_document_changed",
        )
        if result.get("status") != "success":
            return result

        documents = (result.get("data") or {}).get("documents") or []

        def mutator(state):
            is_first_poll = "last_polled_at" not in state
            cursor = state.get("last_polled_at")

            new_docs: List[Dict[str, Any]] = []
            newest = cursor
            for document in documents:
                if not isinstance(document, dict):
                    continue
                update_time = document.get("updateTime") or document.get("createTime")
                if not update_time:
                    continue
                # Emit strictly-newer docs only. A doc whose updateTime == cursor
                # is the previous poll's boundary and is deliberately NOT
                # re-emitted (the cursor is inclusive of what's been seen). ISO
                # 8601 UTC strings order lexicographically, matching Firestore's
                # RFC 3339 timestamps.
                if not is_first_poll and (cursor is None or update_time > cursor):
                    new_docs.append(document)
                if newest is None or update_time > newest:
                    newest = update_time

            if newest is None:
                # No usable updateTime this poll (empty collection). Stay
                # UNBASELINED — persisting a null cursor would make the next poll
                # treat every doc as new (cursor None ⇒ everything qualifies) and
                # flood the workflow.
                return None, (new_docs, newest)
            # First poll baselines (emits nothing); later polls advance only when
            # a strictly-newer doc appeared.
            if is_first_poll or newest != cursor:
                return {**state, "last_polled_at": newest}, (new_docs, newest)
            return None, (new_docs, newest)  # nothing new → no write

        # skip_result: on a transient state blip / lost contention, emit nothing
        # this tick (state untouched) instead of failing the scheduled run.
        new_docs, newest = await self._update_node_state(
            mutator, skip_result=([], None)
        )

        # Drive trigger_produced_no_event: 0 on baseline/skip halts downstream.
        self._poll_emitted_count = len(new_docs)

        return {
            "status": "success",
            "operation": "on_document_changed",
            "collection_path": c.collection_path,
            "items": new_docs,
            "new_count": len(new_docs),
            "last_polled_at": newest,
            "timestamp": time.time(),
        }
