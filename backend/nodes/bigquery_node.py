"""
Google BigQuery automation node.

Provides workflow integration with the BigQuery v2 REST API for operations
including:
- Queries: run query (sync), get query results
- Jobs: insert, get, list, cancel, delete
- Datasets: list, get, create, update, patch, delete, undelete
- Tables: list, get, create, patch, update, delete, stream insert rows, list data;
  IAM: get/set policy, test permissions
- Row Access Policies: list, get
- Routines: list, get, create, update, delete
- Models: list, get, patch, delete
- Project: get service account, list projects
- Trigger: on new query results (poll-based, cursor-deduped)

Authentication (two methods): OAuth 2.0 (Google Identity, Bearer access token)
for user-delegated access, and a service-account JSON key (JWT → access token)
for server-to-server automation. Plain Google API keys are NOT accepted by
BigQuery — every data/job request requires an OAuth/service-account access token.

API Base URL: https://bigquery.googleapis.com/bigquery/v2
Documentation: https://cloud.google.com/bigquery/docs/reference/rest
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx
import jwt

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)
from nodes.scopes.google_cloud import BIGQUERY_SCOPES
from utils.google_service_account import require_google_service_account_token_uri
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

BIGQUERY_API_BASE = "https://bigquery.googleapis.com/bigquery/v2"


# ============================================================================
# Credential Schema
# ============================================================================


class BigQueryOAuthCredential(BaseModel):
    """OAuth credential for Google BigQuery.

    Tokens are obtained via the Google OAuth flow, not entered manually.
    """

    credential_type: Literal["bigquery_oauth"] = Field(
        "bigquery_oauth", json_schema_extra={"ui:hidden": True}
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
                "https://www.googleapis.com/auth/bigquery",
            ],
            "x-credential-url": "https://console.cloud.google.com/apis/credentials",
        }
    )


class BigQueryServiceAccountCredential(BaseModel):
    """Service-account JSON key for server-to-server BigQuery access.

    The primary auth method for automated/backend BigQuery access — a signed
    JWT is exchanged for an OAuth access token per run. The project is read
    from the key, so ``project_id`` fields can be left blank to default to it.
    """

    credential_type: Literal["bigquery_service_account"] = Field(
        "bigquery_service_account", json_schema_extra={"ui:hidden": True}
    )
    service_account_json: str = Field(
        ...,
        title="Service Account JSON",
        description="Raw JSON key for a Google Cloud service account with BigQuery access",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 12},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.cloud.google.com/iam-admin/serviceaccounts",
            "x-credential-instructions": (
                "Create a JSON key for a service account with the required BigQuery IAM "
                "roles (e.g. BigQuery Job User + BigQuery Data Editor). Prefer user OAuth "
                "for user-delegated access; use service accounts for server-to-server "
                "automation."
            ),
        }
    )


BigQueryCredential = Union[
    BigQueryOAuthCredential,
    BigQueryServiceAccountCredential,
]

BIGQUERY_OAUTH_SCOPES = ["https://www.googleapis.com/auth/bigquery"]


# ============================================================================
# Shared dynamic-options descriptors
# ============================================================================

_PROJECT_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "project_id",
        "placeholder": "Select a project...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste project ID",
    }
}

_DATASET_OPTIONS = {
    "x-resource-type": "bigquery_dataset",
    "x-dynamic-options": {
        "field_name": "dataset_id",
        "placeholder": "Select a dataset...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste dataset ID",
    }
}

_TABLE_OPTIONS = {
    "x-resource-type": "bigquery_table",
    "x-dynamic-options": {
        "field_name": "table_id",
        "placeholder": "Select a table...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste table ID",
    }
}

_JOB_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "job_id",
        "placeholder": "Select a job...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste job ID",
        "depends_on": "project_id",
    }
}

_ROUTINE_OPTIONS = {
    "x-resource-type": "bigquery_routine",
    "x-dynamic-options": {
        "field_name": "routine_id",
        "placeholder": "Select a routine...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste routine ID",
        "depends_on": "dataset_id",
    }
}

_MODEL_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "model_id",
        "placeholder": "Select a model...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste model ID",
        "depends_on": "dataset_id",
    }
}


def _job_field() -> Any:
    return Field(
        ...,
        title="Job",
        description="The job ID",
        json_schema_extra=_JOB_OPTIONS,
    )


def _routine_field() -> Any:
    return Field(
        ...,
        title="Routine",
        description="The routine ID",
        json_schema_extra=_ROUTINE_OPTIONS,
    )


def _model_field() -> Any:
    return Field(
        ...,
        title="Model",
        description="The BQML model ID",
        json_schema_extra=_MODEL_OPTIONS,
    )


def _project_field() -> Any:
    return Field(
        ...,
        title="Project",
        description="GCP project ID (billing/quota project)",
        json_schema_extra=_PROJECT_OPTIONS,
    )


def _dataset_field() -> Any:
    return Field(
        ...,
        title="Dataset",
        description="The dataset ID",
        json_schema_extra=_DATASET_OPTIONS,
    )


def _table_field() -> Any:
    return Field(
        ...,
        title="Table",
        description="The table ID",
        json_schema_extra=_TABLE_OPTIONS,
    )


# ============================================================================
# Operation Configs — Queries
# ============================================================================


class BigQueryRunQueryConfig(BaseModel):
    """Run a SQL query and return results inline (synchronous, bounded by timeout)."""

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
    query: str = Field(
        ...,
        title="SQL Query",
        description="The SQL query to execute (GoogleSQL syntax)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    use_legacy_sql: Optional[str] = Field(
        "false",
        title="Use Legacy SQL",
        description="Use BigQuery legacy SQL dialect instead of GoogleSQL",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of result rows to return"
    )
    timeout_ms: Optional[str] = Field(
        "30000",
        title="Timeout (ms)",
        description="How long to wait for the query to complete before returning",
    )
    location: Optional[str] = Field(
        None, title="Location", description="Dataset location (e.g. US, EU, us-central1)"
    )


class BigQueryGetQueryResultsConfig(BaseModel):
    """Page through the results of a (possibly async) query job."""

    operation: Literal["get_query_results"] = Field(
        "get_query_results",
        json_schema_extra={
            "const": "get_query_results",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Get Query Results",
        },
        title="Get Query Results",
    )
    project_id: str = _project_field()
    job_id: str = _job_field()
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of result rows per page"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token to fetch the next page of results"
    )
    location: Optional[str] = Field(
        None, title="Location", description="Dataset location (e.g. US, EU)"
    )


# ============================================================================
# Operation Configs — Triggers
# ============================================================================


class BigQueryOnQueryResultsConfig(BaseModel):
    """Poll-based trigger: run a SQL query on a schedule and emit NEW rows.

    BigQuery has no native webhooks, so this acts as a scheduled query: on each
    tick the user's SQL runs and only rows whose ``cursor_column`` is greater
    than the last-seen cursor are emitted. The cursor high-water-mark lives in
    durable node state (not config, which isn't persisted across polls) so
    already-seen rows are never re-emitted, and the first poll baselines.
    """

    operation: Literal["on_query_results"] = Field(
        "on_query_results",
        json_schema_extra={
            "const": "on_query_results",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Scheduled Query Results",
        },
        title="On Scheduled Query Results",
    )
    project_id: str = _project_field()
    query: str = Field(
        ...,
        title="SQL Query",
        description="The SQL query to run on each poll (GoogleSQL). Must include the cursor column and be ordered so new rows have a higher cursor value.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    cursor_column: str = Field(
        ...,
        title="Cursor Column",
        description="Name of the timestamp/id column used to detect new rows. Only rows whose value in this column is greater than the last-seen value are emitted.",
        json_schema_extra={"placeholder": "created_at"},
    )
    use_legacy_sql: Optional[str] = Field(
        "false",
        title="Use Legacy SQL",
        description="Use BigQuery legacy SQL dialect instead of GoogleSQL",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    location: Optional[str] = Field(
        None, title="Location", description="Dataset location (e.g. US, EU, us-central1)"
    )
    max_results: Optional[str] = Field(
        "1000",
        title="Max Rows Per Poll",
        description="Maximum number of rows to scan per poll",
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to run the query and check for new rows",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    # Hidden internal fields for webhook/schedule management
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
# Operation Configs — Jobs
# ============================================================================


class BigQueryInsertJobConfig(BaseModel):
    """Start a query / load / extract / copy job (async)."""

    operation: Literal["insert_job"] = Field(
        "insert_job",
        json_schema_extra={
            "const": "insert_job",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Insert Job",
        },
        title="Insert Job",
    )
    project_id: str = _project_field()
    configuration: str = Field(
        ...,
        title="Job Configuration",
        description='JSON job configuration, e.g. {"query": {"query": "SELECT 1", "useLegacySql": false}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryGetJobConfig(BaseModel):
    """Fetch a job's status and statistics (poll until DONE)."""

    operation: Literal["get_job"] = Field(
        "get_job",
        json_schema_extra={
            "const": "get_job",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Get Job",
        },
        title="Get Job",
    )
    project_id: str = _project_field()
    job_id: str = _job_field()
    location: Optional[str] = Field(
        None, title="Location", description="Job location (e.g. US, EU)"
    )


class BigQueryListJobsConfig(BaseModel):
    """List jobs in a project (filter by state, time range)."""

    operation: Literal["list_jobs"] = Field(
        "list_jobs",
        json_schema_extra={
            "const": "list_jobs",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "List Jobs",
        },
        title="List Jobs",
    )
    project_id: str = _project_field()
    state_filter: Optional[str] = Field(
        None,
        title="State Filter",
        description="Filter jobs by state",
        json_schema_extra={
            "enum": ["", "running", "pending", "done"],
            "enumNames": ["Any", "Running", "Pending", "Done"],
            "x-enum-searchable": True,
        },
    )
    all_users: Optional[str] = Field(
        "false",
        title="All Users",
        description="Include jobs from all project users (not just the caller)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of jobs to return"
    )


class BigQueryCancelJobConfig(BaseModel):
    """Request cancellation of a running job."""

    operation: Literal["cancel_job"] = Field(
        "cancel_job",
        json_schema_extra={
            "const": "cancel_job",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Cancel Job",
        },
        title="Cancel Job",
    )
    project_id: str = _project_field()
    job_id: str = _job_field()
    location: Optional[str] = Field(
        None, title="Location", description="Job location (e.g. US, EU)"
    )


class BigQueryDeleteJobConfig(BaseModel):
    """Delete a job's metadata."""

    operation: Literal["delete_job"] = Field(
        "delete_job",
        json_schema_extra={
            "const": "delete_job",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Delete Job",
        },
        title="Delete Job",
    )
    project_id: str = _project_field()
    job_id: str = _job_field()
    location: Optional[str] = Field(
        None, title="Location", description="Job location (e.g. US, EU)"
    )


# ============================================================================
# Operation Configs — Datasets
# ============================================================================


class BigQueryListDatasetsConfig(BaseModel):
    """List datasets in the project."""

    operation: Literal["list_datasets"] = Field(
        "list_datasets",
        json_schema_extra={
            "const": "list_datasets",
            "ui:hidden": True,
            "x-category": "Datasets",
            "x-is-trigger": False,
            "x-display-name": "List Datasets",
        },
        title="List Datasets",
    )
    project_id: str = _project_field()
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of datasets to return"
    )


class BigQueryGetDatasetConfig(BaseModel):
    """Fetch dataset metadata."""

    operation: Literal["get_dataset"] = Field(
        "get_dataset",
        json_schema_extra={
            "const": "get_dataset",
            "ui:hidden": True,
            "x-category": "Datasets",
            "x-is-trigger": False,
            "x-display-name": "Get Dataset",
        },
        title="Get Dataset",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()


class BigQueryCreateDatasetConfig(BaseModel):
    """Create a new dataset."""

    operation: Literal["create_dataset"] = Field(
        "create_dataset",
        json_schema_extra={
            "const": "create_dataset",
            "x-creates-resource": True,
            "x-resource-type": "bigquery_dataset",
            "x-resource-id-path": "data.datasetReference.datasetId",
            "ui:hidden": True,
            "x-category": "Datasets",
            "x-is-trigger": False,
            "x-display-name": "Create Dataset",
        },
        title="Create Dataset",
    )
    project_id: str = _project_field()
    dataset_id: str = Field(
        ..., title="Dataset ID", description="ID for the new dataset"
    )
    location: Optional[str] = Field(
        None, title="Location", description="Data location (e.g. US, EU, us-central1)"
    )
    friendly_name: Optional[str] = Field(
        None, title="Friendly Name", description="Human-readable dataset name"
    )
    description: Optional[str] = Field(
        None, title="Description", description="Dataset description"
    )


class BigQueryUpdateDatasetConfig(BaseModel):
    """Full replace of dataset metadata (PUT)."""

    operation: Literal["update_dataset"] = Field(
        "update_dataset",
        json_schema_extra={
            "const": "update_dataset",
            "ui:hidden": True,
            "x-category": "Datasets",
            "x-is-trigger": False,
            "x-display-name": "Update Dataset",
        },
        title="Update Dataset",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    resource: str = Field(
        ...,
        title="Dataset Resource",
        description="Full dataset resource JSON to replace the existing metadata",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryPatchDatasetConfig(BaseModel):
    """Partial update of dataset metadata (PATCH)."""

    operation: Literal["patch_dataset"] = Field(
        "patch_dataset",
        json_schema_extra={
            "const": "patch_dataset",
            "ui:hidden": True,
            "x-category": "Datasets",
            "x-is-trigger": False,
            "x-display-name": "Patch Dataset",
        },
        title="Patch Dataset",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    resource: str = Field(
        ...,
        title="Patch JSON",
        description="Partial dataset resource JSON with only the fields to change",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryDeleteDatasetConfig(BaseModel):
    """Delete a dataset."""

    operation: Literal["delete_dataset"] = Field(
        "delete_dataset",
        json_schema_extra={
            "const": "delete_dataset",
            "ui:hidden": True,
            "x-category": "Datasets",
            "x-is-trigger": False,
            "x-display-name": "Delete Dataset",
        },
        title="Delete Dataset",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    delete_contents: Optional[str] = Field(
        "false",
        title="Delete Contents",
        description="Also delete all tables in the dataset",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Operation Configs — Tables
# ============================================================================


class BigQueryListTablesConfig(BaseModel):
    """List tables/views in a dataset."""

    operation: Literal["list_tables"] = Field(
        "list_tables",
        json_schema_extra={
            "const": "list_tables",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "List Tables",
        },
        title="List Tables",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of tables to return"
    )


class BigQueryGetTableConfig(BaseModel):
    """Fetch table metadata/schema."""

    operation: Literal["get_table"] = Field(
        "get_table",
        json_schema_extra={
            "const": "get_table",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Get Table",
        },
        title="Get Table",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()


class BigQueryCreateTableConfig(BaseModel):
    """Create a table or view with a schema."""

    operation: Literal["create_table"] = Field(
        "create_table",
        json_schema_extra={
            "const": "create_table",
            "x-creates-resource": True,
            "x-resource-type": "bigquery_table",
            "x-resource-id-path": "data.tableReference.tableId",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Create Table",
        },
        title="Create Table",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = Field(..., title="Table ID", description="ID for the new table")
    output_schema: Optional[str] = Field(
        None,
        title="Schema",
        description='Schema fields JSON, e.g. {"fields": [{"name": "id", "type": "INTEGER"}]}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    description: Optional[str] = Field(
        None, title="Description", description="Table description"
    )


class BigQueryPatchTableConfig(BaseModel):
    """Partial update of a table (add columns, set expiration, etc.)."""

    operation: Literal["patch_table"] = Field(
        "patch_table",
        json_schema_extra={
            "const": "patch_table",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Patch Table",
        },
        title="Patch Table",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()
    resource: str = Field(
        ...,
        title="Patch JSON",
        description="Partial table resource JSON with only the fields to change",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryUpdateTableConfig(BaseModel):
    """Full replace of table metadata (PUT)."""

    operation: Literal["update_table"] = Field(
        "update_table",
        json_schema_extra={
            "const": "update_table",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Update Table",
        },
        title="Update Table",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()
    resource: str = Field(
        ...,
        title="Table Resource",
        description="Full table resource JSON to replace the existing metadata",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryDeleteTableConfig(BaseModel):
    """Delete a table or view."""

    operation: Literal["delete_table"] = Field(
        "delete_table",
        json_schema_extra={
            "const": "delete_table",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Delete Table",
        },
        title="Delete Table",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()


class BigQueryStreamInsertConfig(BaseModel):
    """Streaming insert of JSON rows into a table (real-time append)."""

    operation: Literal["stream_insert"] = Field(
        "stream_insert",
        json_schema_extra={
            "const": "stream_insert",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Stream Insert Rows",
        },
        title="Stream Insert Rows",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()
    rows: str = Field(
        ...,
        title="Rows",
        description='JSON array of row objects, e.g. [{"id": 1, "name": "Ada"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    skip_invalid_rows: Optional[str] = Field(
        "false",
        title="Skip Invalid Rows",
        description="Insert all valid rows even if some rows are invalid",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class BigQueryListTableDataConfig(BaseModel):
    """Read rows from a table directly (paginated, no SQL)."""

    operation: Literal["list_table_data"] = Field(
        "list_table_data",
        json_schema_extra={
            "const": "list_table_data",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "List Table Data",
        },
        title="List Table Data",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of rows per page"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token to fetch the next page of rows"
    )


# ============================================================================
# Operation Configs — Routines
# ============================================================================


class BigQueryListRoutinesConfig(BaseModel):
    """List stored procedures / UDFs / TVFs in a dataset."""

    operation: Literal["list_routines"] = Field(
        "list_routines",
        json_schema_extra={
            "const": "list_routines",
            "ui:hidden": True,
            "x-category": "Routines",
            "x-is-trigger": False,
            "x-display-name": "List Routines",
        },
        title="List Routines",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()


class BigQueryGetRoutineConfig(BaseModel):
    """Fetch a routine definition."""

    operation: Literal["get_routine"] = Field(
        "get_routine",
        json_schema_extra={
            "const": "get_routine",
            "ui:hidden": True,
            "x-category": "Routines",
            "x-is-trigger": False,
            "x-display-name": "Get Routine",
        },
        title="Get Routine",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    routine_id: str = _routine_field()


class BigQueryCreateRoutineConfig(BaseModel):
    """Create a stored procedure / UDF / TVF."""

    operation: Literal["create_routine"] = Field(
        "create_routine",
        json_schema_extra={
            "const": "create_routine",
            "x-creates-resource": True,
            "x-resource-type": "bigquery_routine",
            "x-resource-id-path": "data.routineReference.routineId",
            "ui:hidden": True,
            "x-category": "Routines",
            "x-is-trigger": False,
            "x-display-name": "Create Routine",
        },
        title="Create Routine",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    resource: str = Field(
        ...,
        title="Routine Resource",
        description="Full routine resource JSON (routineReference, definitionBody, routineType, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Operation Configs — Models
# ============================================================================


class BigQueryListModelsConfig(BaseModel):
    """List BigQuery ML models in a dataset."""

    operation: Literal["list_models"] = Field(
        "list_models",
        json_schema_extra={
            "const": "list_models",
            "ui:hidden": True,
            "x-category": "Models",
            "x-is-trigger": False,
            "x-display-name": "List Models",
        },
        title="List Models",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()


class BigQueryGetModelConfig(BaseModel):
    """Fetch BQML model metadata."""

    operation: Literal["get_model"] = Field(
        "get_model",
        json_schema_extra={
            "const": "get_model",
            "ui:hidden": True,
            "x-category": "Models",
            "x-is-trigger": False,
            "x-display-name": "Get Model",
        },
        title="Get Model",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    model_id: str = _model_field()


class BigQueryDeleteModelConfig(BaseModel):
    """Delete a BQML model."""

    operation: Literal["delete_model"] = Field(
        "delete_model",
        json_schema_extra={
            "const": "delete_model",
            "ui:hidden": True,
            "x-category": "Models",
            "x-is-trigger": False,
            "x-display-name": "Delete Model",
        },
        title="Delete Model",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    model_id: str = _model_field()


# ============================================================================
# Operation Configs — Project
# ============================================================================


class BigQueryGetServiceAccountConfig(BaseModel):
    """Return the BigQuery service account for the project (KMS/transfer grants)."""

    operation: Literal["get_service_account"] = Field(
        "get_service_account",
        json_schema_extra={
            "const": "get_service_account",
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Get Service Account",
        },
        title="Get Service Account",
    )
    project_id: str = _project_field()


class BigQueryListProjectsConfig(BaseModel):
    """List projects the caller can access (for project picker UIs)."""

    operation: Literal["list_projects"] = Field(
        "list_projects",
        json_schema_extra={
            "const": "list_projects",
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Projects",
        },
        title="List Projects",
    )
    max_results: Optional[str] = Field(
        None, title="Max Results", description="Maximum number of projects to return"
    )


# ============================================================================
# Operation Configs — additional coverage (dataset undelete, routine
# update/delete, model patch, table IAM, row access policies)
# ============================================================================


class BigQueryUndeleteDatasetConfig(BaseModel):
    """Restore a dataset within its time-travel window (datasets.undelete)."""

    operation: Literal["undelete_dataset"] = Field(
        "undelete_dataset",
        json_schema_extra={
            "const": "undelete_dataset",
            "ui:hidden": True,
            "x-category": "Datasets",
            "x-is-trigger": False,
            "x-display-name": "Undelete Dataset",
        },
        title="Undelete Dataset",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    deletion_time: Optional[str] = Field(
        None,
        title="Deletion Time",
        description="RFC3339 timestamp of the dataset version to restore (optional)",
    )


class BigQueryUpdateRoutineConfig(BaseModel):
    """Replace a routine's full definition (routines.update, PUT)."""

    operation: Literal["update_routine"] = Field(
        "update_routine",
        json_schema_extra={
            "const": "update_routine",
            "ui:hidden": True,
            "x-category": "Routines",
            "x-is-trigger": False,
            "x-display-name": "Update Routine",
        },
        title="Update Routine",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    routine_id: str = _routine_field()
    resource: str = Field(
        ...,
        title="Routine Resource",
        description="Full routine resource JSON to replace the existing definition",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryDeleteRoutineConfig(BaseModel):
    """Delete a routine (routines.delete)."""

    operation: Literal["delete_routine"] = Field(
        "delete_routine",
        json_schema_extra={
            "const": "delete_routine",
            "ui:hidden": True,
            "x-category": "Routines",
            "x-is-trigger": False,
            "x-display-name": "Delete Routine",
        },
        title="Delete Routine",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    routine_id: str = _routine_field()


class BigQueryPatchModelConfig(BaseModel):
    """Update mutable BQML model metadata (models.patch)."""

    operation: Literal["patch_model"] = Field(
        "patch_model",
        json_schema_extra={
            "const": "patch_model",
            "ui:hidden": True,
            "x-category": "Models",
            "x-is-trigger": False,
            "x-display-name": "Patch Model",
        },
        title="Patch Model",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    model_id: str = _model_field()
    resource: str = Field(
        ...,
        title="Patch JSON",
        description="Model fields to update (e.g. friendlyName, description, labels, expirationTime)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryGetTableIamPolicyConfig(BaseModel):
    """Get the IAM policy for a table (tables.getIamPolicy)."""

    operation: Literal["get_table_iam_policy"] = Field(
        "get_table_iam_policy",
        json_schema_extra={
            "const": "get_table_iam_policy",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Get Table IAM Policy",
        },
        title="Get Table IAM Policy",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()


class BigQuerySetTableIamPolicyConfig(BaseModel):
    """Set the IAM policy for a table (tables.setIamPolicy)."""

    operation: Literal["set_table_iam_policy"] = Field(
        "set_table_iam_policy",
        json_schema_extra={
            "const": "set_table_iam_policy",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Set Table IAM Policy",
        },
        title="Set Table IAM Policy",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()
    policy: str = Field(
        ...,
        title="Policy JSON",
        description='IAM policy JSON, e.g. {"bindings":[{"role":"roles/bigquery.dataViewer","members":["user:x@y.com"]}]}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryTestTableIamPermissionsConfig(BaseModel):
    """Test the caller's permissions on a table (tables.testIamPermissions)."""

    operation: Literal["test_table_iam_permissions"] = Field(
        "test_table_iam_permissions",
        json_schema_extra={
            "const": "test_table_iam_permissions",
            "ui:hidden": True,
            "x-category": "Tables",
            "x-is-trigger": False,
            "x-display-name": "Test Table IAM Permissions",
        },
        title="Test Table IAM Permissions",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()
    permissions: str = Field(
        ...,
        title="Permissions",
        description='JSON array of permissions to test, e.g. ["bigquery.tables.get","bigquery.tables.getData"]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BigQueryListRowAccessPoliciesConfig(BaseModel):
    """List row access policies on a table (rowAccessPolicies.list)."""

    operation: Literal["list_row_access_policies"] = Field(
        "list_row_access_policies",
        json_schema_extra={
            "const": "list_row_access_policies",
            "ui:hidden": True,
            "x-category": "Row Access Policies",
            "x-is-trigger": False,
            "x-display-name": "List Row Access Policies",
        },
        title="List Row Access Policies",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Maximum number of policies to return"
    )


class BigQueryGetRowAccessPolicyConfig(BaseModel):
    """Get a single row access policy (rowAccessPolicies.get)."""

    operation: Literal["get_row_access_policy"] = Field(
        "get_row_access_policy",
        json_schema_extra={
            "const": "get_row_access_policy",
            "ui:hidden": True,
            "x-category": "Row Access Policies",
            "x-is-trigger": False,
            "x-display-name": "Get Row Access Policy",
        },
        title="Get Row Access Policy",
    )
    project_id: str = _project_field()
    dataset_id: str = _dataset_field()
    table_id: str = _table_field()
    policy_id: str = Field(
        ..., title="Policy ID", description="The row access policy ID"
    )


# ============================================================================
# Discriminated Union
# ============================================================================


BigQueryConfig = Annotated[
    Union[
        BigQueryRunQueryConfig,
        BigQueryGetQueryResultsConfig,
        BigQueryOnQueryResultsConfig,
        BigQueryInsertJobConfig,
        BigQueryGetJobConfig,
        BigQueryListJobsConfig,
        BigQueryCancelJobConfig,
        BigQueryDeleteJobConfig,
        BigQueryListDatasetsConfig,
        BigQueryGetDatasetConfig,
        BigQueryCreateDatasetConfig,
        BigQueryUpdateDatasetConfig,
        BigQueryPatchDatasetConfig,
        BigQueryDeleteDatasetConfig,
        BigQueryListTablesConfig,
        BigQueryGetTableConfig,
        BigQueryCreateTableConfig,
        BigQueryPatchTableConfig,
        BigQueryUpdateTableConfig,
        BigQueryDeleteTableConfig,
        BigQueryStreamInsertConfig,
        BigQueryListTableDataConfig,
        BigQueryListRoutinesConfig,
        BigQueryGetRoutineConfig,
        BigQueryCreateRoutineConfig,
        BigQueryListModelsConfig,
        BigQueryGetModelConfig,
        BigQueryDeleteModelConfig,
        BigQueryGetServiceAccountConfig,
        BigQueryListProjectsConfig,
        BigQueryUndeleteDatasetConfig,
        BigQueryUpdateRoutineConfig,
        BigQueryDeleteRoutineConfig,
        BigQueryPatchModelConfig,
        BigQueryGetTableIamPolicyConfig,
        BigQuerySetTableIamPolicyConfig,
        BigQueryTestTableIamPermissionsConfig,
        BigQueryListRowAccessPoliciesConfig,
        BigQueryGetRowAccessPolicyConfig,
    ],
    Discriminator("operation"),
]


class BigQueryNodeConfig(NodeConfig[BigQueryConfig, BigQueryCredential]):
    """Full configuration for the BigQuery node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _parse_json(value: Optional[str], field_label: str) -> Any:
    """Parse a JSON string from a config field; raise a clear error if invalid."""
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid JSON in {field_label}: {e}")


def _parse_service_account_json(value: str) -> Dict[str, Any]:
    """Parse and validate a Google service-account JSON key blob."""
    try:
        data = json.loads(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid Service Account JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("Service Account JSON must be a JSON object")
    required = ["type", "client_email", "private_key", "private_key_id", "token_uri"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise ValueError(
            f"Service Account JSON is missing required fields: {', '.join(missing)}"
        )
    if data.get("type") != "service_account":
        raise ValueError("Service Account JSON must have type=service_account")
    return data


async def _mint_service_account_access_token(
    service_account_json: str, scopes: Optional[List[str]] = None
) -> str:
    """Exchange a service-account JWT assertion for an OAuth access token."""
    sa = _parse_service_account_json(service_account_json)
    token_uri = require_google_service_account_token_uri(sa["token_uri"])
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": sa["client_email"],
            "scope": " ".join(scopes or BIGQUERY_OAUTH_SCOPES),
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        },
        sa["private_key"],
        algorithm="RS256",
        headers={"kid": sa["private_key_id"]},
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
            f"Service account token exchange failed: {response.text[:200]}"
        )
    access_token = response.json().get("access_token")
    if not access_token:
        raise ValueError("Service account token exchange returned no access_token")
    return access_token


async def _resolve_access_token_from_credential_data(
    credential_data: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Resolve a usable bearer token from raw (pre-freshened) credential data.

    Used by dropdown loaders, where ``credential_data`` arrives already loaded,
    decrypted and (for OAuth) token-refreshed by the workflow handler."""
    credential_data = credential_data or {}
    if credential_data.get("credential_type") == "bigquery_service_account":
        sa_json = credential_data.get("service_account_json")
        return await _mint_service_account_access_token(sa_json) if sa_json else None
    return credential_data.get("access_token")


def _project_id_from_credential_data(
    credential_data: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Best-effort project id from a service-account key (blank in OAuth)."""
    credential_data = credential_data or {}
    if credential_data.get("credential_type") == "bigquery_service_account":
        try:
            return _parse_service_account_json(
                credential_data.get("service_account_json", "")
            ).get("project_id")
        except ValueError:
            return None
    return None


async def _bigquery_request(
    access_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated BigQuery v2 request and return a structured result."""
    url = f"{BIGQUERY_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if json_body is not None:
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
                    error_obj = err.get("error", {})
                    message = (
                        error_obj.get("message")
                        if isinstance(error_obj, dict)
                        else err.get("message", str(err))
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[BigQueryNode] API error ({action_name}): {message}")
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
            logger.error(f"[BigQueryNode] Request failed ({action_name}): {msg}")
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


class BigQueryNode(WorkflowNode):
    """Google BigQuery automation node."""

    edit_examples = [
        "Run a SQL query against a BigQuery dataset",
        "Stream-insert event rows into a BigQuery table",
        "List all datasets in a project",
        "Create a new dataset for analytics data",
        "Fetch the schema of a table",
    ]

    scope_registry = BIGQUERY_SCOPES
    connection_evidence = ConnectionEvidence(
        field="project_id",
        noun="projects",
    )

    @classmethod
    def get_config_model(cls):
        return BigQueryNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """BigQuery trigger is poll-based: the webhook is a wake-up signal, not
        data. Return None so execute() runs and actually polls the query."""
        if config.get("operation") == "on_query_results":
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
        """Provision the webhook + polling schedule for the BigQuery trigger
        (same pattern as the Gmail/cron triggers)."""
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
        logger.info(
            f"[BigQueryNode] Trigger schedule {schedule} -> cron: {cron_expression}"
        )

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
                    payload={"source": "bigquery_trigger", "node_id": node_id},
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

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns / triggers)."""
        if (credential_data or {}).get("credential_type") == "bigquery_service_account":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="google",
        )

    # ------------------------------------------------------------------
    # Dynamic options (projects / datasets / tables)
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
        """Populate cascading dropdowns. ``credential_data`` arrives already
        loaded, decrypted and (for OAuth) freshened by the workflow handler;
        sibling field values (project_id, dataset_id) come in via ``context``."""
        if field_name not in (
            "project_id",
            "dataset_id",
            "table_id",
            "job_id",
            "routine_id",
            "model_id",
        ):
            return {"options": []}

        access_token = await _resolve_access_token_from_credential_data(credential_data)
        if not access_token:
            return {"options": []}

        ctx = context or {}

        if field_name == "project_id":
            result = await _bigquery_request(
                access_token, "GET", "/projects", action_name="list_projects"
            )
            if result.get("status") != "success":
                return {"options": []}
            projects = (result.get("data") or {}).get("projects") or []
            options = []
            for p in projects:
                pid = p.get("id") or p.get("projectReference", {}).get("projectId")
                name = p.get("friendlyName") or pid
                if pid:
                    options.append({"label": str(name), "value": str(pid)})
            return {"options": options}

        # Non-project dropdowns need a project: prefer the sibling field, else
        # fall back to the service-account key's own project.
        project_id = ctx.get("project_id") or _project_id_from_credential_data(
            credential_data
        )
        if not project_id:
            return {"options": []}

        if field_name == "job_id":
            result = await _bigquery_request(
                access_token,
                "GET",
                f"/projects/{project_id}/jobs",
                params={"maxResults": 100},
                action_name="list_jobs",
            )
            if result.get("status") != "success":
                return {"options": []}
            jobs = (result.get("data") or {}).get("jobs") or []
            options = []
            for j in jobs:
                ref = j.get("jobReference", {})
                jid = ref.get("jobId") or j.get("id")
                if not jid:
                    continue
                state = (j.get("status") or {}).get("state")
                label = f"{jid} ({state})" if state else str(jid)
                options.append({"label": label, "value": str(jid)})
            return {"options": options}

        if field_name == "dataset_id":
            result = await _bigquery_request(
                access_token,
                "GET",
                f"/projects/{project_id}/datasets",
                action_name="list_datasets",
            )
            if result.get("status") != "success":
                return {"options": []}
            datasets = (result.get("data") or {}).get("datasets") or []
            options = []
            for d in datasets:
                ref = d.get("datasetReference", {})
                did = ref.get("datasetId") or d.get("id")
                if did:
                    options.append({"label": str(did), "value": str(did)})
            return {"options": options}

        dataset_id = ctx.get("dataset_id")
        if not dataset_id:
            return {"options": []}

        if field_name == "routine_id":
            result = await _bigquery_request(
                access_token,
                "GET",
                f"/projects/{project_id}/datasets/{dataset_id}/routines",
                action_name="list_routines",
            )
            if result.get("status") != "success":
                return {"options": []}
            routines = (result.get("data") or {}).get("routines") or []
            options = []
            for r in routines:
                ref = r.get("routineReference", {})
                rid = ref.get("routineId")
                if rid:
                    options.append({"label": str(rid), "value": str(rid)})
            return {"options": options}

        if field_name == "model_id":
            result = await _bigquery_request(
                access_token,
                "GET",
                f"/projects/{project_id}/datasets/{dataset_id}/models",
                action_name="list_models",
            )
            if result.get("status") != "success":
                return {"options": []}
            models = (result.get("data") or {}).get("models") or []
            options = []
            for m in models:
                ref = m.get("modelReference", {})
                mid = ref.get("modelId")
                if mid:
                    options.append({"label": str(mid), "value": str(mid)})
            return {"options": options}

        # field_name == "table_id"
        result = await _bigquery_request(
            access_token,
            "GET",
            f"/projects/{project_id}/datasets/{dataset_id}/tables",
            action_name="list_tables",
        )
        if result.get("status") != "success":
            return {"options": []}
        tables = (result.get("data") or {}).get("tables") or []
        options = []
        for t in tables:
            ref = t.get("tableReference", {})
            tid = ref.get("tableId") or t.get("id")
            if tid:
                options.append({"label": str(tid), "value": str(tid)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, BigQueryNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect a Google account in the node's credentials tab."
            )

        access_token = await self._ensure_fresh_token(credentials)

        handlers = {
            "run_query": self._run_query,
            "get_query_results": self._get_query_results,
            "on_query_results": self._on_query_results,
            "insert_job": self._insert_job,
            "get_job": self._get_job,
            "list_jobs": self._list_jobs,
            "cancel_job": self._cancel_job,
            "delete_job": self._delete_job,
            "list_datasets": self._list_datasets,
            "get_dataset": self._get_dataset,
            "create_dataset": self._create_dataset,
            "update_dataset": self._update_dataset,
            "patch_dataset": self._patch_dataset,
            "delete_dataset": self._delete_dataset,
            "list_tables": self._list_tables,
            "get_table": self._get_table,
            "create_table": self._create_table,
            "patch_table": self._patch_table,
            "update_table": self._update_table,
            "delete_table": self._delete_table,
            "stream_insert": self._stream_insert,
            "list_table_data": self._list_table_data,
            "list_routines": self._list_routines,
            "get_routine": self._get_routine,
            "create_routine": self._create_routine,
            "list_models": self._list_models,
            "get_model": self._get_model,
            "delete_model": self._delete_model,
            "get_service_account": self._get_service_account,
            "list_projects": self._list_projects,
            "undelete_dataset": self._undelete_dataset,
            "update_routine": self._update_routine,
            "delete_routine": self._delete_routine,
            "patch_model": self._patch_model,
            "get_table_iam_policy": self._get_table_iam_policy,
            "set_table_iam_policy": self._set_table_iam_policy,
            "test_table_iam_permissions": self._test_table_iam_permissions,
            "list_row_access_policies": self._list_row_access_policies,
            "get_row_access_policy": self._get_row_access_policy,
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

    async def _ensure_fresh_token(self, credentials: BigQueryCredential) -> str:
        """Return a valid Google access token for either supported credential mode."""
        if isinstance(credentials, BigQueryServiceAccountCredential):
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
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    # ------------------------------------------------------------------
    # Handlers — Queries
    # ------------------------------------------------------------------
    async def _run_query(self, c: BigQueryRunQueryConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "query": c.query,
            "useLegacySql": c.use_legacy_sql == "true",
            "maxResults": int(c.max_results) if c.max_results else None,
            "timeoutMs": int(c.timeout_ms) if c.timeout_ms else None,
            "location": c.location,
        }
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/queries",
            json_body=body,
            action_name="run_query",
        )

    async def _get_query_results(
        self, c: BigQueryGetQueryResultsConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "maxResults": c.max_results,
            "pageToken": c.page_token,
            "location": c.location,
        }
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/queries/{c.job_id}",
            params=params,
            action_name="get_query_results",
        )

    # ------------------------------------------------------------------
    # Handlers — Triggers
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_bq_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Decode BigQuery's F/V row envelope into plain {field: value} dicts."""
        fields = [
            f.get("name") for f in (data.get("schema") or {}).get("fields", [])
        ]
        rows: List[Dict[str, Any]] = []
        for row in data.get("rows") or []:
            cells = row.get("f") or []
            rows.append(
                {
                    name: (cells[i].get("v") if i < len(cells) else None)
                    for i, name in enumerate(fields)
                }
            )
        return rows

    async def _on_query_results(
        self, c: BigQueryOnQueryResultsConfig, token: str
    ) -> Dict[str, Any]:
        """Run the user query, emit only rows whose cursor value is greater than
        the last seen value, and advance the persisted cursor.

        The cursor high-water-mark (the highest ``cursor_column`` value emitted
        so far) is stored in durable node state keyed on (workflow_id, node_id),
        so already-seen rows are never re-emitted across polls — config is not
        persisted between headless polls, so it can't hold the cursor. The FIRST
        poll *baselines*: it records the current high-water-mark and emits
        nothing, so enabling the trigger never floods the workflow with the whole
        existing result set — it only fires for rows added afterwards.
        """
        body: Dict[str, Any] = {
            "query": c.query,
            "useLegacySql": c.use_legacy_sql == "true",
            "maxResults": int(c.max_results) if c.max_results else None,
            "location": c.location,
        }
        result = await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/queries",
            json_body=body,
            action_name="on_query_results",
        )
        if result.get("status") != "success":
            return result

        all_rows = self._decode_bq_rows(result.get("data") or {})
        cursor_col = c.cursor_column

        def mutator(state):
            is_first_poll = "last_cursor" not in state
            last_cursor = state.get("last_cursor")

            new_items: List[Dict[str, Any]] = []
            max_cursor = last_cursor
            for row in all_rows:
                cursor_value = row.get(cursor_col)
                if cursor_value is None:
                    continue
                cursor_str = str(cursor_value)
                # String compare: BigQuery scalars arrive as strings; ISO
                # timestamps and zero-padded ids order lexicographically.
                if not is_first_poll and (
                    last_cursor is None or cursor_str > str(last_cursor)
                ):
                    new_items.append(row)
                if max_cursor is None or cursor_str > str(max_cursor):
                    max_cursor = cursor_str

            if max_cursor is None:
                # No usable cursor value this poll (empty result, or the cursor
                # column is null on every row). Stay UNBASELINED — persisting a
                # null high-water-mark would make the next poll treat every row
                # as new (last_cursor is None ⇒ everything qualifies) and flood.
                return None, (new_items, max_cursor)
            if is_first_poll or max_cursor != last_cursor:
                return {"last_cursor": max_cursor}, (new_items, max_cursor)
            return None, (new_items, max_cursor)  # nothing new → no write

        new_items, max_cursor = await self._update_node_state(
            mutator, skip_result=([], None)
        )

        # Drive trigger_produced_no_event: nothing new → executor halts downstream.
        self._poll_emitted_count = len(new_items)

        return {
            "status": "success",
            "operation": "on_query_results",
            "cursor_column": cursor_col,
            "last_cursor": max_cursor,
            "new_count": len(new_items),
            "items": new_items,
            "timestamp": time.time(),
        }

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """Scheduled poll found no new rows -> executor skips downstream nodes.
        Returns False when the node never polled, so it can never wrongly halt."""
        if output.get("operation") != "on_query_results":
            return False
        return getattr(self, "_poll_emitted_count", None) == 0

    # ------------------------------------------------------------------
    # Handlers — Jobs
    # ------------------------------------------------------------------
    async def _insert_job(self, c: BigQueryInsertJobConfig, token: str) -> Dict[str, Any]:
        configuration = _parse_json(c.configuration, "Job Configuration")
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/jobs",
            json_body={"configuration": configuration},
            action_name="insert_job",
        )

    async def _get_job(self, c: BigQueryGetJobConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/jobs/{c.job_id}",
            params={"location": c.location},
            action_name="get_job",
        )

    async def _list_jobs(self, c: BigQueryListJobsConfig, token: str) -> Dict[str, Any]:
        params = {
            "stateFilter": c.state_filter or None,
            "allUsers": "true" if c.all_users == "true" else None,
            "maxResults": c.max_results,
        }
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/jobs",
            params=params,
            action_name="list_jobs",
        )

    async def _cancel_job(self, c: BigQueryCancelJobConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/jobs/{c.job_id}/cancel",
            params={"location": c.location},
            action_name="cancel_job",
        )

    async def _delete_job(self, c: BigQueryDeleteJobConfig, token: str) -> Dict[str, Any]:
        # jobs.delete uses a "/delete" suffix on the resource path (unlike other
        # DELETE endpoints); omitting it 404s.
        return await _bigquery_request(
            token,
            "DELETE",
            f"/projects/{c.project_id}/jobs/{c.job_id}/delete",
            params={"location": c.location},
            action_name="delete_job",
        )

    # ------------------------------------------------------------------
    # Handlers — Datasets
    # ------------------------------------------------------------------
    async def _list_datasets(
        self, c: BigQueryListDatasetsConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets",
            params={"maxResults": c.max_results},
            action_name="list_datasets",
        )

    async def _get_dataset(self, c: BigQueryGetDatasetConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}",
            action_name="get_dataset",
        )

    async def _create_dataset(
        self, c: BigQueryCreateDatasetConfig, token: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "datasetReference": {
                "projectId": c.project_id,
                "datasetId": c.dataset_id,
            },
            "location": c.location,
            "friendlyName": c.friendly_name,
            "description": c.description,
        }
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/datasets",
            json_body=body,
            action_name="create_dataset",
        )

    async def _update_dataset(
        self, c: BigQueryUpdateDatasetConfig, token: str
    ) -> Dict[str, Any]:
        resource = _parse_json(c.resource, "Dataset Resource")
        return await _bigquery_request(
            token,
            "PUT",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}",
            json_body=resource,
            action_name="update_dataset",
        )

    async def _patch_dataset(
        self, c: BigQueryPatchDatasetConfig, token: str
    ) -> Dict[str, Any]:
        resource = _parse_json(c.resource, "Patch JSON")
        return await _bigquery_request(
            token,
            "PATCH",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}",
            json_body=resource,
            action_name="patch_dataset",
        )

    async def _delete_dataset(
        self, c: BigQueryDeleteDatasetConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "DELETE",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}",
            params={"deleteContents": "true" if c.delete_contents == "true" else None},
            action_name="delete_dataset",
        )

    # ------------------------------------------------------------------
    # Handlers — Tables
    # ------------------------------------------------------------------
    async def _list_tables(self, c: BigQueryListTablesConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables",
            params={"maxResults": c.max_results},
            action_name="list_tables",
        )

    async def _get_table(self, c: BigQueryGetTableConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}",
            action_name="get_table",
        )

    async def _create_table(
        self, c: BigQueryCreateTableConfig, token: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "tableReference": {
                "projectId": c.project_id,
                "datasetId": c.dataset_id,
                "tableId": c.table_id,
            },
            "schema": _parse_json(c.output_schema, "Schema"),
            "description": c.description,
        }
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables",
            json_body=body,
            action_name="create_table",
        )

    async def _patch_table(self, c: BigQueryPatchTableConfig, token: str) -> Dict[str, Any]:
        resource = _parse_json(c.resource, "Patch JSON")
        return await _bigquery_request(
            token,
            "PATCH",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}",
            json_body=resource,
            action_name="patch_table",
        )

    async def _update_table(
        self, c: BigQueryUpdateTableConfig, token: str
    ) -> Dict[str, Any]:
        resource = _parse_json(c.resource, "Table Resource")
        return await _bigquery_request(
            token,
            "PUT",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}",
            json_body=resource,
            action_name="update_table",
        )

    async def _delete_table(
        self, c: BigQueryDeleteTableConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "DELETE",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}",
            action_name="delete_table",
        )

    async def _stream_insert(
        self, c: BigQueryStreamInsertConfig, token: str
    ) -> Dict[str, Any]:
        rows = _parse_json(c.rows, "Rows")
        if not isinstance(rows, list):
            raise ValueError("Rows must be a JSON array of row objects")
        body = {
            "rows": [{"json": row} for row in rows],
            "skipInvalidRows": c.skip_invalid_rows == "true",
        }
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}/insertAll",
            json_body=body,
            action_name="stream_insert",
        )

    async def _list_table_data(
        self, c: BigQueryListTableDataConfig, token: str
    ) -> Dict[str, Any]:
        params = {"maxResults": c.max_results, "pageToken": c.page_token}
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}/data",
            params=params,
            action_name="list_table_data",
        )

    # ------------------------------------------------------------------
    # Handlers — Routines
    # ------------------------------------------------------------------
    async def _list_routines(
        self, c: BigQueryListRoutinesConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/routines",
            action_name="list_routines",
        )

    async def _get_routine(self, c: BigQueryGetRoutineConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/routines/{c.routine_id}",
            action_name="get_routine",
        )

    async def _create_routine(
        self, c: BigQueryCreateRoutineConfig, token: str
    ) -> Dict[str, Any]:
        resource = _parse_json(c.resource, "Routine Resource")
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/routines",
            json_body=resource,
            action_name="create_routine",
        )

    # ------------------------------------------------------------------
    # Handlers — Models
    # ------------------------------------------------------------------
    async def _list_models(self, c: BigQueryListModelsConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/models",
            action_name="list_models",
        )

    async def _get_model(self, c: BigQueryGetModelConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/models/{c.model_id}",
            action_name="get_model",
        )

    async def _delete_model(self, c: BigQueryDeleteModelConfig, token: str) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "DELETE",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/models/{c.model_id}",
            action_name="delete_model",
        )

    # ------------------------------------------------------------------
    # Handlers — Project
    # ------------------------------------------------------------------
    async def _get_service_account(
        self, c: BigQueryGetServiceAccountConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/serviceAccount",
            action_name="get_service_account",
        )

    async def _list_projects(
        self, c: BigQueryListProjectsConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            "/projects",
            params={"maxResults": c.max_results},
            action_name="list_projects",
        )

    # ------------------------------------------------------------------
    # Handlers — additional coverage
    # ------------------------------------------------------------------
    async def _undelete_dataset(
        self, c: BigQueryUndeleteDatasetConfig, token: str
    ) -> Dict[str, Any]:
        body = {"deletionTime": c.deletion_time} if c.deletion_time else None
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}:undelete",
            json_body=body,
            action_name="undelete_dataset",
        )

    async def _update_routine(
        self, c: BigQueryUpdateRoutineConfig, token: str
    ) -> Dict[str, Any]:
        resource = _parse_json(c.resource, "Routine Resource")
        return await _bigquery_request(
            token,
            "PUT",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/routines/{c.routine_id}",
            json_body=resource,
            action_name="update_routine",
        )

    async def _delete_routine(
        self, c: BigQueryDeleteRoutineConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "DELETE",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/routines/{c.routine_id}",
            action_name="delete_routine",
        )

    async def _patch_model(self, c: BigQueryPatchModelConfig, token: str) -> Dict[str, Any]:
        resource = _parse_json(c.resource, "Patch JSON")
        return await _bigquery_request(
            token,
            "PATCH",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/models/{c.model_id}",
            json_body=resource,
            action_name="patch_model",
        )

    async def _get_table_iam_policy(
        self, c: BigQueryGetTableIamPolicyConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}:getIamPolicy",
            json_body={},
            action_name="get_table_iam_policy",
        )

    async def _set_table_iam_policy(
        self, c: BigQuerySetTableIamPolicyConfig, token: str
    ) -> Dict[str, Any]:
        policy = _parse_json(c.policy, "Policy JSON")
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}:setIamPolicy",
            json_body={"policy": policy},
            action_name="set_table_iam_policy",
        )

    async def _test_table_iam_permissions(
        self, c: BigQueryTestTableIamPermissionsConfig, token: str
    ) -> Dict[str, Any]:
        permissions = _parse_json(c.permissions, "Permissions")
        if not isinstance(permissions, list):
            raise ValueError("Permissions must be a JSON array of permission strings")
        return await _bigquery_request(
            token,
            "POST",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}:testIamPermissions",
            json_body={"permissions": permissions},
            action_name="test_table_iam_permissions",
        )

    async def _list_row_access_policies(
        self, c: BigQueryListRowAccessPoliciesConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}/rowAccessPolicies",
            params={"pageSize": c.page_size},
            action_name="list_row_access_policies",
        )

    async def _get_row_access_policy(
        self, c: BigQueryGetRowAccessPolicyConfig, token: str
    ) -> Dict[str, Any]:
        return await _bigquery_request(
            token,
            "GET",
            f"/projects/{c.project_id}/datasets/{c.dataset_id}/tables/{c.table_id}/rowAccessPolicies/{c.policy_id}",
            action_name="get_row_access_policy",
        )
